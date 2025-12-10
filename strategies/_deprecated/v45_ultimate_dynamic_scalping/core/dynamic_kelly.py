#!/usr/bin/env python3
"""
Dynamic Kelly Criterion Calculator
최근 거래 기반으로 Kelly% 동적 계산
"""

import numpy as np
from typing import List, Dict, Optional


class DynamicKellyCriterion:
    """
    동적 Kelly Criterion 계산기
    - 최근 N거래 기반 승률, 손익비 계산
    - 시장 상태별 조정
    - 안전 범위 제한
    """

    def __init__(self, config: Dict):
        """
        Args:
            config: 설정 dict
        """
        self.enabled = config.get('enabled', True)
        self.lookback_trades = config.get('lookback_trades', 50)
        self.min_trades_required = config.get('min_trades_required', 20)
        self.method = config.get('method', 'half_kelly')
        self.kelly_min = config.get('range', {}).get('min', 0.30)
        self.kelly_max = config.get('range', {}).get('max', 0.98)
        self.initial_kelly = config.get('initial_kelly', 0.50)

        # 시장 상태별 조정 승수
        self.regime_adjustments = config.get('regime_adjustments', {
            'BULL_STRONG': 1.2,
            'BULL_MODERATE': 1.1,
            'SIDEWAYS_UP': 1.0,
            'SIDEWAYS_FLAT': 0.9,
            'SIDEWAYS_DOWN': 0.8,
            'BEAR_MODERATE': 0.7,
            'BEAR_STRONG': 0.6
        })

    def calculate(self, trade_history: List[Dict], market_regime: Optional[str] = None) -> float:
        """
        Kelly Criterion 계산

        Args:
            trade_history: 거래 이력
            market_regime: 시장 상태 (선택)

        Returns:
            Kelly 비율 (0.0-1.0)
        """
        # enabled=false면 initial_kelly 반환 (v43 복제용)
        if not self.enabled:
            return self.initial_kelly

        # 거래 이력 부족 시 초기값
        if len(trade_history) < self.min_trades_required:
            kelly = self.initial_kelly
        else:
            # 최근 N거래만 사용
            recent_trades = trade_history[-self.lookback_trades:]
            kelly = self._calculate_kelly_from_trades(recent_trades)

        # 시장 상태별 조정
        if market_regime and market_regime in self.regime_adjustments:
            adjustment = self.regime_adjustments[market_regime]
            kelly *= adjustment

        # 범위 제한
        kelly = np.clip(kelly, self.kelly_min, self.kelly_max)

        return kelly

    def _calculate_kelly_from_trades(self, trades: List[Dict]) -> float:
        """
        거래 이력에서 Kelly% 계산

        Kelly Formula: K = W - (1-W)/R
        - W: 승률 (Win Rate)
        - R: 손익비 (Win/Loss Ratio)

        Half-Kelly: K/2 (안전)
        """
        if not trades:
            return self.initial_kelly

        returns = [t['return_pct'] for t in trades]

        # 승률 계산
        wins = [r for r in returns if r > 0]
        win_rate = len(wins) / len(returns) if returns else 0.5

        # 손익비 계산
        avg_win = np.mean(wins) if wins else 0.01
        losses = [r for r in returns if r < 0]
        avg_loss = abs(np.mean(losses)) if losses else 0.01

        if avg_loss == 0:
            avg_loss = 0.01  # 0 나누기 방지

        win_loss_ratio = avg_win / avg_loss

        # Kelly Formula
        if win_loss_ratio > 0:
            kelly_full = win_rate - (1 - win_rate) / win_loss_ratio
        else:
            kelly_full = 0.0

        # Half-Kelly (안전)
        if self.method == 'half_kelly':
            kelly = kelly_full * 0.5
        elif self.method == 'quarter_kelly':
            kelly = kelly_full * 0.25
        else:
            kelly = kelly_full

        # 음수 Kelly 처리 (불리한 게임)
        if kelly < 0:
            kelly = self.kelly_min

        return kelly

    def get_kelly_stats(self, trade_history: List[Dict]) -> Dict:
        """Kelly 계산 상세 정보 반환"""
        if len(trade_history) < self.min_trades_required:
            return {
                'kelly': self.initial_kelly,
                'win_rate': 0.0,
                'avg_win': 0.0,
                'avg_loss': 0.0,
                'win_loss_ratio': 0.0,
                'status': 'insufficient_data'
            }

        recent_trades = trade_history[-self.lookback_trades:]
        returns = [t['return_pct'] for t in recent_trades]

        wins = [r for r in returns if r > 0]
        losses = [r for r in returns if r < 0]

        win_rate = len(wins) / len(returns) if returns else 0.0
        avg_win = np.mean(wins) if wins else 0.0
        avg_loss = abs(np.mean(losses)) if losses else 0.01
        win_loss_ratio = avg_win / avg_loss if avg_loss > 0 else 0.0

        kelly_full = win_rate - (1 - win_rate) / win_loss_ratio if win_loss_ratio > 0 else 0.0
        kelly = kelly_full * 0.5 if self.method == 'half_kelly' else kelly_full

        return {
            'kelly': kelly,
            'kelly_full': kelly_full,
            'win_rate': win_rate,
            'avg_win': avg_win,
            'avg_loss': avg_loss,
            'win_loss_ratio': win_loss_ratio,
            'trades_used': len(recent_trades),
            'status': 'calculated'
        }


# 테스트 코드
if __name__ == "__main__":
    print("=" * 80)
    print("Dynamic Kelly Criterion 테스트")
    print("=" * 80)

    config = {
        'lookback_trades': 50,
        'min_trades_required': 20,
        'method': 'half_kelly',
        'range': {'min': 0.30, 'max': 0.98},
        'initial_kelly': 0.50,
        'regime_adjustments': {
            'BULL_STRONG': 1.2,
            'BEAR_STRONG': 0.6
        }
    }

    calculator = DynamicKellyCriterion(config)

    # 시뮬레이션 거래 이력 생성
    np.random.seed(42)

    print("\n시나리오 1: 초기 단계 (10거래)")
    print("-" * 80)
    trades = []
    for i in range(10):
        trades.append({'return_pct': np.random.normal(0.02, 0.05)})

    kelly = calculator.calculate(trades)
    stats = calculator.get_kelly_stats(trades)
    print(f"Kelly: {kelly:.2%}")
    print(f"상태: {stats['status']}")

    print("\n시나리오 2: 좋은 성과 (50거래, 승률 60%, 손익비 2.0)")
    print("-" * 80)
    trades = []
    for i in range(50):
        if np.random.random() < 0.6:  # 60% 승률
            trades.append({'return_pct': np.random.normal(0.04, 0.02)})  # 평균 4% 수익
        else:
            trades.append({'return_pct': np.random.normal(-0.02, 0.01)})  # 평균 -2% 손실

    kelly = calculator.calculate(trades)
    stats = calculator.get_kelly_stats(trades)
    print(f"Kelly: {kelly:.2%}")
    print(f"승률: {stats['win_rate']:.2%}")
    print(f"평균 수익: {stats['avg_win']:.2%}")
    print(f"평균 손실: {stats['avg_loss']:.2%}")
    print(f"손익비: {stats['win_loss_ratio']:.2f}")
    print(f"Full Kelly: {stats['kelly_full']:.2%}")

    print("\n시나리오 3: 나쁜 성과 (50거래, 승률 30%, 손익비 0.8)")
    print("-" * 80)
    trades = []
    for i in range(50):
        if np.random.random() < 0.3:  # 30% 승률
            trades.append({'return_pct': np.random.normal(0.02, 0.01)})  # 평균 2% 수익
        else:
            trades.append({'return_pct': np.random.normal(-0.025, 0.01)})  # 평균 -2.5% 손실

    kelly = calculator.calculate(trades)
    stats = calculator.get_kelly_stats(trades)
    print(f"Kelly: {kelly:.2%}")
    print(f"승률: {stats['win_rate']:.2%}")
    print(f"손익비: {stats['win_loss_ratio']:.2f}")

    print("\n시나리오 4: 시장 상태별 조정")
    print("-" * 80)
    # 좋은 성과 거래 이력 재사용
    trades = []
    for i in range(50):
        if np.random.random() < 0.6:
            trades.append({'return_pct': np.random.normal(0.04, 0.02)})
        else:
            trades.append({'return_pct': np.random.normal(-0.02, 0.01)})

    kelly_bull = calculator.calculate(trades, market_regime='BULL_STRONG')
    kelly_neutral = calculator.calculate(trades, market_regime=None)
    kelly_bear = calculator.calculate(trades, market_regime='BEAR_STRONG')

    print(f"BULL_STRONG: {kelly_bull:.2%} (+20% 조정)")
    print(f"중립:        {kelly_neutral:.2%}")
    print(f"BEAR_STRONG: {kelly_bear:.2%} (-40% 조정)")

    print("\n" + "=" * 80)
    print("테스트 완료")
    print("=" * 80)
