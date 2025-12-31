"""
업비트 거래 실행 모듈
실제 매수/매도 주문 실행
"""

import logging
import os
import time
from pathlib import Path
from typing import Optional, Dict, Any, Tuple
import pyupbit
from dotenv import load_dotenv

# Explicitly load .env from project root
_project_root = Path(__file__).parent.parent.parent
load_dotenv(_project_root / '.env')

logger = logging.getLogger(__name__)


class UpbitTrader:
    """업비트 거래 실행"""

    def __init__(self):
        """환경변수에서 업비트 API 키 로드"""
        # .env already loaded at module level

        self.access_key = os.getenv('UPBIT_ACCESS_KEY')
        self.secret_key = os.getenv('UPBIT_SECRET_KEY')

        if not self.access_key or not self.secret_key:
            raise ValueError("업비트 API 키가 .env 파일에 없습니다")

        self.upbit = pyupbit.Upbit(self.access_key, self.secret_key)
        self.ticker = "KRW-BTC"

        # 연결 테스트
        self._test_connection()

    def _test_connection(self):
        """API 연결 테스트"""
        try:
            balance = self.upbit.get_balance("KRW")
            balance = balance if balance is not None else 0.0
            print(f"✅ 업비트 연결 성공 (KRW 잔고: {balance:,.0f} KRW)")
        except Exception as e:
            raise ConnectionError(f"업비트 연결 실패: {e}")

    def get_current_price(self) -> float:
        """현재 비트코인 가격 조회"""
        try:
            price = pyupbit.get_current_price(self.ticker)
            return price
        except Exception as e:
            print(f"❌ 가격 조회 실패: {e}")
            return 0.0

    def get_balance(self) -> Tuple[float, float]:
        """
        현재 잔고 조회

        Returns:
            (KRW 잔고, BTC 잔고)
        """
        try:
            krw_balance = self.upbit.get_balance("KRW")
            btc_balance = self.upbit.get_balance("BTC")

            # None 처리 (API 권한 부족 시)
            krw_balance = krw_balance if krw_balance is not None else 0.0
            btc_balance = btc_balance if btc_balance is not None else 0.0

            return krw_balance, btc_balance
        except Exception as e:
            print(f"❌ 잔고 조회 실패: {e}")
            return 0.0, 0.0

    def get_total_value(self) -> float:
        """
        총 평가액 조회 (KRW + BTC 평가액)
        """
        krw_balance, btc_balance = self.get_balance()
        current_price = self.get_current_price()

        total_value = krw_balance + (btc_balance * current_price)
        return total_value

    def _wait_for_order_fill(self, uuid: str, max_wait: float = 30.0) -> Optional[Dict[str, Any]]:
        """
        Wait for order fill with exponential backoff.

        Args:
            uuid: Order UUID
            max_wait: Maximum wait time in seconds

        Returns:
            Order status dict if filled, None if timeout
        """
        delay = 0.1  # Start at 100ms
        elapsed = 0.0
        order_status = None

        while elapsed < max_wait:
            order_status = self.upbit.get_order(uuid)

            if order_status and order_status.get('state') == 'done':
                return order_status

            time.sleep(delay)
            elapsed += delay
            delay = min(delay * 2, 2.0)  # Double delay, cap at 2s

        # Timeout - log warning and return last status
        state = order_status.get('state', 'unknown') if order_status else 'unknown'
        logger.warning(f"Order {uuid} not filled after {max_wait}s, state: {state}")
        return order_status

    def buy_market_order(self, amount: float) -> Optional[Dict[str, Any]]:
        """
        시장가 매수

        Args:
            amount: 매수 금액 (KRW)

        Returns:
            거래 결과 딕셔너리
        """
        try:
            # 최소 주문 금액 체크 (5,000 KRW)
            if amount < 5000:
                print(f"❌ 최소 주문 금액 미만: {amount:,.0f} KRW")
                return None

            print(f"📊 시장가 매수 주문: {amount:,.0f} KRW")

            # 주문 실행
            order = self.upbit.buy_market_order(self.ticker, amount)

            if order is None:
                print("❌ 주문 실패")
                return None

            # 주문 UUID
            uuid = order['uuid']

            # 주문 체결 대기 (exponential backoff, 최대 30초)
            order_status = self._wait_for_order_fill(uuid, max_wait=30.0)

            if order_status and order_status.get('state') == 'done':
                # 체결 완료
                executed_volume = float(order_status['executed_volume'])
                executed_amount = float(order_status['paid_fee']) + float(
                    order_status['executed_volume']) * float(order_status['price'])
                executed_price = float(order_status['price'])
                fee = float(order_status['paid_fee'])

                krw_balance, btc_balance = self.get_balance()

                result = {
                    'success': True,
                    'executed_volume': executed_volume,
                    'executed_amount': executed_amount,
                    'executed_price': executed_price,
                    'fee': fee,
                    'krw_balance': krw_balance,
                    'btc_balance': btc_balance,
                    'total_value': self.get_total_value()
                }

                print(f"✅ 매수 완료: {executed_volume:.8f} BTC @ {executed_price:,.0f} KRW")
                return result

            print("⚠️ 주문 체결 시간 초과")
            return None

        except Exception as e:
            print(f"❌ 매수 주문 실패: {e}")
            return None

    def sell_market_order(self, volume: Optional[float] = None) -> Optional[Dict[str, Any]]:
        """
        시장가 매도

        Args:
            volume: 매도 수량 (BTC). None이면 전량 매도

        Returns:
            거래 결과 딕셔너리
        """
        try:
            # 현재 BTC 잔고 조회
            _, btc_balance = self.get_balance()

            if btc_balance == 0:
                print("❌ BTC 잔고 없음")
                return None

            # 매도 수량 결정
            if volume is None:
                volume = btc_balance
            else:
                volume = min(volume, btc_balance)

            # 최소 주문 금액 체크 (5,000 KRW)
            current_price = self.get_current_price()
            if volume * current_price < 5000:
                print(f"❌ 최소 주문 금액 미만: {volume * current_price:,.0f} KRW")
                return None

            print(f"📊 시장가 매도 주문: {volume:.8f} BTC")

            # 주문 실행
            order = self.upbit.sell_market_order(self.ticker, volume)

            if order is None:
                print("❌ 주문 실패")
                return None

            # 주문 UUID
            uuid = order['uuid']

            # 주문 체결 대기 (exponential backoff, 최대 30초)
            order_status = self._wait_for_order_fill(uuid, max_wait=30.0)

            if order_status and order_status.get('state') == 'done':
                # 체결 완료
                executed_volume = float(order_status['executed_volume'])
                executed_amount = float(order_status['executed_volume']) * float(
                    order_status['price']) - float(order_status['paid_fee'])
                executed_price = float(order_status['price'])
                fee = float(order_status['paid_fee'])

                krw_balance, btc_balance = self.get_balance()

                result = {
                    'success': True,
                    'executed_volume': executed_volume,
                    'executed_amount': executed_amount,
                    'executed_price': executed_price,
                    'fee': fee,
                    'krw_balance': krw_balance,
                    'btc_balance': btc_balance,
                    'total_value': self.get_total_value()
                }

                print(f"✅ 매도 완료: {executed_volume:.8f} BTC @ {executed_price:,.0f} KRW")
                return result

            print("⚠️ 주문 체결 시간 초과")
            return None

        except Exception as e:
            print(f"❌ 매도 주문 실패: {e}")
            return None

    def get_orderbook(self) -> Optional[Dict[str, Any]]:
        """호가 정보 조회"""
        try:
            orderbook = pyupbit.get_orderbook(self.ticker)
            return orderbook
        except Exception as e:
            print(f"❌ 호가 조회 실패: {e}")
            return None
