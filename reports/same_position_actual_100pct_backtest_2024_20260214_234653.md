# Actual Backtest Comparison (Forced 100% Position)

- Generated: 2026-02-14T23:46:53.411101
- Period: 2024-01-01 ~ 2024-12-31
- Initial capital: 10000
- Method: real re-run with forced full deployment (not linear normalization).

| Strategy | Type | Symbol | Return % | MDD % | Sharpe | Trades | B&H % | Alpha vs B&H % |
|---|---|---|---:|---:|---:|---:|---:|---:|
| wf_tree60_btc | walkforward_tree60 | BTC | 97.80 | -33.70 | 1.32 | 5 | 119.21 | -21.41 |
| mlp_direction_bnb | mlp_direction | BNB | 39.22 | -11.76 | 0.70 | 10 | 128.12 | -88.90 |
| mlp_direction_btc | mlp_direction | BTC | 7.83 | -2.56 | 0.74 | 19 | 119.21 | -111.38 |
| mlp_direction_eth | mlp_direction | ETH | 1.74 | -1.99 | 0.30 | 16 | 47.66 | -45.92 |

## Execution Notes
- `mlp_direction_*`: forced `position_pct=1.0` via temporary runtime override of allocation config.
- `wf_tree60_btc`: forced `position_size=1.0` via temporary runtime override of `WalkForwardStrategy`.
- Code/files were not permanently changed by this run.