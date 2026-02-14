#!/usr/bin/env python3
"""Optimize RegimeLong v2 portfolio with BTC/SOL caps + BNB momentum overlay.

Purpose:
- Build a portfolio layer on top of per-symbol RegimeLong v2 signals.
- Enforce conservative caps on BTC/SOL allocation.
- Add BNB momentum overlay to increase upside capture.
- Evaluate against equal-weight B&H baseline and matched-weight B&H.
"""

from __future__ import annotations

import argparse
import itertools
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.backtest._common import compute_metrics, load_data
from scripts.backtest.compare_regime_long_only_v1 import (
    ASSET_DB,
    RegimeParams,
    _to_daily,
    run_regime_long_only,
)
from trading.strategies.indicators import calculate_adx, calculate_mfi


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Optimize portfolio for RegimeLong v2 with BNB overlay",
    )
    parser.add_argument("--start-date", default="2021-01-01")
    parser.add_argument("--end-date", default="2026-02-13")
    parser.add_argument("--symbols", nargs="+", default=["BTC", "ETH", "SOL", "BNB"])
    parser.add_argument("--capital", type=float, default=10_000.0)
    parser.add_argument("--output-dir", default="reports")
    parser.add_argument("--top-k", type=int, default=20)
    parser.add_argument("--fee-rate", type=float, default=0.001)
    parser.add_argument(
        "--overlay-signal",
        choices=["live_like", "momentum"],
        default="live_like",
        help=(
            "live_like: use MFI/ADX/EMA200 gate (same shape as runtime switch); "
            "momentum: use EMA20+20d momentum gate."
        ),
    )
    parser.add_argument(
        "--selection-mode",
        choices=["robust", "ew_only"],
        default="robust",
        help=(
            "robust: require alpha_vs_matched_bnh_pctp >= 0 for best selection; "
            "ew_only: select purely by alpha_vs_ew_bnh_pctp."
        ),
    )
    return parser.parse_args()


def _load_daily_data(symbols: list[str], start_date: str, end_date: str) -> dict[str, pd.DataFrame]:
    out: dict[str, pd.DataFrame] = {}
    for symbol in symbols:
        db_path = ASSET_DB.get(symbol)
        if db_path is None or not db_path.exists():
            continue
        df_4h = load_data(
            db_path=str(db_path),
            timeframe="minute240",
            start_date=start_date,
            end_date=end_date,
            exchange="binance",
        )
        if df_4h.empty:
            continue
        daily = _to_daily(df_4h)
        if len(daily) < 250:
            continue
        out[symbol] = daily
    return out


def _merge_symbol_frames(frames: dict[str, pd.DataFrame], symbols: list[str]) -> pd.DataFrame:
    merged: pd.DataFrame | None = None
    for symbol in symbols:
        df = frames.get(symbol)
        if df is None or df.empty:
            continue
        part = df[["timestamp", symbol]].copy()
        merged = part if merged is None else merged.merge(part, on="timestamp", how="inner")
    if merged is None:
        return pd.DataFrame()
    return merged.sort_values("timestamp").reset_index(drop=True)


def _build_weighted_returns(returns_df: pd.DataFrame, weights: dict[str, float]) -> pd.Series:
    cols = [c for c in returns_df.columns if c != "timestamp" and c in weights]
    if not cols:
        return pd.Series(dtype=float)
    out = pd.Series(0.0, index=returns_df.index)
    for c in cols:
        out += returns_df[c].fillna(0.0) * float(weights[c])
    return out


def _normalize_weights(w: dict[str, float]) -> dict[str, float]:
    total = sum(max(0.0, float(v)) for v in w.values())
    if total <= 0:
        n = max(len(w), 1)
        return {k: 1.0 / n for k in w}
    return {k: max(0.0, float(v)) / total for k, v in w.items()}


def _overlay_bnb_weight(
    base_w: dict[str, float],
    boost: float,
    bnb_signal: bool,
) -> dict[str, float]:
    w = dict(base_w)
    if not bnb_signal or boost <= 0:
        return _normalize_weights(w)

    # Increase BNB weight by boost, fund from SOL -> BTC -> ETH.
    w["BNB"] = w.get("BNB", 0.0) + boost
    need = boost
    for donor in ("SOL", "BTC", "ETH"):
        give = min(w.get(donor, 0.0), need)
        w[donor] = w.get(donor, 0.0) - give
        need -= give
        if need <= 1e-12:
            break

    return _normalize_weights(w)


def _daily_equity_from_returns(
    timestamps: pd.Series,
    returns: pd.Series,
    capital: float,
) -> pd.DataFrame:
    eq = [capital]
    for r in returns.fillna(0.0).iloc[1:]:
        eq.append(eq[-1] * (1.0 + float(r)))
    return pd.DataFrame({"timestamp": timestamps, "total_equity": eq})


def _make_bnb_signal_momentum(daily_bnb: pd.DataFrame) -> pd.Series:
    close = daily_bnb["close"].astype(float)
    ema20 = close.ewm(span=20, adjust=False).mean()
    mom20 = close.pct_change(20)
    signal = (close > ema20) & (mom20 > 0.0)
    return pd.Series(signal.values, index=daily_bnb["timestamp"])


def _make_bnb_signal_live_like(
    daily_bnb: pd.DataFrame,
    mfi_threshold: float = 52.0,
    adx_threshold: float = 18.0,
    require_above_ema200: bool = True,
) -> pd.Series:
    """Build BNB overlay signal with runtime-switch-like conditions.

    Runtime switch shape in live:
    - MFI >= switch_mfi_threshold
    - ADX >= switch_adx_threshold
    - close >= EMA200 (if enabled)
    """
    df = daily_bnb.copy().reset_index(drop=True)
    close = df["close"].astype(float)
    ema200 = close.ewm(span=200, adjust=False).mean()

    highs = df["high"].astype(float).to_numpy()
    lows = df["low"].astype(float).to_numpy()
    closes = close.to_numpy()
    volumes = df["volume"].astype(float).to_numpy()

    signals: list[bool] = []
    for i in range(len(df)):
        # Need enough history for ADX/MFI stability.
        if i < 40:
            signals.append(False)
            continue
        h = highs[: i + 1]
        l = lows[: i + 1]
        c = closes[: i + 1]
        v = volumes[: i + 1]
        mfi = float(calculate_mfi(h, l, c, v, period=14))
        adx = float(calculate_adx(h, l, c, period=14))
        ok = (mfi >= mfi_threshold) and (adx >= adx_threshold)
        if require_above_ema200:
            ok = ok and (closes[i] >= float(ema200.iloc[i]))
        signals.append(bool(ok))

    return pd.Series(signals, index=df["timestamp"])


def _grid() -> list[dict[str, Any]]:
    # BTC/SOL caps are hard constraints by candidate choices.
    btc_w = [0.10, 0.15, 0.20, 0.25]
    sol_w = [0.00, 0.05, 0.10]
    bnb_w = [0.40, 0.50, 0.60, 0.70]
    boost = [0.00, 0.05, 0.10, 0.15]
    out: list[dict[str, Any]] = []
    for b, s, n, o in itertools.product(btc_w, sol_w, bnb_w, boost):
        eth = 1.0 - (b + s + n)
        if eth < 0.05 or eth > 0.50:
            continue
        out.append(
            {
                "btc_w": b,
                "eth_w": eth,
                "sol_w": s,
                "bnb_w": n,
                "bnb_overlay_boost": o,
            }
        )
    return out


def main() -> int:
    args = parse_args()
    symbols = [s.upper() for s in args.symbols]
    daily_by_symbol = _load_daily_data(symbols, args.start_date, args.end_date)
    needed = {"BTC", "ETH", "SOL", "BNB"}
    if not needed.issubset(set(daily_by_symbol.keys())):
        print(f"Missing symbols for v3: {sorted(needed - set(daily_by_symbol.keys()))}")
        return 1

    p = RegimeParams(
        entry_lookback_days=4,
        entry_quorum=3,
        drop_1d_pct=-0.07,
        drop_3d_pct=-0.10,
        peak_dd_exit_pct=0.15,
        cooldown_days=5,
        fee_rate=args.fee_rate,
    )

    # Build per-symbol strategy and B&H returns.
    strat_frames: dict[str, pd.DataFrame] = {}
    bnh_frames: dict[str, pd.DataFrame] = {}
    for symbol, daily in daily_by_symbol.items():
        strat = run_regime_long_only(daily=daily, capital=args.capital, p=p)
        eq = strat["equity_curve"][["timestamp", "total_equity"]].copy()
        eq[symbol] = eq["total_equity"].pct_change().fillna(0.0)
        strat_frames[symbol] = eq[["timestamp", symbol]]

        b = daily[["timestamp", "close"]].copy()
        b[symbol] = b["close"].pct_change().fillna(0.0)
        bnh_frames[symbol] = b[["timestamp", symbol]]

    core_symbols = ["BTC", "ETH", "SOL", "BNB"]
    strat_ret = _merge_symbol_frames(strat_frames, core_symbols)
    bnh_ret = _merge_symbol_frames(bnh_frames, core_symbols)

    # Align both on same timestamps.
    merged = strat_ret.merge(bnh_ret, on="timestamp", suffixes=("_strat", "_bnh"), how="inner")
    merged = merged.sort_values("timestamp").reset_index(drop=True)
    if merged.empty:
        print("No overlapping timestamps for portfolio optimization.")
        return 1

    # Build columns.
    strat_cols = {s: f"{s}_strat" for s in ("BTC", "ETH", "SOL", "BNB")}
    bnh_cols = {s: f"{s}_bnh" for s in ("BTC", "ETH", "SOL", "BNB")}

    # Equal-weight B&H baseline (fixed).
    ew_w = {"BTC": 0.25, "ETH": 0.25, "SOL": 0.25, "BNB": 0.25}
    ew_bnh_ret = pd.Series(0.0, index=merged.index)
    for s in ew_w:
        ew_bnh_ret += merged[bnh_cols[s]].fillna(0.0) * ew_w[s]
    ew_bnh_eq = _daily_equity_from_returns(merged["timestamp"], ew_bnh_ret, args.capital)
    ew_bnh_metrics = compute_metrics(ew_bnh_eq, timeframe="day")
    ew_bnh_total = float(ew_bnh_metrics["total_return"])

    # BNB overlay signal.
    if args.overlay_signal == "momentum":
        bnb_signal_raw = _make_bnb_signal_momentum(daily_by_symbol["BNB"])
    else:
        bnb_signal_raw = _make_bnb_signal_live_like(daily_by_symbol["BNB"])
    bnb_signal = merged["timestamp"].map(lambda t: bool(bnb_signal_raw.get(t, False)))

    trials: list[dict[str, Any]] = []
    grid = _grid()
    for idx, params in enumerate(grid, 1):
        base_w = _normalize_weights(
            {
                "BTC": float(params["btc_w"]),
                "ETH": float(params["eth_w"]),
                "SOL": float(params["sol_w"]),
                "BNB": float(params["bnb_w"]),
            }
        )
        boost = float(params["bnb_overlay_boost"])

        strat_port_ret = []
        bnh_port_ret = []
        for i, row in merged.iterrows():
            w = _overlay_bnb_weight(base_w, boost, bool(bnb_signal.iloc[i]))
            sr = sum(float(row[strat_cols[s]]) * w[s] for s in w)
            br = sum(float(row[bnh_cols[s]]) * w[s] for s in w)
            strat_port_ret.append(sr)
            bnh_port_ret.append(br)

        strat_port_ret = pd.Series(strat_port_ret)
        bnh_port_ret = pd.Series(bnh_port_ret)

        strat_eq = _daily_equity_from_returns(merged["timestamp"], strat_port_ret, args.capital)
        bnh_eq = _daily_equity_from_returns(merged["timestamp"], bnh_port_ret, args.capital)

        strat_m = compute_metrics(strat_eq, timeframe="day")
        bnh_m = compute_metrics(bnh_eq, timeframe="day")
        alpha_vs_ew_bnh = float(strat_m["total_return"] - ew_bnh_total)
        alpha_vs_matched_bnh = float(strat_m["total_return"] - bnh_m["total_return"])

        trials.append(
            {
                "trial": idx,
                **params,
                "strat_return_pct": float(strat_m["total_return"]),
                "strat_cagr_pct": float(strat_m["cagr"]),
                "strat_mdd_pct": abs(float(strat_m["mdd"])),
                "strat_sharpe": float(strat_m["sharpe"]),
                "matched_bnh_return_pct": float(bnh_m["total_return"]),
                "ew_bnh_return_pct": ew_bnh_total,
                "alpha_vs_matched_bnh_pctp": alpha_vs_matched_bnh,
                "alpha_vs_ew_bnh_pctp": alpha_vs_ew_bnh,
            }
        )

    ranking = pd.DataFrame(trials).sort_values(
        by=["alpha_vs_ew_bnh_pctp", "strat_return_pct", "strat_sharpe"],
        ascending=[False, False, False],
    )
    top = ranking.head(args.top_k).copy()
    best_ew = top.iloc[0].to_dict()

    robust_pool = ranking[ranking["alpha_vs_matched_bnh_pctp"] >= 0].copy()
    if args.selection_mode == "robust":
        if not robust_pool.empty:
            selected = robust_pool.sort_values(
                by=["alpha_vs_ew_bnh_pctp", "strat_return_pct", "strat_sharpe"],
                ascending=[False, False, False],
            ).iloc[0].to_dict()
        else:
            selected = best_ew
    else:
        selected = best_ew

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = PROJECT_ROOT / args.output_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / f"regime_portfolio_v3_opt_{ts}.csv"
    json_path = out_dir / f"regime_portfolio_v3_opt_{ts}.json"
    md_path = out_dir / f"regime_portfolio_v3_opt_{ts}.md"
    tuned_path = PROJECT_ROOT / "config" / "tuned" / f"regime_portfolio_v3_best_{ts}.json"
    tuned_path.parent.mkdir(parents=True, exist_ok=True)

    top.to_csv(csv_path, index=False)
    payload = {
        "generated_at": datetime.now().isoformat(),
        "start_date": args.start_date,
        "end_date": args.end_date,
        "symbols": ["BTC", "ETH", "SOL", "BNB"],
        "base_strategy_params": p.__dict__,
        "objective": "maximize alpha_vs_ew_bnh_pctp",
        "selection_mode": args.selection_mode,
        "overlay_signal": args.overlay_signal,
        "search_space_size": len(grid),
        "ew_bnh_return_pct": ew_bnh_total,
        "best_trial_selected": selected,
        "best_trial_ew_only": best_ew,
        "robust_candidate_count": int(len(robust_pool)),
        "top_trials": top.to_dict(orient="records"),
    }
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tuned_path.write_text(
        json.dumps(
            {
                "meta": {
                    "generated_at": datetime.now().isoformat(),
                    "source_report": str(json_path.relative_to(PROJECT_ROOT)),
                    "objective": payload["objective"],
                },
                "portfolio_params": {
                    "btc_w": selected["btc_w"],
                    "eth_w": selected["eth_w"],
                    "sol_w": selected["sol_w"],
                    "bnb_w": selected["bnb_w"],
                    "bnb_overlay_boost": selected["bnb_overlay_boost"],
                },
                "performance": {
                    "strat_return_pct": selected["strat_return_pct"],
                    "strat_cagr_pct": selected["strat_cagr_pct"],
                    "strat_mdd_pct": selected["strat_mdd_pct"],
                    "strat_sharpe": selected["strat_sharpe"],
                    "matched_bnh_return_pct": selected["matched_bnh_return_pct"],
                    "ew_bnh_return_pct": selected["ew_bnh_return_pct"],
                    "alpha_vs_matched_bnh_pctp": selected["alpha_vs_matched_bnh_pctp"],
                    "alpha_vs_ew_bnh_pctp": selected["alpha_vs_ew_bnh_pctp"],
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    lines: list[str] = []
    lines.append("# Regime Portfolio v3 Optimization")
    lines.append("")
    lines.append(f"- Generated: {payload['generated_at']}")
    lines.append(f"- Period: {args.start_date} to {args.end_date}")
    lines.append(f"- Search space: {len(grid)}")
    lines.append(f"- Selection mode: {args.selection_mode}")
    lines.append(f"- Overlay signal: {args.overlay_signal}")
    lines.append(f"- Robust candidate count (alpha vs matched B&H >= 0): {len(robust_pool)}")
    lines.append(f"- Equal-weight B&H return: {ew_bnh_total:.2f}%")
    lines.append("")
    lines.append("## Selected Best Trial")
    lines.append("")
    lines.append(
        f"- Weights: BTC={selected['btc_w']:.2f}, ETH={selected['eth_w']:.2f}, "
        f"SOL={selected['sol_w']:.2f}, BNB={selected['bnb_w']:.2f}"
    )
    lines.append(f"- BNB overlay boost: {selected['bnb_overlay_boost']:.2f}")
    lines.append(
        f"- Strat return={selected['strat_return_pct']:.2f}%, MDD={selected['strat_mdd_pct']:.2f}%, "
        f"Sharpe={selected['strat_sharpe']:.2f}"
    )
    lines.append(
        f"- Alpha vs EW B&H={selected['alpha_vs_ew_bnh_pctp']:.2f}%p, "
        f"Alpha vs matched B&H={selected['alpha_vs_matched_bnh_pctp']:.2f}%p"
    )
    lines.append("")
    lines.append("## EW-Only Best (Reference)")
    lines.append("")
    lines.append(
        f"- Weights: BTC={best_ew['btc_w']:.2f}, ETH={best_ew['eth_w']:.2f}, "
        f"SOL={best_ew['sol_w']:.2f}, BNB={best_ew['bnb_w']:.2f}"
    )
    lines.append(f"- BNB overlay boost: {best_ew['bnb_overlay_boost']:.2f}")
    lines.append(
        f"- Alpha vs EW B&H={best_ew['alpha_vs_ew_bnh_pctp']:.2f}%p, "
        f"Alpha vs matched B&H={best_ew['alpha_vs_matched_bnh_pctp']:.2f}%p"
    )
    lines.append("")
    lines.append("## Top Trials")
    lines.append("")
    lines.append("| Trial | BTC | ETH | SOL | BNB | Overlay | Strat Ret % | MDD % | Sharpe | Alpha vs EW B&H %p | Alpha vs Matched B&H %p |")
    lines.append("|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for _, r in top.iterrows():
        lines.append(
            f"| {int(r['trial'])} | {r['btc_w']:.2f} | {r['eth_w']:.2f} | {r['sol_w']:.2f} | "
            f"{r['bnb_w']:.2f} | {r['bnb_overlay_boost']:.2f} | {r['strat_return_pct']:.2f} | "
            f"{r['strat_mdd_pct']:.2f} | {r['strat_sharpe']:.2f} | "
            f"{r['alpha_vs_ew_bnh_pctp']:.2f} | {r['alpha_vs_matched_bnh_pctp']:.2f} |"
        )
    md_path.write_text("\n".join(lines), encoding="utf-8")

    print(f"Saved: {csv_path}")
    print(f"Saved: {json_path}")
    print(f"Saved: {md_path}")
    print(f"Saved: {tuned_path}")
    print(
        "Selected best: "
        f"ret={selected['strat_return_pct']:.2f}% alpha_vs_ew={selected['alpha_vs_ew_bnh_pctp']:.2f}%p "
        f"alpha_vs_matched={selected['alpha_vs_matched_bnh_pctp']:.2f}%p "
        f"weights=({selected['btc_w']:.2f},{selected['eth_w']:.2f},{selected['sol_w']:.2f},{selected['bnb_w']:.2f}) "
        f"overlay={selected['bnb_overlay_boost']:.2f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
