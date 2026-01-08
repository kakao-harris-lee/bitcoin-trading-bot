#!/usr/bin/env python3
"""
Migration: Create comparison_reports table for daily backtest comparison reports.

Usage:
    python scripts/migrations/001_comparison_reports.py [--db-path PATH]
"""

import sqlite3
import argparse
from pathlib import Path


MIGRATION_SQL = """
-- Create comparison_reports table for storing daily backtest comparison results
CREATE TABLE IF NOT EXISTS comparison_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    report_date DATE NOT NULL,
    strategy_name TEXT NOT NULL,
    actual_trades_count INTEGER DEFAULT 0,
    backtest_trades_count INTEGER DEFAULT 0,
    actual_pnl REAL DEFAULT 0.0,
    backtest_pnl REAL DEFAULT 0.0,
    actual_pnl_pct REAL DEFAULT 0.0,
    backtest_pnl_pct REAL DEFAULT 0.0,
    actual_max_drawdown REAL DEFAULT 0.0,
    backtest_max_drawdown REAL DEFAULT 0.0,
    discrepancy_count INTEGER DEFAULT 0,
    max_severity TEXT DEFAULT 'Low',
    report_json TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(report_date, strategy_name)
);

-- Index for date-based queries (most common access pattern)
CREATE INDEX IF NOT EXISTS idx_comparison_reports_date
ON comparison_reports(report_date);

-- Index for strategy-based queries
CREATE INDEX IF NOT EXISTS idx_comparison_reports_strategy
ON comparison_reports(strategy_name);

-- Composite index for date range + strategy queries
CREATE INDEX IF NOT EXISTS idx_comparison_reports_date_strategy
ON comparison_reports(report_date, strategy_name);
"""


def run_migration(db_path: str) -> bool:
    """
    Run the migration to create comparison_reports table.

    Args:
        db_path: Path to the SQLite database

    Returns:
        True if migration successful, False otherwise
    """
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # Check if table already exists
        cursor.execute("""
            SELECT name FROM sqlite_master
            WHERE type='table' AND name='comparison_reports'
        """)

        if cursor.fetchone():
            print(f"Table 'comparison_reports' already exists in {db_path}")
            conn.close()
            return True

        # Execute migration
        cursor.executescript(MIGRATION_SQL)
        conn.commit()

        # Verify table was created
        cursor.execute("""
            SELECT name FROM sqlite_master
            WHERE type='table' AND name='comparison_reports'
        """)

        if cursor.fetchone():
            print(f"Successfully created 'comparison_reports' table in {db_path}")
            conn.close()
            return True
        else:
            print(f"Failed to create table in {db_path}")
            conn.close()
            return False

    except sqlite3.Error as e:
        print(f"Database error: {e}")
        return False
    except Exception as e:
        print(f"Unexpected error: {e}")
        return False


def main():
    """Main entry point for migration script."""
    parser = argparse.ArgumentParser(
        description='Create comparison_reports table for daily backtest comparison'
    )
    parser.add_argument(
        '--db-path',
        type=str,
        default=None,
        help='Path to trading_results.db (default: trading/trading_results.db)'
    )

    args = parser.parse_args()

    # Determine database path
    if args.db_path:
        db_path = args.db_path
    else:
        # Default to trading_results.db at project root
        project_root = Path(__file__).parent.parent.parent
        db_path = str(project_root / 'trading_results.db')

    # Check if database exists
    if not Path(db_path).exists():
        print(f"Warning: Database does not exist at {db_path}")
        print("Creating new database...")

    # Run migration
    success = run_migration(db_path)

    if success:
        print("Migration completed successfully!")
        return 0
    else:
        print("Migration failed!")
        return 1


if __name__ == '__main__':
    exit(main())
