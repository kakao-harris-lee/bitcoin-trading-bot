#!/usr/bin/env python3
"""
Dual Exchange Paper Trading Engine
Upbit(v35) + Binance(SHORT_V1) Paper Trading
"""

import sys
import os
from typing import Dict, Optional
from datetime import datetime
import time

# 프로젝트 루트 추가
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from paper_trading_engine import PaperTradingAccount
from telegram_notifier import TelegramNotifier
from core.data_loader import DataLoader


class DualPaperTradingEngine:
    """듀얼 거래소 Paper Trading 엔진"""

    def __init__(
        self,
        upbit_capital: float = 10_000_000,  # 10M KRW
        binance_capital: float = 10_000,    # 10K USDT
        telegram_enabled: bool = True
    ):
        """
        Args:
            upbit_capital: Upbit 초기 자본 (KRW)
            binance_capital: Binance 초기 자본 (USDT)
            telegram_enabled: 텔레그램 알림 활성화
        """
        print("=" * 70)
        print("  Dual Exchange Paper Trading Engine")
        print("=" * 70)
        print(f"  Upbit Capital: {upbit_capital:,.0f} KRW")
        print(f"  Binance Capital: {binance_capital:,.2f} USDT")
        print("=" * 70)

        # Paper Trading 계좌
        self.upbit_account = PaperTradingAccount(upbit_capital, 'upbit')
        self.binance_account = PaperTradingAccount(binance_capital, 'binance')

        # 전략 로드
        self.v35_strategy = self._load_v35_strategy()
        self.short_v1_strategy = self._load_short_v1_strategy()

        # 텔레그램
        self.telegram = TelegramNotifier() if telegram_enabled else None

        # 상태
        self.upbit_position = False
        self.binance_position = False
        self.last_upbit_signal = None
        self.last_binance_signal = None
        self.iteration_count = 0  # 반복 횟수

        print("✅ 초기화 완료\n")

        # 시작 알림 전송
        self._send_startup_notification(upbit_capital, binance_capital)

    def _send_startup_notification(self, upbit_capital: float, binance_capital: float):
        """시작 알림 전송"""
        if not self.telegram:
            return

        msg = "🚀 Dual Exchange Paper Trading 시작\n"
        msg += "=" * 30 + "\n\n"
        msg += "📊 전략 구성:\n"
        msg += f"  • Upbit: V35 Optimized (Long)\n"
        msg += f"  • Binance: SHORT_V1 (Short)\n\n"
        msg += "💰 초기 자본:\n"
        msg += f"  • Upbit: {upbit_capital:,.0f} KRW\n"
        msg += f"  • Binance: ${binance_capital:,.2f} USDT\n\n"
        msg += f"✅ V35 전략: {'로드 성공' if self.v35_strategy else '❌ 로드 실패'}\n"
        msg += f"✅ SHORT_V1 전략: {'로드 성공' if self.short_v1_strategy else '❌ 로드 실패'}\n\n"
        msg += "⏰ 신호 체크: 60분마다"

        try:
            self.telegram.send_message(msg)
        except Exception as e:
            print(f"⚠️  시작 알림 전송 실패: {e}")

    def _send_status_notification(self, prices: Dict[str, float]):
        """주기적 상태 알림 (6시간마다)"""
        if not self.telegram:
            return

        # 6시간마다 (6회 반복마다)
        if self.iteration_count % 6 != 0:
            return

        upbit_cash, upbit_btc = self.upbit_account.get_balance()
        upbit_total = upbit_cash + (upbit_btc * prices['upbit'])
        upbit_stats = self.upbit_account.get_statistics()

        binance_cash, _ = self.binance_account.get_balance()
        binance_position = self.binance_account.get_position()
        binance_stats = self.binance_account.get_statistics()

        msg = "📊 Dual Paper Trading 상태 보고\n"
        msg += "=" * 30 + "\n\n"
        msg += f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"

        msg += "📈 [Upbit]\n"
        msg += f"  포지션: {'🟢 있음' if self.upbit_position else '⚪ 없음'}\n"
        msg += f"  총 가치: {upbit_total:,.0f}원\n"
        msg += f"  수익률: {upbit_stats['return_pct']:+.2f}%\n\n"

        msg += "📉 [Binance]\n"
        msg += f"  포지션: {'🔻 숏' if self.binance_position else '⚪ 없음'}\n"
        if binance_position:
            msg += f"  진입가: ${binance_position['entry_price']:,.2f}\n"
        msg += f"  현금: ${binance_cash:,.2f}\n"
        msg += f"  수익률: {binance_stats['return_pct']:+.2f}%\n\n"

        # 합계
        total_krw = upbit_total + (binance_cash * 1300)
        initial_total = self.upbit_account.initial_capital + (self.binance_account.initial_capital * 1300)
        total_return_pct = ((total_krw - initial_total) / initial_total) * 100

        msg += f"💰 총 자산: {total_krw:,.0f}원\n"
        msg += f"📊 총 수익률: {total_return_pct:+.2f}%"

        try:
            self.telegram.send_message(msg)
        except Exception as e:
            print(f"⚠️  상태 알림 전송 실패: {e}")

    def _load_v35_strategy(self):
        """v35 전략 로드"""
        try:
            import importlib.util
            import json

            # 절대 경로로 모듈 로드
            strategy_path = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                                         'strategies/v35_optimized/strategy.py')
            spec = importlib.util.spec_from_file_location("v35_strategy", strategy_path)
            v35_module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(v35_module)

            config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                                       'strategies/v35_optimized/config_optimized.json')
            with open(config_path, 'r') as f:
                config = json.load(f)

            strategy = v35_module.V35OptimizedStrategy(config)
            print("✅ V35 전략 로드 완료")
            return strategy

        except Exception as e:
            print(f"❌ V35 전략 로드 실패: {e}")
            import traceback
            traceback.print_exc()
            return None

    def _load_short_v1_strategy(self):
        """SHORT_V1 전략 로드"""
        try:
            import importlib.util
            import json

            # 절대 경로로 모듈 로드
            strategy_path = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                                         'strategies/SHORT_V1/strategy.py')
            spec = importlib.util.spec_from_file_location("short_v1_strategy", strategy_path)
            short_module = importlib.util.module_from_spec(spec)

            # SHORT_V1 indicators 모듈도 로드해야 함
            indicators_path = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                                           'strategies/SHORT_V1/indicators.py')
            ind_spec = importlib.util.spec_from_file_location("indicators", indicators_path)
            ind_module = importlib.util.module_from_spec(ind_spec)
            sys.modules['indicators'] = ind_module
            ind_spec.loader.exec_module(ind_module)

            spec.loader.exec_module(short_module)

            config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                                       'strategies/SHORT_V1/config_optimized.json')
            with open(config_path, 'r') as f:
                config = json.load(f)

            strategy = short_module.ShortV1Strategy(config)
            print("✅ SHORT_V1 전략 로드 완료")
            return strategy

        except Exception as e:
            print(f"❌ SHORT_V1 전략 로드 실패: {e}")
            import traceback
            traceback.print_exc()
            return None

    def get_current_prices(self) -> Dict[str, float]:
        """현재 가격 조회 (실제 시장 데이터)"""
        try:
            import pyupbit
            import requests

            # Upbit BTC/KRW
            upbit_price = pyupbit.get_current_price("KRW-BTC")

            # Binance BTC/USDT
            binance_url = "https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT"
            response = requests.get(binance_url)
            binance_price = float(response.json()['price'])

            return {
                'upbit': upbit_price,
                'binance': binance_price
            }

        except Exception as e:
            print(f"⚠️  가격 조회 실패: {e}")
            return {'upbit': 100_000_000, 'binance': 100_000}  # 임시값

    def execute_upbit_strategy(self, current_price: float):
        """Upbit v35 전략 실행"""
        if not self.v35_strategy:
            print("⚠️  V35 전략 미로드 - Upbit 거래 스킵")
            return

        try:
            # 최근 데이터 로드
            with DataLoader() as loader:
                df = loader.load_timeframe('day', start_date='2024-01-01')

            # 지표 계산 (v35는 자체적으로 처리)
            signal = self.v35_strategy.execute(df, len(df) - 1)

            # 신호 로그 출력
            print(f"[Upbit] 신호: {signal['action']} | 사유: {signal.get('reason', 'N/A')}")

            if signal['action'] == 'buy' and not self.upbit_position:
                # 매수
                cash, btc = self.upbit_account.get_balance()
                buy_amount = cash * signal.get('fraction', 0.5)

                if buy_amount >= 5000:
                    result = self.upbit_account.buy(buy_amount, current_price)

                    if result['success']:
                        self.upbit_position = True
                        self.last_upbit_signal = signal

                        msg = f"🟢 [Upbit Paper] 매수\n"
                        msg += f"━━━━━━━━━━━━━━━━━━━━\n"
                        msg += f"💰 가격: {current_price:,.0f}원\n"
                        msg += f"📊 수량: {result['executed_volume']:.8f} BTC\n"
                        msg += f"📝 사유: {signal.get('reason', 'N/A')}"

                        print(msg)
                        if self.telegram:
                            self.telegram.send_message(msg)

            elif signal['action'] == 'sell' and self.upbit_position:
                # 매도
                cash, btc = self.upbit_account.get_balance()

                if btc > 0:
                    result = self.upbit_account.sell(btc, current_price)

                    if result['success']:
                        self.upbit_position = False
                        self.last_upbit_signal = signal

                        msg = f"🔴 [Upbit Paper] 매도\n"
                        msg += f"━━━━━━━━━━━━━━━━━━━━\n"
                        msg += f"💰 가격: {current_price:,.0f}원\n"
                        msg += f"📊 수량: {result['executed_volume']:.8f} BTC\n"
                        msg += f"💵 손익: {result['pnl']:+,.0f}원\n"
                        msg += f"📝 사유: {signal.get('reason', 'N/A')}"

                        print(msg)
                        if self.telegram:
                            self.telegram.send_message(msg)

            elif signal['action'] == 'hold':
                # 대기 상태 (첫 번째 반복에서만 알림)
                if self.iteration_count == 1:
                    print(f"⚪ [Upbit] 대기 중 - {signal.get('reason', 'N/A')}")

        except Exception as e:
            print(f"❌ Upbit 전략 실행 오류: {e}")
            import traceback
            traceback.print_exc()
            if self.telegram:
                self.telegram.send_message(f"❌ [Upbit] 전략 실행 오류: {e}")

    def execute_binance_strategy(self, current_price: float):
        """Binance SHORT_V1 전략 실행"""
        if not self.short_v1_strategy:
            print("⚠️  SHORT_V1 전략 미로드 - Binance 거래 스킵")
            return

        try:
            # 4시간봉 데이터 필요 (Binance API 또는 로컬 CSV)
            import pandas as pd

            # 로컬 CSV 로드 (data_collector로 미리 수집)
            csv_path = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                                    'strategies/SHORT_V1/results/btcusdt_4h_with_funding_2022-01-01_2024-12-31.csv')

            if os.path.exists(csv_path):
                df = pd.read_csv(csv_path)
                df['timestamp'] = pd.to_datetime(df['timestamp'])
                df = df.tail(300)  # 최근 300개 (워밍업 포함)
                df = df.reset_index(drop=True)

                # 지표 계산
                df = self.short_v1_strategy.prepare_data(df)

                # 현재 자본
                cash, _ = self.binance_account.get_balance()

                # 전략 실행 (execute 메서드 사용)
                signal = self.short_v1_strategy.execute(df, len(df) - 1, cash)

                # 신호 로그 출력
                print(f"[Binance] 신호: {signal['action']} | 사유: {signal.get('reason', 'N/A')}")

                if signal['action'] == 'open_short' and not self.binance_position:
                    # 숏 진입
                    position_size = cash * 0.5  # 50% 사용
                    leverage = signal.get('leverage', 2)

                    if position_size >= 10:  # 최소 10 USDT
                        result = self.binance_account.open_short(
                            position_size,
                            current_price,
                            leverage
                        )

                        if result['success']:
                            self.binance_position = True
                            self.last_binance_signal = signal

                            msg = f"🔻 [Binance Paper] 숏 진입\n"
                            msg += f"━━━━━━━━━━━━━━━━━━━━\n"
                            msg += f"💰 가격: ${current_price:,.2f}\n"
                            msg += f"📊 수량: {result['executed_qty']:.6f} BTC\n"
                            msg += f"⚡ 레버리지: {leverage}x\n"
                            msg += f"📝 사유: {signal.get('reason', 'N/A')}"

                            print(msg)
                            if self.telegram:
                                self.telegram.send_message(msg)

                elif signal['action'] == 'close_short' and self.binance_position:
                    # 숏 청산
                    result = self.binance_account.close_short(current_price)

                    if result['success']:
                        self.binance_position = False
                        self.last_binance_signal = signal

                        msg = f"🔺 [Binance Paper] 숏 청산\n"
                        msg += f"━━━━━━━━━━━━━━━━━━━━\n"
                        msg += f"💰 가격: ${current_price:,.2f}\n"
                        msg += f"💵 손익: ${result['realized_pnl']:+,.2f}\n"
                        msg += f"📝 사유: {signal.get('reason', 'N/A')}"

                        print(msg)
                        if self.telegram:
                            self.telegram.send_message(msg)

                elif signal['action'] == 'hold':
                    # 대기 상태 (첫 번째 반복에서만 알림)
                    if self.iteration_count == 1:
                        print(f"⚪ [Binance] 대기 중 - {signal.get('reason', 'N/A')}")
            else:
                print(f"⚠️  SHORT_V1 데이터 파일 없음: {csv_path}")
                if self.telegram and self.iteration_count == 1:
                    self.telegram.send_message(f"⚠️ [Binance] SHORT_V1 데이터 파일 없음\n실시간 데이터 수집 필요")

        except Exception as e:
            print(f"❌ Binance 전략 실행 오류: {e}")
            import traceback
            traceback.print_exc()
            if self.telegram:
                self.telegram.send_message(f"❌ [Binance] 전략 실행 오류: {e}")

    def run_iteration(self):
        """1회 반복 실행"""
        self.iteration_count += 1

        print(f"\n{'='*70}")
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Paper Trading 실행 (#{self.iteration_count})")
        print(f"{'='*70}")

        # 현재 가격
        prices = self.get_current_prices()
        print(f"Upbit: {prices['upbit']:,.0f}원 | Binance: ${prices['binance']:,.2f}")

        # 전략 실행
        self.execute_upbit_strategy(prices['upbit'])
        self.execute_binance_strategy(prices['binance'])

        # 상태 출력
        self.print_status(prices)

        # 주기적 상태 알림 (6시간마다)
        self._send_status_notification(prices)

    def print_status(self, prices: Dict[str, float]):
        """현재 상태 출력"""
        print(f"\n{'─'*70}")
        print("  현재 상태")
        print(f"{'─'*70}")

        # Upbit
        upbit_cash, upbit_btc = self.upbit_account.get_balance()
        upbit_total = self.upbit_account.get_total_value(prices['upbit'])
        upbit_stats = self.upbit_account.get_statistics()

        print(f"\n[Upbit]")
        print(f"  포지션: {'🟢 있음' if self.upbit_position else '⚪ 없음'}")
        print(f"  현금: {upbit_cash:,.0f}원")
        print(f"  BTC: {upbit_btc:.8f} BTC")
        print(f"  총 가치: {upbit_total:,.0f}원")
        print(f"  수익률: {upbit_stats['return_pct']:+.2f}%")

        # Binance
        binance_cash, _ = self.binance_account.get_balance()
        binance_position = self.binance_account.get_position()
        binance_stats = self.binance_account.get_statistics()

        print(f"\n[Binance]")
        print(f"  포지션: {'🔻 숏' if self.binance_position else '⚪ 없음'}")
        if binance_position:
            print(f"  진입가: ${binance_position['entry_price']:,.2f}")
            print(f"  수량: {binance_position['size']:.6f} BTC")
            print(f"  레버리지: {binance_position['leverage']}x")
        print(f"  현금: ${binance_cash:,.2f}")
        print(f"  수익률: {binance_stats['return_pct']:+.2f}%")

        # 합계
        total_krw = upbit_total + (binance_cash * 1300)  # 간단히 1300 고정
        initial_total = self.upbit_account.initial_capital + (self.binance_account.initial_capital * 1300)
        total_return_pct = ((total_krw - initial_total) / initial_total) * 100

        print(f"\n[합계]")
        print(f"  총 자산: {total_krw:,.0f}원")
        print(f"  총 수익률: {total_return_pct:+.2f}%")
        print(f"{'─'*70}\n")

    def run_forever(self, interval_minutes: int = 60):
        """무한 루프 실행"""
        print(f"\n🚀 Paper Trading 시작 (간격: {interval_minutes}분)\n")

        # 로그 디렉토리 (절대 경로)
        log_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'logs')
        os.makedirs(log_dir, exist_ok=True)

        try:
            while True:
                self.run_iteration()

                # 로그 저장 (절대 경로 사용)
                try:
                    self.upbit_account.save_log(os.path.join(log_dir, 'paper_trading_upbit.json'))
                    self.binance_account.save_log(os.path.join(log_dir, 'paper_trading_binance.json'))
                except Exception as e:
                    print(f"⚠️  로그 저장 실패: {e}")

                # 대기
                print(f"\n⏱️  다음 실행까지 {interval_minutes}분 대기...\n")
                time.sleep(interval_minutes * 60)

        except KeyboardInterrupt:
            print(f"\n\n{'='*70}")
            print("  Paper Trading 중지")
            print(f"{'='*70}\n")

            # 최종 통계
            self.print_final_statistics()

    def print_final_statistics(self):
        """최종 통계 출력"""
        upbit_stats = self.upbit_account.get_statistics()
        binance_stats = self.binance_account.get_statistics()

        print("\n📊 최종 통계")
        print(f"{'='*70}")

        print(f"\n[Upbit]")
        print(f"  초기 자본: {upbit_stats['initial_capital']:,.0f}원")
        print(f"  최종 자본: {upbit_stats['current_cash']:,.0f}원")
        print(f"  총 거래: {upbit_stats['total_trades']}회")
        print(f"  승률: {upbit_stats['win_rate']*100:.1f}%")
        print(f"  순손익: {upbit_stats['net_pnl']:+,.0f}원")
        print(f"  수익률: {upbit_stats['return_pct']:+.2f}%")

        print(f"\n[Binance]")
        print(f"  초기 자본: ${binance_stats['initial_capital']:,.2f}")
        print(f"  최종 자본: ${binance_stats['current_cash']:,.2f}")
        print(f"  총 거래: {binance_stats['total_trades']}회")
        print(f"  승률: {binance_stats['win_rate']*100:.1f}%")
        print(f"  순손익: ${binance_stats['net_pnl']:+,.2f}")
        print(f"  수익률: {binance_stats['return_pct']:+.2f}%")

        print(f"\n{'='*70}\n")


if __name__ == '__main__':
    """실행"""
    import argparse

    parser = argparse.ArgumentParser(description='Dual Exchange Paper Trading')
    parser.add_argument('--upbit-capital', type=float, default=10_000_000,
                        help='Upbit 초기 자본 (KRW, 기본: 10M)')
    parser.add_argument('--binance-capital', type=float, default=10_000,
                        help='Binance 초기 자본 (USDT, 기본: 10K)')
    parser.add_argument('--interval', type=int, default=60,
                        help='실행 간격 (분, 기본: 60)')
    parser.add_argument('--no-telegram', action='store_true',
                        help='텔레그램 알림 비활성화')

    args = parser.parse_args()

    engine = DualPaperTradingEngine(
        upbit_capital=args.upbit_capital,
        binance_capital=args.binance_capital,
        telegram_enabled=not args.no_telegram
    )

    engine.run_forever(interval_minutes=args.interval)
