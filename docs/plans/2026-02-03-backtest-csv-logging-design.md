# Backtest CSV Logging Design

## Overview

백테스팅 실행 시 전략의 전체 상태를 CSV 파일로 기록하여 분석할 수 있는 기능.

## Requirements

- 매 캔들마다 전체 상태 기록 (가격, 포지션, 자산, 지표, 시그널, 레짐)
- 백테스트당 1개 파일 생성
- CLI와 대시보드 모두에서 사용 가능
- 대시보드에서 CSV 다운로드 제공

## CSV Structure

### File Location & Naming

```
backtest_logs/
└── {strategy}_{symbol}_{datetime}.csv
    # Example: short_v1_BTC_2026-02-03_143052.csv
```

### Columns

| Category | Columns |
|----------|---------|
| Time/Price | timestamp, open, high, low, close, volume |
| Position | position, position_qty, entry_price |
| Portfolio | portfolio_value, cash, unrealized_pnl, realized_pnl, cumulative_pnl |
| Risk | drawdown, drawdown_pct, high_water_mark |
| Signal | signal, signal_reason |
| Regime | regime |
| Indicators | mfi, adx, bb_width, rsi, ema_200 (strategy-dependent) |

## Architecture

### New Class: BacktestLogger

Location: `core/backtest_logger.py`

```python
class BacktestLogger:
    def __init__(self, strategy_name: str, symbol: str, output_dir: str = "backtest_logs")
    def log_candle(self, state: dict) -> None
    def flush(self) -> str  # Returns filepath
    def get_filepath(self) -> str
```

### Integration Points

| File | Changes |
|------|---------|
| `core/backtester.py` | Add `csv_log` parameter, integrate BacktestLogger |
| `core/component_adapter.py` | Add `get_state_snapshot()` method |
| `scripts/backtest/_common.py` | Add `--csv-log` CLI option |
| `web/quant_lab/routes.py` | Add download endpoints |

## API Endpoints

```
GET /api/backtest/logs
  → List saved CSV files

GET /api/backtest/logs/<filename>/download
  → Download CSV file
```

## Usage

### CLI

```bash
python scripts/backtest/short_v1.py --csv-log
# Output: "CSV saved: backtest_logs/short_v1_BTC_2026-02-03_143052.csv"
```

### Dashboard

Quant Lab optimization results will include "Download CSV Log" button for best trial.
