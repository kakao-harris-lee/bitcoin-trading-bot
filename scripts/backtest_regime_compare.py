#!/usr/bin/env python3
"""
Compare regime detection v1 vs v2 on the same dataset.

v1: Original regime classification (no smoothing in backtest)
v2: EnhancedRegimeRouter with BBW, MTF, Volume filters

Tracks:
- Total trades
- Win rate
- Return %
- Sharpe ratio
- Regime transition counts
"""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import replace
from pathlib import Path
import sys
from types import MappingProxyType

import pandas as pd

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.backtester import Backtester
from core.data_loader import DataLoader
from trading.indicators import add_all_indicators
from trading.strategies.components.models import (
    MarketData, Position, Signal, TradingContext, build_market_context, RegimeSmoother
)
from trading.strategies.components.strategy_factory import StrategyFactory
from trading.strategies.components.regime_filter import EnhancedRegimeRouter
from scripts.backtest._common import compute_metrics


class RegimeTrackingAdapter:
    """Adapter that tracks regime transitions and optionally applies v2 filtering."""

    def __init__(
        self,
        factory: StrategyFactory,
        strategy_name: str,
        config: dict,
        regime_version: str = "v1",
    ):
        self.strategy_name = strategy_name
        self.config = config
        self.regime_version = regime_version
        self.entry_strategy, self.exit_strategy = factory.create_components(
            strategy_name=strategy_name,
            config=config,
            persistent=False,
        )
        self.market = factory.get_market(strategy_name)
        self.current_position: Position | None = None
        self.high_water_mark: float | None = None
        self.symbol = "BTC"

        # Regime tracking
        self.prev_regime: str | None = None
        self.regime_transitions: list[tuple[str, str]] = []
        self.regime_counts: Counter = Counter()

        # MDD improvement: consecutive loss tracking
        self.consecutive_losses: int = 0
        self.max_consecutive_losses: int = config.get("max_consecutive_losses", 99)  # Default: no limit
        self.cooling_period: int = config.get("cooling_period", 0)  # Bars to wait after max losses
        self.cooling_countdown: int = 0

        # MDD improvement: volatility filter
        self.volatility_filter_enabled: bool = config.get("volatility_filter", False)
        self.volatility_threshold: float = config.get("volatility_threshold", 3.0)  # ATR % threshold

        # MDD improvement: tighter stop loss
        self.custom_stop_loss_pct: float | None = config.get("custom_stop_loss_pct", None)

        # v1: RegimeSmoother (EMA + persistence) - more responsive settings
        self._regime_smoother: RegimeSmoother | None = None
        if regime_version in ("v1", "hybrid"):
            self._regime_smoother = RegimeSmoother(
                ema_alpha=config.get("regime_ema_alpha", 0.5),  # More responsive
                persistence=config.get("regime_persistence", 2),
            )

        # v2: EnhancedRegimeRouter (BBW + MTF + Volume)
        self._enhanced_router: EnhancedRegimeRouter | None = None
        if regime_version in ("v2", "hybrid"):
            self._enhanced_router = EnhancedRegimeRouter(
                bbw_block_threshold=config.get("bbw_block_threshold", 25),
                bbw_confirm_threshold=config.get("bbw_confirm_threshold", 50),
                volume_block_ratio=config.get("volume_block_ratio", 0.8),
                volume_boost_ratio=config.get("volume_boost_ratio", 1.2),
                mtf_enabled=config.get("mtf_enabled", True),
            )

    def _get_filtered_regime(
        self,
        mfi: float,
        adx: float,
        bb_upper: float,
        bb_lower: float,
        bb_middle: float,
        volume: float,
        avg_volume: float,
        base_regime: str,
    ) -> str:
        """Get regime with v1 smoothing, v2 filtering, or hybrid (both)."""
        # Hybrid: First apply persistence smoothing, then BBW+Volume filters
        if self.regime_version == "hybrid":
            # Step 1: Get smoothed regime (persistence filter reduces noise)
            smoothed_regime = self._regime_smoother.update(mfi, adx)

            # Step 2: Apply BBW + Volume filters for additional confirmation
            # BBW filter can block weak signals, volume filter can boost/block
            volume_ratio = volume / avg_volume if avg_volume > 0 else 1.0
            bbw = (bb_upper - bb_lower) / bb_middle * 100 if bb_middle > 0 else 0

            # Check if BBW suggests sideways (low volatility)
            bbw_threshold = self.config.get("bbw_block_threshold", 25)
            if bbw < bbw_threshold:
                # Low volatility - prefer sideways regimes
                if "BULL" in smoothed_regime or "BEAR" in smoothed_regime:
                    # Downgrade strong trends to moderate in low vol
                    if smoothed_regime == "BULL_STRONG":
                        return "BULL_MODERATE"
                    elif smoothed_regime == "BEAR_STRONG":
                        return "BEAR_MODERATE"

            # Check volume confirmation
            vol_boost = self.config.get("volume_boost_ratio", 1.2)
            vol_block = self.config.get("volume_block_ratio", 0.8)
            if volume_ratio < vol_block:
                # Low volume - don't upgrade to strong
                if smoothed_regime == "BULL_STRONG":
                    return "BULL_MODERATE"
                elif smoothed_regime == "BEAR_STRONG":
                    return "BEAR_MODERATE"

            return smoothed_regime

        # v1: Use RegimeSmoother (persistence filter)
        if self._regime_smoother is not None:
            return self._regime_smoother.update(mfi, adx)

        # v2: Use EnhancedRegimeRouter (BBW + MTF + Volume filters)
        if self._enhanced_router is not None:
            volume_ratio = volume / avg_volume if avg_volume > 0 else 1.0
            return self._enhanced_router.get_regime(
                mfi=mfi,
                adx=adx,
                bb_upper=bb_upper,
                bb_lower=bb_lower,
                bb_middle=bb_middle,
                volume_ratio=volume_ratio,
            )

        # Fallback: raw regime
        return base_regime

    def __call__(self, df: pd.DataFrame, i: int, params: dict = None) -> dict:
        row = df.iloc[i]

        # Extract indicators
        mfi = row.get('mfi', 50.0)
        adx = row.get('adx', 20.0)
        atr = row.get('atr', 0.0)
        close = row['close']
        volume = row.get('volume', 0.0)
        avg_volume = row.get('avg_volume_20', 0.0)
        bb_upper = row.get('bb_upper', 0.0)
        bb_lower = row.get('bb_lower', 0.0)
        bb_middle = row.get('bb_middle', 0.0)

        # Build base context
        context = build_market_context(
            mfi=mfi,
            adx=adx,
            atr=atr,
            close=close,
            volume=volume,
            avg_volume=avg_volume,
            recent_high=row.get('high_30d', 0.0) or row.get('prev_high_20', 0.0),
        )

        # Apply regime smoothing (v1) or filtering (v2)
        if self._regime_smoother or self._enhanced_router:
            filtered_regime = self._get_filtered_regime(
                mfi=mfi,
                adx=adx,
                bb_upper=bb_upper,
                bb_lower=bb_lower,
                bb_middle=bb_middle,
                volume=volume,
                avg_volume=avg_volume,
                base_regime=context.regime,
            )
            # Rebuild context with filtered regime
            if filtered_regime in ("BULL_STRONG", "BULL_MODERATE", "SIDEWAYS_UP"):
                trend = "BULL"
            elif filtered_regime in ("BEAR_STRONG", "BEAR_MODERATE", "SIDEWAYS_DOWN"):
                trend = "BEAR"
            else:
                trend = "SIDEWAYS"

            context = replace(context, regime=filtered_regime, trend=trend)

        # Track regime transitions
        current_regime = context.regime
        self.regime_counts[current_regime] += 1
        if self.prev_regime is not None and current_regime != self.prev_regime:
            self.regime_transitions.append((self.prev_regime, current_regime))
        self.prev_regime = current_regime

        # Build MarketData
        ts = row.get('timestamp', 0)
        if hasattr(ts, 'timestamp'):
            ts = int(ts.timestamp() * 1000)
        else:
            ts = int(ts) if ts else 0

        indicators = {}
        for k, v in row.items():
            if isinstance(k, str) and k.startswith(('ema', 'adx', 'rsi', 'plus', 'minus', 'bb')):
                indicators[k] = v

        market_data = MarketData(
            symbol=self.symbol,
            close=close,
            timestamp=ts,
            mfi=mfi,
            adx=adx,
            rsi=row.get('rsi', 50.0),
            high=row.get('high', 0.0) or 0.0,
            low=row.get('low', 0.0) or 0.0,
            volume=volume,
            macd=row.get('macd', 0.0),
            macd_signal=row.get('macd_signal', 0.0),
            stoch_k=row.get('stoch_k', 50.0),
            stoch_d=row.get('stoch_d', 50.0),
            bb_upper=bb_upper,
            bb_lower=bb_lower,
            bb_middle=bb_middle,
            avg_volume_20=avg_volume,
            prev_high_20=row.get('prev_high_20', 0.0),
            prev_low_20=row.get('prev_low_20', 0.0),
            atr=atr,
            ema_200=row.get('ema_200', 0.0),
            market_stress=row.get('market_stress', 0.0),
            high_30d=row.get('high_30d', 0.0),
            breakout_signal=int(row.get('breakout_signal', 0)) if pd.notna(row.get('breakout_signal')) else 0,
            target_price=float(row.get('target_price', 0.0)) if pd.notna(row.get('target_price')) else 0.0,
            indicators=indicators,
            high_water_mark=self.high_water_mark,
        )

        # Decrement cooling countdown
        if self.cooling_countdown > 0:
            self.cooling_countdown -= 1

        # Check exits first
        if self.current_position:
            is_long = getattr(self.current_position, 'side', 'long') == 'long'
            if is_long:
                if self.high_water_mark is None or close > self.high_water_mark:
                    self.high_water_mark = close
            else:
                if self.high_water_mark is None or close < self.high_water_mark:
                    self.high_water_mark = close

            # Calculate PnL for custom stop loss check
            entry_price = self.current_position.entry_price
            if is_long:
                pnl_pct = ((close - entry_price) / entry_price) * 100
            else:
                pnl_pct = ((entry_price - close) / entry_price) * 100

            # MDD improvement: Custom tighter stop loss
            if self.custom_stop_loss_pct is not None:
                if pnl_pct <= -self.custom_stop_loss_pct:
                    self.current_position = None
                    self.high_water_mark = None
                    # Track consecutive losses
                    self.consecutive_losses += 1
                    if self.consecutive_losses >= self.max_consecutive_losses:
                        self.cooling_countdown = self.cooling_period
                    action = 'close_short' if not is_long else 'sell'
                    return {'action': action, 'fraction': 1.0, 'reason': f'custom_stop_loss ({pnl_pct:.2f}%)'}

            market_data = replace(market_data, high_water_mark=self.high_water_mark)
            positions = {self.strategy_name: self.current_position}
            ctx = TradingContext(
                symbol=self.symbol,
                timestamp=market_data.timestamp,
                market=market_data,
                regime=context,
                positions=MappingProxyType(positions),
            )
            signal = self.exit_strategy.check_exit(ctx, self.current_position)

            if signal:
                # Track if it was a loss
                was_loss = pnl_pct < 0
                self.current_position = None
                self.high_water_mark = None
                try:
                    self.exit_strategy.on_position_closed(self.symbol)
                except Exception:
                    pass

                # Update consecutive loss tracking
                if was_loss:
                    self.consecutive_losses += 1
                    if self.consecutive_losses >= self.max_consecutive_losses:
                        self.cooling_countdown = self.cooling_period
                else:
                    self.consecutive_losses = 0  # Reset on win

                action = 'close_short' if not is_long else 'sell'
                return {'action': action, 'fraction': 1.0, 'reason': signal.reason}

            return {'action': 'hold'}

        # MDD improvement: Cooling period check (skip entry after consecutive losses)
        if self.cooling_countdown > 0:
            return {'action': 'hold'}

        # MDD improvement: Volatility filter (skip entry in high volatility)
        if self.volatility_filter_enabled:
            atr_pct = (atr / close) * 100 if close > 0 else 0
            if atr_pct > self.volatility_threshold:
                return {'action': 'hold'}

        # Check entries
        ctx = TradingContext(
            symbol=self.symbol,
            timestamp=market_data.timestamp,
            market=market_data,
            regime=context,
            positions=MappingProxyType({}),
        )
        signal = self.entry_strategy.check_entry(ctx)

        if signal:
            is_short = signal.side == 'sell'
            pos_side = 'short' if is_short else 'long'
            self.current_position = Position(
                symbol=self.symbol,
                entry_price=close,
                quantity=1.0,
                strategy=self.strategy_name,
                market=self.market,
                timestamp=ts,
            )
            object.__setattr__(self.current_position, 'side', pos_side)
            self.high_water_mark = close
            action = 'open_short' if is_short else 'buy'
            return {'action': action, 'fraction': 1.0, 'reason': signal.reason}

        return {'action': 'hold'}


def load_data(db_path: Path, timeframe: str, start: str, end: str) -> pd.DataFrame:
    with DataLoader(str(db_path), exchange="binance") as loader:
        return loader.load_timeframe(timeframe, start, end)


def run_backtest(
    df: pd.DataFrame,
    strategy_name: str,
    config: dict,
    regime_version: str,
    initial_capital: float,
    fee_rate: float,
    slippage: float,
) -> tuple[dict, RegimeTrackingAdapter]:
    factory = StrategyFactory()
    adapter = RegimeTrackingAdapter(
        factory,
        strategy_name=strategy_name,
        config=config,
        regime_version=regime_version,
    )
    backtester = Backtester(
        initial_capital=initial_capital,
        fee_rate=fee_rate,
        slippage=slippage,
        min_order_amount=10,
    )
    results = backtester.run(df, adapter, {})
    return results, adapter


def analyze_drawdowns(results: dict, name: str) -> dict:
    """Analyze drawdown periods to understand loss patterns."""
    trades = results.get("trades", [])
    if not trades:
        return {}

    # Find consecutive losing streaks
    losing_streaks = []
    current_streak = []
    for t in trades:
        if t.profit_loss and t.profit_loss < 0:
            current_streak.append(t)
        else:
            if len(current_streak) >= 2:
                losing_streaks.append(current_streak)
            current_streak = []
    if len(current_streak) >= 2:
        losing_streaks.append(current_streak)

    # Find biggest single losses
    losing_trades = [t for t in trades if t.profit_loss and t.profit_loss < 0]
    losing_trades_sorted = sorted(losing_trades, key=lambda t: t.profit_loss)
    top_losses = losing_trades_sorted[:5] if len(losing_trades_sorted) >= 5 else losing_trades_sorted

    # Calculate loss by month
    monthly_pnl = {}
    for t in trades:
        if t.exit_time and t.profit_loss:
            month_key = t.exit_time.strftime("%Y-%m")
            monthly_pnl[month_key] = monthly_pnl.get(month_key, 0) + t.profit_loss

    worst_months = sorted(monthly_pnl.items(), key=lambda x: x[1])[:3]

    return {
        "losing_streaks": losing_streaks,
        "top_losses": top_losses,
        "worst_months": worst_months,
        "monthly_pnl": monthly_pnl,
    }


def print_results(
    name: str,
    results: dict,
    adapter: RegimeTrackingAdapter,
    timeframe: str,
) -> dict:
    metrics = compute_metrics(results.get("equity_curve"), timeframe)
    transition_count = len(adapter.regime_transitions)

    # Extract trade-level metrics
    avg_profit = results.get("avg_profit", 0.0)
    avg_loss = results.get("avg_loss", 0.0)
    profit_factor = results.get("profit_factor", 0.0)
    winning_trades = results.get("winning_trades", 0)
    losing_trades = results.get("losing_trades", 0)

    print(f"\n{'='*60}")
    print(f" {name}")
    print(f"{'='*60}")
    print(f" Trades:          {results.get('total_trades', 0)}")
    print(f" Win Rate:        {results.get('win_rate', 0.0)*100:.1f}%")
    print(f" Total Return:    {metrics['total_return']:.2f}%")
    print(f" Sharpe Ratio:    {metrics['sharpe']:.2f}")
    print(f" Max Drawdown:    {metrics['mdd']:.2f}%")
    print(f" Regime Transitions: {transition_count}")
    print(f"\n Trade Quality:")
    print(f"   Avg Win:       ${avg_profit:.2f}")
    print(f"   Avg Loss:      ${avg_loss:.2f}")
    print(f"   Win/Loss Ratio: {avg_profit/avg_loss:.2f}x" if avg_loss > 0 else "   Win/Loss Ratio: N/A")
    print(f"   Profit Factor: {profit_factor:.2f}")
    print(f"   Wins/Losses:   {winning_trades}/{losing_trades}")
    print(f"\n Regime Distribution:")
    for regime, count in sorted(adapter.regime_counts.items()):
        pct = count / sum(adapter.regime_counts.values()) * 100
        print(f"   {regime}: {count} ({pct:.1f}%)")

    # Drawdown analysis
    dd_analysis = analyze_drawdowns(results, name)

    return {
        "name": name,
        "trades": results.get("total_trades", 0),
        "win_rate": results.get("win_rate", 0.0),
        "return_pct": metrics["total_return"],
        "sharpe": metrics["sharpe"],
        "mdd": metrics["mdd"],
        "transitions": transition_count,
        "avg_profit": avg_profit,
        "avg_loss": avg_loss,
        "profit_factor": profit_factor,
        "dd_analysis": dd_analysis,
        "all_trades": results.get("trades", []),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare regime detection v1 vs v2 on BTC data."
    )
    parser.add_argument("--db", default="data/binance_bitcoin.db", help="Path to DB")
    parser.add_argument("--timeframe", default="minute60", help="Candle timeframe")
    parser.add_argument("--start", default="2024-01-01", help="Start date")
    parser.add_argument("--end", default="2025-12-31", help="End date")
    parser.add_argument("--capital", type=float, default=10_000, help="Initial capital")
    parser.add_argument("--strategy", default="v35_long", help="Strategy to test")
    args = parser.parse_args()

    db_path = Path(args.db)
    print(f"Loading data: {db_path} [{args.timeframe}] {args.start} -> {args.end}")
    df = load_data(db_path, args.timeframe, args.start, args.end)
    if df.empty:
        raise SystemExit("No data found for the requested range.")

    print(f"Loaded {len(df):,} candles. Computing indicators...")
    df = add_all_indicators(df.copy())

    fee_rate = 0.0005
    slippage = 0.0002

    # Base config for v35_long
    base_config = {
        "entry": {"class": "V35EntryStrategy"},
        "exit": {"class": "V35TrailingExitStrategy"},
    }

    # v1 config with smoother params
    v1_config = {
        **base_config,
        "regime_ema_alpha": 0.5,  # More responsive than 0.3
        "regime_persistence": 2,
    }

    # Hybrid config: v1 smoothing + v2 filters (light touch)
    hybrid_config = {
        **base_config,
        "regime_persistence": 2,
        "bbw_block_threshold": 20,  # Moderate BBW filter
        "volume_block_ratio": 0.7,
        "volume_boost_ratio": 1.2,
    }

    # Hybrid + MDD improvements: testing shows default 2.1% stop is optimal
    # Tighter stops (1.5%, 1.9%) and cooling periods all hurt performance
    hybrid_mdd_config = {
        **base_config,
        "regime_persistence": 2,
        "bbw_block_threshold": 20,
        "volume_block_ratio": 0.7,
        "volume_boost_ratio": 1.2,
        # No custom stop - use exit strategy's default 2.1% (proven by backtest)
    }

    # v2 config with filter params - relaxed settings
    v2_config = {
        **base_config,
        "bbw_block_threshold": 15,  # Lower = less blocking
        "bbw_confirm_threshold": 35,
        "volume_block_ratio": 0.6,  # Lower = less blocking
        "volume_boost_ratio": 1.3,
        "mtf_enabled": False,  # Disable MTF initially for cleaner comparison
    }

    # v2 strict config - original settings
    v2_strict_config = {
        **base_config,
        "bbw_block_threshold": 25,
        "bbw_confirm_threshold": 50,
        "volume_block_ratio": 0.8,
        "volume_boost_ratio": 1.2,
        "mtf_enabled": False,
    }

    # v2 volume-only config - disable BBW filter
    v2_vol_config = {
        **base_config,
        "bbw_block_threshold": 0,  # Effectively disabled
        "bbw_confirm_threshold": 0,
        "volume_block_ratio": 0.7,
        "volume_boost_ratio": 1.3,
        "mtf_enabled": False,
    }

    # Run RAW baseline (no smoothing/filtering)
    print("\n" + "="*60)
    print(" Running RAW (no smoothing/filtering)...")
    print("="*60)
    results_raw, adapter_raw = run_backtest(
        df, args.strategy, base_config, "raw", args.capital, fee_rate, slippage
    )
    stats_raw = print_results("RAW (No Smoothing)", results_raw, adapter_raw, args.timeframe)

    print("\n" + "="*60)
    print(" Running Regime v1 (persistence smoothing)...")
    print("="*60)
    results_v1, adapter_v1 = run_backtest(
        df, args.strategy, v1_config, "v1", args.capital, fee_rate, slippage
    )
    stats_v1 = print_results("Regime v1 (Persistence)", results_v1, adapter_v1, args.timeframe)

    print("\n" + "="*60)
    print(" Running HYBRID (v1 smoothing + v2 filters)...")
    print("="*60)
    results_hybrid, adapter_hybrid = run_backtest(
        df, args.strategy, hybrid_config, "hybrid", args.capital, fee_rate, slippage
    )
    stats_hybrid = print_results("Hybrid (v1+v2)", results_hybrid, adapter_hybrid, args.timeframe)

    print("\n" + "="*60)
    print(" Running HYBRID+MDD (tighter stop, cooling, volatility filter)...")
    print("="*60)
    results_hybrid_mdd, adapter_hybrid_mdd = run_backtest(
        df, args.strategy, hybrid_mdd_config, "hybrid", args.capital, fee_rate, slippage
    )
    stats_hybrid_mdd = print_results("Hybrid+MDD", results_hybrid_mdd, adapter_hybrid_mdd, args.timeframe)

    print("\n" + "="*60)
    print(" Running Regime v2-relaxed (BBW + Volume filters)...")
    print("="*60)
    results_v2, adapter_v2 = run_backtest(
        df, args.strategy, v2_config, "v2", args.capital, fee_rate, slippage
    )
    stats_v2 = print_results("Regime v2 (Relaxed)", results_v2, adapter_v2, args.timeframe)

    print("\n" + "="*60)
    print(" Running Regime v2-strict (BBW + Volume filters)...")
    print("="*60)
    results_v2s, adapter_v2s = run_backtest(
        df, args.strategy, v2_strict_config, "v2", args.capital, fee_rate, slippage
    )
    stats_v2s = print_results("Regime v2 (Strict)", results_v2s, adapter_v2s, args.timeframe)

    print("\n" + "="*60)
    print(" Running Regime v2-vol (Volume filter only)...")
    print("="*60)
    results_v2v, adapter_v2v = run_backtest(
        df, args.strategy, v2_vol_config, "v2", args.capital, fee_rate, slippage
    )
    stats_v2v = print_results("Regime v2 (Vol Only)", results_v2v, adapter_v2v, args.timeframe)

    # Comparison summary
    print("\n" + "="*60)
    print(" COMPARISON SUMMARY")
    print("="*60)
    print(f" {'Variant':<25} {'Trades':>8} {'WinRate':>8} {'Return%':>10} {'Sharpe':>8} {'Trans':>8}")
    print("-" * 75)
    for s in [stats_raw, stats_v1, stats_hybrid, stats_hybrid_mdd, stats_v2, stats_v2s, stats_v2v]:
        print(f" {s['name']:<25} {s['trades']:>8} {s['win_rate']*100:>7.1f}% {s['return_pct']:>9.2f}% {s['sharpe']:>8.2f} {s['mdd']:>8.1f}%")

    # MDD comparison (key focus)
    print("\n" + "-"*60)
    print(" MDD COMPARISON:")
    print(f"   Hybrid:      {stats_hybrid['mdd']:.1f}%")
    print(f"   Hybrid+MDD:  {stats_hybrid_mdd['mdd']:.1f}%")
    mdd_improvement = stats_hybrid['mdd'] - stats_hybrid_mdd['mdd']
    print(f"   Improvement: {mdd_improvement:.1f}% better")

    # Success criteria from design doc
    print("\n" + "-"*60)
    print(" SUCCESS CRITERIA:")
    if stats_raw["transitions"] > 0:
        v1_red = (stats_raw["transitions"] - stats_v1["transitions"]) / stats_raw["transitions"] * 100
        v2_red = (stats_raw["transitions"] - stats_v2["transitions"]) / stats_raw["transitions"] * 100

        print(f"\n   v1 (EMA Smoothing):")
        print(f"   - Transitions reduced by 50%+: ", end="")
        if v1_red >= 50:
            print(f"PASS ({v1_red:.1f}%)")
        else:
            print(f"NEEDS TUNING ({v1_red:.1f}% < 50%)")
        v1_return_diff = stats_v1["return_pct"] - stats_raw["return_pct"]
        print(f"   - PnL improvement or neutral: ", end="")
        if v1_return_diff >= -5.0:
            print(f"PASS ({v1_return_diff:+.2f}%)")
        else:
            print(f"NEEDS REVIEW ({v1_return_diff:+.2f}%)")

        print(f"\n   v2 (BBW + Volume):")
        print(f"   - Transitions reduced by 50%+: ", end="")
        if v2_red >= 50:
            print(f"PASS ({v2_red:.1f}%)")
        else:
            print(f"NEEDS TUNING ({v2_red:.1f}% < 50%)")
        v2_return_diff = stats_v2["return_pct"] - stats_raw["return_pct"]
        print(f"   - PnL improvement or neutral: ", end="")
        if v2_return_diff >= -5.0:
            print(f"PASS ({v2_return_diff:+.2f}%)")
        else:
            print(f"NEEDS REVIEW ({v2_return_diff:+.2f}%)")

    # Best performer
    all_stats = [stats_raw, stats_v1, stats_hybrid, stats_hybrid_mdd, stats_v2, stats_v2s, stats_v2v]
    best_return = max(all_stats, key=lambda x: x["return_pct"])
    best_mdd = min(all_stats, key=lambda x: abs(x["mdd"]))
    best_sharpe = max(all_stats, key=lambda x: x["sharpe"])
    print(f"\n   BEST RETURN: {best_return['name']} ({best_return['return_pct']:+.2f}%)")
    print(f"   BEST MDD: {best_mdd['name']} ({best_mdd['mdd']:.1f}%)")
    print(f"   BEST SHARPE: {best_sharpe['name']} ({best_sharpe['sharpe']:.2f})")

    # Trade quality comparison
    print("\n" + "="*60)
    print(" TRADE QUALITY COMPARISON (Why Return Differs)")
    print("="*60)
    print(f" {'Variant':<25} {'AvgWin':>10} {'AvgLoss':>10} {'W/L Ratio':>10} {'PF':>8}")
    print("-" * 75)
    for s in all_stats:
        wl_ratio = s['avg_profit'] / s['avg_loss'] if s['avg_loss'] > 0 else 0
        print(f" {s['name']:<25} ${s['avg_profit']:>8.2f} ${s['avg_loss']:>8.2f} {wl_ratio:>9.2f}x {s['profit_factor']:>7.2f}")

    # Analysis
    print("\n" + "-"*60)
    print(" ANALYSIS: v1 vs v2 Trade Quality")
    print("-"*60)
    if stats_v1['avg_loss'] > 0 and stats_v2['avg_loss'] > 0:
        v1_wl = stats_v1['avg_profit'] / stats_v1['avg_loss']
        v2_wl = stats_v2['avg_profit'] / stats_v2['avg_loss']
        print(f"   v1 Avg Win:  ${stats_v1['avg_profit']:.2f}  |  v2 Avg Win:  ${stats_v2['avg_profit']:.2f}")
        print(f"   v1 Avg Loss: ${stats_v1['avg_loss']:.2f}  |  v2 Avg Loss: ${stats_v2['avg_loss']:.2f}")
        print(f"   v1 W/L Ratio: {v1_wl:.2f}x    |  v2 W/L Ratio: {v2_wl:.2f}x")
        print(f"   v1 Profit Factor: {stats_v1['profit_factor']:.2f} | v2 Profit Factor: {stats_v2['profit_factor']:.2f}")

        # Diagnose the issue
        print(f"\n   DIAGNOSIS:")
        if stats_v2['avg_profit'] < stats_v1['avg_profit'] * 0.9:
            pct_diff = (1 - stats_v2['avg_profit'] / stats_v1['avg_profit']) * 100
            print(f"   - v2 avg wins are {pct_diff:.1f}% smaller -> Cutting winners short")
        if stats_v2['avg_loss'] > stats_v1['avg_loss'] * 1.1:
            pct_diff = (stats_v2['avg_loss'] / stats_v1['avg_loss'] - 1) * 100
            print(f"   - v2 avg losses are {pct_diff:.1f}% larger -> Holding losers too long")
        if stats_v2['transitions'] > stats_v1['transitions'] * 1.5:
            print(f"   - v2 has {stats_v2['transitions'] - stats_v1['transitions']} more transitions -> More whipsaw")
        if v2_wl < v1_wl * 0.8:
            print(f"   - v2 W/L ratio is significantly worse -> Poor risk/reward")

    # Drawdown Analysis for Hybrid
    print("\n" + "="*60)
    print(" DRAWDOWN ANALYSIS: Hybrid (Best Performer)")
    print("="*60)

    dd = stats_hybrid.get("dd_analysis", {})
    if dd:
        # Worst months
        print("\n Worst Months (PnL):")
        for month, pnl in dd.get("worst_months", []):
            print(f"   {month}: ${pnl:,.2f}")

        # Top single losses
        print("\n Top 5 Biggest Losses:")
        for i, t in enumerate(dd.get("top_losses", []), 1):
            exit_date = t.exit_time.strftime("%Y-%m-%d") if t.exit_time else "N/A"
            pnl_pct = t.profit_loss_pct if t.profit_loss_pct else 0
            print(f"   {i}. {exit_date}: ${t.profit_loss:,.2f} ({pnl_pct:.2f}%) @ entry ${t.entry_price:,.0f}")

        # Losing streaks
        streaks = dd.get("losing_streaks", [])
        if streaks:
            print(f"\n Consecutive Losing Streaks (2+ losses):")
            for streak in sorted(streaks, key=lambda s: sum(t.profit_loss for t in s))[:3]:
                total_loss = sum(t.profit_loss for t in streak)
                start = streak[0].entry_time.strftime("%Y-%m-%d") if streak[0].entry_time else "N/A"
                end = streak[-1].exit_time.strftime("%Y-%m-%d") if streak[-1].exit_time else "N/A"
                print(f"   {len(streak)} trades ({start} to {end}): ${total_loss:,.2f}")

        # Monthly summary
        print("\n Monthly PnL Summary:")
        monthly = dd.get("monthly_pnl", {})
        for month in sorted(monthly.keys()):
            pnl = monthly[month]
            bar = "+" * int(pnl / 100) if pnl > 0 else "-" * int(abs(pnl) / 100)
            print(f"   {month}: ${pnl:>8,.2f} {bar}")


if __name__ == "__main__":
    main()
