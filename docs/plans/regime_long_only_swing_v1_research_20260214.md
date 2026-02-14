# Regime Long-Only Swing v1 Research Notes (2026-02-14)

## Scope

- Objective: Assess whether a practical long-only regime system can slightly beat 4-5 year B&H.
- Constraint: Use robust, low-complexity rules suitable for production operation.
- This note summarizes external research and maps it to implemented rules.

## External Research Takeaways

1. Crypto returns show momentum/trend persistence in some horizons, but not stably enough for naive daily trading edge.
2. Cross-sectional and macro-style factor structure exists (market, size, momentum), suggesting regime-aware exposure control is more realistic than pure directional prediction.
3. Trading frictions and market segmentation materially reduce paper alpha in real implementation.
4. Carry/basis can be a return source, but has crash risk and should be treated as conditional overlay, not always-on edge.

## Why the v1 Rule Set Was Chosen

- The strategy is intentionally simple:
1. Enter only after short-term regime confirmation (recent 4-day quorum).
2. Hold through normal noise.
3. Exit on fast downside breaks.
4. Re-enter only after cooldown.

- This maps to empirical lessons:
1. Trend persistence can be exploited only with filtering.
2. Over-trading daily noise is harmful.
3. Fast downside protection can reduce tail damage relative to always-hold.

## Implementation Link

- Design document: `docs/plans/regime_long_only_swing_v1_20260214.md`
- Backtest implementation: `scripts/backtest/compare_regime_long_only_v1.py`
- Latest comparison output:
  - `reports/regime_long_only_v1_compare_20260214_132853.md`
  - `reports/regime_long_only_v1_compare_20260214_132853.csv`
  - `reports/regime_long_only_v1_compare_20260214_132853.json`

## Current Result Interpretation

- For `2021-01-01` to `2026-02-13` on `BTC/ETH/SOL/BNB`, v1 did not beat B&H.
- Main reason is benchmark hardness:
  - This window includes strong multi-year upside in SOL/BNB.
  - Any risk-off exits create re-entry lag and lower upside capture in persistent rallies.
- Still, v1 shows operationally meaningful behavior:
  - Lower MDD than B&H in all tested symbols.
  - More controllable operational logic than high-frequency prediction systems.

## Practical Next Step (if objective is B&H+epsilon)

1. Keep long-only regime core.
2. Add conditional beta-amplifier layer (e.g., trend-leverage only in strongest regime).
3. Keep crash exits only for extreme breaks to reduce upside under-capture.

## Sources

- NBER w24877: Investor Attention and Cryptocurrency Performance
  - https://www.nber.org/papers/w24877
- NBER w25882: Common Risk Factors in Cryptocurrency
  - https://www.nber.org/papers/w25882
- Journal of Financial Economics (2020): Trading and Arbitrage in Cryptocurrency Markets
  - https://www.sciencedirect.com/science/article/pii/S0304405X19301746
- BIS Working Paper 1087 (rev. 2025): Cash-and-carry in crypto derivatives
  - https://www.bis.org/publ/work1087.htm
- NBER w32936 (2024): The Butterfly Effect of Crypto Market Frictions
  - https://www.nber.org/papers/w32936
