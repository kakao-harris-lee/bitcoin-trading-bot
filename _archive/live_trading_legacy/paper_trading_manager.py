"""
Paper Trading Manager
실거래 없이 가상 자본으로 실시간 테스팅
"""

import os
import json
from datetime import datetime
from typing import Dict, Any, Optional, List
import pytz


class PaperTradingManager:
    """Paper Trading (모의 거래) 관리"""

    def __init__(self, initial_capital: float = 1_000_000):
        """
        Args:
            initial_capital: 초기 가상 자본 (기본 100만원)
        """
        self.initial_capital = initial_capital
        self.cash = initial_capital
        self.btc_balance = 0.0
        self.position = None  # {'entry_price', 'entry_time', 'volume', 'strategy', 'market_state'}
        self.trades = []  # 거래 이력
        self.kst = pytz.timezone('Asia/Seoul')

        # 저장 경로
        self.history_file = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            'paper_trading_history.json'
        )

        # 이력 로드
        self.load_history()

        print(f"📊 Paper Trading 모드 시작")
        print(f"💰 초기 자본: {self.initial_capital:,.0f} KRW")
        print(f"💵 현재 잔고: {self.cash:,.0f} KRW")
        print(f"📈 총 거래: {len(self.trades)}건\n")

    def _get_kst_time(self) -> str:
        """한국 시간 반환 (KST)"""
        return datetime.now(self.kst).strftime('%Y-%m-%d %H:%M:%S')

    def load_history(self):
        """저장된 거래 이력 로드"""
        try:
            if os.path.exists(self.history_file):
                with open(self.history_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)

                self.cash = data.get('cash', self.initial_capital)
                self.btc_balance = data.get('btc_balance', 0.0)
                self.position = data.get('position', None)
                self.trades = data.get('trades', [])

                print(f"✅ 거래 이력 로드: {len(self.trades)}건")
            else:
                print("📝 새로운 Paper Trading 시작")
        except Exception as e:
            print(f"⚠️  이력 로드 실패: {e}, 새로 시작합니다")

    def save_history(self):
        """거래 이력 저장"""
        try:
            data = {
                'initial_capital': self.initial_capital,
                'cash': self.cash,
                'btc_balance': self.btc_balance,
                'position': self.position,
                'trades': self.trades,
                'last_updated': self._get_kst_time()
            }

            with open(self.history_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

        except Exception as e:
            print(f"❌ 이력 저장 실패: {e}")

    def buy(self, price: float, position_pct: float, signal_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        가상 매수 실행

        Args:
            price: 매수 가격
            position_pct: 포지션 비율 (0.0 ~ 1.0)
            signal_data: 신호 데이터

        Returns:
            거래 결과
        """
        try:
            # 포지션이 이미 있으면 매수 불가
            if self.position is not None:
                print("⚠️  이미 포지션 보유 중")
                return None

            # 매수 금액 계산
            buy_amount = self.cash * position_pct

            # 최소 주문 금액 체크
            if buy_amount < 5000:
                print(f"❌ 최소 주문 금액 미만: {buy_amount:,.0f} KRW")
                return None

            # 수수료 계산 (0.05%)
            fee = buy_amount * 0.0005

            # 매수 수량 계산
            volume = (buy_amount - fee) / price

            # 잔고 차감
            self.cash -= buy_amount
            self.btc_balance = volume

            # 포지션 저장
            current_time = self._get_kst_time()
            self.position = {
                'entry_price': price,
                'entry_time': current_time,
                'volume': volume,
                'strategy': signal_data.get('strategy', 'unknown'),
                'market_state': signal_data.get('market_state', 'unknown'),
                'buy_amount': buy_amount,
                'fee': fee
            }

            # 거래 이력 저장
            trade = {
                'type': 'BUY',
                'time': current_time,
                'price': price,
                'volume': volume,
                'amount': buy_amount,
                'fee': fee,
                'strategy': self.position['strategy'],
                'market_state': self.position['market_state']
            }
            self.trades.append(trade)

            # 저장
            self.save_history()

            result = {
                'success': True,
                'executed_price': price,
                'executed_volume': volume,
                'executed_amount': buy_amount,
                'fee': fee,
                'krw_balance': self.cash,
                'btc_balance': self.btc_balance,
                'total_value': self.get_total_value(price)
            }

            print(f"✅ [Paper] 매수: {volume:.8f} BTC @ {price:,.0f} KRW")
            return result

        except Exception as e:
            print(f"❌ 매수 실패: {e}")
            return None

    def sell(self, price: float, signal_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        가상 매도 실행

        Args:
            price: 매도 가격
            signal_data: 신호 데이터

        Returns:
            거래 결과
        """
        try:
            # 포지션이 없으면 매도 불가
            if self.position is None:
                print("⚠️  보유 포지션 없음")
                return None

            volume = self.btc_balance
            sell_amount = volume * price

            # 최소 주문 금액 체크
            if sell_amount < 5000:
                print(f"❌ 최소 주문 금액 미만: {sell_amount:,.0f} KRW")
                return None

            # 수수료 계산 (0.05%)
            fee = sell_amount * 0.0005

            # 수익 계산
            profit = sell_amount - self.position['buy_amount']
            profit_pct = profit / self.position['buy_amount'] * 100

            # 보유 일수 계산
            entry_time = datetime.strptime(self.position['entry_time'], '%Y-%m-%d %H:%M:%S')
            entry_time = self.kst.localize(entry_time)
            now_kst = datetime.now(self.kst)
            hold_days = (now_kst - entry_time).days
            hold_hours = (now_kst - entry_time).total_seconds() / 3600

            # 잔고 증가
            self.cash += (sell_amount - fee)
            self.btc_balance = 0.0

            # 거래 이력 저장
            current_time = self._get_kst_time()
            trade = {
                'type': 'SELL',
                'time': current_time,
                'price': price,
                'volume': volume,
                'amount': sell_amount,
                'fee': fee,
                'entry_price': self.position['entry_price'],
                'entry_time': self.position['entry_time'],
                'profit': profit,
                'profit_pct': profit_pct,
                'hold_days': hold_days,
                'hold_hours': hold_hours,
                'exit_reason': signal_data.get('exit_reason', 'unknown')
            }
            self.trades.append(trade)

            # 포지션 클리어
            self.position = None

            # 저장
            self.save_history()

            result = {
                'success': True,
                'executed_price': price,
                'executed_volume': volume,
                'executed_amount': sell_amount,
                'fee': fee,
                'krw_balance': self.cash,
                'btc_balance': self.btc_balance,
                'total_value': self.get_total_value(price),
                'profit': profit,
                'profit_pct': profit_pct
            }

            print(f"✅ [Paper] 매도: {volume:.8f} BTC @ {price:,.0f} KRW (수익: {profit:+,.0f} KRW, {profit_pct:+.2f}%)")
            return result

        except Exception as e:
            print(f"❌ 매도 실패: {e}")
            return None

    def get_total_value(self, current_price: float) -> float:
        """
        총 평가액 계산

        Args:
            current_price: 현재 BTC 가격

        Returns:
            총 평가액 (KRW)
        """
        return self.cash + (self.btc_balance * current_price)

    def get_performance(self, current_price: float) -> Dict[str, Any]:
        """
        성과 통계

        Args:
            current_price: 현재 BTC 가격

        Returns:
            성과 데이터
        """
        total_value = self.get_total_value(current_price)
        total_return = (total_value - self.initial_capital) / self.initial_capital * 100

        # 거래 통계
        total_trades = len([t for t in self.trades if t['type'] == 'SELL'])
        winning_trades = len([t for t in self.trades if t['type'] == 'SELL' and t['profit'] > 0])
        losing_trades = len([t for t in self.trades if t['type'] == 'SELL' and t['profit'] < 0])
        win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0

        # 총 수익/손실
        total_profit = sum([t['profit'] for t in self.trades if t['type'] == 'SELL'])

        # 평균 수익률
        avg_profit_pct = sum([t['profit_pct'] for t in self.trades if t['type'] == 'SELL']) / total_trades if total_trades > 0 else 0

        # 현재 포지션 수익률
        position_profit_pct = 0
        if self.position:
            position_profit_pct = (current_price - self.position['entry_price']) / self.position['entry_price'] * 100

        return {
            'initial_capital': self.initial_capital,
            'current_cash': self.cash,
            'btc_balance': self.btc_balance,
            'current_price': current_price,
            'total_value': total_value,
            'total_return': total_return,
            'total_profit': total_profit,
            'total_trades': total_trades,
            'winning_trades': winning_trades,
            'losing_trades': losing_trades,
            'win_rate': win_rate,
            'avg_profit_pct': avg_profit_pct,
            'has_position': self.position is not None,
            'position_profit_pct': position_profit_pct
        }

    def get_trade_history(self, limit: int = 10) -> List[Dict[str, Any]]:
        """
        최근 거래 이력

        Args:
            limit: 반환할 거래 수

        Returns:
            거래 이력 리스트
        """
        return self.trades[-limit:]

    def reset(self):
        """초기화 (테스트용)"""
        self.cash = self.initial_capital
        self.btc_balance = 0.0
        self.position = None
        self.trades = []
        self.save_history()
        print("🔄 Paper Trading 초기화 완료")
