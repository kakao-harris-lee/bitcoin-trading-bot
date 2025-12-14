#!/usr/bin/env python3
"""v35 Optimized 4H Backtest

목표:
- v35를 4H(minute240)로 내려서 거래 빈도/성과를 확인
- (옵션) SIDEWAYS_DOWN 보조 진입 로직(enable_sideways_down_entry) 영향도 확인

실행 예:
  cd strategies/v35_optimized
  python backtest_4h.py --year 2024
  python backtest_4h.py --year 2024 --enable-sideways-down
  python backtest_4h.py --all-years --enable-sideways-down

주의:
- core/market_analyzer.py 는 TA-Lib 미설치 시 지표를 추가하지 않습니다.
  지표가 없으면 v35가 KeyError를 낼 수 있으므로, 감지 후 친절한 오류를 냅니다.
"""

from __future__ import annotations

import json
import sys
import os
from typing import Dict

import pandas as pd

# Ensure project root is on sys.path
_current_dir = os.path.dirname(os.path.abspath(__file__))
_strategies_dir = os.path.dirname(_current_dir)
_project_root = os.path.dirname(_strategies_dir)
sys.path.insert(0, _project_root)
sys.path.insert(0, _current_dir)

from core.data_loader import DataLoader
from core.market_analyzer import MarketAnalyzer
from strategy import V35OptimizedStrategy


class V35Backtester4H:
    def __init__(self, initial_capital: float, fee_rate: float = 0.0005, slippage: float = 0.0002):
        self.initial_capital = initial_capital
        self.fee_rate = fee_rate
        self.slippage = slippage

        self.capital = initial_capital
        self.position = 0.0
        self.trades = []
        self.equity_curve = []

    def run(self, df: pd.DataFrame, strategy: V35OptimizedStrategy) -> Dict:
        self.capital = self.initial_capital
        self.position = 0.0
        self.trades = []
        self.equity_curve = []

        for i in range(30, len(df)):
            signal = strategy.execute(df, i)
            row = df.iloc[i]

            if signal["action"] == "buy" and self.position == 0:
                fraction = signal.get("fraction", 0.5)
                buy_amount = self.capital * fraction
                buy_price = row["close"] * (1 + self.slippage)
                fee = buy_amount * self.fee_rate
                shares = (buy_amount - fee) / buy_price

                if shares > 0:
                    self.position = shares
                    self.capital -= buy_amount
                    self.trades.append(
                        {
                            "type": "buy",
                            "time": row.get("timestamp", row.name),
                            "price": buy_price,
                            "shares": shares,
                            "reason": signal.get("reason", "UNKNOWN"),
                            "strategy": signal.get("strategy", "unknown"),
                        }
                    )

            elif signal["action"] == "sell" and self.position > 0:
                sell_fraction = signal.get("fraction", 1.0)
                sell_shares = self.position * sell_fraction
                sell_price = row["close"] * (1 - self.slippage)
                proceeds = sell_shares * sell_price * (1 - self.fee_rate)

                self.capital += proceeds
                self.position -= sell_shares

                self.trades.append(
                    {
                        "type": "sell",
                        "time": row.get("timestamp", row.name),
                        "price": sell_price,
                        "shares": sell_shares,
                        "fraction": sell_fraction,
                        "reason": signal.get("reason", "UNKNOWN"),
                    }
                )

            current_equity = self.capital + (self.position * row["close"] if self.position > 0 else 0.0)
            self.equity_curve.append(current_equity)

        if self.position > 0:
            self.capital += self.position * df.iloc[-1]["close"] * (1 - self.slippage - self.fee_rate)
            self.position = 0.0

        # round-trip count
        buy_trades = [t for t in self.trades if t["type"] == "buy"]
        entries = len(buy_trades)
        entries_by_strategy: Dict[str, int] = {}
        for t in buy_trades:
            strat = t.get("strategy", "unknown") or "unknown"
            entries_by_strategy[strat] = entries_by_strategy.get(strat, 0) + 1

        return {
            "initial_capital": self.initial_capital,
            "final_capital": self.capital,
            "total_return": (self.capital - self.initial_capital) / self.initial_capital * 100,
            "total_trades": entries,
            "entries_by_strategy": entries_by_strategy,
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


def _assert_indicators(df: pd.DataFrame) -> None:
    required = ["rsi", "macd", "macd_signal", "mfi", "adx", "bb_lower", "stoch_k"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise RuntimeError(
            "Missing indicators: "
            + ", ".join(missing)
            + ". TA-Lib이 설치되어 있지 않으면 core/market_analyzer.py가 지표를 추가하지 않습니다. "
            + "(macOS) brew install ta-lib && pip install TA-Lib"
        )


def run_year(year: str, config: Dict) -> Dict:
    with DataLoader("../../upbit_bitcoin.db") as loader:
        df = loader.load_timeframe(
            "minute240",
            start_date=f"{year}-01-01",
            end_date=f"{year}-12-31" if year != "2025" else "2025-12-11",
        )

    df = MarketAnalyzer.add_indicators(df, indicators=["rsi", "macd", "mfi", "adx", "atr", "bb", "stoch"])
    _assert_indicators(df)

    strategy = V35OptimizedStrategy(config)

    # Diagnostics: market state distribution (to tune SIDEWAYS_DOWN frequency)
    state_counts: Dict[str, int] = {}
    for i in range(1, len(df)):
        state = strategy.classifier.classify_market_state(df.iloc[i], df.iloc[i - 1])
        state_counts[state] = state_counts.get(state, 0) + 1

    backtester = V35Backtester4H(
        initial_capital=config.get("initial_capital", 10_000_000),
        fee_rate=config.get("fee_rate", 0.0005),
        slippage=config.get("slippage", 0.0002),
    )

    results = backtester.run(df, strategy)
    results["market_state_counts"] = state_counts
    return results


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--year", default="2024")
    parser.add_argument("--all-years", action="store_true")
    parser.add_argument("--enable-sideways-down", action="store_true")
    args = parser.parse_args()

    config = _load_merged_config()

    if args.enable_sideways_down:
        config = dict(config)
        config.update(
            {
                "enable_sideways_down_entry": True,
                "sideways_down_position_factor": 0.10,
                # Tuned defaults (target: +5~15 entries/year range)
                "sideways_down_rsi_oversold": 38,
                "sideways_down_stoch_oversold": 30,
                "sideways_down_bb_epsilon": 0.10,
                "sideways_down_adx_max": 25,
                "sideways_down_mfi_min": 20,
                "sideways_down_close_off_lows": 0.05,
                "sideways_down_cooldown_bars": 6,
                "sideways_down_take_profit": 0.01,
                "sideways_down_max_hold_bars": 6,
            }
        )

    years = ["2020", "2021", "2022", "2023", "2024", "2025"] if args.all_years else [args.year]

    print("=" * 80)
    print("v35 Optimized - 4H Backtest (minute240)")
    print("enable_sideways_down_entry:", bool(config.get("enable_sideways_down_entry", False)))
    print("=" * 80)

    for y in years:
        r = run_year(y, config)
        entries_by_strategy = r.get("entries_by_strategy", {})
        sd_entries = int(entries_by_strategy.get("sideways_down", 0))
        state_counts = r.get("market_state_counts", {})
        sd_bars = int(state_counts.get("SIDEWAYS_DOWN", 0))
        print(
            f"{y}: return {r['total_return']:+.2f}% | entries {r['total_trades']} (round-trips)"
            + (
                f" | sideways_down entries {sd_entries} | SIDEWAYS_DOWN bars {sd_bars}"
                if bool(config.get("enable_sideways_down_entry", False))
                else ""
            )
        )


if __name__ == "__main__":
    main()
