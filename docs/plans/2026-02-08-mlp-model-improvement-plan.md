# MLP Model Improvement Plan

**Date**: 2026-02-08
**Goal**: Improve MLP Direction strategy returns and risk-adjusted metrics through systematic feature engineering, multi-timeframe signals, model ensembling, and asset expansion.

## Current State

| Item | Current |
|------|---------|
| **Architecture** | 3-layer MLP (128→64→32), LeakyReLU, Dropout 0.2, 3-class (Hold/Buy/Sell) |
| **Feature Set** | `paper_36`: 23 candlestick patterns + 6 technical indicators + 4 EMA crossovers + 3 temporal |
| **Assets** | BTC (bwin=5), ETH/SOL/BNB (bwin=4), all fwin=2 |
| **Training** | AdamW, CrossEntropy/FocalLoss, EarlyStopping(10), paper-aligned split |
| **Performance** | BTC +182%, ETH +342%, SOL +87% (backtest 2020-2026, with vol sizing) |

### Key Finding from Paper (Parente & Rizzuti 2025)

The authors themselves note that candlestick patterns are **"relatively ineffective"** (Figure 6-7). The top-10 most important features by SHAP are ALL from the non-candlestick categories: `bollinger_pct_b`, `rsi`, `ema_cross_*`, `price_zscore`, temporal features. This means **23 of 36 features (64%) contribute minimal signal** while potentially adding noise.

---

## Phase 1: Feature Engineering v2 — Replace Candlestick Patterns

**Status**: COMPLETED — Result: NEGATIVE (v2_36 underperformed paper_36)
**Priority**: HIGHEST — Biggest expected improvement with lowest effort
**Estimated Effort**: 2-3 days
**Expected Impact**: +15-30% returns improvement, reduced noise

### Phase 1 Results (2026-02-08)

**v2_36 significantly underperformed paper_36**:

| Asset | paper_36 | v2_36 | Delta |
|-------|----------|-------|-------|
| BTC | +387.5% | +298.0% | -89.5% |
| ETH | +1270.6% | +409.8% | -860.8% |
| SOL | +172.1% | +191.7% | +19.6% |
| Portfolio Avg | +610.1% | +299.8% | -310.3% |

MDD: BTC improved (-64→-54%), ETH improved (-66→-61%), SOL worsened (-61→-87%).

**Conclusion**: Despite SHAP showing low individual importance for candlestick patterns, they collectively provided useful signal (likely through interaction effects with other features). The paper_36 feature set **remains the production standard**. v2_36 code is kept in codebase for future experimentation but will not be deployed.

**Trained models** (kept for reference):
- `models/mlp_direction/btc_v2_bwin5_fwin2/model_final.pt` (61.6% accuracy)
- `models/mlp_direction/eth_v2_bwin4_fwin2/model_final.pt` (58.9% accuracy)

### Rationale

Replace 23 low-signal candlestick features with proven technical indicators that capture market microstructure. Keep the 13 effective features (6 technical + 4 EMA + 3 temporal) and add 23 new features to maintain the 36-feature input dimension (no model architecture change needed).

### New Feature Set: `v2_36`

| # | Feature | Category | Rationale |
|---|---------|----------|-----------|
| 1 | `bollinger_pct_b` | Volatility | **KEEP** — #1 SHAP importance |
| 2 | `ultosc` | Momentum | **KEEP** — multi-period oscillator |
| 3 | `rsi` | Momentum | **KEEP** — #2 SHAP importance |
| 4 | `close_pct_change` | Return | **KEEP** — 1-bar momentum |
| 5 | `price_zscore` | Mean-Rev | **KEEP** — #8 SHAP importance |
| 6 | `volume_zscore` | Volume | **KEEP** — anomaly detection |
| 7 | `ema_cross_1_20` | Trend | **KEEP** — #3 SHAP importance |
| 8 | `ema_cross_20_50` | Trend | **KEEP** — #4 SHAP importance |
| 9 | `ema_cross_50_100` | Trend | **KEEP** — medium-term trend |
| 10 | `ema_cross_1_50` | Trend | **KEEP** — trend confirmation |
| 11 | `samples_in_day` | Temporal | **KEEP** — intraday seasonality |
| 12 | `day_of_week` | Temporal | **KEEP** — weekly seasonality |
| 13 | `month` | Temporal | **KEEP** — monthly seasonality |
| 14 | `macd_hist` | Momentum | **NEW** — MACD histogram (trend momentum) |
| 15 | `macd_signal_dist` | Momentum | **NEW** — MACD - Signal distance (crossover proximity) |
| 16 | `adx` | Trend | **NEW** — trend strength (0-100) |
| 17 | `plus_di_minus_di` | Trend | **NEW** — +DI/-DI ratio (directional strength) |
| 18 | `stoch_k` | Momentum | **NEW** — Stochastic %K |
| 19 | `stoch_d` | Momentum | **NEW** — Stochastic %D |
| 20 | `mfi` | Volume | **NEW** — Money Flow Index (volume-weighted RSI) |
| 21 | `atr_pct` | Volatility | **NEW** — ATR/price (normalized volatility) |
| 22 | `bb_width` | Volatility | **NEW** — (upper-lower)/middle (volatility regime) |
| 23 | `return_4bar` | Momentum | **NEW** — 4-bar return (16H momentum) |
| 24 | `return_6bar` | Momentum | **NEW** — 6-bar return (24H momentum) |
| 25 | `return_30bar` | Momentum | **NEW** — 30-bar return (5-day momentum) |
| 26 | `vol_ratio_20` | Volume | **NEW** — volume / SMA(volume,20) |
| 27 | `ema_cross_1_200` | Trend | **NEW** — close/EMA(200) (macro trend) |
| 28 | `ema_cross_100_200` | Trend | **NEW** — EMA(100)/EMA(200) (golden/death cross) |
| 29 | `rsi_ema` | Momentum | **NEW** — EMA(RSI,14) (smoothed momentum) |
| 30 | `high_low_range` | Volatility | **NEW** — (high-low)/close (bar range %) |
| 31 | `close_vs_high20` | S/R | **NEW** — close / 20-period high (distance from resistance) |
| 32 | `close_vs_low20` | S/R | **NEW** — close / 20-period low (distance from support) |
| 33 | `market_stress` | Regime | **NEW** — composite stress indicator (already computed) |
| 34 | `obv_zscore` | Volume | **NEW** — OBV z-score (accumulation/distribution) |
| 35 | `willr` | Momentum | **NEW** — Williams %R (overbought/oversold) |
| 36 | `cci` | Momentum | **NEW** — Commodity Channel Index (mean reversion) |

### Files to Modify

| File | Change |
|------|--------|
| `trading/indicators/mlp_features.py` | Add `FEATURE_SET_V2 = "v2_36"`, `FEATURE_NAMES_V2` list, `calculate_mlp_features_v2()`, `extract_single_features_v2()` |
| `trading/indicators/precompute.py` | Ensure all new indicators are pre-computed (most already are) |
| `mlp_trainer/src/dataset_builder.py` | Support `feature_set="v2_36"` in `DatasetConfig` |
| `mlp_trainer/src/constants.py` | Add `V2_INPUT_DIM = 36` |
| `config/strategies/allocation.json` | Change `mlp_feature_set` from `"paper_36"` to `"v2_36"` (after validation) |

### Implementation Steps

1. **Add feature calculation function** `calculate_mlp_features_v2(df)` in `mlp_features.py`
   - Reuse existing indicator columns from `add_all_indicators()`
   - Add new calculations: `macd_signal_dist`, `plus_di_minus_di`, `return_Nbar`, `rsi_ema`, `obv_zscore`, `cci`, `willr`
   - Keep same output format as `calculate_mlp_features_paper()`

2. **Add live extraction function** `extract_single_features_v2(market_data, indicators)` in `mlp_features.py`
   - Map pre-computed indicator dict keys to feature array indices
   - All new features must be available from `add_all_indicators()` or from market_data

3. **Register in dispatcher** — Add `FEATURE_SET_V2` to `calculate_mlp_features()` and `extract_single_features()` dispatch

4. **Build datasets** — `python -m mlp_trainer.src.dataset_builder --feature-set v2_36`

5. **Train models** — Per asset, same hyperparameters, compare validation metrics:
   ```bash
   python -m mlp_trainer.src.mlp_train --feature-set v2_36 --symbol BTC --bwin 5 --fwin 2
   python -m mlp_trainer.src.mlp_train --feature-set v2_36 --symbol ETH --bwin 4 --fwin 2
   python -m mlp_trainer.src.mlp_train --feature-set v2_36 --symbol SOL --bwin 4 --fwin 2
   python -m mlp_trainer.src.mlp_train --feature-set v2_36 --symbol BNB --bwin 4 --fwin 2
   ```

6. **Backtest comparison** — Run A/B with paper_36 vs v2_36:
   ```bash
   python scripts/backtest/feature_set_comparison.py --feature-sets paper_36 v2_36
   ```

7. **Deploy** — If v2_36 wins, update `allocation.json` and retrain final models

### Validation Criteria

- **Must beat paper_36 on total return** for at least 3 of 4 assets
- **Must not increase MDD** by more than 5% absolute
- **Must maintain Sharpe >= current** (within 0.05 tolerance)
- **Forward test window (2023-2026)** must show improvement (not just backtest)

---

## Phase 2: Multi-Timeframe Features

**Priority**: HIGH — Adds structural context that single-timeframe models miss
**Estimated Effort**: 3-4 days
**Dependency**: Phase 1 complete — **use paper_36 as base** (v2_36 failed validation)
**Expected Impact**: +10-20% risk-adjusted improvement (better regime awareness)

### Rationale

Current model sees only 4H bars. It cannot distinguish "4H dip in a daily uptrend" from "4H dip in a daily downtrend". Adding Daily and Weekly indicator summaries as features gives the model macro context without changing the prediction timeframe.

### New Feature Set: `paper_mtf_44`

Extends `paper_36` with 8 multi-timeframe features:

| # | Feature | Source TF | Description |
|---|---------|-----------|-------------|
| 37 | `daily_rsi` | 1D | RSI(14) on daily bars |
| 38 | `daily_adx` | 1D | ADX(14) on daily bars |
| 39 | `daily_ema_cross_20_50` | 1D | Daily EMA(20)/EMA(50) ratio |
| 40 | `daily_bb_width` | 1D | Daily Bollinger bandwidth |
| 41 | `weekly_rsi` | 1W | RSI(14) on weekly bars |
| 42 | `weekly_ema_cross_10_20` | 1W | Weekly EMA(10)/EMA(20) ratio |
| 43 | `daily_return_5d` | 1D | 5-day return |
| 44 | `daily_vol_ratio` | 1D | Daily volume / SMA(volume,20) |

### Implementation Strategy

**Data Aggregation**: Resample 4H OHLCV to 1D and 1W within `calculate_mlp_features_v2_mtf()`:
```python
df_daily = df.resample('1D').agg({'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'})
df_weekly = df.resample('1W').agg(...)
# Calculate indicators on each timeframe, then forward-fill back to 4H
```

**Live Trading**: The 4H candle handler already has access to historical bars. Aggregate on-the-fly:
- Keep a rolling buffer of recent daily closes (from 4H aggregation)
- Compute daily/weekly indicators from buffer
- Pass as additional `indicators` dict keys

### Files to Modify

| File | Change |
|------|--------|
| `trading/indicators/mlp_features.py` | Add `FEATURE_SET_PAPER_MTF = "paper_mtf_44"`, `calculate_mlp_features_paper_mtf()`, `extract_single_features_paper_mtf()` |
| `mlp_trainer/src/dataset_builder.py` | Support MTF feature calculation in dataset building |
| `mlp_trainer/src/constants.py` | Add `V2_MTF_INPUT_DIM = 44` |
| `mlp_trainer/src/mlp_model.py` | No change needed (input_dim is configurable) |
| `trading/strategies/components/mlp_direction_entry.py` | Add MTF indicator computation from history buffer |

### Validation Criteria

- **Must beat v2_36 on Sharpe ratio** for at least 3 of 4 assets
- **MDD improvement expected** (macro context should reduce bear market entries)
- **Training convergence**: Must converge in <= 100 epochs (same as current)

---

## Phase 3: Temporal Ensemble

**Status**: COMPLETED — Result: STRONGLY POSITIVE (all metrics improved for all assets)
**Priority**: MEDIUM — Low-effort diversification of model predictions
**Estimated Effort**: 2-3 days
**Dependency**: Phase 1 complete (at minimum)
**Expected Impact**: +5-15% stability improvement, reduced variance of returns

### Phase 3 Results (2026-02-08)

**Ensemble dramatically improved all metrics for all assets** (weights: 0.15, 0.30, 0.35, 0.20):

| Asset | Single Return | Ensemble Return | MDD Single→Ensemble | Sharpe Single→Ensemble |
|-------|--------------|-----------------|---------------------|------------------------|
| BTC | +387.5% | **+450.0%** | -64.3% → **-39.9%** | 0.69 → **0.75** |
| ETH | +1270.6% | **+1452.4%** | -66.1% → **-54.2%** | 0.91 → **0.98** |
| SOL | +172.1% | **+1267.3%** | -61.2% → **-57.4%** | 0.51 → **0.94** |
| Portfolio | +610.1% | **+1056.6%** (+73%) | | |

**Optimal weights**: bwin3=0.15, bwin4=0.30, bwin5=0.35, bwin7=0.20

**Trained models**:
- `models/mlp_direction/multi_bwin3_fwin1/model_final.pt` (84.9% accuracy)
- `models/mlp_direction/eth_bwin4_fwin2/model_final.pt` (existing, ~62%)
- `models/mlp_direction/btc_bwin5_fwin2/model_final.pt` (existing, ~62%)
- `models/mlp_direction/multi_bwin7_fwin3/model_final.pt` (67.5% accuracy)

**Files created**:
- `trading/strategies/components/mlp_ensemble.py` — MLPEnsemblePredictor class
- `tests/trading/strategies/components/test_mlp_ensemble.py` — 12 unit tests
- `scripts/backtest/ensemble_comparison.py` — A/B comparison backtest

### Rationale

Different `bwin` (backward window) and `fwin` (forward window) parameters capture different market rhythms. A single bwin=5 model may miss patterns that bwin=3 or bwin=7 captures. Soft voting across multiple models reduces overfitting to a single temporal scale.

### Ensemble Architecture

```
Input Features (v2_36 or v2_mtf_44)
    │
    ├──► Model A (bwin=3, fwin=1) → [Hold, Buy, Sell] probabilities
    ├──► Model B (bwin=4, fwin=2) → [Hold, Buy, Sell] probabilities  ← current
    ├──► Model C (bwin=5, fwin=2) → [Hold, Buy, Sell] probabilities  ← current BTC
    └──► Model D (bwin=7, fwin=3) → [Hold, Buy, Sell] probabilities
                    │
                    ▼
            Soft Vote (weighted average)
                    │
                    ▼
            Final [Hold, Buy, Sell] → Action
```

### Implementation

**New file**: `trading/strategies/components/mlp_ensemble.py`

```python
class MLPEnsemblePredictor:
    """Soft-voting ensemble of multiple MLP models."""

    def __init__(self, model_configs: list[dict]):
        """
        model_configs: [
            {"model_path": "...", "weight": 0.25, "bwin": 3, "fwin": 1},
            {"model_path": "...", "weight": 0.35, "bwin": 4, "fwin": 2},
            ...
        ]
        """
        self.models = []
        self.weights = []
        for cfg in model_configs:
            model = MLPDirectionClassifier.load(cfg["model_path"])
            self.models.append(model)
            self.weights.append(cfg["weight"])

    def predict(self, features: np.ndarray) -> tuple[int, np.ndarray]:
        """Weighted soft vote across all models."""
        weighted_probs = np.zeros(3)
        for model, weight in zip(self.models, self.weights):
            probs = model.predict_proba(features)
            weighted_probs += weight * probs
        weighted_probs /= sum(self.weights)
        return np.argmax(weighted_probs), weighted_probs
```

### Configuration

```json
"mlp_direction_btc": {
  "ensemble": {
    "enabled": true,
    "models": [
      {"model_path": "models/mlp_direction/btc_bwin3_fwin1/model_final.pt", "weight": 0.2},
      {"model_path": "models/mlp_direction/btc_bwin4_fwin2/model_final.pt", "weight": 0.3},
      {"model_path": "models/mlp_direction/btc_bwin5_fwin2/model_final.pt", "weight": 0.3},
      {"model_path": "models/mlp_direction/btc_bwin7_fwin3/model_final.pt", "weight": 0.2}
    ]
  }
}
```

### Files to Modify

| File | Change |
|------|--------|
| `trading/strategies/components/mlp_ensemble.py` | **NEW** — `MLPEnsemblePredictor` class |
| `trading/strategies/components/mlp_direction_entry.py` | Add ensemble mode: if `ensemble.enabled`, use `MLPEnsemblePredictor` instead of single model |
| `trading/strategies/components/mlp_direction_exit.py` | Same ensemble integration for sell signal |
| `core/component_adapter.py` | Support ensemble in backtest adapter |
| `config/strategies/allocation.json` | Add `ensemble` block per strategy |

### Training Requirements

Must train additional models per asset:
```bash
# For each asset (BTC, ETH, SOL, BNB):
python -m mlp_trainer.src.mlp_train --bwin 3 --fwin 1 --symbol {ASSET}
python -m mlp_trainer.src.mlp_train --bwin 7 --fwin 3 --symbol {ASSET}
# bwin=4/fwin=2 and bwin=5/fwin=2 already exist
```

### Validation Criteria

- **Ensemble must beat best single model** on Sharpe ratio
- **Return variance reduction**: Rolling 6-month return std should decrease
- **Latency**: Ensemble inference < 10ms (4 models × ~0.5ms each)

---

## Phase 4: Asset Expansion — Add XRP

**Priority**: LOWER — Incremental portfolio diversification
**Estimated Effort**: 1-2 days
**Dependency**: Phase 1 complete — **use paper_36** (proven best performer)
**Expected Impact**: Portfolio diversification, +5-10% risk-adjusted portfolio improvement

### Rationale

XRP data already exists (`data/binance_xrp.db`). XRP has different market microstructure from BTC/ETH/SOL/BNB (legal risk cycles, different holder base), providing genuine diversification.

### Implementation Steps

1. **Generate dataset**:
   ```bash
   python -m mlp_trainer.src.dataset_builder --symbols XRPUSDT --feature-set v2_36
   ```

2. **Train model**:
   ```bash
   python -m mlp_trainer.src.mlp_train --symbol XRP --bwin 4 --fwin 2 --feature-set v2_36
   ```

3. **Backtest**: Run backtest on XRP to validate profitability

4. **Configure**: Add to `allocation.json`:
   ```json
   "mlp_direction_xrp": {
     "enabled": true,
     "market": "spot",
     "symbols": ["XRP"],
     "bwin": 4,
     "mlp_feature_set": "v2_36",
     "model_path": "models/mlp_direction/xrp_bwin4_fwin2/model_final.pt",
     "position_pct": 0.9,
     "position_size": 0.9,
     "volatility_sizing": {
       "enabled": true,
       "target_vol": 0.03,
       "min_scale": 0.25,
       "max_scale": 1.0
     },
     "entry": { "class": "MLPDirectionEntryStrategy", "params": {...} },
     "exit": { "class": "MLPDirectionExitStrategy", "params": {...} }
   }
   ```

5. **Update engine**: Add XRP to `symbols` list, add feed task

### Files to Modify

| File | Change |
|------|--------|
| `config/strategies/allocation.json` | Add `mlp_direction_xrp` strategy, add "XRP" to `symbols` |
| `config/symbol_defaults.json` | Verify XRP step_size and min_qty (likely step=0.1, min=0.1) |
| `scripts/backtest/backtest_mlp.py` | Add XRP to ASSET_DB mapping |
| `scripts/backtest/volatility_sizing_comparison.py` | Add XRP to ASSET_DB |

### Validation Criteria

- **XRP backtest must be net profitable** (total return > 0)
- **Sharpe > 0.3** on forward test window (2023-2026)
- **Must not degrade portfolio metrics** when added to existing 4-asset portfolio

---

## Execution Timeline

```
Phase 1 (Feature v2)        ████████████░░░░░░░░░░░░░░  Days 1-3
Phase 2 (MTF)               ░░░░░░░░░░░░████████████░░  Days 4-7
Phase 3 (Ensemble)          ░░░░░░░░░░░░░░░░████████░░  Days 6-9 (overlaps P2)
Phase 4 (XRP)               ░░░░░░░░░░░░░░░░░░░░████░░  Days 8-10
```

Each phase is independently deployable. Phase 1 should be completed before Phase 2 (MTF extends v2 features). Phase 3 can run in parallel with Phase 2 training. Phase 4 is independent and can run anytime after Phase 1.

## Risk Assessment

| Risk | Mitigation |
|------|------------|
| New features overfit to training data | Paper-aligned validation: train ≤2022, test 2023-2026 |
| MTF features leak future info | Strict forward-fill from lower TF to higher TF |
| Ensemble inference too slow | Pre-load all models at startup; 4×0.5ms = 2ms total |
| XRP model underperforms | Deploy disabled, enable only after live paper trading validation |
| Breaking live trading | Feature set is configurable per-strategy; old models continue working |

## Success Metrics

| Metric | Current (paper_36) | Phase 1 Target | Phase 2 Target | Phase 3 Target |
|--------|-------------------|----------------|----------------|----------------|
| BTC Return | +182% | +210%+ | +220%+ | +220%+ |
| Portfolio Sharpe | ~0.76 | 0.80+ | 0.85+ | 0.90+ |
| Max MDD | -35% | -32% | -28% | -28% |
| Win Rate | ~52% | 54%+ | 55%+ | 55%+ |
