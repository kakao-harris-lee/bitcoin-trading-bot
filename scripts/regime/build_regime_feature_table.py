#!/usr/bin/env python3
"""Build multimodal regime feature table from local CSV files."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from trading.regime.feature_table import build_regime_feature_table


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build regime feature table from local data sources."
    )
    parser.add_argument("--price-csv", required=True, help="Path to price/indicator CSV.")
    parser.add_argument("--onchain-csv", default="", help="Optional on-chain CSV.")
    parser.add_argument("--sentiment-csv", default="", help="Optional sentiment CSV.")
    parser.add_argument("--derivatives-csv", default="", help="Optional derivatives CSV.")
    parser.add_argument("--policy-csv", default="", help="Optional policy/event CSV.")
    parser.add_argument("--join-tolerance", default="4h", help="Asof merge tolerance (default: 4h).")
    parser.add_argument("--vol-jump-window", type=int, default=48)
    parser.add_argument("--vol-jump-z", type=float, default=2.0)
    parser.add_argument("--output", required=True, help="Output file (.csv or .parquet).")
    return parser.parse_args()


def _read_optional_csv(path: str) -> pd.DataFrame | None:
    if not path:
        return None
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"CSV not found: {path}")
    return pd.read_csv(p)


def main() -> int:
    args = parse_args()
    price_df = pd.read_csv(args.price_csv)
    onchain_df = _read_optional_csv(args.onchain_csv)
    sentiment_df = _read_optional_csv(args.sentiment_csv)
    derivatives_df = _read_optional_csv(args.derivatives_csv)
    policy_df = _read_optional_csv(args.policy_csv)

    table = build_regime_feature_table(
        price_df=price_df,
        onchain_df=onchain_df,
        sentiment_df=sentiment_df,
        derivatives_df=derivatives_df,
        policy_df=policy_df,
        join_tolerance=args.join_tolerance,
        vol_jump_window=args.vol_jump_window,
        vol_jump_z=args.vol_jump_z,
    )

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.suffix.lower() == ".parquet":
        table.to_parquet(out, index=False)
    else:
        table.to_csv(out, index=False)

    print(f"Rows: {len(table)}")
    print(f"Columns: {len(table.columns)}")
    print(f"Output: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
