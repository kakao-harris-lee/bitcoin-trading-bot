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


def _detect_project_root() -> Path:
    """Best-effort project root detection for local run and Docker."""
    # Local run: repo_root/web/app.py
    local_root = BASE_DIR.parent
    if (local_root / "logs").exists() or (local_root / "analysis").exists():
        return local_root

    # Docker run (default workdir=/app). We mount volumes under /app.
    docker_root = Path(os.getenv("PROJECT_ROOT", "/app"))
    return docker_root


PROJECT_ROOT = _detect_project_root()
LOG_DIR = Path(os.getenv("LOG_DIR", str(PROJECT_ROOT / "logs")))
KILL_SWITCH_FILE = Path(
    os.getenv("KILL_SWITCH_FILE", str(PROJECT_ROOT / "analysis" / "KILL_SWITCH"))
)


def load_trading_log(exchange: str):
    """Trading 로그 로드 (v2 engine 우선, 없으면 paper fallback)."""
    candidates = [
        LOG_DIR / f"v2_engine_{exchange}.json",
        LOG_DIR / f"paper_trading_{exchange}.json",
    ]

    for log_file in candidates:
        if log_file.exists():
            try:
                with open(log_file, 'r') as f:
                    return json.load(f)
            except Exception as e:
                print(f"로그 로드 실패 ({exchange}): {e}")
                return None
    return None


def _require_admin_token() -> bool:
    """Very small guard for mutating endpoints."""
    token = os.getenv("WEB_ADMIN_TOKEN")
    if not token:
        return False
    from flask import request
    return request.headers.get("X-Admin-Token") == token


@app.route("/")
def dashboard():
    """메인 대시보드"""
    return render_template("dashboard.html")


@app.route("/api/status")
def get_status():
    """현재 상태 API"""

    upbit_log = load_trading_log('upbit')
    binance_log = load_trading_log('binance')

    # 상태 구성
    status = {
        'timestamp': datetime.now().isoformat(),
        'upbit': {
            'enabled': upbit_log is not None,
            'exchange': 'upbit',
            'strategy': upbit_log.get('strategy', 'v35_optimized') if upbit_log else '-',
            'regime': upbit_log.get('regime', '-') if upbit_log else '-',
            'position': None,
            'statistics': None
        },
        'binance': {
            'enabled': binance_log is not None,
            'exchange': 'binance',
            'strategy': binance_log.get('strategy', 'SHORT_V1') if binance_log else '-',
            'position': None,
            'statistics': None
        }
    }

    if upbit_log:
        status['upbit']['statistics'] = upbit_log.get('statistics', {})
        btc_balance = upbit_log.get('btc_balance', 0) or 0
        if btc_balance > 0:
            status['upbit']['position'] = {
                'btc_balance': btc_balance,
                'cash_balance': upbit_log.get('current_cash', 0)
            }

    if binance_log:
        status['binance']['statistics'] = binance_log.get('statistics', {})
        position_size = binance_log.get('position_size', 0) or 0
        if position_size > 0:
            status['binance']['position'] = {
                'size': position_size,
                'entry_price': binance_log.get('entry_price', 0),
                'leverage': binance_log.get('leverage', 1)
            }

    return jsonify(status)


@app.route("/api/kill_switch/status")
def kill_switch_status():
    return jsonify({
        "active": KILL_SWITCH_FILE.exists(),
        "path": str(KILL_SWITCH_FILE),
        "checked_at": datetime.now().isoformat(),
    })


@app.route("/api/kill_switch/on", methods=["POST"])
def kill_switch_on():
    if not _require_admin_token():
        return jsonify({"error": "forbidden"}), 403
    KILL_SWITCH_FILE.parent.mkdir(parents=True, exist_ok=True)
    KILL_SWITCH_FILE.touch(exist_ok=True)
    return kill_switch_status()


@app.route("/api/kill_switch/off", methods=["POST"])
def kill_switch_off():
    if not _require_admin_token():
        return jsonify({"error": "forbidden"}), 403
    try:
        KILL_SWITCH_FILE.unlink(missing_ok=True)
    except TypeError:
        if KILL_SWITCH_FILE.exists():
            KILL_SWITCH_FILE.unlink()
    return kill_switch_status()


@app.route("/api/trades/<exchange>")
def get_trades(exchange: str):
    """거래 기록 API"""

    log = load_trading_log(exchange)

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

    upbit_log = load_trading_log('upbit')
    binance_log = load_trading_log('binance')

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
