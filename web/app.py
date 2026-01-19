#!/usr/bin/env python3
"""
app.py
Flask 웹 대시보드 - Dual Exchange Paper Trading 모니터링
"""

from flask import Flask, render_template, jsonify, request, Response
from flask_cors import CORS
from functools import wraps
import secrets
import json
import os
import requests
from pathlib import Path
from datetime import datetime

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

# Import analytics service (relative import from web/services/)
try:
    import sys
    from pathlib import Path
    web_dir = Path(__file__).parent
    if str(web_dir) not in sys.path:
        sys.path.insert(0, str(web_dir))
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

# 대시보드 인증 정보 (Basic Auth)
DASHBOARD_USERNAME = "admin"
DASHBOARD_PASSWORD = "@1tidh6ls6ls"


def check_auth(username, password):
    """Check if username/password combination is valid."""
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
        auth = request.authorization
        if not auth or not check_auth(auth.username, auth.password):
            return authenticate()
        return f(*args, **kwargs)
    return decorated


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
        exchanges: List of exchanges to read from (default: ['binance'])

    Returns:
        List of entries with exchange field added
    """
    if exchanges is None:
        exchanges = ['binance']

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


def read_redis_trades(limit: int = 1000) -> list:
    """
    Read trades from Redis 'trades' stream (stream architecture).

    Returns:
        List of trade dicts with standardized format.
        For SELL trades without profit data, calculates profit from matching BUY trades.
    """
    try:
        r = redis.from_url(os.getenv('REDIS_URL', 'redis://localhost:6379'), decode_responses=True)

        # Read from trades stream (oldest first for pairing)
        messages = r.xrange('trades', count=limit)

        trades = []
        # Track open positions per symbol for profit calculation
        open_positions: dict[str, list] = {}  # symbol -> [(price, qty, strategy)]

        for msg_id, data in messages:
            # Convert timestamp from millis to ISO format
            ts_millis = int(data.get('timestamp', msg_id.split('-')[0]))
            ts_dt = datetime.fromtimestamp(ts_millis / 1000)

            symbol = data.get('symbol', '')
            action = data.get('side', '').upper()
            price = float(data.get('price', 0))
            volume = float(data.get('quantity', 0))
            strategy = data.get('strategy', '')

            trade = {
                'id': data.get('order_id', msg_id),
                'timestamp': ts_dt.isoformat(),
                'action': action,
                'symbol': symbol,
                'price': price,
                'volume': volume,
                'market': data.get('market', 'spot'),
                'exchange': 'binance',
                'strategy': strategy,
                'paper': data.get('paper', 'true') == 'true',
                'profit': float(data.get('profit', 0)) if data.get('profit') else None,
                'profit_pct': float(data.get('profit_pct', 0)) if data.get('profit_pct') else None,
                'reason': data.get('reason', ''),
            }

            # Calculate profit for SELL trades without profit data
            if action == 'BUY':
                # Add to open positions
                if symbol not in open_positions:
                    open_positions[symbol] = []
                open_positions[symbol].append((price, volume, strategy))

            elif action == 'SELL' and trade['profit'] is None:
                # Try to match with open position
                if symbol in open_positions and open_positions[symbol]:
                    # Use FIFO - match with oldest BUY
                    entry_price, entry_qty, _ = open_positions[symbol][0]
                    # Calculate profit
                    matched_qty = min(volume, entry_qty)
                    profit = (price - entry_price) * matched_qty
                    profit_pct = ((price - entry_price) / entry_price * 100) if entry_price > 0 else 0

                    trade['profit'] = profit
                    trade['profit_pct'] = profit_pct

                    # Update or remove matched position
                    if volume >= entry_qty:
                        open_positions[symbol].pop(0)
                    else:
                        remaining = entry_qty - volume
                        open_positions[symbol][0] = (entry_price, remaining, strategy)

            trades.append(trade)

        # Return in reverse order (newest first)
        return list(reversed(trades))
    except Exception as e:
        print(f"Error reading Redis trades: {e}")
        return []


def read_redis_orders(limit: int = 200) -> list:
    """
    Read order intents/signals from Redis 'orders' stream.

    Returns:
        List of signal dicts
    """
    try:
        r = redis.from_url(os.getenv('REDIS_URL', 'redis://localhost:6379'), decode_responses=True)

        # Read from orders stream (pending signals)
        messages = r.xrevrange('orders', count=limit)

        signals = []
        for msg_id, data in messages:
            ts_millis = int(msg_id.split('-')[0])
            ts_dt = datetime.fromtimestamp(ts_millis / 1000)

            signal = {
                'id': data.get('id', msg_id),
                'timestamp': ts_dt.isoformat(),
                'action': data.get('side', '').upper(),
                'symbol': data.get('symbol', ''),
                'market': data.get('market', 'spot'),
                'strategy': data.get('strategy', ''),
                'reason': data.get('reason', ''),
                'exchange': 'binance',
            }
            signals.append(signal)

        return signals
    except Exception as e:
        print(f"Error reading Redis orders: {e}")
        return []


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
    domain = os.getenv("DASHBOARD_DOMAIN", DEFAULT_DOMAIN)
    port = os.getenv("DASHBOARD_PORT", DEFAULT_PORT)

    message = f"""
🖥️ *대시보드 시작*

🔗 접속: `https://{domain}:{port}/{DASHBOARD_PATH}`
🕐 시작 시간: `{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`
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
@requires_auth
def dashboard():
    """메인 대시보드 (Basic Auth 인증 필요)"""
    return render_template("dashboard.html")


@app.route("/api/status")
def get_status():
    """현재 상태 API - Binance-only stream architecture"""

    # Get current prices from Redis market:prices stream
    prices = {}
    try:
        r = redis.from_url(os.getenv('REDIS_URL', 'redis://localhost:6379'), decode_responses=True)
        # Read most recent prices from stream
        price_msgs = r.xrevrange('market:prices', count=100)
        seen_symbols = set()
        for msg_id, data in price_msgs:
            symbol = data.get('symbol', '')
            if symbol and symbol not in seen_symbols:
                prices[symbol] = float(data.get('price', 0))
                seen_symbols.add(symbol)
    except Exception as e:
        print(f"Error reading prices from Redis: {e}")

    # Get risk data from Redis
    risk = {}
    try:
        r = redis.from_url(os.getenv('REDIS_URL', 'redis://localhost:6379'), decode_responses=True)
        risk = r.hgetall('risk') or {}
    except Exception as e:
        print(f"Error reading risk from Redis: {e}")

    # Try to load from metrics service (Redis-based)
    if metrics_service:
        try:
            dashboard_state = metrics_service.get_dashboard_state()
            binance_data = dashboard_state.get('binance')

            if binance_data:
                # Build per-asset response
                assets = {}
                for pos in binance_data.get('positions', []):
                    symbol = pos.get('asset', 'BTC')
                    market = pos.get('market', 'spot')
                    key = f"{symbol}_{market}"
                    assets[key] = {
                        'symbol': symbol,
                        'exchange': 'binance',
                        'market': market,
                        'enabled': True,
                        'price': pos.get('current_price', 0),
                        'position_active': pos.get('qty', 0) > 0,
                        'position_qty': pos.get('qty', 0),
                        'direction': 'long' if market == 'spot' else 'short',
                        'strategy': pos.get('strategy', 'unknown'),
                        'entry_price': pos.get('entry_price', 0),
                        'unrealized_pnl': pos.get('unrealized_pnl', 0),
                        'unrealized_pnl_pct': pos.get('unrealized_pnl_pct', 0),
                    }

                # If no positions, show symbols with no position (one per symbol)
                if not assets:
                    for symbol in ['BTC', 'ETH', 'SOL']:
                        key = f"{symbol}_spot"
                        assets[key] = {
                            'symbol': symbol,
                            'exchange': 'binance',
                            'market': 'spot',
                            'enabled': True,
                            'price': prices.get(f'{symbol}USDT', 0),
                            'position_active': False,
                            'position_qty': 0,
                            'direction': 'long',
                            'strategy': 'None',
                        }

                status = {
                    'timestamp': dashboard_state.get('timestamp', datetime.now().isoformat()),
                    'mode': risk.get('mode', 'paper'),
                    'engine': 'stream',
                    'engine_status': 'running',
                    'trading_mode': risk.get('mode', 'paper'),
                    'assets': assets,
                    'portfolio': dashboard_state.get('portfolio', {}),
                    'kill_switch': binance_data.get('kill_switch', False),
                    'daily_pnl': binance_data.get('daily_pnl', 0),
                    'prices': prices,
                    'risk': risk,
                }
                return jsonify(status)
        except Exception as e:
            print(f"Error loading from metrics service: {e}")

    # Fallback: try legacy multi-asset status file
    ma_status = load_multi_asset_status()
    if ma_status:
        return jsonify({
            'timestamp': ma_status.get('timestamp', datetime.now().isoformat()),
            'mode': risk.get('mode', 'paper'),
            'engine': 'legacy',
            'engine_status': 'running',
            'trading_mode': risk.get('mode', 'paper'),
            'assets': ma_status.get('assets', {}),
            'portfolio': ma_status.get('portfolio', {}),
            'prices': prices,
            'risk': risk,
        })

    # Final fallback - return minimal status with prices/risk from Redis
    return jsonify({
        'timestamp': datetime.now().isoformat(),
        'mode': risk.get('mode', 'paper'),
        'engine_status': 'stopped' if not prices else 'running',
        'trading_mode': risk.get('mode', 'paper'),
        'prices': prices,
        'risk': risk,
    })


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

    # Read trades from Redis stream (stream architecture)
    redis_trades = read_redis_trades(limit=1000)

    # All trades from Redis (already formatted)
    all_trades = redis_trades

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


@app.route("/api/recent_trades")
def get_recent_trades():
    """
    Get recent trades in simplified format for dashboard.
    Query params: limit (default 20, max 50)
    """
    limit = request.args.get('limit', 20, type=int)
    limit = min(max(1, limit), 50)

    # Read trades from Redis stream
    redis_trades = read_redis_trades(limit=limit)

    # Transform to simplified format
    trades = []
    for t in redis_trades:
        trades.append({
            'id': t.get('id', ''),
            'timestamp': t.get('timestamp', ''),
            'symbol': t.get('symbol', ''),
            'side': t.get('action', '').lower(),
            'market': t.get('market', 'spot'),
            'quantity': t.get('volume', 0),
            'price': t.get('price', 0),
            'strategy': t.get('strategy', ''),
            'profit': t.get('profit'),
            'profit_pct': t.get('profit_pct'),
            'reason': t.get('reason', ''),
        })

    return jsonify(trades)


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

    # Read order intents from Redis orders stream (has reason/regime data)
    redis_orders = read_redis_orders(limit=limit * 2)  # Get more orders for matching

    # Build lookup of order reasons by (symbol, strategy, action) with timestamp
    # Store list of (timestamp, reason) tuples for each key
    order_reasons = {}
    for o in redis_orders:
        key = (o.get('symbol', ''), o.get('strategy', ''), o.get('action', '').upper())
        ts = o.get('timestamp', '')
        reason = o.get('reason', '')
        if reason:
            if key not in order_reasons:
                order_reasons[key] = []
            order_reasons[key].append((ts, reason))

    # Read executed trades from Redis (these are completed signals)
    redis_trades = read_redis_trades(limit=limit)

    # Transform trades to signal format, enriching with reason from orders
    signals = []
    for t in redis_trades:
        # Try to find reason from matching order by key and closest timestamp
        key = (t.get('symbol', ''), t.get('strategy', ''), t.get('action', '').upper())
        reason = t.get('reason', '')

        if not reason and key in order_reasons:
            # Find closest timestamp match
            trade_ts = t.get('timestamp', '')
            best_reason = ''
            best_diff = float('inf')
            for order_ts, order_reason in order_reasons[key]:
                try:
                    # Compare ISO timestamps
                    diff = abs((datetime.fromisoformat(trade_ts) - datetime.fromisoformat(order_ts)).total_seconds())
                    if diff < best_diff and diff < 60:  # Within 60 seconds
                        best_diff = diff
                        best_reason = order_reason
                except Exception:
                    pass
            reason = best_reason

        # Parse regime/market state from reason if present
        regime = ''
        market_state = ''
        strategy = t.get('strategy', '')

        if reason:
            # Extract regime from reason like "V35 entry: BULL_STRONG, MFI=77.0, ADX=35.4"
            if 'BULL_STRONG' in reason:
                regime = 'BULL'
                market_state = 'STRONG'
            elif 'BULL_MODERATE' in reason:
                regime = 'BULL'
                market_state = 'MODERATE'
            elif 'BEAR' in reason:
                regime = 'BEAR'
                market_state = 'TRENDING'
            elif 'SIDEWAYS' in reason or 'sideways' in reason.lower():
                regime = 'SIDEWAYS'
                market_state = 'RANGING'
        else:
            # Infer from strategy name when reason not available
            if 'v35_long' in strategy:
                regime = 'BULL'
                market_state = 'TRENDING'
            elif 'sideways' in strategy:
                regime = 'SIDEWAYS'
                market_state = 'RANGING'
            elif 'short' in strategy:
                regime = 'BEAR'
                market_state = 'TRENDING'

        signals.append({
            'timestamp': t.get('timestamp', ''),
            'exchange': t.get('exchange', 'binance'),
            'strategy': t.get('strategy', ''),
            'action': t.get('action', '').lower(),
            'symbol': t.get('symbol', ''),
            'market': t.get('market', 'spot'),
            'price': t.get('price', 0),
            'reason': reason,
            'regime': regime,
            'market_state': market_state,
            'acted': True,  # All trades from stream are executed
        })

    # Apply filters
    if exchange_filter:
        signals = [s for s in signals if s['exchange'] == exchange_filter]

    if action_filter:
        signals = [s for s in signals if s['action'] == action_filter.lower()]

    # Limit results
    signals = signals[:limit]

    return jsonify({
        'signals': signals,
        'total_count': len(signals)
    })


@app.route("/api/statistics")
def get_statistics():
    """통합 통계 API - Binance only"""

    binance_log = load_trading_log('binance')

    statistics = {
        'binance': binance_log.get('statistics', {}) if binance_log else {}
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

    # Get trades from Redis stream
    all_trades = read_redis_trades(limit=1000)

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

    # Get trades from Redis stream
    all_trades = read_redis_trades(limit=1000)

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

    # Get trades from Redis stream
    all_trades = read_redis_trades(limit=1000)

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


def _get_paper_positions(r, prices: dict) -> dict:
    """Get positions from Redis for paper trading mode."""
    result = {
        'timestamp': datetime.now().isoformat(),
        'total_value': 0,
        'total_unrealized_pnl': 0,
        'positions': [],
        'errors': []
    }

    symbols = ['BTC', 'ETH', 'SOL']

    for symbol in symbols:
        # Check spot position
        spot_pos = r.hgetall(f"positions:{symbol}:spot")
        if spot_pos and float(spot_pos.get('quantity', 0)) > 0:
            qty = float(spot_pos.get('quantity', 0))
            entry_price = float(spot_pos.get('entry_price', 0))
            current_price = prices.get(f'{symbol}USDT', entry_price)
            value = qty * current_price
            unrealized_pnl = (current_price - entry_price) * qty
            unrealized_pnl_pct = ((current_price - entry_price) / entry_price * 100) if entry_price > 0 else 0

            result['positions'].append({
                'symbol': f'{symbol}USDT',
                'exchange': 'binance',
                'market': 'spot',
                'side': 'LONG',
                'quantity': qty,
                'entry_price': entry_price,
                'current_price': current_price,
                'value': value,
                'unrealized_pnl': unrealized_pnl,
                'unrealized_pnl_pct': unrealized_pnl_pct,
                'strategy': spot_pos.get('strategy', 'unknown'),
                'leverage': 1
            })
            result['total_value'] += value
            result['total_unrealized_pnl'] += unrealized_pnl

        # Check futures position
        futures_pos = r.hgetall(f"positions:{symbol}:futures")
        if futures_pos and float(futures_pos.get('quantity', 0)) != 0:
            qty = float(futures_pos.get('quantity', 0))
            entry_price = float(futures_pos.get('entry_price', 0))
            current_price = prices.get(f'{symbol}USDT', entry_price)
            side = futures_pos.get('side', 'buy').upper()
            if side == 'BUY':
                side = 'LONG'
            elif side == 'SELL':
                side = 'SHORT'

            abs_qty = abs(qty)
            value = abs_qty * current_price

            if side == 'LONG':
                unrealized_pnl = (current_price - entry_price) * abs_qty
            else:
                unrealized_pnl = (entry_price - current_price) * abs_qty

            unrealized_pnl_pct = (unrealized_pnl / (entry_price * abs_qty) * 100) if entry_price > 0 else 0

            result['positions'].append({
                'symbol': f'{symbol}USDT',
                'exchange': 'binance',
                'market': 'futures',
                'side': side,
                'quantity': abs_qty,
                'entry_price': entry_price,
                'current_price': current_price,
                'value': value,
                'unrealized_pnl': unrealized_pnl,
                'unrealized_pnl_pct': unrealized_pnl_pct,
                'strategy': futures_pos.get('strategy', 'unknown'),
                'leverage': int(futures_pos.get('leverage', 1))
            })
            result['total_value'] += value
            result['total_unrealized_pnl'] += unrealized_pnl

    return result


@app.route("/api/positions")
def get_positions():
    """
    Get all Binance positions (Spot + Futures) with unrealized P&L.
    Also includes positions tracked in Redis by the trading bot.
    In paper mode, returns positions from Redis only.
    """
    # Check mode from Redis
    r = redis.from_url(os.getenv('REDIS_URL', 'redis://localhost:6379'), decode_responses=True)
    risk_data = r.hgetall('risk') or {}
    mode = risk_data.get('mode', 'paper')

    # Get current prices from Redis
    prices = {}
    try:
        price_data = r.hgetall('market:latest:prices') or {}
        for key, val in price_data.items():
            prices[key] = float(val)
    except Exception:
        pass

    # Paper mode: return positions from Redis only
    if mode == 'paper':
        return jsonify(_get_paper_positions(r, prices))

    # Live mode: fetch from Binance
    result = {
        'timestamp': datetime.now().isoformat(),
        'total_value': 0,
        'total_unrealized_pnl': 0,
        'positions': [],
        'errors': []
    }

    try:
        from binance.client import Client
        import time

        api_key = os.getenv('BINANCE_API_KEY')
        api_secret = os.getenv('BINANCE_API_SECRET')

        if not api_key or not api_secret:
            result['errors'].append('Binance: API credentials not configured')
            return jsonify(result)

        client = Client(api_key, api_secret)
        server_time = client.get_server_time()
        local_time = int(time.time() * 1000)
        client.timestamp_offset = server_time['serverTime'] - local_time

        # Get current prices
        prices = {}
        for ticker in client.get_all_tickers():
            prices[ticker['symbol']] = float(ticker['price'])

        # ==================== SPOT POSITIONS ====================
        spot_account = client.get_account(recvWindow=60000)

        # Get entry prices from Redis (tracked by trading bot)
        r = redis.from_url(os.getenv('REDIS_URL', 'redis://localhost:6379'), decode_responses=True)

        for balance in spot_account['balances']:
            asset = balance['asset']
            if asset in ['BTC', 'ETH', 'SOL']:
                total = float(balance['free']) + float(balance['locked'])
                if total > 0:
                    symbol = f"{asset}USDT"
                    current_price = prices.get(symbol, 0)
                    value = total * current_price

                    if value > 1:  # Only show if worth more than $1
                        # Try to get entry price from Redis
                        redis_pos = r.hgetall(f"positions:{asset}:spot")
                        entry_price = float(redis_pos.get('entry_price', current_price)) if redis_pos else current_price
                        strategy = redis_pos.get('strategy', 'manual') if redis_pos else 'manual'

                        # Calculate P&L
                        if entry_price > 0:
                            unrealized_pnl = (current_price - entry_price) * total
                            unrealized_pnl_pct = ((current_price - entry_price) / entry_price) * 100
                        else:
                            unrealized_pnl = 0
                            unrealized_pnl_pct = 0

                        result['positions'].append({
                            'symbol': symbol,
                            'exchange': 'binance',
                            'market': 'spot',
                            'side': 'LONG',
                            'quantity': total,
                            'entry_price': entry_price,
                            'current_price': current_price,
                            'value': value,
                            'unrealized_pnl': unrealized_pnl,
                            'unrealized_pnl_pct': unrealized_pnl_pct,
                            'strategy': strategy,
                            'leverage': 1
                        })
                        result['total_value'] += value
                        result['total_unrealized_pnl'] += unrealized_pnl

        # ==================== FUTURES POSITIONS ====================
        futures_account = client.futures_account(recvWindow=60000)

        for pos in futures_account['positions']:
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

                # Get strategy from Redis
                asset = pos['symbol'].replace('USDT', '')
                redis_pos = r.hgetall(f"positions:{asset}:futures")
                strategy = redis_pos.get('strategy', 'manual') if redis_pos else 'manual'

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
                    'market': 'futures',
                    'side': side,
                    'quantity': abs_size,
                    'entry_price': entry_price,
                    'current_price': mark_price,
                    'value': value,
                    'unrealized_pnl': unrealized_pnl,
                    'unrealized_pnl_pct': unrealized_pnl_pct,
                    'liquidation_price': liquidation_price if liquidation_price > 0 else None,
                    'strategy': strategy,
                    'leverage': leverage
                })
                result['total_value'] += value
                result['total_unrealized_pnl'] += unrealized_pnl

    except Exception as e:
        result['errors'].append(f'Binance: {str(e)}')

    return jsonify(result)


# =====================
# Backtest API Endpoints
# =====================

@app.route("/api/backtest/strategies")
@requires_auth
def get_backtest_strategies():
    """Get list of available strategies for backtesting."""
    if not backtest_runner:
        return jsonify({'error': 'Backtest service not available'}), 503

    strategies = backtest_runner.get_available_strategies()
    return jsonify({
        'strategies': strategies
    })


@app.route("/api/backtest/run", methods=["POST"])
@requires_auth
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
@requires_auth
def get_backtest_status(job_id: str):
    """Get status and results of a backtest job."""
    if not backtest_runner:
        return jsonify({'error': 'Backtest service not available'}), 503

    job = backtest_runner.get_job(job_id)
    if not job:
        return jsonify({'error': 'Job not found'}), 404

    return jsonify(job.to_dict())


@app.route("/api/backtest/cancel/<job_id>", methods=["POST"])
@requires_auth
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


@app.route("/api/backtest/history")
@requires_auth
def get_backtest_history():
    """Get list of all backtest jobs (history)."""
    if not backtest_runner:
        return jsonify({'error': 'Backtest service not available'}), 503

    jobs = backtest_runner.get_all_jobs()
    return jsonify({'jobs': jobs})


@app.route("/api/exchange_balances")
def get_exchange_balances():
    """Fetch balances from Binance (both Spot and Futures).
    In paper mode, returns simulated balances from Redis.
    """
    # Check mode from Redis
    r = redis.from_url(os.getenv('REDIS_URL', 'redis://localhost:6379'), decode_responses=True)
    risk_data = r.hgetall('risk') or {}
    mode = risk_data.get('mode', 'paper')

    result = {
        'timestamp': datetime.now().isoformat(),
        'binance': None,
        'errors': []
    }

    # Paper mode: return simulated balances from Redis
    if mode == 'paper':
        try:
            account = r.hgetall('account') or {}
            spot_balance = float(account.get('spot_balance', 10000))
            futures_balance = float(account.get('futures_balance', 10000))

            # Get prices from Redis
            prices = {}
            price_data = r.hgetall('market:latest:prices') or {}
            for key, val in price_data.items():
                prices[key] = float(val)

            # Calculate position values
            spot_positions = []
            futures_positions = []
            spot_position_value = 0
            futures_unrealized_pnl = 0

            for symbol in ['BTC', 'ETH', 'SOL']:
                # Spot positions
                spot_pos = r.hgetall(f"positions:{symbol}:spot")
                if spot_pos and float(spot_pos.get('quantity', 0)) > 0:
                    qty = float(spot_pos.get('quantity', 0))
                    entry_price = float(spot_pos.get('entry_price', 0))
                    current_price = prices.get(f'{symbol}USDT', entry_price)
                    value = qty * current_price
                    spot_positions.append({
                        'asset': symbol,
                        'market': 'spot',
                        'quantity': qty,
                        'price': current_price,
                        'value': value,
                    })
                    spot_position_value += value

                # Futures positions
                futures_pos = r.hgetall(f"positions:{symbol}:futures")
                if futures_pos and float(futures_pos.get('quantity', 0)) != 0:
                    qty = float(futures_pos.get('quantity', 0))
                    entry_price = float(futures_pos.get('entry_price', 0))
                    current_price = prices.get(f'{symbol}USDT', entry_price)
                    side = futures_pos.get('side', 'buy').upper()
                    if side == 'BUY':
                        side = 'LONG'
                    elif side == 'SELL':
                        side = 'SHORT'

                    abs_qty = abs(qty)
                    if side == 'LONG':
                        pnl = (current_price - entry_price) * abs_qty
                    else:
                        pnl = (entry_price - current_price) * abs_qty

                    futures_positions.append({
                        'symbol': symbol,
                        'market': 'futures',
                        'size': qty,
                        'side': side,
                        'entry_price': entry_price,
                        'mark_price': current_price,
                        'unrealized_pnl': pnl,
                        'leverage': int(futures_pos.get('leverage', 1)),
                        'liquidation_price': 0,
                    })
                    futures_unrealized_pnl += pnl

            total_equity = spot_balance + spot_position_value + futures_balance + futures_unrealized_pnl

            result['binance'] = {
                'spot': {
                    'usdt_balance': spot_balance,
                    'position_value': spot_position_value,
                    'total': spot_balance + spot_position_value,
                    'positions': spot_positions,
                },
                'futures': {
                    'usdt_balance': futures_balance,
                    'unrealized_pnl': futures_unrealized_pnl,
                    'total': futures_balance + futures_unrealized_pnl,
                    'positions': futures_positions,
                    'hedge_mode': False,
                },
                'total_equity': total_equity,
            }
            return jsonify(result)

        except Exception as e:
            result['errors'].append(f'Paper mode error: {str(e)}')
            return jsonify(result)

    # Live mode: fetch from Binance
    try:
        from binance.client import Client
        import time
        api_key = os.getenv('BINANCE_API_KEY')
        api_secret = os.getenv('BINANCE_API_SECRET')

        if not api_key or not api_secret:
            result['errors'].append('Binance: API credentials not configured')
            return jsonify(result)

        # Sync time offset with Binance server
        client = Client(api_key, api_secret)
        server_time = client.get_server_time()
        local_time = int(time.time() * 1000)
        client.timestamp_offset = server_time['serverTime'] - local_time

        # ==================== SPOT ACCOUNT ====================
        spot_account = client.get_account(recvWindow=60000)
        spot_usdt = 0.0
        spot_positions = []

        # Get current prices for value calculation
        prices = {}
        for ticker in client.get_all_tickers():
            prices[ticker['symbol']] = float(ticker['price'])

        for balance in spot_account['balances']:
            asset = balance['asset']
            free = float(balance['free'])
            locked = float(balance['locked'])
            total = free + locked

            if total > 0:
                if asset == 'USDT':
                    spot_usdt = total
                elif asset in ['BTC', 'ETH', 'SOL']:
                    symbol = f"{asset}USDT"
                    price = prices.get(symbol, 0)
                    value = total * price
                    if value > 1:  # Only show if worth more than $1
                        spot_positions.append({
                            'asset': asset,
                            'market': 'spot',
                            'quantity': total,
                            'price': price,
                            'value': value,
                        })

        spot_position_value = sum(p['value'] for p in spot_positions)

        # ==================== FUTURES ACCOUNT ====================
        futures_account = client.futures_account(recvWindow=60000)
        futures_usdt = 0.0
        futures_unrealized_pnl = 0.0
        futures_positions = []

        for asset in futures_account['assets']:
            if asset['asset'] == 'USDT':
                futures_usdt = float(asset['walletBalance'])
                futures_unrealized_pnl = float(asset['unrealizedProfit'])
                break

        # Check hedge mode status (dualSidePosition)
        hedge_mode_enabled = False
        try:
            position_mode = client.futures_get_position_mode(recvWindow=60000)
            hedge_mode_enabled = position_mode.get('dualSidePosition', False)
        except Exception:
            pass  # Fall back to False if not available

        for pos in futures_account['positions']:
            size = float(pos['positionAmt'])
            if size != 0:
                # Determine position side
                position_side = pos.get('positionSide', 'BOTH')
                if position_side == 'BOTH':
                    # One-way mode: derive from size
                    side = 'LONG' if size > 0 else 'SHORT'
                else:
                    # Hedge mode: use positionSide directly
                    side = position_side

                futures_positions.append({
                    'symbol': pos['symbol'].replace('USDT', ''),
                    'market': 'futures',
                    'size': size,
                    'side': side,
                    'entry_price': float(pos['entryPrice']),
                    'mark_price': float(pos['markPrice']),
                    'unrealized_pnl': float(pos['unrealizedProfit']),
                    'leverage': int(pos['leverage']),
                    'liquidation_price': float(pos.get('liquidationPrice', 0)),
                })

        # ==================== COMBINED SUMMARY ====================
        total_equity = spot_usdt + spot_position_value + futures_usdt + futures_unrealized_pnl

        result['binance'] = {
            'spot': {
                'usdt_balance': spot_usdt,
                'position_value': spot_position_value,
                'total': spot_usdt + spot_position_value,
                'positions': spot_positions,
            },
            'futures': {
                'usdt_balance': futures_usdt,
                'unrealized_pnl': futures_unrealized_pnl,
                'total': futures_usdt + futures_unrealized_pnl,
                'positions': futures_positions,
                'hedge_mode': hedge_mode_enabled,
            },
            'total_equity': total_equity,
        }

    except Exception as e:
        result['errors'].append(f'Binance: {str(e)}')

    return jsonify(result)


# =============================================================================
# Real-Time Metrics Dashboard Endpoints
# =============================================================================

@app.route("/api/metrics/realtime")
def get_realtime_metrics():
    """
    Get real-time trading metrics for the dashboard.

    Returns DashboardState JSON with:
    - Current strategy decisions for Binance
    - Position and P&L information
    - Connection status (Redis-based)
    """
    if not metrics_service:
        return jsonify({'error': 'Metrics service not available'}), 500

    try:
        dashboard_state = metrics_service.get_dashboard_state()

        # Check if any data is available
        if not dashboard_state.get('binance'):
            return jsonify({
                'error': 'No trading data available',
                'message': 'Trading bot may not be running or Redis not connected'
            }), 404

        return jsonify(dashboard_state)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route("/api/metrics/leverage")
def get_leverage_state():
    """
    Get current leverage manager state.

    Returns:
    - peak_equity: High water mark
    - current_equity: Current account equity
    - drawdown_pct: Current drawdown percentage
    - tier: Current leverage tier name
    - leverage: Allowed leverage multiplier
    - daily_loss_pct: Daily loss as percentage
    - tiers: All defined tiers with active indicator
    """
    try:
        r = redis.from_url(os.getenv('REDIS_URL', 'redis://localhost:6379'), decode_responses=True)
        state = r.hgetall("leverage:state")

        if not state:
            return jsonify({
                'enabled': False,
                'message': 'LeverageManager not initialized'
            })

        # Parse state values
        return jsonify({
            'enabled': True,
            'peak_equity': float(state.get('peak_equity', 0)),
            'current_equity': float(state.get('current_equity', 0)),
            'drawdown_pct': float(state.get('drawdown_pct', 0)),
            'tier': state.get('current_tier', 'unknown'),
            'leverage': int(state.get('current_leverage', 1)),
            'daily_pnl': float(state.get('daily_pnl', 0) if 'daily_pnl' in state else 0),
            'last_updated': state.get('last_updated', ''),
            'tiers': [
                {'name': 'full', 'drawdown_max_pct': 5, 'leverage': 5},
                {'name': 'reduced', 'drawdown_max_pct': 10, 'leverage': 3},
                {'name': 'cautious', 'drawdown_max_pct': 15, 'leverage': 2},
                {'name': 'minimal', 'drawdown_max_pct': 20, 'leverage': 1},
                {'name': 'halted', 'drawdown_max_pct': 100, 'leverage': 0},
            ]
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route("/api/metrics/decisions")
def get_decision_history():
    """
    Get strategy decision history with optional filtering.

    Query parameters:
    - hours: Hours of history to return (default 24, max 72)
    - limit: Maximum number of decisions (default 50, max 200)
    """
    if not metrics_service:
        return jsonify({'error': 'Metrics service not available'}), 500

    try:
        hours = max(1, min(int(request.args.get('hours', 24)), 72))
        limit = max(1, min(int(request.args.get('limit', 50)), 200))

        decisions = metrics_service.get_recent_decisions(
            hours=hours,
            limit=limit,
            exchange='binance'  # Binance-only now
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
    print(f"Basic Auth required (admin / @1tidh6ls6ls)")
    print(f"{'='*50}\n")

    # 텔레그램으로 대시보드 URL 알림
    _notify_dashboard_url(port=5080)

    app.run(host="0.0.0.0", port=5080, debug=False)
