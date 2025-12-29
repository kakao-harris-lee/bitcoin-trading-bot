#!/usr/bin/env python3
"""
Kimchi Premium Delta-Neutral Hedge Module

This is NOT a standalone strategy. It works WITH existing Upbit long positions:

1. Main strategy (v35) buys BTC on Upbit when BULL
2. This module hedges that position on Binance when premium is HIGH
3. Result: Lock in premium while maintaining delta-neutral exposure
4. When premium normalizes: Remove hedge, back to directional long

Key insight: We ALREADY have Upbit long from main strategy.
This module just adds/removes the Binance short hedge.

Usage:
    python scripts/backtest_kimchi_arb.py
    python scripts/backtest_kimchi_arb.py --by-year
"""

from __future__ import annotations

import argparse
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd


# ==============================================================================
# Configuration
# ==============================================================================

@dataclass
class KimchiHedgeConfig:
    """Configuration for premium-based hedging."""

    # Separate capital for hedging (margin for Binance shorts)
    binance_margin_usdt: float = 10_000  # $10K margin for shorts

    # Premium thresholds
    hedge_entry_premium: float = 5.0   # Start hedging when premium >= 5%
    hedge_exit_premium: float = 2.0    # Remove hedge when premium <= 2%

    # Hedge ratio (what % of Upbit position to hedge)
    hedge_ratio: float = 1.0  # 100% hedge = fully delta-neutral

    # Costs
    binance_fee_pct: float = 0.04     # 0.04% taker
    slippage_pct: float = 0.02        # 0.02%

    # Funding (8-hourly)
    default_funding_rate: float = 0.0001  # 0.01%

    # Simulated Upbit position (from main v35 strategy)
    simulated_upbit_btc: float = 0.5  # Assume 0.5 BTC position from v35

    # Exchange rate
    usd_krw_rate: float = 1450.0

    # Regime-based gating: Only hedge in these regimes
    # BULL = Don't hedge (let position ride)
    # SIDEWAYS/BEAR = Hedge for protection
    allowed_hedge_regimes: tuple = ("BEAR",)  # BEAR only - most conservative
    use_regime_gating: bool = True  # Enable/disable regime filtering

    # Price-based stop loss: Exit if price moves too far against us
    stop_loss_pct: float = 5.0  # Exit if short loses > 5%


# ==============================================================================
# Data Loading
# ==============================================================================

def load_data(
    upbit_db: Path,
    binance_db: Path,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> pd.DataFrame:
    """Load aligned data with premium calculation."""

    upbit_conn = sqlite3.connect(str(upbit_db))
    binance_conn = sqlite3.connect(str(binance_db))

    date_filter = ""
    if start_date:
        date_filter += f" AND timestamp >= '{start_date}'"
    if end_date:
        date_filter += f" AND timestamp <= '{end_date}'"

    upbit_df = pd.read_sql(f"""
        SELECT timestamp, trade_price as upbit_krw
        FROM bitcoin_minute60
        WHERE 1=1 {date_filter}
        ORDER BY timestamp
    """, upbit_conn)

    binance_df = pd.read_sql(f"""
        SELECT timestamp, close as binance_usd
        FROM binance_minute60
        WHERE 1=1 {date_filter}
        ORDER BY timestamp
    """, binance_conn)

    upbit_conn.close()
    binance_conn.close()

    df = pd.merge(upbit_df, binance_df, on='timestamp', how='inner')
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df = df.set_index('timestamp').sort_index()

    # Calculate premium
    df['implied_rate'] = df['upbit_krw'] / df['binance_usd']
    df['fair_rate'] = df['implied_rate'].rolling(window=24*7, min_periods=24).median()
    df['fair_rate'] = df['fair_rate'].fillna(df['implied_rate'].iloc[:24*7].median())
    df['premium_pct'] = ((df['implied_rate'] / df['fair_rate']) - 1) * 100

    # Calculate market regime using Binance price (USD reference)
    df['sma50'] = df['binance_usd'].rolling(window=50).mean()
    df['sma200'] = df['binance_usd'].rolling(window=200).mean()

    def classify_regime(row):
        price = row['binance_usd']
        sma50 = row['sma50']
        sma200 = row['sma200']

        if pd.isna(sma200):
            return 'SIDEWAYS'

        if price > sma50 > sma200:
            return 'BULL'
        elif price < sma50 < sma200:
            return 'BEAR'
        else:
            return 'SIDEWAYS'

    df['regime'] = df.apply(classify_regime, axis=1)

    return df


# ==============================================================================
# Hedge Module
# ==============================================================================

@dataclass
class HedgePosition:
    """Binance short hedge position."""
    entry_time: Optional[datetime] = None
    entry_price: float = 0.0
    entry_premium: float = 0.0
    btc_size: float = 0.0
    margin_used: float = 0.0
    entry_fee: float = 0.0
    accumulated_funding: float = 0.0

    @property
    def is_active(self) -> bool:
        return self.btc_size > 0


@dataclass
class HedgeTrade:
    """Record of a hedge trade."""
    entry_time: datetime
    exit_time: datetime
    entry_premium: float
    exit_premium: float
    entry_price: float
    exit_price: float
    btc_size: float
    short_pnl: float
    fees: float
    funding: float
    hold_hours: int


class KimchiHedgeModule:
    """
    Premium-based hedging module.

    Assumes main strategy has a long position on Upbit.
    This module adds/removes Binance short hedge based on premium.

    When premium is HIGH (≥5%):
      - Short Binance to match Upbit position
      - Now delta-neutral: immune to BTC price moves
      - Effectively "locked in" the high premium

    When premium NORMALIZES (≤2%):
      - Close Binance short
      - Back to directional long (Upbit only)

    Profit comes from:
      - Premium captured (sold high premium)
      - Funding income (shorts often receive funding)
      - Minus: trading fees
    """

    def __init__(self, config: KimchiHedgeConfig):
        self.config = config
        self.hedge = HedgePosition()
        self.cash_usd = config.binance_margin_usdt
        self.trades: List[HedgeTrade] = []
        self.equity_history: List[Dict] = []

    def calculate_equity(self, binance_price: float) -> float:
        """Calculate current USD equity."""
        if self.hedge.is_active:
            # Mark-to-market short position
            short_pnl = (self.hedge.entry_price - binance_price) * self.hedge.btc_size
            return self.cash_usd + self.hedge.margin_used + short_pnl + self.hedge.accumulated_funding
        return self.cash_usd

    def check_entry(
        self,
        timestamp: datetime,
        premium: float,
        binance_price: float,
        regime: str = "SIDEWAYS",
    ) -> bool:
        """Enter hedge when premium is high and regime allows."""
        if self.hedge.is_active:
            return False

        if premium < self.config.hedge_entry_premium:
            return False

        # Regime gating: Only hedge in BEAR/SIDEWAYS, not in BULL
        if self.config.use_regime_gating:
            if regime not in self.config.allowed_hedge_regimes:
                return False

        cfg = self.config

        # Calculate hedge size (match Upbit position)
        btc_to_short = cfg.simulated_upbit_btc * cfg.hedge_ratio
        margin_needed = btc_to_short * binance_price

        if margin_needed > self.cash_usd * 0.8:
            # Not enough margin
            btc_to_short = (self.cash_usd * 0.8) / binance_price
            margin_needed = btc_to_short * binance_price

        fee = margin_needed * (cfg.binance_fee_pct + cfg.slippage_pct) / 100

        # Enter short
        self.cash_usd -= (margin_needed + fee)
        self.hedge = HedgePosition(
            entry_time=timestamp,
            entry_price=binance_price,
            entry_premium=premium,
            btc_size=btc_to_short,
            margin_used=margin_needed,
            entry_fee=fee,
            accumulated_funding=0.0,
        )

        return True

    def check_exit(
        self,
        timestamp: datetime,
        premium: float,
        binance_price: float,
    ) -> Optional[HedgeTrade]:
        """Exit hedge when premium normalizes or stop-loss hit."""
        if not self.hedge.is_active:
            return None

        # Check stop-loss first (price moved too far against short)
        price_change_pct = (binance_price - self.hedge.entry_price) / self.hedge.entry_price * 100
        stop_hit = price_change_pct > self.config.stop_loss_pct

        # Exit if premium normalizes OR stop-loss hit
        if premium > self.config.hedge_exit_premium and not stop_hit:
            return None

        cfg = self.config
        h = self.hedge

        # Close short
        exit_value = h.btc_size * binance_price
        exit_fee = exit_value * (cfg.binance_fee_pct + cfg.slippage_pct) / 100

        # Short P&L = (entry - exit) * size
        short_pnl = (h.entry_price - binance_price) * h.btc_size

        # Return margin + P&L
        self.cash_usd += h.margin_used + short_pnl + h.accumulated_funding - exit_fee

        hold_hours = int((timestamp - h.entry_time).total_seconds() / 3600)

        trade = HedgeTrade(
            entry_time=h.entry_time,
            exit_time=timestamp,
            entry_premium=h.entry_premium,
            exit_premium=premium,
            entry_price=h.entry_price,
            exit_price=binance_price,
            btc_size=h.btc_size,
            short_pnl=short_pnl,
            fees=h.entry_fee + exit_fee,
            funding=h.accumulated_funding,
            hold_hours=hold_hours,
        )

        self.trades.append(trade)
        self.hedge = HedgePosition()

        return trade

    def apply_funding(self, binance_price: float, rate: float = None) -> float:
        """Apply funding rate to short position."""
        if not self.hedge.is_active:
            return 0.0

        r = rate if rate is not None else self.config.default_funding_rate
        # Positive rate = shorts receive payment
        funding = self.hedge.btc_size * binance_price * r
        self.hedge.accumulated_funding += funding
        return funding


# ==============================================================================
# Backtester
# ==============================================================================

@dataclass
class BacktestResult:
    start_date: str
    end_date: str
    initial_capital: float
    final_capital: float
    total_return_pct: float

    # Trade stats
    total_trades: int
    winning_trades: int
    win_rate_pct: float

    # P&L breakdown
    total_short_pnl: float
    total_fees: float
    total_funding: float
    net_pnl: float

    # Premium stats
    avg_entry_premium: float
    avg_exit_premium: float
    avg_premium_captured: float
    avg_hold_hours: float

    # Time in hedge
    time_hedged_pct: float

    equity_df: pd.DataFrame = field(default_factory=pd.DataFrame)


def run_backtest(config: KimchiHedgeConfig, df: pd.DataFrame) -> BacktestResult:
    """Run hedge module backtest."""

    module = KimchiHedgeModule(config)
    initial_capital = config.binance_margin_usdt

    funding_counter = 0
    hours_hedged = 0
    total_hours = len(df)

    for timestamp, row in df.iterrows():
        binance_price = row['binance_usd']
        premium = row['premium_pct']
        regime = row['regime']

        # Try entry/exit
        module.check_entry(timestamp, premium, binance_price, regime)
        trade = module.check_exit(timestamp, premium, binance_price)

        # Track hedged time
        if module.hedge.is_active:
            hours_hedged += 1

        # Apply funding every 8 hours
        funding_counter += 1
        if funding_counter >= 8 and module.hedge.is_active:
            module.apply_funding(binance_price)
            funding_counter = 0

        # Record equity
        equity = module.calculate_equity(binance_price)
        module.equity_history.append({
            'timestamp': timestamp,
            'equity_usd': equity,
            'premium_pct': premium,
            'is_hedged': module.hedge.is_active,
        })

    # Force close at end
    if module.hedge.is_active:
        last = df.iloc[-1]
        module.check_exit(df.index[-1], -100, last['binance_usd'])

    # Build results
    equity_df = pd.DataFrame(module.equity_history)
    if not equity_df.empty:
        equity_df = equity_df.set_index('timestamp')

    final_capital = module.cash_usd
    trades = module.trades

    if trades:
        winning = [t for t in trades if t.short_pnl + t.funding - t.fees > 0]
        total_short_pnl = sum(t.short_pnl for t in trades)
        total_fees = sum(t.fees for t in trades)
        total_funding = sum(t.funding for t in trades)
        avg_entry = np.mean([t.entry_premium for t in trades])
        avg_exit = np.mean([t.exit_premium for t in trades])
        avg_hold = np.mean([t.hold_hours for t in trades])
    else:
        winning = []
        total_short_pnl = 0
        total_fees = 0
        total_funding = 0
        avg_entry = 0
        avg_exit = 0
        avg_hold = 0

    return BacktestResult(
        start_date=df.index[0].strftime("%Y-%m-%d"),
        end_date=df.index[-1].strftime("%Y-%m-%d"),
        initial_capital=initial_capital,
        final_capital=round(final_capital, 2),
        total_return_pct=round((final_capital / initial_capital - 1) * 100, 2),
        total_trades=len(trades),
        winning_trades=len(winning),
        win_rate_pct=round(len(winning) / len(trades) * 100, 1) if trades else 0,
        total_short_pnl=round(total_short_pnl, 2),
        total_fees=round(total_fees, 2),
        total_funding=round(total_funding, 2),
        net_pnl=round(total_short_pnl + total_funding - total_fees, 2),
        avg_entry_premium=round(avg_entry, 2),
        avg_exit_premium=round(avg_exit, 2),
        avg_premium_captured=round(avg_entry - avg_exit, 2),
        avg_hold_hours=round(avg_hold, 1),
        time_hedged_pct=round(hours_hedged / total_hours * 100, 1),
        equity_df=equity_df,
    )


def print_result(result: BacktestResult, title: str = "Kimchi Hedge Module") -> None:
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"  Period: {result.start_date} ~ {result.end_date}")
    print(f"{'='*60}")

    print(f"\n💰 Capital (Binance margin for shorts):")
    print(f"   Initial:  ${result.initial_capital:,.0f}")
    print(f"   Final:    ${result.final_capital:,.2f}")
    print(f"   Return:   {result.total_return_pct:+.2f}%")

    print(f"\n📊 Hedge Trades:")
    print(f"   Total:    {result.total_trades}")
    print(f"   Winning:  {result.winning_trades} ({result.win_rate_pct:.0f}%)")
    print(f"   Time hedged: {result.time_hedged_pct:.1f}% of period")

    print(f"\n💱 Premium Captured:")
    print(f"   Entry:    {result.avg_entry_premium:+.2f}%")
    print(f"   Exit:     {result.avg_exit_premium:+.2f}%")
    print(f"   Captured: {result.avg_premium_captured:+.2f}%")
    print(f"   Avg Hold: {result.avg_hold_hours:.0f} hours")

    print(f"\n💵 P&L Breakdown (USD):")
    print(f"   Short P&L: ${result.total_short_pnl:+,.2f}")
    print(f"   Funding:   ${result.total_funding:+,.2f}")
    print(f"   Fees:      ${result.total_fees:,.2f}")
    print(f"   Net P&L:   ${result.net_pnl:+,.2f}")


def run_by_year(config: KimchiHedgeConfig, upbit_db: Path, binance_db: Path):
    years = [2020, 2021, 2022, 2023, 2024, 2025]
    results = []

    for year in years:
        try:
            df = load_data(upbit_db, binance_db, f"{year}-01-01", f"{year}-12-31")
            if len(df) < 100:
                continue
            result = run_backtest(config, df)
            results.append((year, result))
            print_result(result, f"{year} Kimchi Hedge")
        except Exception as e:
            print(f"⚠️ {year}: {e}")

    if results:
        print(f"\n{'='*80}")
        print(f"  YEARLY SUMMARY")
        print(f"{'='*80}")
        print(f"{'Year':<6} {'Return':>8} {'Trades':>8} {'Win%':>7} {'Premium':>10} {'Net P&L':>12}")
        print(f"{'-'*80}")
        for year, r in results:
            print(f"{year:<6} {r.total_return_pct:>+7.1f}% {r.total_trades:>8} {r.win_rate_pct:>6.0f}% {r.avg_premium_captured:>+9.2f}% ${r.net_pnl:>+10,.0f}")


def main():
    parser = argparse.ArgumentParser(description="Kimchi Premium Hedge Module Backtester")
    parser.add_argument("--start", type=str, default="2020-01-01")
    parser.add_argument("--end", type=str, default=None)
    parser.add_argument("--by-year", action="store_true")
    parser.add_argument("--entry-premium", type=float, default=5.0)
    parser.add_argument("--exit-premium", type=float, default=2.0)
    parser.add_argument("--margin", type=float, default=10_000)
    parser.add_argument("--no-regime-gate", action="store_true",
                       help="Disable regime gating (hedge in all regimes including BULL)")

    args = parser.parse_args()

    project_root = Path(__file__).parent.parent
    upbit_db = project_root / "data" / "upbit_bitcoin.db"
    binance_db = project_root / "data" / "binance_bitcoin.db"

    config = KimchiHedgeConfig(
        binance_margin_usdt=args.margin,
        hedge_entry_premium=args.entry_premium,
        hedge_exit_premium=args.exit_premium,
        use_regime_gating=not args.no_regime_gate,
    )

    print(f"\n🔄 Kimchi Premium Hedge Module")
    print(f"   Purpose: Hedge Upbit longs when premium is high")
    print(f"   Capital: ${config.binance_margin_usdt:,.0f} USDT (margin for shorts)")
    print(f"   Entry:   Premium >= {config.hedge_entry_premium}%")
    print(f"   Exit:    Premium <= {config.hedge_exit_premium}%")
    if config.use_regime_gating:
        print(f"   Regime:  Only hedge in BEAR/SIDEWAYS (skip BULL)")
    else:
        print(f"   Regime:  Hedge in ALL regimes (no gating)")

    if args.by_year:
        run_by_year(config, upbit_db, binance_db)
    else:
        end_date = args.end or datetime.now().strftime("%Y-%m-%d")
        df = load_data(upbit_db, binance_db, args.start, end_date)
        print(f"   Data:    {len(df):,} hours")
        result = run_backtest(config, df)
        print_result(result)


if __name__ == "__main__":
    main()
