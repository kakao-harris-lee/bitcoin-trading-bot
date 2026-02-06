"""Growth-focused objective function for V35 optimization.

Implements a single-objective optimization targeting maximum returns
with MDD constraints. Uses ComponentStrategyAdapter for full V35
feature support (RF probability, drawdown protection, core-hold overlay).
"""
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional
import logging
import optuna

from .v35_search_space import sample_v35_config, get_strategy_param_groups

logger = logging.getLogger(__name__)


def calculate_growth_score(
    total_return: float,
    max_drawdown: float,
    sharpe_ratio: float,
    mdd_soft_limit: float = 0.25,
    mdd_hard_limit: float = 0.30,
) -> float:
    """Calculate growth-focused score with MDD constraints.

    Score formula:
        score = total_return - mdd_penalty + sharpe_bonus

    Where:
        - mdd_penalty = 2 * max(0, mdd - 0.25)  (penalize MDD above 25%)
        - sharpe_bonus = 0.1 * max(0, sharpe - 1.0)  (reward Sharpe above 1.0)

    Args:
        total_return: Total return as decimal (1.0 = 100%).
        max_drawdown: Max drawdown as decimal (0.25 = 25%).
        sharpe_ratio: Sharpe ratio.
        mdd_soft_limit: MDD threshold for soft penalty (default 25%).
        mdd_hard_limit: MDD threshold for trial pruning (default 30%).

    Returns:
        Composite growth score (higher is better).

    Raises:
        optuna.TrialPruned: If MDD exceeds hard limit.

    Examples:
        >>> calculate_growth_score(1.20, 0.18, 1.5)  # Good: 120% return, 18% MDD
        1.25  # 1.20 + 0.05 sharpe bonus

        >>> calculate_growth_score(1.50, 0.28, 1.0)  # High MDD: 28% > 25%
        1.44  # 1.50 - 0.06 penalty
    """
    if max_drawdown > mdd_hard_limit:
        raise optuna.TrialPruned(
            f"MDD {max_drawdown:.1%} exceeded hard limit {mdd_hard_limit:.0%}"
        )

    # Soft penalty for MDD above soft limit
    mdd_penalty = max(0, (max_drawdown - mdd_soft_limit) * 2.0)

    # Sharpe bonus for risk-adjusted quality
    sharpe_bonus = max(0, (sharpe_ratio - 1.0) * 0.1)

    score = total_return - mdd_penalty + sharpe_bonus
    return score


@dataclass
class GrowthObjective:
    """Optuna objective for V35 growth optimization.

    Uses ComponentStrategyAdapter for full V35 feature support including:
    - RF probability integration
    - Drawdown protection (3-level)
    - Core-hold overlay logic
    - Dynamic position sizing
    - Stop-loss cooldown

    Attributes:
        strategy_name: Name of V35 strategy to optimize.
        data_path: Path to price data SQLite database.
        start_date: Backtest start date (YYYY-MM-DD).
        end_date: Backtest end date (YYYY-MM-DD).
        symbol: Trading symbol (default "BTC").
        capital: Initial capital in USD (default $10,000).
        enabled_groups: Parameter groups to tune (default: strategy-specific).
        mdd_soft_limit: MDD threshold for soft penalty.
        mdd_hard_limit: MDD threshold for pruning.
    """

    strategy_name: str
    data_path: str
    start_date: str
    end_date: str
    symbol: str = "BTC"
    capital: float = 10_000.0
    enabled_groups: Optional[List[str]] = None
    mdd_soft_limit: float = 0.25
    mdd_hard_limit: float = 0.30

    # Cached data (loaded once)
    _df: Any = field(default=None, repr=False)
    _base_config: Dict[str, Any] = field(default_factory=dict, repr=False)

    def __call__(self, trial: optuna.Trial) -> float:
        """Evaluate trial and return growth score.

        Args:
            trial: Optuna trial with hyperparameters.

        Returns:
            Growth score (higher is better).

        Raises:
            optuna.TrialPruned: If MDD exceeds hard limit or backtest fails.
        """
        # Sample configuration from trial
        config = sample_v35_config(
            trial,
            self.strategy_name,
            self.enabled_groups,
        )

        # Merge with base config
        full_config = {**self._base_config, **config}

        try:
            results = self._run_backtest(full_config)
        except Exception as e:
            logger.warning(f"Backtest failed: {e}")
            raise optuna.TrialPruned(f"Backtest error: {e}")

        # Calculate and return growth score
        return calculate_growth_score(
            total_return=results["total_return"],
            max_drawdown=results["max_drawdown"],
            sharpe_ratio=results["sharpe_ratio"],
            mdd_soft_limit=self.mdd_soft_limit,
            mdd_hard_limit=self.mdd_hard_limit,
        )

    def _load_data(self) -> None:
        """Load price data and base config (cached)."""
        if self._df is not None:
            return

        import sys
        from pathlib import Path
        import json

        # Ensure project root in path
        project_root = Path(__file__).parent.parent.parent.parent
        if str(project_root) not in sys.path:
            sys.path.insert(0, str(project_root))

        from core.data_loader import DataLoader
        from trading.indicators import add_all_indicators

        # Load data
        loader = DataLoader(db_path=self.data_path)
        df = loader.load_timeframe(
            timeframe="minute60",
            start_date=self.start_date,
            end_date=self.end_date,
        )

        if df.empty:
            raise ValueError(
                f"No data found for {self.start_date} to {self.end_date}"
            )

        # Add all indicators
        self._df = add_all_indicators(df)
        logger.info(f"Loaded {len(self._df)} candles for optimization")

        # Load base config from allocation.json
        config_path = project_root / "config/strategies/allocation.json"
        if config_path.exists():
            with open(config_path) as f:
                allocation = json.load(f)
            self._base_config = allocation.get("strategies", {}).get(
                self.strategy_name, {}
            )
        else:
            self._base_config = {}

    def _run_backtest(self, config: Dict[str, Any]) -> Dict[str, float]:
        """Run backtest with ComponentStrategyAdapter.

        Args:
            config: Full configuration dict (base + trial params).

        Returns:
            Dict with total_return, max_drawdown, sharpe_ratio, etc.
        """
        import sys
        from pathlib import Path

        # Ensure project root in path
        project_root = Path(__file__).parent.parent.parent.parent
        if str(project_root) not in sys.path:
            sys.path.insert(0, str(project_root))

        from core.backtester import Backtester
        from core.component_adapter import ComponentStrategyAdapter
        from trading.strategies.components import StrategyFactory

        # Load data if not cached
        self._load_data()

        # Create adapter
        factory = StrategyFactory()
        adapter = ComponentStrategyAdapter(
            factory=factory,
            strategy_name=self.strategy_name,
            config=config,
        )
        adapter.symbol = self.symbol

        # Run backtest with spot settings
        backtester = Backtester(
            initial_capital=self.capital,
            fee_rate=0.001,  # 0.1% spot fee
            slippage=0.0004,  # 0.04% slippage
            market="spot",
        )

        results = backtester.run(self._df, adapter)

        return {
            "total_return": results["total_return"] / 100.0,  # Convert to decimal
            "max_drawdown": abs(results.get("max_drawdown_pct", 0)) / 100.0,
            "sharpe_ratio": results.get("sharpe_ratio", 0),
            "win_rate": results.get("win_rate", 0),
            "total_trades": results.get("total_trades", 0),
            "profit_factor": results.get("profit_factor", 0),
        }


def create_v35_study(
    strategy_name: str,
    start_date: str,
    end_date: str,
    storage: Optional[str] = None,
    sampler_seed: int = 42,
) -> optuna.Study:
    """Create Optuna study for V35 optimization.

    Uses TPE sampler for efficient hyperparameter search.

    Args:
        strategy_name: V35 strategy to optimize.
        start_date: Backtest start date.
        end_date: Backtest end date.
        storage: Optional SQLite URL for persistence.
        sampler_seed: Random seed for reproducibility.

    Returns:
        Configured Optuna study (direction: maximize).
    """
    study_name = f"v35_{strategy_name}_{start_date}_{end_date}"

    return optuna.create_study(
        study_name=study_name,
        storage=storage,
        direction="maximize",  # Maximize growth score
        sampler=optuna.samplers.TPESampler(seed=sampler_seed),
        load_if_exists=True,
    )
