#!/usr/bin/env python3
"""
app.py
Flask 웹 대시보드 - Dual Exchange Paper Trading 모니터링
"""

# pylint: disable=broad-exception-caught

from flask import Flask, render_template, jsonify, request, Response
from flask_cors import CORS
from functools import wraps
import secrets
import json
import os
import requests
from pathlib import Path
from datetime import datetime, timedelta

import redis
from redis import ConnectionPool

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

# Import backtest DB (for history/details fallback)
try:
    from services import backtest_db
except Exception as e:
    print(f"Failed to import backtest_db: {e}")
    backtest_db = None

# Import metrics service for real-time dashboard
try:
    from services.metrics_service import metrics_service
except Exception as e:
    print(f"Failed to import metrics_service: {e}")
    metrics_service = None

# Import Quant Lab blueprint
try:
    from quant_lab.routes import quant_lab_bp
except Exception as e:
    print(f"Failed to import quant_lab: {e}")
    quant_lab_bp = None

# Shared runtime defaults
try:
    from trading.core.runtime_defaults import default_backtest_date_range
except Exception:
    def default_backtest_date_range(days: int = 365) -> tuple[str, str]:
        end_dt = datetime.now().date()
        start_dt = end_dt - timedelta(days=max(1, int(days)))
        return start_dt.isoformat(), end_dt.isoformat()

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY") or secrets.token_hex(32)
CORS(app)

# Register Quant Lab blueprint
if quant_lab_bp:
    app.register_blueprint(quant_lab_bp, url_prefix='/quant-lab')

BASE_DIR = Path(__file__).parent

# Valid exchange names (prevents path traversal attacks)
VALID_EXCHANGES = {
    ex.strip().lower()
    for ex in os.getenv("VALID_EXCHANGES", "binance").split(",")
    if ex.strip()
}

# Redis connection pool (shared across all requests)
_redis_pool = ConnectionPool.from_url(
    os.getenv('REDIS_URL', 'redis://localhost:6379'),
    decode_responses=True,
    max_connections=20
)


def get_redis() -> redis.Redis:
    """Get a Redis connection from the pool."""
    return redis.Redis(connection_pool=_redis_pool)


# 대시보드 경로/주소 기본값
# Localhost must stay local by default (no domain redirection guidance).
DEFAULT_DOMAIN = "localhost"
DEFAULT_PORT = "5080"
DEFAULT_DASHBOARD_PATH = "btc-dashboard"
DASHBOARD_PATH = (os.getenv("DASHBOARD_PATH", DEFAULT_DASHBOARD_PATH) or DEFAULT_DASHBOARD_PATH).strip("/")
DASHBOARD_PATH = DASHBOARD_PATH or DEFAULT_DASHBOARD_PATH

DEFAULT_DASHBOARD_SYMBOLS = ("BTC", "ETH", "SOL")

# 대시보드 인증 정보 (Basic Auth) - loaded from environment variables
DASHBOARD_USERNAME = os.getenv("DASHBOARD_USERNAME", "admin")
DASHBOARD_PASSWORD = os.getenv("DASHBOARD_PASSWORD")
if not DASHBOARD_PASSWORD:
    raise ValueError("DASHBOARD_PASSWORD environment variable must be set")


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
            with open(config_path, encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _parse_symbol_list(raw_symbols) -> list[str]:
    if not isinstance(raw_symbols, list):
        return []
    normalized: list[str] = []
    seen: set[str] = set()
    for item in raw_symbols:
        symbol = _normalize_symbol(item)
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        normalized.append(symbol)
    return normalized


def _load_dashboard_symbols(config: dict | None = None) -> list[str]:
    if config is None:
        config = load_allocation_config()
    from_config = _parse_symbol_list(config.get("symbols", [])) if isinstance(config, dict) else []
    if from_config:
        return from_config

    env_symbols = [_normalize_symbol(token) for token in os.getenv("DASHBOARD_DEFAULT_SYMBOLS", "").split(",")]
    env_symbols = [symbol for symbol in env_symbols if symbol]
    if env_symbols:
        unique_symbols: list[str] = []
        seen = set()
        for symbol in env_symbols:
            if symbol in seen:
                continue
            seen.add(symbol)
            unique_symbols.append(symbol)
        return unique_symbols

    return list(DEFAULT_DASHBOARD_SYMBOLS)


def _dashboard_api_base() -> str:
    raw_base = (os.getenv("DASHBOARD_API_BASE", "") or "").strip()
    if not raw_base or raw_base == "/":
        return ""
    return "/" + raw_base.strip("/")


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
    """Trading 로그 로드 (v2 engine 우선, 없으면 paper fallback).

    Args:
        exchange: Exchange name (must be in VALID_EXCHANGES)

    Returns:
        Loaded JSON data or None if not found/invalid
    """
    # Validate exchange to prevent path traversal
    if exchange not in VALID_EXCHANGES:
        print(f"Invalid exchange: {exchange}")
        return None

    candidates = [
        LOG_DIR / f"v2_engine_{exchange}.json",
        LOG_DIR / f"paper_trading_{exchange}.json",
    ]

    for log_file in candidates:
        if log_file.exists():
            try:
                with open(log_file, 'r', encoding='utf-8') as f:
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
        r = get_redis()

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
                'market': data.get('market', 'futures'),
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


def get_latest_prices() -> dict:
    """
    Get latest prices from Redis market:prices stream.

    Returns:
        Dict mapping symbol (e.g., 'BTCUSDT') to price
    """
    try:
        r = get_redis()

        # Read recent entries from price stream to get latest for each symbol
        messages = r.xrevrange('market:prices', count=100)

        prices = {}
        seen_symbols = set()
        for _, data in messages:
            symbol = data.get('symbol', '')
            if symbol and symbol not in seen_symbols:
                price = float(data.get('price', 0))
                if price > 0:
                    # Store as BTCUSDT format for compatibility
                    prices[f'{symbol}USDT'] = price
                    seen_symbols.add(symbol)

        return prices
    except Exception as e:
        print(f"Error reading prices from stream: {e}")
        return {}



def _normalize_symbol(symbol: str) -> str:
    """
    Normalize symbol to base asset format (e.g., BTCUSDT -> BTC).
    """
    if not symbol:
        return ""

    normalized = str(symbol).strip().upper()
    if "/" in normalized:
        normalized = normalized.split("/", 1)[0]
    if ":" in normalized:
        normalized = normalized.split(":", 1)[0]

    for suffix in ("USDT", "BUSD", "USDC", "USD"):
        if normalized.endswith(suffix) and len(normalized) > len(suffix):
            return normalized[:-len(suffix)]
    return normalized


def _read_latest_regime_status(r: redis.Redis, limit: int = 300) -> dict:
    """
    Read latest per-symbol regime/trend from strategy decisions stream.
    """
    regime_status = {}

    try:
        messages = r.xrevrange('strategy:decisions', count=limit)
    except Exception as e:
        print(f"Error reading regime status from Redis: {e}")
        return regime_status

    for msg_id, data in messages:
        raw_symbol = data.get('symbol', '')
        symbol = _normalize_symbol(raw_symbol)
        if not symbol or symbol in regime_status:
            continue

        ts_raw = data.get('timestamp', msg_id.split('-')[0])
        try:
            ts_ms = int(float(ts_raw))
            ts_iso = datetime.fromtimestamp(ts_ms / 1000).isoformat()
        except (TypeError, ValueError):
            ts_iso = str(ts_raw)

        regime_status[symbol] = {
            'symbol': symbol,
            'regime': data.get('regime', 'UNKNOWN'),
            'trend': data.get('trend', 'UNKNOWN'),
            'decision': data.get('decision', data.get('action', 'WAIT')),
            'timestamp': ts_iso,
        }

    return regime_status

def read_redis_orders(limit: int = 200) -> list:
    """
    Read order intents/signals from Redis 'orders' stream.

    Returns:
        List of signal dicts
    """
    try:
        r = get_redis()

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
                'market': data.get('market', 'futures'),
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
            with open(status_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"Multi-asset status load failed: {e}")
    return None


def _require_admin_token() -> bool:
    """Very small guard for mutating endpoints."""
    token = os.getenv("WEB_ADMIN_TOKEN")
    if not token:
        return False
    return request.headers.get("X-Admin-Token") == token


def _parse_kill_switch_value(value) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _get_redis_kill_switch() -> bool | None:
    """Return Redis kill-switch status, or None when unavailable."""
    try:
        risk = get_redis().hgetall("risk") or {}
        if "kill_switch" not in risk:
            return None
        return _parse_kill_switch_value(risk.get("kill_switch"))
    except Exception as e:
        print(f"Error reading kill_switch from Redis: {e}")
        return None


def _set_redis_kill_switch(active: bool) -> bool:
    """Set Redis kill-switch flag. Returns True on success."""
    try:
        get_redis().hset("risk", "kill_switch", "true" if active else "false")
        return True
    except Exception as e:
        print(f"Error writing kill_switch to Redis: {e}")
        return False


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


def _notify_dashboard_url():
    """대시보드 URL을 텔레그램으로 알림"""
    domain = os.getenv("DASHBOARD_DOMAIN", DEFAULT_DOMAIN)
    port = os.getenv("DASHBOARD_PORT", DEFAULT_PORT)
    scheme = "http" if domain in ("localhost", "127.0.0.1") else "https"

    message = f"""
🖥️ *대시보드 시작*

🔗 접속: `{scheme}://{domain}:{port}/{DASHBOARD_PATH}`
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
    css_path = BASE_DIR / "static" / "css" / "style.css"
    js_path = BASE_DIR / "static" / "js" / "dashboard.js"
    allocation_config = load_allocation_config()
    return render_template(
        "dashboard.html",
        css_version=int(css_path.stat().st_mtime) if css_path.exists() else 1,
        js_version=int(js_path.stat().st_mtime) if js_path.exists() else 1,
        dashboard_path=DASHBOARD_PATH,
        dashboard_symbols=_load_dashboard_symbols(allocation_config),
        api_base=_dashboard_api_base(),
    )

_STATUS_FALLBACK_MAX_ASSETS = 28


def _read_status_prices(r: redis.Redis, count: int = 100) -> dict:
    prices: dict = {}
    seen_symbols = set()
    for _, data in r.xrevrange('market:prices', count=count):
        symbol = str(data.get('symbol', '')).strip().upper()
        if not symbol or symbol in seen_symbols:
            continue
        price = _safe_float(data.get('price', 0))
        if price <= 0:
            seen_symbols.add(symbol)
            continue
        prices[symbol] = price
        base_symbol = _normalize_symbol(symbol)
        if base_symbol:
            prices[base_symbol] = price
        seen_symbols.add(symbol)
    return prices


def _load_status_prices_and_regimes() -> tuple[dict, dict]:
    try:
        r = get_redis()
        prices = _read_status_prices(r)
        regime_status = _read_latest_regime_status(r)
        return prices, regime_status
    except Exception as e:
        print(f"Error reading prices from Redis: {e}")
        return {}, {}


def _load_status_risk() -> dict:
    try:
        return get_redis().hgetall('risk') or {}
    except Exception as e:
        print(f"Error reading risk from Redis: {e}")
        return {}


def _build_status_asset_from_position(pos: dict, regime_status: dict) -> tuple[str, dict]:
    symbol = _normalize_symbol(pos.get('asset', 'BTC'))
    market = pos.get('market', 'futures')
    key = f"{symbol}_{market}"
    regime_info = regime_status.get(symbol, {})
    payload = {
        'symbol': symbol,
        'exchange': 'binance',
        'market': market,
        'enabled': True,
        'price': pos.get('current_price', 0),
        'position_active': pos.get('qty', 0) > 0,
        'position_qty': pos.get('qty', 0),
        'direction': pos.get('side', 'long'),
        'strategy': pos.get('strategy', 'unknown'),
        'entry_price': pos.get('entry_price', 0),
        'unrealized_pnl': pos.get('unrealized_pnl', 0),
        'unrealized_pnl_pct': pos.get('unrealized_pnl_pct', 0),
        'regime': regime_info.get('regime', 'UNKNOWN'),
        'trend': regime_info.get('trend', 'UNKNOWN'),
        'regime_updated_at': regime_info.get('timestamp', ''),
    }
    return key, payload


def _build_status_assets_from_positions(binance_positions: list, regime_status: dict) -> dict:
    assets: dict = {}
    for pos in binance_positions:
        key, payload = _build_status_asset_from_position(pos, regime_status)
        assets[key] = payload
    return assets


def _parse_selector_symbol_list(payload: str | None) -> list[str]:
    if not payload:
        return []
    try:
        raw = json.loads(payload)
    except (TypeError, json.JSONDecodeError):
        return []
    if not isinstance(raw, list):
        return []
    symbols: list[str] = []
    for item in raw:
        symbol = _normalize_symbol(str(item))
        if symbol:
            symbols.append(symbol)
    return symbols


def _parse_selector_top_scores(payload: str | None) -> list[str]:
    if not payload:
        return []
    try:
        raw = json.loads(payload)
    except (TypeError, json.JSONDecodeError):
        return []
    if not isinstance(raw, list):
        return []
    symbols: list[str] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        symbol = _normalize_symbol(str(item.get("symbol", "")))
        if symbol:
            symbols.append(symbol)
    return symbols


def _load_selector_fallback_symbols(r: redis.Redis, limit: int = _STATUS_FALLBACK_MAX_ASSETS) -> list[str]:
    symbols: list[str] = []
    seen: set[str] = set()
    try:
        keys = sorted(r.keys("strategy:selector:latest:*") or [])
    except Exception:
        return symbols

    for key in keys:
        try:
            state = r.hgetall(key) or {}
        except Exception:
            continue

        candidates = _parse_selector_symbol_list(state.get("selected_symbols"))
        if not candidates:
            candidates = _parse_selector_top_scores(state.get("top_scores"))

        for symbol in candidates:
            if symbol in seen:
                continue
            seen.add(symbol)
            symbols.append(symbol)
            if len(symbols) >= limit:
                return symbols
    return symbols


def _build_status_fallback_assets(
    prices: dict,
    regime_status: dict,
    selector_symbols: list[str] | None = None,
) -> dict:
    fallback_symbols = _load_dashboard_symbols()
    base_symbol_count = len(fallback_symbols)

    if selector_symbols:
        for symbol in selector_symbols:
            normalized = _normalize_symbol(symbol)
            if normalized and normalized not in fallback_symbols:
                fallback_symbols.append(normalized)
    else:
        # Legacy-safe fallback when selector state is unavailable:
        # keep snapshot compact by adding only a few symbols from recent prices.
        for raw_symbol in prices.keys():
            symbol = _normalize_symbol(raw_symbol)
            if not symbol or symbol in fallback_symbols:
                continue
            fallback_symbols.append(symbol)
            if len(fallback_symbols) >= min(_STATUS_FALLBACK_MAX_ASSETS, base_symbol_count + 8):
                break

    fallback_symbols = fallback_symbols[:_STATUS_FALLBACK_MAX_ASSETS]

    assets: dict = {}
    for symbol in fallback_symbols:
        regime_info = regime_status.get(symbol, {})
        assets[f"{symbol}_futures"] = {
            'symbol': symbol,
            'exchange': 'binance',
            'market': 'futures',
            'enabled': True,
            'price': prices.get(symbol, prices.get(f'{symbol}USDT', 0)),
            'position_active': False,
            'position_qty': 0,
            'direction': 'long',
            'strategy': '-',
            'regime': regime_info.get('regime', 'UNKNOWN'),
            'trend': regime_info.get('trend', 'UNKNOWN'),
            'regime_updated_at': regime_info.get('timestamp', ''),
        }
    return assets


def _build_stream_status(
    dashboard_state: dict,
    binance_data: dict,
    prices: dict,
    regime_status: dict,
    risk: dict,
    selector_symbols: list[str] | None = None,
) -> dict:
    assets = _build_status_assets_from_positions(binance_data.get('positions', []), regime_status)
    if not assets:
        assets = _build_status_fallback_assets(prices, regime_status, selector_symbols=selector_symbols)

    return {
        'timestamp': dashboard_state.get('timestamp', datetime.now().isoformat()),
        'mode': risk.get('mode', 'paper'),
        'engine': 'stream',
        'engine_status': 'running',
        'trading_mode': risk.get('mode', 'paper'),
        'assets': assets,
        'portfolio': dashboard_state.get('portfolio', {}),
        'kill_switch': _parse_kill_switch_value(risk.get('kill_switch', 'false')),
        'daily_pnl': binance_data.get('daily_pnl', 0),
        'prices': prices,
        'regime_status': regime_status,
        'risk': risk,
    }


def _load_stream_status(prices: dict, regime_status: dict, risk: dict) -> dict | None:
    if not metrics_service:
        return None
    try:
        dashboard_state = metrics_service.get_dashboard_state()
        binance_data = dashboard_state.get('binance')
        if not binance_data:
            return None
        selector_symbols: list[str] = []
        try:
            selector_symbols = _load_selector_fallback_symbols(get_redis())
        except Exception as e:
            print(f"Error loading selector fallback symbols: {e}")
        return _build_stream_status(
            dashboard_state,
            binance_data,
            prices,
            regime_status,
            risk,
            selector_symbols=selector_symbols,
        )
    except Exception as e:
        print(f"Error loading from metrics service: {e}")
        return None


def _build_legacy_status(ma_status: dict, prices: dict, regime_status: dict, risk: dict) -> dict:
    return {
        'timestamp': ma_status.get('timestamp', datetime.now().isoformat()),
        'mode': risk.get('mode', 'paper'),
        'engine': 'legacy',
        'engine_status': 'running',
        'trading_mode': risk.get('mode', 'paper'),
        'assets': ma_status.get('assets', {}),
        'portfolio': ma_status.get('portfolio', {}),
        'prices': prices,
        'regime_status': regime_status,
        'risk': risk,
    }


def _build_minimal_status(prices: dict, regime_status: dict, risk: dict) -> dict:
    return {
        'timestamp': datetime.now().isoformat(),
        'mode': risk.get('mode', 'paper'),
        'engine_status': 'stopped' if not prices else 'running',
        'trading_mode': risk.get('mode', 'paper'),
        'prices': prices,
        'regime_status': regime_status,
        'risk': risk,
    }


@app.route("/api/status")
def get_status():
    """현재 상태 API - Binance-only stream architecture"""
    prices, regime_status = _load_status_prices_and_regimes()
    risk = _load_status_risk()

    stream_status = _load_stream_status(prices, regime_status, risk)
    if stream_status:
        return jsonify(stream_status)

    ma_status = load_multi_asset_status()
    if ma_status:
        return jsonify(_build_legacy_status(ma_status, prices, regime_status, risk))

    return jsonify(_build_minimal_status(prices, regime_status, risk))


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
            port=int(os.getenv("REDIS_PORT", "6379")),
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
    redis_active = _get_redis_kill_switch()
    file_active = KILL_SWITCH_FILE.exists()
    active = redis_active if redis_active is not None else file_active
    return jsonify({
        "active": active,
        "redis_active": redis_active,
        "file_active": file_active,
        "source": "redis" if redis_active is not None else "file",
        "path": str(KILL_SWITCH_FILE),
        "checked_at": datetime.now().isoformat(),
    })


@app.route("/api/kill_switch/on", methods=["POST"])
def kill_switch_on():
    if not _require_admin_token():
        return jsonify({"error": "forbidden"}), 403
    KILL_SWITCH_FILE.parent.mkdir(parents=True, exist_ok=True)
    KILL_SWITCH_FILE.touch(exist_ok=True)
    _set_redis_kill_switch(True)
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
    _set_redis_kill_switch(False)
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


def _parse_trade_query_params() -> dict:
    page = request.args.get('page', 1, type=int)
    limit = request.args.get('limit', 100, type=int)
    return {
        'page': page,
        'limit': min(max(1, limit), 500),
        'exchange_filter': request.args.get('exchange'),
        'start_date': request.args.get('start_date'),
        'end_date': request.args.get('end_date'),
        'symbol_filter': request.args.get('symbol'),
    }


def _is_paper_mode_active() -> bool:
    r = get_redis()
    risk_data = r.hgetall('risk') or {}
    return risk_data.get('mode', 'paper') == 'paper'


def _filter_trade_history(
    redis_trades: list[dict],
    *,
    is_paper_mode: bool,
    exchange_filter: str | None,
    symbol_filter: str | None,
    start_date: str | None,
    end_date: str | None,
) -> list[dict]:
    filtered = [t for t in redis_trades if t.get('paper', True) == is_paper_mode]

    if exchange_filter:
        filtered = [t for t in filtered if t['exchange'] == exchange_filter]

    if symbol_filter:
        filtered = [t for t in filtered if symbol_filter.upper() in t.get('symbol', 'BTC').upper()]

    if start_date:
        filtered = [t for t in filtered if t['timestamp'] >= start_date]

    if end_date:
        filtered = [t for t in filtered if t['timestamp'] <= end_date + 'T23:59:59']

    filtered.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
    return filtered


def _paginate_trades(trades: list[dict], *, page: int, limit: int) -> tuple[list[dict], int, int]:
    total_count = len(trades)
    start_idx = (page - 1) * limit
    end_idx = start_idx + limit
    return trades[start_idx:end_idx], total_count, end_idx


def _summarize_filtered_trades(filtered_trades: list[dict]) -> dict:
    buy_count = 0
    sell_count = 0
    spot_count = 0
    futures_count = 0
    realized_count = 0
    realized_pnl = 0.0
    winning = 0
    symbols: set[str] = set()

    for trade in filtered_trades:
        action = trade.get('action')
        if action == 'BUY':
            buy_count += 1
        elif action == 'SELL':
            sell_count += 1

        market = trade.get('market')
        if market == 'spot':
            spot_count += 1
        elif market == 'futures':
            futures_count += 1

        symbol = trade.get('symbol')
        if symbol:
            symbols.add(symbol)

        if trade.get('profit') is None:
            continue
        pnl_value = float(trade.get('profit', 0) or 0)
        realized_count += 1
        realized_pnl += pnl_value
        if pnl_value > 0:
            winning += 1

    win_rate = (winning / realized_count * 100) if realized_count else None

    return {
        'buy_count': buy_count,
        'sell_count': sell_count,
        'spot_count': spot_count,
        'futures_count': futures_count,
        'realized_trade_count': realized_count,
        'realized_pnl': realized_pnl,
        'win_rate': win_rate,
        'unique_symbols': sorted(symbols),
    }


@app.route("/api/trades")
def get_trades():
    """
    Get paginated trade history with filters.
    Query params: page, limit, exchange, start_date, end_date, symbol
    """
    params = _parse_trade_query_params()
    page = params['page']
    limit = params['limit']

    is_paper_mode = _is_paper_mode_active()
    redis_trades = read_redis_trades(limit=1000)
    filtered_trades = _filter_trade_history(
        redis_trades,
        is_paper_mode=is_paper_mode,
        exchange_filter=params['exchange_filter'],
        symbol_filter=params['symbol_filter'],
        start_date=params['start_date'],
        end_date=params['end_date'],
    )
    paginated_trades, total_count, end_idx = _paginate_trades(
        filtered_trades,
        page=page,
        limit=limit,
    )
    summary = _summarize_filtered_trades(filtered_trades)

    return jsonify({
        'trades': paginated_trades,
        'total_count': total_count,
        'page': page,
        'limit': limit,
        'has_more': end_idx < total_count,
        'summary': summary,
    })


@app.route("/api/recent_trades")
def get_recent_trades():
    """
    Get recent trades in simplified format for dashboard.
    Query params: limit (default 20, max 50)
    """
    limit = request.args.get('limit', 20, type=int)
    limit = min(max(1, limit), 50)

    # Get current mode from Redis
    r = get_redis()
    risk_data = r.hgetall('risk') or {}
    mode = risk_data.get('mode', 'paper')
    is_paper_mode = (mode == 'paper')

    # Read trades from Redis stream and filter by mode
    redis_trades = read_redis_trades(limit=limit * 2)  # Read more to account for filtering
    redis_trades = [t for t in redis_trades if t.get('paper', True) == is_paper_mode][:limit]

    # Transform to simplified format
    trades = []
    for t in redis_trades:
        trades.append({
            'id': t.get('id', ''),
            'timestamp': t.get('timestamp', ''),
            'symbol': t.get('symbol', ''),
            'side': t.get('action', '').lower(),
            'market': t.get('market', 'futures'),
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
    Get recent market-analysis signals (strategy decisions) with optional filters.
    Query params: limit, hours, exchange, action
    """
    limit = request.args.get('limit', 50, type=int)
    hours = request.args.get('hours', 24, type=int)
    exchange_filter = request.args.get('exchange')
    action_filter = request.args.get('action')

    # Clamp limit
    limit = min(max(1, limit), 200)
    hours = min(max(1, hours), 72)

    # Signals tab should represent current market analysis (decision/regime),
    # not executed trade history.
    signals = []
    if metrics_service:
        decisions = metrics_service.get_recent_decisions(
            hours=hours,
            limit=limit,
            exchange='binance',
        )
        for d in decisions:
            regime = d.get('regime', '')
            market_state = ''
            if 'BULL_STRONG' in regime:
                market_state = 'STRONG'
            elif 'BULL' in regime:
                market_state = 'BULL'
            elif 'BEAR' in regime:
                market_state = 'BEAR'
            elif 'SIDEWAYS' in regime:
                market_state = 'RANGING'

            decision = (d.get('decision') or 'WAIT').upper()
            signals.append({
                'timestamp': d.get('timestamp', ''),
                'exchange': d.get('exchange', 'binance'),
                'strategy': d.get('strategy', ''),
                'action': decision.lower(),
                'decision': decision,
                'symbol': d.get('symbol', ''),
                'market': d.get('market', 'futures'),
                'price': (d.get('indicators') or {}).get('price', 0),
                'reason': d.get('reason', ''),
                'regime': regime,
                'market_state': market_state,
                'acted': False,
                'indicators': d.get('indicators', {}),
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

    # Get current mode from Redis
    r = get_redis()
    risk_data = r.hgetall('risk') or {}
    mode = risk_data.get('mode', 'paper')
    is_paper_mode = (mode == 'paper')

    # Get trades from Redis stream and filter by mode
    all_trades = read_redis_trades(limit=1000)
    all_trades = [t for t in all_trades if t.get('paper', True) == is_paper_mode]

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

    # Get current mode from Redis
    r = get_redis()
    risk_data = r.hgetall('risk') or {}
    mode = risk_data.get('mode', 'paper')
    is_paper_mode = (mode == 'paper')

    # Get trades from Redis stream and filter by mode
    all_trades = read_redis_trades(limit=1000)
    all_trades = [t for t in all_trades if t.get('paper', True) == is_paper_mode]

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


_VALID_ANALYTICS_PERIODS = ('7d', '30d', '90d', 'all')


def _normalize_analytics_period(period: str) -> str:
    return period if period in _VALID_ANALYTICS_PERIODS else '30d'


def _is_paper_mode() -> bool:
    risk_data = get_redis().hgetall('risk') or {}
    return risk_data.get('mode', 'paper') == 'paper'


def _mode_filtered_trades(limit: int = 1000) -> list[dict]:
    is_paper_mode = _is_paper_mode()
    all_trades = read_redis_trades(limit=limit)
    return [t for t in all_trades if t.get('paper', True) == is_paper_mode]


def _filter_trades_by_period(trades: list[dict], period: str, now: datetime | None = None) -> list[dict]:
    if period == 'all':
        return trades
    base_time = now or datetime.now()
    cutoff = base_time - timedelta(days=int(period.replace('d', '')))
    cutoff_str = cutoff.isoformat()
    return [t for t in trades if t.get('timestamp', '') >= cutoff_str]


def _empty_daily_stats() -> dict:
    return {'trades': 0, 'buys': 0, 'sells': 0, 'profit': 0.0, 'wins': 0, 'losses': 0}


def _aggregate_daily_trade_stats(trades: list[dict]) -> dict:
    from collections import defaultdict

    daily_data = defaultdict(_empty_daily_stats)
    for trade in trades:
        timestamp = trade.get('timestamp', '')
        if not timestamp:
            continue
        date_str = timestamp[:10]
        action = trade.get('action', '').upper()
        profit = trade.get('profit')
        stats = daily_data[date_str]
        stats['trades'] += 1
        if action == 'BUY':
            stats['buys'] += 1
            continue
        if action != 'SELL':
            continue
        stats['sells'] += 1
        if profit is None:
            continue
        pnl = _safe_float(profit)
        stats['profit'] += pnl
        if pnl > 0:
            stats['wins'] += 1
        else:
            stats['losses'] += 1
    return daily_data


def _daily_stats_list(daily_data: dict) -> list[dict]:
    daily_list: list[dict] = []
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
            'win_rate': round(win_rate, 1),
        })
    return daily_list


def _daily_summary(daily_list: list[dict]) -> dict:
    return {
        'total_days': len(daily_list),
        'total_trades': sum(d['trades'] for d in daily_list),
        'total_profit': sum(d['profit'] for d in daily_list),
        'total_wins': sum(d['wins'] for d in daily_list),
        'total_losses': sum(d['losses'] for d in daily_list),
        'profitable_days': sum(1 for d in daily_list if d['profit'] > 0),
        'losing_days': sum(1 for d in daily_list if d['profit'] < 0),
    }


@app.route("/api/analytics/daily")
def get_daily_analytics():
    """
    Get daily breakdown of trading performance.
    Query params: period (7d, 30d, 90d, all)
    """
    period = _normalize_analytics_period(request.args.get('period', '30d'))
    trades = _mode_filtered_trades(limit=1000)
    filtered_trades = _filter_trades_by_period(trades, period)
    daily_data = _aggregate_daily_trade_stats(filtered_trades)
    daily_list = _daily_stats_list(daily_data)
    return jsonify({
        'period': period,
        'days': daily_list,
        'summary': _daily_summary(daily_list),
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

    symbols = _discover_position_symbols(r)

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
                'leverage': 1,
                'entry_time': int(spot_pos.get('entry_time', 0))
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
                'leverage': int(futures_pos.get('leverage', 1)),
                'entry_time': int(futures_pos.get('entry_time', 0))
            })
            result['total_value'] += value
            result['total_unrealized_pnl'] += unrealized_pnl

    return result


def _new_live_positions_result() -> dict:
    return {
        'timestamp': datetime.now().isoformat(),
        'total_value': 0.0,
        'total_unrealized_pnl': 0.0,
        'positions': [],
        'errors': [],
    }


def _calculate_unrealized_pct(side: str, entry_price: float, current_price: float, leverage: int) -> float:
    if entry_price <= 0:
        return 0.0
    if side == 'LONG':
        return ((current_price / entry_price) - 1) * 100 * leverage
    return ((entry_price / current_price) - 1) * 100 * leverage


def _append_live_spot_positions(result: dict, r, spot_account: dict, prices: dict) -> None:
    for balance in spot_account['balances']:
        asset = balance['asset']
        total = _safe_float(balance['free']) + _safe_float(balance['locked'])
        if total <= 0:
            continue
        symbol = f"{asset}USDT"
        current_price = _safe_float(prices.get(symbol, 0))
        value = total * current_price
        if value <= 1:
            continue
        redis_pos = r.hgetall(f"positions:{asset}:spot")
        entry_price = _safe_float((redis_pos or {}).get('entry_price', current_price), current_price)
        strategy = (redis_pos or {}).get('strategy', 'manual')
        unrealized_pnl = (current_price - entry_price) * total if entry_price > 0 else 0.0
        unrealized_pnl_pct = ((current_price - entry_price) / entry_price) * 100 if entry_price > 0 else 0.0
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
            'leverage': 1,
        })
        result['total_value'] += value
        result['total_unrealized_pnl'] += unrealized_pnl


def _append_live_futures_positions(result: dict, r, futures_account: dict) -> None:
    for pos in futures_account['positions']:
        size = _safe_float(pos['positionAmt'])
        if size == 0:
            continue
        entry_price = _safe_float(pos['entryPrice'])
        unrealized_pnl = _safe_float(pos['unrealizedProfit'])
        mark_price = _safe_float(pos.get('markPrice', entry_price), entry_price)
        liquidation_price = _safe_float(pos.get('liquidationPrice', 0))
        leverage = _safe_int(pos.get('leverage', 1), 1)
        side = 'LONG' if size > 0 else 'SHORT'
        abs_size = abs(size)
        value = abs_size * mark_price
        asset = pos['symbol'].replace('USDT', '')
        redis_pos = r.hgetall(f"positions:{asset}:futures")
        strategy = (redis_pos or {}).get('strategy', 'manual')
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
            'unrealized_pnl_pct': _calculate_unrealized_pct(side, entry_price, mark_price, leverage),
            'liquidation_price': liquidation_price if liquidation_price > 0 else None,
            'strategy': strategy,
            'leverage': leverage,
        })
        result['total_value'] += value
        result['total_unrealized_pnl'] += unrealized_pnl


@app.route("/api/positions")
def get_positions():
    """
    Get all Binance positions (Spot + Futures) with unrealized P&L.
    Also includes positions tracked in Redis by the trading bot.
    In paper mode, returns positions from Redis only.
    """
    r = get_redis()
    risk_data = r.hgetall('risk') or {}
    mode = risk_data.get('mode', 'paper')
    prices = get_latest_prices()
    if mode == 'paper':
        return jsonify(_get_paper_positions(r, prices))

    result = _new_live_positions_result()

    try:
        client = _build_binance_client()
        prices = _load_live_price_map(client)
        spot_account = client.get_account(recvWindow=60000)
        _append_live_spot_positions(result, r, spot_account, prices)
        futures_account = client.futures_account(recvWindow=60000)
        _append_live_futures_positions(result, r, futures_account)
    except Exception as exc:
        result['errors'].append(f'Binance: {str(exc)}')

    return jsonify(result)


# =====================
# Spot Trading API Endpoints
# ========================


def _new_summary(mode: str) -> dict:
    return {
        'timestamp': datetime.now().isoformat(),
        'mode': mode,
        'spot': {
            'balance': 0.0,
            'position_value': 0.0,
            'total': 0.0,
            'positions': 0,
        },
        'futures': {
            'balance': 0.0,
            'unrealized_pnl': 0.0,
            'position_value': 0.0,
            'total': 0.0,
            'positions': 0,
        },
        'total_equity': 0.0,
        'positions': [],
    }


def _build_paper_summary_positions(
    r,
    prices: dict,
) -> tuple[list[dict], float, int, float, float, int]:
    positions: list[dict] = []
    spot_value = 0.0
    spot_count = 0
    futures_pnl = 0.0
    futures_position_value = 0.0
    futures_count = 0
    for symbol in _discover_position_symbols(r):
        spot_pos = r.hgetall(f"positions:{symbol}:spot")
        spot_qty = _safe_float((spot_pos or {}).get('quantity', 0))
        if spot_pos and spot_qty > 0:
            entry_price = _safe_float(spot_pos.get('entry_price', 0))
            current_price = _safe_float(prices.get(f'{symbol}USDT', entry_price), entry_price)
            value = spot_qty * current_price
            pnl = (current_price - entry_price) * spot_qty
            spot_value += value
            spot_count += 1
            positions.append({
                'symbol': f'{symbol}USDT',
                'market': 'spot',
                'side': 'LONG',
                'quantity': spot_qty,
                'entry_price': entry_price,
                'current_price': current_price,
                'value': value,
                'unrealized_pnl': pnl,
                'strategy': spot_pos.get('strategy', 'unknown'),
            })

        futures_pos = r.hgetall(f"positions:{symbol}:futures")
        futures_qty = _safe_float((futures_pos or {}).get('quantity', 0))
        if not futures_pos or futures_qty == 0:
            continue
        entry_price = _safe_float(futures_pos.get('entry_price', 0))
        current_price = _safe_float(prices.get(f'{symbol}USDT', entry_price), entry_price)
        side = _normalize_futures_side(futures_pos.get('side', 'buy'))
        abs_qty = abs(futures_qty)
        notional_value = abs_qty * current_price
        pnl = (current_price - entry_price) * abs_qty if side == 'LONG' else (entry_price - current_price) * abs_qty
        futures_pnl += pnl
        futures_position_value += notional_value
        futures_count += 1
        positions.append({
            'symbol': f'{symbol}USDT',
            'market': 'futures',
            'side': side,
            'quantity': abs_qty,
            'entry_price': entry_price,
            'current_price': current_price,
            'value': notional_value,
            'unrealized_pnl': pnl,
            'leverage': _safe_int(futures_pos.get('leverage', 1), 1),
            'strategy': futures_pos.get('strategy', 'unknown'),
        })
    return positions, spot_value, spot_count, futures_pnl, futures_position_value, futures_count


def _populate_paper_summary(summary: dict, r, prices: dict) -> dict:
    account = r.hgetall('account:paper') or {}
    spot_balance = _safe_float(account.get('spot_balance', 10000), 10000)
    futures_balance = _safe_float(account.get('futures_balance', 10000), 10000)
    positions, spot_value, spot_count, futures_pnl, futures_position_value, futures_count = _build_paper_summary_positions(
        r, prices
    )
    summary['spot']['balance'] = spot_balance
    summary['spot']['position_value'] = spot_value
    summary['spot']['positions'] = spot_count
    summary['futures']['balance'] = futures_balance
    summary['futures']['unrealized_pnl'] = futures_pnl
    summary['futures']['position_value'] = futures_position_value
    summary['futures']['positions'] = futures_count
    summary['positions'] = positions
    return summary


def _build_live_summary_spot_positions(r, spot_account: dict, prices: dict) -> tuple[float, float, int, list[dict]]:
    spot_usdt = 0.0
    spot_position_value = 0.0
    spot_count = 0
    positions: list[dict] = []
    for balance in spot_account['balances']:
        asset = balance['asset']
        total = _safe_float(balance['free']) + _safe_float(balance['locked'])
        if total <= 0:
            continue
        if asset == 'USDT':
            spot_usdt = total
            continue
        symbol = f"{asset}USDT"
        price = _safe_float(prices.get(symbol, 0))
        value = total * price
        if value <= 1:
            continue
        redis_pos = r.hgetall(f"positions:{asset}:spot")
        entry_price = _safe_float((redis_pos or {}).get('entry_price', price), price)
        pnl = (price - entry_price) * total if entry_price > 0 else 0.0
        positions.append({
            'symbol': symbol,
            'market': 'spot',
            'side': 'LONG',
            'quantity': total,
            'entry_price': entry_price,
            'current_price': price,
            'value': value,
            'unrealized_pnl': pnl,
            'strategy': (redis_pos or {}).get('strategy', 'manual'),
        })
        spot_position_value += value
        spot_count += 1
    return spot_usdt, spot_position_value, spot_count, positions


def _build_live_summary_futures_positions(r, futures_account: dict) -> tuple[float, float, float, int, list[dict]]:
    futures_usdt = 0.0
    futures_unrealized_pnl = 0.0
    for asset in futures_account['assets']:
        if asset['asset'] == 'USDT':
            futures_usdt = _safe_float(asset['walletBalance'])
            futures_unrealized_pnl = _safe_float(asset['unrealizedProfit'])
            break

    futures_count = 0
    futures_position_value = 0.0
    positions: list[dict] = []
    for pos in futures_account['positions']:
        size = _safe_float(pos['positionAmt'])
        if size == 0:
            continue
        position_side = pos.get('positionSide', 'BOTH')
        side = 'LONG' if position_side == 'BOTH' and size > 0 else 'SHORT' if position_side == 'BOTH' else position_side
        asset = pos['symbol'].replace('USDT', '')
        redis_pos = r.hgetall(f"positions:{asset}:futures")
        current_price = _safe_float(pos['markPrice'])
        abs_size = abs(size)
        positions.append({
            'symbol': pos['symbol'],
            'market': 'futures',
            'side': side,
            'quantity': abs_size,
            'entry_price': _safe_float(pos['entryPrice']),
            'current_price': current_price,
            'value': abs_size * current_price,
            'unrealized_pnl': _safe_float(pos['unrealizedProfit']),
            'leverage': _safe_int(pos['leverage']),
            'strategy': (redis_pos or {}).get('strategy', 'manual'),
        })
        futures_position_value += abs_size * current_price
        futures_count += 1
    return futures_usdt, futures_unrealized_pnl, futures_position_value, futures_count, positions


def _populate_live_summary(summary: dict, r, prices: dict) -> dict:
    client = _build_binance_client()
    spot_account = client.get_account(recvWindow=60000)
    futures_account = client.futures_account(recvWindow=60000)

    spot_usdt, spot_position_value, spot_count, spot_positions = _build_live_summary_spot_positions(r, spot_account, prices)
    futures_usdt, futures_unrealized_pnl, futures_position_value, futures_count, futures_positions = (
        _build_live_summary_futures_positions(r, futures_account)
    )

    summary['spot']['balance'] = spot_usdt
    summary['spot']['position_value'] = spot_position_value
    summary['spot']['positions'] = spot_count
    summary['futures']['balance'] = futures_usdt
    summary['futures']['unrealized_pnl'] = futures_unrealized_pnl
    summary['futures']['position_value'] = futures_position_value
    summary['futures']['positions'] = futures_count
    summary['positions'] = spot_positions + futures_positions
    return summary


def _finalize_summary(summary: dict) -> dict:
    summary['spot']['total'] = summary['spot']['balance'] + summary['spot']['position_value']
    summary['futures']['total'] = summary['futures']['balance'] + summary['futures']['unrealized_pnl']
    summary['total_equity'] = summary['spot']['total'] + summary['futures']['total']
    return summary


@app.route("/api/summary")
@requires_auth
def get_summary():
    """
    Get combined spot + futures summary.
    Returns total equity, balances, and position counts for both markets.
    """
    try:
        r = get_redis()
        risk_data = r.hgetall('risk') or {}
        mode = risk_data.get('mode', 'paper')
        prices = get_latest_prices()
        summary = _new_summary(mode)
        if mode == 'paper':
            summary = _populate_paper_summary(summary, r, prices)
        else:
            if not os.getenv('BINANCE_API_KEY') or not os.getenv('BINANCE_API_SECRET'):
                return jsonify({'error': 'Binance credentials not configured'}), 500
            summary = _populate_live_summary(summary, r, prices)
        return jsonify(_finalize_summary(summary))

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route("/api/spot/positions")
@requires_auth
def get_spot_positions_api():
    """
    Get spot positions from Redis.
    Returns positions with current market value and P&L.
    """
    try:
        r = get_redis()
        prices = get_latest_prices()

        positions = []
        symbols = _discover_position_symbols(r)

        for symbol in symbols:
            spot_pos = r.hgetall(f"positions:{symbol}:spot")
            if spot_pos and float(spot_pos.get('quantity', 0)) > 0:
                qty = float(spot_pos['quantity'])
                entry_price = float(spot_pos['entry_price'])
                current_price = prices.get(f'{symbol}USDT', entry_price)
                value = qty * current_price
                pnl = (current_price - entry_price) * qty
                pnl_pct = ((current_price - entry_price) / entry_price * 100) if entry_price > 0 else 0

                positions.append({
                    'symbol': f'{symbol}USDT',
                    'market': 'spot',
                    'side': 'LONG',
                    'quantity': qty,
                    'entry_price': entry_price,
                    'current_price': current_price,
                    'value': value,
                    'unrealized_pnl': pnl,
                    'unrealized_pnl_pct': pnl_pct,
                    'strategy': spot_pos.get('strategy', 'unknown'),
                    'entry_time': int(spot_pos.get('entry_time', 0)),
                })

        return jsonify({
            'timestamp': datetime.now().isoformat(),
            'positions': positions,
            'count': len(positions),
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route("/api/spot/balance")
@requires_auth
def get_spot_balance_api():
    """
    Get spot USDT balance.
    In paper mode, returns Redis balance. In live mode, returns Binance balance.
    """
    try:
        r = get_redis()
        risk_data = r.hgetall('risk') or {}
        mode = risk_data.get('mode', 'paper')

        if mode == 'paper':
            account = r.hgetall('account:paper') or {}
            balance = float(account.get('spot_balance', 10000))
        else:
            from binance.client import Client
            import time

            api_key = os.getenv('BINANCE_API_KEY')
            api_secret = os.getenv('BINANCE_API_SECRET')

            if not api_key or not api_secret:
                return jsonify({'error': 'Binance credentials not configured'}), 500

            client = Client(api_key, api_secret)
            server_time = client.get_server_time()
            local_time = int(time.time() * 1000)
            client.timestamp_offset = server_time['serverTime'] - local_time

            spot_account = client.get_account(recvWindow=60000)
            balance = 0.0

            for bal in spot_account['balances']:
                if bal['asset'] == 'USDT':
                    balance = float(bal['free']) + float(bal['locked'])
                    break

        return jsonify({
            'timestamp': datetime.now().isoformat(),
            'mode': mode,
            'balance': balance,
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


# =====================
# Strategies API Endpoints
# ========================

# Import strategy registry for dynamic class lookup
try:
    from trading.strategies.components.strategy_factory import STRATEGY_REGISTRY
except ImportError:
    STRATEGY_REGISTRY = {}

# Hide legacy/deprecated strategies from dashboard enable list.
DEPRECATED_STRATEGY_NAMES = {"sideways_v2", "mlp_direction"}


def _strategy_class_name(strategy_name: str, cfg: dict, class_key: str, registry_attr: str, default=None):
    section = cfg.get('exit', {}) if class_key.startswith('persistent') else cfg.get(class_key.split('_')[0], {})
    if section.get('class'):
        return section['class']
    if class_key == 'persistent_class':
        persistent_cfg = cfg.get('exit', {})
        if persistent_cfg.get('persistent_class'):
            return persistent_cfg['persistent_class']
    if strategy_name not in STRATEGY_REGISTRY:
        return default
    registry_item = STRATEGY_REGISTRY[strategy_name]
    attr_value = getattr(registry_item, registry_attr, None)
    return attr_value.__name__ if attr_value else default


def _build_regime_routing_payload(cfg: dict) -> tuple[dict | None, bool]:
    regime_routing = cfg.get('regime_routing')
    if not regime_routing:
        return None, False
    payload = {
        regime: {
            'entry': r_cfg.get('entry'),
            'exit': r_cfg.get('exit'),
            'entry_params': r_cfg.get('entry_params', {}),
            'exit_params': r_cfg.get('exit_params', {}),
        }
        for regime, r_cfg in regime_routing.items()
    }
    return payload, True


def _load_strategy_live_state(r, strategy_name: str, symbols: list[str]) -> dict:
    live_state: dict = {}
    for symbol in symbols:
        state_keys = r.keys(f"state:{strategy_name}:{symbol}:*")
        if not state_keys:
            continue
        symbol_state: dict = {}
        for key in state_keys:
            var_name = key.split(':')[-1]
            value = r.get(key)
            if not value:
                continue
            try:
                symbol_state[var_name] = float(value)
            except (TypeError, ValueError):
                symbol_state[var_name] = value
        if symbol_state:
            live_state[symbol] = symbol_state
    return live_state


def _load_strategy_active_positions(r, strategy_name: str, symbols: list[str]) -> list[dict]:
    active_positions: list[dict] = []
    for symbol in symbols:
        pos_data = r.hgetall(f"positions:{symbol}:futures")
        if not pos_data or pos_data.get('strategy') != strategy_name:
            continue
        active_positions.append({
            'symbol': symbol,
            'qty': _safe_float(pos_data.get('qty', 0)),
            'entry_price': _safe_float(pos_data.get('entry_price', 0)),
            'side': pos_data.get('side', 'long'),
        })
    return active_positions


def _parse_json_field(raw: str, default):
    if not raw:
        return default
    try:
        return json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return default


def _load_strategy_selector_state(r, strategy_name: str) -> dict | None:
    key = f"strategy:selector:latest:{strategy_name}"
    raw = r.hgetall(key)
    if not raw:
        return None
    return {
        "timestamp": raw.get("timestamp", ""),
        "changed": raw.get("changed", "false") == "true",
        "selected_symbols": _parse_json_field(raw.get("selected_symbols"), []),
        "top_scores": _parse_json_field(raw.get("top_scores"), []),
        "rejected": _parse_json_field(raw.get("rejected"), []),
        "rejection_counts": _parse_json_field(raw.get("rejection_counts"), {}),
        "data_quality": _parse_json_field(raw.get("data_quality"), {}),
        "dq_enabled": raw.get("dq_enabled", "false") == "true",
        "dq_blocked_count": int(_safe_float(raw.get("dq_blocked_count", 0))),
        "selected_count": int(_safe_float(raw.get("selected_count", 0))),
        "universe_size": int(_safe_float(raw.get("universe_size", 0))),
    }


def _build_strategy_info(strategy_name: str, cfg: dict, r, symbols: list[str]) -> dict:
    strategy_info = {
        'name': strategy_name,
        'enabled': True,
        'market': cfg.get('market', 'futures'),
        'leverage': 1 if cfg.get('market') == 'spot' else cfg.get('leverage', 3),
        'position_pct': cfg.get('position_pct', 0.1),
        'position_size': cfg.get('position_size', 0.01),
        'dynamic_sizing': cfg.get('dynamic_sizing', False),
        'use_smart_exit': cfg.get('use_smart_exit', False),
        'entry_class': _strategy_class_name(strategy_name, cfg, 'entry_class', 'entry_class', default='Unknown'),
        'exit_class': _strategy_class_name(strategy_name, cfg, 'exit_class', 'exit_class', default='Unknown'),
        'persistent_exit_class': _strategy_class_name(
            strategy_name,
            cfg,
            'persistent_class',
            'persistent_exit_class',
            default=None,
        ),
    }

    regime_payload, is_tuned = _build_regime_routing_payload(cfg)
    strategy_info['is_tuned'] = is_tuned
    if regime_payload:
        strategy_info['regime_routing'] = regime_payload
    if cfg.get('tuned_config'):
        strategy_info['tuned_config'] = cfg.get('tuned_config')

    strategy_info['live_state'] = _load_strategy_live_state(r, strategy_name, symbols)
    strategy_info['active_positions'] = _load_strategy_active_positions(r, strategy_name, symbols)
    selector_cfg = cfg.get("symbol_selector") if isinstance(cfg.get("symbol_selector"), dict) else None
    if selector_cfg:
        strategy_info["symbol_selector"] = selector_cfg
        strategy_info["selector_state"] = _load_strategy_selector_state(r, strategy_name)
    return strategy_info


def _build_available_strategies(enabled_names: set[str], disabled_names: set[str]) -> list[str]:
    available_in_registry = {
        name for name in STRATEGY_REGISTRY.keys()
        if name not in DEPRECATED_STRATEGY_NAMES
    } - enabled_names
    return sorted((available_in_registry | disabled_names) - DEPRECATED_STRATEGY_NAMES)


@app.route("/api/strategies")
@requires_auth
def get_strategies():
    """
    Get all active strategies with configuration and live Redis state.
    Returns strategy config from allocation.json and runtime state from Redis.
    Uses STRATEGY_REGISTRY for dynamic entry/exit class lookup.
    """
    try:
        config = load_allocation_config()
        if not config:
            return jsonify({'error': 'Failed to load allocation config'}), 500

        strategies_config = config.get('strategies', {})
        symbols = _load_dashboard_symbols(config)
        defaults = config.get('defaults', {})
        r = get_redis()

        strategies: list[dict] = []
        enabled_strategy_names = set()
        disabled_strategy_names = set()

        for name, cfg in strategies_config.items():
            if name in DEPRECATED_STRATEGY_NAMES:
                disabled_strategy_names.add(name)
                continue
            if not bool(cfg.get('enabled', True)):
                disabled_strategy_names.add(name)
                continue

            strategies.append(_build_strategy_info(name, cfg, r, symbols))
            enabled_strategy_names.add(name)

        available_strategies = _build_available_strategies(enabled_strategy_names, disabled_strategy_names)

        return jsonify({
            'strategies': strategies,
            'symbols': symbols,
            'defaults': defaults,
            'count': len(strategies),
            'available_strategies': available_strategies,
        })

    except Exception as e:
        print(f"Error in get_strategies: {e}")
        return jsonify({'error': str(e)}), 500


@app.route("/api/strategies/<strategy_name>/enable", methods=["POST"])
@requires_auth
def enable_strategy(strategy_name: str):
    """
    Enable a strategy by adding it to allocation.json.
    Only strategies in STRATEGY_REGISTRY can be enabled.
    """
    try:
        if strategy_name not in STRATEGY_REGISTRY:
            return jsonify({'error': f'Unknown strategy: {strategy_name}'}), 400
        if strategy_name in DEPRECATED_STRATEGY_NAMES:
            return jsonify({'error': f'Strategy {strategy_name} is deprecated and cannot be enabled'}), 400

        # Load current config
        config = load_allocation_config()
        if not config:
            return jsonify({'error': 'Failed to load allocation config'}), 500

        strategies_config = config.get('strategies', {})

        # If already configured, support re-enable via enabled flag
        existing_cfg = strategies_config.get(strategy_name)
        if existing_cfg is not None:
            if bool(existing_cfg.get('enabled', True)):
                return jsonify({'message': f'{strategy_name} is already enabled'}), 200
            existing_cfg['enabled'] = True
            strategies_config[strategy_name] = existing_cfg
            config['strategies'] = strategies_config

            config_path = Path(__file__).parent.parent / "config" / "strategies" / "allocation.json"
            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=2)

            return jsonify({
                'success': True,
                'message': f'Strategy {strategy_name} enabled',
                'config': existing_cfg
            })

        # Get spec from registry
        spec = STRATEGY_REGISTRY[strategy_name]

        # Create default config for the strategy
        new_strategy_config = {
            'market': spec.market,
            'leverage': 3,
            'dynamic_sizing': True,
            'position_pct': 0.1,
            'position_size': 0.01,
            'use_smart_exit': True,
            'entry': {
                'class': spec.entry_class.__name__
            },
            'exit': {
                'class': spec.exit_class.__name__
            }
        }

        # Add persistent exit class if available
        if spec.persistent_exit_class:
            new_strategy_config['exit']['persistent_class'] = spec.persistent_exit_class.__name__

        # Update config
        strategies_config[strategy_name] = new_strategy_config
        config['strategies'] = strategies_config

        # Save config
        config_path = Path(__file__).parent.parent / "config" / "strategies" / "allocation.json"
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2)

        return jsonify({
            'success': True,
            'message': f'Strategy {strategy_name} enabled',
            'config': new_strategy_config
        })

    except Exception as e:
        print(f"Error enabling strategy: {e}")
        return jsonify({'error': str(e)}), 500


@app.route("/api/strategies/<strategy_name>/disable", methods=["POST"])
@requires_auth
def disable_strategy(strategy_name: str):
    """
    Disable a strategy by removing it from allocation.json.
    """
    try:
        # Load current config
        config = load_allocation_config()
        if not config:
            return jsonify({'error': 'Failed to load allocation config'}), 500

        strategies_config = config.get('strategies', {})

        # Check if exists
        if strategy_name not in strategies_config:
            return jsonify({'message': f'{strategy_name} is already disabled'}), 200

        if not bool(strategies_config[strategy_name].get('enabled', True)):
            return jsonify({'message': f'{strategy_name} is already disabled'}), 200

        # Check for active positions before disabling
        r = get_redis()
        symbols = _load_dashboard_symbols(config)

        for symbol in symbols:
            pos_key = f"positions:{symbol}:futures"
            pos_data = r.hgetall(pos_key)
            if pos_data and pos_data.get('strategy') == strategy_name:
                return jsonify({
                    'error': f'Cannot disable {strategy_name}: has active position in {symbol}'
                }), 400

        # Keep strategy config but mark disabled for consistency with allocation schema.
        disabled_config = dict(strategies_config[strategy_name])
        disabled_config['enabled'] = False
        strategies_config[strategy_name] = disabled_config
        config['strategies'] = strategies_config

        # Save config
        config_path = Path(__file__).parent.parent / "config" / "strategies" / "allocation.json"
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2)

        return jsonify({
            'success': True,
            'message': f'Strategy {strategy_name} disabled',
            'disabled_config': disabled_config
        })

    except Exception as e:
        print(f"Error disabling strategy: {e}")
        return jsonify({'error': str(e)}), 500


@app.route("/api/strategies/<strategy_name>/config", methods=["POST"])
@requires_auth
def update_strategy_config(strategy_name: str):
    """
    Update strategy configuration (position_pct, leverage).
    Request body: { position_pct?: number, leverage?: number }
    """
    try:
        data = request.get_json() or {}

        # Load current config
        config = load_allocation_config()
        if not config:
            return jsonify({'error': 'Failed to load allocation config'}), 500

        strategies_config = config.get('strategies', {})

        # Check if strategy exists
        if strategy_name not in strategies_config:
            return jsonify({'error': f'Strategy {strategy_name} not found'}), 404

        strategy_cfg = strategies_config[strategy_name]
        updated_fields = []

        # Update position_pct if provided
        if 'position_pct' in data:
            new_pct = float(data['position_pct'])
            if not 0 < new_pct <= 1.0:
                return jsonify({'error': 'position_pct must be between 0 and 1'}), 400
            strategy_cfg['position_pct'] = new_pct
            updated_fields.append(f'position_pct={new_pct:.2%}')

        # Update leverage if provided
        if 'leverage' in data:
            new_leverage = int(data['leverage'])
            if not 1 <= new_leverage <= 20:
                return jsonify({'error': 'leverage must be between 1 and 20'}), 400
            strategy_cfg['leverage'] = new_leverage
            updated_fields.append(f'leverage={new_leverage}x')

        if not updated_fields:
            return jsonify({'error': 'No valid fields to update'}), 400

        # Save config
        config['strategies'][strategy_name] = strategy_cfg
        config_path = Path(__file__).parent.parent / "config" / "strategies" / "allocation.json"
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2)

        return jsonify({
            'success': True,
            'message': f'Updated {strategy_name}: {", ".join(updated_fields)}',
            'config': strategy_cfg
        })

    except ValueError as e:
        return jsonify({'error': f'Invalid value: {e}'}), 400
    except Exception as e:
        print(f"Error updating strategy config: {e}")
        return jsonify({'error': str(e)}), 500


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
    initial_capital = data.get('initial_capital', 10000)
    try:
        initial_capital = float(initial_capital)
    except (TypeError, ValueError):
        return jsonify({'error': 'initial_capital must be a number'}), 400
    if initial_capital <= 0:
        return jsonify({'error': 'initial_capital must be > 0'}), 400

    default_start_date, default_end_date = default_backtest_date_range()
    config = {
        'strategy': strategy,
        'start_date': data.get('start_date') or default_start_date,
        'end_date': data.get('end_date') or default_end_date,
        'initial_capital': initial_capital,
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
    if job:
        return jsonify(job.to_dict())

    # Fallback to persisted history (supports viewing results after server restart)
    if backtest_db:
        persisted = backtest_db.get_backtest(job_id)
        if persisted:
            status = persisted.get('status')
            progress = 100 if status in ('completed', 'failed', 'cancelled') else 0
            persisted['progress'] = progress
            persisted.setdefault('started_at', None)
            return jsonify(persisted)

    return jsonify({'error': 'Job not found'}), 404


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

    limit_raw = request.args.get('limit', '50')
    try:
        limit = int(limit_raw)
    except ValueError:
        return jsonify({'error': 'Invalid limit'}), 400
    limit = max(1, min(limit, 200))

    jobs = backtest_runner.get_all_jobs(limit=limit)
    return jsonify({'jobs': jobs})


def _discover_position_symbols(r) -> list[str]:
    """Return tracked symbols plus any symbols currently persisted in Redis positions keys."""
    base = _load_dashboard_symbols()
    seen = set(base)
    try:
        raw_keys = r.keys("positions:*:*") or []
    except Exception:
        return base

    if not isinstance(raw_keys, (list, tuple, set)):
        return base

    discovered: set[str] = set()
    for raw_key in raw_keys:
        key = str(raw_key or "")
        parts = key.split(":")
        if len(parts) != 3:
            continue
        if parts[0] != "positions":
            continue
        if parts[2] not in ("spot", "futures"):
            continue
        symbol = _normalize_symbol(parts[1])
        if not symbol or symbol in seen:
            continue
        discovered.add(symbol)

    return base + sorted(discovered)


def _safe_float(value, default=0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _safe_int(value, default=0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return int(default)


def _new_exchange_balance_result() -> dict:
    return {
        'timestamp': datetime.now().isoformat(),
        'binance': None,
        'errors': [],
    }


def _normalize_futures_side(side: str) -> str:
    normalized = str(side or '').upper()
    if normalized == 'BUY':
        return 'LONG'
    if normalized == 'SELL':
        return 'SHORT'
    return normalized or 'LONG'


def _build_spot_paper_positions(r, prices: dict) -> tuple[list[dict], float]:
    positions: list[dict] = []
    position_value = 0.0
    for symbol in _discover_position_symbols(r):
        spot_pos = r.hgetall(f"positions:{symbol}:spot")
        qty = _safe_float((spot_pos or {}).get('quantity', 0))
        if not spot_pos or qty <= 0:
            continue
        entry_price = _safe_float(spot_pos.get('entry_price', 0))
        current_price = _safe_float(prices.get(f'{symbol}USDT', entry_price), entry_price)
        value = qty * current_price
        positions.append({
            'asset': symbol,
            'market': 'spot',
            'quantity': qty,
            'price': current_price,
            'value': value,
        })
        position_value += value
    return positions, position_value


def _build_futures_paper_positions(r, prices: dict) -> tuple[list[dict], float, float]:
    positions: list[dict] = []
    unrealized_pnl = 0.0
    position_value = 0.0
    for symbol in _discover_position_symbols(r):
        futures_pos = r.hgetall(f"positions:{symbol}:futures")
        qty = _safe_float((futures_pos or {}).get('quantity', 0))
        if not futures_pos or qty == 0:
            continue
        entry_price = _safe_float(futures_pos.get('entry_price', 0))
        current_price = _safe_float(prices.get(f'{symbol}USDT', entry_price), entry_price)
        side = _normalize_futures_side(futures_pos.get('side', 'buy'))
        abs_qty = abs(qty)
        pnl = (current_price - entry_price) * abs_qty if side == 'LONG' else (entry_price - current_price) * abs_qty
        notional_value = abs_qty * current_price
        positions.append({
            'symbol': symbol,
            'market': 'futures',
            'size': qty,
            'side': side,
            'entry_price': entry_price,
            'mark_price': current_price,
            'value': notional_value,
            'unrealized_pnl': pnl,
            'leverage': _safe_int(futures_pos.get('leverage', 1), 1),
            'liquidation_price': 0,
            'entry_time': _safe_int(futures_pos.get('entry_time', 0)),
            'strategy': futures_pos.get('strategy', 'unknown'),
        })
        unrealized_pnl += pnl
        position_value += notional_value
    return positions, unrealized_pnl, position_value


def _compose_exchange_balance_payload(
    spot_usdt: float,
    spot_position_value: float,
    spot_positions: list[dict],
    futures_usdt: float,
    futures_unrealized_pnl: float,
    futures_position_value: float,
    futures_positions: list[dict],
    hedge_mode_enabled: bool,
) -> dict:
    total_equity = spot_usdt + spot_position_value + futures_usdt + futures_unrealized_pnl
    return {
        'spot': {
            'usdt_balance': spot_usdt,
            'position_value': spot_position_value,
            'total': spot_usdt + spot_position_value,
            'positions': spot_positions,
        },
        'futures': {
            'usdt_balance': futures_usdt,
            'unrealized_pnl': futures_unrealized_pnl,
            'position_value': futures_position_value,
            'total': futures_usdt + futures_unrealized_pnl,
            'positions': futures_positions,
            'hedge_mode': hedge_mode_enabled,
        },
        'total_equity': total_equity,
    }


def _build_paper_exchange_balances(r, prices: dict) -> dict:
    account = r.hgetall('account:paper') or {}
    spot_balance = _safe_float(account.get('spot_balance', 10000), 10000)
    futures_balance = _safe_float(account.get('futures_balance', 10000), 10000)
    spot_positions, spot_position_value = _build_spot_paper_positions(r, prices)
    futures_positions, futures_unrealized_pnl, futures_position_value = _build_futures_paper_positions(r, prices)
    return _compose_exchange_balance_payload(
        spot_usdt=spot_balance,
        spot_position_value=spot_position_value,
        spot_positions=spot_positions,
        futures_usdt=futures_balance,
        futures_unrealized_pnl=futures_unrealized_pnl,
        futures_position_value=futures_position_value,
        futures_positions=futures_positions,
        hedge_mode_enabled=False,
    )


def _build_binance_client():
    from binance.client import Client
    import time

    api_key = os.getenv('BINANCE_API_KEY')
    api_secret = os.getenv('BINANCE_API_SECRET')
    if not api_key or not api_secret:
        raise ValueError('Binance: API credentials not configured')
    client = Client(api_key, api_secret)
    server_time = client.get_server_time()
    local_time = int(time.time() * 1000)
    client.timestamp_offset = server_time['serverTime'] - local_time
    return client


def _load_live_price_map(client) -> dict:
    return {
        ticker['symbol']: _safe_float(ticker['price'])
        for ticker in client.get_all_tickers()
    }


def _build_spot_live_positions(spot_account: dict, prices: dict) -> tuple[float, list[dict], float]:
    spot_usdt = 0.0
    positions: list[dict] = []
    for balance in spot_account['balances']:
        asset = balance['asset']
        total = _safe_float(balance['free']) + _safe_float(balance['locked'])
        if total <= 0:
            continue
        if asset == 'USDT':
            spot_usdt = total
            continue
        symbol = f"{asset}USDT"
        price = _safe_float(prices.get(symbol, 0))
        value = total * price
        if value <= 1:
            continue
        positions.append({
            'asset': asset,
            'market': 'spot',
            'quantity': total,
            'price': price,
            'value': value,
        })
    position_value = sum(p['value'] for p in positions)
    return spot_usdt, positions, position_value


def _resolve_hedge_mode(client) -> bool:
    try:
        position_mode = client.futures_get_position_mode(recvWindow=60000)
        return bool(position_mode.get('dualSidePosition', False))
    except Exception:
        return False


def _build_futures_live_positions(futures_account: dict, r) -> tuple[float, float, float, list[dict]]:
    futures_usdt = 0.0
    futures_unrealized_pnl = 0.0
    for asset in futures_account['assets']:
        if asset['asset'] == 'USDT':
            futures_usdt = _safe_float(asset['walletBalance'])
            futures_unrealized_pnl = _safe_float(asset['unrealizedProfit'])
            break

    positions: list[dict] = []
    position_value = 0.0
    for pos in futures_account['positions']:
        size = _safe_float(pos['positionAmt'])
        if size == 0:
            continue
        position_side = pos.get('positionSide', 'BOTH')
        side = 'LONG' if position_side == 'BOTH' and size > 0 else 'SHORT' if position_side == 'BOTH' else position_side
        asset = pos['symbol'].replace('USDT', '')
        redis_pos = r.hgetall(f"positions:{asset}:futures")
        entry_time = _safe_int((redis_pos or {}).get('entry_time', 0))
        strategy = (redis_pos or {}).get('strategy', 'unknown')
        mark_price = _safe_float(pos['markPrice'])
        notional_value = abs(size) * mark_price
        positions.append({
            'symbol': asset,
            'market': 'futures',
            'size': size,
            'side': side,
            'entry_price': _safe_float(pos['entryPrice']),
            'mark_price': mark_price,
            'value': notional_value,
            'unrealized_pnl': _safe_float(pos['unrealizedProfit']),
            'leverage': _safe_int(pos['leverage']),
            'liquidation_price': _safe_float(pos.get('liquidationPrice', 0)),
            'entry_time': entry_time,
            'strategy': strategy,
        })
        position_value += notional_value
    return futures_usdt, futures_unrealized_pnl, position_value, positions


@app.route("/api/exchange_balances")
def get_exchange_balances():
    """Fetch balances from Binance (both Spot and Futures).
    In paper mode, returns simulated balances from Redis.
    """
    r = get_redis()
    risk_data = r.hgetall('risk') or {}
    mode = risk_data.get('mode', 'paper')
    result = _new_exchange_balance_result()

    if mode == 'paper':
        try:
            prices = get_latest_prices()
            result['binance'] = _build_paper_exchange_balances(r, prices)
            return jsonify(result)
        except Exception as exc:
            result['errors'].append(f'Paper mode error: {str(exc)}')
            return jsonify(result)

    try:
        client = _build_binance_client()
        spot_account = client.get_account(recvWindow=60000)
        prices = _load_live_price_map(client)
        spot_usdt, spot_positions, spot_position_value = _build_spot_live_positions(spot_account, prices)
        futures_account = client.futures_account(recvWindow=60000)
        futures_usdt, futures_unrealized_pnl, futures_position_value, futures_positions = _build_futures_live_positions(
            futures_account, r
        )
        result['binance'] = _compose_exchange_balance_payload(
            spot_usdt=spot_usdt,
            spot_position_value=spot_position_value,
            spot_positions=spot_positions,
            futures_usdt=futures_usdt,
            futures_unrealized_pnl=futures_unrealized_pnl,
            futures_position_value=futures_position_value,
            futures_positions=futures_positions,
            hedge_mode_enabled=_resolve_hedge_mode(client),
        )
    except Exception as exc:
        result['errors'].append(f'Binance: {str(exc)}')

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
        r = get_redis()
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


# =============================================================================
# Event Stream API Endpoints (Observability Feature)
# =============================================================================

@app.route("/api/events/entry")
@requires_auth
def get_entry_events():
    """
    Get entry evaluation events with optional filters.

    Query parameters:
    - hours: Hours of history (default 24, max 72)
    - limit: Maximum events (default 50, max 200)
    - symbol: Filter by symbol (e.g., "BTC")
    - strategy: Filter by strategy (e.g., "short_v1")
    """
    if not metrics_service:
        return jsonify({'error': 'Metrics service not available'}), 500

    try:
        hours = max(1, min(int(request.args.get('hours', 24)), 72))
        limit = max(1, min(int(request.args.get('limit', 50)), 200))
        symbol = request.args.get('symbol')
        strategy = request.args.get('strategy')

        events = metrics_service.get_entry_events(
            hours=hours,
            limit=limit,
            symbol=symbol,
            strategy=strategy,
        )

        return jsonify({
            'events': events,
            'total_count': len(events),
        })
    except ValueError:
        return jsonify({'error': 'Invalid parameter values'}), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route("/api/events/exit")
@requires_auth
def get_exit_events():
    """
    Get exit evaluation events with optional filters.

    Query parameters:
    - hours: Hours of history (default 24, max 72)
    - limit: Maximum events (default 50, max 200)
    - symbol: Filter by symbol
    - strategy: Filter by strategy
    """
    if not metrics_service:
        return jsonify({'error': 'Metrics service not available'}), 500

    try:
        hours = max(1, min(int(request.args.get('hours', 24)), 72))
        limit = max(1, min(int(request.args.get('limit', 50)), 200))
        symbol = request.args.get('symbol')
        strategy = request.args.get('strategy')

        events = metrics_service.get_exit_events(
            hours=hours,
            limit=limit,
            symbol=symbol,
            strategy=strategy,
        )

        return jsonify({
            'events': events,
            'total_count': len(events),
        })
    except ValueError:
        return jsonify({'error': 'Invalid parameter values'}), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route("/api/events/hwm/<symbol>/<strategy>")
@requires_auth
def get_hwm_timeline(symbol: str, strategy: str):
    """
    Get HWM update timeline for a specific position.

    URL parameters:
    - symbol: Trading symbol (e.g., "BTC")
    - strategy: Strategy name (e.g., "short_v1")

    Query parameters:
    - hours: Hours of history (default 24, max 72)
    """
    if not metrics_service:
        return jsonify({'error': 'Metrics service not available'}), 500

    try:
        hours = max(1, min(int(request.args.get('hours', 24)), 72))

        timeline = metrics_service.get_hwm_timeline(
            symbol=symbol,
            strategy=strategy,
            hours=hours,
        )

        return jsonify({
            'symbol': symbol,
            'strategy': strategy,
            'timeline': timeline,
            'total_count': len(timeline),
        })
    except ValueError:
        return jsonify({'error': 'Invalid parameter values'}), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route("/api/events/safety")
@requires_auth
def get_safety_rejections():
    """
    Get safety filter rejection events with optional filters.

    Query parameters:
    - hours: Hours of history (default 24, max 72)
    - limit: Maximum events (default 50, max 200)
    - rejection_type: Filter by type (e.g., "weak_trend", "wrong_regime")
    """
    if not metrics_service:
        return jsonify({'error': 'Metrics service not available'}), 500

    try:
        hours = max(1, min(int(request.args.get('hours', 24)), 72))
        limit = max(1, min(int(request.args.get('limit', 50)), 200))
        rejection_type = request.args.get('rejection_type')

        rejections = metrics_service.get_safety_rejections(
            hours=hours,
            limit=limit,
            rejection_type=rejection_type,
        )

        return jsonify({
            'rejections': rejections,
            'total_count': len(rejections),
        })
    except ValueError:
        return jsonify({'error': 'Invalid parameter values'}), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route("/api/events/selector")
@requires_auth
def get_selector_events():
    """
    Get symbol-selector events with optional filters.

    Query parameters:
    - hours: Hours of history (default 24, max 72)
    - limit: Maximum events (default 50, max 200)
    - strategy: Filter by strategy
    - changed_only: true/false (default true)
    """
    if not metrics_service:
        return jsonify({'error': 'Metrics service not available'}), 500

    try:
        hours = max(1, min(int(request.args.get('hours', 24)), 72))
        limit = max(1, min(int(request.args.get('limit', 50)), 200))
        strategy = request.args.get('strategy')
        changed_only = request.args.get('changed_only', 'true').lower() == 'true'

        events = metrics_service.get_selector_events(
            hours=hours,
            limit=limit,
            strategy=strategy,
            changed_only=changed_only,
        )

        return jsonify({
            'events': events,
            'total_count': len(events),
        })
    except ValueError:
        return jsonify({'error': 'Invalid parameter values'}), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route("/api/events/summary")
@requires_auth
def get_events_summary():
    """
    Get aggregated event summary for dashboard overview.

    Query parameters:
    - hours: Hours of history (default 24, max 72)
    """
    if not metrics_service:
        return jsonify({'error': 'Metrics service not available'}), 500

    try:
        hours = max(1, min(int(request.args.get('hours', 24)), 72))

        entry_events = metrics_service.get_entry_events(hours=hours, limit=1000)
        exit_events = metrics_service.get_exit_events(hours=hours, limit=1000)
        safety_rejections = metrics_service.get_safety_rejections(hours=hours, limit=1000)
        selector_events = metrics_service.get_selector_events(hours=hours, limit=1000, changed_only=True)

        # Calculate summary stats
        entry_signals = sum(1 for e in entry_events if e.get('signal_generated') == 'true')
        exit_signals = sum(1 for e in exit_events if e.get('signal_generated') == 'true')

        # Group rejections by type
        rejection_by_type = {}
        for r in safety_rejections:
            rtype = r.get('rejection_type', 'unknown')
            rejection_by_type[rtype] = rejection_by_type.get(rtype, 0) + 1

        return jsonify({
            'hours': hours,
            'entry_events_count': len(entry_events),
            'entry_signals_count': entry_signals,
            'exit_events_count': len(exit_events),
            'exit_signals_count': exit_signals,
            'safety_rejections_count': len(safety_rejections),
            'selector_changes_count': len(selector_events),
            'rejections_by_type': rejection_by_type,
            'timestamp': datetime.now().isoformat(),
        })
    except ValueError:
        return jsonify({'error': 'Invalid parameter values'}), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 500


def _parse_trade_log_filters() -> dict:
    days = max(1, min(int(request.args.get('days', 7)), 90))
    return {
        'days': days,
        'event': request.args.get('event', '').upper(),
        'symbol': request.args.get('symbol', '').upper(),
        'strategy': request.args.get('strategy', ''),
        'limit': max(1, min(int(request.args.get('limit', 500)), 2000)),
        'cutoff': (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d'),
    }


def _trade_log_file_path() -> Path:
    return Path(__file__).parent.parent / 'logs' / 'trades.jsonl'


def _trade_log_summary_template() -> dict:
    return {
        'by_event': {},
        'by_symbol': {},
        'total_pnl': 0.0,
        'wins': 0,
        'losses': 0,
    }


def _matches_trade_log_filters(entry: dict, filters: dict) -> bool:
    ts = entry.get('ts', '')[:10]
    if ts < filters['cutoff']:
        return False
    event = entry.get('event', '')
    if filters['event'] and event != filters['event']:
        return False
    symbol = entry.get('symbol', '')
    if filters['symbol'] and symbol != filters['symbol']:
        return False
    if filters['strategy'] and filters['strategy'] not in entry.get('strategy', ''):
        return False
    return True


def _update_trade_log_summary(summary: dict, entry: dict) -> None:
    event = entry.get('event', '')
    symbol = entry.get('symbol', '')
    summary['by_event'][event] = summary['by_event'].get(event, 0) + 1
    if symbol:
        summary['by_symbol'][symbol] = summary['by_symbol'].get(symbol, 0) + 1
    if event != 'EXIT':
        return
    pnl = _safe_float(entry.get('pnl', 0))
    summary['total_pnl'] += pnl
    if pnl > 0:
        summary['wins'] += 1
    elif pnl < 0:
        summary['losses'] += 1


def _load_trade_log_entries(log_path: Path, filters: dict) -> tuple[list[dict], dict]:
    entries: list[dict] = []
    summary = _trade_log_summary_template()
    with open(log_path, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not _matches_trade_log_filters(entry, filters):
                continue
            entries.append(entry)
            _update_trade_log_summary(summary, entry)
    return entries, summary


def _build_trade_log_response(entries: list[dict], summary: dict, filters: dict) -> dict:
    limited_entries = sorted(entries, key=lambda x: x.get('ts', ''), reverse=True)[:filters['limit']]
    wins = summary['wins']
    losses = summary['losses']
    total_closed = wins + losses
    return {
        'entries': limited_entries,
        'summary': {
            'total': len(limited_entries),
            'by_event': summary['by_event'],
            'by_symbol': summary['by_symbol'],
            'total_pnl': round(summary['total_pnl'], 2),
            'wins': wins,
            'losses': losses,
            'win_rate': round(wins / total_closed * 100, 1) if total_closed > 0 else 0,
        },
        'filters': {
            'days': filters['days'],
            'event': filters['event'] or None,
            'symbol': filters['symbol'] or None,
            'strategy': filters['strategy'] or None,
        },
    }


@app.route("/api/analytics/trade-log")
@requires_auth
def get_trade_log():
    """
    Get structured trade log entries from logs/trades.jsonl.

    Query parameters:
    - days: Number of days to look back (default 7, max 90)
    - event: Filter by event type (ENTRY, EXIT, FILL, PNL, DECISION)
    - symbol: Filter by symbol (BTC, ETH, SOL)
    - strategy: Filter by strategy name
    - limit: Max entries to return (default 500, max 2000)
    """
    try:
        filters = _parse_trade_log_filters()
        log_path = _trade_log_file_path()
        if not log_path.exists():
            return jsonify({
                'entries': [],
                'summary': {'total': 0, 'by_event': {}, 'by_symbol': {}},
                'message': 'No trade log file found'
            })

        entries, summary = _load_trade_log_entries(log_path, filters)
        return jsonify(_build_trade_log_response(entries, summary, filters))
    except ValueError:
        return jsonify({'error': 'Invalid parameter values'}), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route("/api/analytics/trade-log/download")
@requires_auth
def download_trade_log():
    """
    Download trade log as JSONL file.

    Query parameters:
    - days: Number of days (default 30)
    """
    from flask import send_file
    import io

    try:
        days = max(1, min(int(request.args.get('days', 30)), 365))
        cutoff = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')

        log_path = Path(__file__).parent.parent / 'logs' / 'trades.jsonl'
        if not log_path.exists():
            return jsonify({'error': 'No trade log file found'}), 404

        # Filter and prepare download
        output = io.StringIO()
        with open(log_path, encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    ts = entry.get('ts', '')[:10]
                    if ts >= cutoff:
                        output.write(line + '\n')
                except Exception:
                    continue

        output.seek(0)
        filename = f"trades_{datetime.now().strftime('%Y%m%d')}.jsonl"

        return send_file(
            io.BytesIO(output.getvalue().encode('utf-8')),
            mimetype='application/x-ndjson',
            as_attachment=True,
            download_name=filename
        )

    except Exception as e:
        return jsonify({'error': str(e)}), 500


if __name__ == "__main__":
    host = os.getenv("DASHBOARD_HOST", "0.0.0.0")
    port = int(os.getenv("DASHBOARD_PORT", DEFAULT_PORT))
    local_url = f"http://localhost:{port}/{DASHBOARD_PATH}"

    print(f"\n{'='*50}")
    print(f"Dashboard available at: {local_url}")
    print("Basic Auth required (credentials from environment)")
    print(f"{'='*50}\n")

    # 텔레그램으로 대시보드 URL 알림
    _notify_dashboard_url()

    app.run(host=host, port=port, debug=False)
