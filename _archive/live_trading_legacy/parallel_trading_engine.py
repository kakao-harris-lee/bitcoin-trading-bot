#!/usr/bin/env python3
"""
병렬 전략 실행 엔진

두 전략을 **독립적으로** 동시 실행:
- 업비트 (KRW): v35_optimized Long 전략
- 바이낸스 (USDT): SHORT_V1 Short 전략

각 거래소의 증거금은 해당 전략에서만 사용되며,
전략 간에 자본 할당/분배가 발생하지 않음.
"""

import os
import sys
import time
import json
import threading
from datetime import datetime
from typing import Dict, Optional
from dotenv import load_dotenv

# 프로젝트 루트 경로 설정 (상대 경로 지원)
_current_dir = os.path.dirname(os.path.abspath(__file__))
_project_root = os.path.dirname(_current_dir)
sys.path.insert(0, _project_root)
sys.path.insert(0, _current_dir)

import pyupbit

# 로컬 모듈
from upbit_trader import UpbitTrader
from binance_futures_trader import BinanceFuturesTrader
from telegram_notifier import TelegramNotifier


class LongStrategyRunner:
    """업비트 Long 전략 실행기 (v35_optimized)"""

    def __init__(self, config: Dict, notifier: Optional[TelegramNotifier] = None):
        self.config = config
        self.notifier = notifier
        self.upbit = UpbitTrader()

        # 전략 로드
        self._load_strategy()

        # 상태
        self.position = None  # {'entry_price', 'entry_time', 'size', 'market_state'}
        self.last_signal = None

    def _load_strategy(self):
        """v35_optimized 전략 로드"""
        import importlib.util

        strategies_dir = os.path.join(_project_root, 'strategies')
        v35_dir = os.path.join(strategies_dir, 'v35_optimized')
        v34_dir = os.path.join(strategies_dir, '_deprecated', 'v34_supreme')

        # v35_optimized 모듈 직접 로드 (이름 충돌 방지)
        # market_classifier_v34
        spec = importlib.util.spec_from_file_location(
            "market_classifier_v34",
            os.path.join(v34_dir, 'market_classifier_v34.py')
        )
        mc_module = importlib.util.module_from_spec(spec)
        sys.modules['market_classifier_v34'] = mc_module
        spec.loader.exec_module(mc_module)

        # dynamic_exit_manager
        spec = importlib.util.spec_from_file_location(
            "dynamic_exit_manager",
            os.path.join(v35_dir, 'dynamic_exit_manager.py')
        )
        dem_module = importlib.util.module_from_spec(spec)
        sys.modules['dynamic_exit_manager'] = dem_module
        spec.loader.exec_module(dem_module)

        # sideways_enhanced
        spec = importlib.util.spec_from_file_location(
            "sideways_enhanced",
            os.path.join(v35_dir, 'sideways_enhanced.py')
        )
        se_module = importlib.util.module_from_spec(spec)
        sys.modules['sideways_enhanced'] = se_module
        spec.loader.exec_module(se_module)

        # v35 strategy
        spec = importlib.util.spec_from_file_location(
            "v35_strategy",
            os.path.join(v35_dir, 'strategy.py')
        )
        v35_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(v35_module)

        V35OptimizedStrategy = v35_module.V35OptimizedStrategy
        DynamicExitManager = dem_module.DynamicExitManager

        # 설정 파일 로드
        config_path = os.path.join(v35_dir, 'config_optimized.json')
        with open(config_path) as f:
            strategy_config = json.load(f)

        self.strategy = V35OptimizedStrategy(strategy_config)
        self.exit_manager = DynamicExitManager(strategy_config)

        print("[Long] v35_optimized 전략 로드 완료")

    def get_market_data(self, count: int = 100):
        """업비트 일봉 데이터 조회"""
        return pyupbit.get_ohlcv("KRW-BTC", interval="day", count=count)

    def run_once(self) -> Dict:
        """한 번 실행"""
        result = {
            'action': 'hold',
            'reason': '',
            'market_state': 'UNKNOWN'
        }

        try:
            # 데이터 수집
            df = self.get_market_data(100)
            if df is None or len(df) < 50:
                result['reason'] = 'INSUFFICIENT_DATA'
                return result

            # 전략 실행
            i = len(df) - 1
            signal = self.strategy.execute(df, i)

            if signal is None:
                result['reason'] = 'NO_SIGNAL'
                return result

            result['action'] = signal.get('action', 'hold')
            result['reason'] = signal.get('reason', '')

            # 시장 상태 분류
            current_row = df.iloc[i]
            prev_row = df.iloc[i - 1] if i > 0 else None
            market_state = self.strategy.classifier.classify_market_state(current_row, prev_row)
            result['market_state'] = market_state

            # 청산 조건 체크 (포지션 있을 때)
            if self.position:
                current_price = current_row['close']
                exit_signal = self.exit_manager.check_exit(
                    current_price,
                    self.position['entry_price'],
                    market_state
                )
                if exit_signal and exit_signal.get('action') == 'sell':
                    result['action'] = 'sell'
                    result['reason'] = exit_signal.get('reason', 'EXIT_SIGNAL')

            # 거래 실행
            if result['action'] == 'buy' and not self.position:
                self._execute_buy(df.iloc[-1]['close'], signal, market_state)

            elif result['action'] == 'sell' and self.position:
                self._execute_sell(df.iloc[-1]['close'], result['reason'])

            self.last_signal = result

        except Exception as e:
            result['reason'] = f'ERROR: {str(e)}'
            print(f"[Long] 오류: {e}")

        return result

    def _execute_buy(self, price: float, signal: Dict, market_state: str):
        """매수 실행"""
        try:
            krw_balance, _ = self.upbit.get_balance()
            fraction = signal.get('fraction', 0.5)
            buy_amount = krw_balance * fraction

            if buy_amount < 5000:
                print(f"[Long] 매수 금액 부족: {buy_amount:,.0f} KRW")
                return

            result = self.upbit.buy_market_order(buy_amount)

            if result and result.get('success'):
                self.position = {
                    'entry_price': price,
                    'entry_time': datetime.now(),
                    'size': buy_amount,
                    'market_state': market_state
                }
                self.exit_manager.set_entry(price, market_state)

                print(f"[Long] 매수 완료: {price:,.0f} KRW")

                if self.notifier:
                    self.notifier.send_message(
                        f"[Long] 매수\n"
                        f"가격: {price:,.0f} KRW\n"
                        f"금액: {buy_amount:,.0f} KRW\n"
                        f"시장: {market_state}"
                    )

        except Exception as e:
            print(f"[Long] 매수 오류: {e}")

    def _execute_sell(self, price: float, reason: str):
        """매도 실행"""
        try:
            result = self.upbit.sell_market_order()

            if result and result.get('success'):
                entry_price = self.position['entry_price']
                pnl_pct = (price - entry_price) / entry_price * 100

                print(f"[Long] 매도 완료: {price:,.0f} KRW ({pnl_pct:+.2f}%)")

                if self.notifier:
                    self.notifier.send_message(
                        f"[Long] 매도\n"
                        f"가격: {price:,.0f} KRW\n"
                        f"손익: {pnl_pct:+.2f}%\n"
                        f"이유: {reason}"
                    )

                self.position = None
                self.exit_manager.reset()

        except Exception as e:
            print(f"[Long] 매도 오류: {e}")

    def get_status(self) -> Dict:
        """상태 조회"""
        krw_balance, btc_balance = self.upbit.get_balance()
        current_price = pyupbit.get_current_price("KRW-BTC")
        btc_value = btc_balance * current_price if btc_balance else 0

        return {
            'strategy': 'v35_optimized',
            'exchange': 'upbit',
            'has_position': self.position is not None,
            'position': self.position,
            'krw_balance': krw_balance,
            'btc_balance': btc_balance,
            'btc_value_krw': btc_value,
            'total_value_krw': krw_balance + btc_value,
            'last_signal': self.last_signal
        }


class ShortStrategyRunner:
    """바이낸스 Short 전략 실행기 (SHORT_V1)"""

    def __init__(self, config: Dict, notifier: Optional[TelegramNotifier] = None):
        self.config = config
        self.notifier = notifier

        try:
            self.binance = BinanceFuturesTrader()
            self.enabled = True
            print("[Short] 바이낸스 연결 완료")
        except Exception as e:
            print(f"[Short] 바이낸스 연결 실패: {e}")
            self.binance = None
            self.enabled = False

        if self.enabled:
            self._load_strategy()

        # 상태
        self.position = None
        self.last_signal = None

    def _load_strategy(self):
        """SHORT_V1 전략 로드"""
        import importlib.util

        strategies_dir = os.path.join(_project_root, 'strategies')
        short_dir = os.path.join(strategies_dir, 'SHORT_V1')

        sys.path.insert(0, short_dir)

        # indicators 로드
        spec = importlib.util.spec_from_file_location(
            "short_indicators",
            os.path.join(short_dir, 'indicators.py')
        )
        ind_module = importlib.util.module_from_spec(spec)
        sys.modules['indicators'] = ind_module
        spec.loader.exec_module(ind_module)

        # strategy 로드
        spec = importlib.util.spec_from_file_location(
            "short_strategy",
            os.path.join(short_dir, 'strategy.py')
        )
        strat_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(strat_module)

        # 설정 로드
        config_path = os.path.join(short_dir, 'config_optimized.json')
        with open(config_path) as f:
            strategy_config = json.load(f)

        self.strategy = strat_module.ShortV1Strategy(strategy_config)
        print("[Short] SHORT_V1 전략 로드 완료")

    def get_market_data(self, count: int = 300):
        """바이낸스 4시간봉 데이터 조회"""
        if not self.binance:
            return None

        try:
            # 바이낸스에서 직접 데이터 수집
            import requests
            import pandas as pd

            url = "https://fapi.binance.com/fapi/v1/klines"
            params = {
                'symbol': 'BTCUSDT',
                'interval': '4h',
                'limit': count
            }
            response = requests.get(url, params=params)
            data = response.json()

            df = pd.DataFrame(data, columns=[
                'timestamp', 'open', 'high', 'low', 'close', 'volume',
                'close_time', 'quote_volume', 'trades', 'taker_buy_base',
                'taker_buy_quote', 'ignore'
            ])

            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            df.set_index('timestamp', inplace=True)

            for col in ['open', 'high', 'low', 'close', 'volume']:
                df[col] = df[col].astype(float)

            return df

        except Exception as e:
            print(f"[Short] 데이터 수집 오류: {e}")
            return None

    def run_once(self) -> Dict:
        """한 번 실행"""
        result = {
            'action': 'hold',
            'reason': '',
        }

        if not self.enabled:
            result['reason'] = 'BINANCE_DISABLED'
            return result

        try:
            # 데이터 수집
            df = self.get_market_data(300)
            if df is None or len(df) < 200:
                result['reason'] = 'INSUFFICIENT_DATA'
                return result

            # 지표 추가
            df = self.strategy.prepare_data(df)

            # 자본 조회
            account = self.binance.get_account_info()
            capital_usd = account.get('available_balance', 0)

            # 전략 실행
            i = len(df) - 1
            signal = self.strategy.execute(df, i, capital_usd)

            if signal is None:
                result['reason'] = 'NO_SIGNAL'
                return result

            result['action'] = signal.get('action', 'hold')
            result['reason'] = signal.get('reason', '')

            # 거래 실행
            if result['action'] == 'open_short' and not self.position:
                self._execute_open_short(signal)

            elif result['action'] == 'close_short' and self.position:
                self._execute_close_short(signal)

            self.last_signal = result

        except Exception as e:
            result['reason'] = f'ERROR: {str(e)}'
            print(f"[Short] 오류: {e}")

        return result

    def _execute_open_short(self, signal: Dict):
        """숏 포지션 오픈"""
        try:
            position_size = signal.get('position_size', 100)
            leverage = signal.get('leverage', 2)

            result = self.binance.open_short(
                usdt_amount=position_size,
                leverage=leverage
            )

            if result and result.get('success'):
                self.position = {
                    'entry_price': signal['entry_price'],
                    'entry_time': datetime.now(),
                    'size': position_size,
                    'leverage': leverage,
                    'stop_loss': signal.get('stop_loss'),
                    'take_profit': signal.get('take_profit')
                }

                # 전략 내부 상태 업데이트
                self.strategy.open_position(
                    entry_price=signal['entry_price'],
                    entry_time=datetime.now(),
                    size=position_size,
                    leverage=leverage,
                    stop_loss=signal.get('stop_loss'),
                    take_profit=signal.get('take_profit'),
                    reason=signal.get('reason', 'SHORT_ENTRY')
                )

                print(f"[Short] 숏 오픈: ${signal['entry_price']:,.2f}")

                if self.notifier:
                    self.notifier.send_message(
                        f"[Short] 숏 오픈\n"
                        f"가격: ${signal['entry_price']:,.2f}\n"
                        f"크기: ${position_size:,.0f}\n"
                        f"레버리지: {leverage}x"
                    )

        except Exception as e:
            print(f"[Short] 숏 오픈 오류: {e}")

    def _execute_close_short(self, signal: Dict):
        """숏 포지션 청산"""
        try:
            result = self.binance.close_position()

            if result:
                exit_price = signal.get('exit_price', 0)
                entry_price = self.position['entry_price']
                leverage = self.position['leverage']
                pnl_pct = (entry_price - exit_price) / entry_price * 100 * leverage

                # 전략 내부 상태 업데이트
                self.strategy.close_position(
                    exit_price=exit_price,
                    exit_time=datetime.now(),
                    exit_reason=signal.get('reason', 'SHORT_EXIT'),
                    funding_paid=0
                )

                print(f"[Short] 숏 청산: ${exit_price:,.2f} ({pnl_pct:+.2f}%)")

                if self.notifier:
                    self.notifier.send_message(
                        f"[Short] 숏 청산\n"
                        f"가격: ${exit_price:,.2f}\n"
                        f"손익: {pnl_pct:+.2f}%\n"
                        f"이유: {signal.get('reason', '')}"
                    )

                self.position = None

        except Exception as e:
            print(f"[Short] 숏 청산 오류: {e}")

    def get_status(self) -> Dict:
        """상태 조회"""
        if not self.enabled:
            return {
                'strategy': 'SHORT_V1',
                'exchange': 'binance',
                'enabled': False
            }

        account = self.binance.get_account_info()
        position = self.binance.get_position()

        return {
            'strategy': 'SHORT_V1',
            'exchange': 'binance',
            'enabled': True,
            'has_position': self.position is not None,
            'position': self.position,
            'balance_usdt': account.get('available_balance', 0),
            'total_balance_usdt': account.get('total_balance', 0),
            'binance_position': position,
            'last_signal': self.last_signal
        }


class ParallelTradingEngine:
    """
    병렬 전략 실행 엔진

    업비트와 바이낸스에서 각각 독립적으로 전략 실행
    """

    def __init__(self, config: Dict = None):
        load_dotenv()

        self.config = config or {}

        # 텔레그램 알림
        try:
            self.notifier = TelegramNotifier()
        except Exception as e:
            print(f"텔레그램 알림 비활성화: {e}")
            self.notifier = None

        # 전략 실행기
        self.long_runner = LongStrategyRunner(self.config, self.notifier)
        self.short_runner = ShortStrategyRunner(self.config, self.notifier)

        # 실행 간격 (초)
        self.long_interval = self.config.get('long_interval', 300)  # 5분
        self.short_interval = self.config.get('short_interval', 60)  # 1분 (4시간봉이지만 더 자주 체크)

        print(f"\n{'='*60}")
        print(f"  병렬 전략 실행 엔진 초기화 완료")
        print(f"  Long 간격: {self.long_interval}초")
        print(f"  Short 간격: {self.short_interval}초")
        print(f"{'='*60}\n")

    def run_long_loop(self):
        """Long 전략 루프"""
        print("[Long] 루프 시작")

        while True:
            try:
                result = self.long_runner.run_once()
                print(f"[Long] {datetime.now().strftime('%H:%M:%S')} - "
                      f"{result['action']} ({result.get('reason', '')})")

            except Exception as e:
                print(f"[Long] 오류: {e}")

            time.sleep(self.long_interval)

    def run_short_loop(self):
        """Short 전략 루프"""
        if not self.short_runner.enabled:
            print("[Short] 비활성화됨")
            return

        print("[Short] 루프 시작")

        while True:
            try:
                result = self.short_runner.run_once()
                print(f"[Short] {datetime.now().strftime('%H:%M:%S')} - "
                      f"{result['action']} ({result.get('reason', '')})")

            except Exception as e:
                print(f"[Short] 오류: {e}")

            time.sleep(self.short_interval)

    def run_once(self):
        """한 번 실행 (테스트용)"""
        print(f"\n{'='*60}")
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 전략 실행")
        print(f"{'='*60}")

        # Long 전략
        long_result = self.long_runner.run_once()
        print(f"[Long] {long_result['action']} - {long_result.get('reason', '')}")
        print(f"       시장 상태: {long_result.get('market_state', 'UNKNOWN')}")

        # Short 전략
        short_result = self.short_runner.run_once()
        print(f"[Short] {short_result['action']} - {short_result.get('reason', '')}")

        # 상태 출력
        print(f"\n[현재 상태]")
        long_status = self.long_runner.get_status()
        print(f"  업비트: {long_status['total_value_krw']:,.0f} KRW "
              f"(포지션: {'있음' if long_status['has_position'] else '없음'})")

        short_status = self.short_runner.get_status()
        if short_status.get('enabled'):
            print(f"  바이낸스: ${short_status['total_balance_usdt']:,.2f} USDT "
                  f"(포지션: {'있음' if short_status['has_position'] else '없음'})")
        else:
            print(f"  바이낸스: 비활성화")

    def run_parallel(self):
        """병렬 실행"""
        print(f"\n{'='*60}")
        print(f"  병렬 전략 실행 시작")
        print(f"{'='*60}\n")

        if self.notifier:
            self.notifier.send_message(
                f"병렬 트레이딩 봇 시작\n"
                f"Long: v35_optimized (업비트)\n"
                f"Short: SHORT_V1 (바이낸스)"
            )

        # Long 전략 스레드
        long_thread = threading.Thread(target=self.run_long_loop, daemon=True)
        long_thread.start()

        # Short 전략 스레드 (활성화된 경우)
        if self.short_runner.enabled:
            short_thread = threading.Thread(target=self.run_short_loop, daemon=True)
            short_thread.start()

        try:
            while True:
                time.sleep(60)
                # 주기적 상태 출력
                self._print_status()

        except KeyboardInterrupt:
            print("\n\n사용자 중단")
            self.emergency_close_all()

    def _print_status(self):
        """상태 출력"""
        long_status = self.long_runner.get_status()
        short_status = self.short_runner.get_status()

        print(f"\n[{datetime.now().strftime('%H:%M:%S')}] 상태")
        print(f"  Long: {long_status['total_value_krw']:,.0f} KRW")
        if short_status.get('enabled'):
            print(f"  Short: ${short_status['total_balance_usdt']:,.2f} USDT")

    def emergency_close_all(self):
        """긴급 청산"""
        print("\n긴급 청산 실행...")

        # Long 청산
        if self.long_runner.position:
            try:
                self.long_runner.upbit.sell_market_order()
                print("[Long] 청산 완료")
            except Exception as e:
                print(f"[Long] 청산 오류: {e}")

        # Short 청산
        if self.short_runner.enabled and self.short_runner.position:
            try:
                self.short_runner.binance.close_all_positions()
                print("[Short] 청산 완료")
            except Exception as e:
                print(f"[Short] 청산 오류: {e}")

        if self.notifier:
            self.notifier.send_message("긴급 청산 완료")

        print("긴급 청산 완료")

    def get_total_status(self) -> Dict:
        """전체 상태 조회"""
        long_status = self.long_runner.get_status()
        short_status = self.short_runner.get_status()

        # 환율 (대략)
        usd_krw = 1300

        total_krw = long_status['total_value_krw']
        if short_status.get('enabled'):
            total_krw += short_status['total_balance_usdt'] * usd_krw

        return {
            'long': long_status,
            'short': short_status,
            'total_krw': total_krw
        }


def main():
    import argparse

    parser = argparse.ArgumentParser(description='병렬 전략 실행 엔진')
    parser.add_argument('--once', action='store_true', help='한 번만 실행')
    parser.add_argument('--long-interval', type=int, default=300, help='Long 전략 간격 (초)')
    parser.add_argument('--short-interval', type=int, default=60, help='Short 전략 간격 (초)')

    args = parser.parse_args()

    config = {
        'long_interval': args.long_interval,
        'short_interval': args.short_interval
    }

    engine = ParallelTradingEngine(config)

    if args.once:
        engine.run_once()
    else:
        engine.run_parallel()


if __name__ == '__main__':
    main()
