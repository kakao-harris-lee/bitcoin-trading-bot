#!/bin/bash
#
# Dashboard management script
# Usage: ./dashboard.sh {start|stop|restart|status}
#

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

PIDFILE="$SCRIPT_DIR/logs/dashboard.pid"
LOGFILE="$SCRIPT_DIR/logs/dashboard.log"

if [ -f "$SCRIPT_DIR/.env" ]; then
    set -a
    # shellcheck disable=SC1091
    source "$SCRIPT_DIR/.env"
    set +a
fi

PORT="${DASHBOARD_PORT:-5080}"
DASHBOARD_PATH="${DASHBOARD_PATH:-btc-dashboard}"
DASHBOARD_PATH="${DASHBOARD_PATH#/}"
DASHBOARD_PATH="${DASHBOARD_PATH%/}"
[ -z "$DASHBOARD_PATH" ] && DASHBOARD_PATH="btc-dashboard"

# Ensure logs directory exists
mkdir -p "$SCRIPT_DIR/logs"

find_python_bin() {
    if [ -x "$SCRIPT_DIR/.venv/bin/python3" ]; then
        echo "$SCRIPT_DIR/.venv/bin/python3"
    elif [ -x "$SCRIPT_DIR/venv/bin/python3" ]; then
        echo "$SCRIPT_DIR/venv/bin/python3"
    else
        command -v python3
    fi
}

get_pid() {
    if [ -f "$PIDFILE" ]; then
        cat "$PIDFILE"
    else
        echo ""
    fi
}

is_running() {
    local pid=$(get_pid)
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
        return 0
    else
        # Check if process is running on port even without pidfile
        local port_pid
        port_pid=$(lsof -ti :"$PORT" 2>/dev/null)
        if [ -n "$port_pid" ]; then
            echo "$port_pid" > "$PIDFILE"
            return 0
        fi
        return 1
    fi
}

start() {
    if is_running; then
        echo "Dashboard is already running (PID: $(get_pid))"
        exit 1
    fi

    echo "Starting dashboard on port $PORT..."
    local python_bin
    python_bin="$(find_python_bin)"
    if [ -z "$python_bin" ]; then
        echo "Failed to find python3 executable"
        exit 1
    fi

    # Fully detach from the invoking shell when possible.
    if command -v setsid >/dev/null 2>&1; then
        PYTHONPATH="$SCRIPT_DIR" setsid "$python_bin" "$SCRIPT_DIR/web/app.py" < /dev/null >> "$LOGFILE" 2>&1 &
    else
        PYTHONPATH="$SCRIPT_DIR" nohup "$python_bin" "$SCRIPT_DIR/web/app.py" < /dev/null >> "$LOGFILE" 2>&1 &
    fi
    local pid=$!
    disown "$pid" 2>/dev/null || true
    echo $pid > "$PIDFILE"

    local count=0
    while [ $count -lt 10 ]; do
        if is_running; then
            break
        fi
        sleep 1
        count=$((count + 1))
    done

    if is_running; then
        echo "Dashboard started successfully (PID: $pid)"
        echo "Access at: http://localhost:$PORT/$DASHBOARD_PATH"
    else
        echo "Failed to start dashboard. Check logs: $LOGFILE"
        rm -f "$PIDFILE"
        exit 1
    fi
}

stop() {
    if ! is_running; then
        echo "Dashboard is not running"
        rm -f "$PIDFILE"
        return 0
    fi

    local pid=$(get_pid)
    echo "Stopping dashboard (PID: $pid)..."

    kill "$pid" 2>/dev/null

    # Wait for process to stop
    local count=0
    while is_running && [ $count -lt 10 ]; do
        sleep 1
        count=$((count + 1))
    done

    if is_running; then
        echo "Force killing dashboard..."
        kill -9 "$pid" 2>/dev/null
        sleep 1
    fi

    rm -f "$PIDFILE"
    echo "Dashboard stopped"
}

restart() {
    echo "Restarting dashboard..."
    stop
    sleep 1
    start
}

status() {
    if is_running; then
        local pid=$(get_pid)
        echo "Dashboard is running (PID: $pid)"
        echo "Port: $PORT"
        echo "URL: http://localhost:$PORT/$DASHBOARD_PATH"
    else
        echo "Dashboard is not running"
    fi
}

logs() {
    if [ -f "$LOGFILE" ]; then
        tail -f "$LOGFILE"
    else
        echo "No log file found: $LOGFILE"
    fi
}

case "$1" in
    start)
        start
        ;;
    stop)
        stop
        ;;
    restart)
        restart
        ;;
    status)
        status
        ;;
    logs)
        logs
        ;;
    *)
        echo "Usage: $0 {start|stop|restart|status|logs}"
        exit 1
        ;;
esac
