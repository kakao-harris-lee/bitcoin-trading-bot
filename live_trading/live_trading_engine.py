"""
실시간 트레이딩 엔진
v35 전략 기반 자동/수동 매매
"""

import os
import sys
import time
import json
import sqlite3
import pandas as pd
import numpy as np
import talib
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, Tuple
from dotenv import load_dotenv
import pytz

# 프로젝트 루트를 경로에 추가
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from live_trading.upbit_trader import UpbitTrader
from live_trading.telegram_notifier import TelegramNotifier
from live_trading.paper_trading_manager import PaperTradingManager
from live_trading.telegram_command_handler import TelegramCommandHandler
from strategies.v35_optimized.strategy import V35OptimizedStrategy
from strategies.v35_optimized.dynamic_exit_manager import DynamicExitManager
import pyupbit
import threading


class LiveTradingEngine:
    """실시간 트레이딩 엔진"""

    def __init__(self, auto_trade: bool = False, paper_trading: bool = False, initial_capital: float = 1_000_000):
        """
        Args:
            auto_trade: True면 자동 거래, False면 텔레그램 알림만
            paper_trading: True면 Paper Trading (모의 거래), False면 실거래
            initial_capital: Paper Trading 초기 자본 (기본 100만원)
        """
        load_dotenv()

        self.auto_trade = auto_trade
        self.paper_trading = paper_trading

        # 프로젝트 루트 경로
        self.project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.db_path = os.path.join(self.project_root, "upbit_bitcoin.db")

        # 컴포넌트 초기화
        if paper_trading:
            # Paper Trading 모드
            self.paper_trader = PaperTradingManager(initial_capital)
            self.trader = None  # 실제 거래 없음
        else:
            # 실거래 모드
            self.trader = UpbitTrader()
            self.paper_trader = None

        self.notifier = TelegramNotifier()

        # 텔레그램 명령어 핸들러
        self.command_handler = TelegramCommandHandler(self.notifier)
        self._register_commands()

        # 모니터링 상태
        self.monitoring_active = False
        self.monitoring_thread = None
        self.monitoring_interval = 30  # 30초마다

        # 설정 로드 (strategy 초기화 전에)
        self._load_config()

        self.strategy = V35OptimizedStrategy(self.config)
        self.exit_manager = DynamicExitManager(self.config)

        # 포지션 상태
        self.position = None  # {'entry_price', 'entry_time', 'volume', 'strategy', 'market_state'}

        # 중복 알림 방지 (마지막 알림 정보)
        self.last_notified_signal = None  # {'type': 'BUY/SELL', 'price': float, 'time': datetime}

        # 초기 자본 계산
        if self.paper_trading:
            initial_value = self.paper_trader.get_total_value(self.get_current_price())
        else:
            initial_value = self.trader.get_total_value()

        # 시작 알림
        mode_text = "Paper Trading" if self.paper_trading else "실거래"
        self.notifier.notify_start(
            strategy=f"v35_optimized ({mode_text})",
            capital=initial_value
        )

        print(f"\n{'=' * 60}")
        print(f"🤖 실시간 트레이딩 엔진 시작")
        print(f"{'=' * 60}")
        print(f"전략: v35_optimized")
        print(f"모드: {mode_text}")
        print(f"자동 거래: {'ON' if self.auto_trade else 'OFF (알림만)'}")
        print(f"초기 자본: {initial_value:,.0f} KRW")
        print(f"{'=' * 60}\n")

        # 텔레그램 명령어 polling 시작
        self.command_handler.start_polling()

    def _load_config(self):
        """v35 설정 로드"""
        config_path = os.path.join(
            self.project_root,
            "strategies/v35_optimized/config_optimized.json"
        )

        with open(config_path, 'r') as f:
            self.config = json.load(f)

        print(f"✅ 설정 로드 완료: {config_path}")

    def _register_commands(self):
        """텔레그램 명령어 등록"""
        self.command_handler.register_command('monitor', self._handle_monitor_command)
        self.command_handler.register_command('status', self._handle_status_command)
        self.command_handler.register_command('help', self._handle_help_command)

    def _handle_monitor_command(self, args: str):
        """
        /monitor 명령어 처리

        Args:
            args: "start" 또는 "stop"
        """
        args = args.strip().lower()

        if args == 'start':
            if self.monitoring_active:
                self.notifier.send_message("⚠️ 모니터링이 이미 실행 중입니다.")
            else:
                self._start_monitoring()
                self.notifier.send_message(
                    f"✅ 모니터링 시작\n\n"
                    f"📊 {self.monitoring_interval}초마다 상태를 전송합니다.\n"
                    f"중지: /monitor stop"
                )

        elif args == 'stop':
            if not self.monitoring_active:
                self.notifier.send_message("⚠️ 모니터링이 실행 중이 아닙니다.")
            else:
                self._stop_monitoring()
                self.notifier.send_message("✅ 모니터링 중지")

        else:
            self.notifier.send_message(
                "⚠️ 사용법:\n"
                "/monitor start - 모니터링 시작\n"
                "/monitor stop - 모니터링 중지"
            )

    def _handle_status_command(self, args: str):
        """/status 명령어 처리 - 현재 상태 즉시 전송"""
        self._send_monitoring_report()

    def _handle_help_command(self, args: str):
        """/help 명령어 처리"""
        help_text = """
📖 *사용 가능한 명령어*

/status - 현재 상태 확인
/monitor start - 실시간 모니터링 시작 (30초마다)
/monitor stop - 실시간 모니터링 중지
/help - 도움말

_v35 Paper Trading Bot_
        """
        self.notifier.send_message(help_text)

    def _start_monitoring(self):
        """주기적 모니터링 시작"""
        if self.monitoring_active:
            return

        self.monitoring_active = True

        def monitoring_worker():
            print(f"🔄 모니터링 시작 ({self.monitoring_interval}초마다)")

            while self.monitoring_active:
                try:
                    self._send_monitoring_report()
                    time.sleep(self.monitoring_interval)
                except Exception as e:
                    print(f"❌ 모니터링 에러: {e}")
                    time.sleep(10)

            print("⏸️  모니터링 중지")

        self.monitoring_thread = threading.Thread(target=monitoring_worker, daemon=True)
        self.monitoring_thread.start()

    def _stop_monitoring(self):
        """주기적 모니터링 중지"""
        self.monitoring_active = False

        if self.monitoring_thread:
            self.monitoring_thread.join(timeout=5)

    def _send_monitoring_report(self):
        """현재 상태 리포트 전송"""
        try:
            current_price = self.get_current_price()

            # Paper Trading 성과
            if self.paper_trading:
                perf = self.paper_trader.get_performance(current_price)

                # 포지션 상태
                if self.position:
                    position_info = f"""
📊 *보유 포지션*
  • 진입가: `{self.position['entry_price']:,.0f}` KRW
  • 수량: `{self.position['volume']:.8f}` BTC
  • 현재 수익률: `{perf['position_profit_pct']:+.2f}%`
  • 전략: `{self.position['strategy']}`
  • 시장 상태: `{self.position['market_state']}`
"""
                else:
                    position_info = "\n📊 *보유 포지션*\n  • 없음 (대기 중)\n"

                message = f"""
📊 *Paper Trading 현황*
━━━━━━━━━━━━━━━━━━━━━━━━━━
🕐 시간: `{self._get_kst_time()}` (KST)
💵 현재가: `{current_price:,.0f}` KRW

💰 *잔고*
  • KRW: `{perf['current_cash']:,.0f}` KRW
  • BTC: `{perf['btc_balance']:.8f}` BTC
  • 평가액: `{perf['total_value']:,.0f}` KRW

📈 *성과*
  • 누적 수익률: `{perf['total_return']:+.2f}%`
  • 누적 수익: `{perf['total_profit']:+,.0f}` KRW
  • 총 거래: `{perf['total_trades']}건`
  • 승률: `{perf['win_rate']:.1f}%`
{position_info}
━━━━━━━━━━━━━━━━━━━━━━━━━━
_자동 업데이트 중..._
"""
            else:
                # 실거래 모드
                krw_balance, btc_balance = self.trader.get_balance()
                total_value = self.trader.get_total_value()

                message = f"""
📊 *실거래 현황*
━━━━━━━━━━━━━━━━━━━━━━━━━━
🕐 시간: `{self._get_kst_time()}` (KST)
💵 현재가: `{current_price:,.0f}` KRW

💰 *잔고*
  • KRW: `{krw_balance:,.0f}` KRW
  • BTC: `{btc_balance:.8f}` BTC
  • 평가액: `{total_value:,.0f}` KRW

━━━━━━━━━━━━━━━━━━━━━━━━━━
_자동 업데이트 중..._
"""

            self.notifier.send_message(message)

        except Exception as e:
            print(f"❌ 모니터링 리포트 전송 실패: {e}")

    def _get_kst_time(self) -> str:
        """한국 시간 반환 (KST)"""
        kst = pytz.timezone('Asia/Seoul')
        return datetime.now(kst).strftime('%Y-%m-%d %H:%M:%S')

    def get_current_price(self) -> float:
        """
        현재 비트코인 가격 조회 (실시간 API)

        Returns:
            현재 가격
        """
        try:
            price = pyupbit.get_current_price("KRW-BTC")
            return price if price else 0.0
        except Exception as e:
            print(f"❌ 가격 조회 실패: {e}")
            return 0.0

    def get_latest_data(self, timeframe: str = "day", count: int = 100) -> pd.DataFrame:
        """
        DB에서 최신 데이터 로드

        Args:
            timeframe: 타임프레임 (day, minute60 등)
            count: 로드할 캔들 수

        Returns:
            DataFrame
        """
        try:
            conn = sqlite3.connect(self.db_path)

            query = f"""
                SELECT
                    timestamp,
                    opening_price as open,
                    high_price as high,
                    low_price as low,
                    trade_price as close,
                    candle_acc_trade_volume as volume
                FROM bitcoin_{timeframe}
                ORDER BY timestamp DESC
                LIMIT {count}
            """

            df = pd.read_sql_query(query, conn)
            conn.close()

            # 최신순 -> 오래된 순으로 정렬
            df = df.iloc[::-1].reset_index(drop=True)
            df['timestamp'] = pd.to_datetime(df['timestamp'])

            return df

        except Exception as e:
            print(f"❌ 데이터 로드 실패: {e}")
            return pd.DataFrame()

    def _calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        기술 지표 계산

        Args:
            df: OHLCV 데이터

        Returns:
            지표가 추가된 DataFrame
        """
        try:
            # MFI (Money Flow Index) - 14일
            df['mfi'] = talib.MFI(
                df['high'].values,
                df['low'].values,
                df['close'].values,
                df['volume'].values,
                timeperiod=14
            )

            # MACD
            macd, macd_signal, macd_hist = talib.MACD(
                df['close'].values,
                fastperiod=12,
                slowperiod=26,
                signalperiod=9
            )
            df['macd'] = macd
            df['macd_signal'] = macd_signal
            df['macd_hist'] = macd_hist

            # ADX (Average Directional Index)
            df['adx'] = talib.ADX(
                df['high'].values,
                df['low'].values,
                df['close'].values,
                timeperiod=14
            )

            # RSI
            df['rsi'] = talib.RSI(df['close'].values, timeperiod=14)

            # Bollinger Bands
            upper, middle, lower = talib.BBANDS(
                df['close'].values,
                timeperiod=20,
                nbdevup=2,
                nbdevdn=2
            )
            df['bb_upper'] = upper
            df['bb_middle'] = middle
            df['bb_lower'] = lower

            # EMA (Exponential Moving Average)
            df['ema_12'] = talib.EMA(df['close'].values, timeperiod=12)
            df['ema_26'] = talib.EMA(df['close'].values, timeperiod=26)
            df['ema_50'] = talib.EMA(df['close'].values, timeperiod=50)

            # Stochastic
            slowk, slowd = talib.STOCH(
                df['high'].values,
                df['low'].values,
                df['close'].values,
                fastk_period=14,
                slowk_period=3,
                slowd_period=3
            )
            df['stoch_k'] = slowk
            df['stoch_d'] = slowd

            # ATR (Average True Range)
            df['atr'] = talib.ATR(
                df['high'].values,
                df['low'].values,
                df['close'].values,
                timeperiod=14
            )

            return df

        except Exception as e:
            print(f"❌ 지표 계산 실패: {e}")
            return df

    def check_signal(self) -> Tuple[str, Dict[str, Any]]:
        """
        매매 신호 체크

        Returns:
            (신호 타입, 신호 데이터)
            신호 타입: "BUY", "SELL", "HOLD"
        """
        try:
            # 최신 데이터 로드 및 지표 계산
            df = self.get_latest_data(timeframe="day", count=100)

            if df.empty:
                return "HOLD", {}

            # 지표 계산 (MarketClassifierV34에서 필요한 지표들)
            df = self._calculate_indicators(df)

            # 현재 포지션 체크
            if self.position is None:
                # 포지션 없음 -> 매수 신호 체크
                # execute 메서드 호출 (마지막 캔들 기준)
                signal = self.strategy.execute(df, len(df) - 1)

                if signal['action'] == 'buy':
                    current_price = self.get_current_price()

                    # 시장 상태 가져오기
                    market_state = self.strategy.classifier.classify_market_state(
                        df.iloc[-1],
                        df.iloc[-2] if len(df) > 1 else None
                    )

                    # 목표가 계산
                    tp_config = self.config['exit_conditions']

                    if market_state == "BULL_STRONG":
                        tp1_pct = tp_config['tp_bull_strong_1']
                        tp2_pct = tp_config['tp_bull_strong_2']
                        tp3_pct = tp_config['tp_bull_strong_3']
                    elif market_state == "BULL_MODERATE":
                        tp1_pct = tp_config['tp_bull_moderate_1']
                        tp2_pct = tp_config['tp_bull_moderate_2']
                        tp3_pct = tp_config['tp_bull_moderate_3']
                    else:  # SIDEWAYS
                        tp1_pct = tp_config['tp_sideways_1']
                        tp2_pct = tp_config['tp_sideways_2']
                        tp3_pct = tp_config['tp_sideways_3']

                    sl_pct = tp_config['stop_loss']

                    # 매수 금액 계산
                    if self.paper_trading:
                        total_value = self.paper_trader.get_total_value(current_price)
                    else:
                        total_value = self.trader.get_total_value()

                    position_pct = self.config['position_sizing']['position_size']
                    buy_amount = total_value * position_pct

                    signal_data = {
                        'date': self._get_kst_time(),
                        'price': current_price,
                        'market_state': market_state,
                        'strategy': signal.get('reason', 'unknown'),
                        'amount': buy_amount,
                        'position_pct': position_pct * 100,
                        'tp1': current_price * (1 + tp1_pct),
                        'tp1_pct': tp1_pct * 100,
                        'tp2': current_price * (1 + tp2_pct),
                        'tp2_pct': tp2_pct * 100,
                        'tp3': current_price * (1 + tp3_pct),
                        'tp3_pct': tp3_pct * 100,
                        'sl': current_price * (1 + sl_pct),
                        'sl_pct': sl_pct * 100
                    }

                    return "BUY", signal_data

            else:
                # 포지션 있음 -> 매도 신호 체크
                current_price = self.get_current_price()

                # execute 메서드 호출 (매도 신호 체크)
                signal = self.strategy.execute(df, len(df) - 1)

                if signal['action'] == 'sell':
                    # 수익률 계산
                    profit_pct = (current_price - self.position['entry_price']) / self.position[
                        'entry_price'] * 100
                    profit = (current_price - self.position['entry_price']) * self.position['volume']

                    # 보유 일수 계산
                    kst = pytz.timezone('Asia/Seoul')
                    now_kst = datetime.now(kst)

                    # entry_time도 timezone-aware로 변환
                    if isinstance(self.position['entry_time'], str):
                        entry_time = datetime.strptime(self.position['entry_time'], '%Y-%m-%d %H:%M:%S')
                        entry_time = kst.localize(entry_time)
                    else:
                        entry_time = self.position['entry_time']
                        if entry_time.tzinfo is None:
                            entry_time = kst.localize(entry_time)

                    hold_days = (now_kst - entry_time).days

                    signal_data = {
                        'date': self._get_kst_time(),
                        'price': current_price,
                        'amount': current_price * self.position['volume'],
                        'profit_pct': profit_pct,
                        'profit': profit,
                        'hold_days': hold_days,
                        'exit_reason': signal.get('reason', 'UNKNOWN')
                    }

                    return "SELL", signal_data

            return "HOLD", {}

        except Exception as e:
            print(f"❌ 신호 체크 실패: {e}")
            self.notifier.notify_error(f"신호 체크 실패: {e}")
            return "HOLD", {}

    def execute_trade(self, signal_type: str, signal_data: Dict[str, Any]) -> bool:
        """
        거래 실행 (Paper Trading 또는 실거래)

        Args:
            signal_type: "BUY" or "SELL"
            signal_data: 신호 데이터

        Returns:
            성공 여부
        """
        try:
            if signal_type == "BUY":
                # 매수 실행
                if self.paper_trading:
                    # Paper Trading 매수
                    position_pct = self.config['position_sizing']['position_size']
                    result = self.paper_trader.buy(
                        price=signal_data['price'],
                        position_pct=position_pct,
                        signal_data=signal_data
                    )
                else:
                    # 실거래 매수
                    result = self.trader.buy_market_order(signal_data['amount'])

                if result and result['success']:
                    # 포지션 저장 (한국 시간)
                    kst = pytz.timezone('Asia/Seoul')
                    self.position = {
                        'entry_price': result['executed_price'],
                        'entry_time': datetime.now(kst),
                        'volume': result['executed_volume'],
                        'strategy': signal_data['strategy'],
                        'market_state': signal_data['market_state']
                    }

                    # 알림 전송 (Paper Trading 표시 추가)
                    result_with_mode = result.copy()
                    result_with_mode['paper_trading'] = self.paper_trading
                    self.notifier.notify_trade_executed("BUY", result_with_mode)

                    return True

            elif signal_type == "SELL":
                # 매도 실행
                if self.paper_trading:
                    # Paper Trading 매도
                    result = self.paper_trader.sell(
                        price=signal_data['price'],
                        signal_data=signal_data
                    )
                else:
                    # 실거래 매도
                    result = self.trader.sell_market_order()

                if result and result['success']:
                    # 포지션 클리어
                    self.position = None

                    # 알림 전송 (Paper Trading 표시 추가)
                    result_with_mode = result.copy()
                    result_with_mode['paper_trading'] = self.paper_trading
                    self.notifier.notify_trade_executed("SELL", result_with_mode)

                    return True

            return False

        except Exception as e:
            print(f"❌ 거래 실행 실패: {e}")
            self.notifier.notify_error(f"거래 실행 실패: {e}")
            return False

    def run_once(self):
        """한 번 실행 (5분마다 호출)"""
        print(f"\n{'=' * 60}")
        print(f"🔍 신호 체크: {self._get_kst_time()} (KST)")
        print(f"{'=' * 60}")

        # 신호 체크
        signal_type, signal_data = self.check_signal()

        if signal_type == "HOLD":
            print("⚪ 신호 없음 (대기)")
            return

        # === 중복 알림 방지 ===
        should_notify = False

        if signal_type == "BUY":
            # BUY 신호: 마지막 알림과 비교
            if self.last_notified_signal is None:
                # 첫 신호
                should_notify = True
            elif self.last_notified_signal['type'] != 'BUY':
                # 이전 신호가 BUY가 아니었음 (SELL → BUY)
                should_notify = True
            else:
                # 이전에도 BUY였음 → 가격 변동 체크
                last_price = self.last_notified_signal['price']
                current_price = signal_data['price']
                price_change = abs(current_price - last_price) / last_price

                if price_change >= 0.05:  # 5% 이상 변동
                    should_notify = True
                    print(f"💡 가격 변동 {price_change*100:.2f}% → 알림 재전송")
                else:
                    print(f"⏸️  동일 BUY 신호 (가격 변동 {price_change*100:.2f}%) → 알림 생략")

        elif signal_type == "SELL":
            # SELL 신호: 항상 알림 (익절/손절 타이밍 중요)
            should_notify = True

        # === 알림 전송 ===
        if should_notify:
            self.notifier.notify_signal(signal_type, signal_data)

            # 마지막 알림 정보 저장
            kst = pytz.timezone('Asia/Seoul')
            self.last_notified_signal = {
                'type': signal_type,
                'price': signal_data['price'],
                'time': datetime.now(kst)
            }

            print(f"\n📱 {signal_type} 신호 알림 전송!")
            print(f"데이터: {signal_data}")

            # 자동 거래 모드면 실행
            if self.auto_trade:
                print("\n🤖 자동 거래 실행...")
                success = self.execute_trade(signal_type, signal_data)

                if success:
                    print("✅ 거래 실행 완료")
                else:
                    print("❌ 거래 실행 실패")
            else:
                print("\n📱 알림만 전송 (자동 거래 OFF)")
        else:
            print(f"\n{signal_type} 신호 발생 (알림 생략)")

    def run_forever(self):
        """
        무한 루프 실행
        - 신호 체크: 5분마다
        - 일일 리포트: 매일 오전 9시(KST)
        """
        print("\n🔄 실시간 모니터링 시작...")
        print("신호 체크: 5분마다")
        print("일일 리포트: 매일 오전 9시(KST)\n")

        last_report_date = None
        kst = pytz.timezone('Asia/Seoul')

        while True:
            try:
                # 한국 시간 기준
                now_kst = datetime.now(kst)

                # === 신호 체크 (5분마다) ===
                self.run_once()

                # === 일일 리포트 (오전 9시) ===
                if now_kst.hour == 9 and now_kst.minute < 5:  # 9:00~9:04
                    today = now_kst.date()

                    # 오늘 아직 리포트 안보냈으면
                    if last_report_date != today:
                        self.send_daily_report()
                        last_report_date = today

                # 5분 대기
                time.sleep(300)

            except KeyboardInterrupt:
                print("\n\n⚠️ 사용자에 의해 중단됨")
                break

            except Exception as e:
                print(f"\n❌ 오류 발생: {e}")
                self.notifier.notify_error(f"시스템 오류: {e}")
                time.sleep(60)  # 에러 시 1분 대기

    def send_daily_report(self):
        """일일 리포트 전송"""
        try:
            current_price = self.get_current_price()
            kst = pytz.timezone('Asia/Seoul')
            today_kst = datetime.now(kst).strftime('%Y-%m-%d')

            if self.paper_trading:
                # Paper Trading 성과
                perf = self.paper_trader.get_performance(current_price)

                report = {
                    'date': today_kst,
                    'krw_balance': perf['current_cash'],
                    'btc_balance': perf['btc_balance'],
                    'total_value': perf['total_value'],
                    'daily_return': 0.0,  # TODO: 일일 수익률 계산
                    'total_return': perf['total_return'],
                    'total_profit': perf['total_profit'],
                    'today_trades': 0,  # TODO: 오늘 거래 수
                    'total_trades': perf['total_trades'],
                    'win_rate': perf['win_rate'],
                    'paper_trading': True
                }
            else:
                # 실거래 잔고
                krw_balance, btc_balance = self.trader.get_balance()
                total_value = self.trader.get_total_value()

                report = {
                    'date': today_kst,
                    'krw_balance': krw_balance,
                    'btc_balance': btc_balance,
                    'total_value': total_value,
                    'daily_return': 0.0,  # TODO: 계산
                    'total_return': 0.0,  # TODO: 계산
                    'total_profit': 0.0,  # TODO: 계산
                    'today_trades': 0,  # TODO: 계산
                    'total_trades': 0,  # TODO: 계산
                    'win_rate': 0.0,  # TODO: 계산
                    'paper_trading': False
                }

            self.notifier.notify_daily_report(report)

        except Exception as e:
            print(f"❌ 리포트 전송 실패: {e}")
