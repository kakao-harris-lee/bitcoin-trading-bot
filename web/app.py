#!/usr/bin/env python3
"""
app.py
Flask 웹 대시보드 - Dual Exchange Paper Trading 모니터링
"""

from flask import Flask, render_template, jsonify, request, Response, session
from flask_cors import CORS
from functools import wraps
import secrets
import json
import os
import requests
from pathlib import Path
from datetime import datetime

import pyotp

# Load .env file from project root
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY") or secrets.token_hex(32)
CORS(app)

BASE_DIR = Path(__file__).parent

# 대시보드 고정 경로
DASHBOARD_PATH = "btc-dashboard"

# TOTP 설정 (환경변수에서 비밀키 로드, 없으면 생성하여 출력)
TOTP_SECRET = os.getenv("DASHBOARD_TOTP_SECRET")
if not TOTP_SECRET:
    TOTP_SECRET = pyotp.random_base32()
    print(f"\n⚠️  DASHBOARD_TOTP_SECRET not set. Generated new secret:")
    print(f"   Add to .env: DASHBOARD_TOTP_SECRET={TOTP_SECRET}\n")

totp = pyotp.TOTP(TOTP_SECRET, interval=30)

# 대시보드 인증 정보 (기존 Basic Auth - optional fallback)
DASHBOARD_USERNAME = os.getenv("DASHBOARD_USERNAME")
DASHBOARD_PASSWORD = os.getenv("DASHBOARD_PASSWORD")


def check_auth(username, password):
    """Check if username/password combination is valid."""
    if not DASHBOARD_USERNAME or not DASHBOARD_PASSWORD:
        return True  # No auth configured
    return username == DASHBOARD_USERNAME and password == DASHBOARD_PASSWORD


def authenticate():
    """Send 401 response to enable basic auth."""
    return Response(
        'Authentication required.', 401,
        {'WWW-Authenticate': 'Basic realm="Bitcoin Trading Bot Dashboard"'}
    )


def requires_auth(f):
    """Decorator for routes that require authentication."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not DASHBOARD_USERNAME or not DASHBOARD_PASSWORD:
            return f(*args, **kwargs)  # No auth configured
        auth = request.authorization
        if not auth or not check_auth(auth.username, auth.password):
            return authenticate()
        return f(*args, **kwargs)
    return decorated


def verify_totp(code: str) -> bool:
    """Verify TOTP code with 1 interval tolerance."""
    return totp.verify(code, valid_window=1)


def get_current_totp() -> str:
    """Get current TOTP code."""
    return totp.now()


def requires_totp(f):
    """Decorator for routes that require TOTP authentication."""
    @wraps(f)
    def decorated(*args, **kwargs):
        # Check if already authenticated in session
        if session.get('totp_authenticated'):
            return f(*args, **kwargs)

        # Check for TOTP code in query parameter
        totp_code = request.args.get('code')
        if totp_code and verify_totp(totp_code):
            session['totp_authenticated'] = True
            session.permanent = False  # Session expires when browser closes
            return f(*args, **kwargs)

        # Return TOTP input form
        return render_totp_form()

    return decorated


def render_totp_form():
    """Render TOTP input form."""
    return '''
    <!DOCTYPE html>
    <html>
    <head>
        <title>Dashboard Access</title>
        <style>
            body { font-family: Arial; background: #1a1a2e; color: #fff; display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0; }
            .container { background: #16213e; padding: 40px; border-radius: 10px; text-align: center; }
            h2 { margin-bottom: 20px; }
            input { padding: 15px; font-size: 24px; width: 200px; text-align: center; letter-spacing: 8px; border: 2px solid #0f3460; border-radius: 5px; background: #1a1a2e; color: #fff; }
            button { padding: 15px 40px; font-size: 16px; background: #e94560; color: #fff; border: none; border-radius: 5px; cursor: pointer; margin-top: 20px; }
            button:hover { background: #ff6b6b; }
            .error { color: #e94560; margin-top: 10px; }
        </style>
    </head>
    <body>
        <div class="container">
            <h2>🔐 Dashboard Access</h2>
            <form method="GET">
                <input type="text" name="code" placeholder="000000" maxlength="6" pattern="[0-9]{6}" required autofocus>
                <br>
                <button type="submit">Verify</button>
            </form>
            <p style="margin-top: 20px; font-size: 12px; color: #888;">Enter TOTP code from Telegram /dashboard command</p>
        </div>
    </body>
    </html>
    ''', 200


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


def load_multi_asset_status() -> dict:
    """Load multi-asset engine status."""
    status_file = LOG_DIR / "multi_asset_engine_status.json"
    if status_file.exists():
        try:
            with open(status_file, 'r') as f:
                return json.load(f)
        except Exception as e:
            print(f"Multi-asset status load failed: {e}")
    return None


def load_premium_history(symbol: str) -> dict:
    """Load premium history for a symbol."""
    history_file = LOG_DIR / f"premium_history_{symbol}.json"
    if history_file.exists():
        try:
            with open(history_file, 'r') as f:
                return json.load(f)
        except Exception as e:
            print(f"Premium history load failed ({symbol}): {e}")
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


def _notify_dashboard_url(port: int = 5080):
    """대시보드 URL을 텔레그램으로 알림"""
    current_code = get_current_totp()
    domain = os.getenv("DASHBOARD_DOMAIN", "lchsvr.duckdns.org")

    message = f"""
🖥️ *대시보드 시작*

🔗 접속: `https://{domain}/{DASHBOARD_PATH}`
🔐 현재 TOTP: `{current_code}`
🕐 시작 시간: `{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`

_/dashboard 명령어로 TOTP 코드를 받을 수 있습니다._
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


@app.route(f"/{DASHBOARD_PATH}")
@requires_totp
def dashboard():
    """메인 대시보드 (TOTP 인증 필요)"""
    return render_template("dashboard.html")


@app.route("/api/status")
def get_status():
    """현재 상태 API - Multi-asset support"""

    # Load multi-asset engine status
    ma_status = load_multi_asset_status()
    allocation = load_allocation_config()

    if not ma_status:
        return jsonify({'error': 'No engine status available'}), 404

    # Build response
    assets_data = ma_status.get('assets', {})
    portfolio = ma_status.get('portfolio', {})
    hedge = ma_status.get('hedge', {})
    delta = ma_status.get('delta', {})

    # Build per-asset response
    assets = {}
    for symbol, data in assets_data.items():
        asset_config = allocation.get('assets', {}).get(symbol, {})
        portfolio_asset = portfolio.get('assets', {}).get(symbol, {})
        hedge_stats = hedge.get('statistics', {}).get(symbol, {})
        delta_state = delta.get('states', {}).get(symbol, {})

        assets[symbol] = {
            'enabled': asset_config.get('enabled', False),
            'regime': data.get('regime', 'UNKNOWN'),
            'upbit_price': data.get('upbit_price', 0),
            'binance_price': data.get('binance_price', 0),
            'premium_pct': data.get('premium_pct', 0),
            'position_active': data.get('position_active', False),
            'position_qty': data.get('position_qty', 0),
            # Portfolio allocation
            'alpha_ratio': asset_config.get('alpha_ratio', 0),
            'allocated_krw': portfolio_asset.get('allocated_krw', 0),
            'position_value_krw': portfolio_asset.get('position_value_krw', 0),
            # Hedge info
            'hedge_enabled': asset_config.get('hedge_enabled', False),
            'long_qty': delta_state.get('long_qty', 0),
            'short_qty': delta_state.get('short_qty', 0),
            'net_delta': delta_state.get('net_delta', 0),
            # Strategy config
            'strategies': asset_config.get('strategies', {}),
        }

    status = {
        'timestamp': ma_status.get('timestamp', datetime.now().isoformat()),
        'mode': ma_status.get('mode', 'paper'),
        'engine': ma_status.get('engine', 'multi-asset'),
        'iteration_count': ma_status.get('iteration_count', 0),
        'signal_count': ma_status.get('signal_count', 0),
        'assets': assets,
        'portfolio': {
            'total_capital_krw': portfolio.get('total_capital_krw', 0),
            'total_value_krw': portfolio.get('total_value_krw', 0),
            'cash_krw': portfolio.get('cash_krw', 0),
            'exposure_pct': portfolio.get('exposure_pct', 0),
            'unrealized_pnl': portfolio.get('total_unrealized_pnl', 0),
        },
        'hedge': {
            'symbols': hedge.get('symbols', []),
            'total_capital_usdt': hedge.get('total_capital', 0),
            'positions': hedge.get('positions', {}),
        },
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


@app.route("/api/hedge")
def get_hedge_info():
    """Kimchi Premium and Hedge Ratio API - Multi-asset support"""
    ma_status = load_multi_asset_status()
    allocation = load_allocation_config()

    if not ma_status:
        return jsonify({'error': 'No hedge data available'}), 404

    try:
        assets_data = ma_status.get('assets', {})
        hedge = ma_status.get('hedge', {})
        delta = ma_status.get('delta', {})

        # Build per-asset premium data
        premiums = {}
        for symbol, data in assets_data.items():
            # Load premium history for stats
            history = load_premium_history(symbol)
            premium_stats = {}
            if history and 'history' in history:
                recent = history['history'][-24:]  # Last 24 entries (hourly)
                if recent:
                    pct_values = [h.get('premium_pct', 0) for h in recent]
                    import statistics
                    premium_stats = {
                        'mean_24h': statistics.mean(pct_values) if pct_values else 0,
                        'std_24h': statistics.stdev(pct_values) if len(pct_values) > 1 else 0,
                        'volatility_state': 'high' if len(pct_values) > 1 and statistics.stdev(pct_values) > 1.5 else 'normal',
                    }

            premiums[symbol] = {
                'premium_pct': data.get('premium_pct', 0),
                'upbit_price': data.get('upbit_price', 0),
                'binance_price': data.get('binance_price', 0),
                'regime': data.get('regime', 'UNKNOWN'),
                'stats': premium_stats,
            }

        # Build hedge/delta info
        delta_states = delta.get('states', {})
        hedge_symbols = hedge.get('symbols', [])

        return jsonify({
            'generated_at': ma_status.get('timestamp'),
            'mode': ma_status.get('mode'),
            'premiums': premiums,
            'hedge': {
                'symbols': hedge_symbols,
                'total_capital_usdt': hedge.get('total_capital', 0),
                'positions': hedge.get('positions', {}),
            },
            'delta': {
                'states': delta_states,
            },
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


if __name__ == "__main__":
    print(f"\n{'='*50}")
    print(f"Dashboard available at: http://localhost:5080/{DASHBOARD_PATH}")
    print(f"TOTP authentication required (use /dashboard command in Telegram)")
    print(f"{'='*50}\n")

    # 텔레그램으로 대시보드 URL 알림
    _notify_dashboard_url(port=5080)

    app.run(host="0.0.0.0", port=5080, debug=False)
