#!/bin/bash
# Update OHLCV data for all symbols
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${ROOT_DIR}"

if [[ -f ".venv/bin/activate" ]]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

START=$(date -d '2 days ago' +%Y-%m-%d)
END=$(date -d 'tomorrow' +%Y-%m-%d)

# Update BTC
python scripts/collectors/binance_collector.py --start $START --end $END --timeframe minute60 2>/dev/null

# Update ETH and SOL
python -c "
import sqlite3
from pathlib import Path
import requests
from datetime import datetime

def update_db(symbol, db_file, table_prefix):
    db_path = Path('data') / db_file
    if not db_path.exists():
        return
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    url = 'https://api.binance.com/api/v3/klines'
    params = {'symbol': f'{symbol}USDT', 'interval': '1h', 'limit': 48}
    resp = requests.get(url, params=params)
    if resp.status_code != 200:
        return
    for k in resp.json():
        ts = datetime.utcfromtimestamp(k[0]/1000).strftime('%Y-%m-%dT%H:%M:%S')
        cursor.execute(f'''
            INSERT OR REPLACE INTO {table_prefix}_minute60
            (timestamp, open, high, low, close, volume)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (ts, float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5])))
    conn.commit()
    conn.close()

update_db('ETH', 'binance_ethereum.db', 'ethereum')
update_db('SOL', 'binance_solana.db', 'solana')
" 2>/dev/null

echo "$(date): OHLCV update complete" >> "${ROOT_DIR}/logs/ohlcv_update.log"
