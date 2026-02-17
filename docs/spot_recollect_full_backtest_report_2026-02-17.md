# Spot Recollect + Full Backtest Report (2026-02-17)

## 1) Scope
- Requested workflow executed end-to-end:
  - Spot-only data recollection (all trading assets)
  - Indicator calculation/parity verification
  - Full backtest run for all enabled live-paper strategies
  - Chart regeneration and artifact validation

## 2) Spot Data Recollection
- Script: `scripts/collectors/recollect_spot_all_assets.py`
- Command:
  - `python scripts/collectors/recollect_spot_all_assets.py --start 2020-01-01 --end 2026-02-18`
- Covered assets/tables:
  - BTC: `btc_*` and `binance_*` (`minute15`, `minute60`, `minute240`, `day`)
  - ETH: `ethereum_*` and `binance_*` (`minute15`, `minute60`, `minute240`, `day`)
  - SOL: `solana_*` (`minute15`, `minute60`, `minute240`, `day`)
  - BNB: `bnb_*` (`minute60`, `minute240`, `day`)
  - XRP: `xrp_*` (`minute15`, `minute60`, `minute240`, `day`)
- Funding tables were cleared to prevent futures contamination:
  - `*_funding_rate` row count = 0

## 3) Indicator Calculation Verification
- Verification script:
  - `scripts/validate_binance_indicator_parity.py`
- Command:
  - `python scripts/validate_binance_indicator_parity.py --start 2024-01-01 --end 2025-01-01 --interval 4h --market auto --output docs/binance_indicator_parity_report_2026-02-17_after_spot_recollect.md`
- Result:
  - `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`, `XRPUSDT` all selected as `spot`
  - OHLC/volume/major indicators (RSI/MFI/ADX/BB/MACD) max diff = 0
- Report:
  - `docs/binance_indicator_parity_report_2026-02-17_after_spot_recollect.md`

## 4) Full Backtest Execution (Enabled Strategies)
- Date range: `2020-01-01` ~ `2026-02-17`
- Initial capital: `10,000`
- Enabled strategies from `config/strategies/allocation.json`:
  - `mlp_direction_btc`
  - `mlp_direction_eth`
  - `mlp_direction_bnb`
- Run output:
  - `reports/spot_full_backtest_2020-01-01_2026-02-17_20260217_181506.json`
  - `reports/spot_full_backtest_2020-01-01_2026-02-17_20260217_181506.csv`
  - `reports/spot_full_backtest_2020-01-01_2026-02-17_20260217_181506.md`

## 5) Performance Summary
| strategy | return % | benchmark(B&H) % | alpha vs B&H % | MDD % | Sharpe | trades | win rate % | profit factor |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| mlp_direction_btc | 37.48 | 853.53 | -816.05 | -9.16 | 0.36 | 66 | 42.42 | 2.12 |
| mlp_direction_eth | 12.41 | 1434.82 | -1422.41 | -2.93 | 0.44 | 104 | 37.50 | 2.29 |
| mlp_direction_bnb | 409.51 | 4439.26 | -4029.75 | -22.81 | 0.54 | 70 | 38.57 | 1.96 |

## 6) Regenerated Charts (Verified Existing)
- BTC:
  - `web/static/charts/backtest_mlp_direction_btc_26d5daa2.png`
  - `web/static/charts/regime_mlp_direction_btc_26d5daa2.png`
- ETH:
  - `web/static/charts/backtest_mlp_direction_eth_9251c26d.png`
  - `web/static/charts/regime_mlp_direction_eth_9251c26d.png`
- BNB:
  - `web/static/charts/backtest_mlp_direction_bnb_0c4103b3.png`
  - `web/static/charts/regime_mlp_direction_bnb_0c4103b3.png`
- Yearly chart directories were also generated for each strategy run:
  - `web/static/charts/yearly_mlp_direction_btc_26d5daa2`
  - `web/static/charts/yearly_mlp_direction_eth_9251c26d`
  - `web/static/charts/yearly_mlp_direction_bnb_0c4103b3`

## 7) Notes
- `MLflow not installed, tracking disabled` message appeared during run; backtest/chart artifacts were generated normally.
- `scripts/auto_collect_data.py` has been updated to spot mode for ETH/SOL collection:
  - `ccxt.binanceusdm` -> `ccxt.binance`
  - `ETH/USDT:USDT`, `SOL/USDT:USDT` -> `ETH/USDT`, `SOL/USDT`
