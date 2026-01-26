# Volatility Breakout & LSTM Scaling Design

**Date:** 2026-01-26
**Status:** Approved
**Author:** Claude

## Overview

Extend the Binance data collector to add:
1. Larry Williams Volatility Breakout indicators (target_price from prev day high/low)
2. LSTM preprocessing with MinMax scaling (global + rolling)

## Requirements

### Volatility Breakout Strategy
- Calculate on **daily** data: previous day high, low, range
- Apply to **hourly** data: target_price = open + (prev_day_range × k)
- k value is configurable and optimizable via Optuna (default: 0.5)
- Generate breakout_signal (1 if close > target_price)

### LSTM Scaling
- **Global MinMax**: Scale all numeric columns to 0-1 using full dataset min/max
- **Rolling MinMax**: Scale using recent 720 hours (30 days) window
- Automatically detect and scale all numeric columns
- Store scaling parameters in metadata table for reproducibility

## Data Schema

### New Columns (binance_minute60)

| Column | Type | Description |
|--------|------|-------------|
| `prev_day_high` | REAL | Previous day's high price |
| `prev_day_low` | REAL | Previous day's low price |
| `prev_day_range` | REAL | prev_day_high - prev_day_low |
| `target_price` | REAL | open + (prev_day_range × k) |
| `breakout_signal` | INTEGER | 1 if close > target_price, else 0 |
| `{col}_scaled` | REAL | Global MinMax scaled (0-1) |
| `{col}_scaled_rolling` | REAL | Rolling MinMax scaled (30-day window) |

### New Table: scaling_params

```sql
CREATE TABLE scaling_params (
    column_name TEXT PRIMARY KEY,
    min_value REAL NOT NULL,
    max_value REAL NOT NULL,
    rolling_window INTEGER,
    updated_at TEXT NOT NULL
);
```

## Implementation

### Location
Extend `scripts/collectors/binance_collector.py`

### New Methods

```python
class BinanceSQLiteCollector:

    def _get_prev_day_data(self, date: str) -> tuple[float, float]:
        """Get previous day's high and low from binance_day table."""

    def add_volatility_breakout(
        self,
        timeframe: str = 'minute60',
        k: float = 0.5
    ) -> int:
        """Add volatility breakout indicators to hourly data.

        1. Load hourly data
        2. Join with daily data for prev day high/low
        3. Calculate target_price and breakout_signal
        4. Update table with new columns

        Returns: Number of rows updated
        """

    def add_scaled_columns(
        self,
        timeframe: str = 'minute60',
        rolling_window: int = 720,
        exclude_cols: list = ['timestamp', 'breakout_signal']
    ) -> int:
        """Add LSTM scaling columns.

        1. Auto-detect numeric columns
        2. Calculate global MinMax → {col}_scaled
        3. Calculate rolling MinMax → {col}_scaled_rolling
        4. Save scaling params to metadata table

        Returns: Number of columns added
        """

    def collect_with_features(
        self,
        start_date: str,
        end_date: str,
        k: float = 0.5
    ):
        """Full collection pipeline with feature computation.

        1. Collect daily data first (dependency)
        2. Collect hourly data
        3. Add volatility breakout indicators
        4. Add scaled columns
        """
```

### CLI Extension

```bash
# Full collection with features
python -m scripts.collectors.binance_collector \
    --start 2020-01-01 \
    --with-features \
    --k 0.5

# Add features to existing data
python -m scripts.collectors.binance_collector --add-features

# Scale only (no volatility breakout)
python -m scripts.collectors.binance_collector --scale-only
```

## Processing Flow

```
1. fetch_klines() - Collect OHLCV
           ↓
2. Query binance_day for prev day high/low
           ↓
3. Calculate volatility breakout indicators
   - prev_day_range = high - low
   - target_price = open + range × k
   - breakout_signal = close > target_price
           ↓
4. Batch scaling (after full collection)
   - Global MinMax: (x - min) / (max - min)
   - Rolling MinMax: 720-hour window
           ↓
5. Save to DB (INSERT OR REPLACE)
```

## Optuna Integration

Add to `web/quant_lab/optimizer/objective.py`:

```python
def volatility_breakout_objective(trial: optuna.Trial, df: pd.DataFrame):
    k = trial.suggest_float('breakout_k', 0.3, 0.7, step=0.05)

    df['target_price'] = df['open'] + df['prev_day_range'] * k
    df['breakout_signal'] = (df['close'] > df['target_price']).astype(int)

    return run_backtest(df, strategy='volatility_breakout')
```

## Configuration

Add to `config/strategies/allocation.json`:

```json
{
  "volatility_breakout": {
    "enabled": true,
    "k": 0.5,
    "entry_after_hour": 9,
    "exit_before_close": true
  }
}
```

## Usage Examples

### Data Collection
```bash
python -m scripts.collectors.binance_collector \
    --start 2020-01-01 --with-features --k 0.5
```

### Backtest Access
```python
from core.data_loader import DataLoader

loader = DataLoader()
df = loader.load_timeframe('minute60', start='2021-01-01')

# Volatility breakout signals
entries = df[df['breakout_signal'] == 1]

# LSTM training data (scaled)
scaled_cols = [c for c in df.columns if c.endswith('_scaled')]
X = df[scaled_cols].values
```

### Quant Lab Optimization
1. Dashboard → Quant Lab → Strategy: `volatility_breakout`
2. Search Space: `k: [0.3, 0.7]`
3. Run optimization
4. Apply best k value

## Dependencies

- Daily data must be collected before hourly (for prev day lookup)
- Scaling runs as batch after full data collection
- For real-time updates, only rolling scaling is updated

## Testing

1. Unit tests for `_get_prev_day_data()`
2. Integration test for `add_volatility_breakout()`
3. Verify scaling produces values in [0, 1] range
4. Backtest validation for breakout signals
