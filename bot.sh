#!/bin/bash
#
# Bitcoin Trading Bot - 시작/종료 스크립트
#
# 사용법:
#   ./bot.sh start [paper|live]   # 시작 (기본: paper)
#   ./bot.sh stop                 # 종료
#   ./bot.sh status               # 상태 확인
#   ./bot.sh logs                 # 로그 보기
#   ./bot.sh restart [paper|live] # 재시작
#

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

PID_FILE="$SCRIPT_DIR/.bot.pid"
LOG_DIR="$SCRIPT_DIR/logs"
LOG_FILE="$LOG_DIR/bot_$(date +%Y%m%d).log"

# 로그 디렉토리 생성
mkdir -p "$LOG_DIR"

start() {
    MODE="${1:-paper}"

    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        if ps -p "$PID" > /dev/null 2>&1; then
            echo "⚠️  봇이 이미 실행 중입니다 (PID: $PID)"
            echo "    종료하려면: ./bot.sh stop"
            exit 1
        fi
    fi

    echo "🚀 Trading Bot 시작 (mode: $MODE)"
    echo "   로그: $LOG_FILE"

    # 환경 설정
    source "$SCRIPT_DIR/.venv/bin/activate" 2>/dev/null || source "$SCRIPT_DIR/venv/bin/activate" 2>/dev/null

    # Live 모드 환경변수
    if [ "$MODE" = "live" ]; then
        export ENABLE_LIVE_TRADING=1
        echo "   ⚠️  LIVE 모드 - 실제 거래가 실행됩니다!"
    fi

    # nohup으로 백그라운드 실행
    nohup python run.py --mode "$MODE" --interval 5 >> "$LOG_FILE" 2>&1 &

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
        exit 0
    fi

    PID=$(cat "$PID_FILE")

    if ! ps -p "$PID" > /dev/null 2>&1; then
        echo "⚠️  봇이 실행 중이지 않습니다 (stale PID file)"
        rm -f "$PID_FILE"
        exit 0
    fi

    echo "🛑 Trading Bot 종료 중 (PID: $PID)..."
    kill "$PID" 2>/dev/null

    # 최대 10초 대기
    for i in {1..10}; do
        if ! ps -p "$PID" > /dev/null 2>&1; then
            echo "✅ 종료됨"
            rm -f "$PID_FILE"
            exit 0
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
    MODE="${1:-paper}"
    stop
    sleep 2
    start "$MODE"
}

case "$1" in
    start)
        start "$2"
        ;;
    stop)
        stop
        ;;
    status)
        status
        ;;
    logs)
        logs
        ;;
    restart)
        restart "$2"
        ;;
    *)
        echo "Bitcoin Trading Bot 관리 스크립트"
        echo ""
        echo "사용법: $0 {start|stop|status|logs|restart} [mode]"
        echo ""
        echo "명령어:"
        echo "  start [paper|live]   봇 시작 (기본: paper)"
        echo "  stop                 봇 종료"
        echo "  status               상태 확인"
        echo "  logs                 실시간 로그 보기"
        echo "  restart [paper|live] 재시작"
        echo ""
        echo "예시:"
        echo "  $0 start             # Paper 모드 시작"
        echo "  $0 start live        # Live 모드 시작"
        echo "  $0 stop              # 종료"
        echo "  $0 logs              # 로그 확인"
        exit 1
        ;;
esac
