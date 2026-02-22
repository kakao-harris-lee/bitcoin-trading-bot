#!/usr/bin/env python3
"""Run ALT-only bull-follow research backtests.

Keeps base MLP majors (BTC/ETH/BNB) out of the experimental universe, then
compares:
1) baseline equal-weight execution
2) trend-concentrated execution (score-weighted + crash guard)
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.bull_follow.train_bull_follow_model import (
    DEFAULT_DATA_DIR,
    DEFAULT_EXCLUDED_SYMBOLS,
    DEFAULT_MODEL_DIR,
    DEFAULT_REPORT_DIR,
    TrainConfig,
    _compute_metrics,
    build_train_test,
    evaluate_model,
    fit_model,
    load_symbol_frames,
    prepare_universe_features,
    resolve_feature_columns,
    resolve_target_column,
    resolve_train_end_date,
    run_portfolio_backtest,
    write_report,
)
from trading.indicators.bull_follow_features import BullFollowTargetConfig


DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "strategies" / "allocation.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="ALT-only bull-follow research backtest"
    )
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH))
    parser.add_argument("--strategy-id", default="mlp_direction_bnb")
    parser.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
    parser.add_argument("--timeframe", default="minute240")
    parser.add_argument("--symbols", nargs="+", default=None)
    parser.add_argument(
        "--exclude-symbols",
        nargs="+",
        default=list(DEFAULT_EXCLUDED_SYMBOLS),
        help="Majors excluded from ALT research universe.",
    )
    parser.add_argument("--start-date", default="2020-01-01")
    parser.add_argument(
        "--end-date",
        default=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    )
    parser.add_argument("--train-end-date", default="2024-12-31")
    parser.add_argument(
        "--target-mode", choices=("forward", "excess", "pnl"), default="forward"
    )
    parser.add_argument(
        "--feature-profile", choices=("base", "liquidity"), default="base"
    )
    parser.add_argument("--horizon-bars", type=int, default=1)
    parser.add_argument("--min-history", type=int, default=240)
    parser.add_argument("--top-k", type=int, default=8)
    parser.add_argument("--min-score", type=float, default=0.004)
    parser.add_argument("--min-adx", type=float, default=10.0)
    parser.add_argument("--breakout-floor", type=float, default=-0.01)
    parser.add_argument("--risk-on-breadth", type=float, default=0.45)
    parser.add_argument("--max-symbol-weight", type=float, default=0.75)
    parser.add_argument("--crash-ret3-threshold", type=float, default=-0.06)
    parser.add_argument("--crash-breadth-threshold", type=float, default=0.35)
    parser.add_argument("--fee-rate", type=float, default=0.001)
    parser.add_argument("--slippage", type=float, default=0.0002)
    parser.add_argument("--max-symbols", type=int, default=0)
    parser.add_argument("--random-state", type=int, default=42)
    parser.add_argument("--score-quantile", type=float, default=0.0)
    parser.add_argument("--score-power", type=float, default=2.5)
    parser.add_argument("--trend-weight", type=float, default=1.5)
    parser.add_argument("--vol-penalty-power", type=float, default=0.5)
    parser.add_argument(
        "--paper-preset",
        dest="paper_preset",
        action="store_true",
        help="Apply paper preset: no adaptive + symbol quality filter + regime weak guard.",
    )
    parser.add_argument(
        "--no-paper-preset",
        dest="paper_preset",
        action="store_false",
        help="Disable paper preset and use only explicit flags.",
    )
    parser.add_argument("--enable-breadth-adaptive", action="store_true")
    parser.add_argument("--no-breadth-adaptive", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--min-score-breadth-coef", type=float, default=0.004)
    parser.add_argument("--min-score-floor", type=float, default=0.003)
    parser.add_argument("--top-k-breadth-boost", type=float, default=0.5)
    parser.add_argument("--top-k-max", type=int, default=10)
    parser.add_argument("--enable-symbol-quality-filter", action="store_true")
    parser.add_argument("--symbol-quality-ema-alpha", type=float, default=0.35)
    parser.add_argument("--symbol-quality-min-ema", type=float, default=-0.006)
    parser.add_argument("--symbol-quality-min-obs", type=int, default=4)
    parser.add_argument("--enable-regime-weak-guard", action="store_true")
    parser.add_argument("--regime-breadth-drop-threshold", type=float, default=0.08)
    parser.add_argument("--regime-cs-ret1-threshold", type=float, default=-0.01)
    parser.add_argument("--model-dir", default=str(DEFAULT_MODEL_DIR))
    parser.add_argument("--report-dir", default=str(DEFAULT_REPORT_DIR))
    parser.set_defaults(paper_preset=True)
    return parser.parse_args()


def _dedupe_keep_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for raw in items:
        symbol = str(raw).strip().upper()
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        out.append(symbol)
    return out


def resolve_alt_symbols(
    config_path: Path,
    strategy_id: str,
    explicit_symbols: list[str] | None,
    exclude_symbols: list[str],
) -> list[str]:
    if explicit_symbols:
        symbols = _dedupe_keep_order(explicit_symbols)
    else:
        cfg = json.loads(config_path.read_text(encoding="utf-8"))
        strategy_symbols = (
            cfg.get("strategies", {}).get(strategy_id, {}).get("symbols", [])
        )
        root_symbols = cfg.get("symbols", [])
        symbols = _dedupe_keep_order(strategy_symbols or root_symbols)

    excluded = {s.upper() for s in exclude_symbols}
    return [s for s in symbols if s not in excluded]


def make_cfg(args: argparse.Namespace, **overrides: Any) -> TrainConfig:
    paper_preset = bool(getattr(args, "paper_preset", True))
    breadth_adaptive_enabled = (
        bool(args.enable_breadth_adaptive) and not bool(args.no_breadth_adaptive)
    )
    quality_filter_enabled = bool(args.enable_symbol_quality_filter) or paper_preset
    regime_guard_enabled = bool(args.enable_regime_weak_guard) or paper_preset
    base = {
        "start_date": args.start_date,
        "end_date": args.end_date,
        "train_end_date": args.train_end_date,
        "timeframe": args.timeframe,
        "top_k": int(args.top_k),
        "min_score": float(args.min_score),
        "min_adx": float(args.min_adx),
        "breakout_floor": float(args.breakout_floor),
        "risk_on_breadth": float(args.risk_on_breadth),
        "fee_rate": float(args.fee_rate),
        "slippage": float(args.slippage),
        "horizon_bars": int(args.horizon_bars),
        "min_history": int(args.min_history),
        "random_state": int(args.random_state),
        "weighting_mode": "equal",
        "max_symbol_weight": 1.0,
        "atr_vol_floor": 0.01,
        "atr_vol_cap": 0.12,
        "crash_guard_enabled": False,
        "crash_ret3_threshold": float(args.crash_ret3_threshold),
        "crash_breadth_threshold": float(args.crash_breadth_threshold),
        "score_power": float(args.score_power),
        "trend_weight": float(args.trend_weight),
        "vol_penalty_power": float(args.vol_penalty_power),
        "full_deploy_on_signal": True,
        "score_quantile": float(args.score_quantile),
        "breadth_adaptive_enabled": breadth_adaptive_enabled,
        "min_score_breadth_coef": float(args.min_score_breadth_coef),
        "min_score_floor": float(args.min_score_floor),
        "top_k_breadth_boost": float(args.top_k_breadth_boost),
        "top_k_max": int(args.top_k_max),
        "symbol_quality_filter_enabled": quality_filter_enabled,
        "symbol_quality_ema_alpha": float(args.symbol_quality_ema_alpha),
        "symbol_quality_min_ema": float(args.symbol_quality_min_ema),
        "symbol_quality_min_obs": int(args.symbol_quality_min_obs),
        "regime_weak_guard_enabled": regime_guard_enabled,
        "regime_breadth_drop_threshold": float(args.regime_breadth_drop_threshold),
        "regime_cs_ret1_threshold": float(args.regime_cs_ret1_threshold),
    }
    base.update(overrides)
    return TrainConfig(**base)


def _write_comparison_report(
    rows: list[dict[str, Any]],
    dataset_info: dict[str, Any],
    report_dir: Path,
) -> tuple[Path, Path]:
    report_dir.mkdir(parents=True, exist_ok=True)
    run_tag = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    csv_path = report_dir / f"bull_follow_alt_compare_{run_tag}.csv"
    md_path = report_dir / f"bull_follow_alt_compare_{run_tag}.md"

    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values(
            ["alpha_return_pct", "strategy_return_pct"], ascending=False
        )
    df.to_csv(csv_path, index=False)

    lines = [
        "# ALT Bull-Follow Variant Comparison",
        "",
        f"- run_tag: `{run_tag}`",
        f"- symbols: `{dataset_info['symbol_count']}`",
        f"- symbol_list: `{', '.join(dataset_info['symbols'])}`",
        f"- split: train `{dataset_info['train_rows']}` / test `{dataset_info['test_rows']}` (train_end `{dataset_info['train_end']}`)",
        f"- csv: `{csv_path.relative_to(PROJECT_ROOT)}`",
        "",
        "| Variant | Return % | MDD % | Sharpe | EW B&H % | Alpha %p | Avg Exposure | Crash Bars |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in df.to_dict(orient="records"):
        lines.append(
            "| "
            f"{row['variant']} | "
            f"{row['strategy_return_pct']:.2f} | "
            f"{row['strategy_mdd_pct']:.2f} | "
            f"{row['strategy_sharpe']:.3f} | "
            f"{row['benchmark_return_pct']:.2f} | "
            f"{row['alpha_return_pct']:.2f} | "
            f"{row['avg_gross_exposure']:.3f} | "
            f"{int(row['crash_block_bars'])} |"
        )
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return csv_path, md_path


def main() -> int:
    args = parse_args()
    config_path = Path(args.config)
    data_dir = Path(args.data_dir)
    model_dir = Path(args.model_dir)
    report_dir = Path(args.report_dir)

    target_column = resolve_target_column(args.target_mode)
    feature_cols = resolve_feature_columns(args.feature_profile)
    target_cfg = BullFollowTargetConfig(horizon_bars=int(args.horizon_bars))

    alt_symbols = resolve_alt_symbols(
        config_path=config_path,
        strategy_id=args.strategy_id,
        explicit_symbols=args.symbols,
        exclude_symbols=[s.upper() for s in args.exclude_symbols],
    )
    if not alt_symbols:
        print("No ALT symbols resolved after exclusions.")
        return 1

    frames = load_symbol_frames(
        data_dir=data_dir,
        timeframe=args.timeframe,
        symbols=alt_symbols,
        exclude_symbols=[],
        start_date=args.start_date,
        end_date=args.end_date,
        max_symbols=int(args.max_symbols),
    )
    if not frames:
        print("No frames loaded for ALT symbols.")
        return 1

    feature_frame = prepare_universe_features(
        symbol_frames=frames,
        target_config=target_cfg,
        min_history=int(args.min_history),
    )
    train_end = resolve_train_end_date(feature_frame, args.train_end_date)
    train_df, test_df = build_train_test(
        frame=feature_frame,
        feature_cols=feature_cols,
        train_end_date=train_end,
        target_column=target_column,
    )

    model = fit_model(
        train_df=train_df,
        feature_cols=feature_cols,
        random_state=int(args.random_state),
        target_column=target_column,
    )
    model_eval = evaluate_model(
        model=model,
        test_df=test_df,
        feature_cols=feature_cols,
        target_column=target_column,
    )

    variants = [
        (
            "alt_baseline_equal",
            make_cfg(
                args,
                weighting_mode="equal",
                max_symbol_weight=1.0,
                crash_guard_enabled=False,
                full_deploy_on_signal=True,
            ),
        ),
        (
            "alt_trend_concentrated_guard",
            make_cfg(
                args,
                weighting_mode="trend_score_inv_vol",
                max_symbol_weight=float(args.max_symbol_weight),
                crash_guard_enabled=True,
                crash_ret3_threshold=float(args.crash_ret3_threshold),
                crash_breadth_threshold=float(args.crash_breadth_threshold),
                full_deploy_on_signal=True,
            ),
        ),
    ]

    run_tag = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    rows: list[dict[str, Any]] = []
    for variant_name, cfg in variants:
        equity_df, symbol_df, extra = run_portfolio_backtest(
            test_df=test_df,
            model=model,
            feature_cols=feature_cols,
            cfg=cfg,
        )
        strat = _compute_metrics(equity_df["equity"], equity_df["timestamp"])
        bnh = _compute_metrics(equity_df["benchmark_equity"], equity_df["timestamp"])
        alpha = float(strat.total_return_pct - bnh.total_return_pct)

        artifacts = write_report(
            run_tag=f"{run_tag}_{variant_name}",
            experiment_tag=f"alt_{args.feature_profile}_{args.target_mode}_{variant_name}",
            feature_profile=args.feature_profile,
            target_mode=args.target_mode,
            target_column=target_column,
            target_config=target_cfg,
            cfg=cfg,
            model=model,
            model_eval=model_eval,
            train_df=train_df,
            test_df=test_df,
            feature_cols=feature_cols,
            equity_df=equity_df,
            symbol_df=symbol_df,
            extra=extra,
            model_dir=model_dir,
            report_dir=report_dir,
        )

        rows.append(
            {
                "variant": variant_name,
                "strategy_return_pct": float(strat.total_return_pct),
                "strategy_mdd_pct": float(strat.mdd_pct),
                "strategy_sharpe": float(strat.sharpe),
                "benchmark_return_pct": float(bnh.total_return_pct),
                "benchmark_mdd_pct": float(bnh.mdd_pct),
                "alpha_return_pct": alpha,
                "avg_gross_exposure": float(extra["avg_gross_exposure"]),
                "avg_selected_count": float(extra["avg_selected_count"]),
                "crash_block_bars": int(extra["crash_block_bars"]),
                "summary_md": str(artifacts["summary_md"].relative_to(PROJECT_ROOT)),
                "config": json.dumps(asdict(cfg), ensure_ascii=True),
            }
        )

    dataset_info = {
        "symbol_count": len(train_df["symbol"].unique()),
        "symbols": sorted(train_df["symbol"].unique().tolist()),
        "train_rows": int(len(train_df)),
        "test_rows": int(len(test_df)),
        "train_end": str(train_end.date()),
    }
    csv_path, md_path = _write_comparison_report(
        rows=rows,
        dataset_info=dataset_info,
        report_dir=report_dir,
    )

    print(
        "ALT research backtest complete:",
        f"symbols={dataset_info['symbol_count']}",
        f"csv={csv_path.relative_to(PROJECT_ROOT)}",
        f"md={md_path.relative_to(PROJECT_ROOT)}",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
