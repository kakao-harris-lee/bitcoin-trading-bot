# Complexity Hotspot Refactor Plan (2026-02-17)

> Archived note (2026-04-24): this document was written for an older architecture that included removed futures, short, hedge, or multi-exchange paths. The active runtime is Binance spot-only, so use this file only as historical reference.


## Baseline (lizard/radon)
- Scope: `trading`, `core`, `scripts`, `web` (deprecated upbit refs excluded)
- `CCN > 15`: 42 functions
- Top hotspots:
  - `scripts/backtest_risk_based_sizing.py:107` `RiskBasedBacktester.run` (CCN 45)
  - `trading/core/paper_readiness.py:86` `evaluate_paper_readiness` (CCN 44)
  - `scripts/backtest/walkforward_backtest.py:264` `WalkForwardStrategy.__call__` (CCN 34)
  - `web/app.py:845` `get_trades` (CCN 34)
  - `web/app.py:2313` `get_exchange_balances` (CCN 32)

## Completed (P0)
- Target: `trading/core/paper_readiness.py:269`
- Action: split monolithic readiness evaluation into:
  - `_collect_paper_exit_metrics`
  - `_append_collection_warnings`
  - `_aggregate_metrics`
  - `_append_readiness_threshold_errors`
  - `_build_report`
- Result:
  - `evaluate_paper_readiness`: `CCN 44 -> 7`
  - File warnings: none above lizard default threshold
  - Tests: `tests/trading/core/test_paper_readiness.py` passed

## Completed (P1)
- Target: `scripts/backtest_risk_based_sizing.py:366`
- Action:
  - Split run-time responsibilities into helpers:
    - `_create_risk_config`
    - `_init_core_overlay`
    - `_update_core_overlay_state`
    - `_handle_buy_signal`
    - `_handle_sell_signal`
    - `_record_equity_point`
    - `_close_remaining_position`
  - Simplified result generation:
    - `_empty_results`
    - `_closed_trade_stats`
- Result:
  - `RiskBasedBacktester.run`: `CCN 45 -> 9`
  - `_generate_results`: `CCN 21 -> 7`
  - `_update_core_overlay_state`: `CCN 20 -> 7`
  - File warnings: none above lizard default threshold
  - Syntax check: `python -m py_compile scripts/backtest_risk_based_sizing.py`

## Completed (P2)
- Target: `scripts/backtest/walkforward_backtest.py:264` `WalkForwardStrategy.__call__`
- Action:
  - Split monolithic decision flow into state-specific helpers:
    - `_initial_entry_signal`
    - `_in_position_signal`
    - `_stage2_scale_in_signal`
    - `_risk_exit_signal`
    - `_model_sell_exit_signal`
    - `_out_of_position_signal`
    - `_model_buy_reentry_signal`
    - `_cooldown_reentry_signal`
- Result:
  - `WalkForwardStrategy.__call__`: `CCN 34 -> 6`
  - Intermediate file warning reduced to single remaining hotspot: `run_walkforward_asset` (CCN 28)
  - Syntax check: `python -m py_compile scripts/backtest/walkforward_backtest.py`

## Completed (P3)
- Target: `scripts/backtest/walkforward_backtest.py:488` `run_walkforward_asset`
- Action:
  - Extracted orchestration helpers:
    - `_raise_if_cancelled`
    - `_print_walkforward_header`
    - `_collect_oos_predictions`
    - `_run_stitched_backtest`
  - Kept fold-level math/training in dedicated helpers added earlier:
    - `_build_fold_data`
    - `_run_fold_models`
    - `_store_fold_predictions`
    - `_print_fold_summary`
- Result:
  - `run_walkforward_asset`: `CCN 28 -> 10`
  - `walkforward_backtest.py` lizard warnings: none
  - Syntax check: `python -m py_compile scripts/backtest/walkforward_backtest.py`

## Completed (P4)
- Target: `web/app.py:845` `get_trades`
- Action:
  - Extracted route helpers:
    - `_parse_trade_query_params`
    - `_is_paper_mode_active`
    - `_filter_trade_history`
    - `_paginate_trades`
    - `_summarize_filtered_trades`
  - Converted summary aggregation to single-pass loop to avoid comprehension-driven CCN growth.
- Result:
  - `get_trades`: `CCN 34 -> 1`
  - New helpers stay below lizard threshold (`_filter_trade_history` CCN 15, `_summarize_filtered_trades` CCN 11)
  - `web/app.py` warning count: `8 -> 7`
  - Syntax check: `python -m py_compile web/app.py`
  - Note: `tests/test_web_api.py` currently skipped in this environment (0 collected / 1 skipped).

## Completed (P5)
- Target: `web/app.py:2367` `get_exchange_balances`
- Action:
  - Split paper/live composition into dedicated helpers:
    - `_build_spot_paper_positions`
    - `_build_futures_paper_positions`
    - `_build_paper_exchange_balances`
    - `_build_spot_live_positions`
    - `_build_futures_live_positions`
    - `_compose_exchange_balance_payload`
  - Added small parsing guards:
    - `_safe_float`
    - `_safe_int`
  - Kept response schema and error envelope unchanged.
- Result:
  - `get_exchange_balances`: `CCN 32 -> 5`
  - Syntax check: `python -m py_compile web/app.py`

## Completed (P6)
- Target: `web/services/backtest_runner.py:1506` `_run_walkforward_backtest`
- Action:
  - Extracted walk-forward defaults/param resolution:
    - `_resolve_walkforward_asset`
    - `_resolve_wf_param`
    - `_resolve_walkforward_params`
    - `_load_walkforward_runtime_settings`
  - Extracted progress/equity/trade/result composition:
    - `_make_walkforward_progress_callback`
    - `_build_walkforward_equity_curve`
    - `_sample_walkforward_trades`
    - `_format_walkforward_trades`
    - `_compute_walkforward_trade_metrics`
    - `_load_walkforward_price_data`
    - `_build_walkforward_response`
- Result:
  - `_run_walkforward_backtest`: `CCN 30 -> 2`
  - Syntax check: `python -m py_compile web/services/backtest_runner.py`

## Completed (P7)
- Target: `web/app.py:1573` `get_summary`
- Action:
  - Extracted summary assembly helpers:
    - `_new_summary`
    - `_build_paper_summary_positions`
    - `_populate_paper_summary`
    - `_build_live_summary_spot_positions`
    - `_build_live_summary_futures_positions`
    - `_populate_live_summary`
    - `_finalize_summary`
  - Reused new numeric guards and side normalization:
    - `_safe_float`
    - `_safe_int`
    - `_normalize_futures_side`
- Result:
  - `get_summary`: `CCN 30 -> 6`
  - Syntax check: `python -m py_compile web/app.py`

## Completed (P8)
- Target: `web/app.py:1419` `get_positions`
- Action:
  - Extracted live-mode assembly helpers:
    - `_new_live_positions_result`
    - `_calculate_unrealized_pct`
    - `_append_live_spot_positions`
    - `_append_live_futures_positions`
  - Reused shared live helpers:
    - `_build_binance_client`
    - `_load_live_price_map`
- Result:
  - `get_positions`: `CCN 21 -> 4`
  - Syntax check: `python -m py_compile web/app.py`

## Completed (P9)
- Target: `web/app.py:1898` `get_strategies`
- Action:
  - Extracted strategy projection helpers:
    - `_strategy_class_name`
    - `_build_regime_routing_payload`
    - `_load_strategy_live_state`
    - `_load_strategy_active_positions`
    - `_build_strategy_info`
    - `_build_available_strategies`
  - Kept deprecated filtering and available strategy semantics unchanged.
- Result:
  - `get_strategies`: `CCN 28 -> 6`
  - Syntax check: `python -m py_compile web/app.py`

## Completed (P10)
- Target: `web/services/backtest_runner.py:418` `get_available_strategies`
- Action:
  - Split strategy source loading/merge steps:
    - `_load_allocation_strategies`
    - `_append_factory_strategies`
    - `_append_allocation_only_strategies`
    - `_append_backtest_only_strategies`
- Result:
  - `get_available_strategies`: `CCN 16 -> 1`
  - Syntax check: `python -m py_compile web/services/backtest_runner.py`

## Completed (P11)
- Target: `web/app.py:547` `get_status`
- Action:
  - Extracted status pipeline helpers:
    - `_read_status_prices`
    - `_load_status_prices_and_regimes`
    - `_load_status_risk`
    - `_build_status_asset_from_position`
    - `_build_status_assets_from_positions`
    - `_build_status_fallback_assets`
    - `_build_stream_status`
    - `_load_stream_status`
    - `_build_minimal_status`
- Result:
  - `get_status`: `CCN 19 -> 3`
  - Syntax check: `python -m py_compile web/app.py`

## Completed (P12)
- Target: `web/app.py:2922` `get_trade_log`
- Action:
  - Extracted parsing/filter/aggregation helpers:
    - `_parse_trade_log_filters`
    - `_trade_log_file_path`
    - `_trade_log_summary_template`
    - `_matches_trade_log_filters`
    - `_update_trade_log_summary`
    - `_load_trade_log_entries`
    - `_build_trade_log_response`
- Result:
  - `get_trade_log`: `CCN 22 -> 4`
  - Syntax check: `python -m py_compile web/app.py`

## Completed (P13)
- Target: `web/app.py:1271` `get_daily_analytics`
- Action:
  - Extracted daily analytics helpers:
    - `_normalize_analytics_period`
    - `_is_paper_mode`
    - `_mode_filtered_trades`
    - `_filter_trades_by_period`
    - `_empty_daily_stats`
    - `_aggregate_daily_trade_stats`
    - `_daily_stats_list`
    - `_daily_summary`
- Result:
  - `get_daily_analytics`: `CCN 24 -> 1`
  - Syntax check: `python -m py_compile web/app.py`

## Updated Lizard Warning Set
- `web/app.py` + `web/services/backtest_runner.py`: `CCN > 15` warnings `0`
- Full-scope snapshot (`trading/core/scripts/web`): warning count `28` (from baseline `42`)

## Next Refactor Queue
1. `scripts/paper/run_soak_vs_bnh.py:357` `main`
   - Split scenario orchestration and report output stages.
   - Goal: `CCN <= 18`
2. `scripts/regime/evaluate_regime_ensemble.py:147` `main`
   - Isolate config loading, metric computation, and rendering paths.
   - Goal: `CCN <= 18`

## Guardrail
- After each step:
  - run targeted unit tests first
  - rerun `lizard` for touched file
  - preserve API/output payload compatibility
