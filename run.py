#!/usr/bin/env python3
"""
Bitcoin Trading Bot - Entry Point
비트코인 트레이딩 봇 진입점

Usage:
    python run.py --mode paper      # Paper Trading (기본)
    python run.py --mode live       # Live Trading (ENABLE_LIVE_TRADING=1 필요)
    python run.py --help            # 도움말
"""

import argparse
import asyncio
import sys
from pathlib import Path

# 프로젝트 루트를 path에 추가
PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))


async def main(args):
    """AsyncTradingEngine 실행."""
    from trading.async_engine import AsyncTradingEngine, AsyncEngineConfig

    config = AsyncEngineConfig(
        execution_mode=str(args.mode),
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


def run():
    """메인 함수"""
    parser = argparse.ArgumentParser(
        description='Bitcoin Trading Bot (AsyncEngine)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python run.py --mode paper        # Paper trading
  python run.py --mode live         # Live trading (requires ENABLE_LIVE_TRADING=1)
  python run.py --no-telegram       # Without telegram notifications
        """
    )

    # 실행 모드
    parser.add_argument(
        '--mode',
        choices=['paper', 'live'],
        default='paper',
        help='실행 모드 (기본: paper)'
    )

    # Paper Trading 자본금 설정 (Live 모드에서는 무시됨 - 실제 잔고 조회)
    parser.add_argument(
        '--paper-upbit-capital',
        type=float,
        default=10_000_000,
        help='[Paper 전용] Upbit 시뮬레이션 자본 (KRW, 기본: 10,000,000)'
    )

    parser.add_argument(
        '--paper-binance-capital',
        type=float,
        default=10_000,
        help='[Paper 전용] Binance 시뮬레이션 자본 (USDT, 기본: 10,000)'
    )

    # 텔레그램 설정
    parser.add_argument(
        '--no-telegram',
        action='store_true',
        help='텔레그램 알림 비활성화'
    )

    parser.add_argument(
        '--telegram-commands',
        action='store_true',
        help='텔레그램 명령어 polling 활성화'
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

    print("Starting AsyncTradingEngine...")
    asyncio.run(main(args))


if __name__ == "__main__":
    run()
