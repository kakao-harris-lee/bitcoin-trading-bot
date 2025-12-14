#!/usr/bin/env python3
"""v35 entry frequency sensitivity check.

목표:
- v35가 '너무 방어적'으로 거래가 적을 때, entry 쪽 임계값을 얼마나 완화하면
  거래 횟수/성과가 어떻게 변하는지 빠르게 확인.

주의:
- 이 스크립트는 연구/분석용입니다.
- production config_optimized.json 자체는 수정하지 않습니다.

실행:
  cd strategies/v35_optimized
  PYTHONPATH="../v34_supreme/v34_supreme:$PYTHONPATH" python quick_entry_sensitivity.py
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from typing import Dict, List

import numpy as np
import pandas as pd

# Ensure project root is on sys.path (run from strategies/v35_optimized)
_current_dir = os.path.dirname(os.path.abspath(__file__))
_strategies_dir = os.path.dirname(_current_dir)
_project_root = os.path.dirname(_strategies_dir)
sys.path.insert(0, _project_root)
sys.path.insert(0, _current_dir)

from core.data_loader import DataLoader
from core.market_analyzer import MarketAnalyzer
from strategy import V35OptimizedStrategy


@dataclass
class YearResult:
    year: str
    total_return: float
    total_trades: int
    sharpe: float
    mdd: float


class V35BacktesterMini:
    def __init__(self, initial_capital: float, fee_rate: float = 0.0005, slippage: float = 0.0002):
        self.initial_capital = initial_capital
        self.fee_rate = fee_rate
        self.slippage = slippage

    def run(self, df: pd.DataFrame, strategy: V35OptimizedStrategy) -> Dict:
        capital = self.initial_capital
        position = 0.0
        trades = []
        equity_curve = []

        for i in range(30, len(df)):
            sig = strategy.execute(df, i)
            row = df.iloc[i]

            if sig["action"] == "buy" and position == 0:
                fraction = sig.get("fraction", 0.5)
                buy_amount = capital * fraction
                buy_price = row["close"] * (1 + self.slippage)
                fee = buy_amount * self.fee_rate
                shares = (buy_amount - fee) / buy_price
                if shares > 0:
                    position = shares
                    capital -= buy_amount
                    trades.append(("buy", buy_price))

            elif sig["action"] == "sell" and position > 0:
                sell_fraction = sig.get("fraction", 1.0)
                sell_shares = position * sell_fraction
                sell_price = row["close"] * (1 - self.slippage)
                proceeds = sell_shares * sell_price * (1 - self.fee_rate)
                capital += proceeds
                position -= sell_shares
                trades.append(("sell", sell_price))

            equity_curve.append(capital + (position * row["close"] if position > 0 else 0.0))

        if position > 0:
            capital += position * df.iloc[-1]["close"] * (1 - self.slippage - self.fee_rate)

        equity = pd.Series(equity_curve)
        total_return = (capital - self.initial_capital) / self.initial_capital * 100
        rets = equity.pct_change().dropna()
        sharpe = rets.mean() / rets.std() * np.sqrt(252) if len(rets) and rets.std() > 0 else 0.0
        peak = equity.cummax()
        dd = (equity - peak) / peak * 100
        mdd = float(dd.min()) if len(dd) else 0.0

        # round-trip trades count (buy->sell pairs)
        total_trades = min(sum(1 for t in trades if t[0] == "buy"), sum(1 for t in trades if t[0] == "sell"))

        return {
            "total_return": total_return,
            "total_trades": total_trades,
            "sharpe": sharpe,
            "mdd": mdd,
        }


def _load_merged_config() -> Dict:
    with open("config_optimized.json") as f:
        cfg = json.load(f)

    merged: Dict = {}
    for k, v in cfg.items():
        if isinstance(v, dict):
            merged.update(v)
        else:
            merged[k] = v
    return merged


def _load_year_df(year: str) -> pd.DataFrame:
    # backtest.py와 동일한 상대 경로 유지
    with DataLoader("../../upbit_bitcoin.db") as loader:
        df = loader.load_timeframe(
            "day",
            start_date=f"{year}-01-01",
            end_date=f"{year}-12-31",
        )
    df = MarketAnalyzer.add_indicators(df, indicators=["rsi", "macd", "mfi", "adx", "atr", "bb", "stoch"])
    return df


def _run_variant(name: str, base: Dict, overrides: Dict, years: List[str]) -> List[YearResult]:
    cfg = dict(base)
    cfg.update(overrides)

    bt = V35BacktesterMini(
        initial_capital=cfg.get("initial_capital", 10_000_000),
        fee_rate=cfg.get("fee_rate", 0.0005),
        slippage=cfg.get("slippage", 0.0002),
    )

    out: List[YearResult] = []
    for y in years:
        df = _load_year_df(y)
        strat = V35OptimizedStrategy(cfg)
        r = bt.run(df, strat)
        out.append(YearResult(year=y, total_return=r["total_return"], total_trades=r["total_trades"], sharpe=r["sharpe"], mdd=r["mdd"]))

    avg_trades = sum(r.total_trades for r in out) / len(out)
    avg_ret = sum(r.total_return for r in out) / len(out)

    print("\n" + "=" * 90)
    print(f"{name}")
    print("Overrides:", overrides)
    print("=" * 90)
    print(f"{'Year':<6} {'Return':>10} {'Trades':>8} {'Sharpe':>8} {'MDD':>10}")
    print("-" * 90)
    for r in out:
        print(f"{r.year:<6} {r.total_return:>+9.2f}% {r.total_trades:>8} {r.sharpe:>8.2f} {r.mdd:>9.2f}%")
    print("-" * 90)
    print(f"Avg   {avg_ret:>+9.2f}% {avg_trades:>8.1f} {'':>8} {'':>10}")

    return out


def main() -> None:
    base = _load_merged_config()
    years = ["2020", "2021", "2022", "2023", "2024"]

    # Baseline
    _run_variant(
        name="Baseline (config_optimized.json)",
        base=base,
        overrides={},
        years=years,
    )

    # Variant D: enable market classifier overrides (from merged config)
    _run_variant(
        name="Variant D: use market classifier overrides (opt-in)",
        base=base,
        overrides={
            "use_market_classifier_overrides": True,
        },
        years=years,
    )

    # Variant A: momentum RSI 완화 (거래 빈도 증가 기대)
    _run_variant(
        name="Variant A: lower momentum RSI thresholds",
        base=base,
        overrides={
            "momentum_rsi_bull_strong": max(40, int(base.get("momentum_rsi_bull_strong", 57)) - 4),
            "momentum_rsi_bull_moderate": max(40, int(base.get("momentum_rsi_bull_moderate", 55)) - 4),
        },
        years=years,
    )

    # Variant B: breakout/volume gate 완화
    _run_variant(
        name="Variant B: easier breakout (threshold/volume)",
        base=base,
        overrides={
            "breakout_threshold": float(base.get("breakout_threshold", 0.007)) * 0.7,
            "breakout_volume_mult": float(base.get("breakout_volume_mult", 1.23)) * 0.8,
        },
        years=years,
    )

    # Variant C: range 진입 완화 (rsi, support zone)
    _run_variant(
        name="Variant C: easier range entries",
        base=base,
        overrides={
            "range_support_zone": min(0.25, float(base.get("range_support_zone", 0.14)) * 1.4),
            "range_rsi_oversold": min(45, int(base.get("range_rsi_oversold", 38)) + 4),
        },
        years=years,
    )


if __name__ == "__main__":
    main()
