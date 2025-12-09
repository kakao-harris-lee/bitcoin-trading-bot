#!/usr/bin/env python3
"""
바이낸스 선물 거래 모듈
BTCUSDT 무기한 선물 거래 (숏 포지션)
"""

import os
from typing import Optional, Dict, Any, Tuple
from binance.client import Client
from binance.enums import *
from binance.exceptions import BinanceAPIException
from dotenv import load_dotenv
import time


class BinanceFuturesTrader:
    """바이낸스 선물 거래 실행 (숏 포지션 전용)"""

    def __init__(self):
        """환경변수에서 바이낸스 API 키 로드"""
        load_dotenv()

        self.api_key = os.getenv('BINANCE_API_KEY')
        self.api_secret = os.getenv('BINANCE_API_SECRET')

        if not self.api_key or not self.api_secret:
            raise ValueError("바이낸스 API 키가 .env 파일에 없습니다")

        self.client = Client(self.api_key, self.api_secret)
        self.symbol = 'BTCUSDT'
        self.max_leverage = 1  # 안전하게 1배 고정

        # 연결 테스트
        self._test_connection()
        self._initialize_futures()

    def _test_connection(self):
        """API 연결 테스트"""
        try:
            account = self.client.futures_account()
            total_balance = float(account['totalWalletBalance'])
            print(f"✅ 바이낸스 선물 연결 성공 (총 잔고: {total_balance:.2f} USDT)")
        except Exception as e:
            raise ConnectionError(f"바이낸스 선물 연결 실패: {e}")

    def _initialize_futures(self):
        """선물 계정 초기화"""
        try:
            # 레버리지 설정 (1배)
            self.client.futures_change_leverage(
                symbol=self.symbol,
                leverage=self.max_leverage
            )
            print(f"✅ {self.symbol} 레버리지 {self.max_leverage}배로 설정")

            # 마진 타입: CROSSED (교차 마진)
            try:
                self.client.futures_change_margin_type(
                    symbol=self.symbol,
                    marginType='CROSSED'
                )
                print(f"✅ {self.symbol} 마진 타입: CROSSED")
            except BinanceAPIException as e:
                if e.code == -4046:  # 이미 설정된 경우
                    print(f"ℹ️  {self.symbol} 마진 타입 이미 CROSSED로 설정됨")
                else:
                    raise

        except Exception as e:
            raise RuntimeError(f"선물 계정 초기화 실패: {e}")

    def get_current_price(self) -> float:
        """현재 BTC 가격 조회"""
        try:
            ticker = self.client.futures_symbol_ticker(symbol=self.symbol)
            return float(ticker['price'])
        except Exception as e:
            print(f"❌ 가격 조회 실패: {e}")
            return 0.0

    def get_account_info(self) -> Dict[str, Any]:
        """계정 정보 조회"""
        try:
            account = self.client.futures_account()

            total_balance = float(account['totalWalletBalance'])
            available_balance = float(account['availableBalance'])
            total_unrealized_pnl = float(account['totalUnrealizedProfit'])

            return {
                'total_balance': total_balance,
                'available_balance': available_balance,
                'unrealized_pnl': total_unrealized_pnl
            }
        except Exception as e:
            print(f"❌ 계정 정보 조회 실패: {e}")
            return {}

    def get_position(self) -> Optional[Dict[str, Any]]:
        """
        현재 포지션 조회

        Returns:
            포지션 정보 또는 None (포지션 없음)
        """
        try:
            positions = self.client.futures_position_information(symbol=self.symbol)

            for pos in positions:
                position_amt = float(pos['positionAmt'])
                if position_amt != 0:
                    entry_price = float(pos['entryPrice'])
                    unrealized_pnl = float(pos['unRealizedProfit'])
                    leverage = int(pos['leverage'])

                    return {
                        'symbol': self.symbol,
                        'position_amt': position_amt,  # 음수 = 숏, 양수 = 롱
                        'entry_price': entry_price,
                        'unrealized_pnl': unrealized_pnl,
                        'leverage': leverage,
                        'side': 'SHORT' if position_amt < 0 else 'LONG'
                    }

            return None  # 포지션 없음

        except Exception as e:
            print(f"❌ 포지션 조회 실패: {e}")
            return None

    def open_short(self, usdt_amount: float, leverage: int = 1) -> Optional[Dict[str, Any]]:
        """
        숏 포지션 오픈

        Args:
            usdt_amount: 투자 금액 (USDT)
            leverage: 레버리지 (기본 1배, 최대 1배로 제한)

        Returns:
            거래 결과 딕셔너리
        """
        try:
            # 안전장치: 레버리지 1배 초과 방지
            if leverage > self.max_leverage:
                print(f"⚠️  레버리지 {leverage}배는 최대 {self.max_leverage}배를 초과합니다. 1배로 제한합니다.")
                leverage = self.max_leverage

            # 레버리지 설정
            self.client.futures_change_leverage(
                symbol=self.symbol,
                leverage=leverage
            )

            # 현재 가격
            current_price = self.get_current_price()
            if current_price == 0:
                return None

            # 수량 계산 (USDT -> BTC)
            quantity = (usdt_amount * leverage) / current_price

            # 바이낸스 최소 주문 수량 (0.001 BTC)
            min_qty = 0.001
            if quantity < min_qty:
                print(f"❌ 최소 주문 수량 미달: {quantity:.6f} BTC (최소 {min_qty} BTC)")
                return None

            # 소수점 3자리로 반올림
            quantity = round(quantity, 3)

            print(f"📊 숏 포지션 오픈: {quantity:.3f} BTC @ {current_price:,.2f} USDT (레버리지 {leverage}배)")

            # 주문 실행 (SELL = 숏 오픈)
            order = self.client.futures_create_order(
                symbol=self.symbol,
                side=SIDE_SELL,
                type=ORDER_TYPE_MARKET,
                quantity=quantity
            )

            # 체결 확인
            time.sleep(1)
            order_status = self.client.futures_get_order(
                symbol=self.symbol,
                orderId=order['orderId']
            )

            if order_status['status'] == 'FILLED':
                avg_price = float(order_status['avgPrice'])
                executed_qty = float(order_status['executedQty'])
                commission = float(order_status.get('fee', 0))

                position = self.get_position()

                result = {
                    'success': True,
                    'side': 'SHORT',
                    'symbol': self.symbol,
                    'executed_qty': executed_qty,
                    'avg_price': avg_price,
                    'commission': commission,
                    'leverage': leverage,
                    'position': position
                }

                print(f"✅ 숏 오픈 완료: {executed_qty:.3f} BTC @ {avg_price:,.2f} USDT")
                return result

            else:
                print(f"⚠️  주문 미체결: {order_status['status']}")
                return None

        except BinanceAPIException as e:
            print(f"❌ 바이낸스 API 에러: {e}")
            return None
        except Exception as e:
            print(f"❌ 숏 오픈 실패: {e}")
            return None

    def close_short(self) -> Optional[Dict[str, Any]]:
        """
        숏 포지션 청산

        Returns:
            거래 결과 딕셔너리
        """
        try:
            # 현재 포지션 확인
            position = self.get_position()

            if not position:
                print("ℹ️  청산할 포지션이 없습니다.")
                return None

            if position['side'] != 'SHORT':
                print(f"⚠️  숏 포지션이 아닙니다: {position['side']}")
                return None

            # 포지션 수량 (음수)
            position_amt = abs(position['position_amt'])
            entry_price = position['entry_price']
            unrealized_pnl = position['unrealized_pnl']

            print(f"📊 숏 포지션 청산: {position_amt:.3f} BTC (진입가: {entry_price:,.2f}, PnL: {unrealized_pnl:+.2f} USDT)")

            # 청산 주문 (BUY = 숏 청산)
            order = self.client.futures_create_order(
                symbol=self.symbol,
                side=SIDE_BUY,
                type=ORDER_TYPE_MARKET,
                quantity=position_amt
            )

            # 체결 확인
            time.sleep(1)
            order_status = self.client.futures_get_order(
                symbol=self.symbol,
                orderId=order['orderId']
            )

            if order_status['status'] == 'FILLED':
                avg_price = float(order_status['avgPrice'])
                executed_qty = float(order_status['executedQty'])
                commission = float(order_status.get('fee', 0))

                # 실현 손익 계산
                realized_pnl = (entry_price - avg_price) * executed_qty - commission

                result = {
                    'success': True,
                    'side': 'CLOSE_SHORT',
                    'symbol': self.symbol,
                    'executed_qty': executed_qty,
                    'entry_price': entry_price,
                    'exit_price': avg_price,
                    'realized_pnl': realized_pnl,
                    'commission': commission
                }

                print(f"✅ 숏 청산 완료: {executed_qty:.3f} BTC @ {avg_price:,.2f} USDT")
                print(f"   실현 손익: {realized_pnl:+.2f} USDT")
                return result

            else:
                print(f"⚠️  주문 미체결: {order_status['status']}")
                return None

        except BinanceAPIException as e:
            print(f"❌ 바이낸스 API 에러: {e}")
            return None
        except Exception as e:
            print(f"❌ 숏 청산 실패: {e}")
            return None

    def close_all_positions(self) -> bool:
        """
        모든 포지션 강제 청산 (긴급 상황용)

        Returns:
            성공 여부
        """
        try:
            position = self.get_position()

            if not position:
                print("ℹ️  청산할 포지션이 없습니다.")
                return True

            print(f"⚠️  긴급 청산: {position['side']} {abs(position['position_amt']):.3f} BTC")

            if position['side'] == 'SHORT':
                result = self.close_short()
            else:
                # 롱 포지션 청산 (필요 시)
                position_amt = position['position_amt']
                self.client.futures_create_order(
                    symbol=self.symbol,
                    side=SIDE_SELL,
                    type=ORDER_TYPE_MARKET,
                    quantity=position_amt
                )

            return result is not None if position['side'] == 'SHORT' else True

        except Exception as e:
            print(f"❌ 긴급 청산 실패: {e}")
            return False


if __name__ == '__main__':
    """테스트"""

    print("=" * 70)
    print("  바이낸스 선물 트레이더 - 테스트")
    print("=" * 70)

    try:
        trader = BinanceFuturesTrader()

        # 계정 정보
        account = trader.get_account_info()
        print(f"\n[계정 정보]")
        print(f"  총 잔고: {account['total_balance']:.2f} USDT")
        print(f"  사용 가능: {account['available_balance']:.2f} USDT")
        print(f"  미실현 손익: {account['unrealized_pnl']:+.2f} USDT")

        # 현재 포지션
        position = trader.get_position()
        if position:
            print(f"\n[현재 포지션]")
            print(f"  {position['side']}: {abs(position['position_amt']):.3f} BTC")
            print(f"  진입가: {position['entry_price']:,.2f} USDT")
            print(f"  미실현 손익: {position['unrealized_pnl']:+.2f} USDT")
            print(f"  레버리지: {position['leverage']}배")
        else:
            print(f"\n[현재 포지션]")
            print(f"  없음")

        # 현재 가격
        current_price = trader.get_current_price()
        print(f"\n[현재 가격]")
        print(f"  BTC/USDT: {current_price:,.2f} USDT")

        print(f"\n✅ 테스트 완료!")
        print(f"\n⚠️  실제 거래를 위해서는 .env 파일에 다음을 추가하세요:")
        print(f"   BINANCE_API_KEY=your_api_key")
        print(f"   BINANCE_API_SECRET=your_api_secret")

    except Exception as e:
        print(f"\n❌ 테스트 실패: {e}")
        print(f"\n💡 .env 파일에 바이낸스 API 키를 추가하세요.")
