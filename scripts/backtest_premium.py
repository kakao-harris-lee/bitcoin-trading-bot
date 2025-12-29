#!/usr/bin/env python3
"""
Kimchi Premium Hedge Strategy Backtester

Backtests the premium-based hedging strategy:
- Upbit: Long BTC position (KRW)
- Binance: Short BTC position (USDT) as hedge
- Dynamic hedge ratio based on premium conditions

Usage:
    python scripts/backtest_premium.py
    python scripts/backtest_premium.py --start 2024-01-01 --end 2024-12-31
    python scripts/backtest_premium.py --by-year
"""

from __future__ import annotations

import argparse
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd


# ==============================================================================
# Configuration
# ==============================================================================

@dataclass
class PremiumBacktestConfig:
    """Backtest configuration."""
    # Capital
    upbit_capital_krw: float = 10_000_000  # 10M KRW
    binance_capital_usdt: float = 10_000   # 10K USDT

    # Exchange rate (for combined equity calculation)
    usd_krw_rate: float = 1450.0

    # Strategy mode: "hedge", "mean_reversion", or "arbitrage"
    strategy_mode: str = "mean_reversion"  # Best risk-adjusted performance

    # Regime-aware (only for hedge mode)
    hedge_in_bull: bool = False
    hedge_in_sideways: bool = True
    hedge_in_bear: bool = True

    # Mean-reversion thresholds (trade premium spread)
    mr_short_entry: float = 5.0       # Short Binance when premium > 5%
    mr_short_exit: float = 2.0        # Close short when premium < 2%
    mr_long_entry: float = -3.0       # Long Binance when premium < -3%
    mr_long_exit: float = 0.0         # Close long when premium > 0%
    mr_position_size: float = 0.3     # Use 30% of Binance capital per trade

    # Legacy hedge settings
    premium_high: float = 5.0
    premium_elevated: float = 3.0
    premium_low: float = 0.0
    premium_negative: float = -3.0
    hedge_ratio_high: float = 0.5
    hedge_ratio_elevated: float = 0.3
    hedge_ratio_normal: float = 0.0
    hedge_ratio_low: float = 0.0

    # Trading costs
    upbit_fee: float = 0.0005    # 0.05%
    binance_fee: float = 0.0004  # 0.04%
    slippage: float = 0.0002     # 0.02%

    # Funding rate (8h average for shorts)
    avg_funding_rate: float = 0.0001  # 0.01% per 8h

    # Rebalance frequency
    rebalance_hours: int = 24  # Rebalance hedge every 24 hours (reduce trading)


# ==============================================================================
# Data Loading
# ==============================================================================

def load_premium_data(
    upbit_db: Path,
    binance_db: Path,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    timeframe: str = "minute60",
) -> pd.DataFrame:
    """
    Load and align Upbit and Binance data for premium calculation.

    Returns DataFrame with columns:
    - timestamp, upbit_price (KRW), binance_price (USD), premium_pct
    """
    # Connect to databases
    upbit_conn = sqlite3.connect(str(upbit_db))
    binance_conn = sqlite3.connect(str(binance_db))

    # Build date filter
    date_filter = ""
    if start_date:
        date_filter += f" AND timestamp >= '{start_date}'"
    if end_date:
        date_filter += f" AND timestamp <= '{end_date}'"

    # Load Upbit data (KRW)
    upbit_table = f"bitcoin_{timeframe}"
    upbit_df = pd.read_sql(f"""
        SELECT timestamp, trade_price as upbit_price
        FROM {upbit_table}
        WHERE 1=1 {date_filter}
        ORDER BY timestamp
    """, upbit_conn)

    # Load Binance data (USD)
    binance_table = f"binance_{timeframe}"
    binance_df = pd.read_sql(f"""
        SELECT timestamp, close as binance_price
        FROM {binance_table}
        WHERE 1=1 {date_filter}
        ORDER BY timestamp
    """, binance_conn)

    upbit_conn.close()
    binance_conn.close()

    # Merge on timestamp (inner join - only aligned data)
    df = pd.merge(upbit_df, binance_df, on='timestamp', how='inner')

    if df.empty:
        raise ValueError("No aligned data found. Check date range and database.")

    # Calculate premium percentage
    # Premium = (Upbit_KRW / (Binance_USD * USD_KRW_rate) - 1) * 100
    # We'll use implied rate from the data
    df['implied_rate'] = df['upbit_price'] / df['binance_price']

    # Use rolling median of implied rate as reference (to filter noise)
    df['base_rate'] = df['implied_rate'].rolling(window=24*7, min_periods=24).median()
    df['base_rate'] = df['base_rate'].fillna(df['implied_rate'].iloc[:24*7].median())

    # Premium = deviation from base rate
    df['premium_pct'] = ((df['implied_rate'] / df['base_rate']) - 1) * 100

    # Convert timestamp to datetime
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df = df.set_index('timestamp')

    # Add regime classification (simple SMA-based)
    # BULL: price > SMA50 > SMA200
    # BEAR: price < SMA50 < SMA200
    # SIDEWAYS: otherwise
    df['sma50'] = df['upbit_price'].rolling(window=50).mean()
    df['sma200'] = df['upbit_price'].rolling(window=200).mean()

    def classify_regime(row):
        price = row['upbit_price']
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
# Hedge Strategy
# ==============================================================================

@dataclass
class Position:
    """Track position state."""
    # Upbit (Long)
    upbit_btc: float = 0.0
    upbit_entry_price: float = 0.0
    upbit_cash_krw: float = 0.0

    # Binance (Short)
    binance_short_btc: float = 0.0
    binance_entry_price: float = 0.0
    binance_margin_usdt: float = 0.0
    binance_cash_usdt: float = 0.0


@dataclass
class Trade:
    """Record a trade."""
    timestamp: datetime
    exchange: str
    side: str  # "buy", "sell", "short", "cover"
    price: float
    size: float
    fee: float
    reason: str


class PremiumMeanReversionStrategy:
    """
    Premium mean-reversion strategy.

    - Holds Upbit BTC as base position
    - Trades Binance based on premium mean-reversion:
      - Short when premium is high (expect reversion)
      - Long when premium is negative (expect reversion)
    """

    def __init__(self, config: PremiumBacktestConfig):
        self.config = config
        self.position = Position(
            upbit_cash_krw=config.upbit_capital_krw,
            binance_cash_usdt=config.binance_capital_usdt,
        )
        self.trades: List[Trade] = []
        self.equity_history: List[Dict] = []
        self.binance_position: str = "none"  # "none", "short", "long"

    def calculate_equity(
        self,
        upbit_price_krw: float,
        binance_price_usd: float,
    ) -> Dict:
        """Calculate current portfolio equity."""
        cfg = self.config
        pos = self.position

        # Upbit equity
        upbit_btc_value = pos.upbit_btc * upbit_price_krw
        upbit_equity = pos.upbit_cash_krw + upbit_btc_value

        # Binance equity
        if pos.binance_short_btc > 0:
            short_pnl = (pos.binance_entry_price - binance_price_usd) * pos.binance_short_btc
        else:
            short_pnl = 0.0

        binance_equity = pos.binance_cash_usdt + pos.binance_margin_usdt + short_pnl
        combined_krw = upbit_equity + (binance_equity * cfg.usd_krw_rate)

        return {
            "upbit_equity_krw": upbit_equity,
            "binance_equity_usdt": binance_equity,
            "combined_equity_krw": combined_krw,
            "upbit_btc": pos.upbit_btc,
            "binance_short_btc": pos.binance_short_btc,
            "short_pnl_usdt": short_pnl,
        }

    def rebalance(
        self,
        timestamp: datetime,
        upbit_price_krw: float,
        binance_price_usd: float,
        premium_pct: float,
        regime: str,
    ) -> List[Trade]:
        """Execute mean-reversion trades based on premium."""
        cfg = self.config
        pos = self.position
        trades = []

        # Initial Upbit buy (hold BTC as base)
        if pos.upbit_btc == 0:
            buy_amount_krw = pos.upbit_cash_krw * 0.95
            fee = buy_amount_krw * (cfg.upbit_fee + cfg.slippage)
            btc_bought = (buy_amount_krw - fee) / upbit_price_krw
            pos.upbit_btc = btc_bought
            pos.upbit_entry_price = upbit_price_krw
            pos.upbit_cash_krw -= buy_amount_krw
            trades.append(Trade(timestamp, "upbit", "buy", upbit_price_krw, btc_bought, fee, "initial"))

        # Mean-reversion logic
        if self.binance_position == "none":
            # Check for entry signals
            if premium_pct >= cfg.mr_short_entry:
                # High premium - short Binance (expect premium to shrink)
                size_usdt = pos.binance_cash_usdt * cfg.mr_position_size
                size_btc = size_usdt / binance_price_usd
                fee = size_usdt * (cfg.binance_fee + cfg.slippage)

                pos.binance_short_btc = size_btc
                pos.binance_entry_price = binance_price_usd
                pos.binance_margin_usdt = size_usdt
                pos.binance_cash_usdt -= size_usdt + fee
                self.binance_position = "short"

                trades.append(Trade(
                    timestamp, "binance", "short", binance_price_usd, size_btc, fee,
                    f"MR short entry (premium={premium_pct:.1f}%)"
                ))

            elif premium_pct <= cfg.mr_long_entry:
                # Negative premium - this is unusual, could go long
                # But for now, just track it
                pass

        elif self.binance_position == "short":
            # Check for exit signal
            if premium_pct <= cfg.mr_short_exit:
                # Premium reverted - close short
                size_btc = pos.binance_short_btc
                size_usdt = size_btc * binance_price_usd
                fee = size_usdt * (cfg.binance_fee + cfg.slippage)
                pnl = (pos.binance_entry_price - binance_price_usd) * size_btc

                pos.binance_cash_usdt += pos.binance_margin_usdt + pnl - fee
                pos.binance_margin_usdt = 0
                pos.binance_short_btc = 0
                self.binance_position = "none"

                trades.append(Trade(
                    timestamp, "binance", "cover", binance_price_usd, size_btc, fee,
                    f"MR short exit (premium={premium_pct:.1f}%, pnl=${pnl:.2f})"
                ))

        return trades

    def apply_funding(self, hours: int, binance_price_usd: float) -> float:
        if self.position.binance_short_btc <= 0:
            return 0.0
        funding_periods = hours / 8
        funding_cost = (
            self.position.binance_short_btc *
            binance_price_usd *
            self.config.avg_funding_rate *
            funding_periods
        )
        self.position.binance_cash_usdt -= funding_cost
        return funding_cost


class PremiumArbitrageStrategy:
    """
    Pure premium arbitrage - market neutral spread trading.

    - No directional BTC exposure
    - When premium HIGH: Long Upbit + Short Binance (lock in premium)
    - When premium NORMAL: Close all positions
    - Profit from premium convergence, not BTC direction
    """

    def __init__(self, config: PremiumBacktestConfig):
        self.config = config
        self.position = Position(
            upbit_cash_krw=config.upbit_capital_krw,
            binance_cash_usdt=config.binance_capital_usdt,
        )
        self.trades: List[Trade] = []
        self.equity_history: List[Dict] = []
        self.in_trade: bool = False
        self.entry_premium: float = 0.0

    def calculate_equity(
        self,
        upbit_price_krw: float,
        binance_price_usd: float,
    ) -> Dict:
        cfg = self.config
        pos = self.position

        upbit_btc_value = pos.upbit_btc * upbit_price_krw
        upbit_equity = pos.upbit_cash_krw + upbit_btc_value

        if pos.binance_short_btc > 0:
            short_pnl = (pos.binance_entry_price - binance_price_usd) * pos.binance_short_btc
        else:
            short_pnl = 0.0

        binance_equity = pos.binance_cash_usdt + pos.binance_margin_usdt + short_pnl
        combined_krw = upbit_equity + (binance_equity * cfg.usd_krw_rate)

        return {
            "upbit_equity_krw": upbit_equity,
            "binance_equity_usdt": binance_equity,
            "combined_equity_krw": combined_krw,
            "upbit_btc": pos.upbit_btc,
            "binance_short_btc": pos.binance_short_btc,
            "short_pnl_usdt": short_pnl,
        }

    def rebalance(
        self,
        timestamp: datetime,
        upbit_price_krw: float,
        binance_price_usd: float,
        premium_pct: float,
        regime: str,
    ) -> List[Trade]:
        """Execute arbitrage trades."""
        cfg = self.config
        pos = self.position
        trades = []

        if not self.in_trade:
            # Look for entry when premium is high
            if premium_pct >= cfg.mr_short_entry:
                # Enter spread: Long Upbit + Short Binance
                # Use 50% of each capital
                upbit_amount = pos.upbit_cash_krw * 0.5
                binance_amount = pos.binance_cash_usdt * 0.5

                # Long Upbit
                fee1 = upbit_amount * (cfg.upbit_fee + cfg.slippage)
                btc_bought = (upbit_amount - fee1) / upbit_price_krw
                pos.upbit_btc = btc_bought
                pos.upbit_entry_price = upbit_price_krw
                pos.upbit_cash_krw -= upbit_amount
                trades.append(Trade(timestamp, "upbit", "buy", upbit_price_krw, btc_bought, fee1,
                    f"Arb entry LONG (premium={premium_pct:.1f}%)"))

                # Short Binance (same BTC amount for market neutral)
                short_btc = btc_bought
                short_usdt = short_btc * binance_price_usd
                if short_usdt > binance_amount:
                    short_btc = binance_amount / binance_price_usd
                    short_usdt = binance_amount

                fee2 = short_usdt * (cfg.binance_fee + cfg.slippage)
                pos.binance_short_btc = short_btc
                pos.binance_entry_price = binance_price_usd
                pos.binance_margin_usdt = short_usdt
                pos.binance_cash_usdt -= short_usdt + fee2
                trades.append(Trade(timestamp, "binance", "short", binance_price_usd, short_btc, fee2,
                    f"Arb entry SHORT (premium={premium_pct:.1f}%)"))

                self.in_trade = True
                self.entry_premium = premium_pct

        else:
            # Look for exit when premium normalizes
            if premium_pct <= cfg.mr_short_exit:
                # Exit spread: Sell Upbit + Cover Binance
                # Sell Upbit
                sell_value = pos.upbit_btc * upbit_price_krw
                fee1 = sell_value * (cfg.upbit_fee + cfg.slippage)
                trades.append(Trade(timestamp, "upbit", "sell", upbit_price_krw, pos.upbit_btc, fee1,
                    f"Arb exit SELL (premium={premium_pct:.1f}%)"))
                pos.upbit_cash_krw += sell_value - fee1
                pos.upbit_btc = 0

                # Cover Binance
                cover_value = pos.binance_short_btc * binance_price_usd
                fee2 = cover_value * (cfg.binance_fee + cfg.slippage)
                pnl = (pos.binance_entry_price - binance_price_usd) * pos.binance_short_btc
                trades.append(Trade(timestamp, "binance", "cover", binance_price_usd, pos.binance_short_btc, fee2,
                    f"Arb exit COVER (pnl=${pnl:.2f})"))
                pos.binance_cash_usdt += pos.binance_margin_usdt + pnl - fee2
                pos.binance_margin_usdt = 0
                pos.binance_short_btc = 0

                self.in_trade = False
                self.entry_premium = 0.0

        return trades

    def apply_funding(self, hours: int, binance_price_usd: float) -> float:
        if self.position.binance_short_btc <= 0:
            return 0.0
        funding_cost = (
            self.position.binance_short_btc *
            binance_price_usd *
            self.config.avg_funding_rate *
            (hours / 8)
        )
        self.position.binance_cash_usdt -= funding_cost
        return funding_cost


class PremiumHedgeStrategy:
    """
    Premium-based hedge strategy.

    - Maintains long exposure on Upbit
    - Dynamically adjusts short hedge on Binance based on premium
    """

    def __init__(self, config: PremiumBacktestConfig):
        self.config = config
        self.position = Position(
            upbit_cash_krw=config.upbit_capital_krw,
            binance_cash_usdt=config.binance_capital_usdt,
        )
        self.trades: List[Trade] = []
        self.equity_history: List[Dict] = []

    def get_target_hedge_ratio(self, premium_pct: float, regime: str) -> float:
        """Determine target hedge ratio based on premium and regime."""
        cfg = self.config

        # Check if hedging is allowed in current regime
        if regime == 'BULL' and not cfg.hedge_in_bull:
            return 0.0
        elif regime == 'SIDEWAYS' and not cfg.hedge_in_sideways:
            return 0.0
        elif regime == 'BEAR' and not cfg.hedge_in_bear:
            return 0.0

        # Premium-based hedge ratio
        if premium_pct >= cfg.premium_high:
            return cfg.hedge_ratio_high
        elif premium_pct >= cfg.premium_elevated:
            # Linear interpolation between elevated and high
            ratio = (premium_pct - cfg.premium_elevated) / (cfg.premium_high - cfg.premium_elevated)
            return cfg.hedge_ratio_elevated + ratio * (cfg.hedge_ratio_high - cfg.hedge_ratio_elevated)
        elif premium_pct >= cfg.premium_low:
            # Linear interpolation between normal and elevated
            ratio = (premium_pct - cfg.premium_low) / (cfg.premium_elevated - cfg.premium_low)
            return cfg.hedge_ratio_normal + ratio * (cfg.hedge_ratio_elevated - cfg.hedge_ratio_normal)
        elif premium_pct >= cfg.premium_negative:
            # Linear interpolation down to zero
            ratio = (premium_pct - cfg.premium_negative) / (cfg.premium_low - cfg.premium_negative)
            return cfg.hedge_ratio_low + ratio * (cfg.hedge_ratio_normal - cfg.hedge_ratio_low)
        else:
            return cfg.hedge_ratio_low

    def calculate_equity(
        self,
        upbit_price_krw: float,
        binance_price_usd: float,
    ) -> Dict:
        """Calculate current portfolio equity."""
        cfg = self.config
        pos = self.position

        # Upbit equity (KRW)
        upbit_btc_value = pos.upbit_btc * upbit_price_krw
        upbit_equity = pos.upbit_cash_krw + upbit_btc_value

        # Binance equity (USDT)
        # Short P&L = (entry_price - current_price) * size
        if pos.binance_short_btc > 0:
            short_pnl = (pos.binance_entry_price - binance_price_usd) * pos.binance_short_btc
        else:
            short_pnl = 0.0
        binance_equity = pos.binance_cash_usdt + pos.binance_margin_usdt + short_pnl

        # Combined equity (in KRW)
        combined_krw = upbit_equity + (binance_equity * cfg.usd_krw_rate)

        return {
            "upbit_equity_krw": upbit_equity,
            "binance_equity_usdt": binance_equity,
            "combined_equity_krw": combined_krw,
            "upbit_btc": pos.upbit_btc,
            "binance_short_btc": pos.binance_short_btc,
            "short_pnl_usdt": short_pnl,
        }

    def rebalance(
        self,
        timestamp: datetime,
        upbit_price_krw: float,
        binance_price_usd: float,
        premium_pct: float,
        regime: str,
    ) -> List[Trade]:
        """Rebalance positions based on premium and regime."""
        cfg = self.config
        pos = self.position
        trades = []

        # Step 1: Ensure we have Upbit long position (use 95% of capital)
        target_upbit_exposure = 0.95
        current_upbit_value = pos.upbit_btc * upbit_price_krw
        current_upbit_exposure = current_upbit_value / (pos.upbit_cash_krw + current_upbit_value) if (pos.upbit_cash_krw + current_upbit_value) > 0 else 0

        if pos.upbit_btc == 0:
            # Initial buy
            buy_amount_krw = pos.upbit_cash_krw * target_upbit_exposure
            fee = buy_amount_krw * (cfg.upbit_fee + cfg.slippage)
            btc_bought = (buy_amount_krw - fee) / upbit_price_krw

            pos.upbit_btc = btc_bought
            pos.upbit_entry_price = upbit_price_krw
            pos.upbit_cash_krw -= buy_amount_krw

            trades.append(Trade(
                timestamp=timestamp,
                exchange="upbit",
                side="buy",
                price=upbit_price_krw,
                size=btc_bought,
                fee=fee,
                reason="initial_entry",
            ))

        # Step 2: Adjust Binance short hedge (regime-aware)
        target_hedge_ratio = self.get_target_hedge_ratio(premium_pct, regime)

        # Target short size = Upbit BTC * hedge_ratio
        target_short_btc = pos.upbit_btc * target_hedge_ratio
        current_short_btc = pos.binance_short_btc

        # Only rebalance if difference is significant (>5% of position)
        size_diff = target_short_btc - current_short_btc
        if abs(size_diff) > 0.05 * max(target_short_btc, current_short_btc, 0.001):

            if size_diff > 0:
                # Need to short more
                short_value_usdt = size_diff * binance_price_usd
                fee = short_value_usdt * (cfg.binance_fee + cfg.slippage)

                # Check if we have enough margin (use 50% for shorts)
                available_margin = pos.binance_cash_usdt * 0.5
                if short_value_usdt > available_margin:
                    size_diff = available_margin / binance_price_usd
                    short_value_usdt = size_diff * binance_price_usd
                    fee = short_value_usdt * (cfg.binance_fee + cfg.slippage)

                if size_diff > 0:
                    # Update position (weighted average entry)
                    if pos.binance_short_btc > 0:
                        total_value = (pos.binance_short_btc * pos.binance_entry_price +
                                      size_diff * binance_price_usd)
                        pos.binance_entry_price = total_value / (pos.binance_short_btc + size_diff)
                    else:
                        pos.binance_entry_price = binance_price_usd

                    pos.binance_short_btc += size_diff
                    pos.binance_margin_usdt += short_value_usdt
                    pos.binance_cash_usdt -= short_value_usdt + fee

                    trades.append(Trade(
                        timestamp=timestamp,
                        exchange="binance",
                        side="short",
                        price=binance_price_usd,
                        size=size_diff,
                        fee=fee,
                        reason=f"hedge_increase (premium={premium_pct:.1f}%)",
                    ))

            elif size_diff < 0:
                # Need to cover some shorts
                cover_size = min(abs(size_diff), pos.binance_short_btc)
                if cover_size > 0:
                    cover_value_usdt = cover_size * binance_price_usd
                    fee = cover_value_usdt * (cfg.binance_fee + cfg.slippage)

                    # Realize P&L
                    pnl = (pos.binance_entry_price - binance_price_usd) * cover_size

                    # Return margin proportionally
                    margin_returned = pos.binance_margin_usdt * (cover_size / pos.binance_short_btc)

                    pos.binance_short_btc -= cover_size
                    pos.binance_margin_usdt -= margin_returned
                    pos.binance_cash_usdt += margin_returned + pnl - fee

                    trades.append(Trade(
                        timestamp=timestamp,
                        exchange="binance",
                        side="cover",
                        price=binance_price_usd,
                        size=cover_size,
                        fee=fee,
                        reason=f"hedge_decrease (premium={premium_pct:.1f}%, pnl={pnl:.2f})",
                    ))

        return trades

    def apply_funding(self, hours: int, binance_price_usd: float) -> float:
        """Apply funding rate cost for shorts."""
        if self.position.binance_short_btc <= 0:
            return 0.0

        # Funding is paid every 8 hours
        funding_periods = hours / 8
        funding_cost = (
            self.position.binance_short_btc *
            binance_price_usd *
            self.config.avg_funding_rate *
            funding_periods
        )

        self.position.binance_cash_usdt -= funding_cost
        return funding_cost


# ==============================================================================
# Backtester
# ==============================================================================

@dataclass
class BacktestResult:
    """Backtest results."""
    start_date: str
    end_date: str

    # Returns
    total_return_pct: float
    upbit_only_return_pct: float
    binance_only_return_pct: float

    # Risk metrics
    max_drawdown_pct: float
    sharpe_ratio: float
    sortino_ratio: float

    # Premium stats
    avg_premium_pct: float
    max_premium_pct: float
    min_premium_pct: float

    # Trading stats
    total_trades: int
    total_fees: float
    total_funding_cost: float
    avg_hedge_ratio: float

    # Equity curve
    equity_df: pd.DataFrame = field(default_factory=pd.DataFrame)


def run_backtest(
    config: PremiumBacktestConfig,
    df: pd.DataFrame,
) -> BacktestResult:
    """Run premium strategy backtest."""

    # Select strategy based on mode
    if config.strategy_mode == "arbitrage":
        strategy = PremiumArbitrageStrategy(config)
    elif config.strategy_mode == "mean_reversion":
        strategy = PremiumMeanReversionStrategy(config)
    else:
        strategy = PremiumHedgeStrategy(config)

    rebalance_counter = 0
    funding_counter = 0
    total_funding_cost = 0.0
    hedge_ratios = []

    for timestamp, row in df.iterrows():
        upbit_price = row['upbit_price']
        binance_price = row['binance_price']
        premium = row['premium_pct']
        regime = row['regime']

        # Rebalance every N hours
        if rebalance_counter % config.rebalance_hours == 0:
            trades = strategy.rebalance(
                timestamp=timestamp,
                upbit_price_krw=upbit_price,
                binance_price_usd=binance_price,
                premium_pct=premium,
                regime=regime,
            )
            strategy.trades.extend(trades)

        # Apply funding every hour
        funding_counter += 1
        if funding_counter >= 1:
            funding_cost = strategy.apply_funding(1, binance_price)
            total_funding_cost += funding_cost
            funding_counter = 0

        # Record equity
        equity = strategy.calculate_equity(upbit_price, binance_price)
        equity['timestamp'] = timestamp
        equity['premium_pct'] = premium
        equity['regime'] = regime
        equity['upbit_price'] = upbit_price
        equity['binance_price'] = binance_price

        if strategy.position.upbit_btc > 0:
            hedge_ratio = strategy.position.binance_short_btc / strategy.position.upbit_btc
        else:
            hedge_ratio = 0.0
        equity['hedge_ratio'] = hedge_ratio
        hedge_ratios.append(hedge_ratio)

        strategy.equity_history.append(equity)
        rebalance_counter += 1

    # Convert to DataFrame
    equity_df = pd.DataFrame(strategy.equity_history)
    equity_df = equity_df.set_index('timestamp')

    # Calculate metrics
    initial_equity = config.upbit_capital_krw + config.binance_capital_usdt * config.usd_krw_rate
    final_equity = equity_df['combined_equity_krw'].iloc[-1]
    total_return_pct = (final_equity / initial_equity - 1) * 100

    # Upbit-only return (buy and hold)
    upbit_start_price = df['upbit_price'].iloc[0]
    upbit_end_price = df['upbit_price'].iloc[-1]
    upbit_only_return_pct = (upbit_end_price / upbit_start_price - 1) * 100

    # Binance-only return (no position)
    binance_only_return_pct = 0.0  # Cash stays as cash

    # Maximum drawdown
    equity_series = equity_df['combined_equity_krw']
    rolling_max = equity_series.expanding().max()
    drawdown = (equity_series - rolling_max) / rolling_max * 100
    max_drawdown_pct = drawdown.min()

    # Sharpe ratio (assuming hourly data)
    returns = equity_series.pct_change().dropna()
    if len(returns) > 0 and returns.std() > 0:
        # Annualize: 24 hours * 365 days
        sharpe_ratio = (returns.mean() / returns.std()) * np.sqrt(24 * 365)
    else:
        sharpe_ratio = 0.0

    # Sortino ratio
    negative_returns = returns[returns < 0]
    if len(negative_returns) > 0 and negative_returns.std() > 0:
        sortino_ratio = (returns.mean() / negative_returns.std()) * np.sqrt(24 * 365)
    else:
        sortino_ratio = sharpe_ratio

    # Premium stats
    premium_series = df['premium_pct']

    # Trading stats
    total_trades = len(strategy.trades)
    total_fees = sum(t.fee for t in strategy.trades)

    return BacktestResult(
        start_date=df.index[0].strftime("%Y-%m-%d"),
        end_date=df.index[-1].strftime("%Y-%m-%d"),
        total_return_pct=round(total_return_pct, 2),
        upbit_only_return_pct=round(upbit_only_return_pct, 2),
        binance_only_return_pct=round(binance_only_return_pct, 2),
        max_drawdown_pct=round(max_drawdown_pct, 2),
        sharpe_ratio=round(sharpe_ratio, 2),
        sortino_ratio=round(sortino_ratio, 2),
        avg_premium_pct=round(premium_series.mean(), 2),
        max_premium_pct=round(premium_series.max(), 2),
        min_premium_pct=round(premium_series.min(), 2),
        total_trades=total_trades,
        total_fees=round(total_fees, 2),
        total_funding_cost=round(total_funding_cost, 2),
        avg_hedge_ratio=round(np.mean(hedge_ratios), 2) if hedge_ratios else 0.0,
        equity_df=equity_df,
    )


def print_result(result: BacktestResult, title: str = "Backtest Result") -> None:
    """Print backtest results."""
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"  Period: {result.start_date} ~ {result.end_date}")
    print(f"{'='*60}")

    print(f"\n📈 Returns:")
    print(f"   Hedge Strategy:  {result.total_return_pct:+.2f}%")
    print(f"   Upbit Only:      {result.upbit_only_return_pct:+.2f}%")
    print(f"   Outperformance:  {result.total_return_pct - result.upbit_only_return_pct:+.2f}%")

    print(f"\n📊 Risk Metrics:")
    print(f"   Max Drawdown:    {result.max_drawdown_pct:.2f}%")
    print(f"   Sharpe Ratio:    {result.sharpe_ratio:.2f}")
    print(f"   Sortino Ratio:   {result.sortino_ratio:.2f}")

    print(f"\n💱 Premium Stats:")
    print(f"   Average:         {result.avg_premium_pct:+.2f}%")
    print(f"   Range:           {result.min_premium_pct:+.2f}% ~ {result.max_premium_pct:+.2f}%")
    print(f"   Avg Hedge Ratio: {result.avg_hedge_ratio:.1%}")

    print(f"\n💰 Costs:")
    print(f"   Total Trades:    {result.total_trades}")
    print(f"   Total Fees:      ${result.total_fees:,.2f}")
    print(f"   Funding Cost:    ${result.total_funding_cost:,.2f}")


def run_by_year(
    config: PremiumBacktestConfig,
    upbit_db: Path,
    binance_db: Path,
) -> None:
    """Run backtests year by year."""
    years = [2020, 2021, 2022, 2023, 2024, 2025]
    results = []

    for year in years:
        start = f"{year}-01-01"
        end = f"{year}-12-31"

        try:
            df = load_premium_data(upbit_db, binance_db, start, end)
            if len(df) < 100:
                print(f"⚠️  {year}: Insufficient data ({len(df)} rows)")
                continue

            result = run_backtest(config, df)
            results.append((year, result))
            print_result(result, f"{year} Backtest")

        except Exception as e:
            print(f"⚠️  {year}: {e}")

    # Summary table
    if results:
        print(f"\n{'='*80}")
        print(f"  YEARLY SUMMARY")
        print(f"{'='*80}")
        print(f"{'Year':<6} {'Strategy':>10} {'Upbit Only':>12} {'Outperf':>10} {'MDD':>8} {'Sharpe':>8} {'Avg Premium':>12}")
        print(f"{'-'*80}")

        for year, r in results:
            outperf = r.total_return_pct - r.upbit_only_return_pct
            print(f"{year:<6} {r.total_return_pct:>+9.1f}% {r.upbit_only_return_pct:>+11.1f}% {outperf:>+9.1f}% {r.max_drawdown_pct:>7.1f}% {r.sharpe_ratio:>7.2f} {r.avg_premium_pct:>+11.2f}%")


# ==============================================================================
# Main
# ==============================================================================

def main():
    parser = argparse.ArgumentParser(description="Kimchi Premium Hedge Strategy Backtester")
    parser.add_argument("--start", type=str, default="2020-01-01", help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", type=str, default=None, help="End date (YYYY-MM-DD)")
    parser.add_argument("--by-year", action="store_true", help="Run year-by-year analysis")
    parser.add_argument("--upbit-capital", type=float, default=10_000_000, help="Upbit capital (KRW)")
    parser.add_argument("--binance-capital", type=float, default=10_000, help="Binance capital (USDT)")

    args = parser.parse_args()

    # Paths
    project_root = Path(__file__).parent.parent
    upbit_db = project_root / "data" / "upbit_bitcoin.db"
    binance_db = project_root / "data" / "binance_bitcoin.db"

    # Verify databases exist
    if not upbit_db.exists():
        print(f"❌ Upbit DB not found: {upbit_db}")
        return
    if not binance_db.exists():
        print(f"❌ Binance DB not found: {binance_db}")
        return

    # Config
    config = PremiumBacktestConfig(
        upbit_capital_krw=args.upbit_capital,
        binance_capital_usdt=args.binance_capital,
    )

    print(f"\n🚀 Kimchi Premium Hedge Strategy Backtester")
    print(f"   Upbit Capital:   {config.upbit_capital_krw:,.0f} KRW")
    print(f"   Binance Capital: {config.binance_capital_usdt:,.0f} USDT")

    if args.by_year:
        run_by_year(config, upbit_db, binance_db)
    else:
        # Single period backtest
        end_date = args.end or datetime.now().strftime("%Y-%m-%d")

        print(f"   Period: {args.start} ~ {end_date}")

        df = load_premium_data(upbit_db, binance_db, args.start, end_date)
        print(f"   Data points: {len(df):,}")

        result = run_backtest(config, df)
        print_result(result)


if __name__ == "__main__":
    main()
