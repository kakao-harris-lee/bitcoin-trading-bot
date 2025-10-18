#!/usr/bin/env python3
"""
app.py
FastAPI 웹 대시보드
"""

from fastapi import FastAPI, Request
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
import sqlite3
from pathlib import Path

app = FastAPI(title="Bitcoin Trading Bot Dashboard")

# 정적 파일 및 템플릿
BASE_DIR = Path(__file__).parent
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")

DB_PATH = BASE_DIR.parent / "trading_results.db"

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    """메인 대시보드"""
    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()

    cursor.execute("""
        SELECT s.version, s.name, b.total_return, b.sharpe_ratio, b.max_drawdown, b.win_rate
        FROM strategies s
        LEFT JOIN backtest_results b ON s.strategy_id = b.strategy_id
        ORDER BY s.created_at DESC
    """)

    strategies = cursor.fetchall()
    conn.close()

    return templates.TemplateResponse(
        "dashboard.html",
        {"request": request, "strategies": strategies}
    )

@app.get("/api/strategies")
async def get_strategies():
    """전략 목록 API"""
    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM strategies")
    strategies = cursor.fetchall()
    conn.close()

    return {"strategies": strategies}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
