#!/usr/bin/env python3
"""
app.py
Flask 웹 대시보드 - Dual Exchange Paper Trading 모니터링
"""

from flask import Flask, render_template, jsonify
from flask_cors import CORS
import sqlite3
import json
import os
from pathlib import Path
from datetime import datetime

app = Flask(__name__)
CORS(app)

BASE_DIR = Path(__file__).parent
PROJECT_ROOT = BASE_DIR.parent
LOG_DIR = PROJECT_ROOT / "logs"


def load_paper_trading_log(exchange: str):
    """Paper Trading 로그 로드"""
    log_file = LOG_DIR / f"paper_trading_{exchange}.json"

    if log_file.exists():
        try:
            with open(log_file, 'r') as f:
                return json.load(f)
        except Exception as e:
            print(f"로그 로드 실패 ({exchange}): {e}")
            return None
    return None


@app.route("/")
def dashboard():
    """메인 대시보드"""
    return render_template("dashboard.html")


@app.route("/api/status")
def get_status():
    """현재 상태 API"""

    # Upbit Paper Trading
    upbit_log = load_paper_trading_log('upbit')

    # Binance Paper Trading
    binance_log = load_paper_trading_log('binance')

    # 상태 구성
    status = {
        'timestamp': datetime.now().isoformat(),
        'upbit': {
            'enabled': upbit_log is not None,
            'exchange': 'upbit',
            'strategy': 'v35_optimized',
            'position': None,
            'statistics': None
        },
        'binance': {
            'enabled': binance_log is not None,
            'exchange': 'binance',
            'strategy': 'SHORT_V1',
            'position': None,
            'statistics': None
        }
    }

    if upbit_log:
        status['upbit']['statistics'] = upbit_log.get('statistics', {})
        if upbit_log.get('btc_balance', 0) > 0:
            status['upbit']['position'] = {
                'btc_balance': upbit_log['btc_balance'],
                'cash_balance': upbit_log['current_cash']
            }

    if binance_log:
        status['binance']['statistics'] = binance_log.get('statistics', {})
        if binance_log.get('position_size', 0) > 0:
            status['binance']['position'] = {
                'size': binance_log['position_size'],
                'entry_price': binance_log.get('entry_price', 0),
                'leverage': binance_log.get('leverage', 1)
            }

    return jsonify(status)


@app.route("/api/trades/<exchange>")
def get_trades(exchange: str):
    """거래 기록 API"""

    log = load_paper_trading_log(exchange)

    if not log:
        return jsonify({'error': 'No data'}), 404

    trades = log.get('trades', [])

    # 최근 50개만
    recent_trades = trades[-50:] if len(trades) > 50 else trades

    return jsonify({
        'exchange': exchange,
        'trades': recent_trades,
        'total_count': len(trades)
    })


@app.route("/api/statistics")
def get_statistics():
    """통합 통계 API"""

    upbit_log = load_paper_trading_log('upbit')
    binance_log = load_paper_trading_log('binance')

    statistics = {
        'upbit': upbit_log.get('statistics', {}) if upbit_log else {},
        'binance': binance_log.get('statistics', {}) if binance_log else {}
    }

    # 합계 계산 (간단히 수익률 평균)
    if upbit_log and binance_log:
        upbit_return = statistics['upbit'].get('return_pct', 0)
        binance_return = statistics['binance'].get('return_pct', 0)

        statistics['combined'] = {
            'average_return_pct': (upbit_return + binance_return) / 2,
            'total_trades': (
                statistics['upbit'].get('total_trades', 0) +
                statistics['binance'].get('total_trades', 0)
            )
        }

    return jsonify(statistics)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=True)
