# BTC/ETH LLM Scale-In Backtest Validation

## Context

The active paper strategy is now focused on `llm_direction_btc` and
`llm_direction_eth`. Entries are LLM-first with a regime fallback, existing
positions may scale in, and exits are protective rules such as bear-regime and
EMA deadcross exits. That makes a single profit-and-loss backtest insufficient:
the validation needs to separate strategy logic, LLM route behavior, execution
replay, and paper-vs-backtest drift.

## Validation Goals

1. Prove that the deterministic fallback and protective exit stack behaves
   sensibly without depending on live LLM availability.
2. Verify that scale-in entries are represented in backtests with average-entry
   accounting, not collapsed into a single position flag.
3. Compare paper trades against replayed backtest trades by day so missed,
   extra, and wrong-direction trades are visible.
4. Measure route-level behavior: primary LLM entries, fallback entries,
   protective exits, and their realized contribution.
5. Keep live-transition readiness separate from historical backtest returns.

## Test Layers

### 1. Deterministic Baseline

Run BTC and ETH using the same `allocation.json` sizing and exit settings while
forcing deterministic fallback behavior. This answers whether the fallback
entry plus protective exit structure is acceptable before assigning value to the
LLM route.

Primary metrics:

- total return and max drawdown
- profit factor
- exit count and average exit PnL
- regime-level performance
- scale-in count per completed position

### 2. LLM Strategy Replay

Replay the same component strategy through the backtest adapter using the
configured `LLMDecisionEntryStrategy`, fallback settings, volatility scaling,
and protective exit rules. This checks that the backtest engine can represent
the live trading shape, including repeated buys into an existing spot position.
The default backtest path forces the LLM entry to an offline HOLD decision so
the configured fallback can run deterministically without calling a live model.

Primary checks:

- repeated BUY actions are preserved as scale-ins
- average entry price updates after each scale-in
- `context_max_symbol_exposure_pct` caps further entries
- full exits realize PnL against the averaged position

### 3. Paper-vs-Backtest Comparison

Use `scripts/daily_comparison.py` and
`trading/risk/comparison_report.py` for day-level comparison. The report should
be run for each BTC/ETH LLM strategy after the paper session has generated
trades.

Example:

```bash
python scripts/daily_comparison.py --date 2026-05-08 --strategies llm_direction_btc llm_direction_eth --dry-run --no-notify
```

The comparison report is not a performance optimizer. It is a drift detector:
it should show whether paper execution produced trades the backtest did not
produce, whether the backtest expected trades that did not execute, and whether
directions diverged.

By default the CLI reads `data/paper_trading_results.db`, because the paper
executor persists fills there. Use `--db-path` only when comparing against a
different archived trading database.

Before running a comparison for recent paper trades, check OHLCV coverage:

```bash
python scripts/daily_comparison.py --coverage --strategies llm_direction_btc llm_direction_eth --no-notify
```

If the coverage max timestamp is older than the paper-trade date, update the
market data first; otherwise the comparison report will correctly fail with
`No market data`.

The regular collector is `scripts/auto_collect_data.py`. It updates BTC/ETH
`minute15`, `minute60`, `minute240`, and `day` tables incrementally across the
prefixes used by `DataLoader`, so scheduled collection must run it often enough
to keep the 4-hour backtest tables current.

## Acceptance Gates

Backtest validation should not promote the strategy alone. Use these gates as a
minimum review checklist:

- Backtest can run for both BTC and ETH from `allocation.json`.
- Scale-ins appear as separate BUY records in replay output.
- Completed positions calculate realized PnL from average entry.
- Daily paper-vs-backtest comparison runs without strategy lookup failures.
- Paper readiness over a 7-14 day window has enough exits to be meaningful.
- Route-level review shows whether profits/losses are dominated by fallback or
  primary LLM decisions.

## Known Limits

- Historical LLM calls are not guaranteed to be reproducible unless decisions
  are recorded and replayed. Treat live LLM replay as behavioral validation, not
  exact historical truth.
- Redis decision streams are useful for recent forensic analysis, but file or
  database logs are safer for multi-day preservation.
- The current comparison tool matches by timestamp tolerance and direction; it
  does not yet score quantity drift or route-level PnL attribution.
- The dashboard backtest can model a core hold sleeve via `core_hold_pct`, but
  the live runtime still stores one aggregate `positions:{symbol}:spot` record.
  Live scale-in and partial-exit accounting is supported, but true core/overlay
  sleeve protection needs explicit sleeve state before it can safely place large
  core orders or prevent overlay exits from liquidating core exposure.

## Next Extensions

1. Add a decision-log replay mode that consumes stored `strategy:decisions`
   instead of calling the LLM provider.
2. Add route attribution to comparison reports.
3. Add quantity-drift checks for scale-ins.
4. Add a weekly BTC/ETH validation command that emits one compact report for
   backtest metrics, paper readiness, and paper-vs-backtest drift.
5. Add sleeve-aware live position state before enabling `core_hold_pct` as an
   automatic live order target.
