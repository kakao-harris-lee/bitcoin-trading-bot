#!/usr/bin/env python3
"""
Altcoin V35 Parameter Optimizer

Optimizes V35 strategy parameters for specific altcoins (ETH, SOL, XRP, etc.)
Each altcoin gets its own parameter set, independent of BTC parameters.

Usage:
    python scripts/optimize_altcoin_v35.py ETH --trials 200
    python scripts/optimize_altcoin_v35.py SOL --trials 100 --timeframe minute60
    python scripts/optimize_altcoin_v35.py ETH --validate  # Run validation only
"""

import argparse
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, Tuple

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

try:
    import optuna
    from optuna.samplers import TPESampler
    OPTUNA_AVAILABLE = True
except ImportError:
    OPTUNA_AVAILABLE = False
    print("Warning: optuna not installed. Install with: pip install optuna")


# Asset configurations
ASSET_CONFIG = {
    "ETH": {
        "db_path": "data/upbit_ethereum.db",
        "table_prefix": "ethereum",
        "config_path": "config/strategies/v35_eth.json",
    },
    "SOL": {
        "db_path": "data/upbit_solana.db",
        "table_prefix": "solana",
        "config_path": "config/strategies/v35_sol.json",
    },
    "XRP": {
        "db_path": "data/upbit_xrp.db",
        "table_prefix": "xrp",
        "config_path": "config/strategies/v35_xrp.json",
    },
}


class AltcoinDataLoader:
    """Load altcoin data from SQLite database."""

    def __init__(self, symbol: str):
        if symbol not in ASSET_CONFIG:
            raise ValueError(f"Unsupported asset: {symbol}")

        self.symbol = symbol
        self.config = ASSET_CONFIG[symbol]
        self.db_path = PROJECT_ROOT / self.config["db_path"]
        self.table_prefix = self.config["table_prefix"]

    def load(self, timeframe: str, start_date: str, end_date: str) -> pd.DataFrame:
        """Load OHLCV data for the specified timeframe and date range."""
        table_name = f"{self.table_prefix}_{timeframe}"

        conn = sqlite3.connect(str(self.db_path))
        df = pd.read_sql(f"""
            SELECT timestamp,
                   opening_price as open,
                   high_price as high,
                   low_price as low,
                   trade_price as close,
                   candle_acc_trade_volume as volume
            FROM {table_name}
            WHERE timestamp >= '{start_date}' AND timestamp <= '{end_date}'
            ORDER BY timestamp
        """, conn)
        conn.close()

        return df

    def get_date_range(self, timeframe: str) -> Tuple[str, str]:
        """Get available date range for a timeframe."""
        table_name = f"{self.table_prefix}_{timeframe}"

        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        cursor.execute(f"SELECT MIN(timestamp), MAX(timestamp) FROM {table_name}")
        result = cursor.fetchone()
        conn.close()

        return result[0][:10], result[1][:10]


class V35StrategyOptimizable:
    """V35 strategy with configurable parameters for optimization."""

    def __init__(self, params: Dict[str, Any]):
        self.params = params
        self.in_position = False
        self.entry_price = 0.0
        self.market_state = 'UNKNOWN'
        self.partial_exits = 0
        self._cached_df = None

    def add_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add technical indicators."""
        df = df.copy()

        # RSI
        delta = df['close'].diff()
        gain = delta.where(delta > 0, 0).rolling(window=14).mean()
        loss = -delta.where(delta < 0, 0).rolling(window=14).mean()
        rs = gain / loss
        df['rsi'] = 100 - (100 / (1 + rs))

        # MACD
        ema12 = df['close'].ewm(span=12, adjust=False).mean()
        ema26 = df['close'].ewm(span=26, adjust=False).mean()
        df['macd'] = ema12 - ema26
        df['macd_signal'] = df['macd'].ewm(span=9, adjust=False).mean()

        # Bollinger Bands
        sma20 = df['close'].rolling(window=20).mean()
        std20 = df['close'].rolling(window=20).std()
        df['bb_upper'] = sma20 + (std20 * self.params.get('bb_mult', 2.0))
        df['bb_lower'] = sma20 - (std20 * self.params.get('bb_mult', 2.0))

        # ADX
        df['tr'] = np.maximum(
            df['high'] - df['low'],
            np.maximum(
                abs(df['high'] - df['close'].shift(1)),
                abs(df['low'] - df['close'].shift(1))
            )
        )
        df['atr'] = df['tr'].rolling(window=14).mean()

        plus_dm = df['high'].diff()
        minus_dm = -df['low'].diff()
        plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0)
        minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0)

        plus_di = 100 * (plus_dm.rolling(14).mean() / df['atr'])
        minus_di = 100 * (minus_dm.rolling(14).mean() / df['atr'])
        dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di + 1e-10)
        df['adx'] = dx.rolling(14).mean()

        # MFI
        typical_price = (df['high'] + df['low'] + df['close']) / 3
        raw_mf = typical_price * df['volume']
        mf_positive = raw_mf.where(typical_price > typical_price.shift(1), 0)
        mf_negative = raw_mf.where(typical_price < typical_price.shift(1), 0)
        mf_ratio = mf_positive.rolling(14).sum() / (mf_negative.rolling(14).sum() + 1e-10)
        df['mfi'] = 100 - (100 / (1 + mf_ratio))

        # Stochastic
        low_14 = df['low'].rolling(14).min()
        high_14 = df['high'].rolling(14).max()
        df['stoch_k'] = 100 * (df['close'] - low_14) / (high_14 - low_14 + 1e-10)
        df['stoch_d'] = df['stoch_k'].rolling(3).mean()

        return df

    def classify_market(self, row: pd.Series) -> str:
        """Classify market state based on MFI and ADX."""
        mfi = row.get('mfi', 50)
        adx = row.get('adx', 15)
        p = self.params

        if mfi >= p['mfi_bull_strong'] and adx >= p['adx_strong']:
            return 'BULL_STRONG'
        elif mfi >= p['mfi_bull_moderate'] and adx >= p['adx_moderate']:
            return 'BULL_MODERATE'
        elif mfi >= p['mfi_sideways']:
            return 'SIDEWAYS'
        elif adx >= p['adx_strong']:
            return 'BEAR_STRONG'
        else:
            return 'BEAR_MODERATE'

    def check_entry(self, row: pd.Series) -> Optional[Dict]:
        """Check entry conditions."""
        if self.in_position:
            return None

        p = self.params
        rsi = row.get('rsi', 50)
        close = row['close']
        bb_lower = row.get('bb_lower', close)
        macd = row.get('macd', 0)
        macd_signal = row.get('macd_signal', 0)
        stoch_k = row.get('stoch_k', 50)

        # Entry in BULL markets
        if self.market_state in ['BULL_STRONG', 'BULL_MODERATE']:
            rsi_ok = rsi < p['rsi_oversold']
            bb_ok = close <= bb_lower * (1 + p['bb_entry_tolerance'])
            macd_ok = macd > macd_signal

            if rsi_ok and bb_ok and macd_ok:
                fraction = p['position_size_bull_strong'] if self.market_state == 'BULL_STRONG' else p['position_size_bull_moderate']
                return {
                    'action': 'buy',
                    'fraction': fraction,
                    'reason': f'ENTRY: RSI={rsi:.1f}, BB_LOWER, {self.market_state}'
                }

        # Entry in SIDEWAYS (optional, looser conditions)
        elif self.market_state == 'SIDEWAYS' and p.get('sideways_entry_enabled', True):
            if rsi < p.get('rsi_sideways_oversold', 30) and stoch_k < p.get('stoch_oversold', 20):
                return {
                    'action': 'buy',
                    'fraction': p.get('position_size_sideways', 0.2),
                    'reason': f'ENTRY: RSI={rsi:.1f}, Stoch={stoch_k:.1f}, SIDEWAYS'
                }

        return None

    def check_exit(self, row: pd.Series) -> Optional[Dict]:
        """Check exit conditions."""
        if not self.in_position:
            return None

        p = self.params
        close = row['close']
        pnl_pct = (close - self.entry_price) / self.entry_price

        # Stop loss
        if pnl_pct <= p['stop_loss']:
            return {
                'action': 'sell',
                'fraction': 1.0,
                'reason': f'STOP_LOSS: {pnl_pct*100:.2f}%'
            }

        # Take profit levels based on market state
        if self.market_state == 'BULL_STRONG':
            tp_levels = [p['tp_bull_strong_1'], p['tp_bull_strong_2'], p['tp_bull_strong_3']]
        elif self.market_state == 'BULL_MODERATE':
            tp_levels = [p['tp_bull_moderate_1'], p['tp_bull_moderate_2'], p['tp_bull_moderate_3']]
        else:
            tp_levels = [p['tp_sideways_1'], p['tp_sideways_2'], p['tp_sideways_3']]

        # Partial exits
        if self.partial_exits < len(tp_levels):
            if pnl_pct >= tp_levels[self.partial_exits]:
                fraction = p['exit_fraction_1'] if self.partial_exits == 0 else p['exit_fraction_2']
                return {
                    'action': 'sell',
                    'fraction': fraction,
                    'reason': f'TP_LEVEL_{self.partial_exits + 1}: {pnl_pct*100:.2f}%'
                }

        # MACD dead cross exit
        macd = row.get('macd', 0)
        macd_signal = row.get('macd_signal', 0)
        if macd < macd_signal and pnl_pct > p.get('min_profit_for_macd_exit', 0.005):
            return {
                'action': 'sell',
                'fraction': 1.0,
                'reason': f'MACD_DEAD_CROSS: {pnl_pct*100:.2f}%'
            }

        return None

    def __call__(self, df: pd.DataFrame, i: int, params: Dict) -> Dict:
        """Backtester-compatible interface."""
        if i < 50:
            return {'action': 'hold'}

        if self._cached_df is None or len(df) != len(self._cached_df):
            self._cached_df = self.add_indicators(df)

        row = self._cached_df.iloc[i]
        self.market_state = self.classify_market(row)

        exit_signal = self.check_exit(row)
        if exit_signal:
            if exit_signal['fraction'] >= 1.0:
                self.in_position = False
                self.entry_price = 0
                self.partial_exits = 0
            else:
                self.partial_exits += 1
            return exit_signal

        entry_signal = self.check_entry(row)
        if entry_signal:
            self.in_position = True
            self.entry_price = row['close']
            return entry_signal

        return {'action': 'hold'}


def create_objective(loader: AltcoinDataLoader, timeframe: str,
                     train_start: str, train_end: str):
    """Create Optuna objective function."""

    from core.backtester import Backtester

    # Load training data once
    df_train = loader.load(timeframe, train_start, train_end)
    print(f"Training data: {len(df_train)} bars ({train_start} to {train_end})")

    def objective(trial: optuna.Trial) -> float:
        # Sample parameters
        params = {
            # Market classification
            'mfi_bull_strong': trial.suggest_int('mfi_bull_strong', 48, 60),
            'mfi_bull_moderate': trial.suggest_int('mfi_bull_moderate', 42, 52),
            'mfi_sideways': trial.suggest_int('mfi_sideways', 38, 48),
            'adx_strong': trial.suggest_int('adx_strong', 18, 28),
            'adx_moderate': trial.suggest_int('adx_moderate', 12, 22),

            # Entry conditions
            'rsi_oversold': trial.suggest_int('rsi_oversold', 25, 40),
            'bb_mult': trial.suggest_float('bb_mult', 1.5, 2.5),
            'bb_entry_tolerance': trial.suggest_float('bb_entry_tolerance', 0.01, 0.05),

            # Sideways entry
            'sideways_entry_enabled': trial.suggest_categorical('sideways_entry_enabled', [True, False]),
            'rsi_sideways_oversold': trial.suggest_int('rsi_sideways_oversold', 20, 35),
            'stoch_oversold': trial.suggest_int('stoch_oversold', 15, 30),

            # Position sizing
            'position_size_bull_strong': trial.suggest_float('position_size_bull_strong', 0.4, 0.8),
            'position_size_bull_moderate': trial.suggest_float('position_size_bull_moderate', 0.2, 0.5),
            'position_size_sideways': trial.suggest_float('position_size_sideways', 0.1, 0.3),

            # Exit conditions
            'stop_loss': trial.suggest_float('stop_loss', -0.03, -0.01),
            'tp_bull_strong_1': trial.suggest_float('tp_bull_strong_1', 0.03, 0.08),
            'tp_bull_strong_2': trial.suggest_float('tp_bull_strong_2', 0.08, 0.15),
            'tp_bull_strong_3': trial.suggest_float('tp_bull_strong_3', 0.15, 0.25),
            'tp_bull_moderate_1': trial.suggest_float('tp_bull_moderate_1', 0.02, 0.05),
            'tp_bull_moderate_2': trial.suggest_float('tp_bull_moderate_2', 0.05, 0.10),
            'tp_bull_moderate_3': trial.suggest_float('tp_bull_moderate_3', 0.10, 0.15),
            'tp_sideways_1': trial.suggest_float('tp_sideways_1', 0.01, 0.03),
            'tp_sideways_2': trial.suggest_float('tp_sideways_2', 0.03, 0.06),
            'tp_sideways_3': trial.suggest_float('tp_sideways_3', 0.06, 0.10),
            'exit_fraction_1': trial.suggest_float('exit_fraction_1', 0.3, 0.5),
            'exit_fraction_2': trial.suggest_float('exit_fraction_2', 0.3, 0.5),
            'min_profit_for_macd_exit': trial.suggest_float('min_profit_for_macd_exit', 0.002, 0.01),
        }

        # Run backtest
        strategy = V35StrategyOptimizable(params)
        bt = Backtester(initial_capital=10_000_000, fee_rate=0.0005, slippage=0.0002)
        result = bt.run(df_train, strategy, {})

        # Calculate metrics
        equity = result['equity_curve']
        initial = float(equity['total_equity'].iloc[0])
        final = float(equity['total_equity'].iloc[-1])
        total_return = (final - initial) / initial * 100

        # MDD
        peak = equity['total_equity'].cummax()
        dd = (equity['total_equity'] - peak) / peak
        mdd = float(dd.min() * 100)

        # Sharpe
        rets = equity['total_equity'].pct_change().dropna()
        sharpe = float((rets.mean() / rets.std()) * np.sqrt(252)) if rets.std() > 0 else 0

        # Trade count penalty (too few trades is suspicious)
        n_trades = result.get('total_trades', 0)
        if n_trades < 5:
            return -100  # Penalize too few trades

        # Multi-objective: maximize return, minimize MDD, maximize Sharpe
        # Combined score
        score = total_return - abs(mdd) * 0.5 + sharpe * 5

        return score

    return objective


def run_optimization(symbol: str, timeframe: str = "minute60",
                     n_trials: int = 200, train_ratio: float = 0.7) -> Dict:
    """Run parameter optimization for an altcoin."""

    if not OPTUNA_AVAILABLE:
        raise RuntimeError("Optuna is required. Install with: pip install optuna")

    loader = AltcoinDataLoader(symbol)
    start_date, end_date = loader.get_date_range(timeframe)

    # Split into train/validation
    all_dates = pd.date_range(start_date, end_date)
    split_idx = int(len(all_dates) * train_ratio)
    train_end = all_dates[split_idx].strftime('%Y-%m-%d')
    val_start = all_dates[split_idx + 1].strftime('%Y-%m-%d')

    print(f"\n{'='*60}")
    print(f"Optimizing V35 for {symbol}")
    print(f"{'='*60}")
    print(f"Timeframe: {timeframe}")
    print(f"Training: {start_date} to {train_end}")
    print(f"Validation: {val_start} to {end_date}")
    print(f"Trials: {n_trials}")
    print()

    # Create study
    study = optuna.create_study(
        direction="maximize",
        sampler=TPESampler(seed=42),
        study_name=f"v35_{symbol.lower()}"
    )

    # Run optimization
    objective = create_objective(loader, timeframe, start_date, train_end)
    study.optimize(objective, n_trials=n_trials, show_progress_bar=True)

    # Best parameters
    best_params = study.best_params
    best_score = study.best_value

    print(f"\n{'='*60}")
    print(f"Optimization Complete")
    print(f"{'='*60}")
    print(f"Best Score: {best_score:.2f}")
    print(f"Best Parameters:")
    for k, v in sorted(best_params.items()):
        print(f"  {k}: {v}")

    # Validate on out-of-sample data
    print(f"\n{'='*60}")
    print(f"Validation (Out-of-Sample)")
    print(f"{'='*60}")

    from core.backtester import Backtester

    df_val = loader.load(timeframe, val_start, end_date)
    print(f"Validation data: {len(df_val)} bars ({val_start} to {end_date})")

    strategy = V35StrategyOptimizable(best_params)
    bt = Backtester(initial_capital=10_000_000, fee_rate=0.0005, slippage=0.0002)
    result = bt.run(df_val, strategy, {})

    equity = result['equity_curve']
    initial = float(equity['total_equity'].iloc[0])
    final = float(equity['total_equity'].iloc[-1])
    val_return = (final - initial) / initial * 100

    peak = equity['total_equity'].cummax()
    dd = (equity['total_equity'] - peak) / peak
    val_mdd = float(dd.min() * 100)

    rets = equity['total_equity'].pct_change().dropna()
    val_sharpe = float((rets.mean() / rets.std()) * np.sqrt(252)) if rets.std() > 0 else 0

    print(f"OOS Return: {val_return:+.2f}%")
    print(f"OOS MDD: {val_mdd:.2f}%")
    print(f"OOS Sharpe: {val_sharpe:.2f}")
    print(f"OOS Trades: {result.get('total_trades', 0)}")
    print(f"OOS Win Rate: {result.get('win_rate', 0) * 100:.1f}%")

    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "train_period": f"{start_date} to {train_end}",
        "validation_period": f"{val_start} to {end_date}",
        "best_score": best_score,
        "best_params": best_params,
        "validation": {
            "return_pct": val_return,
            "mdd_pct": val_mdd,
            "sharpe": val_sharpe,
            "trades": result.get('total_trades', 0),
            "win_rate": result.get('win_rate', 0)
        }
    }


def save_config(symbol: str, result: Dict):
    """Save optimized parameters to config file."""
    config = ASSET_CONFIG[symbol]
    config_path = PROJECT_ROOT / config["config_path"]

    # Format parameters for config file
    params = result["best_params"]

    config_data = {
        "strategy_name": "v35_optimized",
        "version": "v35",
        "asset": symbol,
        "timeframe": result["timeframe"],
        "description": f"V35 Optuna optimized for {symbol}",
        "optimized_at": datetime.now().isoformat(),
        "market_classifier": {
            "mfi_bull_strong": params["mfi_bull_strong"],
            "mfi_bull_moderate": params["mfi_bull_moderate"],
            "mfi_sideways": params["mfi_sideways"],
            "adx_strong": params["adx_strong"],
            "adx_moderate": params["adx_moderate"],
        },
        "entry_conditions": {
            "rsi_oversold": params["rsi_oversold"],
            "bb_mult": params["bb_mult"],
            "bb_entry_tolerance": params["bb_entry_tolerance"],
            "sideways_entry_enabled": params["sideways_entry_enabled"],
            "rsi_sideways_oversold": params["rsi_sideways_oversold"],
            "stoch_oversold": params["stoch_oversold"],
        },
        "position_sizing": {
            "position_size_bull_strong": params["position_size_bull_strong"],
            "position_size_bull_moderate": params["position_size_bull_moderate"],
            "position_size_sideways": params["position_size_sideways"],
        },
        "exit_conditions": {
            "stop_loss": params["stop_loss"],
            "tp_bull_strong_1": params["tp_bull_strong_1"],
            "tp_bull_strong_2": params["tp_bull_strong_2"],
            "tp_bull_strong_3": params["tp_bull_strong_3"],
            "tp_bull_moderate_1": params["tp_bull_moderate_1"],
            "tp_bull_moderate_2": params["tp_bull_moderate_2"],
            "tp_bull_moderate_3": params["tp_bull_moderate_3"],
            "tp_sideways_1": params["tp_sideways_1"],
            "tp_sideways_2": params["tp_sideways_2"],
            "tp_sideways_3": params["tp_sideways_3"],
            "exit_fraction_1": params["exit_fraction_1"],
            "exit_fraction_2": params["exit_fraction_2"],
            "min_profit_for_macd_exit": params["min_profit_for_macd_exit"],
        },
        "backtesting": {
            "train_period": result["train_period"],
            "validation_period": result["validation_period"],
            "best_score": result["best_score"],
        },
        "validation_results": result["validation"]
    }

    config_path.parent.mkdir(parents=True, exist_ok=True)
    with open(config_path, 'w') as f:
        json.dump(config_data, f, indent=2)

    print(f"\nConfig saved to: {config_path}")
    return config_path


def main():
    parser = argparse.ArgumentParser(description="Optimize V35 parameters for altcoins")
    parser.add_argument('symbol', type=str, help='Asset symbol (ETH, SOL, XRP)')
    parser.add_argument('--trials', type=int, default=200, help='Number of optimization trials')
    parser.add_argument('--timeframe', type=str, default='minute60', help='Timeframe for optimization')
    parser.add_argument('--train-ratio', type=float, default=0.7, help='Training data ratio')
    parser.add_argument('--validate', action='store_true', help='Only run validation with existing config')

    args = parser.parse_args()
    symbol = args.symbol.upper()

    if symbol not in ASSET_CONFIG:
        print(f"Error: Unsupported asset '{symbol}'")
        print(f"Supported: {list(ASSET_CONFIG.keys())}")
        return

    if args.validate:
        # Load existing config and validate
        config_path = PROJECT_ROOT / ASSET_CONFIG[symbol]["config_path"]
        if not config_path.exists():
            print(f"Error: Config not found: {config_path}")
            print("Run optimization first without --validate flag")
            return

        with open(config_path) as f:
            config = json.load(f)

        # Reconstruct params from config
        params = {}
        for section in ['market_classifier', 'entry_conditions', 'position_sizing', 'exit_conditions']:
            if section in config:
                params.update(config[section])

        # Run validation
        from core.backtester import Backtester
        loader = AltcoinDataLoader(symbol)
        val_period = config.get('backtesting', {}).get('validation_period', '')
        if ' to ' in val_period:
            val_start, val_end = val_period.split(' to ')
        else:
            _, val_end = loader.get_date_range(args.timeframe)
            val_start = '2025-01-01'

        df_val = loader.load(args.timeframe, val_start, val_end)
        strategy = V35StrategyOptimizable(params)
        bt = Backtester(initial_capital=10_000_000, fee_rate=0.0005, slippage=0.0002)
        result = bt.run(df_val, strategy, {})

        equity = result['equity_curve']
        initial = float(equity['total_equity'].iloc[0])
        final = float(equity['total_equity'].iloc[-1])
        val_return = (final - initial) / initial * 100

        print(f"\n{symbol} V35 Validation Results")
        print(f"{'='*40}")
        print(f"Period: {val_start} to {val_end}")
        print(f"Return: {val_return:+.2f}%")
        print(f"Trades: {result.get('total_trades', 0)}")
        print(f"Win Rate: {result.get('win_rate', 0) * 100:.1f}%")
        return

    # Run optimization
    result = run_optimization(
        symbol=symbol,
        timeframe=args.timeframe,
        n_trials=args.trials,
        train_ratio=args.train_ratio
    )

    # Save config
    save_config(symbol, result)

    print(f"\n{'='*60}")
    print("DONE")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
