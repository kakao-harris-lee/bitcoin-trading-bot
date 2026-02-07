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


def main():
    """Main entry point."""
    args = parse_args()

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
