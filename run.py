#!/usr/bin/env python3
# run.py
"""Entry point for the trading bot."""
import argparse
import asyncio
import logging
import os
import sys
from logging.handlers import TimedRotatingFileHandler

from trading.engine import TradingEngine
from trading.core.paper_readiness import (
    evaluate_paper_readiness,
    format_paper_readiness_report,
)

LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
os.makedirs(LOG_DIR, exist_ok=True)

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"

# Root logger setup
root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)

# Console handler (for bot.sh logs / direct run)
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setFormatter(logging.Formatter(LOG_FORMAT))
root_logger.addHandler(console_handler)

# File handler — rotates daily at midnight, keeps 30 days
file_handler = TimedRotatingFileHandler(
    filename=os.path.join(LOG_DIR, "bot.log"),
    when="midnight",
    interval=1,
    backupCount=30,
    encoding="utf-8",
)
file_handler.suffix = "%Y-%m-%d"
file_handler.setFormatter(logging.Formatter(LOG_FORMAT))
root_logger.addHandler(file_handler)

logger = logging.getLogger(__name__)


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="Bitcoin Trading Bot")
    parser.add_argument(
        "--trend",
        choices=["paper", "live"],
        default="paper",
        help="Trading mode: paper (simulated) or live",
    )
    parser.add_argument(
        "--config",
        default="config/strategies/allocation.json",
        help="Path to configuration file",
    )
    return parser.parse_args()


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def main():
    """Main entry point."""
    args = parse_args()

    if args.trend == "live" and os.getenv("ENABLE_LIVE_TRADING") != "1":
        logger.error(
            "Refusing to start in live mode: set ENABLE_LIVE_TRADING=1 to arm live trading."
        )
        sys.exit(1)

    if args.trend == "live":
        if _env_bool("SKIP_PAPER_READINESS_CHECK", False):
            logger.warning("Skipping paper readiness check (SKIP_PAPER_READINESS_CHECK=1).")
        else:
            report = evaluate_paper_readiness(
                config_path=args.config,
                trades_log_path=os.getenv(
                    "PAPER_TRADES_LOG_PATH",
                    os.getenv("TRADE_LOG_PATH", "logs/trades.jsonl"),
                ),
                lookback_days=_env_int("PAPER_READINESS_LOOKBACK_DAYS", 14),
                min_exits_per_strategy=_env_int("PAPER_READINESS_MIN_EXITS_PER_STRATEGY", 10),
                min_total_exits=_env_int("PAPER_READINESS_MIN_TOTAL_EXITS", 40),
                min_win_rate_pct=_env_float("PAPER_READINESS_MIN_WIN_RATE_PCT", 45.0),
                min_profit_factor=_env_float("PAPER_READINESS_MIN_PROFIT_FACTOR", 1.0),
                require_positive_pnl=_env_bool("PAPER_READINESS_REQUIRE_POSITIVE_PNL", True),
            )
            if not report.ready:
                logger.error("Refusing to start in live mode: paper readiness check failed.")
                logger.error("\n" + format_paper_readiness_report(report))
                logger.error("Override only if intentional: set SKIP_PAPER_READINESS_CHECK=1")
                sys.exit(1)
            logger.info("Paper readiness check passed.")

    logger.info(f"Starting trading bot in {args.trend} mode")

    engine = TradingEngine(config_path=args.config)

    try:
        asyncio.run(engine.start(mode=args.trend))
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
