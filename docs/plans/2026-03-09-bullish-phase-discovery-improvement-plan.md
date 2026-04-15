# Bullish-Phase Discovery Improvement Plan

Date: 2026-03-09
Goal: find coins entering a rising phase earlier, trade them with less selector churn, and avoid cutting winners too quickly.

## Design Targets

1. Reduce non-actionable selector churn.
2. Route more selector attention toward symbols with historically better edge.
3. Stop low-quality regime fallback entries when MLP explicitly rejects the trade.
4. Keep bullish entries alive longer by removing micro deadcross exits in bullish regimes.
5. Preserve paper-trading observability so the next soak period can validate the changes clearly.

## Implemented Changes

### 1. Selector routing and persistence
- Added per-symbol score multipliers so the selector can upweight stronger historical names and downweight chronic weak names.
- Added `min_consecutive_eligible` and `entry_ready_min_consecutive` so candidates must persist across refreshes before selection / alert escalation.
- BNB sleeve config now emphasizes breakout + EMA alignment more strongly than raw momentum.

### 2. Fallback entry policy separation
- Hybrid entry now distinguishes:
  - MLP unavailable / warmup
  - MLP non-BUY prediction
  - MLP low-confidence BUY
  - MLP safety-filter block
- BTC/ETH fallback is now restricted to unavailable/warmup cases and only in stronger bullish regimes.
- BNB sleeve can still use regime fallback for non-BUY MLP states, but only with tighter regime-entry quality rules.

### 3. Regime fallback quality upgrades
- RegimeLongV2 entry can now require:
  - close above EMA120
  - EMA5 above EMA20
  - minimum volume ratio
  - minimum proximity to the 20-bar breakout level
- BNB sleeve fallback now requires stronger multi-check confirmation so it favors coins already transitioning into bullish structure.

### 4. Bullish hold protection
- Added regime-aware blocking for EMA deadcross exits.
- BTC deadcross exits are now suppressed in `BULL_STRONG`, `BULL_MODERATE`, and `SIDEWAYS_UP`, and require more hold bars / streak persistence when active.

### 5. Freshness bottleneck mitigation
- BNB selector and DQ freshness thresholds were relaxed moderately.
- DQ eviction cooldown was shortened so stale symbols recover faster once feed quality returns.

## Expected Effects

1. Fewer selector alerts with no downstream trades.
2. Lower exposure to structurally weak, high-churn symbols.
3. Fewer BTC 11-53 second round trips.
4. Better chance of holding coins after early bullish transition instead of exiting on weak fallback noise.

## Next Validation Window

Monitor for 24-72 hours after restart:
- selector `ENTRY_READY` / `NEW_CANDIDATE` conversion
- `avg_dq_blocked_ratio`
- `stale_reject_ratio`
- BNB sleeve trade count and symbol mix
- BTC short-hold exits under 60 seconds
- ETH `regime_protect` exit share

## Follow-up Triggers

1. If selector conversion remains near zero while stale rejection stays high, investigate feed freshness rather than strategy thresholds.
2. If BTC still churns, disable deadcross completely for the BTC sleeve.
3. If BNB sleeve remains idle, tighten the universe further around boosted symbols only.
4. If ETH still exits mainly via `regime_protect`, harden fallback entry further or raise regime-protect hold tolerance again.
