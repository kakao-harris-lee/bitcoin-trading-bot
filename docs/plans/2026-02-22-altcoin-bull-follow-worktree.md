# ALT Bull-Follow Worktree Implementation (2026-02-22)

## Scope
- Keep existing `MLP base` strategies for `BTC/ETH/BNB` unchanged.
- Implement ALT-only research pipeline in separate worktree branch.
- Run backtest on ALT universe and compare execution variants.

## Branch / Worktree
- branch: `feat/altcoin-bull-follow`
- worktree: `/home/deploy/project/bitcoin-trading-bot-wt-altcoin-follow`

## Implemented Code
1. `trading/indicators/bull_follow_features.py`
- Added CTREND-lite style features:
  - `ret_12`
  - `trend_ema_5_20`, `trend_ema_20_120`
  - `volume_trend_3_24`, `volume_trend_6_48`
  - `illiq_ret3_interaction`, `trend_volume_interaction`

2. `scripts/bull_follow/train_bull_follow_model.py`
- Added ALT-friendly execution controls:
  - symbol exclusion (`--exclude-symbols`, default: BTC ETH BNB)
  - weighting mode (`equal` / `inv_vol`)
  - per-symbol max weight cap (`--max-symbol-weight`)
  - crash guard (`--crash-ret3-threshold`, `--crash-breadth-threshold`, `--no-crash-guard`)
- Backtest output now includes:
  - `gross_exposure`, `crash_block`, `avg_gross_exposure`, `crash_block_bars`

3. `scripts/bull_follow/optimize_portfolio_params.py`
- Updated for new train config contract and ALT symbol exclusion path.

4. `scripts/collectors/collect_universe_ohlcv.py`
- Added `--exclude-symbols` option to collect ALT-only datasets directly.

5. `scripts/bull_follow/run_altcoin_research_backtest.py` (new)
- ALT-only end-to-end runner.
- Variant comparison in one command:
  - `alt_baseline_equal`
  - `alt_ctrend_invvol_guard`
- Auto-generates comparison CSV/MD.

## Backtest Execution
```bash
python scripts/bull_follow/run_altcoin_research_backtest.py \
  --data-dir /home/deploy/project/bitcoin-trading-bot/data/universe_backtest_4h \
  --config config/strategies/allocation.json \
  --strategy-id mlp_direction_bnb \
  --timeframe minute240 \
  --start-date 2020-01-01 \
  --end-date 2026-02-22 \
  --train-end-date 2024-12-31 \
  --feature-profile base \
  --target-mode forward \
  --top-k 8
```

## Result Summary (ALT-only)
- symbol universe: 63 (BTC/ETH/BNB excluded)
- split: train 117,592 / test 157,626
- benchmark: equal-weight ALT B&H

| Variant | Return % | MDD % | Sharpe | ALT EW B&H % | Alpha %p | Avg Exposure | Crash Bars |
|---|---:|---:|---:|---:|---:|---:|---:|
| alt_ctrend_invvol_guard | -49.94 | -55.28 | -1.888 | -78.07 | +28.13 | 0.173 | 91 |
| alt_baseline_equal | -69.42 | -73.13 | -2.211 | -78.07 | +8.65 | 0.240 | 0 |

## Artifacts
- comparison: `reports/bull_follow_alt_compare_20260222_043042.md`
- comparison csv: `reports/bull_follow_alt_compare_20260222_043042.csv`
- variant summary:
  - `reports/bull_follow_v1_alt_base_forward_alt_baseline_equal_20260222_042826_alt_baseline_equal_summary.md`
  - `reports/bull_follow_v1_alt_base_forward_alt_ctrend_invvol_guard_20260222_042826_alt_ctrend_invvol_guard_summary.md`

## Interpretation
- ALT-only on this sample still produced negative absolute return.
- However, CTREND-lite execution (`inv_vol + crash guard`) reduced drawdown materially and improved alpha vs ALT B&H.
- This is suitable as a next paper-trading candidate for ALT sleeve only, while keeping BTC/ETH/BNB base MLP unchanged.
