#!/usr/bin/env python3
"""
Bitcoin Trading Bot - Entry Point
비트코인 트레이딩 봇 진입점

Usage:
    python run.py --trend paper --premium paper  # Both paper (default)
    python run.py --trend live --premium paper   # Trend live, premium paper
    python run.py --trend live --premium live    # Both live
    python run.py --multi-asset                  # Multi-asset mode (BTC + ETH)
    python run.py --help                         # Help
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

# 프로젝트 루트를 path에 추가
PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))


async def main_async(args):
    """AsyncTradingEngine 실행 (Single-asset BTC)."""
    from trading.async_engine import AsyncTradingEngine, AsyncEngineConfig

    config = AsyncEngineConfig(
        trend_mode=str(args.trend),
        premium_mode=str(args.premium),
        paper_upbit_capital=float(args.paper_upbit_capital),
        paper_binance_capital=float(args.paper_binance_capital),
        telegram_enabled=not bool(args.no_telegram),
        telegram_commands_enabled=bool(args.telegram_commands),
    )

    engine = AsyncTradingEngine(config)

    try:
        await engine.start()
    except KeyboardInterrupt:
        print("\nShutting down...")
    finally:
        await engine.stop()


async def main_multi_asset(args):
    """MultiAssetTradingEngine 실행 (BTC + ETH + ...)."""
    from trading.multi_asset_engine import MultiAssetTradingEngine, MultiAssetEngineConfig

    # Load allocation config
    config_path = PROJECT_ROOT / "config" / "strategies" / "allocation.json"
    with open(config_path) as f:
        allocation_config = json.load(f)

    # Map mode to execution_mode
    execution_mode = "live" if args.trend == "live" else "paper"

    config = MultiAssetEngineConfig(
        execution_mode=execution_mode,
        total_capital_krw=float(args.paper_upbit_capital),
        hedge_capital_usdt=float(args.paper_binance_capital),
        telegram_enabled=not bool(args.no_telegram),
    )

    engine = MultiAssetTradingEngine(config, allocation_config)

    try:
        await engine.start()
    except KeyboardInterrupt:
        print("\nShutting down...")
    finally:
        await engine.stop()


async def main(args):
    """Route to appropriate engine."""
    if args.multi_asset:
        await main_multi_asset(args)
    else:
        await main_async(args)


def run():
    """메인 함수"""
    parser = argparse.ArgumentParser(
        description='Bitcoin Trading Bot (AsyncEngine)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python run.py --trend paper --premium paper  # Both paper (default)
  python run.py --trend live --premium paper   # Trend live, premium paper
  python run.py --trend live --premium live    # Both live
  python run.py --multi-asset                  # Multi-asset mode (BTC + ETH)
  python run.py --no-telegram                  # Without telegram notifications
        """
    )

    # Multi-asset mode
    parser.add_argument(
        '--multi-asset',
        action='store_true',
        help='Enable multi-asset mode (BTC + ETH from allocation.json)'
    )

    # 실행 모드 (Dual mode)
    parser.add_argument(
        '--trend',
        choices=['paper', 'live'],
        default='paper',
        help='Trend/directional trading mode (default: paper)'
    )

    parser.add_argument(
        '--premium',
        choices=['paper', 'live'],
        default='paper',
        help='Kimchi premium hedge mode (default: paper)'
    )

    # Legacy --mode argument (maps to --trend)
    parser.add_argument(
        '--mode',
        choices=['paper', 'live'],
        default=None,
        help=argparse.SUPPRESS  # Hidden, for backward compatibility
    )

    # Paper Trading 자본금 설정 (Live 모드에서는 무시됨 - 실제 잔고 조회)
    parser.add_argument(
        '--paper-upbit-capital',
        type=float,
        default=10_000_000,
        help='[Paper only] Upbit simulation capital in KRW (default: 10,000,000)'
    )

    parser.add_argument(
        '--paper-binance-capital',
        type=float,
        default=10_000,
        help='[Paper only] Binance simulation capital in USDT (default: 10,000)'
    )

    # 텔레그램 설정
    parser.add_argument(
        '--no-telegram',
        action='store_true',
        help='Disable telegram notifications'
    )

    parser.add_argument(
        '--telegram-commands',
        action='store_true',
        help='Enable telegram command polling'
    )

    # Legacy compatibility (ignored)
    parser.add_argument('--engine', default='async', help=argparse.SUPPRESS)
    parser.add_argument('--interval', type=int, default=60, help=argparse.SUPPRESS)
    parser.add_argument('--once', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--candidate-json', type=str, default=None, help=argparse.SUPPRESS)
    parser.add_argument('--candidate-index', type=int, default=0, help=argparse.SUPPRESS)
    parser.add_argument('--sideways-policy', type=str, default='sideways_v2', help=argparse.SUPPRESS)
    parser.add_argument('--binance-policy', type=str, default='short_v1', help=argparse.SUPPRESS)
    parser.add_argument('--binance-gate', type=str, default='bear_only', help=argparse.SUPPRESS)

    args = parser.parse_args()

    # Handle legacy --mode argument
    if args.mode is not None:
        args.trend = args.mode
        print(f"Warning: --mode is deprecated. Use --trend instead.")

    if args.multi_asset:
        print(f"Starting MultiAssetTradingEngine (Mode={args.trend.upper()})...")
        print(f"  Assets from allocation.json (BTC, ETH, ...)")
    else:
        print(f"Starting AsyncTradingEngine (Trend={args.trend.upper()}, Premium={args.premium.upper()})...")

    asyncio.run(main(args))


if __name__ == "__main__":
    run()
