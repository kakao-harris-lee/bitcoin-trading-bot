# ALT Capital Concentration Update (2026-02-22)

## User Requirement
- Frequent trading is not the goal.
- Allocate larger capital to coins showing strong trend signals.
- Do not recycle cash to BTC/ETH/BNB.
- Keep cash available, but when strong ALT signals appear, deploy full capital to selected ALT symbols.

## Code Changes
1. `scripts/bull_follow/train_bull_follow_model.py`
- Added concentrated weighting modes:
  - `trend_score`
  - `trend_score_inv_vol`
- Added strong-signal controls:
  - `score_power`
  - `trend_weight`
  - `score_quantile`
- Added full-deploy behavior:
  - `full_deploy_on_signal=True` normalizes selected weights to 100% gross exposure when entries exist.
- Updated defaults for strong-signal ALT style:
  - `horizon_bars=1`
  - `min_score=0.004`
  - `weighting_mode=trend_score_inv_vol`
  - `max_symbol_weight=0.75`
  - `score_quantile=0.0`

2. `scripts/bull_follow/run_altcoin_research_backtest.py`
- Variant renamed to `alt_trend_concentrated_guard`.
- Defaults aligned to strong-signal concentrated deployment.

3. `scripts/bull_follow/optimize_portfolio_params.py`
- Updated `TrainConfig` mapping for new weighting fields.
- Default horizon aligned to `1`.

## Validation Run
Command:
```bash
python scripts/bull_follow/run_altcoin_research_backtest.py \
  --data-dir /home/deploy/project/bitcoin-trading-bot/data/universe_backtest_4h \
  --config config/strategies/allocation.json \
  --strategy-id mlp_direction_bnb \
  --timeframe minute240 \
  --start-date 2020-01-01 \
  --end-date 2026-02-22 \
  --train-end-date 2024-12-31
```

Result (`reports/bull_follow_alt_compare_20260222_053123.md`):
- `alt_trend_concentrated_guard`
  - Return: `+20.60%`
  - MDD: `-10.56%`
  - Sharpe: `1.063`
  - Alpha vs ALT EW B&H: `+99.06%p`
- `alt_baseline_equal`
  - Return: `+19.33%`
  - MDD: `-10.06%`

## Exposure Behavior Check
`reports/bull_follow_v1_alt_base_forward_alt_trend_concentrated_guard_20260222_052922_alt_trend_concentrated_guard_equity.csv`
- bars: `2507`
- nonzero exposure bars: `41` (`1.64%`)
- average exposure on nonzero bars: `1.0`

Interpretation:
- Strategy stays mostly in cash (strong-signal only).
- When a strong signal appears, it deploys full cash to selected ALT basket.
- No BTC/ETH/BNB fallback/recycle path is used.

## Paper Preset (Updated)
- `run_altcoin_research_backtest.py` now defaults to **paper preset ON**:
  - no breadth-adaptive (unless explicitly enabled)
  - symbol quality filter ON
  - regime weak guard ON
- New helper command:
```bash
scripts/bull_follow/run_paper_preset_backtest.sh
```
- Latest default-paper result:
  - report: `reports/bull_follow_alt_compare_20260222_142747.md`
  - `alt_trend_concentrated_guard`: return `+23.55%`, MDD `-10.56%`, Sharpe `1.223`
