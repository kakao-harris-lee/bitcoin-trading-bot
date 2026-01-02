#!/bin/bash
# Multi-Asset Trading Bot Dashboard (Flask)

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

# Fixed secret path (set env var to override)
export DASHBOARD_SECRET_PATH="${DASHBOARD_SECRET_PATH:-btc-dashboard}"

# Kill existing dashboard
ps aux | grep "[w]eb/app.py" | awk '{print $2}' | xargs -r kill 2>/dev/null
sleep 1

# Start Flask dashboard on port 5080
echo "Starting dashboard..."
mkdir -p logs
cd web
nohup python3 app.py > ../logs/dashboard.log 2>&1 &
sleep 3

echo ""
echo "Dashboard URL: http://localhost:5080/$DASHBOARD_SECRET_PATH"
echo "Logs: tail -f logs/dashboard.log"
