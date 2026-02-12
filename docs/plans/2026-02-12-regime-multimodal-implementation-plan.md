# Regime Multimodal Implementation Plan

**Date**: 2026-02-12  
**Status**: Phase 1 implemented and validated with unit tests

## Objective

Improve crypto regime classification accuracy by combining:

- Technical/price signals
- On-chain behavior
- Sentiment signals
- Derivatives positioning (OI/Funding)
- Policy/event context

while preserving current production stability.

## Non-Goals (Phase 1)

- Direct external API integration (Glassnode/Twitter/news vendors)
- Immediate replacement of production v2 regime logic
- Full HMM/MS-GARCH production inference path

Phase 1 focuses on data schema, feature fusion, offline dataset build, and safe hooks.

## Current Baseline

- Production regime logic: `build_market_context()` + `EnhancedRegimeRouter`
- Existing filters: MTF/BBW/Volume, drawdown override, MFI/ADX thresholds
- Existing strategy stack: `mlp_direction_*` in `allocation.json`

## Target Architecture

1. **Regime Feature Schema Layer**
- Canonical row schema for 1h-aligned multimodal features.
- Deterministic handling of missing/lagged external data.

2. **Fusion Layer**
- Convert heterogeneous signals into normalized comparable scores.
- Build composite exogenous regime score and volatility jump flag.

3. **Dataset Builder**
- Local CSV/Parquet pipeline to create train/eval dataset from merged sources.
- Supports multi-timeframe trend context (1h/4h/1d).

4. **Model Layer (Phase 2+)**
- HMM / RF / XGBoost / MS-GARCH training and ensemble weighting.
- Walk-forward evaluation + regime transition metrics.

5. **Runtime Overlay (Phase 3+)**
- Optional exogenous regime overlay with safety toggle.
- Default OFF, can be enabled per strategy/config.

## Phased Plan

## Phase 1 (this implementation)

Deliverables:

- `trading/regime/types.py`: typed schema objects
- `trading/regime/fusion.py`: normalization + composite score + vol jump logic
- `trading/regime/feature_table.py`: multi-source table builder
- `scripts/regime/build_regime_feature_table.py`: CLI for dataset generation
- Unit tests for fusion/table behavior

Acceptance criteria:

- Can generate deterministic feature table from local CSV inputs.
- Missing external sources do not break pipeline (graceful fill + quality score).
- Test coverage for critical score/merge functions.

## Phase 2

Deliverables:

- `scripts/regime/train_regime_hmm.py`
- `scripts/regime/train_regime_rf.py`
- `scripts/regime/train_ms_garch.py`
- `scripts/regime/train_ensemble.py`
- regime-switch weighted loss handling and calibration outputs

Acceptance criteria:

- OOS regime transition F1 improves over baseline.
- false-switch rate reduced with bounded delay.

## Phase 3

Deliverables:

- Runtime regime overlay service
- Config-driven integration in strategy evaluation path
- Paper validation gates using overlay confidence/quality

Acceptance criteria:

- No degradation in paper readiness safety metrics.
- Controlled live rollout behind explicit feature flag.

## Data Contract (Phase 1 schema)

Required:

- `timestamp`, `close`

Recommended technical:

- `volume`, `mfi`, `adx`, `atr`

External optional:

- `onchain_activity_score`
- `sentiment_score`
- `open_interest_change`
- `funding_rate`
- `policy_event_score`

Derived:

- `derivatives_stress_score`
- `external_regime_score`
- `volatility_jump`
- `trend_1h`, `trend_4h`, `trend_1d`
- `data_quality_score`

## Risk Controls

- Feature flag default OFF for any runtime overlay.
- Never hard-fail trading loop due to missing external inputs.
- Source-level quality scoring required before model consumption.
- Strong offline evaluation before any live path change.

## Initial Execution Checklist

1. [x] Implement schema/fusion/table builder modules.
2. [x] Add CLI dataset build script.
3. [x] Add unit tests.
4. [ ] Validate generated dataset on BTC sample.
5. [x] Prepare initial Phase 2 model training scripts (RF/HMM).

## Phase 1 Completion Notes (2026-02-12)

- Implemented:
`trading/regime/types.py`,
`trading/regime/fusion.py`,
`trading/regime/feature_table.py`,
`trading/regime/training.py`,
`scripts/regime/build_regime_feature_table.py`,
`scripts/regime/train_regime_rf.py`,
`scripts/regime/train_regime_hmm.py`,
`scripts/backtest/period_problem_areas.py`
- Added tests:
`tests/trading/regime/test_fusion.py`,
`tests/trading/regime/test_feature_table.py`,
`tests/trading/regime/test_training.py`
- Verification command:
`pytest -q tests/trading/regime/test_fusion.py tests/trading/regime/test_feature_table.py tests/trading/regime/test_training.py`

## Execution Snapshot (2026-02-12)

- Period comparison run completed:
`python scripts/backtest/period_vs_bnh.py --start-date 2025-01-01 --end-date 2026-02-01 --timeframe minute240 --periods M,Q`
- Problem-area report generated:
`python scripts/backtest/period_problem_areas.py --label 2025-01_2026-02`
- Key outputs:
`logs/backtest_reports/period_vs_bnh_summary.csv`,
`logs/backtest_reports/period_vs_bnh_problem_areas_2025-01_2026-02.md`,
`logs/backtest_reports/period_vs_bnh_symbol_weakness.csv`
- RF regime model training run completed (BTC, minute240):
`python scripts/regime/train_regime_rf.py ...`
- Dependency status confirmed:
`xgboost`, `lightgbm`, `hmmlearn` installed.
- HMM regime model training run completed (BTC, minute240):
`python scripts/regime/train_regime_hmm.py ...`
- RF+HMM ensemble OOS evaluation script added and executed:
`python scripts/regime/evaluate_regime_ensemble.py ...`
- Ensemble OOS snapshot (BTC, 2025-01~2026-02, 337 rows):
RF macro-F1 `0.3442`, HMM macro-F1 `0.2552`, Ensemble(0.7/0.3) macro-F1 `0.2888`.
- Weight sweep snapshot:
best tested mix was RF/HMM `0.95/0.05` with macro-F1 `0.3396` (still below RF-only).
- HMM feature expansion test (ATR/ADX/Volume included) completed:
best tested mix RF/HMM `0.95/0.05` macro-F1 `0.3425` (improved vs prior ensemble sweep, but still below RF-only `0.3442`).
- Rule-based hybrid guard test completed:
`low-confidence RF trend -> SIDEWAYS when HMM sideways prob high`.
- Hybrid OOS snapshot (default conf/sideways = `0.55/0.65`):
accuracy `0.5875`, macro-F1 `0.3158` (better than simple ensemble, below RF-only).
- Hybrid sweep snapshot:
best macro-F1 matched RF-only at conf/sideways `0.45/0.70` (`0.3442`), indicating conservative guard is safest.
- Calibration + hybrid refinement completed (validation-based RF class multiplier tuning):
RF-calibrated macro-F1 `0.3619` (vs RF `0.3442`), with lower accuracy.
- Calibrated ensemble snapshot:
macro-F1 `0.3521` (improved vs non-calibrated ensemble `0.2701`).
- Calibrated hybrid snapshot (default conf/sideways `0.55/0.65`):
accuracy `0.5727`, macro-F1 `0.3714` (improves both accuracy and macro-F1 vs RF baseline on current OOS run).
- Multi-asset extension completed (ETH/SOL/BNB, same OOS window):
results stored in `logs/regime_models/multi_asset_calibrated_hybrid_summary_2025-01_2026-02.csv`.
- Best model by macro-F1 on this run:
ETH=`ensemble`, SOL=`rf_calibrated`, BNB=`rf_calibrated`
(`logs/regime_models/multi_asset_best_model_by_macro_f1_2025-01_2026-02.csv`).
- Full-available-period rerun completed for BTC/ETH/SOL/BNB and compared against prior window:
`logs/regime_models/multi_asset_calibrated_hybrid_summary_full_available.csv`,
`logs/regime_models/multi_asset_calibrated_hybrid_compare_prior_vs_full.csv`.
- Runtime overlay implementation added (safe-off by default):
`trading/regime/runtime.py`,
`CompositeStrategyTask` integration,
`allocation.json` defaults with per-symbol best-model mapping.
- Runtime overlay tests added:
`tests/trading/regime/test_runtime.py`,
`tests/trading/strategies/components/test_composite_runtime_overlay.py`.
