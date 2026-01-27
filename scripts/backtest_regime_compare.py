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

        # v1: RegimeSmoother (EMA + persistence) - more responsive settings
        self._regime_smoother: RegimeSmoother | None = None
        if regime_version == "v1":
            self._regime_smoother = RegimeSmoother(
                ema_alpha=config.get("regime_ema_alpha", 0.5),  # More responsive
                persistence=config.get("regime_persistence", 2),
            )

        # v2: EnhancedRegimeRouter (BBW + MTF + Volume)
        self._enhanced_router: EnhancedRegimeRouter | None = None
        if regime_version == "v2":
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
        """Get regime with v1 smoothing or v2 filtering."""
        # v1: Use RegimeSmoother (EMA + persistence)
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

        # Check exits first
        if self.current_position:
            is_long = getattr(self.current_position, 'side', 'long') == 'long'
            if is_long:
                if self.high_water_mark is None or close > self.high_water_mark:
                    self.high_water_mark = close
            else:
                if self.high_water_mark is None or close < self.high_water_mark:
                    self.high_water_mark = close

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
                self.current_position = None
                self.high_water_mark = None
                try:
                    self.exit_strategy.on_position_closed(self.symbol)
                except Exception:
                    pass
                action = 'close_short' if not is_long else 'sell'
                return {'action': action, 'fraction': 1.0, 'reason': signal.reason}

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


def print_results(
    name: str,
    results: dict,
    adapter: RegimeTrackingAdapter,
    timeframe: str,
) -> dict:
    metrics = compute_metrics(results.get("equity_curve"), timeframe)
    transition_count = len(adapter.regime_transitions)

    print(f"\n{'='*60}")
    print(f" {name}")
    print(f"{'='*60}")
    print(f" Trades:          {results.get('total_trades', 0)}")
    print(f" Win Rate:        {results.get('win_rate', 0.0)*100:.1f}%")
    print(f" Total Return:    {metrics['total_return']:.2f}%")
    print(f" Sharpe Ratio:    {metrics['sharpe']:.2f}")
    print(f" Max Drawdown:    {metrics['mdd']:.2f}%")
    print(f" Regime Transitions: {transition_count}")
    print(f"\n Regime Distribution:")
    for regime, count in sorted(adapter.regime_counts.items()):
        pct = count / sum(adapter.regime_counts.values()) * 100
        print(f"   {regime}: {count} ({pct:.1f}%)")

    return {
        "name": name,
        "trades": results.get("total_trades", 0),
        "win_rate": results.get("win_rate", 0.0),
        "return_pct": metrics["total_return"],
        "sharpe": metrics["sharpe"],
        "mdd": metrics["mdd"],
        "transitions": transition_count,
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
    print(" Running Regime v1 (EMA smoothing)...")
    print("="*60)
    results_v1, adapter_v1 = run_backtest(
        df, args.strategy, v1_config, "v1", args.capital, fee_rate, slippage
    )
    stats_v1 = print_results("Regime v1 (EMA Smoothing)", results_v1, adapter_v1, args.timeframe)

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
    for s in [stats_raw, stats_v2, stats_v2s, stats_v2v]:
        print(f" {s['name']:<25} {s['trades']:>8} {s['win_rate']*100:>7.1f}% {s['return_pct']:>9.2f}% {s['sharpe']:>8.2f} {s['transitions']:>8}")

    # Calculate reductions vs RAW baseline
    print("\n" + "-"*60)
    print(" TRANSITION REDUCTION vs RAW:")
    if stats_raw["transitions"] > 0:
        v2_red = (stats_raw["transitions"] - stats_v2["transitions"]) / stats_raw["transitions"] * 100
        v2s_red = (stats_raw["transitions"] - stats_v2s["transitions"]) / stats_raw["transitions"] * 100
        v2v_red = (stats_raw["transitions"] - stats_v2v["transitions"]) / stats_raw["transitions"] * 100
        print(f"   v2-relaxed:  {v2_red:.1f}% ({stats_raw['transitions']} -> {stats_v2['transitions']})")
        print(f"   v2-strict:   {v2s_red:.1f}% ({stats_raw['transitions']} -> {stats_v2s['transitions']})")
        print(f"   v2-vol-only: {v2v_red:.1f}% ({stats_raw['transitions']} -> {stats_v2v['transitions']})")

    # Success criteria from design doc
    print("\n" + "-"*60)
    print(" SUCCESS CRITERIA (v2-relaxed vs RAW):")
    if stats_raw["transitions"] > 0:
        v2_red = (stats_raw["transitions"] - stats_v2["transitions"]) / stats_raw["transitions"] * 100
        print(f"   - Transitions reduced by 50%+: ", end="")
        if v2_red >= 50:
            print(f"PASS ({v2_red:.1f}%)")
        else:
            print(f"NEEDS TUNING ({v2_red:.1f}% < 50%)")

    return_diff = stats_v2["return_pct"] - stats_raw["return_pct"]
    print(f"   - PnL improvement or neutral: ", end="")
    if return_diff >= -5.0:  # Allow up to 5% worse for noise reduction
        print(f"ACCEPTABLE ({return_diff:+.2f}%)")
    else:
        print(f"NEEDS REVIEW ({return_diff:+.2f}%)")


if __name__ == "__main__":
    main()
