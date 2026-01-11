#!/usr/bin/env python3
# run.py
"""Entry point for the trading bot."""
import argparse
import asyncio
import logging
import sys

from trading.engine import TradingEngine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
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
