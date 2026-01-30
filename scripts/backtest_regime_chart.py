#!/usr/bin/env python3
"""Generate backtest equity chart with regime overlay."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap
from matplotlib.patches import Patch
import numpy as np
import pandas as pd

from trading.indicators import add_all_indicators
from trading.strategies.components.models import build_market_context
from trading.strategies.components.regime_filter import EnhancedRegimeRouter
from trading.strategies.components.strategy_factory import STRATEGY_REGISTRY


REGIME_ORDER = [
    "BULL_STRONG",
    "BULL_MODERATE",
    "SIDEWAYS_UP",
    "SIDEWAYS_FLAT",
    "SIDEWAYS_DOWN",
    "BEAR_MODERATE",
    "BEAR_STRONG",
    "UNKNOWN",
]

REGIME_COLORS = {
    "BULL_STRONG": "#2e7d32",
    "BULL_MODERATE": "#66bb6a",
    "SIDEWAYS_UP": "#fbc02d",
    "SIDEWAYS_FLAT": "#b0bec5",
    "SIDEWAYS_DOWN": "#f9a825",
    "BEAR_MODERATE": "#ef5350",
    "BEAR_STRONG": "#c62828",
    "UNKNOWN": "#9e9e9e",
}


def _safe_float(value: object, default: float) -> float:
    try:
        if value is None:
            return default
        if isinstance(value, float) and np.isnan(value):
            return default
        return float(value)
    except Exception:
        return default


def compute_regimes(df: pd.DataFrame, config: dict) -> list[str]:
    regime_version = config.get("regime_version", "v1")
    router = None
    if regime_version == "v2":
        router = EnhancedRegimeRouter(
            bbw_block_threshold=config.get("bbw_block_threshold", 25),
            bbw_confirm_threshold=config.get("bbw_confirm_threshold", 50),
            bbw_window=config.get("bbw_window", 100),
            volume_block_ratio=config.get("volume_block_ratio", 0.8),
            volume_boost_ratio=config.get("volume_boost_ratio", 1.2),
            mtf_enabled=config.get("mtf_enabled", True),
        )

    regimes: list[str] = []
    for _, row in df.iterrows():
        mfi = _safe_float(row.get("mfi"), 50.0)
        adx = _safe_float(row.get("adx"), 20.0)
        atr = _safe_float(row.get("atr"), 0.0)
        close = _safe_float(row.get("close"), 0.0)
        volume = _safe_float(row.get("volume"), 0.0)
        avg_volume = _safe_float(row.get("avg_volume_20"), 0.0)

        recent_high = _safe_float(row.get("high_30d"), 0.0)
        if recent_high <= 0:
            recent_high = _safe_float(row.get("prev_high_20"), 0.0)

        context = build_market_context(
            mfi=mfi,
            adx=adx,
            atr=atr,
            close=close,
            volume=volume,
            avg_volume=avg_volume,
            recent_high=recent_high,
        )

        if router is None:
            regimes.append(context.regime)
            continue

        bb_upper = _safe_float(row.get("bb_upper"), 0.0)
        bb_lower = _safe_float(row.get("bb_lower"), 0.0)
        bb_middle = _safe_float(row.get("bb_middle"), 0.0)
        volume_ratio = volume / avg_volume if avg_volume > 0 else 1.0

        filtered_regime = router.get_regime(
            mfi=mfi,
            adx=adx,
            bb_upper=bb_upper,
            bb_lower=bb_lower,
            bb_middle=bb_middle,
            volume_ratio=volume_ratio,
        )

        final_regime = filtered_regime
        if context.is_drawdown_bear and filtered_regime not in ("BEAR_STRONG", "BEAR_MODERATE"):
            final_regime = "BEAR_STRONG" if context.adx >= 25 else "BEAR_MODERATE"

        regimes.append(final_regime)

    return regimes


def build_chart(dates: pd.Series, equity: pd.Series, regimes: list[str], output_path: Path) -> None:
    regime_to_int = {name: idx for idx, name in enumerate(REGIME_ORDER)}
    numeric_regimes = np.array([regime_to_int.get(r, regime_to_int["UNKNOWN"]) for r in regimes])

    cmap = ListedColormap([REGIME_COLORS[r] for r in REGIME_ORDER])

    fig, (ax1, ax2) = plt.subplots(
        2,
        1,
        figsize=(16, 9),
        sharex=True,
        gridspec_kw={"height_ratios": [3, 1]},
    )

    ax1.plot(dates, equity, color="#1565c0", linewidth=1.2, label="Equity")
    ax1.set_title("v35_long_v2 Backtest Equity + Regime")
    ax1.set_ylabel("Equity (USDT)")
    ax1.grid(True, alpha=0.2)

    extent = [mdates.date2num(dates.iloc[0]), mdates.date2num(dates.iloc[-1]), 0, 1]
    ax2.imshow(
        numeric_regimes.reshape(1, -1),
        aspect="auto",
        interpolation="nearest",
        cmap=cmap,
        extent=extent,
    )
    ax2.set_yticks([])
    ax2.set_ylabel("Regime")

    ax2.xaxis.set_major_locator(mdates.YearLocator())
    ax2.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))

    legend_handles = [
        Patch(color=REGIME_COLORS[name], label=name) for name in REGIME_ORDER if name != "UNKNOWN"
    ]
    ax1.legend(handles=legend_handles, loc="upper left", ncol=4, fontsize=8)

    fig.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=140)
    plt.close(fig)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate backtest equity chart with regime overlay")
    parser.add_argument("--strategy", default="v35_long_v2")
    parser.add_argument("--start", default="2020-01-01")
    parser.add_argument("--end", default="2025-01-01")
    parser.add_argument("--capital", type=float, default=10000)
    parser.add_argument("--output", default="logs/backtest_v35_long_v2_regime.png")
    parser.add_argument("--db-path", default=None, help="Optional sqlite DB path override")
    args = parser.parse_args()

    # Optional DB override to avoid live locks
    if args.db_path:
        import core.data_loader as dl
        dl._BINANCE_DB_PATH = Path(args.db_path)

    from web.services.backtest_runner import BacktestJob, _run_generic_backtest

    job = BacktestJob("regime-chart", {
        "strategy_id": args.strategy,
        "start_date": args.start,
        "end_date": args.end,
        "initial_capital": args.capital,
    })

    results, df = _run_generic_backtest(
        args.strategy,
        args.start,
        args.end,
        args.capital,
        job,
    )

    if df is None or df.empty:
        raise SystemExit("No data returned from backtest")

    # Ensure indicators exist (backtest should already do this)
    if "mfi" not in df.columns:
        add_all_indicators(df)

    allocation_path = Path(__file__).parent.parent / "config" / "strategies" / "allocation.json"
    with allocation_path.open("r") as f:
        allocation = json.load(f)
    strategy_config = allocation.get("strategies", {}).get(args.strategy, {})

    regimes = compute_regimes(df, strategy_config)

    equity_curve = pd.DataFrame(results.get("equity_curve", []))
    if equity_curve.empty:
        raise SystemExit("No equity curve in results")

    equity = equity_curve["equity"].astype(float)
    dates = pd.to_datetime(equity_curve["date"])

    output_path = Path(args.output)
    build_chart(dates, equity, regimes, output_path)

    print(f"Chart saved: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
