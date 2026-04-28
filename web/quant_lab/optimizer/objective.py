"""Multi-objective optimization function for regime-based strategies."""
# pylint: disable=broad-exception-caught
from dataclasses import dataclass
from typing import List, Tuple, Dict, Any, Optional
import optuna
from optuna.study import StudyDirection

from .search_space import SearchSpaceConfig, sample_trial_config


@dataclass
class RegimeBacktestObjective:
    """Callable objective function for Optuna multi-objective optimization.

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
        config = sample_trial_config(trial, self.search_config)
        metrics = self._run_backtest(config)
        return (
            metrics["win_rate"],
            metrics["total_return"],
            metrics["max_drawdown"],
        )

    def _run_backtest(self, config: Dict[str, Any]) -> Dict[str, float]:
        import sys
        from pathlib import Path

        web_dir = Path(__file__).parent.parent.parent
        project_root = web_dir.parent
        if str(project_root) not in sys.path:
            sys.path.insert(0, str(project_root))

        from core.data_loader import DataLoader
        from core.backtester import Backtester
        from trading.strategies.components.registry import get_entry_class, get_exit_class
        from trading.indicators import add_all_indicators
        from trading.strategies.components.models import build_market_context
        import pandas as pd
        import logging

        logger = logging.getLogger(__name__)

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

        df = add_all_indicators(df)

        regime_strategies = {}
        for regime, regime_config in config.items():
            entry_name = regime_config.get("entry")
            exit_name = regime_config.get("exit")
            if entry_name == "None" or not entry_name:
                regime_strategies[regime] = None
                continue

            entry_params = regime_config.get("params", {}).get("entry", {})
            exit_params = regime_config.get("params", {}).get("exit", {})

            try:
                entry_cls = get_entry_class(entry_name + "Strategy") if entry_name != "None" else None
                exit_cls = get_exit_class(exit_name + "Strategy") if exit_name != "None" else None

                from trading.strategies.components.registry import (
                    get_entry_params_class,
                    get_exit_params_class,
                    build_params_from_config,
                )

                entry_params_cls = get_entry_params_class(entry_name + "Strategy")
                exit_params_cls = get_exit_params_class(exit_name + "Strategy")
                entry_params_obj = build_params_from_config(entry_params_cls, entry_params) if entry_params_cls else None
                exit_params_obj = build_params_from_config(exit_params_cls, exit_params) if exit_params_cls else None

                regime_strategies[regime] = {
                    "entry": entry_cls(entry_params_obj),
                    "exit": exit_cls(exit_params_obj),
                }
            except Exception as exc:
                logger.warning("Failed to create components for %s: %s", regime, exc)
                regime_strategies[regime] = None

        regime_thresholds = config.pop("regime_thresholds", {})
        current_position: Dict[str, Any] = {"position": None, "regime": None}

        def regime_strategy_func(df_data: pd.DataFrame, i: int, _params: dict) -> dict:
            if i < 200:
                return {"action": "hold"}

            row = df_data.iloc[i]
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
                **regime_thresholds,
            )
            current_regime = context.regime
            strategy_components = regime_strategies.get(current_regime)

            if strategy_components is None:
                if current_position["position"] is not None:
                    current_position["position"] = None
                    current_position["regime"] = None
                    return {"action": "sell", "fraction": 1.0, "reason": f"Regime changed to {current_regime} (no trading)"}
                return {"action": "hold"}

            entry_strategy = strategy_components["entry"]
            exit_strategy = strategy_components["exit"]

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

            position_data = current_position.get("position")
            if isinstance(position_data, dict):
                from trading.strategies.components.models import Position, TradingContext
                from types import MappingProxyType

                pos = Position(
                    symbol=position_data["symbol"],
                    entry_price=position_data["entry_price"],
                    quantity=position_data["quantity"],
                    strategy="optimization",
                    market="spot",
                    timestamp=position_data["timestamp"],
                )

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

            from trading.strategies.components.models import TradingContext
            from types import MappingProxyType
            trading_ctx = TradingContext(
                symbol=self.symbols[0] if self.symbols else "BTC",
                timestamp=int(row["timestamp"].timestamp() * 1000) if hasattr(row["timestamp"], "timestamp") else 0,
                market=market_data,
                regime=context,
                positions=MappingProxyType({}),
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

        backtester = Backtester(
            initial_capital=10_000_000,
            fee_rate=0.0005,
            slippage=0.0004,
        )

        try:
            results = backtester.run(df, regime_strategy_func)
            return {
                "win_rate": results.get("win_rate", 0.0),
                "total_return": results.get("total_return", 0.0) / 100.0,
                "max_drawdown": abs(results.get("max_drawdown_pct", 0.0)) / 100.0,
            }
        except Exception as exc:
            logger.error("Backtest error: %s", exc, exc_info=True)
            raise


def create_multi_objective(
    study_name: str,
    storage: Optional[str] = None,
) -> optuna.Study:
    """Create an Optuna study with 3 objectives."""
    return optuna.create_study(
        study_name=study_name,
        storage=storage,
        directions=[
            StudyDirection.MAXIMIZE,
            StudyDirection.MAXIMIZE,
            StudyDirection.MINIMIZE,
        ],
        sampler=optuna.samplers.NSGAIISampler(),
        load_if_exists=True,
    )
