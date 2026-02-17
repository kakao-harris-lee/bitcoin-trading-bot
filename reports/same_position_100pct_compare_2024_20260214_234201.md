# Same Position(100%) Performance Comparison (2024)

- Generated: 2026-02-14T23:42:01.822283
- Source: `data/backtest_history.db` latest completed run per strategy for 2024-01-01~2024-12-31
- Method: deployed-capital normalization (`return_pct / deployed_fraction`, `mdd_pct / deployed_fraction`)

| Strategy | Deployed % | Actual Return % | Return % @100% | Actual MDD % | MDD % @100% | Sharpe | Trades |
|---|---:|---:|---:|---:|---:|---:|---:|
| wf_tree60_btc | 80.00 | 78.75 | 98.44 | -28.10 | -35.12 | 1.31 | 5 |
| mlp_direction_eth | 5.00 | 1.74 | 34.80 | -1.99 | -39.80 | 0.30 | 16 |
| mlp_direction_btc | 25.00 | 7.83 | 31.32 | -2.56 | -10.24 | 0.74 | 19 |
| mlp_direction_bnb | 70.00 | 1.84 | 2.63 | -31.71 | -45.30 | 0.09 | 9 |

## Notes
- `wf_tree60_btc` uses hardcoded `position_size=0.8` in `scripts/backtest/walkforward_backtest.py`.
- Normalized metrics are for same-capital fairness check and can differ from full re-run because fees/path dependency are nonlinear.