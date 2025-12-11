#!/usr/bin/env python3
"""
layer_strategy.py
개별 레이어 전략 (분할 매수/매도 지원)

특징:
- v04 Simple EMA 크로스 전략 기반
- 3단계 분할 매수 (골든크로스, +5%, +10%)
- 3단계 분할 매도 (+10%, +20%, +30%/트레일링)
- Kelly Criterion 지원
"""

import pandas as pd
import numpy as np
from typing import Dict, Optional


class LayerStrategy:
    """개별 레이어 전략"""

    def __init__(self, layer_name: str, config: dict, kelly_enabled: bool = False):
        """
        Args:
            layer_name: 레이어 이름 (day, minute240, ...)
            config: 레이어 설정
            kelly_enabled: Kelly Criterion 활성화 여부
        """
        self.layer_name = layer_name
        self.config = config
        self.kelly_enabled = kelly_enabled

        # 파라미터
        self.position_fraction = config.get('position_fraction', 0.80)
        self.trailing_stop_pct = config.get('trailing_stop_pct', 0.20)
        self.stop_loss_pct = config.get('stop_loss_pct', 0.15)

        # 분할 매수/매도 설정
        self.split_orders_enabled = config.get('split_orders_enabled', True)

        # 포지션 상태
        self.position = None  # None or 'long'
        self.entry_price = 0.0
        self.entry_idx = 0
        self.highest_price = 0.0
        self.filled_fraction = 0.0  # 현재까지 매수한 비율
        self.sell_fraction = 0.0  # 현재까지 매도한 비율

        # 분할 매수 트리거
        self.buy_splits = [
            {'trigger': 'golden_cross', 'fraction': 0.50, 'triggered': False},
            {'trigger': 'price_up_5pct', 'fraction': 0.30, 'triggered': False},
            {'trigger': 'price_up_10pct', 'fraction': 0.20, 'triggered': False}
        ]

        # 분할 매도 트리거
        self.sell_splits = [
            {'trigger': 'profit_10pct', 'fraction': 0.30, 'triggered': False},
            {'trigger': 'profit_20pct', 'fraction': 0.30, 'triggered': False},
            {'trigger': 'trailing_or_30pct', 'fraction': 1.00, 'triggered': False}
        ]

    def generate_signal(
        self,
        df: pd.DataFrame,
        i: int,
        current_capital: float,
        kelly_fraction: Optional[float] = None
    ) -> Dict:
        """
        신호 생성

        Args:
            df: 데이터프레임
            i: 현재 인덱스
            current_capital: 현재 자본
            kelly_fraction: Kelly Criterion 비율 (0.0 ~ 1.0)

        Returns:
            {'action': 'buy'|'sell'|'hold', 'fraction': float, 'reason': str}
        """
        # 최소 데이터 확보
        if i < 26:
            return {'action': 'hold', 'fraction': 0.0, 'reason': 'insufficient_data'}

        current = df.iloc[i]
        prev = df.iloc[i - 1]

        price = current['close']
        ema12 = current.get('ema_12', price)
        ema26 = current.get('ema_26', price)
        prev_ema12 = prev.get('ema_12', price)
        prev_ema26 = prev.get('ema_26', price)

        # NaN 처리
        if pd.isna(ema12) or pd.isna(ema26):
            return {'action': 'hold', 'fraction': 0.0, 'reason': 'missing_ema'}

        # === 포지션 없을 때: 진입 신호 ===
        if self.position is None:
            golden_cross = (prev_ema12 <= prev_ema26) and (ema12 > ema26)
            already_golden = (ema12 > ema26)

            if golden_cross or already_golden:
                # Kelly Criterion 적용
                if self.kelly_enabled and kelly_fraction is not None:
                    buy_fraction = min(kelly_fraction, self.position_fraction)
                else:
                    buy_fraction = self.position_fraction

                # 분할 매수 활성화된 경우
                if self.split_orders_enabled:
                    # 첫 번째 매수: 50%
                    buy_fraction = self.buy_splits[0]['fraction'] * self.position_fraction
                    self.buy_splits[0]['triggered'] = True
                    self.filled_fraction = self.buy_splits[0]['fraction']

                return {
                    'action': 'buy',
                    'fraction': buy_fraction,
                    'reason': f'golden_cross EMA12({ema12:.0f}) > EMA26({ema26:.0f})'
                }

        # === 포지션 있을 때: 추가 매수 또는 청산 신호 ===
        else:
            # 최고가 갱신
            if price > self.highest_price:
                self.highest_price = price

            # 수익률
            pnl_ratio = (price - self.entry_price) / self.entry_price
            drop_from_high = (self.highest_price - price) / self.highest_price

            # === 분할 매수 체크 (아직 100% 매수 안 했을 때) ===
            if self.split_orders_enabled and self.filled_fraction < 1.0:
                # 2단계 매수: +5% 상승 시 30% 추가
                if not self.buy_splits[1]['triggered'] and pnl_ratio >= 0.05:
                    self.buy_splits[1]['triggered'] = True
                    additional_fraction = self.buy_splits[1]['fraction'] * self.position_fraction
                    self.filled_fraction += self.buy_splits[1]['fraction']
                    return {
                        'action': 'buy',
                        'fraction': additional_fraction,
                        'reason': f'split_buy_2 price_up_5pct PnL={pnl_ratio:.2%}'
                    }

                # 3단계 매수: +10% 상승 시 20% 추가
                if not self.buy_splits[2]['triggered'] and pnl_ratio >= 0.10:
                    self.buy_splits[2]['triggered'] = True
                    additional_fraction = self.buy_splits[2]['fraction'] * self.position_fraction
                    self.filled_fraction += self.buy_splits[2]['fraction']
                    return {
                        'action': 'buy',
                        'fraction': additional_fraction,
                        'reason': f'split_buy_3 price_up_10pct PnL={pnl_ratio:.2%}'
                    }

            # === 청산 조건 1: 데드크로스 (전량 매도) ===
            dead_cross = (prev_ema12 >= prev_ema26) and (ema12 < ema26)
            if dead_cross:
                self._reset_position()
                return {
                    'action': 'sell',
                    'fraction': 1.0,
                    'reason': f'dead_cross EMA12({ema12:.0f}) < EMA26({ema26:.0f}), PnL={pnl_ratio:.2%}'
                }

            # === 청산 조건 2: Stop Loss (전량 매도) ===
            if pnl_ratio <= -self.stop_loss_pct:
                self._reset_position()
                return {
                    'action': 'sell',
                    'fraction': 1.0,
                    'reason': f'stop_loss PnL={pnl_ratio:.2%} <= -{self.stop_loss_pct:.2%}'
                }

            # === 분할 매도 (split_orders 활성화 시) ===
            if self.split_orders_enabled:
                # 1단계 매도: +10% 익절 → 30% 매도
                if not self.sell_splits[0]['triggered'] and pnl_ratio >= 0.10:
                    self.sell_splits[0]['triggered'] = True
                    self.sell_fraction += self.sell_splits[0]['fraction']
                    return {
                        'action': 'sell',
                        'fraction': self.sell_splits[0]['fraction'],
                        'reason': f'split_sell_1 profit_10pct PnL={pnl_ratio:.2%}'
                    }

                # 2단계 매도: +20% 익절 → 30% 매도
                if not self.sell_splits[1]['triggered'] and pnl_ratio >= 0.20:
                    self.sell_splits[1]['triggered'] = True
                    self.sell_fraction += self.sell_splits[1]['fraction']
                    return {
                        'action': 'sell',
                        'fraction': self.sell_splits[1]['fraction'],
                        'reason': f'split_sell_2 profit_20pct PnL={pnl_ratio:.2%}'
                    }

                # 3단계 매도: +30% 익절 또는 Trailing Stop → 전량 매도
                trailing_hit = drop_from_high >= self.trailing_stop_pct
                profit_30pct = pnl_ratio >= 0.30

                if not self.sell_splits[2]['triggered'] and (trailing_hit or profit_30pct):
                    self.sell_splits[2]['triggered'] = True
                    self._reset_position()
                    reason = 'trailing_stop' if trailing_hit else 'profit_30pct'
                    return {
                        'action': 'sell',
                        'fraction': 1.0,
                        'reason': f'split_sell_3 {reason} PnL={pnl_ratio:.2%}, drop={drop_from_high:.2%}'
                    }

            else:
                # 분할 매도 비활성화: v04 로직
                if drop_from_high >= self.trailing_stop_pct:
                    self._reset_position()
                    return {
                        'action': 'sell',
                        'fraction': 1.0,
                        'reason': f'trailing_stop high={self.highest_price:.0f}, drop={drop_from_high:.2%}, PnL={pnl_ratio:.2%}'
                    }

        # 홀드
        return {
            'action': 'hold',
            'fraction': 0.0,
            'reason': f'holding PnL={pnl_ratio:.2%}, high={self.highest_price:.0f}' if self.position else 'no_signal'
        }

    def on_buy(self, idx: int, price: float):
        """매수 체결 시 호출"""
        if self.position is None:
            self.position = 'long'
            self.entry_price = price
            self.entry_idx = idx
            self.highest_price = price
        else:
            # 추가 매수 시 평균 단가 계산 (MultiTimeframeBacktester에서 처리)
            pass

    def on_sell(self, fraction: float):
        """매도 체결 시 호출"""
        if fraction >= 0.99:  # 전량 매도
            self._reset_position()

    def _reset_position(self):
        """포지션 초기화"""
        self.position = None
        self.entry_price = 0.0
        self.entry_idx = 0
        self.highest_price = 0.0
        self.filled_fraction = 0.0
        self.sell_fraction = 0.0

        # 분할 매수/매도 트리거 초기화
        for split in self.buy_splits:
            split['triggered'] = False
        for split in self.sell_splits:
            split['triggered'] = False

    def update_params(self, new_params: Dict):
        """파라미터 동적 업데이트 (Auto-tuning용)"""
        if 'position_fraction' in new_params:
            self.position_fraction = new_params['position_fraction']
        if 'trailing_stop_pct' in new_params:
            self.trailing_stop_pct = new_params['trailing_stop_pct']
        if 'stop_loss_pct' in new_params:
            self.stop_loss_pct = new_params['stop_loss_pct']
