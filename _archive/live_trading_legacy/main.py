"""
실시간 트레이딩 메인 스크립트
"""

import argparse
try:
    # When executed as a module: `python -m live_trading.main`
    from .live_trading_engine import LiveTradingEngine
except ImportError:  # pragma: no cover
    # When executed as a script: `python live_trading/main.py`
    from live_trading_engine import LiveTradingEngine


def _run_dual_paper_v2(args: argparse.Namespace):
    """Run compose-style dual paper engine (router + trading_engine_v2 strategies)."""
    try:
        from .dual_paper_trading import DualPaperTradingEngine
    except ImportError:  # pragma: no cover
        from dual_paper_trading import DualPaperTradingEngine

    engine = DualPaperTradingEngine(
        upbit_capital=float(args.upbit_capital),
        binance_capital=float(args.binance_capital),
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


def main():
    """메인 함수"""

    # 명령행 인자 파싱
    parser = argparse.ArgumentParser(description='Trading bot entrypoint (legacy v35 / operational dual paper v2)')

    parser.add_argument(
        '--engine',
        choices=['legacy_v35', 'dual_paper_v2'],
        default='legacy_v35',
        help='실행 엔진 선택 (기본: legacy_v35)'
    )

    parser.add_argument(
        '--auto',
        action='store_true',
        help='자동 거래 모드 (기본: 알림만)'
    )

    parser.add_argument(
        '--paper',
        action='store_true',
        help='Paper Trading 모드 (모의 거래, 기본: OFF) - legacy_v35 엔진에만 적용'
    )

    parser.add_argument(
        '--capital',
        type=float,
        default=1_000_000,
        help='Paper Trading 초기 자본 (legacy_v35 전용, 기본 1,000,000 KRW)'
    )

    parser.add_argument(
        '--once',
        action='store_true',
        help='한 번만 실행 (기본: 무한 루프)'
    )

    # dual_paper_v2 options
    parser.add_argument('--mode', choices=['paper', 'live'], default='paper', help='dual_paper_v2 실행 모드 (기본: paper)')
    parser.add_argument('--upbit-capital', type=float, default=10_000_000, help='Upbit 초기 자본 (KRW, dual_paper_v2 전용)')
    parser.add_argument('--binance-capital', type=float, default=10_000, help='Binance 초기 자본 (USDT, dual_paper_v2 전용)')
    parser.add_argument('--interval', type=int, default=60, help='실행 간격 (분, dual_paper_v2 전용)')
    parser.add_argument('--no-telegram', action='store_true', help='텔레그램 알림 비활성화 (dual_paper_v2 전용)')
    parser.add_argument('--telegram-commands', action='store_true', help='텔레그램 명령어 polling 활성화 (dual_paper_v2 전용)')
    parser.add_argument('--candidate-json', type=str, default=None, help='tune_operational_router 결과/selected candidate JSON 경로')
    parser.add_argument('--candidate-index', type=int, default=0, help='candidate index (기본: 0)')

    args = parser.parse_args()

    if args.engine == 'dual_paper_v2':
        _run_dual_paper_v2(args)
        return

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
