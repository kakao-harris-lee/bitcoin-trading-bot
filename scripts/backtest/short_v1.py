#!/usr/bin/env python3
"""
Backtest for Short V1 Strategy.

Short V1 is an EMA/ADX-based short strategy for Binance Futures that:
- Enters on EMA death cross with strong ADX
- Uses -DI > +DI confirmation
- Exits on golden cross or TP/SL levels

Note: Uses margin-style backtesting for short positions.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Dict

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.backtest._common import (
    create_parser,
    get_db_path,
    load_data,
    compute_metrics,
    print_summary,
    print_yearly_table,
)
from trading.strategy.short_v1 import ShortV1Strategy


class ShortV1Adapter:
    """Adapter to make ShortV1Strategy compatible with margin backtester."""

    def __init__(self, config: dict = None):
        self.strategy = ShortV1Strategy(strategy_config=config)
        self._cached_df = None

    @property
    def in_position(self) -> bool:
        return self.strategy.in_position

    def __call__(self, df, i, params):
        if i < 200:  # EMA200 warmup
            return {"action": "hold"}

        # Cache indicators
        if self._cached_df is None or len(df) != len(self._cached_df):
            self._cached_df = self.strategy.add_indicators(df)

        signal = self.strategy.generate_signal(self._cached_df, i)
        if signal is None:
            return {"action": "hold"}

        # Map short actions to buy/sell for margin backtester
        action = signal.get("action", "hold")
        if action == "open_short":
            return {
                "action": "buy",  # "buy" opens short in margin backtester
                "fraction": signal.get("fraction", 1.0),
                "reason": signal.get("reason", ""),
            }
        elif action == "close_short":
            return {
                "action": "sell",  # "sell" closes short in margin backtester
                "fraction": 1.0,
                "reason": signal.get("reason", ""),
            }

        return {"action": "hold"}


class ShortMarginBacktester:
    """Margin-style backtester for short positions."""

    def __init__(
        self,
        initial_capital: float = 10_000,
        fee_rate: float = 0.0005,
        slippage: float = 0.0002,
    ):
        self.initial_capital = float(initial_capital)
        self.fee_rate = float(fee_rate)
        self.slippage = float(slippage)

        self.cash = self.initial_capital
        self.in_short = False
        self.entry_price = 0.0
        self.size = 0.0
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

    def run(self, df: pd.DataFrame, strategy_func, params: Dict = None) -> Dict:
        self.reset()
        params = params or {}

        for i in range(len(df)):
            row = df.iloc[i]
            ts = row["timestamp"]
            price = float(row["close"])

            sig = strategy_func(df, i, params)
            action = sig.get("action", "hold")
            fraction = float(sig.get("fraction", 1.0))

            if action == "buy":
                self._open_short(ts, price, fraction)
            elif action == "sell":
                self._close_short(ts, price)

            self.equity_curve.append({
                "timestamp": ts,
                "cash": self.cash,
                "margin": self.margin,
                "total_equity": self._equity(price),
            })

        # Force close at end
        if self.in_short:
            last = df.iloc[-1]
            self._close_short(last["timestamp"], float(last["close"]))

        return self._generate_results()

    def _open_short(self, ts, price: float, fraction: float):
        if self.in_short:
            return

        margin = self.cash * fraction
        if margin < 10:
            return

        entry_exec = price * (1 - self.slippage)
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

    def _close_short(self, ts, price: float):
        if not self.in_short:
            return

        exit_exec = price * (1 + self.slippage)
        exit_fee = (self.size * exit_exec) * self.fee_rate
        pnl = (self.entry_price - exit_exec) * self.size
        self.cash += self.margin + pnl - exit_fee

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

    def _generate_results(self) -> Dict:
        eq = pd.DataFrame(self.equity_curve)
        final_equity = float(eq["total_equity"].iloc[-1]) if not eq.empty else self.cash
        total_return = ((final_equity - self.initial_capital) / self.initial_capital) * 100

        closed_trades = [t for t in self.trades if t.get("exit_time") is not None]
        wins = [t for t in closed_trades if t.get("pnl", 0) > 0]
        losses = [t for t in closed_trades if t.get("pnl", 0) <= 0]

        win_rate = len(wins) / len(closed_trades) if closed_trades else 0.0
        avg_profit = float(np.mean([t["pnl"] for t in wins])) if wins else 0.0
        avg_loss = float(abs(np.mean([t["pnl"] for t in losses]))) if losses else 0.0
        profit_factor = (
            sum(t["pnl"] for t in wins) / abs(sum(t["pnl"] for t in losses))
            if losses and sum(t["pnl"] for t in losses) != 0
            else 0.0
        )

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


def main():
    parser = create_parser(
        strategy_name="short_v1",
        default_timeframe="minute240",
        default_capital=10_000,  # USDT
    )
    args = parser.parse_args()

    db_path = get_db_path(args.db_path)

    print(f"Loading data: {args.timeframe} from {args.start_date} to {args.end_date}")
    df = load_data(db_path, args.timeframe, args.start_date, args.end_date)
    print(f"Loaded {len(df):,} candles")

    # Initialize strategy adapter
    strategy = ShortV1Adapter()

    # Run backtest with margin backtester
    bt = ShortMarginBacktester(
        initial_capital=args.capital,
        fee_rate=0.0005,
        slippage=0.0002,
    )
    results = bt.run(df, strategy, {})

    # Compute metrics
    metrics = compute_metrics(results.get("equity_curve", None))

    # Print results
    print_summary("Short V1", results, metrics, verbose=args.verbose)

    if args.by_year:
        print_yearly_table(results.get("equity_curve", None))


if __name__ == "__main__":
    main()
