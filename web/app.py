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
import redis

# Load .env file from project root
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

# Import metrics collector
try:
    from trading.core.metrics import metrics_collector
except ImportError:
    metrics_collector = None

# Import trade logger for database access
try:
    from trading.risk.trade_logger import TradeLogger
    # Use project root trading_results.db
    project_root = Path(__file__).parent.parent
    trade_logger = TradeLogger(db_path=str(project_root / "trading_results.db"))
except ImportError:
    trade_logger = None

# Import analytics service
try:
    from services.analytics import calculate_metrics, calculate_equity_curve
except Exception as e:
    print(f"Failed to import analytics: {e}")
    calculate_metrics = None
    calculate_equity_curve = None

# Import backtest runner service
try:
    from services import backtest_runner
except Exception as e:
    print(f"Failed to import backtest_runner: {e}")
    backtest_runner = None

# Import metrics service for real-time dashboard
try:
    from services.metrics_service import metrics_service
except Exception as e:
    print(f"Failed to import metrics_service: {e}")
    metrics_service = None

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY") or secrets.token_hex(32)
CORS(app)

BASE_DIR = Path(__file__).parent

# 대시보드 고정 경로
DEFAULT_DOMAIN = "lchsvr.duckdns.org"
DEFAULT_PORT = "5080"
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

        # For API calls, return JSON error instead of HTML form
        if request.path.startswith('/api/'):
            return jsonify({'error': 'Authentication required'}), 401

        # Return TOTP input form for page requests
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


def read_json_logs(log_type: str = 'signals', exchanges: list = None) -> list:
    """
    Read JSON log files and aggregate data.

    Args:
        log_type: 'signals' or 'trades'
        exchanges: List of exchanges to read from (default: ['upbit', 'binance'])

    Returns:
        List of entries with exchange field added
    """
    if exchanges is None:
        exchanges = ['upbit', 'binance']

    all_entries = []
    for exchange in exchanges:
        log = load_trading_log(exchange)
        if log:
            entries = log.get(log_type, [])
            for entry in entries:
                entry_copy = entry.copy()
                entry_copy['exchange'] = exchange
                all_entries.append(entry_copy)

    # Sort by timestamp descending
    all_entries.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
    return all_entries


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
    domain = os.getenv("DASHBOARD_DOMAIN", DEFAULT_DOMAIN)
    port = os.getenv("DASHBOARD_PORT", DEFAULT_PORT)

    message = f"""
🖥️ *대시보드 시작*

🔗 접속: `https://{domain}:{port}/{DASHBOARD_PATH}`
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
    """현재 상태 API - Multi-asset support with exchange separation"""

    # Load multi-asset engine status
    ma_status = load_multi_asset_status()
    allocation = load_allocation_config()

    if not ma_status:
        return jsonify({'error': 'No engine status available'}), 404

    # Build response
    assets_data = ma_status.get('assets', {})
    portfolio = ma_status.get('portfolio', {})
    capital_cfg = allocation.get('capital', {})

    # Build per-asset-per-exchange response
    assets = {}
    for symbol, data in assets_data.items():
        asset_config = allocation.get('assets', {}).get(symbol, {})
        portfolio_asset = portfolio.get('assets', {}).get(symbol, {})
        regime = data.get('regime', 'UNKNOWN')

        # Upbit card (if enabled)
        if asset_config.get('upbit_enabled', True) or data.get('upbit_enabled', True):
            upbit_key = f"{symbol}_upbit"
            assets[upbit_key] = {
                'symbol': symbol,
                'exchange': 'upbit',
                'enabled': asset_config.get('upbit_enabled', True),
                'regime': regime,
                'price': data.get('upbit_price', 0),
                'position_active': data.get('upbit_position_active', data.get('position_active', False)),
                'position_qty': data.get('upbit_position_qty', data.get('position_qty', 0)),
                'direction': 'long',
                'strategy': data.get('upbit_strategy'),
                # Portfolio allocation
                'alpha_ratio': asset_config.get('alpha_ratio', 0),
                'allocated_krw': portfolio_asset.get('allocated_krw', 0),
                'position_value_krw': portfolio_asset.get('position_value_krw', 0),
                # Strategy config
                'strategies': asset_config.get('upbit_strategies', asset_config.get('strategies', {})),
            }

        # Binance card (if enabled)
        if asset_config.get('binance_enabled', False) or data.get('binance_enabled', False):
            binance_key = f"{symbol}_binance"
            assets[binance_key] = {
                'symbol': symbol,
                'exchange': 'binance',
                'enabled': asset_config.get('binance_enabled', False),
                'regime': regime,
                'price': data.get('binance_price', 0),
                'position_active': data.get('binance_position_active', False),
                'position_qty': data.get('binance_position_qty', 0),
                'direction': data.get('binance_direction', 'long'),
                'strategy': data.get('binance_strategy'),
                'leverage': data.get('binance_leverage', asset_config.get('binance_leverage', 1)),
                # Capital allocation
                'alpha_ratio': asset_config.get('alpha_ratio', 0),
                'capital_usdt': capital_cfg.get('binance_usdt', 5000) * asset_config.get('alpha_ratio', 0),
                # Strategy config
                'strategies': asset_config.get('binance_strategies', {}),
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
        'capital': capital_cfg,
    }

    return jsonify(status)


@app.route("/health")
@app.route("/api/health")
def health_check():
    """
    Health check endpoint for monitoring.

    Returns component status and overall health.
    No authentication required for monitoring tools.
    """
    start_time = datetime.now()

    # Check components
    components = {}
    overall_healthy = True

    # Check Redis
    try:
        r = redis.Redis(
            host=os.getenv("REDIS_HOST", "localhost"),
            port=int(os.getenv("REDIS_PORT", 6379)),
            socket_timeout=2.0,
        )
        r.ping()
        components["redis"] = {"status": "healthy", "latency_ms": 0}
    except Exception as e:
        components["redis"] = {"status": "unhealthy", "error": str(e)[:100]}
        # Redis not critical, don't mark overall unhealthy

    # Check engine status file
    ma_status = load_multi_asset_status()
    if ma_status:
        last_update = ma_status.get("timestamp", "")
        try:
            if last_update:
                last_dt = datetime.fromisoformat(last_update.replace("Z", "+00:00"))
                age_seconds = (datetime.now() - last_dt.replace(tzinfo=None)).total_seconds()
                if age_seconds < 300:  # Updated within 5 minutes
                    components["engine"] = {"status": "healthy", "age_seconds": age_seconds}
                else:
                    components["engine"] = {"status": "stale", "age_seconds": age_seconds}
            else:
                components["engine"] = {"status": "unknown"}
        except Exception:
            components["engine"] = {"status": "unknown", "last_update": last_update}
    else:
        components["engine"] = {"status": "not_running"}
        overall_healthy = False

    # Check kill switch
    components["kill_switch"] = {
        "status": "active" if KILL_SWITCH_FILE.exists() else "inactive",
    }

    # Get asset health if available from engine status
    assets_health = {}
    if ma_status:
        health_data = ma_status.get("health", {})
        assets_data = health_data.get("assets", {})
        for symbol, asset_info in assets_data.items():
            if isinstance(asset_info, dict):
                assets_health[symbol] = {
                    "enabled": asset_info.get("enabled", True),
                    "consecutive_failures": asset_info.get("consecutive_failures", 0),
                }
            else:
                assets_health[symbol] = {"enabled": asset_info}

    # Get metrics summary if available
    metrics_summary = {}
    if metrics_collector:
        try:
            metrics_summary = metrics_collector.get_summary()
        except Exception:
            pass

    response = {
        "status": "healthy" if overall_healthy else "degraded",
        "timestamp": datetime.now().isoformat(),
        "components": components,
        "assets": assets_health,
        "metrics": metrics_summary,
        "response_time_ms": (datetime.now() - start_time).total_seconds() * 1000,
    }

    status_code = 200 if overall_healthy else 503
    return jsonify(response), status_code


@app.route("/api/metrics")
def get_metrics():
    """Get detailed trading metrics."""
    if not metrics_collector:
        return jsonify({"error": "Metrics not available"}), 503

    try:
        return jsonify(metrics_collector.get_metrics())
    except Exception as e:
        return jsonify({"error": str(e)}), 500


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
def get_trades_by_exchange(exchange: str):
    """거래 기록 API (legacy - by exchange)"""

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


@app.route("/api/trades")
def get_trades():
    """
    Get paginated trade history with filters.
    Query params: page, limit, exchange, start_date, end_date, symbol
    """
    # Parse query parameters
    page = request.args.get('page', 1, type=int)
    limit = request.args.get('limit', 100, type=int)
    exchange_filter = request.args.get('exchange')
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    symbol_filter = request.args.get('symbol')

    # Clamp limit
    limit = min(max(1, limit), 500)

    # Try to use TradeLogger for database trades first
    db_trades = []
    if trade_logger:
        try:
            # Get trades from database
            if start_date and end_date:
                db_trades = trade_logger.get_trades_for_date_range(start_date, end_date)
            else:
                db_trades = trade_logger.get_recent_trades(limit=1000)
        except Exception as e:
            print(f"TradeLogger error: {e}")

    # Also get trades from JSON logs for richer data
    json_trades = read_json_logs('trades')

    # Merge and dedupe trades (prefer JSON for detail, DB for completeness)
    all_trades = []

    # Add JSON trades first (have more detail)
    for t in json_trades:
        all_trades.append({
            'id': t.get('id', len(all_trades)),
            'timestamp': t.get('timestamp', ''),
            'action': t.get('action', '').upper(),
            'price': t.get('price', 0),
            'volume': t.get('volume', 0),
            'profit': t.get('profit'),
            'profit_pct': t.get('profit_pct'),
            'exchange': t.get('exchange', 'unknown'),
            'strategy': t.get('strategy', ''),
            'reason': t.get('reason', ''),
            'regime': t.get('regime', ''),
        })

    # Apply filters
    filtered_trades = all_trades

    if exchange_filter:
        filtered_trades = [t for t in filtered_trades if t['exchange'] == exchange_filter]

    if symbol_filter:
        filtered_trades = [t for t in filtered_trades if symbol_filter.upper() in t.get('symbol', 'BTC').upper()]

    if start_date:
        filtered_trades = [t for t in filtered_trades if t['timestamp'] >= start_date]

    if end_date:
        filtered_trades = [t for t in filtered_trades if t['timestamp'] <= end_date + 'T23:59:59']

    # Sort by timestamp descending
    filtered_trades.sort(key=lambda x: x.get('timestamp', ''), reverse=True)

    # Calculate pagination
    total_count = len(filtered_trades)
    start_idx = (page - 1) * limit
    end_idx = start_idx + limit
    paginated_trades = filtered_trades[start_idx:end_idx]

    return jsonify({
        'trades': paginated_trades,
        'total_count': total_count,
        'page': page,
        'limit': limit,
        'has_more': end_idx < total_count
    })


@app.route("/api/trades/<int:trade_id>")
def get_trade_detail(trade_id: int):
    """Get detailed information for a specific trade."""
    # Search in JSON logs for trade detail
    json_trades = read_json_logs('trades')

    for t in json_trades:
        if t.get('id') == trade_id:
            return jsonify({
                'id': trade_id,
                'timestamp': t.get('timestamp', ''),
                'action': t.get('action', '').upper(),
                'price': t.get('price', 0),
                'volume': t.get('volume', 0),
                'profit': t.get('profit'),
                'profit_pct': t.get('profit_pct'),
                'exchange': t.get('exchange', 'unknown'),
                'strategy': t.get('strategy', ''),
                'reason': t.get('reason', ''),
                'regime': t.get('regime', ''),
                'market_state': t.get('market_state', ''),
                'indicators': t.get('indicators', {}),
            })

    return jsonify({'error': 'Trade not found'}), 404


@app.route("/api/signals/<exchange>")
def get_signals_by_exchange(exchange: str):
    """전략 신호 기록 API (legacy - by exchange)"""

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


@app.route("/api/signals")
def get_signals():
    """
    Get recent trading signals with optional filters.
    Query params: limit, exchange, action
    """
    limit = request.args.get('limit', 50, type=int)
    exchange_filter = request.args.get('exchange')
    action_filter = request.args.get('action')

    # Clamp limit
    limit = min(max(1, limit), 200)

    # Read signals from JSON logs
    all_signals = read_json_logs('signals')

    # Transform to standard format
    signals = []
    for s in all_signals:
        signals.append({
            'timestamp': s.get('timestamp', ''),
            'exchange': s.get('exchange', 'unknown'),
            'strategy': s.get('strategy', ''),
            'action': s.get('action', 'hold'),
            'reason': s.get('reason', ''),
            'regime': s.get('regime', ''),
            'market_state': s.get('market_state', ''),
            'acted': s.get('acted', False),
            'indicators': s.get('indicators', {}),
        })

    # Apply filters
    if exchange_filter:
        signals = [s for s in signals if s['exchange'] == exchange_filter]

    if action_filter:
        signals = [s for s in signals if s['action'] == action_filter]

    # Limit results
    signals = signals[:limit]

    return jsonify({
        'signals': signals,
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


@app.route("/api/analytics")
def get_analytics():
    """
    Get performance analytics for specified period.
    Query params: period (7d, 30d, 90d, all), strategy
    """
    period = request.args.get('period', '30d')
    strategy_filter = request.args.get('strategy')

    # Validate period
    valid_periods = ['7d', '30d', '90d', 'all']
    if period not in valid_periods:
        period = '30d'

    # Get trades from JSON logs
    all_trades = read_json_logs('trades')

    # Filter by strategy if specified
    if strategy_filter:
        all_trades = [t for t in all_trades if t.get('strategy') == strategy_filter]

    # Calculate metrics
    if calculate_metrics:
        metrics = calculate_metrics(all_trades, period)
    else:
        metrics = {'error': 'Analytics service not available'}

    return jsonify(metrics)


@app.route("/api/analytics/equity-curve")
def get_equity_curve():
    """
    Get equity curve data for charting.
    Query params: period (7d, 30d, 90d, all), points (max data points)
    """
    period = request.args.get('period', '30d')
    max_points = request.args.get('points', 100, type=int)

    # Validate
    valid_periods = ['7d', '30d', '90d', 'all']
    if period not in valid_periods:
        period = '30d'

    max_points = min(max(1, max_points), 500)

    # Get trades from JSON logs
    all_trades = read_json_logs('trades')

    # Calculate equity curve
    if calculate_equity_curve:
        curve_data = calculate_equity_curve(all_trades, period)

        # Downsample if needed
        points = curve_data.get('points', [])
        if len(points) > max_points:
            step = len(points) // max_points
            curve_data['points'] = points[::step][:max_points]

        return jsonify(curve_data)
    else:
        return jsonify({'error': 'Analytics service not available'}), 503


@app.route("/api/analytics/daily")
def get_daily_analytics():
    """
    Get daily breakdown of trading performance.
    Query params: period (7d, 30d, 90d, all)
    """
    from datetime import timedelta
    from collections import defaultdict

    period = request.args.get('period', '30d')

    # Validate period
    valid_periods = ['7d', '30d', '90d', 'all']
    if period not in valid_periods:
        period = '30d'

    # Get trades from JSON logs
    all_trades = read_json_logs('trades')

    # Filter by period
    now = datetime.now()
    if period != 'all':
        days = int(period.replace('d', ''))
        cutoff = now - timedelta(days=days)
        cutoff_str = cutoff.isoformat()
        all_trades = [t for t in all_trades if t.get('timestamp', '') >= cutoff_str]

    # Group by date
    daily_data = defaultdict(lambda: {
        'trades': 0,
        'buys': 0,
        'sells': 0,
        'profit': 0,
        'wins': 0,
        'losses': 0
    })

    for trade in all_trades:
        timestamp = trade.get('timestamp', '')
        if not timestamp:
            continue

        # Extract date part
        date_str = timestamp[:10]  # YYYY-MM-DD
        action = trade.get('action', '').upper()
        profit = trade.get('profit')

        daily_data[date_str]['trades'] += 1

        if action == 'BUY':
            daily_data[date_str]['buys'] += 1
        elif action == 'SELL':
            daily_data[date_str]['sells'] += 1
            if profit is not None:
                daily_data[date_str]['profit'] += profit
                if profit > 0:
                    daily_data[date_str]['wins'] += 1
                else:
                    daily_data[date_str]['losses'] += 1

    # Convert to sorted list
    daily_list = []
    for date_str, stats in sorted(daily_data.items()):
        total_closed = stats['wins'] + stats['losses']
        win_rate = (stats['wins'] / total_closed * 100) if total_closed > 0 else 0

        daily_list.append({
            'date': date_str,
            'trades': stats['trades'],
            'buys': stats['buys'],
            'sells': stats['sells'],
            'profit': stats['profit'],
            'wins': stats['wins'],
            'losses': stats['losses'],
            'win_rate': round(win_rate, 1)
        })

    # Calculate totals
    total_profit = sum(d['profit'] for d in daily_list)
    total_trades = sum(d['trades'] for d in daily_list)
    total_wins = sum(d['wins'] for d in daily_list)
    total_losses = sum(d['losses'] for d in daily_list)

    return jsonify({
        'period': period,
        'days': daily_list,
        'summary': {
            'total_days': len(daily_list),
            'total_trades': total_trades,
            'total_profit': total_profit,
            'total_wins': total_wins,
            'total_losses': total_losses,
            'profitable_days': sum(1 for d in daily_list if d['profit'] > 0),
            'losing_days': sum(1 for d in daily_list if d['profit'] < 0)
        }
    })


@app.route("/api/positions")
def get_positions():
    """
    Get consolidated positions from both exchanges.
    Returns positions with unrealized P&L.
    """
    result = {
        'timestamp': datetime.now().isoformat(),
        'total_value': 0,
        'total_unrealized_pnl': 0,
        'positions': [],
        'errors': []
    }

    # Fetch Upbit positions
    try:
        import pyupbit

        upbit_client = pyupbit.Upbit(
            os.getenv('UPBIT_ACCESS_KEY'),
            os.getenv('UPBIT_SECRET_KEY')
        )
        balances = upbit_client.get_balances()

        for bal in balances:
            currency = bal.get('currency', '')
            if currency == 'KRW':
                continue

            balance = float(bal.get('balance', 0))
            avg_price = float(bal.get('avg_buy_price', 0))

            if balance > 0 and avg_price > 0:
                ticker = f"KRW-{currency}"
                current_price = pyupbit.get_current_price(ticker) or avg_price
                value = balance * current_price
                cost = balance * avg_price
                unrealized_pnl = value - cost
                unrealized_pnl_pct = ((current_price / avg_price) - 1) * 100 if avg_price > 0 else 0

                result['positions'].append({
                    'symbol': currency,
                    'exchange': 'upbit',
                    'side': 'LONG',
                    'quantity': balance,
                    'entry_price': avg_price,
                    'current_price': current_price,
                    'value': value,
                    'unrealized_pnl': unrealized_pnl,
                    'unrealized_pnl_pct': unrealized_pnl_pct,
                    'liquidation_price': None,
                    'leverage': None
                })
                result['total_value'] += value
                result['total_unrealized_pnl'] += unrealized_pnl

    except Exception as e:
        result['errors'].append(f'Upbit: {str(e)}')

    # Fetch Binance Futures positions
    try:
        from binance.client import Client
        import time

        api_key = os.getenv('BINANCE_API_KEY')
        api_secret = os.getenv('BINANCE_API_SECRET')

        if api_key and api_secret:
            client = Client(api_key, api_secret)
            server_time = client.get_server_time()
            local_time = int(time.time() * 1000)
            client.timestamp_offset = server_time['serverTime'] - local_time

            account = client.futures_account(recvWindow=60000)

            for pos in account['positions']:
                size = float(pos['positionAmt'])
                if size != 0:
                    entry_price = float(pos['entryPrice'])
                    unrealized_pnl = float(pos['unrealizedProfit'])
                    mark_price = float(pos.get('markPrice', entry_price))
                    liquidation_price = float(pos.get('liquidationPrice', 0))
                    leverage = int(pos.get('leverage', 1))

                    side = 'LONG' if size > 0 else 'SHORT'
                    abs_size = abs(size)
                    value = abs_size * mark_price

                    # Calculate P&L percentage
                    if entry_price > 0:
                        if side == 'LONG':
                            unrealized_pnl_pct = ((mark_price / entry_price) - 1) * 100 * leverage
                        else:
                            unrealized_pnl_pct = ((entry_price / mark_price) - 1) * 100 * leverage
                    else:
                        unrealized_pnl_pct = 0

                    result['positions'].append({
                        'symbol': pos['symbol'],
                        'exchange': 'binance',
                        'side': side,
                        'quantity': abs_size,
                        'entry_price': entry_price,
                        'current_price': mark_price,
                        'value': value,
                        'unrealized_pnl': unrealized_pnl,
                        'unrealized_pnl_pct': unrealized_pnl_pct,
                        'liquidation_price': liquidation_price if liquidation_price > 0 else None,
                        'leverage': leverage
                    })
                    result['total_value'] += value
                    result['total_unrealized_pnl'] += unrealized_pnl
        else:
            result['errors'].append('Binance: API credentials not configured')

    except Exception as e:
        result['errors'].append(f'Binance: {str(e)}')

    return jsonify(result)


# =====================
# Backtest API Endpoints
# =====================

@app.route("/api/backtest/strategies")
@requires_totp
def get_backtest_strategies():
    """Get list of available strategies for backtesting."""
    if not backtest_runner:
        return jsonify({'error': 'Backtest service not available'}), 503

    strategies = backtest_runner.get_available_strategies()
    return jsonify({
        'strategies': strategies
    })


@app.route("/api/backtest/run", methods=["POST"])
@requires_totp
def run_backtest():
    """
    Start a new backtest job.
    Request body: { strategy, start_date, end_date, initial_capital }
    """
    if not backtest_runner:
        return jsonify({'error': 'Backtest service not available'}), 503

    data = request.get_json() or {}

    # Validate required fields
    strategy = data.get('strategy')
    if not strategy:
        return jsonify({'error': 'Strategy is required'}), 400

    # Validate strategy exists
    strategies = backtest_runner.get_available_strategies()
    valid_ids = [s['id'] for s in strategies]
    if strategy not in valid_ids:
        return jsonify({'error': f'Invalid strategy: {strategy}'}), 400

    # Build config
    config = {
        'strategy': strategy,
        'start_date': data.get('start_date', '2024-01-01'),
        'end_date': data.get('end_date', '2024-12-31'),
        'initial_capital': data.get('initial_capital', 10000000),
    }

    # Start backtest (with rate limiting)
    try:
        job = backtest_runner.start_backtest(config)
    except RuntimeError as e:
        return jsonify({'error': str(e)}), 429  # Too Many Requests

    return jsonify({
        'job_id': job.job_id,
        'status': job.status,
        'config': job.config,
        'created_at': job.created_at
    })


@app.route("/api/backtest/status/<job_id>")
@requires_totp
def get_backtest_status(job_id: str):
    """Get status and results of a backtest job."""
    if not backtest_runner:
        return jsonify({'error': 'Backtest service not available'}), 503

    job = backtest_runner.get_job(job_id)
    if not job:
        return jsonify({'error': 'Job not found'}), 404

    return jsonify(job.to_dict())


@app.route("/api/backtest/cancel/<job_id>", methods=["POST"])
@requires_totp
def cancel_backtest(job_id: str):
    """Cancel a running backtest job."""
    if not backtest_runner:
        return jsonify({'error': 'Backtest service not available'}), 503

    success = backtest_runner.cancel_job(job_id)
    if success:
        job = backtest_runner.get_job(job_id)
        return jsonify(job.to_dict())
    else:
        return jsonify({'error': 'Job not found or cannot be cancelled'}), 404


@app.route("/api/exchange_balances")
def get_exchange_balances():
    """Fetch live balances from Upbit and Binance exchanges."""
    result = {
        'timestamp': datetime.now().isoformat(),
        'upbit': None,
        'binance': None,
        'errors': []
    }

    # Fetch Upbit balance
    try:
        from trading.adapters.upbit import UpbitTrader
        import pyupbit

        upbit = UpbitTrader()
        krw_balance, btc_balance = upbit.get_balance()
        btc_price = upbit.get_current_price() or 0

        btc_value = btc_balance * btc_price if btc_price else 0
        total_krw = krw_balance + btc_value

        # Get all coin balances from Upbit
        positions = []
        try:
            upbit_client = pyupbit.Upbit(
                os.getenv('UPBIT_ACCESS_KEY'),
                os.getenv('UPBIT_SECRET_KEY')
            )
            balances = upbit_client.get_balances()
            for bal in balances:
                currency = bal.get('currency', '')
                if currency == 'KRW':
                    continue
                balance = float(bal.get('balance', 0))
                avg_price = float(bal.get('avg_buy_price', 0))
                if balance > 0 and avg_price > 0:
                    # Get current price
                    ticker = f"KRW-{currency}"
                    current_price = pyupbit.get_current_price(ticker) or avg_price
                    value_krw = balance * current_price
                    cost_krw = balance * avg_price
                    pnl_krw = value_krw - cost_krw
                    pnl_pct = ((current_price / avg_price) - 1) * 100 if avg_price > 0 else 0

                    positions.append({
                        'symbol': currency,
                        'quantity': balance,
                        'avg_price': avg_price,
                        'current_price': current_price,
                        'value_krw': value_krw,
                        'cost_krw': cost_krw,
                        'pnl_krw': pnl_krw,
                        'pnl_pct': pnl_pct,
                    })
        except Exception as e:
            result['errors'].append(f'Upbit positions: {str(e)}')

        result['upbit'] = {
            'krw_balance': krw_balance,
            'btc_balance': btc_balance,
            'btc_price': btc_price,
            'btc_value_krw': btc_value,
            'total_krw': total_krw,
            'positions': positions,
        }
    except Exception as e:
        result['errors'].append(f'Upbit: {str(e)}')

    # Fetch Binance balance
    try:
        from binance.client import Client
        import time
        api_key = os.getenv('BINANCE_API_KEY')
        api_secret = os.getenv('BINANCE_API_SECRET')

        if api_key and api_secret:
            # Sync time offset with Binance server
            client = Client(api_key, api_secret)
            server_time = client.get_server_time()
            local_time = int(time.time() * 1000)
            client.timestamp_offset = server_time['serverTime'] - local_time

            account = client.futures_account(recvWindow=60000)

            usdt_balance = 0
            unrealized_pnl = 0
            for asset in account['assets']:
                if asset['asset'] == 'USDT':
                    usdt_balance = float(asset['walletBalance'])
                    unrealized_pnl = float(asset['unrealizedProfit'])
                    break

            # Get open positions
            positions = []
            for pos in account['positions']:
                size = float(pos['positionAmt'])
                if size != 0:
                    positions.append({
                        'symbol': pos['symbol'],
                        'size': size,
                        'entry_price': float(pos['entryPrice']),
                        'unrealized_pnl': float(pos['unrealizedProfit']),
                    })

            result['binance'] = {
                'usdt_balance': usdt_balance,
                'unrealized_pnl': unrealized_pnl,
                'total_equity': usdt_balance + unrealized_pnl,
                'positions': positions,
            }
        else:
            result['errors'].append('Binance: API credentials not configured')
    except Exception as e:
        result['errors'].append(f'Binance: {str(e)}')

    return jsonify(result)


# =============================================================================
# Real-Time Metrics Dashboard Endpoints
# =============================================================================

@app.route("/metrics")
@requires_auth
def metrics_page():
    """Render the real-time metrics dashboard page."""
    return render_template("metrics.html")


@app.route("/api/metrics/realtime")
def get_realtime_metrics():
    """
    Get real-time trading metrics for the dashboard.

    Returns DashboardState JSON per contracts/api.yaml with:
    - Current strategy decisions for each exchange
    - Position and P&L information
    - Market regime classification
    - Connection status
    """
    if not metrics_service:
        return jsonify({'error': 'Metrics service not available'}), 500

    try:
        dashboard_state = metrics_service.get_dashboard_state()

        # Check if any data is available
        if not dashboard_state.get('upbit') and not dashboard_state.get('binance'):
            return jsonify({
                'error': 'No trading data available',
                'message': 'Trading bot may not be running or no log files found'
            }), 404

        return jsonify(dashboard_state)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route("/api/metrics/decisions")
def get_decision_history():
    """
    Get strategy decision history with optional filtering.

    Query parameters:
    - exchange: Filter by exchange (upbit, binance)
    - hours: Hours of history to return (default 24, max 72)
    - limit: Maximum number of decisions (default 50, max 200)
    """
    if not metrics_service:
        return jsonify({'error': 'Metrics service not available'}), 500

    try:
        # Parse query parameters
        exchange = request.args.get('exchange')
        if exchange and exchange not in ['upbit', 'binance']:
            return jsonify({'error': 'Invalid exchange. Use upbit or binance'}), 400

        hours = max(1, min(int(request.args.get('hours', 24)), 72))
        limit = max(1, min(int(request.args.get('limit', 50)), 200))

        decisions = metrics_service.get_recent_decisions(
            hours=hours,
            limit=limit,
            exchange=exchange
        )

        return jsonify({
            'decisions': decisions,
            'total_count': len(decisions)
        })
    except ValueError:
        return jsonify({'error': 'Invalid parameter values'}), 400
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
