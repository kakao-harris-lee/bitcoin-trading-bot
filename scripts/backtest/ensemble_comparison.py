#!/usr/bin/env python3
"""
Ensemble A/B Comparison Backtest.

Compares single-model MLP Direction strategy vs temporal ensemble
(soft-voting across bwin=3/1, bwin=4/2, bwin=5/2, bwin=7/3 models).

Usage:
    python scripts/backtest/ensemble_comparison.py
    python scripts/backtest/ensemble_comparison.py --assets BTC ETH SOL
    python scripts/backtest/ensemble_comparison.py --by-year
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.backtest._common import (
    load_data,
    compute_metrics,
    print_yearly_table,
)
from scripts.backtest.backtest_mlp import (
    MLPDirectionBacktester,
    load_strategy_config,
)
from core.backtester import Backtester
from core.component_adapter import ComponentStrategyAdapter
from trading.strategies.components.strategy_factory import StrategyFactory

# Asset database paths
ASSET_DB = {
    "BTC": ("data/binance_bitcoin.db", "BTC"),
    "ETH": ("data/binance_ethereum.db", "ETH"),
    "SOL": ("data/binance_solana.db", "SOL"),
    "XRP": ("data/binance_xrp.db", "XRP"),
}

MLP_STRATEGY_IDS = {
    "BTC": "mlp_direction_btc",
    "ETH": "mlp_direction_eth",
    "SOL": "mlp_direction_sol",
    "XRP": "mlp_direction_xrp",
}

# Ensemble model configurations per asset
# All assets use the same set of multi-asset models
ENSEMBLE_CONFIGS = [
    {"model_path": "models/mlp_direction/multi_bwin3_fwin1/model_final.pt", "weight": 0.15},
    {"model_path": "models/mlp_direction/eth_bwin4_fwin2/model_final.pt", "weight": 0.30},
    {"model_path": "models/mlp_direction/btc_bwin5_fwin2/model_final.pt", "weight": 0.35},
    {"model_path": "models/mlp_direction/multi_bwin7_fwin3/model_final.pt", "weight": 0.20},
]

# MTF ensemble (paper_mtf_44 feature set)
MTF_ENSEMBLE_CONFIGS = [
    {"model_path": "models/mlp_direction/mtf_bwin3_fwin1/model_final.pt", "weight": 0.15},
    {"model_path": "models/mlp_direction/mtf_bwin4_fwin2/model_final.pt", "weight": 0.30},
    {"model_path": "models/mlp_direction/mtf_bwin5_fwin2/model_final.pt", "weight": 0.35},
    {"model_path": "models/mlp_direction/mtf_bwin7_fwin3/model_final.pt", "weight": 0.20},
]

# Mixed ensemble: MLP + XGBoost + LightGBM (heterogeneous architecture, paper_36 features)
MIXED_ENSEMBLE_CONFIGS = [
    {"model_path": "models/mlp_direction/multi_bwin3_fwin1/model_final.pt", "weight": 0.10},
    {"model_path": "models/mlp_direction/eth_bwin4_fwin2/model_final.pt", "weight": 0.15},
    {"model_path": "models/mlp_direction/btc_bwin5_fwin2/model_final.pt", "weight": 0.20},
    {"model_path": "models/mlp_direction/multi_bwin7_fwin3/model_final.pt", "weight": 0.10},
    {"model_path": "models/mlp_direction/xgb_bwin3_fwin1/model.json", "weight": 0.20},
    {"model_path": "models/mlp_direction/lgb_bwin7_fwin3/model.txt", "weight": 0.25},
]

# Tree-only ensemble: XGBoost + LightGBM with tree_60 features
TREE60_ENSEMBLE_CONFIGS = [
    {"model_path": "models/mlp_direction/xgb_tree60_bwin3_fwin1/model.json", "weight": 0.50},
    {"model_path": "models/mlp_direction/lgb_tree60_bwin7_fwin3/model.txt", "weight": 0.50},
]


def run_single_asset(
    asset: str,
    config_path: str,
    capital: float,
    start_date: str,
    end_date: str,
    ensemble_models: list[dict] | None = None,
    feature_set: str | None = None,
    exit_overrides: dict | None = None,
) -> dict[str, Any]:
    """Run MLP Direction backtest for a single asset.

    Args:
        ensemble_models: If provided, use ensemble prediction instead of single model.
        feature_set: Override feature set (e.g. 'paper_mtf_44').
        exit_overrides: Override exit strategy params (e.g. fwin_exit_enabled).
    """
    db_file, symbol = ASSET_DB[asset]
    db_path = str(PROJECT_ROOT / db_file)

    try:
        _, strategy_id, strategy_config = load_strategy_config(
            config_path=config_path,
            symbol=asset,
            mode="paper",
            strategy_id=MLP_STRATEGY_IDS.get(asset),
        )
    except ValueError as e:
        print(f"  WARNING: {e}, skipping {asset}")
        return {}

    # Inject ensemble configuration
    if ensemble_models:
        strategy_config["ensemble_models"] = ensemble_models
        if strategy_config.get("entry", {}).get("params"):
            strategy_config["entry"]["params"]["ensemble_models"] = ensemble_models

    # Override feature set (must propagate to entry/exit params too)
    if feature_set:
        strategy_config["mlp_feature_set"] = feature_set
        if strategy_config.get("entry", {}).get("params"):
            strategy_config["entry"]["params"]["mlp_feature_set"] = feature_set
        if strategy_config.get("exit", {}).get("params"):
            strategy_config["exit"]["params"]["mlp_feature_set"] = feature_set

    # Override exit strategy params
    if exit_overrides:
        exit_params = strategy_config.get("exit", {}).get("params", {})
        exit_params.update(exit_overrides)
        if "exit" not in strategy_config:
            strategy_config["exit"] = {}
        if "params" not in strategy_config["exit"]:
            strategy_config["exit"]["params"] = {}
        strategy_config["exit"]["params"].update(exit_overrides)

    model_path = Path(strategy_config.get("model_path", ""))
    if not ensemble_models and not model_path.exists():
        print(f"  WARNING: Model not found at {model_path}, skipping {asset}")
        return {}

    # Load data — for MTF features, add 200-day warmup before start_date
    # (weekly EMA20 needs ~140 days to stabilize)
    if feature_set == "paper_mtf_44":
        from datetime import datetime as _dt, timedelta
        warmup_start = (_dt.strptime(start_date, "%Y-%m-%d") - timedelta(days=200)).strftime("%Y-%m-%d")
    else:
        warmup_start = start_date
    df = load_data(db_path, "minute240", warmup_start, end_date, exchange="binance")
    if df.empty:
        print(f"  WARNING: No data for {asset}")
        return {}

    mlp_bt = MLPDirectionBacktester(
        symbol=asset,
        config=strategy_config,
        strategy_label=strategy_id,
    )
    df = mlp_bt.prepare_data(df)

    # Create adapter and precompute predictions (including warmup data)
    factory = StrategyFactory(redis=None)
    adapter = ComponentStrategyAdapter(
        factory=factory,
        strategy_name="mlp_direction",
        config=strategy_config,
    )
    adapter.symbol = asset
    adapter.precompute_mlp_predictions(df)

    # Trim warmup rows and remap cache indices so backtest evaluates only from start_date
    if warmup_start != start_date and "timestamp" in df.columns:
        start_ts = pd.Timestamp(start_date)
        mask = pd.to_datetime(df["timestamp"]) >= start_ts
        eval_start = mask.idxmax() if mask.any() else 0
        if eval_start > 0:
            # Remap precomputed cache indices
            if adapter._mlp_cache:
                remapped = {}
                for old_idx, val in adapter._mlp_cache.items():
                    new_idx = old_idx - eval_start
                    if new_idx >= 0:
                        remapped[new_idx] = val
                adapter._mlp_cache = remapped
            df = df.iloc[eval_start:].reset_index(drop=True)

    # Run backtest
    bt = Backtester(
        initial_capital=capital,
        fee_rate=0.001,
        slippage=0.0002,
    )
    results = bt.run(df, adapter, {})
    metrics = compute_metrics(results.get("equity_curve"), timeframe="minute240")
    metrics["num_trades"] = len(bt.trades)

    return {
        "results": results,
        "metrics": metrics,
        "equity_curve": results.get("equity_curve"),
        "config": strategy_config,
    }


def run_comparison(
    assets: list[str],
    config_path: str,
    capital_per_asset: float,
    start_date: str,
    end_date: str,
    by_year: bool = False,
    weights: list[float] | None = None,
) -> None:
    """Run A/B comparison: single model vs ensemble."""
    # Prepare ensemble configs with optional weight override
    ensemble_configs = []
    for i, cfg in enumerate(ENSEMBLE_CONFIGS):
        entry = dict(cfg)
        if weights and i < len(weights):
            entry["weight"] = weights[i]
        ensemble_configs.append(entry)

    single_results = {}
    ensemble_results = {}

    for asset in assets:
        print(f"\n{'='*60}")
        print(f"  {asset}: Running single model (baseline)...")
        print(f"{'='*60}")
        single_results[asset] = run_single_asset(
            asset, config_path, capital_per_asset, start_date, end_date,
            ensemble_models=None,
        )

        print(f"\n  {asset}: Running ensemble (4 models)...")
        ensemble_results[asset] = run_single_asset(
            asset, config_path, capital_per_asset, start_date, end_date,
            ensemble_models=ensemble_configs,
        )

    # Print comparison table
    print("\n")
    print("=" * 85)
    print("  ENSEMBLE COMPARISON: Single Model vs Temporal Ensemble")
    print("=" * 85)

    # Show ensemble weights
    print(f"\n  Ensemble: ", end="")
    for cfg in ensemble_configs:
        name = Path(cfg["model_path"]).parent.name
        print(f"{name}(w={cfg['weight']:.1f}) ", end="")
    print("\n")

    header = f"{'Asset':<8} {'Metric':<14} {'Single':>12} {'Ensemble':>12} {'Delta':>10}"
    print(header)
    print("-" * 85)

    portfolio_single_return = 0.0
    portfolio_ensemble_return = 0.0

    for asset in assets:
        s = single_results.get(asset, {}).get("metrics", {})
        e = ensemble_results.get(asset, {}).get("metrics", {})

        if not s or not e:
            print(f"{asset:<8} {'SKIPPED':<14}")
            continue

        for metric, label, fmt in [
            ("total_return", "Return", "{:+.1f}%"),
            ("mdd", "MDD", "{:.1f}%"),
            ("sharpe", "Sharpe", "{:.2f}"),
        ]:
            s_val = s.get(metric, 0)
            e_val = e.get(metric, 0)
            delta = e_val - s_val

            s_str = fmt.format(s_val)
            e_str = fmt.format(e_val)
            delta_str = fmt.format(delta)

            print(f"{asset if metric == 'total_return' else '':<8} {label:<14} {s_str:>12} {e_str:>12} {delta_str:>10}")

        # Calmar ratio
        s_calmar = abs(s.get("total_return", 0) / s.get("mdd", -1)) if s.get("mdd", 0) != 0 else 0
        e_calmar = abs(e.get("total_return", 0) / e.get("mdd", -1)) if e.get("mdd", 0) != 0 else 0
        delta_calmar = e_calmar - s_calmar
        print(f"{'':8} {'Calmar':<14} {s_calmar:>11.2f}x {e_calmar:>11.2f}x {delta_calmar:>+9.2f}x")

        # Trade count
        s_trades = s.get("num_trades", 0)
        e_trades = e.get("num_trades", 0)
        print(f"{'':8} {'Trades':<14} {s_trades:>12} {e_trades:>12} {e_trades - s_trades:>+10}")
        print()

        portfolio_single_return += s.get("total_return", 0)
        portfolio_ensemble_return += e.get("total_return", 0)

    # Portfolio summary
    n = len([a for a in assets if single_results.get(a, {}).get("metrics")])
    if n > 0:
        print("-" * 85)
        avg_s = portfolio_single_return / n
        avg_e = portfolio_ensemble_return / n
        print(f"{'PORTFOLIO':<8} {'Avg Return':<14} {avg_s:>+11.1f}% {avg_e:>+11.1f}% {avg_e-avg_s:>+9.1f}%")

    # Per-year breakdown
    if by_year:
        for asset in assets:
            for label, results in [("Single", single_results), ("Ensemble", ensemble_results)]:
                eq = results.get(asset, {}).get("equity_curve")
                if eq is not None and not eq.empty:
                    print(f"\n--- {asset} {label} Per-Year ---")
                    print_yearly_table(eq)


def run_mtf_comparison(
    assets: list[str],
    config_path: str,
    capital_per_asset: float,
    start_date: str,
    end_date: str,
    by_year: bool = False,
) -> None:
    """Run A/B comparison: paper_36 ensemble vs paper_mtf_44 ensemble."""
    baseline_results = {}
    mtf_results = {}

    for asset in assets:
        print(f"\n{'='*60}")
        print(f"  {asset}: Running paper_36 ensemble (baseline)...")
        print(f"{'='*60}")
        baseline_results[asset] = run_single_asset(
            asset, config_path, capital_per_asset, start_date, end_date,
            ensemble_models=list(ENSEMBLE_CONFIGS),
        )

        print(f"\n  {asset}: Running paper_mtf_44 ensemble...")
        mtf_results[asset] = run_single_asset(
            asset, config_path, capital_per_asset, start_date, end_date,
            ensemble_models=list(MTF_ENSEMBLE_CONFIGS),
            feature_set="paper_mtf_44",
        )

    # Print comparison table
    print("\n")
    print("=" * 85)
    print("  MTF COMPARISON: paper_36 Ensemble vs paper_mtf_44 Ensemble")
    print("=" * 85)

    print(f"\n  Baseline (paper_36): ", end="")
    for cfg in ENSEMBLE_CONFIGS:
        name = Path(cfg["model_path"]).parent.name
        print(f"{name}(w={cfg['weight']:.2f}) ", end="")
    print()
    print(f"  MTF (paper_mtf_44): ", end="")
    for cfg in MTF_ENSEMBLE_CONFIGS:
        name = Path(cfg["model_path"]).parent.name
        print(f"{name}(w={cfg['weight']:.2f}) ", end="")
    print("\n")

    header = f"{'Asset':<8} {'Metric':<14} {'paper_36':>12} {'mtf_44':>12} {'Delta':>10}"
    print(header)
    print("-" * 85)

    portfolio_bl_return = 0.0
    portfolio_mtf_return = 0.0

    for asset in assets:
        bl = baseline_results.get(asset, {}).get("metrics", {})
        mt = mtf_results.get(asset, {}).get("metrics", {})

        if not bl or not mt:
            print(f"{asset:<8} {'SKIPPED':<14}")
            continue

        for metric, label, fmt in [
            ("total_return", "Return", "{:+.1f}%"),
            ("mdd", "MDD", "{:.1f}%"),
            ("sharpe", "Sharpe", "{:.2f}"),
        ]:
            bl_val = bl.get(metric, 0)
            mt_val = mt.get(metric, 0)
            delta = mt_val - bl_val

            bl_str = fmt.format(bl_val)
            mt_str = fmt.format(mt_val)
            delta_str = fmt.format(delta)

            print(f"{asset if metric == 'total_return' else '':<8} {label:<14} {bl_str:>12} {mt_str:>12} {delta_str:>10}")

        # Calmar ratio
        bl_calmar = abs(bl.get("total_return", 0) / bl.get("mdd", -1)) if bl.get("mdd", 0) != 0 else 0
        mt_calmar = abs(mt.get("total_return", 0) / mt.get("mdd", -1)) if mt.get("mdd", 0) != 0 else 0
        delta_calmar = mt_calmar - bl_calmar
        print(f"{'':8} {'Calmar':<14} {bl_calmar:>11.2f}x {mt_calmar:>11.2f}x {delta_calmar:>+9.2f}x")

        # Trade count
        bl_trades = bl.get("num_trades", 0)
        mt_trades = mt.get("num_trades", 0)
        print(f"{'':8} {'Trades':<14} {bl_trades:>12} {mt_trades:>12} {mt_trades - bl_trades:>+10}")
        print()

        portfolio_bl_return += bl.get("total_return", 0)
        portfolio_mtf_return += mt.get("total_return", 0)

    # Portfolio summary
    n = len([a for a in assets if baseline_results.get(a, {}).get("metrics")])
    if n > 0:
        print("-" * 85)
        avg_bl = portfolio_bl_return / n
        avg_mt = portfolio_mtf_return / n
        print(f"{'PORTFOLIO':<8} {'Avg Return':<14} {avg_bl:>+11.1f}% {avg_mt:>+11.1f}% {avg_mt-avg_bl:>+9.1f}%")

    # Per-year breakdown
    if by_year:
        for asset in assets:
            for label, results in [("paper_36", baseline_results), ("mtf_44", mtf_results)]:
                eq = results.get(asset, {}).get("equity_curve")
                if eq is not None and not eq.empty:
                    print(f"\n--- {asset} {label} Per-Year ---")
                    print_yearly_table(eq)


def run_mixed_comparison(
    assets: list[str],
    config_path: str,
    capital_per_asset: float,
    start_date: str,
    end_date: str,
    by_year: bool = False,
) -> None:
    """Run A/B comparison: MLP-only ensemble vs Mixed (MLP+Tree) ensemble."""
    mlp_results = {}
    mixed_results = {}

    for asset in assets:
        print(f"\n{'='*60}")
        print(f"  {asset}: Running MLP-only ensemble (baseline)...")
        print(f"{'='*60}")
        mlp_results[asset] = run_single_asset(
            asset, config_path, capital_per_asset, start_date, end_date,
            ensemble_models=list(ENSEMBLE_CONFIGS),
        )

        print(f"\n  {asset}: Running Mixed ensemble (MLP+XGBoost+LightGBM)...")
        mixed_results[asset] = run_single_asset(
            asset, config_path, capital_per_asset, start_date, end_date,
            ensemble_models=list(MIXED_ENSEMBLE_CONFIGS),
        )

    # Print comparison table
    print("\n")
    print("=" * 85)
    print("  MIXED ENSEMBLE: MLP-only vs MLP+XGBoost+LightGBM")
    print("=" * 85)

    print(f"\n  MLP-only ({len(ENSEMBLE_CONFIGS)} models): ", end="")
    for cfg in ENSEMBLE_CONFIGS:
        name = Path(cfg["model_path"]).parent.name
        print(f"{name}(w={cfg['weight']:.2f}) ", end="")
    print()
    print(f"  Mixed ({len(MIXED_ENSEMBLE_CONFIGS)} models): ", end="")
    for cfg in MIXED_ENSEMBLE_CONFIGS:
        name = Path(cfg["model_path"]).parent.name
        ext = Path(cfg["model_path"]).suffix
        tag = {".json": "[XGB]", ".txt": "[LGB]"}.get(ext, "[MLP]")
        print(f"{name}{tag}(w={cfg['weight']:.2f}) ", end="")
    print("\n")

    header = f"{'Asset':<8} {'Metric':<14} {'MLP-only':>12} {'Mixed':>12} {'Delta':>10}"
    print(header)
    print("-" * 85)

    portfolio_mlp_return = 0.0
    portfolio_mixed_return = 0.0

    for asset in assets:
        m = mlp_results.get(asset, {}).get("metrics", {})
        x = mixed_results.get(asset, {}).get("metrics", {})

        if not m or not x:
            print(f"{asset:<8} {'SKIPPED':<14}")
            continue

        for metric, label, fmt in [
            ("total_return", "Return", "{:+.1f}%"),
            ("mdd", "MDD", "{:.1f}%"),
            ("sharpe", "Sharpe", "{:.2f}"),
        ]:
            m_val = m.get(metric, 0)
            x_val = x.get(metric, 0)
            delta = x_val - m_val

            m_str = fmt.format(m_val)
            x_str = fmt.format(x_val)
            delta_str = fmt.format(delta)

            print(f"{asset if metric == 'total_return' else '':<8} {label:<14} {m_str:>12} {x_str:>12} {delta_str:>10}")

        # Calmar ratio
        m_calmar = abs(m.get("total_return", 0) / m.get("mdd", -1)) if m.get("mdd", 0) != 0 else 0
        x_calmar = abs(x.get("total_return", 0) / x.get("mdd", -1)) if x.get("mdd", 0) != 0 else 0
        delta_calmar = x_calmar - m_calmar
        print(f"{'':8} {'Calmar':<14} {m_calmar:>11.2f}x {x_calmar:>11.2f}x {delta_calmar:>+9.2f}x")

        # Trade count
        m_trades = m.get("num_trades", 0)
        x_trades = x.get("num_trades", 0)
        print(f"{'':8} {'Trades':<14} {m_trades:>12} {x_trades:>12} {x_trades - m_trades:>+10}")
        print()

        portfolio_mlp_return += m.get("total_return", 0)
        portfolio_mixed_return += x.get("total_return", 0)

    # Portfolio summary
    n = len([a for a in assets if mlp_results.get(a, {}).get("metrics")])
    if n > 0:
        print("-" * 85)
        avg_m = portfolio_mlp_return / n
        avg_x = portfolio_mixed_return / n
        print(f"{'PORTFOLIO':<8} {'Avg Return':<14} {avg_m:>+11.1f}% {avg_x:>+11.1f}% {avg_x-avg_m:>+9.1f}%")

    # Per-year breakdown
    if by_year:
        for asset in assets:
            for label, results in [("MLP-only", mlp_results), ("Mixed", mixed_results)]:
                eq = results.get(asset, {}).get("equity_curve")
                if eq is not None and not eq.empty:
                    print(f"\n--- {asset} {label} Per-Year ---")
                    print_yearly_table(eq)


def run_tree60_comparison(
    assets: list[str],
    config_path: str,
    capital_per_asset: float,
    start_date: str,
    end_date: str,
    by_year: bool = False,
) -> None:
    """Run A/B comparison: MLP paper_36 ensemble vs Tree tree_60 ensemble."""
    mlp_results = {}
    tree_results = {}

    for asset in assets:
        print(f"\n{'='*60}")
        print(f"  {asset}: Running MLP ensemble (paper_36 baseline)...")
        print(f"{'='*60}")
        mlp_results[asset] = run_single_asset(
            asset, config_path, capital_per_asset, start_date, end_date,
            ensemble_models=list(ENSEMBLE_CONFIGS),
        )

        print(f"\n  {asset}: Running Tree ensemble (tree_60 features)...")
        tree_results[asset] = run_single_asset(
            asset, config_path, capital_per_asset, start_date, end_date,
            ensemble_models=list(TREE60_ENSEMBLE_CONFIGS),
            feature_set="tree_60",
        )

    # Print comparison table
    print("\n")
    print("=" * 85)
    print("  TREE_60 COMPARISON: MLP paper_36 vs Tree tree_60")
    print("=" * 85)

    print(f"\n  MLP paper_36 ({len(ENSEMBLE_CONFIGS)} models): ", end="")
    for cfg in ENSEMBLE_CONFIGS:
        name = Path(cfg["model_path"]).parent.name
        print(f"{name}(w={cfg['weight']:.2f}) ", end="")
    print()
    print(f"  Tree tree_60 ({len(TREE60_ENSEMBLE_CONFIGS)} models): ", end="")
    for cfg in TREE60_ENSEMBLE_CONFIGS:
        name = Path(cfg["model_path"]).parent.name
        ext = Path(cfg["model_path"]).suffix
        tag = {".json": "[XGB]", ".txt": "[LGB]"}.get(ext, "")
        print(f"{name}{tag}(w={cfg['weight']:.2f}) ", end="")
    print("\n")

    header = f"{'Asset':<8} {'Metric':<14} {'MLP p36':>12} {'Tree t60':>12} {'Delta':>10}"
    print(header)
    print("-" * 85)

    portfolio_mlp_return = 0.0
    portfolio_tree_return = 0.0

    for asset in assets:
        m = mlp_results.get(asset, {}).get("metrics", {})
        t = tree_results.get(asset, {}).get("metrics", {})

        if not m or not t:
            print(f"{asset:<8} {'SKIPPED':<14}")
            continue

        for metric, label, fmt in [
            ("total_return", "Return", "{:+.1f}%"),
            ("mdd", "MDD", "{:.1f}%"),
            ("sharpe", "Sharpe", "{:.2f}"),
        ]:
            m_val = m.get(metric, 0)
            t_val = t.get(metric, 0)
            delta = t_val - m_val

            m_str = fmt.format(m_val)
            t_str = fmt.format(t_val)
            delta_str = fmt.format(delta)

            print(f"{asset if metric == 'total_return' else '':<8} {label:<14} {m_str:>12} {t_str:>12} {delta_str:>10}")

        # Calmar ratio
        m_calmar = abs(m.get("total_return", 0) / m.get("mdd", -1)) if m.get("mdd", 0) != 0 else 0
        t_calmar = abs(t.get("total_return", 0) / t.get("mdd", -1)) if t.get("mdd", 0) != 0 else 0
        delta_calmar = t_calmar - m_calmar
        print(f"{'':8} {'Calmar':<14} {m_calmar:>11.2f}x {t_calmar:>11.2f}x {delta_calmar:>+9.2f}x")

        # Trade count
        m_trades = m.get("num_trades", 0)
        t_trades = t.get("num_trades", 0)
        print(f"{'':8} {'Trades':<14} {m_trades:>12} {t_trades:>12} {t_trades - m_trades:>+10}")
        print()

        portfolio_mlp_return += m.get("total_return", 0)
        portfolio_tree_return += t.get("total_return", 0)

    # Portfolio summary
    n = len([a for a in assets if mlp_results.get(a, {}).get("metrics")])
    if n > 0:
        print("-" * 85)
        avg_m = portfolio_mlp_return / n
        avg_t = portfolio_tree_return / n
        print(f"{'PORTFOLIO':<8} {'Avg Return':<14} {avg_m:>+11.1f}% {avg_t:>+11.1f}% {avg_t-avg_m:>+9.1f}%")

    # Per-year breakdown
    if by_year:
        for asset in assets:
            for label, results in [("MLP paper_36", mlp_results), ("Tree tree_60", tree_results)]:
                eq = results.get(asset, {}).get("equity_curve")
                if eq is not None and not eq.empty:
                    print(f"\n--- {asset} {label} Per-Year ---")
                    print_yearly_table(eq)


def run_fwin_comparison(
    assets: list[str],
    config_path: str,
    capital_per_asset: float,
    start_date: str,
    end_date: str,
    by_year: bool = False,
) -> None:
    """Run A/B comparison: current exit (MLP SELL) vs fwin-aligned exit.

    Tests whether aligning the exit strategy with model training labels
    (forward window exit) improves performance.
    """
    current_results = {}
    fwin_results = {}

    # Aligned exit: take profit at alpha (3.8%) + tight stop loss (3%)
    # Matches model's prediction: "price rises 3.8%+ within fwin"
    aligned_overrides = {
        "take_profit_enabled": True,
        "take_profit_pct": 4.0,       # Close to alpha=3.8%
        "stop_loss_pct": 3.0,          # Tight stop matching prediction horizon
        "use_mlp_sell_exit": True,     # Keep SELL exit as backup
        "fwin_exit_enabled": True,     # Time limit exit
        "fwin_periods": 5,             # 20H max hold (reasonable for 4H bars)
    }

    for asset in assets:
        print(f"\n{'='*60}")
        print(f"  {asset}: Running current config (MLP SELL exit, 10% SL)...")
        print(f"{'='*60}")
        current_results[asset] = run_single_asset(
            asset, config_path, capital_per_asset, start_date, end_date,
            ensemble_models=list(ENSEMBLE_CONFIGS),
        )

        print(f"\n  {asset}: Running aligned exit (TP 4%, SL 3%, fwin 5)...")
        fwin_results[asset] = run_single_asset(
            asset, config_path, capital_per_asset, start_date, end_date,
            ensemble_models=list(ENSEMBLE_CONFIGS),
            exit_overrides=aligned_overrides,
        )

    # Print comparison table
    print("\n")
    print("=" * 85)
    print("  GAP 1 FIX: Label-Strategy Alignment (MLP SELL exit vs FWin exit)")
    print("=" * 85)
    print(f"\n  Current: MLP SELL exit (fwin disabled, 10% stop loss)")
    print(f"  Aligned: TP 4% + SL 3% + fwin 5 (20H max hold) + SELL exit")
    print()

    header = f"{'Asset':<8} {'Metric':<14} {'Current':>12} {'Aligned':>12} {'Delta':>10}"
    print(header)
    print("-" * 85)

    portfolio_curr_return = 0.0
    portfolio_fwin_return = 0.0

    for asset in assets:
        c = current_results.get(asset, {}).get("metrics", {})
        f = fwin_results.get(asset, {}).get("metrics", {})

        if not c or not f:
            print(f"{asset:<8} {'SKIPPED':<14}")
            continue

        for metric, label, fmt in [
            ("total_return", "Return", "{:+.1f}%"),
            ("mdd", "MDD", "{:.1f}%"),
            ("sharpe", "Sharpe", "{:.2f}"),
        ]:
            c_val = c.get(metric, 0)
            f_val = f.get(metric, 0)
            delta = f_val - c_val

            c_str = fmt.format(c_val)
            f_str = fmt.format(f_val)
            delta_str = fmt.format(delta)

            print(f"{asset if metric == 'total_return' else '':<8} {label:<14} {c_str:>12} {f_str:>12} {delta_str:>10}")

        # Calmar ratio
        c_calmar = abs(c.get("total_return", 0) / c.get("mdd", -1)) if c.get("mdd", 0) != 0 else 0
        f_calmar = abs(f.get("total_return", 0) / f.get("mdd", -1)) if f.get("mdd", 0) != 0 else 0
        print(f"{'':8} {'Calmar':<14} {c_calmar:>11.2f}x {f_calmar:>11.2f}x {f_calmar-c_calmar:>+9.2f}x")

        c_trades = c.get("num_trades", 0)
        f_trades = f.get("num_trades", 0)
        print(f"{'':8} {'Trades':<14} {c_trades:>12} {f_trades:>12} {f_trades - c_trades:>+10}")
        print()

        portfolio_curr_return += c.get("total_return", 0)
        portfolio_fwin_return += f.get("total_return", 0)

    n = len([a for a in assets if current_results.get(a, {}).get("metrics")])
    if n > 0:
        print("-" * 85)
        avg_c = portfolio_curr_return / n
        avg_f = portfolio_fwin_return / n
        print(f"{'PORTFOLIO':<8} {'Avg Return':<14} {avg_c:>+11.1f}% {avg_f:>+11.1f}% {avg_f-avg_c:>+9.1f}%")

    if by_year:
        for asset in assets:
            for label, results in [("SELL exit", current_results), ("FWin exit", fwin_results)]:
                eq = results.get(asset, {}).get("equity_curve")
                if eq is not None and not eq.empty:
                    print(f"\n--- {asset} {label} Per-Year ---")
                    print_yearly_table(eq)


def main():
    parser = argparse.ArgumentParser(description="Ensemble A/B Comparison")
    parser.add_argument(
        "--assets", nargs="+", default=["BTC", "ETH", "SOL"],
        choices=list(ASSET_DB.keys()),
        help="Assets to backtest",
    )
    parser.add_argument(
        "--config", default="config/strategies/allocation.json",
        help="Path to allocation config",
    )
    parser.add_argument(
        "--capital", type=float, default=10_000,
        help="Capital per asset",
    )
    parser.add_argument(
        "--start-date", default="2020-01-01",
        help="Backtest start date",
    )
    parser.add_argument(
        "--end-date", default="2026-02-01",
        help="Backtest end date",
    )
    parser.add_argument(
        "--by-year", action="store_true",
        help="Show per-year breakdown",
    )
    parser.add_argument(
        "--weights", nargs=4, type=float,
        help="Custom weights for 4 ensemble models (bwin3, bwin4, bwin5, bwin7)",
    )
    parser.add_argument(
        "--mtf", action="store_true",
        help="Compare paper_36 ensemble vs paper_mtf_44 ensemble",
    )
    parser.add_argument(
        "--mixed", action="store_true",
        help="Compare MLP-only ensemble vs Mixed (MLP+XGBoost+LightGBM) ensemble",
    )
    parser.add_argument(
        "--tree60", action="store_true",
        help="Compare MLP paper_36 ensemble vs Tree tree_60 ensemble",
    )
    parser.add_argument(
        "--fwin", action="store_true",
        help="Compare current exit (MLP SELL) vs fwin-aligned exit",
    )

    args = parser.parse_args()

    if args.fwin:
        run_fwin_comparison(
            assets=args.assets,
            config_path=args.config,
            capital_per_asset=args.capital,
            start_date=args.start_date,
            end_date=args.end_date,
            by_year=args.by_year,
        )
    elif args.tree60:
        run_tree60_comparison(
            assets=args.assets,
            config_path=args.config,
            capital_per_asset=args.capital,
            start_date=args.start_date,
            end_date=args.end_date,
            by_year=args.by_year,
        )
    elif args.mixed:
        run_mixed_comparison(
            assets=args.assets,
            config_path=args.config,
            capital_per_asset=args.capital,
            start_date=args.start_date,
            end_date=args.end_date,
            by_year=args.by_year,
        )
    elif args.mtf:
        run_mtf_comparison(
            assets=args.assets,
            config_path=args.config,
            capital_per_asset=args.capital,
            start_date=args.start_date,
            end_date=args.end_date,
            by_year=args.by_year,
        )
    else:
        run_comparison(
            assets=args.assets,
            config_path=args.config,
            capital_per_asset=args.capital,
            start_date=args.start_date,
            end_date=args.end_date,
            by_year=args.by_year,
            weights=args.weights,
        )


if __name__ == "__main__":
    main()
