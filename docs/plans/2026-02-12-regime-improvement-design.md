# Regime Detection Improvement Design

**Date**: 2026-02-12
**Status**: Phase 1-2 Complete, Phase 3 Partially Implemented

## Problem Statement

The current regime detection system (V2 EnhancedRegimeRouter) has five structural weaknesses:

1. Hardcoded MFI/ADX thresholds in `_classify_regime()` — not configurable
2. MFI lag on rallies — drawdown override covers crashes but not recoveries
3. V2 filter pipeline complexity — MTF + BBW + Volume may be overly conservative
4. MLP-regime dual judgment — MLP predicts direction, regime also gates entry, potential conflict
5. No backtest validation — no data proving the regime filter improves returns

## Execution Strategy

**Data-first approach**: Run ablation backtest (#5) before implementing changes (#1-#4). Decisions for #2, #3, #4 depend on ablation results.

```
Phase 1: Backtest Validation (#5)     ← First
Phase 2: Data-Based Decisions         ← Analyze results
Phase 3: Implementation (#1-#4)       ← Act on data
```

---

## Phase 1: Regime Ablation Backtest (#5)

### Goal

Quantify the impact of each regime filter component on strategy performance.

### Experiment Matrix

6 regime configurations x 3 assets (BTC/ETH/SOL) x 3 strategy types:

| Config | Description | What it tests |
|--------|-------------|---------------|
| `baseline` | Regime filter completely disabled | Is regime useful at all? |
| `v2_full` | Current production (MTF + BBW + Volume) | Production baseline |
| `v2_no_mtf` | BBW + Volume only | MTF contribution |
| `v2_no_bbw` | MTF + Volume only | BBW contribution |
| `v2_no_vol` | MTF + BBW only | Volume filter contribution |
| `regime_only` | Raw `_classify_regime()` without V2 filters | V2 pipeline value-add |

### Strategy Coverage

| Strategy | Market | Regime Usage |
|----------|--------|-------------|
| MLP Direction | Spot | `skip_bear_regime` gate |
| Short V1 | Futures | Regime is primary entry gate |
| Sideways | Futures | SIDEWAYS_* regime required for entry |

### Metrics

Per config-asset-strategy combination:
- Total return (%)
- Max drawdown (%)
- Sharpe ratio
- Total trades
- Win rate (%)
- Profit factor
- BEAR-period BUY signals (for #4 analysis)

### Implementation

**Script**: `scripts/backtest/regime_ablation.py`

```
Usage:
  python scripts/backtest/regime_ablation.py [--assets BTC,ETH,SOL] [--strategies mlp,short,sideways]

Output:
  - Console table comparing all configs
  - CSV export for further analysis
```

**Mechanism**: Use existing `ComponentStrategyAdapter` with config overrides:
- `baseline`: Set `skip_bear_regime=False`, disable regime checks in entry components via config flag
- `v2_no_*`: Toggle `mtf_enabled`, `bbw_enabled`, `volume_filter_enabled` flags
- `regime_only`: Set `regime_version="v2"` but disable all 3 sub-filters

**Required changes before running**:
- Add `bbw_enabled` and `volume_filter_enabled` flags to `EnhancedRegimeRouter` (currently only `mtf_enabled` exists)
- Add `regime_bypass` config flag to entry components to skip all regime checks

### Data Period

- Training: 2020-01-01 to 2024-12-31
- Test (OOS): 2025-01-01 to 2026-02-01

---

## Phase 2: Ablation Results & Decisions

### Ablation Results (2020-2026, full period)

**MLP Strategy** (BTC/ETH averages, SOL excluded due to missing model):

| Config | Avg Ret% | Avg Sharpe | Avg Trades |
|--------|----------|------------|------------|
| baseline (no regime) | +40.6% | 0.57 | 308 |
| v2_full (production) | +42.3% | 0.59 | 284 |
| **v2_no_bbw** | **+45.9%** | **0.64** | 285 |
| regime_only | +44.5% | 0.63 | 290 |

**Sideways Strategy** (BTC/ETH/SOL averages):

| Config | Avg Ret% | Avg Sharpe | Avg Trades |
|--------|----------|------------|------------|
| baseline (no regime) | **-0.7%** | **-0.69** | **173** |
| v2_full (production) | +0.0% | 0.06 | 60 |
| **v2_no_vol** | **+0.1%** | **0.12** | 59 |
| regime_only | -0.0% | -0.02 | 60 |

**Short Strategy** (BTC/ETH/SOL averages, after backtester short support fix):

| Config | Avg Ret% | Avg Sharpe | Avg Trades |
|--------|----------|------------|------------|
| baseline (no regime) | **-4.2%** | **-1.02** | **378** |
| v2_full (production) | -0.1% | -0.38 | 2 |
| regime_only | -0.0% | -0.17 | 0 |

Regime is **critical** for Short — prevents 378 losing trades. Raw regime classification alone is sufficient (regime_only ≈ v2_full).

### Decisions

#### #3 V2 Filter Simplification → SIMPLIFY

| Filter | MLP Impact | Sideways Impact | Decision |
|--------|-----------|-----------------|----------|
| **BBW** | Hurts ETH (-7.3% return) | Slightly beneficial (+0.05 Sharpe) | **Disable for MLP, keep for Sideways** |
| **Volume** | Minimal (+3.7% BTC, 0 ETH) | Slightly harmful (-0.06 Sharpe) | **Disable for both** |
| **MTF** | Minimal | Minimal | Keep enabled (low cost) |

**Implemented**: `allocation.json` MLP strategies now set `bbw_enabled: false, volume_filter_enabled: false`.

#### #4 MLP-Regime Dual Judgment → REGIME IS MARGINAL

Baseline (+40.6%) vs v2_full (+42.3%) shows regime adds only +1.7% over 6 years for MLP. The MLP model's own predictions already filter well. However, regime doesn't significantly hurt either, so keep it with simplified filters (no BBW/Volume overhead).

**Decision**: Keep regime for MLP but disable BBW and Volume filters. No confidence-based gate needed.

#### #2 MFI Lag (Rally Override) → SKIP (YAGNI)

Baseline doesn't significantly outperform v2_full in aggregate. No evidence of rally-miss problem in the data.

**Decision**: Skip rally override implementation.

#### #1 Threshold Externalization → DEFER

With BBW/Volume disabled for MLP and minimal filter impact overall, the urgency is low. Defer to when Quant Lab optimization is needed.

#### Short Backtester Fix → COMPLETED

Added `_execute_open_short()` and `_execute_close_short()` to `core/backtester.py`. Margin model with leverage support. Short results confirm regime is critical for preventing losses.

---

## Phase 3: Implementation

### #1 Threshold Externalization (execute regardless of ablation)

**Rationale**: Infrastructure improvement. Enables future tuning without code changes.

**Design**:

```python
@dataclass(frozen=True)
class RegimeThresholds:
    mfi_bull: float = 54.0          # BULL if MFI >= this AND ADX >= moderate
    mfi_sideways_up: float = 49.0   # SIDEWAYS_UP if MFI >= this
    mfi_sideways_flat: float = 41.0 # SIDEWAYS_FLAT if MFI >= this
    mfi_bear: float = 34.0          # BEAR if MFI < this
    adx_strong: float = 25.0        # Strong trend threshold
    adx_moderate: float = 18.0      # Moderate trend threshold
```

**Files to change**:
- `trading/strategies/components/models.py`: Add `RegimeThresholds`, update `_classify_regime()` signature
- `trading/strategies/components/composite_task.py`: Read thresholds from config, pass to `build_market_context()`
- `core/component_adapter.py`: Same config reading
- `config/strategies/allocation.json`: Add optional `regime_thresholds` section under `defaults`

**LRU cache compatibility**: `frozen=True` dataclass is hashable, can be part of cache key.

### #2 Rally Override (conditional on Phase 2 decision)

**Design**: Symmetric to existing drawdown override.

```python
# In build_market_context(), after drawdown override:
if recent_low > 0:
    rally_pct = (close - recent_low) / recent_low
    if rally_pct >= rally_bull_threshold:
        is_rally_bull = True
        regime = "BULL_STRONG" if adx >= adx_strong else "BULL_MODERATE"
```

**Files to change**:
- `trading/strategies/components/models.py`: Add `rally_bull_threshold` param to `build_market_context()`, add `is_rally_bull` to `MarketContext`, add `low_30d` to `MarketData`
- `trading/indicators/`: Compute 30-day rolling low

**Configuration**: `rally_bull_threshold` in allocation.json (default 0.15, set to 1.0 to disable).

### #3 V2 Filter Simplification (conditional on Phase 2 decision)

**If simplifying**: Add enable/disable flags to `EnhancedRegimeRouter`:

```python
class EnhancedRegimeRouter:
    def __init__(self, ..., bbw_enabled=True, volume_filter_enabled=True, mtf_enabled=True):
```

These flags are needed for Phase 1 ablation anyway, so they get built first.

**Files**: `trading/strategies/components/regime_filter.py`

### #4 MLP Confidence-Based Regime (conditional on Phase 2 decision)

**If converting from boolean to confidence-based**:

```python
# In mlp_direction_entry.py
if regime in BEAR_REGIMES:
    bear_confidence = config.get("bear_min_confidence", 0.80)  # stricter in BEAR
    if confidence < bear_confidence:
        return Signal.NEUTRAL  # block low-confidence BEAR entries
    # allow high-confidence entries even in BEAR
```

**Files**: `trading/strategies/components/mlp_direction_entry.py`

---

## File Impact Summary

### Phase 1 (Ablation)
| File | Change |
|------|--------|
| `scripts/backtest/regime_ablation.py` | NEW — ablation runner |
| `trading/strategies/components/regime_filter.py` | Add `bbw_enabled`, `volume_filter_enabled` flags |
| Entry components | Add `regime_bypass` config flag |

### Phase 3 (Implementation, conditional)
| File | Change |
|------|--------|
| `models.py` | `RegimeThresholds` dataclass, `_classify_regime()` params |
| `composite_task.py` | Read thresholds from config |
| `component_adapter.py` | Read thresholds from config |
| `regime_filter.py` | Filter enable/disable flags |
| `mlp_direction_entry.py` | Confidence-based regime gate |
| `allocation.json` | `regime_thresholds`, `bear_min_confidence` |

---

## Risk Assessment

| Risk | Mitigation |
|------|-----------|
| Ablation takes too long | Limit to 3 assets, reuse existing backtest infra |
| Removing filters worsens live performance | Only change after OOS (2025+) data confirms |
| Threshold changes break existing strategies | Default values match current hardcoded values |
| Rally override creates false bull signals | Configurable threshold, default disabled (1.0) |

## Success Criteria

1. Ablation script produces clear comparison table for all configs
2. Each regime component has measured contribution to performance
3. Decisions for #2-#4 are data-driven, not speculative
4. Threshold externalization enables future Quant Lab optimization
