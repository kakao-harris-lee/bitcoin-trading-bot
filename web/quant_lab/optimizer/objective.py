"""Multi-objective optimization function for regime-based and MLP strategies."""
from dataclasses import dataclass
from typing import List, Tuple, Dict, Any, Optional
import optuna
from optuna.study import StudyDirection

from .search_space import SearchSpaceConfig, sample_trial_config, sample_mlp_trial_config, REGIMES


@dataclass
class RegimeBacktestObjective:
    """
    Callable objective function for Optuna multi-objective optimization.

    Returns (win_rate, total_return, max_drawdown) tuple.
    """
    data_path: str
    start_date: str
    end_date: str
    symbols: List[str]
    search_config: SearchSpaceConfig = None

    def __post_init__(self):
        if self.search_config is None:
            self.search_config = SearchSpaceConfig()

    def __call__(self, trial: optuna.Trial) -> Tuple[float, float, float]:
        """
        Evaluate a trial configuration.

        Args:
            trial: Optuna trial with hyperparameters

        Returns:
            Tuple of (win_rate, total_return, max_drawdown)
        """
        # Sample configuration from trial
        config = sample_trial_config(trial, self.search_config)

        # Run backtest with this configuration
        metrics = self._run_backtest(config)

        return (
            metrics["win_rate"],
            metrics["total_return"],
            metrics["max_drawdown"],
        )

    def _run_backtest(self, config: Dict[str, Any]) -> Dict[str, float]:
        """
        Run backtest with the given regime configuration.

        Args:
            config: Dict mapping regime -> {entry, exit, params}

        Returns:
            Dict with win_rate, total_return, max_drawdown
        """
        import os
        import sys
        from pathlib import Path

        # Ensure project root is in sys.path for core module imports
        # This is needed when running in RQ worker context
        web_dir = Path(__file__).parent.parent.parent
        project_root = web_dir.parent
        if str(project_root) not in sys.path:
            sys.path.insert(0, str(project_root))

        from core.data_loader import DataLoader
        from core.backtester import Backtester
        from trading.strategies.components import StrategyFactory
        from trading.strategies.components.registry import get_entry_class, get_exit_class
        from trading.indicators import add_all_indicators
        from trading.strategies.components.models import build_market_context
        import pandas as pd
        import logging
        
        logger = logging.getLogger(__name__)
        
        # Load data
        data_path = Path(self.data_path)
        if not data_path.exists():
            error_msg = f"Data file not found: {data_path}"
            logger.error(error_msg)
            raise FileNotFoundError(error_msg)
        
        loader = DataLoader(db_path=str(data_path))
        df = loader.load_timeframe(
            timeframe="minute60",
            start_date=self.start_date,
            end_date=self.end_date
        )
        
        if df.empty:
            error_msg = f"No data found for timeframe=minute60, dates={self.start_date} to {self.end_date}"
            logger.error(error_msg)
            raise ValueError(error_msg)
        
        # Add all technical indicators
        df = add_all_indicators(df)
        
        # Create strategy factory and instantiate components per regime
        factory = StrategyFactory()
        regime_strategies = {}
        
        for regime, regime_config in config.items():
            entry_name = regime_config.get("entry")
            exit_name = regime_config.get("exit")
            
            # Skip if entry is "None" (no trading in this regime)
            if entry_name == "None" or not entry_name:
                regime_strategies[regime] = None
                continue
            
            # Get component-specific params from nested structure
            entry_params = regime_config.get("params", {}).get("entry", {})
            exit_params = regime_config.get("params", {}).get("exit", {})
            
            # Create entry/exit components for this regime
            try:
                # Add "Strategy" suffix to match registered class names
                entry_cls = get_entry_class(entry_name + "Strategy") if entry_name != "None" else None
                exit_cls = get_exit_class(exit_name + "Strategy") if exit_name != "None" else None

                # Get params classes and build proper params objects
                from trading.strategies.components.registry import (
                    get_entry_params_class,
                    get_exit_params_class,
                    build_params_from_config,
                )

                entry_params_cls = get_entry_params_class(entry_name + "Strategy")
                exit_params_cls = get_exit_params_class(exit_name + "Strategy")

                # Build params objects from dicts
                entry_params_obj = build_params_from_config(entry_params_cls, entry_params) if entry_params_cls else None
                exit_params_obj = build_params_from_config(exit_params_cls, exit_params) if exit_params_cls else None

                # Instantiate with params objects
                entry_strategy = entry_cls(entry_params_obj)
                exit_strategy = exit_cls(exit_params_obj)
                
                regime_strategies[regime] = {
                    "entry": entry_strategy,
                    "exit": exit_strategy,
                }
            except Exception as e:
                # Skip this regime if component instantiation fails
                logger.warning(f"Failed to create components for {regime}: {e}")
                regime_strategies[regime] = None
        
        # Create regime-aware strategy function for backtester
        current_position = {"position": None, "regime": None}
        
        def regime_strategy_func(df_data: pd.DataFrame, i: int, params: dict) -> dict:
            """Strategy function that switches based on current regime."""
            if i < 200:  # Need enough data for indicators
                return {"action": "hold"}
            
            row = df_data.iloc[i]
            
            # Determine current regime using build_market_context
            # Includes drawdown-based BEAR detection (15% from 30-day high = BEAR override)
            # Use 30-day high for better crash detection (falls back to 20-period if not available)
            high_30d = row.get("high_30d", 0.0)
            recent_high = high_30d if high_30d > 0 else row.get("prev_high_20", 0.0)
            context = build_market_context(
                mfi=row.get("mfi", 50.0),
                adx=row.get("adx", 20.0),
                atr=row.get("atr", 0.0),
                close=row["close"],
                volume=row.get("volume", 0.0),
                avg_volume=row.get("avg_volume_20", 0.0),
                recent_high=recent_high,
            )
            current_regime = context.regime
            
            # Get strategy components for current regime
            strategy_components = regime_strategies.get(current_regime)
            
            if strategy_components is None:
                # No trading allowed in this regime
                if current_position["position"] is not None:
                    # Close position if regime changed to non-trading regime
                    current_position["position"] = None
                    current_position["regime"] = None
                    return {"action": "sell", "fraction": 1.0, "reason": f"Regime changed to {current_regime} (no trading)"}
                return {"action": "hold"}
            
            entry_strategy = strategy_components["entry"]
            exit_strategy = strategy_components["exit"]
            
            # Build MarketData for components
            from trading.strategies.components.models import MarketData
            market_data = MarketData(
                symbol=self.symbols[0] if self.symbols else "BTC",
                close=row["close"],
                timestamp=int(row["timestamp"].timestamp() * 1000) if hasattr(row["timestamp"], "timestamp") else 0,
                mfi=row.get("mfi", 50.0),
                adx=row.get("adx", 20.0),
                rsi=row.get("rsi", 50.0),
                atr=row.get("atr", 0.0),
                macd=row.get("macd", 0.0),
                macd_signal=row.get("macd_signal", 0.0),
                stoch_k=row.get("stoch_k", 50.0),
                stoch_d=row.get("stoch_d", 50.0),
                bb_upper=row.get("bb_upper", 0.0),
                bb_lower=row.get("bb_lower", 0.0),
                bb_middle=row.get("bb_middle", 0.0),
                volume=row.get("volume", 0.0),
                avg_volume_20=row.get("avg_volume_20", 0.0),
                prev_high_20=row.get("prev_high_20", 0.0),
                prev_low_20=row.get("prev_low_20", 0.0),
            )
            
            # Check exit first if we have a position
            if current_position["position"] is not None:
                from trading.strategies.components.models import Position, TradingContext
                from types import MappingProxyType

                pos = Position(
                    symbol=current_position["position"]["symbol"],
                    entry_price=current_position["position"]["entry_price"],
                    quantity=current_position["position"]["quantity"],
                    strategy="optimization",
                    market="futures",
                    timestamp=current_position["position"]["timestamp"],
                )

                # Create TradingContext for exit strategy
                exit_trading_ctx = TradingContext(
                    symbol=self.symbols[0] if self.symbols else "BTC",
                    timestamp=int(row["timestamp"].timestamp() * 1000) if hasattr(row["timestamp"], "timestamp") else 0,
                    market=market_data,
                    regime=context,
                    positions=MappingProxyType({"optimization": pos}),
                )

                signal = exit_strategy.check_exit(exit_trading_ctx, pos)
                if signal:
                    current_position["position"] = None
                    current_position["regime"] = None
                    return {"action": "sell", "fraction": 1.0, "reason": signal.reason}

                return {"action": "hold"}
            
            # No position, check entry
            # Create TradingContext for entry strategy
            from trading.strategies.components.models import TradingContext
            from types import MappingProxyType
            trading_ctx = TradingContext(
                symbol=self.symbols[0] if self.symbols else "BTC",
                timestamp=int(row["timestamp"].timestamp() * 1000) if hasattr(row["timestamp"], "timestamp") else 0,
                market=market_data,
                regime=context,
                positions=MappingProxyType({}),  # No positions for backtesting
            )
            signal = entry_strategy.check_entry(trading_ctx)
            if signal:
                current_position["position"] = {
                    "symbol": self.symbols[0] if self.symbols else "BTC",
                    "entry_price": row["close"],
                    "quantity": signal.quantity,
                    "timestamp": int(row["timestamp"].timestamp() * 1000) if hasattr(row["timestamp"], "timestamp") else 0,
                }
                current_position["regime"] = current_regime
                return {"action": "buy", "fraction": 0.01, "reason": signal.reason}
            
            return {"action": "hold"}
        
        # Run backtest
        backtester = Backtester(
            initial_capital=10_000_000,  # 10M KRW
            fee_rate=0.0005,  # 0.05%
            slippage=0.0004,  # 0.04%
        )
        
        try:
            results = backtester.run(df, regime_strategy_func)
            
            return {
                "win_rate": results.get("win_rate", 0.0),
                "total_return": results.get("total_return", 0.0) / 100.0,  # Convert to decimal
                "max_drawdown": abs(results.get("max_drawdown_pct", 0.0)) / 100.0,  # Convert to decimal
            }
        except Exception as e:
            # Log error and re-raise to fail the trial
            logger.error(f"Backtest error: {e}", exc_info=True)
            raise


@dataclass
class MLPDirectionObjective:
    """Callable objective function for MLP Direction strategy optimization.

    Uses ComponentStrategyAdapter with precomputed MLP predictions to backtest
    different entry/exit/ensemble parameter combinations.

    Returns (win_rate, total_return, max_drawdown) tuple.
    """
    asset: str  # BTC, ETH, SOL
    config_path: str  # Path to allocation.json
    start_date: str
    end_date: str

    def __call__(self, trial: optuna.Trial) -> Tuple[float, float, float]:
        """Evaluate a trial configuration."""
        mlp_config = sample_mlp_trial_config(trial)
        metrics = self._run_backtest(mlp_config)
        return (
            metrics["win_rate"],
            metrics["total_return"],
            metrics["max_drawdown"],
        )

    def _run_backtest(self, mlp_config: Dict[str, Any]) -> Dict[str, float]:
        """Run MLP Direction backtest with sampled parameters."""
        import sys
        from pathlib import Path
        import logging

        web_dir = Path(__file__).parent.parent.parent
        project_root = web_dir.parent
        if str(project_root) not in sys.path:
            sys.path.insert(0, str(project_root))

        logger = logging.getLogger(__name__)

        from scripts.backtest.backtest_mlp import (
            load_strategy_config,
            MLPDirectionBacktester,
        )
        from scripts.backtest._common import load_data

        # Load base strategy config from allocation.json
        try:
            allocation, strategy_id, strategy_config = load_strategy_config(
                config_path=self.config_path,
                symbol=self.asset,
                mode="paper",
            )
        except ValueError as e:
            logger.error(f"Failed to load strategy config: {e}")
            raise

        # Inject sampled ensemble weights into config
        ensemble_models = strategy_config.get("ensemble_models", [])
        weight_keys = ["weight_bwin3", "weight_bwin4", "weight_bwin5", "weight_bwin7"]
        for i, key in enumerate(weight_keys):
            if i < len(ensemble_models) and key in mlp_config.get("ensemble", {}):
                ensemble_models[i]["weight"] = mlp_config["ensemble"][key]

        # Inject sampled adapter-level params
        adapter_params = mlp_config.get("adapter", {})
        for key in ("cash_in_bear", "cash_below_ema200", "stop_loss_cooldown",
                     "drawdown_bear_threshold"):
            if key in adapter_params:
                strategy_config[key] = adapter_params[key]

        # Build entry/exit overrides from sampled params
        entry_overrides = dict(mlp_config.get("entry", {}))
        exit_overrides = dict(mlp_config.get("exit", {}))

        # Resolve data path from asset
        symbol_db_map = {
            "BTC": "data/binance_bitcoin.db",
            "ETH": "data/binance_ethereum.db",
            "SOL": "data/binance_solana.db",
        }
        db_path = str(Path(self.config_path).parent.parent / symbol_db_map.get(
            self.asset.upper(), "data/binance_bitcoin.db"
        ))

        # Load data
        df = load_data(db_path, "minute240", self.start_date, self.end_date, exchange="binance")
        if df.empty:
            raise ValueError(f"No data for {self.asset} ({self.start_date} to {self.end_date})")

        # Initialize backtester and run
        backtester = MLPDirectionBacktester(
            symbol=self.asset,
            config=strategy_config,
            entry_overrides=entry_overrides,
            exit_overrides=exit_overrides,
        )

        df = backtester.prepare_data(df)
        results = backtester.run(df, initial_capital=10_000)

        return {
            "win_rate": results.get("win_rate", 0.0),
            "total_return": results.get("total_return", 0.0) / 100.0,
            "max_drawdown": abs(results.get("max_drawdown_pct", 0.0)) / 100.0,
        }


def create_multi_objective(
    study_name: str,
    storage: Optional[str] = None,
) -> optuna.Study:
    """
    Create an Optuna study with 3 objectives.

    Objectives:
        1. Win Rate (maximize)
        2. Total Return (maximize)
        3. Max Drawdown (minimize)

    Args:
        study_name: Name for the study
        storage: Optional SQLite URL for persistence

    Returns:
        Configured Optuna study
    """
    return optuna.create_study(
        study_name=study_name,
        storage=storage,
        directions=[
            StudyDirection.MAXIMIZE,  # win_rate
            StudyDirection.MAXIMIZE,  # total_return
            StudyDirection.MINIMIZE,  # max_drawdown
        ],
        sampler=optuna.samplers.NSGAIISampler(),
        load_if_exists=True,
    )
