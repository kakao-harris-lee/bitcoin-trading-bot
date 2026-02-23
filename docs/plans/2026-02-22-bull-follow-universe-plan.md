# Bull-Follow Universe Upgrade Plan (2026-02-22)

## Objective
Shift from defensive single-model behavior to a cross-asset bull-follow pipeline that can capture fast up-moves in non-major coins.

## Scope
- Spot-only data (Binance spot universe)
- Cross-asset pooled training
- Long-only top-K rotation with risk-on gating
- Equal-position benchmark comparison versus buy-and-hold basket

## Implementation Delivered
1. Universe spot collector
- `scripts/collectors/collect_universe_ohlcv.py`
- Sources symbols from `config/strategies/allocation.json` (default: `strategies.mlp_direction_bnb.symbols`)
- Stores per-symbol OHLCV CSV under `data/universe_backtest_4h`

2. Bull-follow feature library
- `trading/indicators/bull_follow_features.py`
- Per-symbol features: momentum/trend/volume/volatility/breakout
- Cross-sectional features: breadth, median momentum, breakout ratio
- Forward target columns for supervised ranking

3. Train + backtest pipeline
- `scripts/bull_follow/train_bull_follow_model.py`
- Trains pooled cross-asset model and runs top-K long-only portfolio simulation
- Applies risk-on gate (`cs_above_ema50_ratio`) and transaction costs
- Writes summary/metrics/contribution artifacts to `reports/`
- Saves model artifact to `models/bull_follow/v1/`

## Baseline Execution
```bash
python scripts/collectors/collect_universe_ohlcv.py \
  --strategy-id mlp_direction_bnb \
  --timeframe minute240 \
  --start-date 2020-01-01 \
  --end-date 2026-02-22

python scripts/bull_follow/train_bull_follow_model.py \
  --data-dir data/universe_backtest_4h \
  --timeframe minute240 \
  --start-date 2020-01-01 \
  --end-date 2026-02-22 \
  --train-end-date 2024-12-31 \
  --top-k 8
```

## Promotion Gate
Promote to paper-trading candidate only if all conditions hold:
- Return alpha vs equal-weight B&H basket is positive.
- MDD is not materially worse than current paper baseline.
- Spearman IC is stable (> 0 on OOS period).
- Turnover remains acceptable after fees/slippage.

## Next Iteration
- Add regime-aware position scaling (risk-on strong/moderate tiers).
- Add symbol-level liquidity filters (tick/volume quality) directly into backtest script.
- Run walk-forward tuning for `top_k`, `risk_on_breadth`, `min_score`, `min_adx`.
