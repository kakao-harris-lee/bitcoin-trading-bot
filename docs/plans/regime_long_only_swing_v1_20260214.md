# Regime Long-Only Swing v1 (Implementation Plan)

## Goal

- Build a practical long-only system for 4-5 year operation.
- Prioritize return capture in bull/expanding regimes.
- Avoid forced trading in harsh downtrends.
- Compare against current MLP baseline and buy-and-hold (B&H).

## Strategy Thesis

- Daily prediction noise is high, so fully active day-trading is likely inefficient.
- A realistic structure is:
1. Enter only when short-term regime confirms upside persistence.
2. Hold while pullback is normal.
3. Exit quickly on sharp downside break.
4. Wait briefly, then re-evaluate regime for re-entry.

## Universe / Data / Horizon

- Symbols: `BTC`, `ETH`, `SOL`, `BNB`
- Data source: Binance OHLCV
- Canonical bar for this system: `day` (derived from `minute240` to keep symbol parity)
- Baseline evaluation horizon: `2021-01-01` to latest available date

## Rule Set (v1)

## 1) Regime scoring (daily)

For each day, assign one point for each condition:

1. `close > EMA20`
2. `EMA20 > EMA100`
3. `RSI14 > 50`
4. `20-day return > 0`

`risk_on_day = (score >= 3)`

## 2) Entry

- Lookback window: recent 4 days.
- Entry condition:
1. `risk_on_day` count in recent 4 days is at least 3.
2. Current close is above `EMA20`.
3. Not in cooldown period.

- Position: 100% notional long when in market.

## 3) Hold

- Continue holding while no hard-exit trigger fires.
- Track peak price after entry and monitor position drawdown.

## 4) Exit (fast downside defense)

Exit all on first matching trigger:

1. 1-day return <= `-6%`
2. 3-day cumulative return <= `-10%`
3. Close below `EMA100` for 2 consecutive days
4. Position drawdown from post-entry peak >= `12%`

## 5) Re-entry loop

- After exit, enforce cooldown: `3` days.
- After cooldown, return to entry logic.

## Execution Assumptions

- Long-only spot-like execution.
- Fee model: round-trip cost via per-side fee in simulation.
- No leverage in v1.

## Comparison Framework

For each symbol and equal-weight aggregate:

1. `B&H`
2. `Current MLP baseline` (active `allocation.json` MLP per symbol)
3. `Regime Long-Only Swing v1`

Report:

- Total Return (%)
- CAGR (%)
- MDD (%)
- Sharpe
- Trades
- Win Rate (%)
- Alpha vs B&H (%p)

## Acceptance Criteria (research stage)

- Primary: mean alpha vs B&H across symbols is close to flat or positive.
- Secondary: at least one major symbol beats B&H with acceptable operational simplicity.
- If underperforming: tune only a small set of robust parameters
  (`entry quorum`, `drop thresholds`, `cooldown`, `drawdown exit`) and re-check.

