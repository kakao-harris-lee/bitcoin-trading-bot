#!/usr/bin/env python3
"""Run RF+HMM ensemble OOS evaluation on a regime feature table."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, classification_report, f1_score

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from trading.regime.ensemble import (
    build_hmm_feature_frame_from_table,
    build_state_class_distribution,
    combine_probabilities,
    predict_proba_all_classes,
    states_to_class_proba,
)
from trading.regime.hybrid import apply_sideways_guard
from trading.regime.calibration import apply_class_multipliers, tune_class_multipliers
from trading.regime.training import (
    CLASS_TO_REGIME,
    DEFAULT_FEATURE_COLUMNS,
    add_regime_target,
    build_supervised_dataset,
    compute_class_weight_map,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate RF+HMM regime ensemble (OOS).")
    parser.add_argument("--dataset", required=True, help="Input feature table (.csv/.parquet)")
    parser.add_argument("--output-dir", required=True, help="Directory for metrics/predictions")
    parser.add_argument("--features", default="", help="Comma-separated RF feature columns")
    parser.add_argument("--forward-horizon", type=int, default=6)
    parser.add_argument("--bull-threshold", type=float, default=0.015)
    parser.add_argument("--bear-threshold", type=float, default=-0.015)
    parser.add_argument("--train-ratio", type=float, default=0.7)
    parser.add_argument("--val-ratio", type=float, default=0.15)
    parser.add_argument("--rf-weight", type=float, default=0.7)
    parser.add_argument("--hmm-weight", type=float, default=0.3)
    parser.add_argument(
        "--rf-calibration-grid",
        default="0.7,0.85,1.0,1.15,1.3,1.6",
        help="Comma-separated RF class multipliers grid for validation-based calibration.",
    )
    parser.add_argument(
        "--weight-grid",
        default="",
        help="Optional comma-separated RF weights for post-fit ensemble sweep (e.g. 0.95,0.9,0.8,0.7).",
    )
    parser.add_argument("--rf-n-estimators", type=int, default=600)
    parser.add_argument("--rf-max-depth", type=int, default=12)
    parser.add_argument("--hmm-components", type=int, default=3)
    parser.add_argument("--hmm-iter", type=int, default=250)
    parser.add_argument("--hmm-vol-window", type=int, default=24)
    parser.add_argument(
        "--hmm-extra-features",
        default="atr,adx,volume",
        help="Comma-separated extra HMM features from table: atr,adx,volume (empty for base-only).",
    )
    parser.add_argument(
        "--hybrid-conf-threshold",
        type=float,
        default=0.55,
        help="RF confidence threshold for sideways guard.",
    )
    parser.add_argument(
        "--hybrid-sideways-threshold",
        type=float,
        default=0.65,
        help="HMM sideways probability threshold for sideways guard.",
    )
    parser.add_argument(
        "--hybrid-conf-grid",
        default="",
        help="Optional comma-separated confidence thresholds for hybrid guard sweep.",
    )
    parser.add_argument(
        "--hybrid-sideways-grid",
        default="",
        help="Optional comma-separated HMM sideways thresholds for hybrid guard sweep.",
    )
    parser.add_argument("--random-state", type=int, default=42)
    return parser.parse_args()


def _read_frame(path: Path) -> pd.DataFrame:
    if path.suffix.lower() == ".parquet":
        return pd.read_parquet(path)
    return pd.read_csv(path)


def _split_bounds(n: int, train_ratio: float, val_ratio: float) -> tuple[int, int]:
    if n < 100:
        raise ValueError("need at least 100 rows for ensemble OOS evaluation")
    if not (0 < train_ratio < 1) or not (0 <= val_ratio < 1):
        raise ValueError("invalid split ratios")
    if train_ratio + val_ratio >= 1:
        raise ValueError("train_ratio + val_ratio must be < 1")
    train_end = int(n * train_ratio)
    val_end = int(n * (train_ratio + val_ratio))
    return train_end, val_end


def _metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, float]:
    return {
        "accuracy": float(accuracy_score(y_true, y_pred)),
        "macro_f1": float(f1_score(y_true, y_pred, average="macro")),
    }


def _parse_float_grid(raw: str, *, low: float = 0.0, high: float = 1.0) -> list[float]:
    if not raw.strip():
        return []
    values: list[float] = []
    for token in raw.split(","):
        t = token.strip()
        if not t:
            continue
        w = float(t)
        if not (low <= w <= high):
            raise ValueError(f"value out of range [{low}, {high}]: {w}")
        values.append(w)
    return values


def _parse_hmm_extra_features(raw: str) -> tuple[bool, bool, bool]:
    tokens = {t.strip().lower() for t in raw.split(",") if t.strip()}
    if not tokens:
        return False, False, False
    allowed = {"atr", "adx", "volume"}
    unknown = sorted(tokens - allowed)
    if unknown:
        raise ValueError(f"unsupported hmm extra features: {unknown}")
    return ("atr" in tokens), ("adx" in tokens), ("volume" in tokens)


def main() -> int:
    args = parse_args()

    try:
        from hmmlearn.hmm import GaussianHMM
    except Exception as exc:
        raise RuntimeError("hmmlearn is required. Install via: pip install hmmlearn") from exc

    dataset_path = Path(args.dataset)
    if not dataset_path.exists():
        raise FileNotFoundError(f"dataset not found: {dataset_path}")

    frame = _read_frame(dataset_path)
    frame = add_regime_target(
        frame,
        forward_horizon=args.forward_horizon,
        bull_threshold=args.bull_threshold,
        bear_threshold=args.bear_threshold,
    )

    features = [f.strip() for f in args.features.split(",") if f.strip()] or list(DEFAULT_FEATURE_COLUMNS)
    data = build_supervised_dataset(frame, feature_columns=features, target_column="regime_target_class")

    working = data.frame.reset_index(drop=True)
    X = data.X.reset_index(drop=True)
    y = data.y.reset_index(drop=True)

    train_end, val_end = _split_bounds(len(X), args.train_ratio, args.val_ratio)

    # RF train/val/test
    X_train = X.iloc[:train_end]
    y_train = y.iloc[:train_end]
    X_val = X.iloc[train_end:val_end]
    y_val = y.iloc[train_end:val_end]
    X_test = X.iloc[val_end:]

    class_weight = compute_class_weight_map(y_train)
    rf = RandomForestClassifier(
        n_estimators=args.rf_n_estimators,
        max_depth=args.rf_max_depth,
        class_weight=class_weight or None,
        random_state=args.random_state,
        n_jobs=-1,
    )
    rf.fit(X_train, y_train)

    all_classes = sorted(CLASS_TO_REGIME.keys())
    rf_val_proba = predict_proba_all_classes(rf, X_val, all_classes)
    rf_test_proba = predict_proba_all_classes(rf, X_test, all_classes)
    calibration_grid = _parse_float_grid(args.rf_calibration_grid, low=0.05, high=5.0)
    best_multipliers, best_calibration = tune_class_multipliers(
        rf_val_proba,
        y_val.to_numpy(dtype=int),
        grid_values=calibration_grid,
    )
    rf_test_proba_cal = apply_class_multipliers(rf_test_proba, best_multipliers)

    # HMM train/test
    include_atr, include_adx, include_volume = _parse_hmm_extra_features(args.hmm_extra_features)
    hmm_feat = build_hmm_feature_frame_from_table(
        working,
        vol_window=args.hmm_vol_window,
        include_atr=include_atr,
        include_adx=include_adx,
        include_volume=include_volume,
    )
    hmm_feature_cols = list(hmm_feat.columns)
    hmm_train = hmm_feat.iloc[:train_end].dropna()
    hmm_test = hmm_feat.iloc[val_end:].dropna()
    if len(hmm_train) < 100 or len(hmm_test) < 30:
        raise ValueError("insufficient HMM train/test rows after warmup")

    hmm = GaussianHMM(
        n_components=args.hmm_components,
        covariance_type="diag",
        n_iter=args.hmm_iter,
        random_state=args.random_state,
    )
    hmm.fit(hmm_train[hmm_feature_cols].to_numpy(dtype=float))

    hmm_train_states = hmm.predict(hmm_train[hmm_feature_cols].to_numpy(dtype=float))
    hmm_train_y = y.iloc[hmm_train.index].to_numpy(dtype=int)
    state_dist = build_state_class_distribution(hmm_train_states, hmm_train_y, n_classes=len(all_classes))

    hmm_test_states = hmm.predict(hmm_test[hmm_feature_cols].to_numpy(dtype=float))
    hmm_test_proba = states_to_class_proba(hmm_test_states, state_dist, n_classes=len(all_classes))

    # Fair OOS comparison on common index subset
    rf_test_df = pd.DataFrame(rf_test_proba, index=X_test.index, columns=all_classes)
    hmm_test_df = pd.DataFrame(hmm_test_proba, index=hmm_test.index, columns=all_classes)
    common_idx = rf_test_df.index.intersection(hmm_test_df.index)
    if len(common_idx) < 30:
        raise ValueError("too few common OOS rows for ensemble")

    rf_common = rf_test_df.loc[common_idx].to_numpy(dtype=float)
    rf_test_cal_df = pd.DataFrame(rf_test_proba_cal, index=X_test.index, columns=all_classes)
    rf_common_cal = rf_test_cal_df.loc[common_idx].to_numpy(dtype=float)
    hmm_common = hmm_test_df.loc[common_idx].to_numpy(dtype=float)
    y_common = y.iloc[common_idx].to_numpy(dtype=int)

    ensemble_proba_raw = combine_probabilities(
        rf_common,
        hmm_common,
        rf_weight=args.rf_weight,
        hmm_weight=args.hmm_weight,
    )
    ensemble_pred_raw = ensemble_proba_raw.argmax(axis=1)

    ensemble_proba_cal = combine_probabilities(
        rf_common_cal,
        hmm_common,
        rf_weight=args.rf_weight,
        hmm_weight=args.hmm_weight,
    )
    ensemble_pred_cal = ensemble_proba_cal.argmax(axis=1)

    rf_common_pred_raw = rf_common.argmax(axis=1)
    rf_common_pred_cal = rf_common_cal.argmax(axis=1)
    hmm_common_pred = hmm_common.argmax(axis=1)

    metrics = {
        "rf": _metrics(y_common, rf_common_pred_raw),
        "rf_calibrated": _metrics(y_common, rf_common_pred_cal),
        "hmm": _metrics(y_common, hmm_common_pred),
        "ensemble": _metrics(y_common, ensemble_pred_raw),
        "ensemble_calibrated": _metrics(y_common, ensemble_pred_cal),
    }

    weight_sweep_rows: list[dict[str, float]] = []
    for rf_w in _parse_float_grid(args.weight_grid, low=0.0, high=1.0):
        hmm_w = 1.0 - rf_w
        ens_proba_w = combine_probabilities(
            rf_common_cal,
            hmm_common,
            rf_weight=rf_w,
            hmm_weight=hmm_w,
        )
        ens_pred_w = ens_proba_w.argmax(axis=1)
        m = _metrics(y_common, ens_pred_w)
        weight_sweep_rows.append(
            {
                "rf_weight": float(rf_w),
                "hmm_weight": float(hmm_w),
                "accuracy": float(m["accuracy"]),
                "macro_f1": float(m["macro_f1"]),
            }
        )

    hybrid_pred = apply_sideways_guard(
        rf_pred=rf_common_cal.argmax(axis=1),
        rf_proba=rf_common_cal,
        hmm_proba=hmm_common,
        sideways_class=1,
        conf_threshold=args.hybrid_conf_threshold,
        hmm_sideways_threshold=args.hybrid_sideways_threshold,
    )
    metrics["hybrid"] = _metrics(y_common, hybrid_pred)

    hybrid_sweep_rows: list[dict[str, float]] = []
    conf_grid = _parse_float_grid(args.hybrid_conf_grid, low=0.0, high=1.0)
    sideways_grid = _parse_float_grid(args.hybrid_sideways_grid, low=0.0, high=1.0)
    if conf_grid and sideways_grid:
        for conf_th in conf_grid:
            for side_th in sideways_grid:
                pred = apply_sideways_guard(
                    rf_pred=rf_common_cal.argmax(axis=1),
                    rf_proba=rf_common_cal,
                    hmm_proba=hmm_common,
                    sideways_class=1,
                    conf_threshold=conf_th,
                    hmm_sideways_threshold=side_th,
                )
                m = _metrics(y_common, pred)
                hybrid_sweep_rows.append(
                    {
                        "conf_threshold": float(conf_th),
                        "sideways_threshold": float(side_th),
                        "accuracy": float(m["accuracy"]),
                        "macro_f1": float(m["macro_f1"]),
                    }
                )

    labels = sorted(CLASS_TO_REGIME.keys())
    target_names = [CLASS_TO_REGIME[c] for c in labels]

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Save models/artifacts
    rf_model_path = output_dir / "rf_model.joblib"
    hmm_model_path = output_dir / "hmm_model.pkl"
    joblib.dump(rf, rf_model_path)
    with hmm_model_path.open("wb") as f:
        import pickle

        pickle.dump(hmm, f)

    # Save predictions table
    ts_series = pd.to_datetime(working.get("timestamp"), errors="coerce") if "timestamp" in working.columns else None
    pred_df = pd.DataFrame(
        {
            "index": common_idx,
            "timestamp": ts_series.iloc[common_idx].values if ts_series is not None else pd.NaT,
            "y_true": y_common,
            "rf_pred": rf_common_pred_raw,
            "rf_cal_pred": rf_common_pred_cal,
            "hmm_pred": hmm_common_pred,
            "ensemble_pred": ensemble_pred_raw,
            "ensemble_cal_pred": ensemble_pred_cal,
            "hybrid_pred": hybrid_pred,
        }
    )
    pred_df["y_true_label"] = pred_df["y_true"].map(CLASS_TO_REGIME)
    pred_df["rf_label"] = pred_df["rf_pred"].map(CLASS_TO_REGIME)
    pred_df["rf_cal_label"] = pred_df["rf_cal_pred"].map(CLASS_TO_REGIME)
    pred_df["hmm_label"] = pred_df["hmm_pred"].map(CLASS_TO_REGIME)
    pred_df["ensemble_label"] = pred_df["ensemble_pred"].map(CLASS_TO_REGIME)
    pred_df["ensemble_cal_label"] = pred_df["ensemble_cal_pred"].map(CLASS_TO_REGIME)
    pred_df["hybrid_label"] = pred_df["hybrid_pred"].map(CLASS_TO_REGIME)
    pred_path = output_dir / "oos_predictions.csv"
    pred_df.to_csv(pred_path, index=False)

    # Save metadata/metrics
    report = {
        "dataset": str(dataset_path),
        "rows_total": int(len(X)),
        "train_end": int(train_end),
        "val_end": int(val_end),
        "oos_rows_common": int(len(common_idx)),
        "features": features,
        "params": {
            "forward_horizon": args.forward_horizon,
            "bull_threshold": args.bull_threshold,
            "bear_threshold": args.bear_threshold,
            "train_ratio": args.train_ratio,
            "val_ratio": args.val_ratio,
            "rf_weight": args.rf_weight,
            "hmm_weight": args.hmm_weight,
            "rf_calibration_grid": args.rf_calibration_grid,
            "rf_n_estimators": args.rf_n_estimators,
            "rf_max_depth": args.rf_max_depth,
            "hmm_components": args.hmm_components,
            "hmm_iter": args.hmm_iter,
            "hmm_vol_window": args.hmm_vol_window,
            "hmm_extra_features": args.hmm_extra_features,
            "hybrid_conf_threshold": args.hybrid_conf_threshold,
            "hybrid_sideways_threshold": args.hybrid_sideways_threshold,
            "random_state": args.random_state,
        },
        "rf_calibration": {
            "best_multipliers": [float(x) for x in best_multipliers.tolist()],
            "val_metrics": best_calibration,
        },
        "hmm_feature_columns": hmm_feature_cols,
        "metrics": metrics,
        "weight_sweep": weight_sweep_rows,
        "hybrid_sweep": hybrid_sweep_rows,
        "hmm_state_class_distribution": {
            str(state): {str(i): float(p) for i, p in enumerate(probs)}
            for state, probs in state_dist.items()
        },
        "classification_report": {
            "rf": classification_report(
                y_common,
                rf_common_pred_raw,
                labels=labels,
                target_names=target_names,
                digits=4,
                zero_division=0,
                output_dict=True,
            ),
            "rf_calibrated": classification_report(
                y_common,
                rf_common_pred_cal,
                labels=labels,
                target_names=target_names,
                digits=4,
                zero_division=0,
                output_dict=True,
            ),
            "hmm": classification_report(
                y_common,
                hmm_common_pred,
                labels=labels,
                target_names=target_names,
                digits=4,
                zero_division=0,
                output_dict=True,
            ),
            "ensemble": classification_report(
                y_common,
                ensemble_pred_raw,
                labels=labels,
                target_names=target_names,
                digits=4,
                zero_division=0,
                output_dict=True,
            ),
            "ensemble_calibrated": classification_report(
                y_common,
                ensemble_pred_cal,
                labels=labels,
                target_names=target_names,
                digits=4,
                zero_division=0,
                output_dict=True,
            ),
            "hybrid": classification_report(
                y_common,
                hybrid_pred,
                labels=labels,
                target_names=target_names,
                digits=4,
                zero_division=0,
                output_dict=True,
            ),
        },
    }

    report_path = output_dir / "metrics.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    if weight_sweep_rows:
        sweep_df = pd.DataFrame(weight_sweep_rows).sort_values(
            by=["macro_f1", "accuracy"],
            ascending=[False, False],
        )
        sweep_path = output_dir / "weight_sweep.csv"
        sweep_df.to_csv(sweep_path, index=False)
        best = sweep_df.iloc[0]
        print(
            "Weight sweep best - "
            f"rf_weight={best['rf_weight']:.2f}, hmm_weight={best['hmm_weight']:.2f}, "
            f"accuracy={best['accuracy']:.4f}, macro_f1={best['macro_f1']:.4f}"
        )
        print(f"Saved: {sweep_path}")

    if hybrid_sweep_rows:
        hybrid_df = pd.DataFrame(hybrid_sweep_rows).sort_values(
            by=["macro_f1", "accuracy"],
            ascending=[False, False],
        )
        hybrid_path = output_dir / "hybrid_guard_sweep.csv"
        hybrid_df.to_csv(hybrid_path, index=False)
        best_h = hybrid_df.iloc[0]
        print(
            "Hybrid sweep best - "
            f"conf={best_h['conf_threshold']:.2f}, sideways={best_h['sideways_threshold']:.2f}, "
            f"accuracy={best_h['accuracy']:.4f}, macro_f1={best_h['macro_f1']:.4f}"
        )
        print(f"Saved: {hybrid_path}")

    print(f"OOS rows (common): {len(common_idx)}")
    print(f"RF      - accuracy={metrics['rf']['accuracy']:.4f}, macro_f1={metrics['rf']['macro_f1']:.4f}")
    print(
        "RF(cal) - "
        f"accuracy={metrics['rf_calibrated']['accuracy']:.4f}, "
        f"macro_f1={metrics['rf_calibrated']['macro_f1']:.4f}, "
        f"mult={ [round(float(x),3) for x in best_multipliers.tolist()] }"
    )
    print(f"HMM     - accuracy={metrics['hmm']['accuracy']:.4f}, macro_f1={metrics['hmm']['macro_f1']:.4f}")
    print(f"Ensemble- accuracy={metrics['ensemble']['accuracy']:.4f}, macro_f1={metrics['ensemble']['macro_f1']:.4f}")
    print(
        "Ens(cal)- "
        f"accuracy={metrics['ensemble_calibrated']['accuracy']:.4f}, "
        f"macro_f1={metrics['ensemble_calibrated']['macro_f1']:.4f}"
    )
    print(f"Hybrid  - accuracy={metrics['hybrid']['accuracy']:.4f}, macro_f1={metrics['hybrid']['macro_f1']:.4f}")
    print(f"Saved: {rf_model_path}")
    print(f"Saved: {hmm_model_path}")
    print(f"Saved: {pred_path}")
    print(f"Saved: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
