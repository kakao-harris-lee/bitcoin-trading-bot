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
LOG_FILE="$LOG_DIR/bot_$(date +%Y%m%d).log"

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

    # nohup으로 백그라운드 실행 (-u: 버퍼링 비활성화)
    nohup "$PYTHON_BIN" -u run.py --trend "$TREND_MODE" >> "$LOG_FILE" 2>&1 &

    PID=$!
    echo $PID > "$PID_FILE"

    sleep 2
    if ps -p "$PID" > /dev/null 2>&1; then
        echo "✅ 시작됨 (PID: $PID)"
    else
        echo "❌ 시작 실패. 로그를 확인하세요:"
        tail -20 "$LOG_FILE"
        rm -f "$PID_FILE"
        exit 1
    fi
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
    if [ ! -f "$PID_FILE" ]; then
        echo "❌ 봇이 실행 중이지 않습니다"
        exit 1
    fi

    PID=$(cat "$PID_FILE")

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
    else
        echo "❌ 봇이 실행 중이지 않습니다 (stale PID file)"
        rm -f "$PID_FILE"
        exit 1
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
