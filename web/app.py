#!/usr/bin/env python3
"""
app.py
Flask 웹 대시보드 - Dual Exchange Paper Trading 모니터링
"""

from flask import Flask, render_template, jsonify
from flask_cors import CORS
import secrets
import json
import os
import requests
from pathlib import Path
from datetime import datetime

app = Flask(__name__)
CORS(app)

BASE_DIR = Path(__file__).parent

# 대시보드 비밀 경로 (환경변수 또는 랜덤 생성)
DASHBOARD_SECRET_PATH = os.getenv("DASHBOARD_SECRET_PATH") or secrets.token_urlsafe(16)


def load_allocation_config() -> dict:
    """Load strategy allocation config."""
    config_path = BASE_DIR.parent / 'config' / 'strategies' / 'allocation.json'
    if config_path.exists():
        try:
            with open(config_path) as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _detect_project_root() -> Path:
    """Best-effort project root detection for local run and Docker."""
    # Local run: repo_root/web/app.py
    local_root = BASE_DIR.parent
    if (local_root / "logs").exists() or (local_root / "trading").exists():
        return local_root

    # Docker run (default workdir=/app). We mount volumes under /app.
    docker_root = Path(os.getenv("PROJECT_ROOT", "/app"))
    return docker_root


PROJECT_ROOT = _detect_project_root()
LOG_DIR = Path(os.getenv("LOG_DIR", str(PROJECT_ROOT / "logs")))
KILL_SWITCH_FILE = Path(
    os.getenv("KILL_SWITCH_FILE", str(PROJECT_ROOT / "data" / "KILL_SWITCH"))
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


def _send_telegram_notification(message: str) -> bool:
    """텔레그램으로 알림 전송"""
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if not bot_token or not chat_id:
        print("텔레그램 설정 없음 - 알림 스킵")
        return False

    api_url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "Markdown"
    }

    try:
        resp = requests.post(api_url, json=payload, timeout=10)
        if resp.status_code == 400:
            # Markdown 파싱 오류 시 plain text로 재시도
            payload.pop("parse_mode", None)
            resp = requests.post(api_url, json=payload, timeout=10)
        return 200 <= resp.status_code < 300
    except Exception as e:
        print(f"텔레그램 전송 실패: {e}")
        return False


def _notify_dashboard_url(port: int = 8080):
    """대시보드 URL을 텔레그램으로 알림"""
    # 환경변수에서 설정된 경로인지, 랜덤 생성인지 확인
    is_random = not os.getenv("DASHBOARD_SECRET_PATH")
    path_type = "랜덤 생성" if is_random else "환경변수 설정"

    message = f"""
🖥️ *대시보드 시작*

🔐 경로 타입: `{path_type}`
🔗 접속 경로: `/{DASHBOARD_SECRET_PATH}`
🕐 시작 시간: `{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`

_이 URL을 안전하게 보관하세요._
"""
    _send_telegram_notification(message)


@app.route("/")
def index():
    """루트 경로 - 404 반환 (보안)"""
    return "Not Found", 404


@app.route("/index.html")
@app.route("/default.html")
@app.route("/dashboard.html")
def block_common():
    """일반적인 파일명 차단"""
    return "Not Found", 404


@app.route(f"/{DASHBOARD_SECRET_PATH}")
def dashboard():
    """메인 대시보드 (비밀 경로)"""
    return render_template("dashboard.html")


@app.route("/api/status")
def get_status():
    """현재 상태 API"""

    upbit_log = load_trading_log('upbit')
    binance_log = load_trading_log('binance')
    allocation = load_allocation_config()

    # Extract last signal for each exchange
    upbit_signals = upbit_log.get('signals', []) if upbit_log else []
    binance_signals = binance_log.get('signals', []) if binance_log else []
    upbit_last_signal = upbit_signals[-1] if upbit_signals else None
    binance_last_signal = binance_signals[-1] if binance_signals else None

    # Build per-strategy info for Upbit (from log file, fallback to allocation config)
    upbit_alloc = allocation.get('upbit', {})
    log_strategies = upbit_log.get('strategies', {}) if upbit_log else {}

    upbit_strategies = {}
    for strat_name in ['v35', 'va02']:
        strat_config = upbit_alloc.get(strat_name, {})
        log_strat = log_strategies.get(strat_name, {})

        upbit_strategies[strat_name] = {
            'enabled': strat_config.get('enabled', False),
            'ratio': strat_config.get('ratio', 0),
            'regimes': strat_config.get('regimes', []),
            # Per-strategy position data from engine
            'active': log_strat.get('active', False),
            'btc': log_strat.get('btc', 0.0),
            'entry_price': log_strat.get('entry_price', 0.0),
            'cash': log_strat.get('cash', 0.0),
            'value': log_strat.get('value', 0.0),
        }

    # 상태 구성
    status = {
        'timestamp': datetime.now().isoformat(),
        'market': {
            'regime': upbit_log.get('regime') if upbit_log else None,
            'market_state': upbit_log.get('market_state') if upbit_log else None,
        },
        'upbit': {
            'enabled': upbit_log is not None,
            'exchange': 'upbit',
            'strategy': upbit_log.get('strategy', 'none') if upbit_log else '-',
            'regime': upbit_log.get('regime', '-') if upbit_log else '-',
            'market_state': upbit_log.get('market_state', '-') if upbit_log else '-',
            'position': None,
            'statistics': None,
            'strategies': upbit_strategies,
            'last_signal': upbit_last_signal,
        },
        'binance': {
            'enabled': binance_log is not None,
            'exchange': 'binance',
            'strategy': binance_log.get('strategy', 'none') if binance_log else '-',
            'position': None,
            'statistics': None,
            'last_signal': binance_last_signal,
        }
    }

    if upbit_log:
        status['upbit']['statistics'] = upbit_log.get('statistics', {})
        status['upbit']['current_cash'] = upbit_log.get('current_cash', 0)
        status['upbit']['total_value'] = upbit_log.get('total_value', 0)
        btc_balance = upbit_log.get('btc_balance', 0) or 0
        if btc_balance > 0:
            status['upbit']['position'] = {
                'btc_balance': btc_balance,
                'cash_balance': upbit_log.get('current_cash', 0)
            }

    if binance_log:
        status['binance']['statistics'] = binance_log.get('statistics', {})
        status['binance']['current_cash'] = binance_log.get('current_cash', 0)
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


@app.route("/api/signals/<exchange>")
def get_signals(exchange: str):
    """전략 신호 기록 API"""

    log = load_trading_log(exchange)

    if not log:
        return jsonify({'error': 'No data'}), 404

    signals = log.get('signals', [])

    # 최근 50개
    recent_signals = signals[-50:] if len(signals) > 50 else signals

    return jsonify({
        'exchange': exchange,
        'signals': recent_signals,
        'total_count': len(signals)
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
    print(f"\n{'='*50}")
    print(f"Dashboard available at: http://localhost:8081/{DASHBOARD_SECRET_PATH}")
    print(f"{'='*50}\n")

    # 텔레그램으로 대시보드 URL 알림
    _notify_dashboard_url(port=8081)

    app.run(host="0.0.0.0", port=8081, debug=False)
