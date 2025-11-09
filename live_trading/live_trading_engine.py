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

# 프로젝트 루트를 경로에 추가
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from live_trading.upbit_trader import UpbitTrader
from live_trading.telegram_notifier import TelegramNotifier
from strategies.v35_optimized.strategy import V35OptimizedStrategy
from strategies.v35_optimized.dynamic_exit_manager import DynamicExitManager


class LiveTradingEngine:
    """실시간 트레이딩 엔진"""

    def __init__(self, auto_trade: bool = False):
        """
        Args:
            auto_trade: True면 자동 거래, False면 텔레그램 알림만
        """
        load_dotenv()

        self.auto_trade = auto_trade

        # 프로젝트 루트 경로
        self.project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.db_path = os.path.join(self.project_root, "upbit_bitcoin.db")

        # 컴포넌트 초기화
        self.trader = UpbitTrader()
        self.notifier = TelegramNotifier()

        # 설정 로드 (strategy 초기화 전에)
        self._load_config()

        self.strategy = V35OptimizedStrategy(self.config)
        self.exit_manager = DynamicExitManager(self.config)

        # 포지션 상태
        self.position = None  # {'entry_price', 'entry_time', 'volume', 'strategy', 'market_state'}

        # 시작 알림
        self.notifier.notify_start(
            strategy="v35_optimized",
            capital=self.trader.get_total_value()
        )

        print(f"\n{'=' * 60}")
        print(f"🤖 실시간 트레이딩 엔진 시작")
        print(f"{'=' * 60}")
        print(f"전략: v35_optimized")
        print(f"자동 거래: {'ON' if self.auto_trade else 'OFF (알림만)'}")
        print(f"초기 자본: {self.trader.get_total_value():,.0f} KRW")
        print(f"{'=' * 60}\n")

    def _load_config(self):
        """v35 설정 로드"""
        config_path = os.path.join(
            self.project_root,
            "strategies/v35_optimized/config_optimized.json"
        )

        with open(config_path, 'r') as f:
            self.config = json.load(f)

        print(f"✅ 설정 로드 완료: {config_path}")

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
                    current_price = self.trader.get_current_price()

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
                    total_value = self.trader.get_total_value()
                    position_pct = self.config['position_sizing']['position_size']
                    buy_amount = total_value * position_pct

                    signal_data = {
                        'date': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
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
                current_price = self.trader.get_current_price()

                # execute 메서드 호출 (매도 신호 체크)
                signal = self.strategy.execute(df, len(df) - 1)

                if signal['action'] == 'sell':
                    # 수익률 계산
                    profit_pct = (current_price - self.position['entry_price']) / self.position[
                        'entry_price'] * 100
                    profit = (current_price - self.position['entry_price']) * self.position['volume']

                    # 보유 일수 계산
                    hold_days = (datetime.now() - self.position['entry_time']).days

                    signal_data = {
                        'date': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
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
        거래 실행

        Args:
            signal_type: "BUY" or "SELL"
            signal_data: 신호 데이터

        Returns:
            성공 여부
        """
        try:
            if signal_type == "BUY":
                # 매수 실행
                result = self.trader.buy_market_order(signal_data['amount'])

                if result and result['success']:
                    # 포지션 저장
                    self.position = {
                        'entry_price': result['executed_price'],
                        'entry_time': datetime.now(),
                        'volume': result['executed_volume'],
                        'strategy': signal_data['strategy'],
                        'market_state': signal_data['market_state']
                    }

                    # 알림 전송
                    self.notifier.notify_trade_executed("BUY", result)

                    return True

            elif signal_type == "SELL":
                # 매도 실행
                result = self.trader.sell_market_order()

                if result and result['success']:
                    # 포지션 클리어
                    self.position = None

                    # 알림 전송
                    self.notifier.notify_trade_executed("SELL", result)

                    return True

            return False

        except Exception as e:
            print(f"❌ 거래 실행 실패: {e}")
            self.notifier.notify_error(f"거래 실행 실패: {e}")
            return False

    def run_once(self):
        """한 번 실행 (매일 오전 9시에 호출)"""
        print(f"\n{'=' * 60}")
        print(f"🔍 신호 체크: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'=' * 60}")

        # 신호 체크
        signal_type, signal_data = self.check_signal()

        if signal_type == "HOLD":
            print("⚪ 신호 없음 (대기)")
            return

        # 신호 알림
        self.notifier.notify_signal(signal_type, signal_data)

        print(f"\n{signal_type} 신호 발생!")
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

    def run_forever(self):
        """
        무한 루프 실행
        매일 오전 9시에 신호 체크
        """
        print("\n🔄 실시간 모니터링 시작...")
        print("매일 오전 9시에 신호를 체크합니다.\n")

        last_check_date = None

        while True:
            try:
                now = datetime.now()

                # 오전 9시 체크
                if now.hour == 9 and now.minute == 0:
                    today = now.date()

                    # 오늘 아직 체크 안했으면
                    if last_check_date != today:
                        self.run_once()
                        last_check_date = today

                        # 일일 리포트 전송
                        self.send_daily_report()

                # 1분마다 체크
                time.sleep(60)

            except KeyboardInterrupt:
                print("\n\n⚠️ 사용자에 의해 중단됨")
                break

            except Exception as e:
                print(f"\n❌ 오류 발생: {e}")
                self.notifier.notify_error(f"시스템 오류: {e}")
                time.sleep(60)

    def send_daily_report(self):
        """일일 리포트 전송"""
        try:
            krw_balance, btc_balance = self.trader.get_balance()
            total_value = self.trader.get_total_value()

            report = {
                'date': datetime.now().strftime('%Y-%m-%d'),
                'krw_balance': krw_balance,
                'btc_balance': btc_balance,
                'total_value': total_value,
                'daily_return': 0.0,  # TODO: 계산
                'total_return': 0.0,  # TODO: 계산
                'total_profit': 0.0,  # TODO: 계산
                'today_trades': 0,  # TODO: 계산
                'total_trades': 0,  # TODO: 계산
                'win_rate': 0.0  # TODO: 계산
            }

            self.notifier.notify_daily_report(report)

        except Exception as e:
            print(f"❌ 리포트 전송 실패: {e}")
