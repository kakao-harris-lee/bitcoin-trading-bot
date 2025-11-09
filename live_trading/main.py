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
        '--once',
        action='store_true',
        help='한 번만 실행 (기본: 무한 루프)'
    )

    args = parser.parse_args()

    # 트레이딩 엔진 시작
    engine = LiveTradingEngine(auto_trade=args.auto)

    if args.once:
        # 한 번만 실행
        engine.run_once()
    else:
        # 무한 루프
        engine.run_forever()


if __name__ == "__main__":
    main()
