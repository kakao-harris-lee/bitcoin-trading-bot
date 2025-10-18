#!/usr/bin/env python3
"""
multi_timeframe_backtester.py
멀티 타임프레임 동시 백테스팅 엔진

특징:
- 여러 타임프레임 데이터를 동시 처리
- 각 레이어별 독립적 포지션 관리
- DAY 신호 기반 다른 레이어 활성화/비활성화
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Optional
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Position:
    """포지션 정보"""
    layer: str
    entry_time: datetime
    entry_price: float
    quantity: float
    highest_price: float = 0.0
    split_entries: List[Dict] = field(default_factory=list)  # 분할 매수 기록

    def __post_init__(self):
        if self.highest_price == 0.0:
            self.highest_price = self.entry_price


@dataclass
class Trade:
    """거래 기록"""
    layer: str
    entry_time: datetime
    entry_price: float
    quantity: float
    exit_time: Optional[datetime] = None
    exit_price: Optional[float] = None
    profit_loss: Optional[float] = None
    profit_loss_pct: Optional[float] = None
    reason: str = ""


class MultiTimeframeBacktester:
    """멀티 타임프레임 백테스팅 엔진"""

    def __init__(
        self,
        config: Dict,
        initial_capital: float = 10_000_000,
        fee_rate: float = 0.0005,
        slippage: float = 0.0002
    ):
        """
        Args:
            config: 전략 설정
            initial_capital: 초기 자본
            fee_rate: 수수료율
            slippage: 슬리피지
        """
        self.config = config
        self.initial_capital = initial_capital
        self.fee_rate = fee_rate
        self.slippage = slippage

        # 레이어별 자본 할당
        self.layer_capital = {}
        for layer_name, layer_config in config['layers'].items():
            allocation = layer_config['capital_allocation']
            self.layer_capital[layer_name] = initial_capital * allocation

        # 상태 변수
        self.positions: Dict[str, Optional[Position]] = {}  # layer_name -> Position
        self.cash_by_layer: Dict[str, float] = self.layer_capital.copy()
        self.trades: List[Trade] = []
        self.equity_curve: List[Dict] = []

        # DAY 레이어 활성 상태
        self.day_position_active = False

    def reset(self):
        """상태 초기화"""
        self.positions = {layer: None for layer in self.config['layers'].keys()}
        self.cash_by_layer = self.layer_capital.copy()
        self.trades = []
        self.equity_curve = []
        self.day_position_active = False

    def run(
        self,
        dataframes: Dict[str, pd.DataFrame],
        strategy_func,
        strategy_params: Dict = None
    ) -> Dict:
        """
        백테스팅 실행

        Args:
            dataframes: {timeframe: DataFrame} 딕셔너리
            strategy_func: 전략 함수
            strategy_params: 전략 파라미터

        Returns:
            백테스팅 결과
        """
        self.reset()

        if strategy_params is None:
            strategy_params = {}

        # 가장 짧은 타임프레임 기준으로 순회 (minute5)
        # 실제로는 공통 timestamp 기준으로 병합 필요
        primary_tf = self._get_primary_timeframe(dataframes)
        df_primary = dataframes[primary_tf]

        for i in range(len(df_primary)):
            current_time = df_primary.iloc[i]['timestamp']

            # 각 타임프레임의 현재 인덱스 찾기
            tf_indices = {}
            for tf, df in dataframes.items():
                idx = self._find_timestamp_index(df, current_time)
                if idx is not None:
                    tf_indices[tf] = idx

            # 전략 신호 생성
            signals = strategy_func(
                dataframes=dataframes,
                tf_indices=tf_indices,
                current_time=current_time,
                backtester=self,
                params=strategy_params
            )

            # 신호 실행
            if signals:
                self._execute_signals(signals, dataframes, tf_indices, current_time)

            # Equity curve 기록
            self._record_equity(dataframes, tf_indices, current_time)

        # 마지막 포지션 정리
        self._close_all_positions(dataframes, current_time)

        return self._generate_results()

    def _get_primary_timeframe(self, dataframes: Dict[str, pd.DataFrame]) -> str:
        """가장 세밀한 타임프레임 반환"""
        # minute5 > minute15 > ... > day 순
        tf_priority = ['minute5', 'minute15', 'minute30', 'minute60', 'minute240', 'day']
        for tf in tf_priority:
            if tf in dataframes:
                return tf
        return list(dataframes.keys())[0]

    def _find_timestamp_index(self, df: pd.DataFrame, timestamp: pd.Timestamp) -> Optional[int]:
        """특정 timestamp에 해당하는 인덱스 찾기"""
        # timestamp 이하의 가장 최근 데이터
        mask = df['timestamp'] <= timestamp
        if mask.any():
            return mask[::-1].idxmax()  # 마지막 True 인덱스
        return None

    def _execute_signals(
        self,
        signals: List[Dict],
        dataframes: Dict[str, pd.DataFrame],
        tf_indices: Dict[str, int],
        current_time: pd.Timestamp
    ):
        """신호 실행"""
        for signal in signals:
            layer = signal['layer']
            action = signal['action']
            fraction = signal.get('fraction', 1.0)

            if layer not in self.config['layers']:
                continue

            # 해당 레이어의 현재 가격
            tf = self.config['layers'][layer]['timeframe']
            if tf not in tf_indices:
                continue

            idx = tf_indices[tf]
            price = dataframes[tf].iloc[idx]['close']

            # 매수/매도 실행
            if action == 'buy':
                self._execute_buy(layer, current_time, price, fraction, signal.get('reason', ''))
            elif action == 'sell':
                self._execute_sell(layer, current_time, price, fraction, signal.get('reason', ''))

            # DAY 레이어 상태 업데이트
            if layer == 'day':
                self.day_position_active = (self.positions['day'] is not None)

    def _execute_buy(
        self,
        layer: str,
        timestamp: datetime,
        price: float,
        fraction: float,
        reason: str
    ):
        """매수 실행"""
        available_cash = self.cash_by_layer[layer] * fraction

        if available_cash < 10_000:  # 최소 주문 금액
            return

        # 슬리피지 적용
        execution_price = price * (1 + self.slippage)

        # 수수료 포함 구매 수량
        quantity = available_cash / (execution_price * (1 + self.fee_rate))
        cost = quantity * execution_price * (1 + self.fee_rate)

        if cost > self.cash_by_layer[layer]:
            return

        # 매수 실행
        self.cash_by_layer[layer] -= cost

        # 포지션 생성 또는 업데이트
        if self.positions[layer] is None:
            self.positions[layer] = Position(
                layer=layer,
                entry_time=timestamp,
                entry_price=execution_price,
                quantity=quantity,
                highest_price=execution_price
            )
        else:
            # 분할 매수
            pos = self.positions[layer]
            pos.split_entries.append({
                'time': timestamp,
                'price': execution_price,
                'quantity': quantity
            })
            # 평균 매수가 계산
            total_cost = pos.entry_price * pos.quantity + execution_price * quantity
            pos.quantity += quantity
            pos.entry_price = total_cost / pos.quantity

    def _execute_sell(
        self,
        layer: str,
        timestamp: datetime,
        price: float,
        fraction: float,
        reason: str
    ):
        """매도 실행"""
        if self.positions[layer] is None:
            return

        pos = self.positions[layer]
        sell_quantity = pos.quantity * fraction

        # 슬리피지 적용
        execution_price = price * (1 - self.slippage)

        # 수수료 차감 후 수령 금액
        proceeds = sell_quantity * execution_price * (1 - self.fee_rate)

        if proceeds < 10_000:
            return

        # 매도 실행
        self.cash_by_layer[layer] += proceeds

        # 거래 기록
        pnl = (execution_price - pos.entry_price) * sell_quantity
        pnl_pct = ((execution_price - pos.entry_price) / pos.entry_price) * 100

        trade = Trade(
            layer=layer,
            entry_time=pos.entry_time,
            entry_price=pos.entry_price,
            quantity=sell_quantity,
            exit_time=timestamp,
            exit_price=execution_price,
            profit_loss=pnl,
            profit_loss_pct=pnl_pct,
            reason=reason
        )
        self.trades.append(trade)

        # 포지션 업데이트
        pos.quantity -= sell_quantity
        if pos.quantity < 0.0001:  # 전량 매도
            self.positions[layer] = None

    def _record_equity(
        self,
        dataframes: Dict[str, pd.DataFrame],
        tf_indices: Dict[str, int],
        current_time: pd.Timestamp
    ):
        """Equity curve 기록"""
        total_cash = sum(self.cash_by_layer.values())
        total_position_value = 0.0

        for layer, pos in self.positions.items():
            if pos is not None:
                tf = self.config['layers'][layer]['timeframe']
                if tf in tf_indices:
                    idx = tf_indices[tf]
                    price = dataframes[tf].iloc[idx]['close']
                    total_position_value += pos.quantity * price

                    # 최고가 갱신
                    if price > pos.highest_price:
                        pos.highest_price = price

        self.equity_curve.append({
            'timestamp': current_time,
            'cash': total_cash,
            'position_value': total_position_value,
            'total_equity': total_cash + total_position_value
        })

    def _close_all_positions(
        self,
        dataframes: Dict[str, pd.DataFrame],
        current_time: pd.Timestamp
    ):
        """모든 포지션 청산"""
        for layer, pos in self.positions.items():
            if pos is not None:
                tf = self.config['layers'][layer]['timeframe']
                df = dataframes[tf]
                last_price = df.iloc[-1]['close']
                self._execute_sell(layer, current_time, last_price, 1.0, 'force_close')

    def _generate_results(self) -> Dict:
        """결과 생성"""
        df_equity = pd.DataFrame(self.equity_curve)
        final_equity = df_equity.iloc[-1]['total_equity'] if len(df_equity) > 0 else self.initial_capital
        total_return = ((final_equity - self.initial_capital) / self.initial_capital) * 100

        # 레이어별 통계
        layer_stats = {}
        for layer in self.config['layers'].keys():
            layer_trades = [t for t in self.trades if t.layer == layer]
            if layer_trades:
                winning = [t for t in layer_trades if t.profit_loss > 0]
                losing = [t for t in layer_trades if t.profit_loss <= 0]

                layer_stats[layer] = {
                    'total_trades': len(layer_trades),
                    'winning_trades': len(winning),
                    'losing_trades': len(losing),
                    'win_rate': len(winning) / len(layer_trades) if layer_trades else 0,
                    'total_pnl': sum(t.profit_loss for t in layer_trades),
                    'avg_profit': np.mean([t.profit_loss for t in winning]) if winning else 0,
                    'avg_loss': abs(np.mean([t.profit_loss for t in losing])) if losing else 0
                }

        # 전체 통계
        if self.trades:
            winning_trades = [t for t in self.trades if t.profit_loss > 0]
            losing_trades = [t for t in self.trades if t.profit_loss <= 0]

            win_rate = len(winning_trades) / len(self.trades)
            avg_profit = np.mean([t.profit_loss for t in winning_trades]) if winning_trades else 0
            avg_loss = abs(np.mean([t.profit_loss for t in losing_trades])) if losing_trades else 0

            total_profit = sum(t.profit_loss for t in winning_trades)
            total_loss = abs(sum(t.profit_loss for t in losing_trades))
            profit_factor = total_profit / total_loss if total_loss > 0 else 0
        else:
            win_rate = avg_profit = avg_loss = profit_factor = 0
            winning_trades = losing_trades = []

        return {
            'initial_capital': self.initial_capital,
            'final_capital': final_equity,
            'total_return': total_return,
            'total_trades': len(self.trades),
            'winning_trades': len(winning_trades),
            'losing_trades': len(losing_trades),
            'win_rate': win_rate,
            'avg_profit': avg_profit,
            'avg_loss': avg_loss,
            'profit_factor': profit_factor,
            'trades': self.trades,
            'equity_curve': df_equity,
            'layer_stats': layer_stats
        }
