#!/usr/bin/env python3
"""
Bitcoin Trading Bot - Entry Point
비트코인 트레이딩 봇 진입점

Usage:
    python run.py --mode paper                    # Paper Trading (기본)
    python run.py --mode live                     # Live Trading (ENABLE_LIVE_TRADING=1 필요)
    python run.py --mode paper --once             # 한 번만 실행
    python run.py --help                          # 도움말
"""

import argparse
import sys
from pathlib import Path

# 프로젝트 루트를 path에 추가
PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

from trading_engine_v2.trading_engine import DualPaperTradingEngine


def main():
    """메인 함수"""
    parser = argparse.ArgumentParser(
        description='Bitcoin Trading Bot (Trading Engine V2)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python run.py --mode paper                    # Paper trading mode
  python run.py --mode live                     # Live trading (requires ENABLE_LIVE_TRADING=1)
  python run.py --mode paper --once             # Run once then exit
  python run.py --mode paper --interval 30      # 30 minute interval
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

    # 실행 옵션
    parser.add_argument(
        '--interval',
        type=int,
        default=60,
        help='실행 간격 (분, 기본: 60)'
    )

    parser.add_argument(
        '--once',
        action='store_true',
        help='한 번만 실행 후 종료'
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

    # Candidate 설정
    parser.add_argument(
        '--candidate-json',
        type=str,
        default=None,
        help='튜닝된 candidate JSON 경로 (예: analysis/selected_candidate.json)'
    )

    parser.add_argument(
        '--candidate-index',
        type=int,
        default=0,
        help='candidate index (기본: 0)'
    )

    args = parser.parse_args()

    # 엔진 초기화 및 실행
    engine = DualPaperTradingEngine(
        paper_upbit_capital=float(args.paper_upbit_capital),
        paper_binance_capital=float(args.paper_binance_capital),
        telegram_enabled=not bool(args.no_telegram),
        candidate_json=args.candidate_json,
        candidate_index=int(args.candidate_index),
        execution_mode=str(args.mode),
        telegram_commands_enabled=bool(args.telegram_commands),
    )

    if args.once:
        engine.run_iteration()
    else:
        engine.run_forever(interval_minutes=int(args.interval))


if __name__ == "__main__":
    main()
