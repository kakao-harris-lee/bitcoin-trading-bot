# WF Tree60 Grid Tuning (Stage Reentry + Trailing DD)

- Generated: 2026-02-15T08:44:31.521074
- Period: 2024-01-01 ~ 2024-12-31
- Capital: 10000
- Chart: `web/static/charts/wf_tree60_btc_grid_best_vs_baseline_20260215_084254.png`
- Chart: `web/static/charts/wf_tree60_eth_grid_best_vs_baseline_20260215_084431.png`

| Asset | Variant | Return % | MDD % | Sharpe | Trades | Alpha vs B&H % |
|---|---|---:|---:|---:|---:|---:|
| BTC | baseline_v1 | -16.00 | -24.97 | -0.63 | 5 | -135.21 |
| BTC | best_return_grid | -6.34 | -16.69 | -0.24 | 7 | -125.55 |
| ETH | baseline_v1 | 10.21 | -21.25 | 0.41 | 5 | -37.45 |
| ETH | best_return_grid | 3.59 | -25.25 | 0.23 | 5 | -44.07 |

## Best Params (Return)
- BTC: {'cooldown_reentry_enabled': True, 'cooldown_reentry_requires_buy': True, 'min_bars_after_risk_exit': 24, 'reentry_trend_filter_enabled': True, 'reentry_ema_span': 50, 'reentry_require_ema_rising': True, 'staged_reentry_enabled': True, 'reentry_stage2_fraction': 0.8, 'stage2_confirm_bars': 6, 'reentry_stage1_fraction': 0.55, 'stage2_trigger_pct': 0.8, 'trailing_drawdown_exit_pct': 10.0}
- ETH: {'cooldown_reentry_enabled': True, 'cooldown_reentry_requires_buy': True, 'min_bars_after_risk_exit': 24, 'reentry_trend_filter_enabled': True, 'reentry_ema_span': 50, 'reentry_require_ema_rising': True, 'staged_reentry_enabled': True, 'reentry_stage2_fraction': 0.8, 'stage2_confirm_bars': 6, 'reentry_stage1_fraction': 0.55, 'stage2_trigger_pct': 0.8, 'trailing_drawdown_exit_pct': 14.0}

## Best Params (MDD >= -25, max return)
- BTC: {'cooldown_reentry_enabled': True, 'cooldown_reentry_requires_buy': True, 'min_bars_after_risk_exit': 24, 'reentry_trend_filter_enabled': True, 'reentry_ema_span': 50, 'reentry_require_ema_rising': True, 'staged_reentry_enabled': True, 'reentry_stage2_fraction': 0.8, 'stage2_confirm_bars': 6, 'reentry_stage1_fraction': 0.55, 'stage2_trigger_pct': 0.8, 'trailing_drawdown_exit_pct': 10.0}
- ETH: {'cooldown_reentry_enabled': True, 'cooldown_reentry_requires_buy': True, 'min_bars_after_risk_exit': 24, 'reentry_trend_filter_enabled': True, 'reentry_ema_span': 50, 'reentry_require_ema_rising': True, 'staged_reentry_enabled': True, 'reentry_stage2_fraction': 0.8, 'stage2_confirm_bars': 6, 'reentry_stage1_fraction': 0.55, 'stage2_trigger_pct': 0.8, 'trailing_drawdown_exit_pct': 10.0}