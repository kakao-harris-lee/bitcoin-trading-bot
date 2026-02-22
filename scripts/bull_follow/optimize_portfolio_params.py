#!/usr/bin/env python3
"""Optuna tuning for bull-follow portfolio execution parameters.

Tunes portfolio-level parameters while keeping the base cross-asset model fixed.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import optuna
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.bull_follow.train_bull_follow_model import (  # noqa: E402
    BULL_FOLLOW_FEATURE_COLUMNS,
    DEFAULT_EXCLUDED_SYMBOLS,
    TrainConfig,
    _compute_metrics,
    build_train_test,
    evaluate_model,
    fit_model,
    load_symbol_frames,
    resolve_train_end_date,
    run_portfolio_backtest,
)
from trading.indicators.bull_follow_features import (  # noqa: E402
    BullFollowTargetConfig,
    prepare_universe_features,
)


DEFAULT_DATA_DIR = PROJECT_ROOT / "data" / "universe_backtest_4h"
DEFAULT_REPORT_DIR = PROJECT_ROOT / "reports"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Optimize bull-follow portfolio parameters"
    )
    parser.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
    parser.add_argument("--timeframe", default="minute240")
    parser.add_argument("--symbols", nargs="+", default=None)
    parser.add_argument(
        "--exclude-symbols",
        nargs="+",
        default=list(DEFAULT_EXCLUDED_SYMBOLS),
    )
    parser.add_argument("--start-date", default="2020-01-01")
    parser.add_argument(
        "--end-date",
        default=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    )
    parser.add_argument("--train-end-date", default="2024-12-31")
    parser.add_argument("--horizon-bars", type=int, default=1)
    parser.add_argument("--min-history", type=int, default=240)
    parser.add_argument("--fee-rate", type=float, default=0.001)
    parser.add_argument("--slippage", type=float, default=0.0002)
    parser.add_argument("--random-state", type=int, default=42)
    parser.add_argument("--n-trials", type=int, default=40)
    parser.add_argument("--timeout-sec", type=int, default=0)
    parser.add_argument("--max-symbols", type=int, default=0)
    parser.add_argument(
        "--min-avg-selected",
        type=float,
        default=0.8,
        help="Minimum average selected symbols per bar for a trial to be valid",
    )
    parser.add_argument(
        "--min-risk-on-bars",
        type=int,
        default=300,
        help="Minimum number of risk-on bars for a trial to be valid",
    )
    parser.add_argument(
        "--min-avg-exposure",
        type=float,
        default=0.01,
        help="Minimum average gross exposure per bar",
    )
    parser.add_argument(
        "--min-nonzero-ratio",
        type=float,
        default=0.01,
        help="Minimum ratio of bars with non-zero exposure",
    )
    parser.add_argument(
        "--objective-mode",
        choices=("return_first", "sharpe_first"),
        default="return_first",
        help="Optimization objective blend",
    )
    parser.add_argument("--report-dir", default=str(DEFAULT_REPORT_DIR))
    return parser.parse_args()


def make_cfg(
    base: dict[str, Any],
    top_k: int | None = None,
    min_score: float | None = None,
    min_adx: float | None = None,
    breakout_floor: float | None = None,
    risk_on_breadth: float | None = None,
    max_symbol_weight: float | None = None,
    score_power: float | None = None,
    trend_weight: float | None = None,
    vol_penalty_power: float | None = None,
    crash_ret3_threshold: float | None = None,
    crash_breadth_threshold: float | None = None,
    score_quantile: float | None = None,
    weighting_mode: str | None = None,
    min_score_breadth_coef: float | None = None,
    min_score_floor: float | None = None,
    top_k_breadth_boost: float | None = None,
    top_k_max: int | None = None,
    symbol_quality_filter_enabled: bool | None = None,
    symbol_quality_ema_alpha: float | None = None,
    symbol_quality_min_ema: float | None = None,
    symbol_quality_min_obs: int | None = None,
    regime_weak_guard_enabled: bool | None = None,
    regime_breadth_drop_threshold: float | None = None,
    regime_cs_ret1_threshold: float | None = None,
) -> TrainConfig:
    return TrainConfig(
        start_date=base["start_date"],
        end_date=base["end_date"],
        train_end_date=base["train_end_date"],
        timeframe=base["timeframe"],
        top_k=int(top_k if top_k is not None else base["top_k"]),
        min_score=float(min_score if min_score is not None else base["min_score"]),
        min_adx=float(min_adx if min_adx is not None else base["min_adx"]),
        breakout_floor=float(
            breakout_floor if breakout_floor is not None else base["breakout_floor"]
        ),
        risk_on_breadth=float(
            risk_on_breadth if risk_on_breadth is not None else base["risk_on_breadth"]
        ),
        fee_rate=float(base["fee_rate"]),
        slippage=float(base["slippage"]),
        horizon_bars=int(base["horizon_bars"]),
        min_history=int(base["min_history"]),
        random_state=int(base["random_state"]),
        weighting_mode=str(weighting_mode or base["weighting_mode"]),
        max_symbol_weight=float(
            max_symbol_weight
            if max_symbol_weight is not None
            else base["max_symbol_weight"]
        ),
        atr_vol_floor=float(base["atr_vol_floor"]),
        atr_vol_cap=float(base["atr_vol_cap"]),
        crash_guard_enabled=bool(base["crash_guard_enabled"]),
        crash_ret3_threshold=float(
            crash_ret3_threshold
            if crash_ret3_threshold is not None
            else base["crash_ret3_threshold"]
        ),
        crash_breadth_threshold=float(
            crash_breadth_threshold
            if crash_breadth_threshold is not None
            else base["crash_breadth_threshold"]
        ),
        score_power=float(
            score_power if score_power is not None else base["score_power"]
        ),
        trend_weight=float(
            trend_weight if trend_weight is not None else base["trend_weight"]
        ),
        vol_penalty_power=float(
            vol_penalty_power
            if vol_penalty_power is not None
            else base["vol_penalty_power"]
        ),
        full_deploy_on_signal=bool(base["full_deploy_on_signal"]),
        score_quantile=float(
            score_quantile if score_quantile is not None else base["score_quantile"]
        ),
        breadth_adaptive_enabled=bool(base["breadth_adaptive_enabled"]),
        min_score_breadth_coef=float(
            min_score_breadth_coef
            if min_score_breadth_coef is not None
            else base["min_score_breadth_coef"]
        ),
        min_score_floor=float(
            min_score_floor if min_score_floor is not None else base["min_score_floor"]
        ),
        top_k_breadth_boost=float(
            top_k_breadth_boost
            if top_k_breadth_boost is not None
            else base["top_k_breadth_boost"]
        ),
        top_k_max=int(top_k_max if top_k_max is not None else base["top_k_max"]),
        symbol_quality_filter_enabled=bool(
            symbol_quality_filter_enabled
            if symbol_quality_filter_enabled is not None
            else base["symbol_quality_filter_enabled"]
        ),
        symbol_quality_ema_alpha=float(
            symbol_quality_ema_alpha
            if symbol_quality_ema_alpha is not None
            else base["symbol_quality_ema_alpha"]
        ),
        symbol_quality_min_ema=float(
            symbol_quality_min_ema
            if symbol_quality_min_ema is not None
            else base["symbol_quality_min_ema"]
        ),
        symbol_quality_min_obs=int(
            symbol_quality_min_obs
            if symbol_quality_min_obs is not None
            else base["symbol_quality_min_obs"]
        ),
        regime_weak_guard_enabled=bool(
            regime_weak_guard_enabled
            if regime_weak_guard_enabled is not None
            else base["regime_weak_guard_enabled"]
        ),
        regime_breadth_drop_threshold=float(
            regime_breadth_drop_threshold
            if regime_breadth_drop_threshold is not None
            else base["regime_breadth_drop_threshold"]
        ),
        regime_cs_ret1_threshold=float(
            regime_cs_ret1_threshold
            if regime_cs_ret1_threshold is not None
            else base["regime_cs_ret1_threshold"]
        ),
    )


def evaluate_cfg(
    cfg: TrainConfig,
    test_df: pd.DataFrame,
    model,
) -> dict[str, float]:
    equity_df, _, extra = run_portfolio_backtest(
        test_df=test_df,
        model=model,
        feature_cols=BULL_FOLLOW_FEATURE_COLUMNS,
        cfg=cfg,
    )

    strat = _compute_metrics(equity_df["equity"], equity_df["timestamp"])
    bnh = _compute_metrics(equity_df["benchmark_equity"], equity_df["timestamp"])

    return {
        "strategy_return": float(strat.total_return_pct),
        "strategy_mdd": float(strat.mdd_pct),
        "strategy_sharpe": float(strat.sharpe),
        "benchmark_return": float(bnh.total_return_pct),
        "benchmark_mdd": float(bnh.mdd_pct),
        "alpha_return": float(strat.total_return_pct - bnh.total_return_pct),
        "avg_selected_count": float(extra["avg_selected_count"]),
        "avg_gross_exposure": float(extra.get("avg_gross_exposure", 0.0)),
        "nonzero_exposure_ratio": float(
            (equity_df["gross_exposure"] > 0).mean()
            if "gross_exposure" in equity_df.columns
            else 0.0
        ),
        "risk_on_bars": float(extra["risk_on_bars"]),
        "bars": float(extra["bars"]),
    }


def main() -> int:
    args = parse_args()

    report_dir = Path(args.report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)

    base = {
        "start_date": args.start_date,
        "end_date": args.end_date,
        "train_end_date": args.train_end_date,
        "timeframe": args.timeframe,
        "top_k": 8,
        "min_score": 0.004,
        "min_adx": 10.0,
        "breakout_floor": -0.01,
        "risk_on_breadth": 0.45,
        "fee_rate": args.fee_rate,
        "slippage": args.slippage,
        "horizon_bars": args.horizon_bars,
        "min_history": args.min_history,
        "random_state": args.random_state,
        "weighting_mode": "trend_score_inv_vol",
        "max_symbol_weight": 0.75,
        "atr_vol_floor": 0.01,
        "atr_vol_cap": 0.12,
        "crash_guard_enabled": True,
        "crash_ret3_threshold": -0.06,
        "crash_breadth_threshold": 0.35,
        "score_power": 2.5,
        "trend_weight": 1.5,
        "vol_penalty_power": 0.5,
        "full_deploy_on_signal": True,
        "score_quantile": 0.0,
        "breadth_adaptive_enabled": True,
        "min_score_breadth_coef": 0.004,
        "min_score_floor": 0.003,
        "top_k_breadth_boost": 0.5,
        "top_k_max": 10,
        "symbol_quality_filter_enabled": False,
        "symbol_quality_ema_alpha": 0.35,
        "symbol_quality_min_ema": -0.006,
        "symbol_quality_min_obs": 4,
        "regime_weak_guard_enabled": False,
        "regime_breadth_drop_threshold": 0.08,
        "regime_cs_ret1_threshold": -0.01,
    }

    frames = load_symbol_frames(
        data_dir=Path(args.data_dir),
        timeframe=args.timeframe,
        symbols=[s.upper() for s in args.symbols] if args.symbols else None,
        exclude_symbols=[s.upper() for s in args.exclude_symbols],
        start_date=args.start_date,
        end_date=args.end_date,
        max_symbols=int(args.max_symbols),
    )
    if not frames:
        print("No symbol data loaded.")
        return 1

    feature_frame = prepare_universe_features(
        symbol_frames=frames,
        target_config=BullFollowTargetConfig(horizon_bars=args.horizon_bars),
        min_history=args.min_history,
    )
    train_end = resolve_train_end_date(feature_frame, args.train_end_date)
    train_df, test_df = build_train_test(
        frame=feature_frame,
        feature_cols=BULL_FOLLOW_FEATURE_COLUMNS,
        train_end_date=train_end,
    )

    print(
        "Dataset:",
        f"symbols={len(train_df['symbol'].unique())}",
        f"train={len(train_df):,}",
        f"test={len(test_df):,}",
        f"train_end={train_end.date()}",
    )

    model = fit_model(
        train_df=train_df,
        feature_cols=BULL_FOLLOW_FEATURE_COLUMNS,
        random_state=args.random_state,
    )
    model_eval = evaluate_model(
        model=model,
        test_df=test_df,
        feature_cols=BULL_FOLLOW_FEATURE_COLUMNS,
    )
    # Reuse predictions in each trial for faster optimization.
    test_df = test_df.copy()
    test_df["pred_score"] = model.predict(
        test_df[BULL_FOLLOW_FEATURE_COLUMNS].to_numpy(dtype="float32")
    )
    print(
        "Model fixed:",
        f"MAE={model_eval['mae']:.6f}",
        f"IC={model_eval['spearman_ic']:.6f}",
        f"spread={model_eval['top_minus_bottom']*100:.4f}%p",
    )

    baseline_cfg = make_cfg(
        base=base,
        top_k=8,
        min_score=0.004,
        min_adx=10.0,
        breakout_floor=-0.01,
        risk_on_breadth=0.45,
    )
    baseline_stats = evaluate_cfg(baseline_cfg, test_df=test_df, model=model)
    print(
        "Baseline:",
        f"ret={baseline_stats['strategy_return']:.2f}%",
        f"alpha={baseline_stats['alpha_return']:.2f}%p",
        f"mdd={baseline_stats['strategy_mdd']:.2f}%",
    )

    records: list[dict[str, Any]] = []

    def objective(trial: optuna.Trial) -> float:
        cfg = make_cfg(
            base=base,
            top_k=trial.suggest_int("top_k", 4, 12),
            min_score=trial.suggest_float("min_score", 0.002, 0.008),
            min_adx=trial.suggest_float("min_adx", 8.0, 16.0),
            breakout_floor=trial.suggest_float("breakout_floor", -0.02, 0.01),
            risk_on_breadth=trial.suggest_float("risk_on_breadth", 0.35, 0.60),
            max_symbol_weight=trial.suggest_float("max_symbol_weight", 0.50, 1.00),
            score_power=trial.suggest_float("score_power", 1.0, 4.0),
            trend_weight=trial.suggest_float("trend_weight", 0.5, 2.5),
            vol_penalty_power=trial.suggest_float("vol_penalty_power", 0.0, 1.0),
            crash_ret3_threshold=trial.suggest_float(
                "crash_ret3_threshold", -0.09, -0.03
            ),
            crash_breadth_threshold=trial.suggest_float(
                "crash_breadth_threshold", 0.20, 0.50
            ),
            score_quantile=trial.suggest_float("score_quantile", 0.0, 0.9),
            min_score_breadth_coef=trial.suggest_float(
                "min_score_breadth_coef", 0.0, 0.03
            ),
            min_score_floor=trial.suggest_float("min_score_floor", 0.0, 0.003),
            top_k_breadth_boost=trial.suggest_float("top_k_breadth_boost", 0.0, 20.0),
            top_k_max=trial.suggest_int("top_k_max", 8, 20),
        )
        stats = evaluate_cfg(cfg, test_df=test_df, model=model)
        # Objective with activity constraints:
        # - avoid degenerate no-trade solutions that only maximize alpha by staying flat.
        if stats["avg_selected_count"] < args.min_avg_selected:
            score = -10_000.0 + float(stats["avg_selected_count"])
        elif stats["risk_on_bars"] < args.min_risk_on_bars:
            score = -9_000.0 + float(stats["risk_on_bars"]) / 100.0
        elif stats["avg_gross_exposure"] < args.min_avg_exposure:
            score = -8_000.0 + float(stats["avg_gross_exposure"]) * 100.0
        elif stats["nonzero_exposure_ratio"] < args.min_nonzero_ratio:
            score = -7_000.0 + float(stats["nonzero_exposure_ratio"]) * 100.0
        else:
            if args.objective_mode == "sharpe_first":
                score = (
                    1.25 * float(stats["strategy_return"])
                    + 0.15 * float(stats["alpha_return"])
                    + 3.00 * float(stats["strategy_sharpe"])
                    - 0.06 * abs(float(stats["strategy_mdd"]))
                    + 10.0 * float(stats["avg_gross_exposure"])
                )
            else:
                score = (
                    1.50 * float(stats["strategy_return"])
                    + 0.10 * float(stats["alpha_return"])
                    + 1.50 * float(stats["strategy_sharpe"])
                    - 0.05 * abs(float(stats["strategy_mdd"]))
                    + 12.0 * float(stats["avg_gross_exposure"])
                )

        trial.set_user_attr("strategy_return", stats["strategy_return"])
        trial.set_user_attr("strategy_mdd", stats["strategy_mdd"])
        trial.set_user_attr("alpha_return", stats["alpha_return"])
        trial.set_user_attr("strategy_sharpe", stats["strategy_sharpe"])
        trial.set_user_attr("benchmark_return", stats["benchmark_return"])
        trial.set_user_attr("avg_gross_exposure", stats["avg_gross_exposure"])
        trial.set_user_attr("nonzero_exposure_ratio", stats["nonzero_exposure_ratio"])

        records.append(
            {
                "trial": trial.number,
                **trial.params,
                **stats,
                "score": score,
            }
        )
        return score

    study = optuna.create_study(
        direction="maximize",
        sampler=optuna.samplers.TPESampler(seed=args.random_state),
        study_name=f"bull_follow_exec_opt_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}",
    )

    study.optimize(
        objective,
        n_trials=args.n_trials,
        timeout=(None if args.timeout_sec <= 0 else args.timeout_sec),
        show_progress_bar=False,
    )

    best = study.best_trial
    best_cfg = make_cfg(
        base=base,
        top_k=int(best.params["top_k"]),
        min_score=float(best.params["min_score"]),
        min_adx=float(best.params["min_adx"]),
        breakout_floor=float(best.params["breakout_floor"]),
        risk_on_breadth=float(best.params["risk_on_breadth"]),
        max_symbol_weight=float(best.params["max_symbol_weight"]),
        score_power=float(best.params["score_power"]),
        trend_weight=float(best.params["trend_weight"]),
        vol_penalty_power=float(best.params["vol_penalty_power"]),
        crash_ret3_threshold=float(best.params["crash_ret3_threshold"]),
        crash_breadth_threshold=float(best.params["crash_breadth_threshold"]),
        score_quantile=float(best.params["score_quantile"]),
        min_score_breadth_coef=float(best.params["min_score_breadth_coef"]),
        min_score_floor=float(best.params["min_score_floor"]),
        top_k_breadth_boost=float(best.params["top_k_breadth_boost"]),
        top_k_max=int(best.params["top_k_max"]),
    )
    best_stats = evaluate_cfg(best_cfg, test_df=test_df, model=model)

    run_tag = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    trials_csv = report_dir / f"bull_follow_optuna_{run_tag}_trials.csv"
    summary_json = report_dir / f"bull_follow_optuna_{run_tag}_summary.json"
    summary_md = report_dir / f"bull_follow_optuna_{run_tag}_summary.md"

    df_trials = pd.DataFrame(records)
    if not df_trials.empty:
        df_trials = df_trials.sort_values("score", ascending=False).reset_index(
            drop=True
        )
    df_trials.to_csv(trials_csv, index=False)

    payload = {
        "run_tag": run_tag,
        "n_trials": int(args.n_trials),
        "constraints": {
            "min_avg_selected": float(args.min_avg_selected),
            "min_risk_on_bars": int(args.min_risk_on_bars),
            "min_avg_exposure": float(args.min_avg_exposure),
            "min_nonzero_ratio": float(args.min_nonzero_ratio),
        },
        "baseline": {
            "config": asdict(baseline_cfg),
            "stats": baseline_stats,
        },
        "best": {
            "trial_number": int(best.number),
            "score": float(best.value),
            "params": best.params,
            "config": asdict(best_cfg),
            "stats": best_stats,
        },
        "improvement": {
            "return_delta": float(
                best_stats["strategy_return"] - baseline_stats["strategy_return"]
            ),
            "alpha_delta": float(
                best_stats["alpha_return"] - baseline_stats["alpha_return"]
            ),
            "mdd_delta": float(
                best_stats["strategy_mdd"] - baseline_stats["strategy_mdd"]
            ),
            "sharpe_delta": float(
                best_stats["strategy_sharpe"] - baseline_stats["strategy_sharpe"]
            ),
        },
        "model_eval": model_eval,
        "dataset": {
            "symbols": sorted(train_df["symbol"].unique().tolist()),
            "train_rows": int(len(train_df)),
            "test_rows": int(len(test_df)),
            "train_end": str(train_end.date()),
        },
        "artifacts": {
            "trials_csv": str(trials_csv.relative_to(PROJECT_ROOT)),
        },
    }
    summary_json.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    lines = [
        "# Bull-Follow Optuna Tuning Summary",
        "",
        f"- run_tag: `{run_tag}`",
        f"- trials: `{len(df_trials)}`",
        f"- trials_csv: `{trials_csv.relative_to(PROJECT_ROOT)}`",
        f"- constraints: `avg_selected >= {args.min_avg_selected:.2f}, risk_on_bars >= {args.min_risk_on_bars}, avg_exposure >= {args.min_avg_exposure:.3f}, nonzero_ratio >= {args.min_nonzero_ratio:.3f}`",
        "",
        "## Baseline",
        "",
        f"- return: `{baseline_stats['strategy_return']:.2f}%`",
        f"- alpha: `{baseline_stats['alpha_return']:.2f}%p`",
        f"- mdd: `{baseline_stats['strategy_mdd']:.2f}%`",
        f"- sharpe: `{baseline_stats['strategy_sharpe']:.3f}`",
        f"- avg_selected_count: `{baseline_stats['avg_selected_count']:.2f}`",
        f"- avg_gross_exposure: `{baseline_stats['avg_gross_exposure']:.3f}`",
        f"- nonzero_exposure_ratio: `{baseline_stats['nonzero_exposure_ratio']:.3f}`",
        f"- risk_on_bars: `{baseline_stats['risk_on_bars']:.0f}`",
        "",
        "## Best",
        "",
        f"- trial: `{best.number}`",
        f"- score(alpha): `{best.value:.2f}`",
        f"- params: `top_k={best.params['top_k']}, min_score={best.params['min_score']:.5f}, min_adx={best.params['min_adx']:.2f}, breakout_floor={best.params['breakout_floor']:.4f}, risk_on_breadth={best.params['risk_on_breadth']:.3f}, max_symbol_weight={best.params['max_symbol_weight']:.2f}, score_power={best.params['score_power']:.2f}, trend_weight={best.params['trend_weight']:.2f}, vol_penalty_power={best.params['vol_penalty_power']:.2f}, crash_ret3_threshold={best.params['crash_ret3_threshold']:.3f}, crash_breadth_threshold={best.params['crash_breadth_threshold']:.3f}, score_quantile={best.params['score_quantile']:.2f}, min_score_breadth_coef={best.params['min_score_breadth_coef']:.4f}, min_score_floor={best.params['min_score_floor']:.4f}, top_k_breadth_boost={best.params['top_k_breadth_boost']:.2f}, top_k_max={best.params['top_k_max']}`",
        f"- return: `{best_stats['strategy_return']:.2f}%`",
        f"- alpha: `{best_stats['alpha_return']:.2f}%p`",
        f"- mdd: `{best_stats['strategy_mdd']:.2f}%`",
        f"- sharpe: `{best_stats['strategy_sharpe']:.3f}`",
        f"- avg_selected_count: `{best_stats['avg_selected_count']:.2f}`",
        f"- avg_gross_exposure: `{best_stats['avg_gross_exposure']:.3f}`",
        f"- nonzero_exposure_ratio: `{best_stats['nonzero_exposure_ratio']:.3f}`",
        f"- risk_on_bars: `{best_stats['risk_on_bars']:.0f}`",
        "",
        "## Delta (Best - Baseline)",
        "",
        f"- return_delta: `{payload['improvement']['return_delta']:.2f}%p`",
        f"- alpha_delta: `{payload['improvement']['alpha_delta']:.2f}%p`",
        f"- mdd_delta: `{payload['improvement']['mdd_delta']:.2f}%p`",
        f"- sharpe_delta: `{payload['improvement']['sharpe_delta']:.3f}`",
    ]
    summary_md.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"Best trial={best.number} score={best.value:.2f}")
    print(
        f"Best return={best_stats['strategy_return']:.2f}% alpha={best_stats['alpha_return']:.2f}%p mdd={best_stats['strategy_mdd']:.2f}%"
    )
    print(f"Summary: {summary_md.relative_to(PROJECT_ROOT)}")
    print(f"JSON: {summary_json.relative_to(PROJECT_ROOT)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
