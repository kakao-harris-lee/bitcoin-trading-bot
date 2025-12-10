#!/usr/bin/env python3
"""
듀얼 거래소 실시간 트레이딩 메인 스크립트
- 업비트: v35 전략 롱 포지션
- 바이넨스: BEAR 시장 숏 헤지
"""

import os
import sys
import time
import argparse
from datetime import datetime
from dotenv import load_dotenv

# 프로젝트 루트를 경로에 추가
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from live_trading.dual_exchange_engine import DualExchangeEngine
from live_trading.telegram_notifier import TelegramNotifier
from live_trading.trade_logger import TradeLogger
from strategies.v35_optimized.strategy import V35OptimizedStrategy
from strategies.v35_optimized.dynamic_exit_manager import DynamicExitManager
import pyupbit
import json


class DualTradingEngine:
    """듀얼 거래소 실시간 트레이딩 엔진"""

    def __init__(self, mode: str = 'hedge', check_interval: int = 300):
        """
        Args:
            mode: 'hedge' (바이넨스 헤지) 또는 'cash' (현금 전환)
            check_interval: 체크 주기 (초, 기본 5분)
        """
        load_dotenv()

        self.mode = mode
        self.check_interval = check_interval

        # 프로젝트 루트 경로
        self.project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

        # 듀얼 엔진 초기화
        self.dual_engine = DualExchangeEngine(mode=mode)

        # 텔레그램 알림
        self.notifier = TelegramNotifier()

        # 거래 로거
        self.trade_logger = TradeLogger()

        # v35 전략 설정 로드
        config_path = os.path.join(
            self.project_root,
            'strategies/v35_optimized/config_optimized.json'
        )
        with open(config_path, 'r') as f:
            self.config = json.load(f)

        # v35 전략 초기화
        self.strategy = V35OptimizedStrategy(self.config)
        self.exit_manager = DynamicExitManager(self.config)

        # 포지션 상태
        self.position = None  # {'entry_price', 'entry_time', 'volume', 'strategy', 'market_state'}

        # 시작 알림
        total_value = self.dual_engine.get_total_value()
        mode_text = "헤지 모드" if mode == 'hedge' else "현금 전환 모드"

        self.notifier.notify_start(
            strategy=f"v35_optimized + 바이넨스 ({mode_text})",
            capital=total_value['total_krw']
        )

        print(f"\n{'=' * 70}")
        print(f"🤖 듀얼 거래소 실시간 트레이딩 엔진 시작")
        print(f"{'=' * 70}")
        print(f"전략: v35_optimized")
        print(f"모드: {mode_text}")
        print(f"체크 주기: {check_interval}초")
        print(f"초기 자본: {total_value['total_krw']:,.0f}원")
        print(f"  - 업비트: {total_value['upbit_krw']:,.0f}원")
        if total_value.get('binance_krw'):
            print(f"  - 바이넨스: {total_value['binance_krw']:,.0f}원")
        print(f"{'=' * 70}\n")

    def get_current_price(self) -> float:
        """현재 비트코인 가격 조회"""
        return pyupbit.get_current_price("KRW-BTC")

    def get_market_data(self, timeframe: str = 'day', count: int = 100) -> dict:
        """
        시장 데이터 조회

        Args:
            timeframe: 'day', 'minute60', 'minute240' 등
            count: 조회할 캔들 개수

        Returns:
            DataFrame
        """
        return pyupbit.get_ohlcv("KRW-BTC", interval=timeframe, count=count)

    def analyze_market(self):
        """시장 분석 및 시그널 생성"""

        # Day 타임프레임 데이터 (시장 상태 분류용)
        df_day = self.get_market_data('day', 100)

        if df_day is None or len(df_day) < 50:
            print("⚠️  데이터 조회 실패")
            return None, None

        # v35 전략 실행 (마지막 캔들)
        i = len(df_day) - 1
        signal = self.strategy.execute(df_day, i)

        # 시장 상태 분류
        current_row = df_day.iloc[i]
        prev_row = df_day.iloc[i-1] if i > 0 else None
        market_state = self.strategy.classifier.classify_market_state(current_row, prev_row)

        return signal, market_state

    def check_exit_condition(self):
        """청산 조건 체크"""

        if not self.position:
            return None

        current_price = self.get_current_price()

        # DynamicExitManager를 사용하여 청산 조건 체크
        should_exit, reason = self.exit_manager.should_exit(
            entry_price=self.position['entry_price'],
            current_price=current_price,
            entry_time=self.position['entry_time'],
            strategy=self.position.get('strategy', 'UNKNOWN'),
            market_state=self.position.get('market_state', 'UNKNOWN')
        )

        if should_exit:
            return {
                'action': 'sell',
                'reason': reason,
                'price': current_price
            }

        return None

    def run_once(self):
        """한 번 실행"""

        print(f"\n{'=' * 70}")
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 시장 분석 시작")
        print(f"{'=' * 70}")

        try:
            # 1. 청산 조건 체크 (포지션 있을 때)
            if self.position:
                exit_signal = self.check_exit_condition()

                if exit_signal:
                    print(f"🚨 청산 시그널: {exit_signal['reason']}")

                    # 듀얼 엔진 실행 (매도)
                    df_day = self.get_market_data('day', 100)
                    market_state = self.strategy.classify_market(df_day)

                    self.dual_engine.execute_strategy(exit_signal, market_state)

                    # 포지션 초기화
                    self.position = None

                    # 텔레그램 알림
                    self.notifier.notify_sell(
                        price=exit_signal['price'],
                        reason=exit_signal['reason'],
                        profit_loss=0.0  # TODO: 실제 손익 계산
                    )

                    return

            # 2. 시장 분석
            signal, market_state = self.analyze_market()

            if signal is None:
                print("⚠️  시그널 생성 실패")
                return

            print(f"시장 상태: {market_state}")
            print(f"시그널: {signal['action']} ({signal.get('reason', '')})")

            # 3. 시그널 실행
            if signal['action'] != 'hold':
                # 듀얼 엔진 실행
                self.dual_engine.execute_strategy(signal, market_state)

                # 포지션 업데이트
                if signal['action'] == 'buy':
                    current_price = self.get_current_price()
                    self.position = {
                        'entry_price': current_price,
                        'entry_time': datetime.now(),
                        'volume': 0.0,  # TODO: 실제 체결량
                        'strategy': signal.get('strategy', 'UNKNOWN'),
                        'market_state': market_state
                    }

                    # 텔레그램 알림
                    self.notifier.notify_buy(
                        price=current_price,
                        reason=signal.get('reason', ''),
                        strategy=signal.get('strategy', 'UNKNOWN')
                    )

                elif signal['action'] == 'sell':
                    self.position = None

            else:
                print("ℹ️  현재 포지션 유지")

            # 4. 상태 출력
            status = self.dual_engine.get_status()
            print(f"\n[현재 상태]")
            print(f"  업비트 포지션: {'있음' if status['upbit']['has_position'] else '없음'}")
            print(f"  업비트 총 가치: {status['upbit']['total_value_krw']:,.0f}원")

            if status['binance']:
                print(f"  바이넨스 포지션: {'있음' if status['binance']['has_position'] else '없음'}")
                print(f"  바이넨스 총 잔고: {status['binance']['total_balance_usdt']:.2f} USDT")

            print(f"  총 자산: {status['total_value_krw']:,.0f}원")

        except Exception as e:
            print(f"❌ 오류 발생: {e}")
            import traceback
            traceback.print_exc()

            # 텔레그램 에러 알림
            self.notifier.send_message(f"⚠️ 오류 발생\n{str(e)}")

    def run_forever(self):
        """무한 루프 실행"""

        print(f"🔄 {self.check_interval}초마다 시장 체크 시작\n")

        while True:
            try:
                self.run_once()

                # 다음 체크까지 대기
                print(f"\n⏳ {self.check_interval}초 대기...\n")
                time.sleep(self.check_interval)

            except KeyboardInterrupt:
                print("\n\n⚠️  사용자 중단")
                break

            except Exception as e:
                print(f"\n❌ 예상치 못한 오류: {e}")
                import traceback
                traceback.print_exc()

                # 텔레그램 알림
                self.notifier.send_message(f"⚠️ 예상치 못한 오류\n{str(e)}")

                # 1분 대기 후 재시도
                print(f"⏳ 60초 후 재시도...\n")
                time.sleep(60)

        # 종료 알림
        self.notifier.send_message("🛑 트레이딩 봇 종료")
        print("\n봇 종료 완료")


def main():
    """메인 함수"""

    parser = argparse.ArgumentParser(description='듀얼 거래소 실시간 트레이딩 봇')

    parser.add_argument(
        '--mode',
        type=str,
        choices=['hedge', 'cash'],
        default='hedge',
        help='모드 선택: hedge (바이넨스 헤지) 또는 cash (현금 전환)'
    )

    parser.add_argument(
        '--interval',
        type=int,
        default=300,
        help='체크 주기 (초, 기본: 300 = 5분)'
    )

    parser.add_argument(
        '--once',
        action='store_true',
        help='한 번만 실행 (기본: 무한 루프)'
    )

    args = parser.parse_args()

    # 트레이딩 엔진 시작
    engine = DualTradingEngine(
        mode=args.mode,
        check_interval=args.interval
    )

    if args.once:
        # 한 번만 실행
        engine.run_once()
    else:
        # 무한 루프
        engine.run_forever()


if __name__ == "__main__":
    main()
