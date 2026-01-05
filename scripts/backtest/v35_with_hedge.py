#!/usr/bin/env python3
"""
Combined backtest for V35 Long + SHORT_V2 Hedge Strategy.

Runs V35 Long on daily timeframe (KRW) and SHORT_V2 hedge on 4h timeframe (USDT).
The hedge size matches the long exposure value.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.backtest._common import (
    create_parser,
    get_db_path,
    load_data,
    compute_metrics,
    print_yearly_table,
)
from trading.strategy.v35_long import V35LongStrategy
from trading.strategy.short_v2 import ShortV2Strategy
from trading.strategy.regime_router import RegimeRouter
from core.backtester import Backtester


# Fixed FX rate for KRW/USD conversion
FX_RATE = 1400.0


class CombinedBacktester:
    """Combined backtester for V35 Long + SHORT_V2 Hedge."""

    def __init__(
        self,
        initial_capital_krw: float = 10_000_000,
        hedge_capital_usdt: float = 5_000,
        fee_rate: float = 0.0005,
        slippage: float = 0.0002,
    ):
        self.initial_capital_krw = float(initial_capital_krw)
        self.hedge_capital_usdt = float(hedge_capital_usdt)
        self.fee_rate = float(fee_rate)
        self.slippage = float(slippage)

        # V35 Long state (KRW)
        self.long_cash = self.initial_capital_krw
        self.long_position = 0.0  # BTC quantity
        self.long_entry_price = 0.0

        # SHORT_V2 Hedge state (USDT)
        self.hedge_cash = self.hedge_capital_usdt
        self.hedge_in_short = False
        self.hedge_entry_price = 0.0
        self.hedge_size = 0.0
        self.hedge_margin = 0.0

        # Tracking
        self.equity_curve: List[Dict] = []
        self.long_trades: List[Dict] = []
        self.hedge_trades: List[Dict] = []

        # Strategies
        self.v35_strategy = V35LongStrategy()
        self.short_v2_strategy = ShortV2Strategy()
        self.router = RegimeRouter(
            binance_gate_mode="bear_strong_only",
            binance_policy="short_v2",
        )

    def reset(self):
        """Reset backtester state."""
        self.long_cash = self.initial_capital_krw
        self.long_position = 0.0
        self.long_entry_price = 0.0

        self.hedge_cash = self.hedge_capital_usdt
        self.hedge_in_short = False
        self.hedge_entry_price = 0.0
        self.hedge_size = 0.0
        self.hedge_margin = 0.0

        self.equity_curve = []
        self.long_trades = []
        self.hedge_trades = []

        self.short_v2_strategy = ShortV2Strategy()

    def _get_long_exposure_krw(self, price_krw: float) -> float:
        """Get current long position value in KRW."""
        return self.long_position * price_krw

    def _get_regime(self, daily_df: pd.DataFrame, current_date: pd.Timestamp) -> str:
        """Classify regime from daily data up to current date."""
        if daily_df is None or len(daily_df) < 20:
            return "SIDEWAYS_NEUTRAL"

        # Filter to data up to current date
        df_until = daily_df[daily_df["timestamp"] <= current_date].copy()
        if len(df_until) < 20:
            return "SIDEWAYS_NEUTRAL"

        try:
            market_state = self.router.classify_market_state(df_until)
            return market_state
        except Exception:
            return "SIDEWAYS_NEUTRAL"

    def _long_equity(self, price_krw: float) -> float:
        """Calculate long side equity (KRW)."""
        return self.long_cash + self.long_position * price_krw

    def _hedge_equity(self, price_usdt: float) -> float:
        """Calculate hedge side equity (USDT)."""
        if not self.hedge_in_short:
            return self.hedge_cash
        unrealized = (self.hedge_entry_price - price_usdt * (1 + self.slippage)) * self.hedge_size
        return self.hedge_cash + self.hedge_margin + unrealized

    def _total_equity_krw(self, price_krw: float, price_usdt: float) -> float:
        """Calculate total equity in KRW."""
        long_eq = self._long_equity(price_krw)
        hedge_eq_krw = self._hedge_equity(price_usdt) * FX_RATE
        return long_eq + hedge_eq_krw

    def run(
        self,
        daily_df: pd.DataFrame,
        h4_df: pd.DataFrame,
    ) -> Dict:
        """Run combined backtest.

        Args:
            daily_df: Daily OHLCV data for V35 Long (KRW prices)
            h4_df: 4h OHLCV data for SHORT_V2 hedge (USDT prices from same source)

        Returns:
            Results dictionary
        """
        self.reset()

        if daily_df.empty or h4_df.empty:
            return self._generate_results()

        # Add indicators to both dataframes
        daily_df = self.v35_strategy.add_indicators(daily_df.copy())
        h4_df = self.short_v2_strategy.add_indicators(h4_df.copy())

        # Create date index for daily data
        daily_df["date"] = pd.to_datetime(daily_df["timestamp"]).dt.date
        h4_df["date"] = pd.to_datetime(h4_df["timestamp"]).dt.date

        # Process each 4h candle
        for h4_i in range(len(h4_df)):
            h4_row = h4_df.iloc[h4_i]
            ts = h4_row["timestamp"]
            current_date = pd.to_datetime(ts)

            # Get prices (both in their native currency)
            price_krw = float(h4_row["close"])  # Upbit KRW price
            price_usdt = price_krw / FX_RATE  # Convert to USDT for hedge

            if price_krw <= 0:
                continue

            # Find matching daily candle for V35
            daily_idx = daily_df[daily_df["date"] <= current_date.date()]
            if len(daily_idx) < 30:
                continue
            daily_i = len(daily_idx) - 1

            # Process V35 Long signal (once per day, on first 4h candle of day)
            is_new_day = (h4_i == 0 or
                          h4_df.iloc[h4_i - 1]["date"] != h4_row["date"])

            if is_new_day and daily_i >= 30:
                v35_signal = self.v35_strategy.generate_signal(daily_df, daily_i)
                if v35_signal:
                    self._process_long_signal(v35_signal, ts, price_krw)

            # Get current regime for hedge
            regime = self._get_regime(daily_df.iloc[:daily_i + 1], current_date)

            # Get long exposure for hedge sizing
            long_exposure_krw = self._get_long_exposure_krw(price_krw)

            # Process SHORT_V2 hedge signal (on every 4h candle)
            if h4_i >= 100:  # Warmup for EMA 100
                hedge_signal = self.short_v2_strategy.generate_signal(
                    h4_df, h4_i,
                    regime=regime,
                    long_exposure_krw=long_exposure_krw,
                )
                if hedge_signal:
                    self._process_hedge_signal(hedge_signal, ts, price_usdt, long_exposure_krw)

            # Record equity
            self.equity_curve.append({
                "timestamp": ts,
                "long_equity_krw": self._long_equity(price_krw),
                "hedge_equity_usdt": self._hedge_equity(price_usdt),
                "hedge_equity_krw": self._hedge_equity(price_usdt) * FX_RATE,
                "total_equity": self._total_equity_krw(price_krw, price_usdt),
                "regime": regime,
                "long_exposure_krw": long_exposure_krw,
            })

        # Force close at end
        if len(h4_df) > 0:
            last_row = h4_df.iloc[-1]
            last_price_krw = float(last_row["close"])
            last_price_usdt = last_price_krw / FX_RATE
            if self.long_position > 0:
                self._close_long(last_row["timestamp"], last_price_krw)
            if self.hedge_in_short:
                self._close_hedge(last_row["timestamp"], last_price_usdt)

        return self._generate_results()

    def _process_long_signal(self, signal: Dict, ts, price_krw: float):
        """Process V35 Long signal."""
        action = signal.get("action", "hold")
        fraction = float(signal.get("fraction", 1.0))

        if action == "buy" and self.long_position == 0:
            self._open_long(ts, price_krw, fraction)
        elif action == "sell" and self.long_position > 0:
            self._close_long(ts, price_krw)

    def _open_long(self, ts, price: float, fraction: float):
        """Open long position."""
        amount = self.long_cash * fraction
        fee = amount * self.fee_rate
        exec_price = price * (1 + self.slippage)
        size = (amount - fee) / exec_price

        self.long_cash -= amount
        self.long_position = size
        self.long_entry_price = exec_price

        self.long_trades.append({
            "entry_time": ts,
            "entry_price": exec_price,
            "size": size,
            "exit_time": None,
            "exit_price": None,
            "pnl": None,
        })

    def _close_long(self, ts, price: float):
        """Close long position."""
        if self.long_position <= 0:
            return

        exec_price = price * (1 - self.slippage)
        proceeds = self.long_position * exec_price
        fee = proceeds * self.fee_rate
        pnl = (exec_price - self.long_entry_price) * self.long_position - fee

        self.long_cash += proceeds - fee
        self.long_position = 0
        self.long_entry_price = 0

        for t in self.long_trades:
            if t.get("exit_time") is None:
                t["exit_time"] = ts
                t["exit_price"] = exec_price
                t["pnl"] = pnl
                break

    def _process_hedge_signal(self, signal: Dict, ts, price_usdt: float, long_exposure_krw: float):
        """Process SHORT_V2 hedge signal."""
        action = signal.get("action", "hold")

        if action == "open_short" and not self.hedge_in_short:
            # Size hedge to match long exposure
            hedge_size_usdt = long_exposure_krw / FX_RATE
            # Cap at available hedge capital
            hedge_size_usdt = min(hedge_size_usdt, self.hedge_cash * 0.95)
            if hedge_size_usdt > 10:  # Min 10 USDT
                self._open_hedge(ts, price_usdt, hedge_size_usdt)
        elif action == "close_short" and self.hedge_in_short:
            self._close_hedge(ts, price_usdt)

    def _open_hedge(self, ts, price: float, amount_usdt: float):
        """Open short hedge position."""
        if self.hedge_in_short:
            return

        margin = amount_usdt / (1 + self.fee_rate)
        entry_exec = price * (1 - self.slippage)
        size = margin / entry_exec
        fee = margin * self.fee_rate

        self.hedge_cash -= (margin + fee)
        self.hedge_margin = margin
        self.hedge_size = size
        self.hedge_entry_price = entry_exec
        self.hedge_in_short = True

        self.hedge_trades.append({
            "entry_time": ts,
            "entry_price": entry_exec,
            "size": size,
            "margin": margin,
            "exit_time": None,
            "exit_price": None,
            "pnl": None,
        })

    def _close_hedge(self, ts, price: float):
        """Close short hedge position."""
        if not self.hedge_in_short:
            return

        exit_exec = price * (1 + self.slippage)
        exit_fee = (self.hedge_size * exit_exec) * self.fee_rate
        pnl = (self.hedge_entry_price - exit_exec) * self.hedge_size - exit_fee

        self.hedge_cash += self.hedge_margin + pnl
        self.hedge_in_short = False
        self.hedge_entry_price = 0
        self.hedge_size = 0
        self.hedge_margin = 0

        for t in self.hedge_trades:
            if t.get("exit_time") is None:
                t["exit_time"] = ts
                t["exit_price"] = exit_exec
                t["pnl"] = pnl
                break

    def _generate_results(self) -> Dict:
        """Generate results dictionary."""
        eq = pd.DataFrame(self.equity_curve) if self.equity_curve else pd.DataFrame()

        initial_total = self.initial_capital_krw + self.hedge_capital_usdt * FX_RATE
        final_total = float(eq["total_equity"].iloc[-1]) if not eq.empty else initial_total

        total_return = ((final_total - initial_total) / initial_total) * 100

        # Long trades stats
        closed_long = [t for t in self.long_trades if t.get("exit_time")]
        long_wins = [t for t in closed_long if t.get("pnl", 0) > 0]

        # Hedge trades stats
        closed_hedge = [t for t in self.hedge_trades if t.get("exit_time")]
        hedge_wins = [t for t in closed_hedge if t.get("pnl", 0) > 0]

        return {
            "initial_capital_krw": self.initial_capital_krw,
            "hedge_capital_usdt": self.hedge_capital_usdt,
            "initial_total_krw": initial_total,
            "final_total_krw": final_total,
            "total_return": total_return,
            "long_trades": len(closed_long),
            "long_win_rate": len(long_wins) / len(closed_long) if closed_long else 0,
            "hedge_trades": len(closed_hedge),
            "hedge_win_rate": len(hedge_wins) / len(closed_hedge) if closed_hedge else 0,
            "equity_curve": eq,
            "long_trades_list": closed_long,
            "hedge_trades_list": closed_hedge,
        }


def print_combined_summary(results: Dict, metrics: Dict, long_only_metrics: Dict = None):
    """Print combined backtest summary."""
    print("\n" + "=" * 70)
    print("V35 LONG + SHORT_V2 HEDGE Combined Backtest")
    print("=" * 70)

    print(f"\n{'Capital Allocation:':<25}")
    print(f"  Long (Upbit KRW):     {results['initial_capital_krw']:>15,.0f} KRW")
    print(f"  Hedge (Binance USDT): {results['hedge_capital_usdt']:>15,.0f} USDT")
    print(f"  Total (KRW equiv):    {results['initial_total_krw']:>15,.0f} KRW")

    print(f"\n{'Performance:':<25}")
    print(f"  Final Capital:        {results['final_total_krw']:>15,.0f} KRW")
    print(f"  Total Return:         {results['total_return']:>14.2f}%")
    print(f"  CAGR:                 {metrics.get('cagr', 0):>14.2f}%")
    print(f"  MDD:                  {metrics.get('mdd', 0):>14.2f}%")
    print(f"  Sharpe:               {metrics.get('sharpe', 0):>14.2f}")

    if long_only_metrics:
        print(f"\n{'Comparison (Long Only vs With Hedge):':<40}")
        print(f"  Long Only Return:     {long_only_metrics.get('total_return', 0):>14.2f}%")
        print(f"  With Hedge Return:    {results['total_return']:>14.2f}%")
        print(f"  Long Only MDD:        {long_only_metrics.get('mdd', 0):>14.2f}%")
        print(f"  With Hedge MDD:       {metrics.get('mdd', 0):>14.2f}%")
        mdd_improvement = long_only_metrics.get('mdd', 0) - metrics.get('mdd', 0)
        print(f"  MDD Improvement:      {mdd_improvement:>14.2f}%")

    print(f"\n{'Trade Statistics:':<25}")
    print(f"  Long Trades:          {results['long_trades']:>15}")
    print(f"  Long Win Rate:        {results['long_win_rate']*100:>14.1f}%")
    print(f"  Hedge Trades:         {results['hedge_trades']:>15}")
    print(f"  Hedge Win Rate:       {results['hedge_win_rate']*100:>14.1f}%")


def main():
    parser = create_parser(
        strategy_name="v35_with_hedge",
        default_timeframe="minute240",
        default_capital=10_000_000,
    )
    parser.add_argument(
        "--hedge-capital",
        type=float,
        default=5_000,
        help="Hedge capital in USDT (default: 5000)",
    )
    parser.add_argument(
        "--no-hedge",
        action="store_true",
        help="Run V35 Long only (no hedge) for comparison",
    )
    args = parser.parse_args()

    db_path = get_db_path(args.db_path)

    print("=" * 70)
    print("V35 Long + SHORT_V2 Hedge Combined Backtest")
    print("=" * 70)
    print(f"Period: {args.start_date} to {args.end_date}")
    print(f"Long Capital: {args.capital:,.0f} KRW")
    print(f"Hedge Capital: {args.hedge_capital:,.0f} USDT")
    print("=" * 70)

    # Load data
    print("\nLoading data...")
    daily_df = load_data(db_path, "day", args.start_date, args.end_date)
    h4_df = load_data(db_path, "minute240", args.start_date, args.end_date)
    print(f"Loaded {len(daily_df):,} daily candles, {len(h4_df):,} 4h candles")

    if daily_df.empty or h4_df.empty:
        print("ERROR: No data found for the specified date range.")
        sys.exit(1)

    # Run combined backtest
    bt = CombinedBacktester(
        initial_capital_krw=args.capital,
        hedge_capital_usdt=args.hedge_capital,
    )
    results = bt.run(daily_df, h4_df)

    # Compute metrics
    eq = results.get("equity_curve")
    if not eq.empty:
        eq_for_metrics = eq[["timestamp", "total_equity"]].copy()
        eq_for_metrics.columns = ["timestamp", "total_equity"]
    else:
        eq_for_metrics = pd.DataFrame()

    metrics = compute_metrics(eq_for_metrics, "minute240")

    # Also run long-only for comparison
    long_only_metrics = None
    if not args.no_hedge:
        print("\nRunning long-only comparison...")
        bt_long_only = CombinedBacktester(
            initial_capital_krw=args.capital,
            hedge_capital_usdt=0,  # No hedge
        )
        # Disable hedge by setting capital to 0
        results_long_only = bt_long_only.run(daily_df, h4_df)
        eq_long = results_long_only.get("equity_curve")
        if not eq_long.empty:
            eq_long_metrics = eq_long[["timestamp", "total_equity"]].copy()
            long_only_metrics = compute_metrics(eq_long_metrics, "minute240")
            long_only_metrics["total_return"] = results_long_only["total_return"]

    # Print results
    print_combined_summary(results, metrics, long_only_metrics)

    if args.by_year and not eq.empty:
        eq_for_yearly = eq[["timestamp", "total_equity"]].copy()
        print_yearly_table(eq_for_yearly)


if __name__ == "__main__":
    main()
