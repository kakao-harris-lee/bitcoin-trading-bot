#!/bin/bash
#
# Bitcoin Trading Bot - 시작/종료 스크립트
#
# Usage:
#   ./bot.sh start --trend=live   # Start with specific modes
#   ./bot.sh start                                # Start with defaults (both paper)
#   ./bot.sh stop
#   ./bot.sh status
#   ./bot.sh logs
#   ./bot.sh restart --trend=live
#

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

PID_FILE="$SCRIPT_DIR/.bot.pid"
LOG_DIR="$SCRIPT_DIR/logs"
LOG_FILE="$LOG_DIR/bot.log"

find_running_bot_pid() {
    # Find running paper/live engine process by concrete python invocation.
    # Avoid false-positives from shell commands that merely contain the pattern string.
    ps -eo pid=,args= | awk '
        $0 ~ /python/ &&
        $0 ~ /run\.py[[:space:]]+--trend(=|[[:space:]])(paper|live)([[:space:]]|$)/ {
            print $1
        }
    ' | tail -n 1 || true
}

# 로그 디렉토리 생성
mkdir -p "$LOG_DIR"

# Parse mode arguments
parse_modes() {
    TREND_MODE="paper"

    for arg in "$@"; do
        case $arg in
            --trend=*)
                TREND_MODE="${arg#*=}"
                ;;
            paper|live)
                # Legacy: single mode applies to trend only
                TREND_MODE="$arg"
                ;;
        esac
    done

    # Validate modes
    if [[ ! "$TREND_MODE" =~ ^(paper|live)$ ]]; then
        echo "❌ Invalid trend mode: $TREND_MODE (must be paper or live)"
        exit 1
    fi
}

start() {
    parse_modes "$@"

    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        if ps -p "$PID" > /dev/null 2>&1; then
            echo "⚠️  봇이 이미 실행 중입니다 (PID: $PID)"
            echo "    종료하려면: ./bot.sh stop"
            exit 1
        fi
        rm -f "$PID_FILE"
    fi

    echo "🚀 MultiAssetTradingEngine 시작"
    echo "   Trend:   $TREND_MODE"
    echo "   로그: $LOG_FILE"

    # Find venv python
    if [ -f "$SCRIPT_DIR/.venv/bin/python3" ]; then
        PYTHON_BIN="$SCRIPT_DIR/.venv/bin/python3"
    elif [ -f "$SCRIPT_DIR/venv/bin/python3" ]; then
        PYTHON_BIN="$SCRIPT_DIR/venv/bin/python3"
    else
        PYTHON_BIN="python3"
        echo "   ⚠️  venv not found, using system python"
    fi

    # Live 모드 환경변수
    if [ "$TREND_MODE" = "live" ]; then
        export ENABLE_LIVE_TRADING=1
        echo "   ⚠️  TREND LIVE - 실제 추세매매가 실행됩니다!"
    fi

    # Use dedicated runtime structured-trade log by default.
    # This avoids mixing test-generated events with live/paper readiness data.
    export TRADE_LOG_PATH="${TRADE_LOG_PATH:-$LOG_DIR/trades.runtime.jsonl}"
    export PAPER_TRADES_LOG_PATH="${PAPER_TRADES_LOG_PATH:-$TRADE_LOG_PATH}"
    # Redis timeout defaults for larger symbol universes.
    export REDIS_CONNECT_TIMEOUT_SEC="${REDIS_CONNECT_TIMEOUT_SEC:-20}"
    export REDIS_SOCKET_TIMEOUT_SEC="${REDIS_SOCKET_TIMEOUT_SEC:-60}"
    echo "   Trade log: $TRADE_LOG_PATH"

    # Capture current log line so startup checks only inspect fresh lines.
    local start_line=0
    if [ -f "$LOG_FILE" ]; then
        start_line=$(wc -l < "$LOG_FILE" 2>/dev/null || echo 0)
    fi

    # Fully detach from the invoking shell when possible.
    # In some non-interactive environments `nohup cmd &` is not sufficient and
    # the child can still die with the parent shell/session.
    # Python handles log file rotation (logs/bot.log, daily, 30-day retention)
    if command -v setsid >/dev/null 2>&1; then
        setsid "$PYTHON_BIN" -u run.py --trend "$TREND_MODE" < /dev/null > /dev/null 2>&1 &
    else
        nohup "$PYTHON_BIN" -u run.py --trend "$TREND_MODE" < /dev/null > /dev/null 2>&1 &
    fi

    PID=$!
    disown "$PID" 2>/dev/null || true
    echo $PID > "$PID_FILE"

    # Wait for successful startup marker, process exit, or startup-time fatal logs.
    local startup_ok=0
    local startup_failed=0
    local timeout_sec=30
    local elapsed=0

    while [ "$elapsed" -lt "$timeout_sec" ]; do
        if ! ps -p "$PID" > /dev/null 2>&1; then
            startup_failed=1
            break
        fi

        if [ -f "$LOG_FILE" ]; then
            local new_logs
            new_logs="$(tail -n +"$((start_line + 1))" "$LOG_FILE" 2>/dev/null || true)"

            if echo "$new_logs" | grep -q "TradingEngine started successfully"; then
                startup_ok=1
                break
            fi
            if echo "$new_logs" | grep -Eq "Fatal error|Refusing to start in live mode|paper readiness check failed|Failed to connect to Redis"; then
                startup_failed=1
                break
            fi
        fi

        sleep 1
        elapsed=$((elapsed + 1))
    done

    if [ "$startup_ok" -eq 1 ]; then
        local discovered
        discovered=$(find_running_bot_pid)
        if [ -n "$discovered" ] && ps -p "$discovered" > /dev/null 2>&1; then
            PID="$discovered"
            echo "$PID" > "$PID_FILE"
        fi
        echo "✅ 시작됨 (PID: $PID)"
        return 0
    fi

    if [ "$startup_failed" -eq 1 ] || ! ps -p "$PID" > /dev/null 2>&1; then
        echo "❌ 시작 실패. 최근 로그:"
        tail -50 "$LOG_FILE"
        rm -f "$PID_FILE"
        exit 1
    fi

    echo "⚠️  프로세스는 실행 중이지만 초기화 완료 로그를 확인하지 못했습니다 (PID: $PID)"
    echo "   로그 확인: tail -f $LOG_FILE"
}

stop() {
    if [ ! -f "$PID_FILE" ]; then
        echo "⚠️  봇이 실행 중이지 않습니다"
        return 0
    fi

    PID=$(cat "$PID_FILE")

    if ! ps -p "$PID" > /dev/null 2>&1; then
        echo "⚠️  봇이 실행 중이지 않습니다 (stale PID file)"
        rm -f "$PID_FILE"
        return 0
    fi

    echo "🛑 Trading Bot 종료 중 (PID: $PID)..."
    kill "$PID" 2>/dev/null

    # 최대 10초 대기
    for i in {1..10}; do
        if ! ps -p "$PID" > /dev/null 2>&1; then
            echo "✅ 종료됨"
            rm -f "$PID_FILE"
            return 0
        fi
        sleep 1
    done

    # 강제 종료
    echo "⚠️  강제 종료..."
    kill -9 "$PID" 2>/dev/null
    rm -f "$PID_FILE"
    echo "✅ 종료됨"
}

status() {
    local pid=""

    if [ -f "$PID_FILE" ]; then
        pid=$(cat "$PID_FILE")
    fi

    if [ -n "$pid" ] && ps -p "$pid" > /dev/null 2>&1; then
        PID="$pid"
    else
        # Self-heal stale/missing pid file by probing running bot process.
        local discovered
        discovered=$(find_running_bot_pid)
        if [ -n "$discovered" ] && ps -p "$discovered" > /dev/null 2>&1; then
            PID="$discovered"
            echo "$PID" > "$PID_FILE"
        else
            if [ -n "$pid" ]; then
                echo "❌ 봇이 실행 중이지 않습니다 (stale PID file)"
                rm -f "$PID_FILE"
            else
                echo "❌ 봇이 실행 중이지 않습니다"
            fi
            exit 1
        fi
    fi

    if ps -p "$PID" > /dev/null 2>&1; then
        UPTIME=$(ps -o etime= -p "$PID" | tr -d ' ')
        echo "✅ 봇 실행 중"
        echo "   PID: $PID"
        echo "   실행 시간: $UPTIME"
        echo "   로그: $LOG_FILE"

        # Health status
        HEALTH_FILE="$LOG_DIR/async_engine_health.json"
        if [ -f "$HEALTH_FILE" ]; then
            echo ""
            python3 -c "
import json
with open('$HEALTH_FILE') as f:
    d = json.load(f)
print(f\"   Health: {d['status'].upper()}\")
if d.get('mode'):
    print(f\"   Mode: {d['mode']}\")
# Show BTC price
if d['prices'].get('binance', {}).get('price'):
    print(f\"   BTC (Binance): \${d['prices']['binance']['price']:,.2f}\")
" 2>/dev/null
        fi
    fi
}

logs() {
    if [ -f "$LOG_FILE" ]; then
        tail -f "$LOG_FILE"
    else
        echo "⚠️  로그 파일이 없습니다: $LOG_FILE"
        # 최근 로그 파일 찾기
        LATEST=$(ls -t "$LOG_DIR"/bot_*.log 2>/dev/null | head -1)
        if [ -n "$LATEST" ]; then
            echo "   최근 로그: $LATEST"
            tail -f "$LATEST"
        fi
    fi
}

restart() {
    stop
    sleep 2
    start "$@"
}

show_help() {
    echo "Bitcoin Trading Bot (MultiAssetEngine)"
    echo ""
    echo "Usage: $0 {start|stop|status|logs|restart} [options]"
    echo ""
    echo "Commands:"
    echo "  start     Start the bot"
    echo "  stop      Stop the bot"
    echo "  status    Show bot status"
    echo "  logs      Show live logs"
    echo "  restart   Restart the bot"
    echo ""
    echo "Options:"
    echo "  --trend=MODE     Trend trading mode (paper|live, default: paper)"
    echo ""
    echo "Examples:"
    echo "  $0 start                              # paper (default)"
    echo "  $0 start --trend=live                 # Trend live"
    echo "  $0 restart --trend=live               # Restart with trend live"
    echo "  $0 stop                               # Stop bot"
    echo "  $0 status                             # Check status"
    echo "  $0 health                             # Run server health check"
}

health() {
    # Find venv python
    if [ -f "$SCRIPT_DIR/.venv/bin/python3" ]; then
        PYTHON_BIN="$SCRIPT_DIR/.venv/bin/python3"
    elif [ -f "$SCRIPT_DIR/venv/bin/python3" ]; then
        PYTHON_BIN="$SCRIPT_DIR/venv/bin/python3"
    else
        PYTHON_BIN="python3"
    fi

    echo "🏥 Running Server Health Check..."
    "$PYTHON_BIN" scripts/server_health_check.py
}

case "$1" in
    start)
        shift
        start "$@"
        ;;
    stop)
        stop
        ;;
    status)
        status
        ;;
    health)
        health
        ;;
    logs)
        logs
        ;;
    restart)
        shift
        restart "$@"
        ;;
    help|--help|-h)
        show_help
        ;;
    *)
        show_help
        exit 1
        ;;
esac
