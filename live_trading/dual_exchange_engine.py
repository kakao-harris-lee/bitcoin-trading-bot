#!/usr/bin/env python3
"""
듀얼 거래소 전략 엔진
- 업비트: 롱 포지션 (v35 전략)
- 바이낸스 선물: 숏 포지션 (BEAR 헷지)
"""

from typing import Dict, Optional
from datetime import datetime
import json

from upbit_trader import UpbitTrader
from binance_futures_trader import BinanceFuturesTrader


class DualExchangeEngine:
    """
    업비트 + 바이낸스 듀얼 전략 엔진

    전략:
    - BULL/SIDEWAYS: 업비트 롱 포지션
    - BEAR: 업비트 청산 OR 바이낸스 숏 헷지
    """

    def __init__(self, mode: str = 'hedge'):
        """
        Args:
            mode: 'hedge' (숏 헷지) 또는 'cash' (현금 전환)
        """
        self.mode = mode  # 'hedge' or 'cash'

        # 거래소 연결
        self.upbit = UpbitTrader()

        if mode == 'hedge':
            try:
                self.binance = BinanceFuturesTrader()
                print(f"✅ 듀얼 모드: 업비트 롱 + 바이낸스 숏 헷지")
            except Exception as e:
                print(f"⚠️  바이낸스 연결 실패, 현금 전환 모드로 전환: {e}")
                self.mode = 'cash'
                self.binance = None
        else:
            print(f"✅ 단일 모드: 업비트 롱 + 현금 전환")
            self.binance = None

        # 상태 추적
        self.upbit_position = False
        self.binance_position = False
        self.last_market_state = 'UNKNOWN'
        self.trade_log = []

    def get_total_value(self) -> Dict[str, float]:
        """
        총 자산 가치 조회

        Returns:
            {'upbit': float, 'binance': float, 'total': float}
        """
        # 업비트
        upbit_value = self.upbit.get_total_value()

        # 바이낸스
        binance_value = 0.0
        if self.binance:
            account = self.binance.get_account_info()
            binance_value = account.get('total_balance', 0.0)

            # USD -> KRW 변환 (대략 1,300원)
            # TODO: 실시간 환율 API 연동
            binance_value_krw = binance_value * 1300

        total_value = upbit_value + binance_value_krw if self.binance else upbit_value

        return {
            'upbit_krw': upbit_value,
            'binance_usdt': binance_value,
            'binance_krw': binance_value_krw if self.binance else 0.0,
            'total_krw': total_value
        }

    def execute_strategy(self, signal: Dict, market_state: str):
        """
        전략 실행

        Args:
            signal: v35 전략 시그널
            market_state: 시장 상태 (BULL_STRONG, BEAR_MODERATE 등)
        """
        action = signal['action']
        reason = signal.get('reason', '')

        print(f"\n{'='*70}")
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 전략 실행")
        print(f"시장 상태: {market_state}")
        print(f"시그널: {action} ({reason})")
        print(f"{'='*70}")

        # 1. BEAR 시장 진입
        if market_state in ['BEAR_MODERATE', 'BEAR_STRONG']:
            self._handle_bear_market(signal, market_state)

        # 2. BULL/SIDEWAYS 시장 (정상 거래)
        elif market_state in ['BULL_STRONG', 'BULL_MODERATE', 'SIDEWAYS_UP', 'SIDEWAYS_FLAT']:
            self._handle_bull_market(signal, market_state)

        # 3. SIDEWAYS_DOWN (관망)
        else:
            print(f"ℹ️  {market_state}: 관망")

        # 상태 업데이트
        self.last_market_state = market_state

        # 로그 기록
        self._log_trade(signal, market_state)

    def _handle_bear_market(self, signal: Dict, market_state: str):
        """BEAR 시장 대응"""

        # 옵션 1: 현금 전환 모드
        if self.mode == 'cash':
            if self.upbit_position and signal['action'] == 'sell':
                print(f"💰 BEAR 감지 → 업비트 청산 (현금 전환)")
                result = self.upbit.sell_market_order()

                if result and result['success']:
                    self.upbit_position = False
                    print(f"✅ 업비트 청산 완료: {result['total_value']:,.0f}원")

        # 옵션 2: 숏 헷지 모드
        elif self.mode == 'hedge' and self.binance:
            # 업비트 포지션 유지, 바이낸스 숏 오픈
            if self.upbit_position and not self.binance_position:
                print(f"🛡️ BEAR 감지 → 바이낸스 숏 헷지 오픈")

                # 헷지 비율 (업비트 자산의 50%)
                upbit_value = self.upbit.get_total_value()
                hedge_amount_krw = upbit_value * 0.5
                hedge_amount_usdt = hedge_amount_krw / 1300  # KRW -> USDT

                # 최소 금액 체크 (10 USDT)
                if hedge_amount_usdt < 10:
                    print(f"⚠️  헷지 금액 부족: {hedge_amount_usdt:.2f} USDT (최소 10 USDT)")
                    return

                result = self.binance.open_short(
                    usdt_amount=hedge_amount_usdt,
                    leverage=1  # 안전하게 1배
                )

                if result and result['success']:
                    self.binance_position = True
                    print(f"✅ 바이낸스 숏 오픈: {result['executed_qty']:.3f} BTC @ {result['avg_price']:,.2f} USDT")

    def _handle_bull_market(self, signal: Dict, market_state: str):
        """BULL/SIDEWAYS 시장 대응"""

        # 1. 바이낸스 숏 청산 (있으면)
        if self.binance_position and self.binance:
            print(f"📈 BULL/SIDEWAYS 진입 → 바이낸스 숏 청산")
            result = self.binance.close_short()

            if result and result['success']:
                self.binance_position = False
                print(f"✅ 바이낸스 숏 청산: {result['realized_pnl']:+.2f} USDT")

        # 2. 업비트 거래 실행
        if signal['action'] == 'buy' and not self.upbit_position:
            print(f"📊 업비트 매수 시그널")

            krw_balance, _ = self.upbit.get_balance()
            fraction = signal.get('fraction', 0.5)
            buy_amount = krw_balance * fraction

            if buy_amount >= 5000:  # 최소 주문 금액
                result = self.upbit.buy_market_order(buy_amount)

                if result and result['success']:
                    self.upbit_position = True
                    print(f"✅ 업비트 매수: {result['executed_volume']:.8f} BTC @ {result['executed_price']:,.0f}원")

        elif signal['action'] == 'sell' and self.upbit_position:
            print(f"📊 업비트 매도 시그널")

            result = self.upbit.sell_market_order()

            if result and result['success']:
                self.upbit_position = False
                print(f"✅ 업비트 매도: {result['executed_volume']:.8f} BTC @ {result['executed_price']:,.0f}원")

    def _log_trade(self, signal: Dict, market_state: str):
        """거래 로그 기록"""
        log_entry = {
            'timestamp': datetime.now().isoformat(),
            'market_state': market_state,
            'signal': signal,
            'upbit_position': self.upbit_position,
            'binance_position': self.binance_position,
            'mode': self.mode
        }

        self.trade_log.append(log_entry)

        # 로그 파일 저장 (최근 1000개만)
        if len(self.trade_log) > 1000:
            self.trade_log = self.trade_log[-1000:]

    def get_status(self) -> Dict:
        """현재 상태 조회"""

        total_value = self.get_total_value()

        # 업비트 포지션
        krw_balance, btc_balance = self.upbit.get_balance()
        upbit_btc_value = 0
        if btc_balance > 0:
            current_price = self.upbit.get_current_price()
            upbit_btc_value = btc_balance * current_price

        # 바이낸스 포지션
        binance_position = None
        if self.binance:
            binance_position = self.binance.get_position()

        return {
            'mode': self.mode,
            'last_market_state': self.last_market_state,
            'upbit': {
                'has_position': self.upbit_position,
                'krw_balance': krw_balance,
                'btc_balance': btc_balance,
                'btc_value_krw': upbit_btc_value,
                'total_value_krw': total_value['upbit_krw']
            },
            'binance': {
                'has_position': self.binance_position,
                'position': binance_position,
                'total_balance_usdt': total_value.get('binance_usdt', 0),
                'total_balance_krw': total_value.get('binance_krw', 0)
            } if self.binance else None,
            'total_value_krw': total_value['total_krw']
        }

    def emergency_close_all(self):
        """긴급 전량 청산"""
        print(f"\n⚠️  긴급 전량 청산 시작")

        # 업비트 청산
        if self.upbit_position:
            result = self.upbit.sell_market_order()
            if result and result['success']:
                self.upbit_position = False
                print(f"✅ 업비트 청산 완료")

        # 바이낸스 청산
        if self.binance_position and self.binance:
            result = self.binance.close_all_positions()
            if result:
                self.binance_position = False
                print(f"✅ 바이낸스 청산 완료")

        print(f"✅ 긴급 청산 완료!")


if __name__ == '__main__':
    """테스트"""

    print("=" * 70)
    print("  듀얼 거래소 엔진 - 테스트")
    print("=" * 70)

    # 헷지 모드 테스트
    try:
        engine = DualExchangeEngine(mode='hedge')

        # 상태 확인
        status = engine.get_status()

        print(f"\n[현재 상태]")
        print(f"  모드: {status['mode']}")
        print(f"  시장 상태: {status['last_market_state']}")

        print(f"\n[업비트]")
        print(f"  포지션: {'있음' if status['upbit']['has_position'] else '없음'}")
        print(f"  KRW 잔고: {status['upbit']['krw_balance']:,.0f}원")
        print(f"  BTC 잔고: {status['upbit']['btc_balance']:.8f} BTC")
        print(f"  총 가치: {status['upbit']['total_value_krw']:,.0f}원")

        if status['binance']:
            print(f"\n[바이낸스]")
            print(f"  포지션: {'있음' if status['binance']['has_position'] else '없음'}")
            print(f"  총 잔고: {status['binance']['total_balance_usdt']:.2f} USDT")
            print(f"  총 잔고: {status['binance']['total_balance_krw']:,.0f}원")

        print(f"\n[합계]")
        print(f"  총 자산: {status['total_value_krw']:,.0f}원")

        print(f"\n✅ 테스트 완료!")

    except Exception as e:
        print(f"\n❌ 테스트 실패: {e}")
        import traceback
        traceback.print_exc()
