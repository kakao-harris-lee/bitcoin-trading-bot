#!/usr/bin/env python3
"""Regime Ablation Study — measure each regime filter's contribution.

Runs 6 regime configurations across 3 assets and up to 3 strategy types,
producing a comparison table of returns, MDD, Sharpe, and trade counts.

Configs:
  baseline    — Regime filters completely disabled (regime_bypass=True)
  v2_full     — Current production (MTF + BBW + Volume)
  v2_no_mtf   — BBW + Volume only
  v2_no_bbw   — MTF + Volume only
  v2_no_vol   — MTF + BBW only
  regime_only — Raw _classify_regime() without any V2 filters

Usage:
    python scripts/backtest/regime_ablation.py
    python scripts/backtest/regime_ablation.py --assets BTC ETH --strategies mlp
    python scripts/backtest/regime_ablation.py --start-date 2025-01-01 --end-date 2026-01-01
    python scripts/backtest/regime_ablation.py --csv ablation_results.csv
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.backtest._common import load_data, compute_metrics, compute_trade_stats
from scripts.backtest.backtest_mlp import MLPDirectionBacktester
from core.backtester import Backtester
from core.component_adapter import ComponentStrategyAdapter
from trading.strategies.components.strategy_factory import StrategyFactory

# ── Asset database mapping ──────────────────────────────────────────
ASSET_DB = {
    "BTC": "data/binance_bitcoin.db",
    "ETH": "data/binance_ethereum.db",
    "SOL": "data/binance_solana.db",
}

# ── Regime ablation configs ─────────────────────────────────────────
ABLATION_CONFIGS: dict[str, dict[str, Any]] = {
    "baseline": {
        "regime_version": "v2",
        "mtf_enabled": False,
        "bbw_enabled": False,
        "volume_filter_enabled": False,
        "_regime_bypass": True,
    },
    "v2_full": {
        "regime_version": "v2",
        "mtf_enabled": True,
        "bbw_enabled": True,
        "volume_filter_enabled": True,
        "_regime_bypass": False,
    },
    "v2_no_mtf": {
        "regime_version": "v2",
        "mtf_enabled": False,
        "bbw_enabled": True,
        "volume_filter_enabled": True,
        "_regime_bypass": False,
    },
    "v2_no_bbw": {
        "regime_version": "v2",
        "mtf_enabled": True,
        "bbw_enabled": False,
        "volume_filter_enabled": True,
        "_regime_bypass": False,
    },
    "v2_no_vol": {
        "regime_version": "v2",
        "mtf_enabled": True,
        "bbw_enabled": True,
        "volume_filter_enabled": False,
        "_regime_bypass": False,
    },
    "regime_only": {
        "regime_version": "v2",
        "mtf_enabled": False,
        "bbw_enabled": False,
        "volume_filter_enabled": False,
        "_regime_bypass": False,
    },
}


def _load_allocation() -> dict:
    """Load production allocation.json."""
    path = PROJECT_ROOT / "config" / "strategies" / "allocation.json"
    with open(path) as f:
        return json.load(f)


def _fix_model_path(path_str: str) -> str:
    """Fix model path with directory name + filename fallbacks.

    Handles two common mismatches:
    1. model_final.pt → model_best.pt (file renamed during training)
    2. btc_bwin5_fwin2 → btc_v2_bwin5_fwin2 (dir has _v2 prefix)
    """
    p = PROJECT_ROOT / path_str
    if p.exists():
        return path_str

    # Build candidate paths: (directory, filename) combinations
    candidates = []

    # Original dir + model_best.pt
    if p.name == "model_final.pt":
        candidates.append(p.with_name("model_best.pt"))

    # Try _v2 directory variant: e.g. btc_bwin5 → btc_v2_bwin5
    dir_name = p.parent.name
    import re
    m = re.match(r"^([a-z]+)_(bwin|tree)", dir_name)
    if m:
        v2_dir_name = f"{m.group(1)}_v2_{dir_name[len(m.group(1)) + 1:]}"
        v2_dir = p.parent.parent / v2_dir_name
        candidates.append(v2_dir / p.name)
        if p.name == "model_final.pt":
            candidates.append(v2_dir / "model_best.pt")

    for candidate in candidates:
        if candidate.exists():
            return str(candidate.relative_to(PROJECT_ROOT))

    return path_str


def _fix_model_paths_in_config(config: dict) -> dict:
    """Recursively fix all model_path references in config."""
    config = copy.deepcopy(config)

    # Fix top-level model_path
    if "model_path" in config:
        config["model_path"] = _fix_model_path(config["model_path"])

    # Fix ensemble_models
    for models_key in ("ensemble_models",):
        if models_key in config:
            for m in config[models_key]:
                if "model_path" in m:
                    m["model_path"] = _fix_model_path(m["model_path"])

    # Fix entry/exit params
    for section in ("entry", "exit"):
        if section in config and "params" in config[section]:
            params = config[section]["params"]
            if "model_path" in params:
                params["model_path"] = _fix_model_path(params["model_path"])
            if "ensemble_models" in params:
                for m in params["ensemble_models"]:
                    if "model_path" in m:
                        m["model_path"] = _fix_model_path(m["model_path"])

    return config


def _get_mlp_config(asset: str, alloc: dict) -> dict:
    """Extract MLP direction config for the given asset from allocation."""
    key = f"mlp_direction_{asset.lower()}"
    strategies = alloc.get("strategies", alloc)
    cfg = strategies.get(key, {})
    if not cfg:
        # Try without prefix
        for k, v in strategies.items():
            if "mlp_direction" in k and asset.upper() in str(v.get("symbols", [])):
                cfg = v
                break
    cfg = copy.deepcopy(cfg)
    return _fix_model_paths_in_config(cfg)


def _apply_ablation_config(
    base_config: dict, ablation: dict, strategy_type: str
) -> dict:
    """Merge ablation overrides into strategy config."""
    config = copy.deepcopy(base_config)

    # Apply regime filter flags
    config["regime_version"] = ablation["regime_version"]
    config["mtf_enabled"] = ablation["mtf_enabled"]
    config["bbw_enabled"] = ablation["bbw_enabled"]
    config["volume_filter_enabled"] = ablation["volume_filter_enabled"]

    # Apply regime_bypass to entry params
    regime_bypass = ablation.get("_regime_bypass", False)
    if "entry" in config and "params" in config["entry"]:
        config["entry"]["params"]["regime_bypass"] = regime_bypass
    if strategy_type in ("short", "sideways"):
        # For legacy strategies, also set at top level
        config["regime_bypass"] = regime_bypass

    return config


def run_mlp_backtest(
    asset: str,
    config: dict,
    start_date: str,
    end_date: str,
    capital: float,
) -> dict[str, Any]:
    """Run MLP Direction backtest for a single asset+config."""
    db_path = str(PROJECT_ROOT / ASSET_DB[asset])

    # Load data with warmup
    warmup_start = str(pd.Timestamp(start_date) - pd.DateOffset(months=3))
    df = load_data(db_path, "minute240", warmup_start, end_date, exchange="binance")
    if df.empty:
        return {"return_pct": 0, "mdd": 0, "sharpe": 0, "trades": 0, "win_rate": 0, "pf": 0}

    mlp_bt = MLPDirectionBacktester(
        symbol=asset,
        config=config,
        strategy_label="mlp_direction",
    )
    df = mlp_bt.prepare_data(df)

    factory = StrategyFactory(redis=None)
    adapter = ComponentStrategyAdapter(
        factory=factory,
        strategy_name="mlp_direction",
        config=config,
    )
    adapter.symbol = asset
    adapter.precompute_mlp_predictions(df)

    # Trim warmup
    if "timestamp" in df.columns:
        start_ts = pd.Timestamp(start_date)
        mask = pd.to_datetime(df["timestamp"]) >= start_ts
        eval_start = mask.idxmax() if mask.any() else 0
        if eval_start > 0:
            if adapter._mlp_cache:
                remapped = {}
                for old_idx, val in adapter._mlp_cache.items():
                    new_idx = old_idx - eval_start
                    if new_idx >= 0:
                        remapped[new_idx] = val
                adapter._mlp_cache = remapped
            df = df.iloc[eval_start:].reset_index(drop=True)

    bt = Backtester(initial_capital=capital, fee_rate=0.001, slippage=0.0002)
    results = bt.run(df, adapter, {})
    metrics = compute_metrics(results.get("equity_curve"), timeframe="minute240")
    trade_stats = compute_trade_stats(results)

    return {
        "return_pct": round(metrics.get("total_return", 0), 2),
        "mdd": round(metrics.get("mdd", 0), 2),
        "sharpe": round(metrics.get("sharpe", 0), 2),
        "trades": trade_stats.get("total_trades", 0),
        "win_rate": round(trade_stats.get("win_rate", 0) * 100, 1),
        "pf": round(trade_stats.get("profit_factor", 0), 2),
    }


def run_component_backtest(
    asset: str,
    strategy_name: str,
    config: dict,
    start_date: str,
    end_date: str,
    capital: float,
) -> dict[str, Any]:
    """Run Short or Sideways component backtest."""
    from trading.indicators import add_all_indicators

    db_path = str(PROJECT_ROOT / ASSET_DB[asset])
    df = load_data(db_path, "minute240", start_date, end_date, exchange="binance")
    if df.empty:
        return {"return_pct": 0, "mdd": 0, "sharpe": 0, "trades": 0, "win_rate": 0, "pf": 0}

    df = add_all_indicators(df)

    factory = StrategyFactory(redis=None)
    adapter = ComponentStrategyAdapter(
        factory=factory,
        strategy_name=strategy_name,
        config=config,
    )
    adapter.symbol = asset

    # Short uses margin backtester, but ComponentStrategyAdapter works with Backtester
    fee_rate = 0.0005 if strategy_name == "short_v1" else 0.001
    leverage = 3 if strategy_name == "short_v1" else 1

    bt = Backtester(
        initial_capital=capital,
        fee_rate=fee_rate,
        slippage=0.0002,
    )
    results = bt.run(df, adapter, {})
    metrics = compute_metrics(results.get("equity_curve"), timeframe="minute240")
    trade_stats = compute_trade_stats(results)

    return {
        "return_pct": round(metrics.get("total_return", 0), 2),
        "mdd": round(metrics.get("mdd", 0), 2),
        "sharpe": round(metrics.get("sharpe", 0), 2),
        "trades": trade_stats.get("total_trades", 0),
        "win_rate": round(trade_stats.get("win_rate", 0) * 100, 1),
        "pf": round(trade_stats.get("profit_factor", 0), 2),
    }


def _default_short_config() -> dict:
    """Default Short V1 config for ablation."""
    return {
        "regime_version": "v2",
        "position_pct": 0.3,
        "position_size": 0.01,
        "market": "futures",
        "bbw_block_threshold": 25,
        "bbw_confirm_threshold": 50,
        "volume_block_ratio": 0.8,
        "volume_boost_ratio": 1.2,
        "mtf_enabled": True,
        "bbw_enabled": True,
        "volume_filter_enabled": True,
        "drawdown_bear_threshold": 1.0,
        "stop_loss_cooldown": 0,
    }


def _default_sideways_config() -> dict:
    """Default Sideways V2 config for ablation."""
    return {
        "regime_version": "v2",
        "position_pct": 0.3,
        "position_size": 0.01,
        "market": "futures",
        "bbw_block_threshold": 25,
        "bbw_confirm_threshold": 50,
        "volume_block_ratio": 0.8,
        "volume_boost_ratio": 1.2,
        "mtf_enabled": True,
        "bbw_enabled": True,
        "volume_filter_enabled": True,
        "drawdown_bear_threshold": 1.0,
        "stop_loss_cooldown": 0,
    }


def run_ablation(
    assets: list[str],
    strategies: list[str],
    start_date: str,
    end_date: str,
    capital: float,
    configs: list[str] | None = None,
) -> pd.DataFrame:
    """Run full ablation study.

    Returns DataFrame with columns:
        config, strategy, asset, return_pct, mdd, sharpe, trades, win_rate, pf
    """
    alloc = _load_allocation()
    config_names = configs or list(ABLATION_CONFIGS.keys())
    rows = []

    total = len(config_names) * len(strategies) * len(assets)
    done = 0

    for config_name in config_names:
        ablation = ABLATION_CONFIGS[config_name]

        for strategy_type in strategies:
            for asset in assets:
                done += 1
                label = f"[{done}/{total}] {config_name} / {strategy_type} / {asset}"
                print(f"  {label} ...", end=" ", flush=True)
                t0 = time.time()

                try:
                    if strategy_type == "mlp":
                        base_config = _get_mlp_config(asset, alloc)
                        if not base_config:
                            print("SKIP (no config)")
                            continue
                        merged = _apply_ablation_config(base_config, ablation, strategy_type)
                        result = run_mlp_backtest(asset, merged, start_date, end_date, capital)

                    elif strategy_type == "short":
                        base_config = _default_short_config()
                        merged = _apply_ablation_config(base_config, ablation, strategy_type)
                        result = run_component_backtest(
                            asset, "short_v1", merged, start_date, end_date, capital
                        )

                    elif strategy_type == "sideways":
                        base_config = _default_sideways_config()
                        merged = _apply_ablation_config(base_config, ablation, strategy_type)
                        result = run_component_backtest(
                            asset, "sideways_v2", merged, start_date, end_date, capital
                        )
                    else:
                        print(f"SKIP (unknown strategy: {strategy_type})")
                        continue

                    elapsed = time.time() - t0
                    print(f"ret={result['return_pct']:+.1f}% trades={result['trades']} ({elapsed:.1f}s)")

                    rows.append({
                        "config": config_name,
                        "strategy": strategy_type,
                        "asset": asset,
                        **result,
                    })

                except Exception as e:
                    elapsed = time.time() - t0
                    print(f"ERROR: {e} ({elapsed:.1f}s)")
                    rows.append({
                        "config": config_name,
                        "strategy": strategy_type,
                        "asset": asset,
                        "return_pct": 0, "mdd": 0, "sharpe": 0,
                        "trades": 0, "win_rate": 0, "pf": 0,
                    })

    return pd.DataFrame(rows)


def print_comparison_table(df: pd.DataFrame) -> None:
    """Print formatted comparison table grouped by strategy."""
    if df.empty:
        print("No results.")
        return

    for strategy in df["strategy"].unique():
        sdf = df[df["strategy"] == strategy]
        print(f"\n{'='*80}")
        print(f"  STRATEGY: {strategy.upper()}")
        print(f"{'='*80}")

        # Pivot: rows=config, columns=asset, values=return_pct
        assets = sorted(sdf["asset"].unique())
        configs = list(ABLATION_CONFIGS.keys())

        # Header
        header = f"{'Config':<14}"
        for asset in assets:
            header += f" | {'Ret%':>7} {'MDD%':>7} {'Shrp':>5} {'Trd':>4} {'WR%':>5} {'PF':>5}"
        print(f"\n{' ':<14}", end="")
        for asset in assets:
            print(f" | {asset:^40}", end="")
        print()
        print(f"{'Config':<14}", end="")
        for _ in assets:
            print(f" | {'Ret%':>7} {'MDD%':>7} {'Shrp':>5} {'Trd':>4} {'WR%':>5} {'PF':>5}", end="")
        print()
        print("-" * (14 + len(assets) * 43))

        # Data rows
        for config in configs:
            if config not in sdf["config"].values:
                continue
            row_str = f"{config:<14}"
            for asset in assets:
                r = sdf[(sdf["config"] == config) & (sdf["asset"] == asset)]
                if r.empty:
                    row_str += f" | {'--':>7} {'--':>7} {'--':>5} {'--':>4} {'--':>5} {'--':>5}"
                else:
                    r = r.iloc[0]
                    row_str += (
                        f" | {r['return_pct']:>+7.1f} {r['mdd']:>7.1f} "
                        f"{r['sharpe']:>5.2f} {r['trades']:>4d} "
                        f"{r['win_rate']:>5.1f} {r['pf']:>5.2f}"
                    )
            print(row_str)

        # Summary: average across assets
        print("-" * (14 + len(assets) * 43))
        print(f"\n  Average across assets:")
        print(f"  {'Config':<14} {'Ret%':>8} {'MDD%':>8} {'Sharpe':>8} {'Trades':>8}")
        print(f"  {'-'*50}")
        for config in configs:
            cdf = sdf[sdf["config"] == config]
            if cdf.empty:
                continue
            avg_ret = cdf["return_pct"].mean()
            avg_mdd = cdf["mdd"].mean()
            avg_sharpe = cdf["sharpe"].mean()
            avg_trades = cdf["trades"].mean()
            print(f"  {config:<14} {avg_ret:>+8.1f} {avg_mdd:>8.1f} {avg_sharpe:>8.2f} {avg_trades:>8.0f}")


def main():
    parser = argparse.ArgumentParser(description="Regime Ablation Study")
    parser.add_argument(
        "--assets", nargs="+", default=["BTC", "ETH", "SOL"],
        help="Assets to test (default: BTC ETH SOL)",
    )
    parser.add_argument(
        "--strategies", nargs="+", default=["mlp", "short", "sideways"],
        help="Strategy types (default: mlp short sideways)",
    )
    parser.add_argument("--start-date", default="2020-01-01")
    parser.add_argument("--end-date", default="2026-02-01")
    parser.add_argument("--capital", type=float, default=10_000)
    parser.add_argument(
        "--configs", nargs="+", default=None,
        help="Specific configs to test (default: all 6)",
    )
    parser.add_argument(
        "--csv", default=None,
        help="Export results to CSV file",
    )
    args = parser.parse_args()

    print("=" * 60)
    print("  REGIME ABLATION STUDY")
    print("=" * 60)
    print(f"  Assets:     {', '.join(args.assets)}")
    print(f"  Strategies: {', '.join(args.strategies)}")
    print(f"  Period:     {args.start_date} → {args.end_date}")
    print(f"  Capital:    ${args.capital:,.0f}")
    print(f"  Configs:    {', '.join(args.configs or list(ABLATION_CONFIGS.keys()))}")
    print("=" * 60)
    print()

    t0 = time.time()
    results_df = run_ablation(
        assets=[a.upper() for a in args.assets],
        strategies=args.strategies,
        start_date=args.start_date,
        end_date=args.end_date,
        capital=args.capital,
        configs=args.configs,
    )
    elapsed = time.time() - t0

    print_comparison_table(results_df)

    if args.csv:
        results_df.to_csv(args.csv, index=False)
        print(f"\nResults exported to {args.csv}")

    print(f"\nTotal time: {elapsed:.0f}s")


if __name__ == "__main__":
    main()
