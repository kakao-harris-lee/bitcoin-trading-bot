#!/usr/bin/env python3
"""Operational (Compose-style) routed portfolio backtest.

Implements the user's requested A+B:
A) Run separate full-period backtests:
   - Upbit: router_live (BULL->v35, SIDEWAYS->sideways_v2, BEAR->no long entry)
   - Binance: short_v1, but only when daily regime is BEAR (stickiness until exit)

B) Aggregate both equity curves into a combined portfolio (KRW):
   combined_equity = upbit_krw_equity + (binance_usdt_equity * fx_krw_per_usdt)

Notes / assumptions:
- Binance 4H price series is proxied by the DB's minute240 (Upbit BTC/KRW candles). This keeps the
  research self-contained without external CSV/API. Regime gating is the main objective here.
- Short backtest uses a minimal margin-style model (locks margin, realizes PnL on close).

Run:
  python trading/scripts/backtest_operational_portfolio.py --by-year
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

import numpy as np
import pandas as pd

import sys

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.backtester import Backtester
from core.data_loader import DataLoader

from trading.strategy.regime_router import RegimeRouter as LiveRegimeRouter
from trading.strategy.regime_router import _calc_adx as _live_calc_adx
from trading.strategy.regime_router import _calc_mfi as _live_calc_mfi

from scripts.backtest_strategies import RegimeRouterLiveAdapter, ShortV1StrategyAdapter


@dataclass
class PortfolioBacktestConfig:
    db_path: Path
    start_date: Optional[str]
    end_date: Optional[str]
    upbit_capital_krw: float
    binance_capital_usdt: float
    fx_krw_per_usdt: float


def _to_ymd(ts: pd.Timestamp) -> str:
    return ts.strftime("%Y-%m-%d")


def _coerce_date_str(date_str: str) -> str:
    return pd.Timestamp(date_str).strftime("%Y-%m-%d")


def _daily_regime_series(df_day: pd.DataFrame, router: LiveRegimeRouter) -> pd.Series:
    df = df_day.copy()
    df["mfi"] = _live_calc_mfi(df, period=router.mfi_period)
    df["adx"] = _live_calc_adx(df, period=router.adx_period)

    market_state = df.apply(
        lambda r: router.classify_from_values(mfi=float(r["mfi"]), adx=float(r["adx"])),
        axis=1,
    )

    def to_regime(ms: str) -> str:
        if ms.startswith("BULL"):
            return "BULL"
        if ms.startswith("SIDEWAYS"):
            return "SIDEWAYS"
        if ms.startswith("BEAR"):
            return "BEAR"
        return "UNKNOWN"

    regime = market_state.map(to_regime)
    idx = pd.to_datetime(df["timestamp"]).dt.normalize()
    regime.index = idx
    return regime


def _daily_market_state_series(df_day: pd.DataFrame, router: LiveRegimeRouter) -> pd.Series:
    """Daily market_state series (BULL_*/SIDEWAYS_*/BEAR_*), aligned to normalized day index."""
    df = df_day.copy()
    df["mfi"] = _live_calc_mfi(df, period=router.mfi_period)
    df["adx"] = _live_calc_adx(df, period=router.adx_period)

    market_state = df.apply(
        lambda r: router.classify_from_values(mfi=float(r["mfi"]), adx=float(r["adx"])),
        axis=1,
    )

    idx = pd.to_datetime(df["timestamp"]).dt.normalize()
    market_state.index = idx
    return market_state


def _regime_lookup(regime_by_day: pd.Series, ts: pd.Timestamp) -> str:
    """Lookup regime for an intraday timestamp; use the latest available daily regime <= ts.date."""
    day = ts.normalize()
    if day in regime_by_day.index:
        return str(regime_by_day.loc[day])

    # fallback to previous known day
    pos = regime_by_day.index.searchsorted(day, side="right") - 1
    if pos < 0:
        return "UNKNOWN"
    return str(regime_by_day.iloc[pos])


class BearOnlyShortWrapper:
    """Gate ShortV1StrategyAdapter by daily BEAR regime, with stickiness until exit."""

    def __init__(
        self,
        regime_by_day: pd.Series,
        market_state_by_day: Optional[pd.Series] = None,
        gate_mode: str = "bear_only",
        fraction_mult: float = 1.0,
    ):
        self._regime_by_day = regime_by_day
        self._market_state_by_day = market_state_by_day
        self.gate_mode = gate_mode
        self.fraction_mult = float(fraction_mult)
        self.short = ShortV1StrategyAdapter()

    @property
    def in_position(self) -> bool:
        return bool(getattr(self.short, "in_position", False))

    def __call__(self, df: pd.DataFrame, i: int, params: Dict) -> Dict:
        if i < 200:
            return {"action": "hold"}

        ts = pd.Timestamp(df.iloc[i]["timestamp"])
        regime = _regime_lookup(self._regime_by_day, ts)

        market_state = None
        if self._market_state_by_day is not None:
            market_state = _regime_lookup(self._market_state_by_day, ts)

        # stickiness: if already short, allow exits regardless of regime
        if self.in_position:
            return self.short(df, i, params)

        allow = False
        if self.gate_mode == "bear_only":
            allow = (regime == "BEAR")
        elif self.gate_mode == "bear_or_sideways_bear":
            allow = (regime == "BEAR") or (isinstance(market_state, str) and market_state == "SIDEWAYS_BEAR")
        elif self.gate_mode == "bear_strong_only":
            allow = isinstance(market_state, str) and market_state == "BEAR_STRONG"
        elif self.gate_mode == "bear_strong_or_sideways_bear":
            allow = isinstance(market_state, str) and market_state in {"BEAR_STRONG", "SIDEWAYS_BEAR"}
        else:
            allow = (regime == "BEAR")

        if not allow:
            return {"action": "hold", "reason": f"BEAR_GATE_HOLD_{regime}"}

        sig = self.short(df, i, params)
        if sig.get("action") == "buy":
            sig["fraction"] = max(0.0, min(1.0, float(sig.get("fraction", 1.0)) * self.fraction_mult))
            sig.setdefault("metadata", {})
            sig["metadata"].update({"gate_regime": regime})
        return sig


class ShortMarginBacktester:
    """Minimal short backtester (margin-locked) compatible with ShortV1StrategyAdapter buy/sell signals."""

    def __init__(
        self,
        initial_capital: float,
        fee_rate: float = 0.0005,
        slippage: float = 0.0002,
        min_order_amount: float = 10.0,
    ):
        self.initial_capital = float(initial_capital)
        self.fee_rate = float(fee_rate)
        self.slippage = float(slippage)
        self.min_order_amount = float(min_order_amount)

        self.cash = self.initial_capital
        self.in_short = False
        self.entry_price = 0.0
        self.size = 0.0  # BTC
        self.margin = 0.0
        self.equity_curve = []
        self.trades = []

    def reset(self):
        self.cash = self.initial_capital
        self.in_short = False
        self.entry_price = 0.0
        self.size = 0.0
        self.margin = 0.0
        self.equity_curve = []
        self.trades = []

    def _equity(self, price: float) -> float:
        if not self.in_short:
            return self.cash
        current_exec = price * (1 + self.slippage)
        unrealized = (self.entry_price - current_exec) * self.size
        return self.cash + self.margin + unrealized

    def run(self, df: pd.DataFrame, strategy_func, strategy_params: Optional[Dict] = None) -> Dict:
        self.reset()
        strategy_params = strategy_params or {}

        for i in range(len(df)):
            row = df.iloc[i]
            ts = row["timestamp"]
            price = float(row["close"])

            sig = strategy_func(df, i, strategy_params)
            action = sig.get("action", "hold")
            fraction = float(sig.get("fraction", 1.0))

            if action == "buy":
                self._open_short(ts, price, fraction)
            elif action == "sell":
                self._close_short(ts, price)

            self.equity_curve.append(
                {
                    "timestamp": ts,
                    "cash": self.cash,
                    "margin": self.margin,
                    "total_equity": self._equity(price),
                }
            )

        # force close at end
        if self.in_short:
            last = df.iloc[-1]
            self._close_short(last["timestamp"], float(last["close"]))

        eq = pd.DataFrame(self.equity_curve)
        final_equity = float(eq["total_equity"].iloc[-1]) if not eq.empty else self.cash
        total_return = ((final_equity - self.initial_capital) / self.initial_capital) * 100

        closed_trades = [t for t in self.trades if t.get("exit_time") is not None]
        wins = [t for t in closed_trades if t.get("pnl", 0.0) > 0]
        losses = [t for t in closed_trades if t.get("pnl", 0.0) <= 0]

        win_rate = (len(wins) / len(closed_trades)) if closed_trades else 0.0
        avg_profit = float(np.mean([t["pnl"] for t in wins])) if wins else 0.0
        avg_loss = float(abs(np.mean([t["pnl"] for t in losses]))) if losses else 0.0
        profit_factor = (sum(t["pnl"] for t in wins) / abs(sum(t["pnl"] for t in losses))) if losses else 0.0

        return {
            "initial_capital": self.initial_capital,
            "final_capital": final_equity,
            "total_return": total_return,
            "total_trades": len(closed_trades),
            "win_rate": win_rate,
            "avg_profit": avg_profit,
            "avg_loss": avg_loss,
            "profit_factor": profit_factor,
            "equity_curve": eq,
            "trades": closed_trades,
        }

    def _open_short(self, ts: datetime, price: float, fraction: float):
        if self.in_short:
            return

        margin = self.cash * fraction
        if margin < self.min_order_amount:
            return

        entry_exec = price * (1 - self.slippage)  # sell
        size = margin / entry_exec

        entry_fee = (size * entry_exec) * self.fee_rate
        total_cost = margin + entry_fee
        if total_cost > self.cash:
            return

        self.cash -= total_cost
        self.margin = margin
        self.size = size
        self.entry_price = entry_exec
        self.in_short = True

        self.trades.append({
            "entry_time": ts,
            "entry_price": entry_exec,
            "size": size,
            "margin": margin,
            "exit_time": None,
            "exit_price": None,
            "pnl": None,
        })

    def _close_short(self, ts: datetime, price: float):
        if not self.in_short:
            return

        exit_exec = price * (1 + self.slippage)  # buy
        exit_fee = (self.size * exit_exec) * self.fee_rate

        pnl = (self.entry_price - exit_exec) * self.size

        # release margin + pnl, minus fee
        self.cash += self.margin + pnl - exit_fee

        # mark trade
        for t in self.trades:
            if t.get("exit_time") is None:
                t["exit_time"] = ts
                t["exit_price"] = exit_exec
                t["pnl"] = pnl - exit_fee
                break

        self.in_short = False
        self.entry_price = 0.0
        self.size = 0.0
        self.margin = 0.0


def _compute_metrics(equity_curve: pd.DataFrame) -> Dict[str, float]:
    if equity_curve.empty:
        return {"cagr": 0.0, "mdd": 0.0, "sharpe": 0.0}

    eq = equity_curve.copy()
    eq = eq.sort_values("timestamp")

    start = pd.Timestamp(eq["timestamp"].iloc[0])
    end = pd.Timestamp(eq["timestamp"].iloc[-1])
    years = (end - start).days / 365.25

    initial = float(eq["total_equity"].iloc[0])
    final = float(eq["total_equity"].iloc[-1])

    cagr = ((final / initial) ** (1 / years) - 1) * 100 if years > 0 and initial > 0 else 0.0

    peak = eq["total_equity"].cummax()
    dd = (eq["total_equity"] - peak) / peak
    mdd = float(dd.min() * 100)

    rets = eq["total_equity"].pct_change().dropna()
    sharpe = 0.0
    if len(rets) > 5 and rets.std() != 0:
        # scale: if timestamps are daily, sqrt(252) is fine; if 4h, still indicative.
        sharpe = float((rets.mean() / rets.std()) * np.sqrt(252))

    return {"cagr": float(cagr), "mdd": float(mdd), "sharpe": float(sharpe)}


def _to_daily_last(equity_curve: pd.DataFrame) -> pd.DataFrame:
    df = equity_curve.copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df = df.sort_values("timestamp")
    df = df.set_index("timestamp")
    daily = df.resample("1D").last().dropna(subset=["total_equity"]).reset_index()
    return daily[["timestamp", "total_equity"]]


def _print_summary(title: str, res: Dict, metrics: Dict[str, float]):
    print("\n" + "=" * 80)
    print(title)
    print("=" * 80)
    print(f"initial: {res['initial_capital']:,.2f}")
    print(f"final:   {res['final_capital']:,.2f}")
    print(f"return:  {res['total_return']:+.2f}%")
    print(f"trades:  {res.get('total_trades', 0)}")
    if res.get("total_trades", 0):
        print(f"win%:    {res.get('win_rate', 0.0) * 100:.1f}%")
        print(f"pf:      {res.get('profit_factor', 0.0):.2f}")
    print(f"CAGR:    {metrics.get('cagr', 0.0):+.2f}%")
    print(f"MDD:     {metrics.get('mdd', 0.0):.2f}%")
    print(f"Sharpe:  {metrics.get('sharpe', 0.0):+.2f}")


def _load_candidate_from_json(path: str, index: int = 0) -> Dict:
    p = Path(path)
    with p.open("r", encoding="utf-8") as f:
        data = json.load(f)

    if isinstance(data, dict) and "candidate" in data:
        return dict(data["candidate"])

    results = data.get("results") if isinstance(data, dict) else None
    if not isinstance(results, list) or not results:
        raise ValueError(f"Invalid candidate JSON format: {path}")

    idx = int(index)
    if idx < 0:
        idx = len(results) + idx
    idx = max(0, min(len(results) - 1, idx))

    entry = results[idx]
    if not isinstance(entry, dict) or "candidate" not in entry:
        raise ValueError(f"Invalid results[{idx}] format in {path}")
    return dict(entry["candidate"])


def _yearly_table(equity_curve_daily: pd.DataFrame) -> pd.DataFrame:
    df = equity_curve_daily.copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df["year"] = df["timestamp"].dt.year
    years = []
    for y, grp in df.groupby("year"):
        start = float(grp["total_equity"].iloc[0])
        end = float(grp["total_equity"].iloc[-1])
        ret = ((end - start) / start) * 100 if start > 0 else 0.0
        peak = grp["total_equity"].cummax()
        dd = (grp["total_equity"] - peak) / peak
        mdd = float(dd.min() * 100)
        years.append({"year": int(y), "ret_pct": float(ret), "mdd_pct": float(mdd)})
    return pd.DataFrame(years).sort_values("year")


def main():
    p = argparse.ArgumentParser(description="Operational routed portfolio backtest (A+B)")
    p.add_argument("--db-path", default=str(PROJECT_ROOT / "data" / "upbit_bitcoin.db"))
    p.add_argument("--start-date", default=None)
    p.add_argument("--end-date", default=None)
    p.add_argument("--upbit-capital-krw", type=float, default=10_000_000)
    p.add_argument("--binance-capital-usdt", type=float, default=10_000)
    p.add_argument("--fx", type=float, default=1300.0, help="KRW per 1 USDT for aggregation")
    p.add_argument("--by-year", action="store_true")
    p.add_argument("--candidate-json", type=str, default=None, help="tune_operational_router 결과 JSON 경로")
    p.add_argument("--candidate-index", type=int, default=0, help="candidate index (기본: 0)")

    args = p.parse_args()
    cfg = PortfolioBacktestConfig(
        db_path=Path(args.db_path),
        start_date=_coerce_date_str(args.start_date) if args.start_date else None,
        end_date=_coerce_date_str(args.end_date) if args.end_date else None,
        upbit_capital_krw=float(args.upbit_capital_krw),
        binance_capital_usdt=float(args.binance_capital_usdt),
        fx_krw_per_usdt=float(args.fx),
    )

    # Default tuning knobs for router_live
    router_config = {
        "mfi_bull": 52.0,
        "mfi_bear": 48.0,
        "adx_strong": 25.0,
        "adx_trend": 20.0,
        "adx_weak": 15.0,
    }
    bull_policy = "v35"
    bull_hold_fraction = 1.0
    sideways_policy = "sideways_v2"
    sideways_bear_policy = None
    bear_moderate_policy = None
    bear_strong_policy = None
    sideways_v2_config = None
    v35_fraction_mult = 1.0
    sideways_fraction_mult = 1.0
    binance_gate_mode = "bear_only"
    binance_fraction_mult = 1.0

    if args.candidate_json:
        cand = _load_candidate_from_json(args.candidate_json, args.candidate_index)
        router_config.update(dict(cand.get("router_config") or {}))
        bull_policy = str(cand.get("bull_policy", bull_policy))
        bull_hold_fraction = float(cand.get("bull_hold_fraction", bull_hold_fraction))
        sideways_policy = str(cand.get("sideways_policy", sideways_policy))
        sideways_bear_policy = cand.get("sideways_bear_policy")
        bear_moderate_policy = cand.get("bear_moderate_policy")
        bear_strong_policy = cand.get("bear_strong_policy")
        sideways_v2_config = cand.get("sideways_v2_config")
        v35_fraction_mult = float(cand.get("v35_fraction_mult", v35_fraction_mult))
        sideways_fraction_mult = float(cand.get("sideways_fraction_mult", sideways_fraction_mult))
        binance_gate_mode = str(cand.get("binance_gate_mode", binance_gate_mode))
        binance_fraction_mult = float(cand.get("binance_fraction_mult", binance_fraction_mult))

    with DataLoader(str(cfg.db_path)) as loader:
        day_start, day_end = loader.get_date_range("day")
        h4_start, h4_end = loader.get_date_range("minute240")

    day_start = _coerce_date_str(day_start)
    day_end = _coerce_date_str(day_end)
    h4_start = _coerce_date_str(h4_start)
    h4_end = _coerce_date_str(h4_end)

    start = cfg.start_date or day_start
    end = cfg.end_date or day_end

    # A) Upbit full-period (day)
    with DataLoader(str(cfg.db_path)) as loader:
        df_day = loader.load_timeframe("day", start, end)
    upbit_strategy = RegimeRouterLiveAdapter(
        timeframe="day",
        router_config=router_config,
        bull_policy=bull_policy,
        bull_hold_fraction=bull_hold_fraction,
        sideways_policy=sideways_policy,
        sideways_bear_policy=sideways_bear_policy,
        bear_moderate_policy=bear_moderate_policy,
        bear_strong_policy=bear_strong_policy,
        v35_fraction_mult=v35_fraction_mult,
        sideways_fraction_mult=sideways_fraction_mult,
        sideways_v2_config=sideways_v2_config,
    )
    upbit_bt = Backtester(initial_capital=cfg.upbit_capital_krw, fee_rate=0.0005, slippage=0.0002)
    upbit_res = upbit_bt.run(df_day, upbit_strategy, {})
    upbit_metrics = _compute_metrics(upbit_res["equity_curve"])
    _print_summary("[A] Upbit (KRW) - router_live on DAY", upbit_res, upbit_metrics)

    # Build daily regime schedule (for Binance gating)
    router = LiveRegimeRouter(
        mfi_bull=float(router_config["mfi_bull"]),
        mfi_bear=float(router_config["mfi_bear"]),
        adx_strong=float(router_config["adx_strong"]),
        adx_trend=float(router_config["adx_trend"]),
        adx_weak=float(router_config["adx_weak"]),
    )
    regime_by_day = _daily_regime_series(df_day, router)
    market_state_by_day = _daily_market_state_series(df_day, router)

    # A) Binance full-period (4H) but only when BEAR regime (stickiness)
    # Use intersection period by default for minute240, but keep user range clamp
    start_h4 = max(pd.Timestamp(start), pd.Timestamp(h4_start)).strftime("%Y-%m-%d")
    end_h4 = min(pd.Timestamp(end), pd.Timestamp(h4_end)).strftime("%Y-%m-%d")

    with DataLoader(str(cfg.db_path)) as loader:
        df_h4 = loader.load_timeframe("minute240", start_h4, end_h4)

    gated_short = BearOnlyShortWrapper(
        regime_by_day=regime_by_day,
        market_state_by_day=market_state_by_day,
        gate_mode=binance_gate_mode,
        fraction_mult=binance_fraction_mult,
    )
    short_bt = ShortMarginBacktester(initial_capital=cfg.binance_capital_usdt, fee_rate=0.0005, slippage=0.0002)
    binance_res = short_bt.run(df_h4, gated_short, {})
    binance_metrics = _compute_metrics(binance_res["equity_curve"])
    _print_summary("[A] Binance (USDT) - short_v1 on 4H, gated to BEAR", binance_res, binance_metrics)

    # B) Combined portfolio aggregation (daily)
    upbit_daily = _to_daily_last(upbit_res["equity_curve"])
    binance_daily_usdt = _to_daily_last(binance_res["equity_curve"])

    combined = upbit_daily.merge(binance_daily_usdt, on="timestamp", how="inner", suffixes=("_upbit", "_binance"))
    combined["total_equity"] = combined["total_equity_upbit"] + (combined["total_equity_binance"] * cfg.fx_krw_per_usdt)
    combined = combined[["timestamp", "total_equity"]]

    combined_res = {
        "initial_capital": float(combined["total_equity"].iloc[0]),
        "final_capital": float(combined["total_equity"].iloc[-1]),
        "total_return": ((float(combined["total_equity"].iloc[-1]) - float(combined["total_equity"].iloc[0])) / float(combined["total_equity"].iloc[0])) * 100,
        "total_trades": upbit_res.get("total_trades", 0) + binance_res.get("total_trades", 0),
        "equity_curve": combined,
    }
    combined_metrics = _compute_metrics(combined)
    _print_summary("[B] Combined Portfolio (KRW) - Upbit router_live + Binance BEAR short", combined_res, combined_metrics)

    if args.by_year:
        print("\n" + "=" * 80)
        print("Year-by-year (Combined, KRW)")
        print("=" * 80)
        yt = _yearly_table(combined)
        if yt.empty:
            print("(no data)")
        else:
            print(f"{'YEAR':<6} {'RET%':>10} {'MDD%':>10}")
            print("-" * 30)
            for _, r in yt.iterrows():
                print(f"{int(r['year']):<6} {float(r['ret_pct']):>10.2f} {float(r['mdd_pct']):>10.2f}")


if __name__ == "__main__":
    main()
