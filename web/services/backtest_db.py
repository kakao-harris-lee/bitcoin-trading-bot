"""Backtest history database persistence.

Stores backtest results in SQLite for persistence across server restarts.
"""

import atexit
import json
import sqlite3
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

# Database path
DB_PATH = Path(__file__).parent.parent.parent / "data" / "backtest_history.db"

# Thread-local storage for connections (each thread gets its own connection)
_local = threading.local()
# Track all connections for cleanup
_all_connections: list[sqlite3.Connection] = []
_connections_lock = threading.Lock()


def _get_connection() -> sqlite3.Connection:
    """Get thread-local database connection.

    Each thread gets its own connection for thread safety.
    """
    if not hasattr(_local, 'connection') or _local.connection is None:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        # Each thread gets its own connection - no check_same_thread needed
        conn = sqlite3.connect(str(DB_PATH))
        conn.row_factory = sqlite3.Row
        _local.connection = conn
        # Track for cleanup
        with _connections_lock:
            _all_connections.append(conn)
    return _local.connection


def close_all_connections() -> None:
    """Close all database connections (called at shutdown)."""
    with _connections_lock:
        for conn in _all_connections:
            try:
                conn.close()
            except sqlite3.Error:
                pass
        _all_connections.clear()


# Register cleanup at exit
atexit.register(close_all_connections)


def init_db():
    """Initialize database schema."""
    conn = _get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS backtest_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id TEXT UNIQUE NOT NULL,
            strategy TEXT NOT NULL,
            start_date TEXT NOT NULL,
            end_date TEXT NOT NULL,
            initial_capital REAL NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            completed_at TEXT,
            error TEXT,
            -- Result metrics (stored when completed)
            final_capital REAL,
            total_return_pct REAL,
            win_rate REAL,
            total_trades INTEGER,
            sharpe_ratio REAL,
            max_drawdown_pct REAL,
            profit_factor REAL,
            -- Full result JSON (for loading details)
            result_json TEXT
        )
    """)

    # Create index for faster queries
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_backtest_created
        ON backtest_history(created_at DESC)
    """)

    conn.commit()


def save_backtest(job_id: str, config: dict, status: str,
                  created_at: str, completed_at: Optional[str] = None,
                  error: Optional[str] = None, result: Optional[dict] = None):
    """Save or update a backtest job in the database.

    Args:
        job_id: Unique job identifier
        config: Job configuration dict
        status: Job status (pending, running, completed, failed, cancelled)
        created_at: ISO format timestamp when job was created
        completed_at: ISO format timestamp when job completed (optional)
        error: Error message if failed (optional)
        result: Full result dict if completed (optional)
    """
    conn = _get_connection()
    cursor = conn.cursor()

    # Extract metrics from result if available
    metrics = {}
    if result:
        metrics = {
            'final_capital': result.get('final_capital'),
            'total_return_pct': result.get('total_return_pct'),
            'win_rate': result.get('win_rate'),
            'total_trades': result.get('total_trades'),
            'sharpe_ratio': result.get('sharpe_ratio'),
            'max_drawdown_pct': result.get('max_drawdown_pct'),
            'profit_factor': result.get('profit_factor'),
        }

    def _downsample_list(values: list, max_len: int) -> list:
        if len(values) <= max_len:
            return values
        step = max(1, len(values) // max_len)
        return values[::step]

    def _cap_result_for_storage(raw: dict) -> dict:
        capped = dict(raw)

        equity_curve = capped.get('equity_curve')
        if isinstance(equity_curve, list):
            capped['equity_curve'] = _downsample_list(equity_curve, max_len=5000)

        benchmark_curve = capped.get('benchmark_curve')
        if isinstance(benchmark_curve, list):
            capped['benchmark_curve'] = _downsample_list(benchmark_curve, max_len=5000)

        trades = capped.get('trades')
        if isinstance(trades, list):
            capped['trades'] = trades[:200]

        return capped

    # Prepare result JSON for detail view (cap large arrays)
    result_json = None
    if result:
        result_json = json.dumps(_cap_result_for_storage(result))

    cursor.execute("""
        INSERT INTO backtest_history (
            job_id, strategy, start_date, end_date, initial_capital,
            status, created_at, completed_at, error,
            final_capital, total_return_pct, win_rate, total_trades,
            sharpe_ratio, max_drawdown_pct, profit_factor, result_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(job_id) DO UPDATE SET
            status = excluded.status,
            completed_at = excluded.completed_at,
            error = excluded.error,
            final_capital = excluded.final_capital,
            total_return_pct = excluded.total_return_pct,
            win_rate = excluded.win_rate,
            total_trades = excluded.total_trades,
            sharpe_ratio = excluded.sharpe_ratio,
            max_drawdown_pct = excluded.max_drawdown_pct,
            profit_factor = excluded.profit_factor,
            result_json = excluded.result_json
    """, (
        job_id,
        config.get('strategy', 'unknown'),
        config.get('start_date', ''),
        config.get('end_date', ''),
        config.get('initial_capital', 0),
        status,
        created_at,
        completed_at,
        error,
        metrics.get('final_capital'),
        metrics.get('total_return_pct'),
        metrics.get('win_rate'),
        metrics.get('total_trades'),
        metrics.get('sharpe_ratio'),
        metrics.get('max_drawdown_pct'),
        metrics.get('profit_factor'),
        result_json
    ))

    conn.commit()


def get_history(limit: int = 50) -> List[Dict[str, Any]]:
    """Get backtest history sorted by creation time (newest first).

    Args:
        limit: Maximum number of records to return

    Returns:
        List of backtest history records
    """
    conn = _get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            job_id, strategy, start_date, end_date, initial_capital,
            status, created_at, completed_at, error,
            final_capital, total_return_pct, win_rate, total_trades,
            sharpe_ratio, max_drawdown_pct, profit_factor
        FROM backtest_history
        ORDER BY created_at DESC
        LIMIT ?
    """, (limit,))

    rows = cursor.fetchall()

    history = []
    for row in rows:
        history.append({
            'job_id': row['job_id'],
            'config': {
                'strategy': row['strategy'],
                'start_date': row['start_date'],
                'end_date': row['end_date'],
                'initial_capital': row['initial_capital'],
            },
            'status': row['status'],
            'created_at': row['created_at'],
            'completed_at': row['completed_at'],
            'error': row['error'],
            'metrics': {
                'total_return_pct': row['total_return_pct'],
                'win_rate': row['win_rate'],
                'total_trades': row['total_trades'],
                'sharpe_ratio': row['sharpe_ratio'],
                'max_drawdown_pct': row['max_drawdown_pct'],
            } if row['status'] == 'completed' else None
        })

    return history


def get_backtest(job_id: str) -> Optional[Dict[str, Any]]:
    """Get a specific backtest by job_id.

    Args:
        job_id: The job ID to retrieve

    Returns:
        Backtest record dict or None if not found
    """
    conn = _get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            job_id, strategy, start_date, end_date, initial_capital,
            status, created_at, completed_at, error, result_json
        FROM backtest_history
        WHERE job_id = ?
    """, (job_id,))

    row = cursor.fetchone()
    if not row:
        return None

    result = None
    if row['result_json']:
        result = json.loads(row['result_json'])

    return {
        'job_id': row['job_id'],
        'config': {
            'strategy': row['strategy'],
            'start_date': row['start_date'],
            'end_date': row['end_date'],
            'initial_capital': row['initial_capital'],
        },
        'status': row['status'],
        'created_at': row['created_at'],
        'completed_at': row['completed_at'],
        'error': row['error'],
        'result': result
    }


def delete_backtest(job_id: str) -> bool:
    """Delete a backtest from history.

    Args:
        job_id: The job ID to delete

    Returns:
        True if deleted, False if not found
    """
    conn = _get_connection()
    cursor = conn.cursor()

    cursor.execute("DELETE FROM backtest_history WHERE job_id = ?", (job_id,))
    conn.commit()

    return cursor.rowcount > 0


# Initialize database on module load
init_db()
