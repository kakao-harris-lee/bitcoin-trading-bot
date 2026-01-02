# LSTM Trend Prediction Trainer

## Quick Start

### Local Development (CPU)
```bash
# Export data from main trading bot
python src/export_data.py --db-path ../data/upbit_bitcoin.db

# Quick validation with recent data
python src/dev_mode.py --days 30
```

### GPU Training (Docker)
```bash
# Build and run training
docker compose run trainer

# Or start Jupyter notebook
docker compose up notebook
```

### Production
Copy trained model to trading bot:
```bash
cp models/trading_lstm.pth ../models/
```
