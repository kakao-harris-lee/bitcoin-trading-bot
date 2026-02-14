# Regime Portfolio v3 Optimization (2026-02-14)

## Objective

- Portfolio-level upgrade on top of `RegimeLong v2` per-symbol signals.
- Structure:
  - BTC/SOL allocation caps
  - BNB momentum overlay
- Target:
  - Improve return and Sharpe
  - Check whether portfolio can exceed equal-weight B&H over 2021-01-01 ~ 2026-02-13

## Files

- Optimizer script: `scripts/backtest/optimize_regime_portfolio_v3.py`
- Report:
  - `reports/regime_portfolio_v3_opt_20260214_140819.md`
  - `reports/regime_portfolio_v3_opt_20260214_140819.csv`
  - `reports/regime_portfolio_v3_opt_20260214_140819.json`
- Tuned config:
  - `config/tuned/regime_portfolio_v3_best_20260214_140819.json`

## Search Space

- `btc_w`: 0.10, 0.15, 0.20, 0.25
- `sol_w`: 0.00, 0.05, 0.10
- `bnb_w`: 0.40, 0.50, 0.60, 0.70
- `bnb_overlay_boost`: 0.00, 0.05, 0.10, 0.15
- `eth_w = 1 - (btc_w + sol_w + bnb_w)` with bounds `[0.05, 0.50]`

Total valid trials: 180

## EW-Only Best (Reference, live_like signal)

- Weights: BTC 0.15 / ETH 0.05 / SOL 0.10 / BNB 0.70
- Overlay: +0.15
- Return: 2650.59%
- MDD: 42.57%
- Sharpe: 1.23
- Alpha vs EW B&H: +565.09%p
- Alpha vs matched-weight B&H: -61.09%p

Interpretation:
- Strong alpha vs equal-weight benchmark.
- Slight underperformance vs same-weight B&H, so this is highly BNB-beta concentrated.

## Selected Robust Candidate (default, live_like signal)

- Trial 156 (from top table)
- Weights: BTC 0.25 / ETH 0.05 / SOL 0.00 / BNB 0.70
- Overlay: +0.15
- Return: 2315.91%
- MDD: 42.65%
- Sharpe: 1.18
- Alpha vs EW B&H: +230.41%p
- Alpha vs matched-weight B&H: +61.65%p

Interpretation:
- Keeps positive alpha against both EW B&H and matched-weight B&H under live-like gating.
- More realistic candidate for deployment because signal semantics are aligned with runtime switch behavior.
