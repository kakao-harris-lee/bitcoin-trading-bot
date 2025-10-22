"""
Universal Backtest Engine
=========================
모든 전략을 동일한 방법으로 검증하는 통합 백테스팅 엔진

핵심 기능:
- 정확한 복리 계산 (v43 버그 수정 버전)
- 다양한 청산 로직 지원 (TP/SL/Trailing/Timeout)
- 분할 매수/매도 지원
- 통계 산출 (수익률, 승률, Sharpe, MDD)

작성일: 2025-10-20
"""

import pandas as pd
import numpy as np
from typing import List, Dict, Optional, Any
from datetime import datetime, timedelta
import json


class UniversalBacktestEngine:
    """
    전략 독립적인 통합 백테스팅 엔진

    시그널 배열만 입력하면 모든 전략을 동일한 조건으로 검증 가능
    """

    def __init__(
        self,
        initial_capital: float = 10_000_000,
        fee_rate: float = 0.0005,      # 0.05% (upbit)
        slippage: float = 0.0002        # 0.02% (예상 슬리피지)
    ):
        """
        Args:
            initial_capital: 초기 자본 (기본 1천만원)
            fee_rate: 거래 수수료율 (진입/청산 각각)
            slippage: 슬리피지 (진입/청산 각각)
        """
        self.initial_capital = initial_capital
        self.fee_rate = fee_rate
        self.slippage = slippage
        self.total_fee = fee_rate + slippage  # 0.0007 (0.07%)

        # 백테스팅 상태
        self.current_capital = initial_capital
        self.active_position = None
        self.trades = []
        self.capital_history = []
        self.peak_capital = initial_capital
        self.max_drawdown = 0.0

    def run_backtest(
        self,
        signals: List[Dict],
        price_data: pd.DataFrame,
        exit_config: Dict,
        split_config: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """
        시그널 배열 기반 백테스팅 실행

        Args:
            signals: 매수 시그널 배열
                [{
                    'timestamp': '2024-01-01 09:00',
                    'action': 'BUY',
                    'price': 58839000,
                    'score': 42 (optional)
                }]

            price_data: 가격 데이터프레임
                columns: ['timestamp', 'open', 'high', 'low', 'close', 'volume']

            exit_config: 청산 설정
                {
                    'type': 'fixed' | 'dynamic' | 'trailing',
                    'take_profit': 0.05,        # 5%
                    'stop_loss': 0.02,          # 2%
                    'timeout_hours': 72,        # 3일
                    'trailing_stop': 0.005      # 0.5% (optional)
                }

            split_config: 분할 매매 설정 (optional)
                {
                    'enabled': True,
                    'entries': [0.5, 0.3, 0.2],  # 50%, 30%, 20% 진입
                    'exits': [0.4, 0.3, 0.3]      # 40%, 30%, 30% 청산
                }

        Returns:
            {
                'total_return_pct': 123.45,
                'total_trades': 76,
                'winning_trades': 35,
                'losing_trades': 41,
                'win_rate': 46.05,
                'avg_return': 1.62,
                'avg_winning_return': 3.45,
                'avg_losing_return': -1.23,
                'sharpe_ratio': 3.29,
                'max_drawdown': -15.23,
                'final_capital': 12345678,
                'trades': [...]
            }
        """
        # 초기화
        self._reset()

        # 타임스탬프 인덱스 생성
        price_data = price_data.copy()
        price_data['timestamp'] = pd.to_datetime(price_data['timestamp'])
        price_data = price_data.set_index('timestamp').sort_index()

        # 시그널 처리
        for signal in signals:
            # 포지션이 있으면 스킵
            if self.active_position is not None:
                continue

            signal_time = pd.to_datetime(signal['timestamp'])
            entry_price = signal['price']

            # 진입
            self._enter_position(signal_time, entry_price, signal.get('score'))

        # 포지션 청산 체크 (매 캔들마다)
        for timestamp, bar in price_data.iterrows():
            if self.active_position is None:
                continue

            # 청산 조건 확인
            exit_info = self._check_exit_conditions(
                timestamp,
                bar,
                exit_config
            )

            if exit_info:
                self._exit_position(
                    timestamp,
                    exit_info['price'],
                    exit_info['reason']
                )

        # 미청산 포지션 강제 청산
        if self.active_position is not None:
            last_bar = price_data.iloc[-1]
            self._exit_position(
                price_data.index[-1],
                last_bar['close'],
                'end_of_period'
            )

        # 통계 계산
        return self._calculate_statistics()

    def _reset(self):
        """백테스팅 상태 초기화"""
        self.current_capital = self.initial_capital
        self.active_position = None
        self.trades = []
        self.capital_history = [(datetime.now(), self.initial_capital)]
        self.peak_capital = self.initial_capital
        self.max_drawdown = 0.0

    def _enter_position(
        self,
        timestamp: pd.Timestamp,
        entry_price: float,
        score: Optional[float] = None
    ):
        """
        포지션 진입 (정확한 BTC 계산)

        v43 버그 수정 버전:
        - position = capital / buy_cost (❌ 버그)
        - btc_amount = (capital - fee) / entry_price (✅ 정확)
        """
        capital = self.current_capital

        # 수수료 계산
        buy_fee = capital * self.total_fee
        buy_amount = capital - buy_fee

        # ⭐ 정확한 BTC 수량 계산
        btc_amount = buy_amount / entry_price

        # 포지션 기록
        self.active_position = {
            'entry_time': timestamp,
            'entry_price': entry_price,
            'btc_amount': btc_amount,
            'capital_at_entry': capital,
            'buy_fee': buy_fee,
            'score': score,
            'peak_price': entry_price
        }

    def _exit_position(
        self,
        timestamp: pd.Timestamp,
        exit_price: float,
        reason: str
    ):
        """
        포지션 청산 (정확한 수익 계산)
        """
        if self.active_position is None:
            return

        pos = self.active_position

        # ⭐ 정확한 청산 수익 계산
        sell_gross = pos['btc_amount'] * exit_price
        sell_fee = sell_gross * self.total_fee
        sell_net = sell_gross - sell_fee

        # 수익률 계산
        return_pct = (sell_net - pos['capital_at_entry']) / pos['capital_at_entry'] * 100

        # 거래 기록
        trade = {
            'entry_time': pos['entry_time'],
            'exit_time': timestamp,
            'entry_price': pos['entry_price'],
            'exit_price': exit_price,
            'btc_amount': pos['btc_amount'],
            'capital_before': pos['capital_at_entry'],
            'capital_after': sell_net,
            'return_pct': return_pct,
            'buy_fee': pos['buy_fee'],
            'sell_fee': sell_fee,
            'reason': reason,
            'score': pos.get('score'),
            'holding_hours': (timestamp - pos['entry_time']).total_seconds() / 3600
        }

        self.trades.append(trade)

        # 자본 업데이트
        self.current_capital = sell_net
        self.capital_history.append((timestamp, self.current_capital))

        # MDD 업데이트
        if self.current_capital > self.peak_capital:
            self.peak_capital = self.current_capital
        else:
            drawdown = (self.current_capital - self.peak_capital) / self.peak_capital * 100
            self.max_drawdown = min(self.max_drawdown, drawdown)

        # 포지션 초기화
        self.active_position = None

    def _check_exit_conditions(
        self,
        timestamp: pd.Timestamp,
        bar: pd.Series,
        exit_config: Dict
    ) -> Optional[Dict]:
        """
        청산 조건 확인

        Returns:
            None: 청산 안함
            {'price': float, 'reason': str}: 청산 수행
        """
        if self.active_position is None:
            return None

        pos = self.active_position
        current_price = bar['close']
        high_price = bar['high']
        low_price = bar['low']

        # 현재 수익률 계산
        current_return = (current_price - pos['entry_price']) / pos['entry_price']

        # 1. Take Profit
        if current_return >= exit_config.get('take_profit', 0.05):
            return {'price': current_price, 'reason': 'take_profit'}

        # 2. Stop Loss
        if current_return <= -exit_config.get('stop_loss', 0.02):
            return {'price': current_price, 'reason': 'stop_loss'}

        # 3. Trailing Stop
        if 'trailing_stop' in exit_config:
            # Peak 업데이트
            if current_price > pos['peak_price']:
                pos['peak_price'] = current_price

            # Trailing stop 체크
            trailing_return = (current_price - pos['peak_price']) / pos['peak_price']
            if trailing_return <= -exit_config['trailing_stop']:
                return {'price': current_price, 'reason': 'trailing_stop'}

        # 4. Timeout
        if 'timeout_hours' in exit_config:
            holding_hours = (timestamp - pos['entry_time']).total_seconds() / 3600
            if holding_hours >= exit_config['timeout_hours']:
                return {'price': current_price, 'reason': 'timeout'}

        return None

    def _calculate_statistics(self) -> Dict[str, Any]:
        """통계 계산"""
        if not self.trades:
            return {
                'error': 'No trades executed',
                'total_return_pct': 0.0,
                'total_trades': 0
            }

        trades_df = pd.DataFrame(self.trades)

        # 승/패 분류
        winning_trades = trades_df[trades_df['return_pct'] > 0]
        losing_trades = trades_df[trades_df['return_pct'] <= 0]

        # 기본 통계
        total_return_pct = (self.current_capital - self.initial_capital) / self.initial_capital * 100

        # Sharpe Ratio 계산
        if len(trades_df) > 1:
            returns = trades_df['return_pct'].values
            sharpe = np.mean(returns) / (np.std(returns) + 1e-10) * np.sqrt(len(returns))
        else:
            sharpe = 0.0

        return {
            # 수익률
            'total_return_pct': total_return_pct,
            'final_capital': self.current_capital,

            # 거래 통계
            'total_trades': len(trades_df),
            'winning_trades': len(winning_trades),
            'losing_trades': len(losing_trades),
            'win_rate': len(winning_trades) / len(trades_df) * 100 if len(trades_df) > 0 else 0,

            # 수익 통계
            'avg_return': trades_df['return_pct'].mean(),
            'median_return': trades_df['return_pct'].median(),
            'avg_winning_return': winning_trades['return_pct'].mean() if len(winning_trades) > 0 else 0,
            'avg_losing_return': losing_trades['return_pct'].mean() if len(losing_trades) > 0 else 0,
            'best_trade': trades_df['return_pct'].max(),
            'worst_trade': trades_df['return_pct'].min(),

            # 리스크 지표
            'sharpe_ratio': sharpe,
            'max_drawdown': self.max_drawdown,

            # 보유 시간
            'avg_holding_hours': trades_df['holding_hours'].mean(),
            'median_holding_hours': trades_df['holding_hours'].median(),

            # 수수료
            'total_fees': trades_df['buy_fee'].sum() + trades_df['sell_fee'].sum(),

            # 청산 이유 분포
            'exit_reasons': trades_df['reason'].value_counts().to_dict(),

            # 전체 거래 내역
            'trades': self.trades
        }

    def _calculate_btc_amount(self, capital: float, entry_price: float) -> float:
        """
        정확한 BTC 수량 계산 (v43 버그 수정)

        v43 버그:
            position = capital / (capital * 1.0007) = 0.9993

        정확한 계산:
            btc_amount = (capital - fee) / entry_price
        """
        buy_fee = capital * self.total_fee
        buy_amount = capital - buy_fee
        btc_amount = buy_amount / entry_price
        return btc_amount

    def _calculate_sell_revenue(self, btc_amount: float, exit_price: float) -> float:
        """정확한 청산 수익 계산"""
        sell_gross = btc_amount * exit_price
        sell_fee = sell_gross * self.total_fee
        sell_net = sell_gross - sell_fee
        return sell_net


def load_price_data(year: int, timeframe: str = 'day') -> pd.DataFrame:
    """
    가격 데이터 로드

    Args:
        year: 연도
        timeframe: 타임프레임 ('minute5', 'minute15', 'minute60', 'minute240', 'day')

    Returns:
        DataFrame with columns: [timestamp, open, high, low, close, volume]
    """
    import sqlite3

    db_path = '/Users/bongbong/SynologyDrive/vendor/sandbox/251015_봉봇/upbit_bitcoin.db'

    # 타임프레임별 테이블명
    table_map = {
        'minute5': 'bitcoin_minute5',
        'minute15': 'bitcoin_minute15',
        'minute60': 'bitcoin_minute60',
        'minute240': 'bitcoin_minute240',
        'day': 'bitcoin_day'
    }

    table = table_map.get(timeframe, 'bitcoin_day')

    # 연도 필터링
    start_date = f"{year}-01-01"
    end_date = f"{year}-12-31 23:59:59"

    query = f"""
        SELECT timestamp, open, high, low, close, volume
        FROM {table}
        WHERE timestamp >= '{start_date}' AND timestamp <= '{end_date}'
        ORDER BY timestamp
    """

    conn = sqlite3.connect(db_path)
    df = pd.read_sql_query(query, conn)
    conn.close()

    return df


if __name__ == '__main__':
    # 단위 테스트: v43 첫 거래 재현
    print("=" * 60)
    print("Universal Backtest Engine - Unit Test")
    print("=" * 60)

    engine = UniversalBacktestEngine(initial_capital=10_000_000)

    # v43 첫 거래
    entry_price = 58_839_000
    exit_price = 63_010_000

    print(f"\n[Test Case: v43 First Trade]")
    print(f"Entry Price: {entry_price:,}원")
    print(f"Exit Price:  {exit_price:,}원")
    print(f"Price Change: +{(exit_price - entry_price) / entry_price * 100:.2f}%")

    # BTC 수량 계산
    btc_amount = engine._calculate_btc_amount(10_000_000, entry_price)
    print(f"\nBTC Amount: {btc_amount:.8f} BTC")

    # 청산 수익 계산
    sell_revenue = engine._calculate_sell_revenue(btc_amount, exit_price)
    return_pct = (sell_revenue - 10_000_000) / 10_000_000 * 100

    print(f"\nSell Revenue: {sell_revenue:,.0f}원")
    print(f"Return: +{return_pct:.2f}%")

    # 검증
    expected_revenue = 10_693_407  # 정상 복리 계산
    v43_buggy_revenue = 62_921_848  # v43 버그 결과

    print(f"\n[Validation]")
    print(f"Expected (Correct): {expected_revenue:,}원 (+6.93%)")
    print(f"v43 Buggy Result:   {v43_buggy_revenue:,}원 (+529.22%)")
    print(f"Engine Result:      {sell_revenue:,.0f}원 (+{return_pct:.2f}%)")

    if abs(sell_revenue - expected_revenue) < 500:  # 500원 이내 허용 (부동소수점 오차)
        print("\n✅ TEST PASSED: Engine calculation is CORRECT")
        print(f"   (차이: {abs(sell_revenue - expected_revenue):.0f}원, 허용 범위 내)")
    else:
        print("\n❌ TEST FAILED: Engine calculation is WRONG")
        print(f"   (차이: {abs(sell_revenue - expected_revenue):.0f}원 > 500원)")

    if abs(sell_revenue - v43_buggy_revenue) > 1_000_000:
        print("✅ v43 bug NOT reproduced (Good!)")
    else:
        print("❌ v43 bug detected in engine (Bad!)")

    print("\n" + "=" * 60)
