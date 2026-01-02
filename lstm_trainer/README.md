# LSTM Trend Trainer

PyTorch LSTM for Bitcoin H4 trend prediction.

## Quick Start

### Local Development (CPU)
```bash
python src/export_data.py --db-path ../data/upbit_bitcoin.db
python src/dev_mode.py
```

### GPU Training (Docker)
```bash
docker compose run trainer
```

### Download Model
```bash
scp server:~/lstm_trainer/models/trading_lstm.pth ./models/
```
