"""
실시간 트레이딩 메인 스크립트
"""

import argparse
from live_trading_engine import LiveTradingEngine


def main():
    """메인 함수"""

    # 명령행 인자 파싱
    parser = argparse.ArgumentParser(description='v35 실시간 트레이딩 봇')

    parser.add_argument(
        '--auto',
        action='store_true',
        help='자동 거래 모드 (기본: 알림만)'
    )

    parser.add_argument(
        '--paper',
        action='store_true',
        help='Paper Trading 모드 (모의 거래, 기본: OFF)'
    )

    parser.add_argument(
        '--capital',
        type=float,
        default=1_000_000,
        help='Paper Trading 초기 자본 (기본: 1,000,000 KRW)'
    )

    parser.add_argument(
        '--once',
        action='store_true',
        help='한 번만 실행 (기본: 무한 루프)'
    )

    args = parser.parse_args()

    # 트레이딩 엔진 시작
    engine = LiveTradingEngine(
        auto_trade=args.auto,
        paper_trading=args.paper,
        initial_capital=args.capital
    )

    if args.once:
        # 한 번만 실행
        engine.run_once()
    else:
        # 무한 루프
        engine.run_forever()


if __name__ == "__main__":
    main()
