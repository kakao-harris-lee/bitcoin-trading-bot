#!/bin/bash
#
# Dashboard management script
# Usage: ./dashboard.sh {start|stop|restart|status}
#

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

PIDFILE="$SCRIPT_DIR/logs/dashboard.pid"
LOGFILE="$SCRIPT_DIR/logs/dashboard.log"
PORT=5080

# Ensure logs directory exists
mkdir -p "$SCRIPT_DIR/logs"

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
        local port_pid=$(lsof -ti :$PORT 2>/dev/null)
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

    # Activate virtual environment if exists
    if [ -f "$SCRIPT_DIR/.venv/bin/activate" ]; then
        source "$SCRIPT_DIR/.venv/bin/activate"
    fi

    # Start dashboard
    PYTHONPATH="$SCRIPT_DIR" nohup python "$SCRIPT_DIR/web/app.py" >> "$LOGFILE" 2>&1 &
    local pid=$!
    echo $pid > "$PIDFILE"

    sleep 2

    if is_running; then
        echo "Dashboard started successfully (PID: $pid)"
        echo "Access at: http://localhost:$PORT/btc-dashboard"
    else
        echo "Failed to start dashboard. Check logs: $LOGFILE"
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
        echo "URL: http://localhost:$PORT/btc-dashboard"
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
