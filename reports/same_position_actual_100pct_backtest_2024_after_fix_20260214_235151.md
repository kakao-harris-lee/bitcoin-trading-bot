# Actual Backtest Comparison (Forced 100% Position, After Sizing Fix)

- Generated: 2026-02-14T23:51:51.900404
- Period: 2024-01-01 ~ 2024-12-31
- Initial capital: 10000
- Method: real re-run with forced full deployment (after `use_signal_quantity` fix).

| Strategy | Type | Symbol | Return % | MDD % | Sharpe | Trades | B&H % | Alpha vs B&H % |
|---|---|---|---:|---:|---:|---:|---:|---:|
| wf_tree60_btc | walkforward_tree60 | BTC | 97.80 | -33.70 | 1.32 | 5 | 119.21 | -21.41 |
| mlp_direction_btc | mlp_direction | BTC | 0.00 | 0.00 | 0.00 | 0 | 119.21 | -119.21 |
| mlp_direction_bnb | mlp_direction | BNB | 0.00 | 0.00 | 0.00 | 0 | 128.12 | -128.12 |
| mlp_direction_eth | mlp_direction | ETH | -7.25 | -18.68 | -0.12 | 5 | 47.66 | -54.91 |

## Execution Notes
- `mlp_direction_*`: forced `position_pct=1.0` and `use_signal_quantity=false` at runtime.
- `wf_tree60_btc`: forced `position_size=1.0` via temporary runtime override of `WalkForwardStrategy`.
- Code/files were not permanently changed by this run except committed sizing fix/config updates.