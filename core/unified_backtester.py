"""
Unified Backtesting Framework.

This module provides a comprehensive backtesting framework that simulates
the complete trading system including:
- RegimeRouter for market state classification (BULL/SIDEWAYS/BEAR)
- Strategy selection based on regime (V35 for BULL, VA02 for SIDEWAYS, Short_V1 for BEAR)
- Position management with realistic costs (fees, slippage)
- Premium arbitrage overlay (Kimchi premium hedging)
- Combined P&L calculation in KRW
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

import numpy as np
import pandas as pd

from trading.strategy.regime_router import RegimeRouter


# Project paths
_PROJECT_ROOT = Path(__file__).parent.parent
_DATA_DIR = _PROJECT_ROOT / "data"


@dataclass
class BacktestConfig:
    """Configuration for unified backtesting."""

    start_date: str
    end_date: str
    upbit_capital_krw: float = 10_000_000
    binance_capital_usdt: float = 10_000
    assets: List[str] = field(default_factory=lambda: ["BTC"])
    enable_long: bool = True
    enable_short: bool = True
    enable_premium_arb: bool = True
    upbit_fee: float = 0.0005  # 0.05%
    binance_fee: float = 0.0004  # 0.04%
    slippage: float = 0.0002  # 0.02%
    premium_entry_threshold: float = 5.0
    premium_exit_threshold: float = 2.0
    timeframe: str = "day"

    # Strategy parameters
    long_fraction: float = 0.5  # 50% of capital for long
    short_fraction: float = 0.3  # 30% of capital for short
    take_profit_pct: float = 5.0  # 5% TP
    stop_loss_pct: float = 2.0  # 2% SL


@dataclass
class Trade:
    """Record of a completed trade."""

    asset: str
    side: Literal["long", "short"]
    entry_time: datetime
    entry_price: float
    exit_time: Optional[datetime] = None
    exit_price: Optional[float] = None
    quantity: float = 0.0
    pnl: float = 0.0
    pnl_pct: float = 0.0
    exit_reason: str = ""


@dataclass
class PositionState:
    """Current state of a position."""

    asset: str
    side: Literal["long", "short"]
    quantity: float
    entry_price: float
    entry_time: datetime
    exchange: Literal["upbit", "binance"]


class UnifiedBacktester:
    """
    Unified backtesting engine that simulates the complete trading system.

    Features:
    - Regime-based strategy selection (BULL -> long, BEAR -> short)
    - Realistic cost modeling (fees + slippage)
    - Premium arbitrage overlay
    - Multi-asset support
    - KRW-denominated results
    """

    def __init__(self, config: BacktestConfig):
        """
        Initialize backtester with configuration.

        Args:
            config: BacktestConfig instance with all settings.
        """
        self.config = config

        # Capital tracking
        self.upbit_cash: float = config.upbit_capital_krw
        self.binance_cash: float = config.binance_capital_usdt
        self.initial_upbit_cash: float = config.upbit_capital_krw
        self.initial_binance_cash: float = config.binance_capital_usdt

        # Position tracking
        self.positions: Dict[str, PositionState] = {}
        self.trades: List[Trade] = []

        # Data storage
        self.upbit_data: Dict[str, pd.DataFrame] = {}
        self.binance_data: Dict[str, pd.DataFrame] = {}
        self.fx_rates: pd.DataFrame = pd.DataFrame()
        self.premium_data: Dict[str, pd.DataFrame] = {}

        # Equity curve tracking
        self.equity_history: List[Dict[str, Any]] = []

        # Initialize regime router
        self.router = RegimeRouter()

    def _load_data(self) -> None:
        """Load all required data for backtesting."""
        start = self.config.start_date
        end = self.config.end_date
        timeframe = self.config.timeframe

        # Map asset symbols to DB names
        asset_db_map = {
            "BTC": "bitcoin",
            "ETH": "ethereum",
            "SOL": "solana",
            "XRP": "xrp",
        }

        # Load Upbit data for each asset
        for asset in self.config.assets:
            db_name = asset_db_map.get(asset, asset.lower())
            upbit_db = _DATA_DIR / f"upbit_{db_name}.db"
            if upbit_db.exists():
                self.upbit_data[asset] = self._load_upbit_data(
                    upbit_db, timeframe, start, end
                )

            # Load Binance data
            binance_db = _DATA_DIR / f"binance_{db_name}.db"
            if binance_db.exists():
                self.binance_data[asset] = self._load_binance_data(
                    binance_db, timeframe, start, end
                )

            # Load premium data
            self.premium_data[asset] = self._load_premium_data(asset, start, end)

        # Load FX rates
        self.fx_rates = self._load_fx_rates(start, end)

    def _load_upbit_data(
        self, db_path: Path, timeframe: str, start: str, end: str
    ) -> pd.DataFrame:
        """Load Upbit OHLCV data from SQLite."""
        table_map = {
            "minute1": "bitcoin_minute1",
            "minute5": "bitcoin_minute5",
            "minute15": "bitcoin_minute15",
            "minute30": "bitcoin_minute30",
            "minute60": "bitcoin_minute60",
            "minute240": "bitcoin_minute240",
            "day": "bitcoin_day",
        }

        # Extract asset name from db path
        db_name = db_path.stem  # e.g., "upbit_bitcoin"
        asset_name = db_name.replace("upbit_", "")  # e.g., "bitcoin"

        # Build table name
        base_table = table_map.get(timeframe, "bitcoin_day")
        table_name = base_table.replace("bitcoin", asset_name)

        query = f"""
            SELECT timestamp, opening_price as open, high_price as high,
                   low_price as low, trade_price as close,
                   candle_acc_trade_volume as volume
            FROM {table_name}
            WHERE timestamp >= '{start}' AND timestamp <= '{end}'
            ORDER BY timestamp ASC
        """

        conn = sqlite3.connect(str(db_path))
        try:
            df = pd.read_sql_query(query, conn)
            df["timestamp"] = pd.to_datetime(df["timestamp"])
            return df
        finally:
            conn.close()

    def _load_binance_data(
        self, db_path: Path, timeframe: str, start: str, end: str
    ) -> pd.DataFrame:
        """Load Binance OHLCV data from SQLite."""
        # Extract asset name from db path (e.g., binance_ethereum -> ethereum)
        db_name = db_path.stem  # e.g., "binance_ethereum"
        asset_name = db_name.replace("binance_", "")  # e.g., "ethereum"

        # For Bitcoin, the table prefix is "binance_", for others it's the asset name
        if asset_name == "bitcoin":
            table_prefix = "binance"
        else:
            table_prefix = asset_name

        timeframe_suffix_map = {
            "minute1": "minute1",
            "minute5": "minute5",
            "minute15": "minute15",
            "minute30": "minute30",
            "minute60": "minute60",
            "minute240": "minute240",
            "day": "day",
        }

        suffix = timeframe_suffix_map.get(timeframe, "day")
        table_name = f"{table_prefix}_{suffix}"

        query = f"""
            SELECT timestamp, open, high, low, close, volume
            FROM {table_name}
            WHERE timestamp >= '{start}' AND timestamp <= '{end}'
            ORDER BY timestamp ASC
        """

        conn = sqlite3.connect(str(db_path))
        try:
            df = pd.read_sql_query(query, conn)
            df["timestamp"] = pd.to_datetime(df["timestamp"])
            return df
        except Exception:
            # Table might not exist
            return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])
        finally:
            conn.close()

    def _load_fx_rates(self, start: str, end: str) -> pd.DataFrame:
        """Load USD/KRW exchange rates."""
        fx_db = _DATA_DIR / "fx_rates.db"
        if not fx_db.exists():
            return pd.DataFrame(columns=["date", "rate"])

        query = f"""
            SELECT date, rate
            FROM usd_krw
            WHERE date >= '{start}' AND date <= '{end}'
            ORDER BY date ASC
        """

        conn = sqlite3.connect(str(fx_db))
        try:
            df = pd.read_sql_query(query, conn)
            df["date"] = pd.to_datetime(df["date"])
            return df
        finally:
            conn.close()

    def _load_premium_data(self, asset: str, start: str, end: str) -> pd.DataFrame:
        """Load premium history data."""
        premium_db = _DATA_DIR / "premium_history.db"
        if not premium_db.exists():
            return pd.DataFrame(columns=["date", "premium_pct"])

        # Map asset to table name
        table_map = {
            "BTC": "btc_premium",
            "ETH": "eth_premium",
            "SOL": "sol_premium",
            "XRP": "xrp_premium",
        }

        table_name = table_map.get(asset, f"{asset.lower()}_premium")

        query = f"""
            SELECT date, upbit_krw, binance_usd, fx_rate, premium_pct
            FROM {table_name}
            WHERE date >= '{start}' AND date <= '{end}'
            ORDER BY date ASC
        """

        conn = sqlite3.connect(str(premium_db))
        try:
            df = pd.read_sql_query(query, conn)
            df["date"] = pd.to_datetime(df["date"])
            return df
        except Exception:
            # Table might not exist for some assets
            return pd.DataFrame(columns=["date", "premium_pct"])
        finally:
            conn.close()

    def _calculate_buy_cost(
        self, exchange: str, price: float, quantity: float
    ) -> float:
        """Calculate total cost for a buy order including fees and slippage."""
        if exchange == "upbit":
            fee_rate = self.config.upbit_fee
        else:
            fee_rate = self.config.binance_fee

        # Cost = price * quantity * (1 + fee + slippage)
        total_rate = 1 + fee_rate + self.config.slippage
        return price * quantity * total_rate

    def _calculate_sell_proceeds(
        self, exchange: str, price: float, quantity: float
    ) -> float:
        """Calculate net proceeds from a sell order after fees and slippage."""
        if exchange == "upbit":
            fee_rate = self.config.upbit_fee
        else:
            fee_rate = self.config.binance_fee

        # Proceeds = price * quantity * (1 - fee - slippage)
        total_rate = 1 - fee_rate - self.config.slippage
        return price * quantity * total_rate

    def _calculate_short_entry_margin(self, price: float, quantity: float) -> float:
        """Calculate margin required to open short position."""
        notional = price * quantity
        fee = notional * self.config.binance_fee
        slippage = notional * self.config.slippage
        return notional + fee + slippage

    def _enter_long(
        self,
        asset: str,
        price: float,
        fraction: float,
        timestamp: Optional[datetime] = None,
    ) -> bool:
        """
        Enter a long position on Upbit.

        Args:
            asset: Asset symbol (e.g., "BTC")
            price: Entry price in KRW
            fraction: Fraction of available capital to use
            timestamp: Entry timestamp

        Returns:
            True if position was opened successfully.
        """
        if not self.config.enable_long:
            return False

        if asset in self.positions:
            return False  # Already have a position

        # Calculate position size
        available = self.upbit_cash * fraction
        total_cost_rate = 1 + self.config.upbit_fee + self.config.slippage
        quantity = available / (price * total_cost_rate)

        if quantity <= 0:
            return False

        # Calculate actual cost
        cost = self._calculate_buy_cost("upbit", price, quantity)

        if cost > self.upbit_cash:
            return False

        # Execute entry
        self.upbit_cash -= cost
        self.positions[asset] = PositionState(
            asset=asset,
            side="long",
            quantity=quantity,
            entry_price=price,
            entry_time=timestamp or datetime.now(),
            exchange="upbit",
        )

        # Record trade (will be completed on exit)
        self.trades.append(
            Trade(
                asset=asset,
                side="long",
                entry_time=timestamp or datetime.now(),
                entry_price=price,
                quantity=quantity,
            )
        )

        return True

    def _exit_long(
        self,
        asset: str,
        price: float,
        reason: str = "regime_change",
        timestamp: Optional[datetime] = None,
    ) -> bool:
        """
        Exit a long position on Upbit.

        Args:
            asset: Asset symbol
            price: Exit price in KRW
            reason: Exit reason
            timestamp: Exit timestamp

        Returns:
            True if position was closed successfully.
        """
        if asset not in self.positions:
            return False

        position = self.positions[asset]
        if position.side != "long":
            return False

        # Calculate proceeds
        proceeds = self._calculate_sell_proceeds("upbit", price, position.quantity)
        self.upbit_cash += proceeds

        # Calculate P&L
        entry_cost = self._calculate_buy_cost(
            "upbit", position.entry_price, position.quantity
        )
        pnl = proceeds - entry_cost
        pnl_pct = (price / position.entry_price - 1) * 100

        # Update trade record
        for trade in reversed(self.trades):
            if (
                trade.asset == asset
                and trade.side == "long"
                and trade.exit_time is None
            ):
                trade.exit_time = timestamp or datetime.now()
                trade.exit_price = price
                trade.pnl = pnl
                trade.pnl_pct = pnl_pct
                trade.exit_reason = reason
                break

        # Remove position
        del self.positions[asset]

        return True

    def _enter_short(
        self,
        asset: str,
        price: float,
        fraction: float,
        timestamp: Optional[datetime] = None,
    ) -> bool:
        """
        Enter a short position on Binance.

        Args:
            asset: Asset symbol
            price: Entry price in USDT
            fraction: Fraction of available capital to use
            timestamp: Entry timestamp

        Returns:
            True if position was opened successfully.
        """
        if not self.config.enable_short:
            return False

        key = f"{asset}_SHORT"
        if key in self.positions:
            return False

        # Calculate position size
        available = self.binance_cash * fraction
        total_cost_rate = 1 + self.config.binance_fee + self.config.slippage
        quantity = available / (price * total_cost_rate)

        if quantity <= 0:
            return False

        # Calculate margin required (simplified - no actual margin needed for simulation)
        margin = self._calculate_short_entry_margin(price, quantity)

        if margin > self.binance_cash:
            return False

        # Execute entry
        self.binance_cash -= margin
        self.positions[key] = PositionState(
            asset=asset,
            side="short",
            quantity=quantity,
            entry_price=price,
            entry_time=timestamp or datetime.now(),
            exchange="binance",
        )

        # Record trade
        self.trades.append(
            Trade(
                asset=asset,
                side="short",
                entry_time=timestamp or datetime.now(),
                entry_price=price,
                quantity=quantity,
            )
        )

        return True

    def _exit_short(
        self,
        asset: str,
        price: float,
        reason: str = "regime_change",
        timestamp: Optional[datetime] = None,
    ) -> bool:
        """
        Exit a short position on Binance.

        Args:
            asset: Asset symbol
            price: Exit price in USDT
            reason: Exit reason
            timestamp: Exit timestamp

        Returns:
            True if position was closed successfully.
        """
        key = f"{asset}_SHORT"
        if key not in self.positions:
            return False

        position = self.positions[key]

        # Calculate P&L for short (profit when price goes down)
        entry_notional = position.entry_price * position.quantity
        exit_notional = price * position.quantity
        exit_fee = exit_notional * (self.config.binance_fee + self.config.slippage)

        # Short P&L: (entry - exit) - fees
        pnl = (entry_notional - exit_notional) - exit_fee
        pnl_pct = (position.entry_price / price - 1) * 100

        # Return margin + P&L
        self.binance_cash += entry_notional + pnl

        # Update trade record
        for trade in reversed(self.trades):
            if (
                trade.asset == asset
                and trade.side == "short"
                and trade.exit_time is None
            ):
                trade.exit_time = timestamp or datetime.now()
                trade.exit_price = price
                trade.pnl = pnl
                trade.pnl_pct = pnl_pct
                trade.exit_reason = reason
                break

        # Remove position
        del self.positions[key]

        return True

    def _check_take_profit(self, asset: str, current_price: float) -> bool:
        """Check if position should be closed for take profit."""
        if asset not in self.positions:
            return False

        position = self.positions[asset]
        if position.side == "long":
            pnl_pct = (current_price / position.entry_price - 1) * 100
            return pnl_pct >= self.config.take_profit_pct
        else:
            pnl_pct = (position.entry_price / current_price - 1) * 100
            return pnl_pct >= self.config.take_profit_pct

    def _check_stop_loss(self, asset: str, current_price: float) -> bool:
        """Check if position should be closed for stop loss."""
        if asset not in self.positions:
            return False

        position = self.positions[asset]
        if position.side == "long":
            pnl_pct = (current_price / position.entry_price - 1) * 100
            return pnl_pct <= -self.config.stop_loss_pct
        else:
            pnl_pct = (position.entry_price / current_price - 1) * 100
            return pnl_pct <= -self.config.stop_loss_pct

    def _check_premium_entry(self, asset: str, premium_pct: float) -> bool:
        """Check if premium arbitrage entry condition is met."""
        if not self.config.enable_premium_arb:
            return False
        return premium_pct >= self.config.premium_entry_threshold

    def _check_premium_exit(self, asset: str, premium_pct: float) -> bool:
        """Check if premium arbitrage exit condition is met."""
        if not self.config.enable_premium_arb:
            return False
        return premium_pct < self.config.premium_exit_threshold

    def _get_current_fx_rate(self, date: datetime) -> float:
        """Get FX rate for a given date."""
        if self.fx_rates.empty:
            return 1300.0  # Default fallback

        date_str = date.strftime("%Y-%m-%d")
        mask = self.fx_rates["date"] <= date_str
        if mask.any():
            return float(self.fx_rates.loc[mask, "rate"].iloc[-1])
        return 1300.0

    def _calculate_total_equity_krw(self, fx_rate: float) -> float:
        """Calculate total equity in KRW."""
        # Upbit cash (already in KRW)
        total = self.upbit_cash

        # Add Upbit position values
        for key, pos in self.positions.items():
            if pos.exchange == "upbit" and key in self.upbit_data:
                # Get current price from data
                df = self.upbit_data.get(pos.asset)
                if df is not None and len(df) > 0:
                    current_price = float(df["close"].iloc[-1])
                    total += pos.quantity * current_price

        # Convert Binance cash to KRW
        total += self.binance_cash * fx_rate

        # Add Binance position values (converted to KRW)
        for key, pos in self.positions.items():
            if pos.exchange == "binance":
                asset = pos.asset
                if asset in self.binance_data:
                    df = self.binance_data[asset]
                    if len(df) > 0:
                        current_price = float(df["close"].iloc[-1])
                        # For short, value is the unrealized P&L
                        pnl = (pos.entry_price - current_price) * pos.quantity
                        total += pnl * fx_rate

        return total

    def _calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """Calculate MFI and ADX indicators for regime classification."""
        df = df.copy()

        # MFI calculation
        period = 14
        tp = (df["high"] + df["low"] + df["close"]) / 3.0
        raw_mf = tp * df["volume"]

        direction = tp.diff()
        pos_mf = raw_mf.where(direction > 0, 0.0)
        neg_mf = raw_mf.where(direction < 0, 0.0).abs()

        pos_sum = pos_mf.rolling(period).sum()
        neg_sum = neg_mf.rolling(period).sum()

        mf_ratio = pos_sum / neg_sum.replace(0, np.nan)
        df["mfi"] = 100.0 - (100.0 / (1.0 + mf_ratio))
        df["mfi"] = df["mfi"].fillna(50.0)

        # ADX calculation
        high = df["high"]
        low = df["low"]
        close = df["close"]
        prev_close = close.shift(1)

        tr = pd.concat(
            [(high - low), (high - prev_close).abs(), (low - prev_close).abs()], axis=1
        ).max(axis=1)

        up_move = high.diff()
        down_move = -low.diff()

        plus_dm = up_move.where((up_move > down_move) & (up_move > 0), 0.0)
        minus_dm = down_move.where((down_move > up_move) & (down_move > 0), 0.0)

        atr = tr.rolling(period).mean()
        plus_di = 100.0 * (plus_dm.rolling(period).mean() / atr.replace(0, np.nan))
        minus_di = 100.0 * (minus_dm.rolling(period).mean() / atr.replace(0, np.nan))

        dx = 100.0 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
        df["adx"] = dx.rolling(period).mean()
        df["adx"] = df["adx"].fillna(0.0)

        return df

    def run(self) -> Dict[str, Any]:
        """
        Execute the backtest and return results.

        Returns:
            Dictionary containing:
            - total_return_pct: Total return percentage
            - total_trades: Number of completed trades
            - win_rate: Win rate (0-1)
            - sharpe_ratio: Annualized Sharpe ratio
            - max_drawdown_pct: Maximum drawdown percentage
            - avg_win_pct: Average winning trade percentage
            - avg_loss_pct: Average losing trade percentage
            - equity_curve: DataFrame with equity over time
            - trades: DataFrame of all trades (or None)
        """
        # Load data
        self._load_data()

        # Check if we have data
        if not self.upbit_data:
            return self._generate_empty_results()

        # Get primary asset data for iteration
        primary_asset = self.config.assets[0]
        if primary_asset not in self.upbit_data:
            return self._generate_empty_results()

        df = self.upbit_data[primary_asset].copy()
        if len(df) == 0:
            return self._generate_empty_results()

        # Calculate indicators for regime classification
        df = self._calculate_indicators(df)

        # Initialize state
        current_regime = None
        lookback = 20  # Need some history for indicators

        # Initialize tracking variables
        price_krw = None
        price_usdt = None
        timestamp = None

        # Check if we have enough data
        if len(df) <= lookback:
            return self._generate_empty_results()

        # Main simulation loop
        for i in range(lookback, len(df)):
            row = df.iloc[i]
            timestamp = row["timestamp"]
            price_krw = float(row["close"])
            mfi = float(row["mfi"])
            adx = float(row["adx"])

            # Get Binance price if available
            price_usdt = None
            if primary_asset in self.binance_data:
                binance_df = self.binance_data[primary_asset]
                binance_mask = binance_df["timestamp"] <= timestamp
                if binance_mask.any():
                    price_usdt = float(
                        binance_df.loc[binance_mask, "close"].iloc[-1]
                    )

            # Get premium if available
            premium_pct = None
            if primary_asset in self.premium_data and not self.premium_data[primary_asset].empty:
                premium_df = self.premium_data[primary_asset]
                date_str = timestamp.strftime("%Y-%m-%d") if hasattr(timestamp, 'strftime') else str(timestamp)[:10]
                premium_mask = premium_df["date"].astype(str).str[:10] <= date_str
                if premium_mask.any():
                    premium_pct = float(
                        premium_df.loc[premium_mask, "premium_pct"].iloc[-1]
                    )

            # Classify regime
            market_state = self.router.classify_from_values(mfi, adx)
            new_regime = self._get_regime_from_state(market_state)

            # Check for take profit / stop loss
            self._check_and_execute_tp_sl(primary_asset, price_krw, price_usdt, timestamp)

            # Handle regime changes
            if new_regime != current_regime:
                self._handle_regime_change(
                    primary_asset,
                    current_regime,
                    new_regime,
                    price_krw,
                    price_usdt,
                    timestamp,
                )
                current_regime = new_regime

            # Record equity
            fx_rate = self._get_current_fx_rate(timestamp)
            equity = self._calculate_current_equity(
                primary_asset, price_krw, price_usdt, fx_rate
            )
            self.equity_history.append(
                {
                    "timestamp": timestamp,
                    "total_equity_krw": equity,
                    "upbit_cash": self.upbit_cash,
                    "binance_cash_krw": self.binance_cash * fx_rate,
                    "regime": current_regime,
                }
            )

        # Close any remaining positions (only if we have valid price data)
        if price_krw is not None and timestamp is not None:
            self._close_all_positions(primary_asset, price_krw, price_usdt, timestamp)

        return self._generate_results()

    def _get_regime_from_state(self, market_state: str) -> str:
        """Extract regime from market state."""
        if market_state.startswith("BULL"):
            return "BULL"
        elif market_state.startswith("BEAR"):
            return "BEAR"
        else:
            return "SIDEWAYS"

    def _check_and_execute_tp_sl(
        self,
        asset: str,
        price_krw: float,
        price_usdt: Optional[float],
        timestamp: datetime,
    ) -> None:
        """Check and execute take profit / stop loss."""
        # Check long position
        if asset in self.positions:
            if self._check_take_profit(asset, price_krw):
                self._exit_long(asset, price_krw, "take_profit", timestamp)
            elif self._check_stop_loss(asset, price_krw):
                self._exit_long(asset, price_krw, "stop_loss", timestamp)

        # Check short position
        short_key = f"{asset}_SHORT"
        if short_key in self.positions and price_usdt is not None:
            if self._check_take_profit(short_key, price_usdt):
                self._exit_short(asset, price_usdt, "take_profit", timestamp)
            elif self._check_stop_loss(short_key, price_usdt):
                self._exit_short(asset, price_usdt, "stop_loss", timestamp)

    def _handle_regime_change(
        self,
        asset: str,
        old_regime: Optional[str],
        new_regime: str,
        price_krw: float,
        price_usdt: Optional[float],
        timestamp: datetime,
    ) -> None:
        """Handle position changes on regime transition."""
        # Exit existing positions on regime change
        if old_regime is not None:
            if asset in self.positions:
                self._exit_long(asset, price_krw, "regime_change", timestamp)

            short_key = f"{asset}_SHORT"
            if short_key in self.positions and price_usdt is not None:
                self._exit_short(asset, price_usdt, "regime_change", timestamp)

        # Enter new positions based on new regime
        if new_regime == "BULL" and self.config.enable_long:
            self._enter_long(
                asset, price_krw, self.config.long_fraction, timestamp
            )
        elif new_regime == "BEAR" and self.config.enable_short and price_usdt is not None:
            self._enter_short(
                asset, price_usdt, self.config.short_fraction, timestamp
            )

    def _calculate_current_equity(
        self,
        asset: str,
        price_krw: float,
        price_usdt: Optional[float],
        fx_rate: float,
    ) -> float:
        """Calculate current total equity in KRW."""
        equity = self.upbit_cash

        # Add long position value
        if asset in self.positions:
            pos = self.positions[asset]
            equity += pos.quantity * price_krw

        # Add Binance capital (converted to KRW)
        equity += self.binance_cash * fx_rate

        # Add short position unrealized P&L
        short_key = f"{asset}_SHORT"
        if short_key in self.positions and price_usdt is not None:
            pos = self.positions[short_key]
            pnl = (pos.entry_price - price_usdt) * pos.quantity
            equity += pnl * fx_rate

        return equity

    def _close_all_positions(
        self,
        asset: str,
        price_krw: float,
        price_usdt: Optional[float],
        timestamp: datetime,
    ) -> None:
        """Close all open positions at the end of backtest."""
        if asset in self.positions:
            self._exit_long(asset, price_krw, "backtest_end", timestamp)

        short_key = f"{asset}_SHORT"
        if short_key in self.positions and price_usdt is not None:
            self._exit_short(asset, price_usdt, "backtest_end", timestamp)

    def _generate_empty_results(self) -> Dict[str, Any]:
        """Generate results when no data/trades."""
        return {
            "total_return_pct": 0.0,
            "total_trades": 0,
            "win_rate": 0.0,
            "sharpe_ratio": 0.0,
            "max_drawdown_pct": 0.0,
            "avg_win_pct": 0.0,
            "avg_loss_pct": 0.0,
            "equity_curve": pd.DataFrame(
                columns=["timestamp", "total_equity_krw"]
            ),
            "trades": None,
        }

    def _generate_results(self) -> Dict[str, Any]:
        """Generate comprehensive backtest results."""
        # Build equity curve DataFrame
        equity_df = pd.DataFrame(self.equity_history)

        if equity_df.empty:
            return self._generate_empty_results()

        # Calculate total return
        initial_equity = self.initial_upbit_cash + self.initial_binance_cash * self._get_current_fx_rate(
            datetime.strptime(self.config.start_date, "%Y-%m-%d")
        )
        final_equity = equity_df["total_equity_krw"].iloc[-1]
        total_return_pct = (final_equity / initial_equity - 1) * 100

        # Filter completed trades
        completed_trades = [t for t in self.trades if t.exit_time is not None]
        total_trades = len(completed_trades)

        # Calculate win rate
        if total_trades > 0:
            winning_trades = [t for t in completed_trades if t.pnl > 0]
            losing_trades = [t for t in completed_trades if t.pnl <= 0]
            win_rate = len(winning_trades) / total_trades

            avg_win_pct = (
                np.mean([t.pnl_pct for t in winning_trades])
                if winning_trades
                else 0.0
            )
            avg_loss_pct = (
                np.mean([t.pnl_pct for t in losing_trades])
                if losing_trades
                else 0.0
            )
        else:
            win_rate = 0.0
            avg_win_pct = 0.0
            avg_loss_pct = 0.0

        # Calculate Sharpe ratio
        sharpe_ratio = self._calculate_sharpe_ratio(equity_df)

        # Calculate max drawdown
        max_drawdown_pct = self._calculate_max_drawdown(equity_df)

        # Build trades DataFrame
        trades_df = None
        if completed_trades:
            trades_df = pd.DataFrame(
                [
                    {
                        "asset": t.asset,
                        "side": t.side,
                        "entry_time": t.entry_time,
                        "entry_price": t.entry_price,
                        "exit_time": t.exit_time,
                        "exit_price": t.exit_price,
                        "quantity": t.quantity,
                        "pnl": t.pnl,
                        "pnl_pct": t.pnl_pct,
                        "exit_reason": t.exit_reason,
                    }
                    for t in completed_trades
                ]
            )

        return {
            "total_return_pct": total_return_pct,
            "total_trades": total_trades,
            "win_rate": win_rate,
            "sharpe_ratio": sharpe_ratio,
            "max_drawdown_pct": max_drawdown_pct,
            "avg_win_pct": avg_win_pct,
            "avg_loss_pct": avg_loss_pct,
            "equity_curve": equity_df,
            "trades": trades_df,
        }

    def _calculate_sharpe_ratio(self, equity_df: pd.DataFrame) -> float:
        """Calculate annualized Sharpe ratio."""
        if len(equity_df) < 2:
            return 0.0

        # Calculate daily returns
        equity = equity_df["total_equity_krw"]
        returns = equity.pct_change().dropna()

        if len(returns) == 0 or returns.std() == 0:
            return 0.0

        # Annualized Sharpe (assuming daily data, 252 trading days)
        mean_return = returns.mean()
        std_return = returns.std()

        # Annualize
        annualized_return = mean_return * 252
        annualized_std = std_return * np.sqrt(252)

        if annualized_std == 0:
            return 0.0

        return annualized_return / annualized_std

    def _calculate_max_drawdown(self, equity_df: pd.DataFrame) -> float:
        """Calculate maximum drawdown percentage."""
        if len(equity_df) < 2:
            return 0.0

        equity = equity_df["total_equity_krw"]
        peak = equity.cummax()
        drawdown = (equity - peak) / peak * 100

        return float(drawdown.min())
