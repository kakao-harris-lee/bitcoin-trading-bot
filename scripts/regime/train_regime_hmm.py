#!/usr/bin/env python3
"""Train Gaussian HMM for unsupervised regime inference.

Requires optional dependency: hmmlearn
  pip install hmmlearn
"""
from __future__ import annotations

import argparse
import json
import pickle
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from trading.regime.ensemble import build_hmm_feature_frame_from_table


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train Gaussian HMM regime model.")
    parser.add_argument("--dataset", required=True, help="Input feature table (.csv/.parquet)")
    parser.add_argument("--output-dir", required=True, help="Output directory for model artifacts")
    parser.add_argument("--n-components", type=int, default=3, help="Number of hidden states")
    parser.add_argument("--n-iter", type=int, default=200, help="EM iterations")
    parser.add_argument("--random-state", type=int, default=42)
    parser.add_argument("--vol-window", type=int, default=24)
    parser.add_argument("--close-column", default="close")
    parser.add_argument(
        "--extra-features",
        default="atr,adx,volume",
        help="Comma-separated extra features from table: atr,adx,volume (empty for base-only).",
    )
    return parser.parse_args()


def _read_frame(path: Path) -> pd.DataFrame:
    if path.suffix.lower() == ".parquet":
        return pd.read_parquet(path)
    return pd.read_csv(path)


def _parse_extra_features(raw: str) -> tuple[bool, bool, bool]:
    tokens = {t.strip().lower() for t in raw.split(",") if t.strip()}
    if not tokens:
        return False, False, False
    allowed = {"atr", "adx", "volume"}
    unknown = sorted(tokens - allowed)
    if unknown:
        raise ValueError(f"unsupported extra features: {unknown}")
    return ("atr" in tokens), ("adx" in tokens), ("volume" in tokens)


def main() -> int:
    args = parse_args()

    dataset_path = Path(args.dataset)
    if not dataset_path.exists():
        raise FileNotFoundError(f"dataset not found: {dataset_path}")

    try:
        from hmmlearn.hmm import GaussianHMM
    except Exception as exc:
        raise RuntimeError(
            "hmmlearn is required for HMM training. Install via: pip install hmmlearn"
        ) from exc

    df = _read_frame(dataset_path)
    include_atr, include_adx, include_volume = _parse_extra_features(args.extra_features)
    feat = build_hmm_feature_frame_from_table(
        df,
        close_column=args.close_column,
        vol_window=args.vol_window,
        include_atr=include_atr,
        include_adx=include_adx,
        include_volume=include_volume,
    ).dropna()
    feature_columns = list(feat.columns)
    X = feat[feature_columns].to_numpy(dtype=float)

    if len(X) < 100:
        raise ValueError("insufficient rows for HMM training (need >= 100)")

    model = GaussianHMM(
        n_components=args.n_components,
        covariance_type="diag",
        n_iter=args.n_iter,
        random_state=args.random_state,
    )
    model.fit(X)
    states = model.predict(X)

    tmp = feat.copy()
    tmp["state"] = states
    state_stats = (
        tmp.groupby("state")["log_return"]
        .agg(["mean", "std", "count"])
        .sort_values("mean")
    )

    ordered_states = list(state_stats.index)
    label_map: dict[int, str] = {}
    if ordered_states:
        label_map[int(ordered_states[0])] = "BEAR"
        label_map[int(ordered_states[-1])] = "BULL"
    for s in ordered_states[1:-1]:
        label_map[int(s)] = "SIDEWAYS"

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    model_path = output_dir / "regime_hmm.pkl"
    meta_path = output_dir / "metadata.json"

    with model_path.open("wb") as f:
        pickle.dump(model, f)

    metadata = {
        "model_type": "GaussianHMM",
        "dataset": str(dataset_path),
        "features": feature_columns,
        "rows": int(len(feat)),
        "n_components": args.n_components,
        "n_iter": args.n_iter,
        "random_state": args.random_state,
        "extra_features": args.extra_features,
        "state_label_map": {str(k): v for k, v in label_map.items()},
        "state_stats": {
            str(state): {
                "mean": float(row["mean"]),
                "std": float(row["std"]),
                "count": int(row["count"]),
            }
            for state, row in state_stats.iterrows()
        },
    }
    meta_path.write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"Saved model: {model_path}")
    print(f"Saved metadata: {meta_path}")
    print("State stats:")
    print(state_stats)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
