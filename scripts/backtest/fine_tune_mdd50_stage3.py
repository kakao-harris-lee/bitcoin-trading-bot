#!/usr/bin/env python3
"""Fine-tune stage3 profile under MDD cap.

Goal:
- Maximize mean return across symbols
- Subject to mean MDD <= mdd_cap
"""

from __future__ import annotations

import argparse
import copy
import itertools
import json
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.backtest._common import load_data  # noqa: E402
from scripts.backtest.backtest_mlp import MLPDirectionBacktester, load_strategy_config  # noqa: E402
try:
    from scripts.backtest.compare_three_stage_improvements import (  # noqa: E402
        _apply_stage1_trend_capture,
        _apply_stage2_horizon_objective,
        _apply_stage3_beta_schedule,
    )
except ImportError:
    def _apply_stage1_trend_capture(cfg: dict[str, Any]) -> dict[str, Any]:
        return copy.deepcopy(cfg)

    def _apply_stage2_horizon_objective(cfg: dict[str, Any]) -> dict[str, Any]:
        return copy.deepcopy(cfg)

    def _apply_stage3_beta_schedule(cfg: dict[str, Any]) -> dict[str, Any]:
        return copy.deepcopy(cfg)


@dataclass
class TrialResult:
    trial_id: str
    symbol: str
    return_pct: float
    alpha_pct: float
    mdd_pct: float
    trades: int
    win_rate_pct: float
    params: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "trial_id": self.trial_id,
            "symbol": self.symbol,
            "return_pct": self.return_pct,
            "alpha_pct": self.alpha_pct,
            "mdd_pct": self.mdd_pct,
            "trades": self.trades,
            "win_rate_pct": self.win_rate_pct,
            "params": self.params,
        }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fine-tune stage3 profile under MDD cap.")
    parser.add_argument("--symbols", nargs="+", default=["BTC", "ETH", "SOL", "BNB"])
    parser.add_argument("--start-date", default="2020-01-01")
    parser.add_argument("--end-date", default="2026-02-13")
    parser.add_argument("--timeframe", default="minute240")
    parser.add_argument("--mode", choices=["paper", "live"], default="paper")
    parser.add_argument("--config", default="config/strategies/allocation.json")
    parser.add_argument("--capital", type=float, default=10_000.0)
    parser.add_argument("--mdd-cap", type=float, default=50.0)
    parser.add_argument("--output-dir", default="reports")
    return parser.parse_args()


def _db_path_for_symbol(symbol: str) -> str:
    mapping = {
        "BTC": "binance_bitcoin.db",
        "ETH": "binance_ethereum.db",
        "SOL": "binance_solana.db",
        "BNB": "binance_bnb.db",
    }
    return str(PROJECT_ROOT / "data" / mapping[symbol])


def _build_stage3_base(base_cfg: dict[str, Any]) -> dict[str, Any]:
    return _apply_stage3_beta_schedule(
        _apply_stage2_horizon_objective(
            _apply_stage1_trend_capture(base_cfg)
        )
    )


def _make_trial_configs(stage3_cfg: dict[str, Any]) -> list[tuple[str, dict[str, Any], dict[str, Any]]]:
    trials: list[tuple[str, dict[str, Any], dict[str, Any]]] = []

    pos_scales = [0.90, 1.00, 1.10]
    stop_losses = [9.0, 10.0]
    trailing_profiles = {
        "default": {"activation": 18.0, "distance": 10.0},
        "trend": {"activation": 14.0, "distance": 7.0},
    }
    period_modes = ["on", "off"]

    for pos_scale, stop_loss, trail_name, period_mode in itertools.product(
        pos_scales,
        stop_losses,
        trailing_profiles.keys(),
        period_modes,
    ):
        cfg = copy.deepcopy(stage3_cfg)
        ep = cfg.setdefault("entry", {}).setdefault("params", {})
        xp = cfg.setdefault("exit", {}).setdefault("params", {})

        # Position intensity scaling
        ep["position_size"] = float(ep.get("position_size", 0.55)) * pos_scale
        ep["risk_on_position_size"] = float(ep.get("risk_on_position_size", 0.95)) * pos_scale
        ep["risk_off_position_size"] = float(ep.get("risk_off_position_size", 0.30)) * pos_scale

        # Cap to avoid invalid over-1 fractions
        ep["position_size"] = min(ep["position_size"], 1.0)
        ep["risk_on_position_size"] = min(ep["risk_on_position_size"], 1.0)
        ep["risk_off_position_size"] = min(ep["risk_off_position_size"], 1.0)

        # Exit behavior
        xp["stop_loss_pct"] = stop_loss
        xp["trailing_enabled"] = True
        xp["trailing_activation"] = trailing_profiles[trail_name]["activation"]
        xp["trailing_distance"] = trailing_profiles[trail_name]["distance"]

        # Period guard toggle
        if period_mode == "off":
            ep["period_risk_enabled"] = False
            ep.pop("period_reduce_threshold_pct", None)
            ep.pop("period_reduce_scale", None)
            ep.pop("period_loss_limit_pct", None)
            cfg["period_risk_enabled"] = False
            cfg.pop("period_reduce_threshold_pct", None)
            cfg.pop("period_reduce_scale", None)
            cfg.pop("period_loss_limit_pct", None)
        else:
            ep["period_risk_enabled"] = True
            ep["period_reduce_threshold_pct"] = 3.0
            ep["period_reduce_scale"] = 0.60
            ep["period_loss_limit_pct"] = 4.0
            cfg["period_risk_enabled"] = True
            cfg["period_reduce_threshold_pct"] = 3.0
            cfg["period_reduce_scale"] = 0.60
            cfg["period_loss_limit_pct"] = 4.0

        trial_id = (
            f"ps{pos_scale:.2f}_sl{stop_loss:.1f}_tr{trail_name}_pr{period_mode}"
        )
        params = {
            "pos_scale": pos_scale,
            "stop_loss_pct": stop_loss,
            "trailing_profile": trail_name,
            "period_mode": period_mode,
            "position_size": ep["position_size"],
            "risk_on_position_size": ep["risk_on_position_size"],
            "risk_off_position_size": ep["risk_off_position_size"],
        }
        trials.append((trial_id, cfg, params))
    return trials


def _aggregate(rows: list[TrialResult]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    ids = sorted(set(r.trial_id for r in rows))
    for trial_id in ids:
        sub = [r for r in rows if r.trial_id == trial_id]
        if not sub:
            continue
        params = sub[0].params
        out.append(
            {
                "trial_id": trial_id,
                "params": params,
                "symbols": len(sub),
                "mean_return_pct": float(sum(r.return_pct for r in sub) / len(sub)),
                "mean_alpha_pct": float(sum(r.alpha_pct for r in sub) / len(sub)),
                "mean_mdd_pct": float(sum(r.mdd_pct for r in sub) / len(sub)),
                "max_symbol_mdd_pct": float(max(r.mdd_pct for r in sub)),
                "total_trades": int(sum(r.trades for r in sub)),
                "mean_win_rate_pct": float(sum(r.win_rate_pct for r in sub) / len(sub)),
            }
        )
    return out


def main() -> int:
    args = parse_args()
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    symbols = [s.upper() for s in args.symbols]

    symbol_payloads: dict[str, dict[str, Any]] = {}
    for symbol in symbols:
        _, strategy_id, base_cfg = load_strategy_config(
            config_path=args.config,
            symbol=symbol,
            mode=args.mode,
            strategy_id=None,
        )
        stage3_cfg = _build_stage3_base(base_cfg)
        raw_df = load_data(
            _db_path_for_symbol(symbol),
            args.timeframe,
            args.start_date,
            args.end_date,
            exchange="binance",
        )
        if raw_df.empty:
            raise ValueError(f"{symbol}: empty data")
        prep_df = MLPDirectionBacktester(
            symbol=symbol,
            config=stage3_cfg,
            strategy_label=strategy_id,
        ).prepare_data(raw_df.copy())
        bnh = ((float(raw_df["close"].iloc[-1]) / float(raw_df["close"].iloc[0])) - 1.0) * 100.0
        symbol_payloads[symbol] = {
            "strategy_id": strategy_id,
            "base_stage3_cfg": stage3_cfg,
            "prepared_df": prep_df,
            "bnh_return_pct": float(bnh),
        }

    trial_cfgs = _make_trial_configs(next(iter(symbol_payloads.values()))["base_stage3_cfg"])
    rows: list[TrialResult] = []

    for trial_id, _, params in trial_cfgs:
        print(f"[trial] {trial_id}")
        for symbol in symbols:
            strategy_id = symbol_payloads[symbol]["strategy_id"]
            bnh = symbol_payloads[symbol]["bnh_return_pct"]
            prep_df = symbol_payloads[symbol]["prepared_df"]
            # Rebuild trial config per symbol from that symbol base stage3 config.
            trial_cfg = _make_trial_configs(symbol_payloads[symbol]["base_stage3_cfg"])
            trial_cfg_map = {tid: cfg for tid, cfg, _p in trial_cfg}
            cfg = trial_cfg_map[trial_id]

            res = MLPDirectionBacktester(
                symbol=symbol,
                config=cfg,
                strategy_label=strategy_id,
            ).run(prep_df, initial_capital=args.capital, csv_log=False)
            ret = float(res.get("total_return", 0.0))
            mdd = float(res.get("max_drawdown_pct", 0.0))
            rows.append(
                TrialResult(
                    trial_id=trial_id,
                    symbol=symbol,
                    return_pct=ret,
                    alpha_pct=ret - bnh,
                    mdd_pct=mdd,
                    trades=int(res.get("total_trades", 0)),
                    win_rate_pct=float(res.get("win_rate", 0.0)) * 100.0,
                    params=params,
                )
            )
            print(
                f"  {symbol}: ret={ret:+.2f}% alpha={ret-bnh:+.2f}%p mdd={mdd:.2f}%"
            )

    aggregate = _aggregate(rows)
    feasible = [x for x in aggregate if x["mean_mdd_pct"] <= args.mdd_cap]
    feasible.sort(key=lambda x: x["mean_return_pct"], reverse=True)
    best_feasible = feasible[0] if feasible else None

    now = datetime.now().strftime("%Y%m%d_%H%M%S")
    payload = {
        "generated_at": datetime.now().isoformat(),
        "period": {
            "start_date": args.start_date,
            "end_date": args.end_date,
            "timeframe": args.timeframe,
            "mdd_cap_pct": args.mdd_cap,
        },
        "symbols": symbols,
        "trial_count": len(set(r.trial_id for r in rows)),
        "aggregate": sorted(aggregate, key=lambda x: x["mean_return_pct"], reverse=True),
        "best_feasible": best_feasible,
        "results": [r.to_dict() for r in rows],
    }
    json_path = out_dir / f"fine_tune_mdd{int(args.mdd_cap)}_stage3_{now}.json"
    md_path = out_dir / f"fine_tune_mdd{int(args.mdd_cap)}_stage3_{now}.md"
    json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    lines: list[str] = []
    lines.append(f"# Stage3 Fine Tune (MDD <= {args.mdd_cap:.1f}%)")
    lines.append("")
    lines.append(f"- Generated: {payload['generated_at']}")
    lines.append(f"- Period: {args.start_date} to {args.end_date} ({args.timeframe})")
    lines.append(f"- Trials: {payload['trial_count']}")
    lines.append("")
    if best_feasible is None:
        lines.append("## Best Feasible")
        lines.append("- no feasible trial")
    else:
        lines.append("## Best Feasible")
        lines.append(
            f"- trial: `{best_feasible['trial_id']}` "
            f"(mean_ret={best_feasible['mean_return_pct']:+.2f}%, "
            f"mean_alpha={best_feasible['mean_alpha_pct']:+.2f}%p, "
            f"mean_mdd={best_feasible['mean_mdd_pct']:.2f}%, "
            f"max_symbol_mdd={best_feasible['max_symbol_mdd_pct']:.2f}%)"
        )
        lines.append(f"- params: `{best_feasible['params']}`")
    lines.append("")
    lines.append("## Top Trials by Return")
    lines.append("| trial_id | mean_ret% | mean_alpha%p | mean_mdd% | max_symbol_mdd% | win_rate% |")
    lines.append("|---|---:|---:|---:|---:|---:|")
    for row in payload["aggregate"][:12]:
        lines.append(
            f"| {row['trial_id']} | {row['mean_return_pct']:+.2f} | {row['mean_alpha_pct']:+.2f} | "
            f"{row['mean_mdd_pct']:.2f} | {row['max_symbol_mdd_pct']:.2f} | {row['mean_win_rate_pct']:.1f} |"
        )
    lines.append("")
    lines.append(f"## Feasible Trials (MDD <= {args.mdd_cap:.1f}%)")
    feas = [x for x in payload["aggregate"] if x["mean_mdd_pct"] <= args.mdd_cap]
    if not feas:
        lines.append("- none")
    else:
        for row in feas[:12]:
            lines.append(
                f"- `{row['trial_id']}`: ret={row['mean_return_pct']:+.2f}%, "
                f"alpha={row['mean_alpha_pct']:+.2f}%p, mdd={row['mean_mdd_pct']:.2f}%"
            )

    md_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"[done] json={json_path}")
    print(f"[done] md={md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
