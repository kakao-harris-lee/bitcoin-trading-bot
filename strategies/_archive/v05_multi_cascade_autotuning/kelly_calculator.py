#!/usr/bin/env python3
"""
kelly_calculator.py
Kelly Criterion 계산 및 포지션 사이징

공식:
Kelly = (승률 × 평균이익 - 패배율 × 평균손실) / 평균이익
     = (W × R - L) / R

W = Win Rate (승률)
L = Loss Rate (패배율) = 1 - W
R = Average Win / Average Loss (승패비)

보수적 Kelly: Kelly × 0.5 (과도한 레버리지 방지)
"""

import numpy as np
from typing import List, Dict, Optional


class KellyCalculator:
    """Kelly Criterion 계산기"""

    def __init__(
        self,
        min_trades: int = 10,
        conservative_fraction: float = 0.5,
        max_position: float = 0.95,
        min_position: float = 0.20
    ):
        """
        Args:
            min_trades: Kelly 활성화 최소 거래 수
            conservative_fraction: Kelly 보수적 적용 비율
            max_position: 최대 포지션 비율
            min_position: 최소 포지션 비율
        """
        self.min_trades = min_trades
        self.conservative_fraction = conservative_fraction
        self.max_position = max_position
        self.min_position = min_position

    def calculate_kelly(self, trades: List[Dict]) -> Optional[float]:
        """
        Kelly Criterion 계산

        Args:
            trades: 거래 목록 [{'profit_loss': float, 'profit_loss_pct': float}, ...]

        Returns:
            Kelly fraction (0.0 ~ 1.0) 또는 None (계산 불가)
        """
        if len(trades) < self.min_trades:
            return None

        # 승리/패배 거래 분리
        winning_trades = [t for t in trades if t.get('profit_loss', 0) > 0]
        losing_trades = [t for t in trades if t.get('profit_loss', 0) <= 0]

        if not winning_trades or not losing_trades:
            return None  # 승리 또는 패배만 있는 경우 계산 불가

        # 승률
        win_rate = len(winning_trades) / len(trades)
        loss_rate = 1 - win_rate

        # 평균 승리/손실 (절대값)
        avg_win = np.mean([abs(t['profit_loss']) for t in winning_trades])
        avg_loss = np.mean([abs(t['profit_loss']) for t in losing_trades])

        if avg_loss == 0:
            return None

        # 승패비
        win_loss_ratio = avg_win / avg_loss

        # Kelly Fraction 계산
        kelly = (win_rate * win_loss_ratio - loss_rate) / win_loss_ratio

        # 보수적 적용
        kelly_conservative = kelly * self.conservative_fraction

        # 범위 제한
        kelly_final = np.clip(kelly_conservative, self.min_position, self.max_position)

        return kelly_final

    def calculate_kelly_by_layer(self, trades_by_layer: Dict[str, List[Dict]]) -> Dict[str, Optional[float]]:
        """
        레이어별 Kelly Criterion 계산

        Args:
            trades_by_layer: {layer_name: [trades]}

        Returns:
            {layer_name: kelly_fraction}
        """
        kelly_by_layer = {}

        for layer, trades in trades_by_layer.items():
            kelly_by_layer[layer] = self.calculate_kelly(trades)

        return kelly_by_layer

    def get_position_fraction(
        self,
        trades: List[Dict],
        default_fraction: float = 0.80
    ) -> float:
        """
        포지션 비율 반환 (Kelly 또는 기본값)

        Args:
            trades: 거래 목록
            default_fraction: Kelly 계산 불가 시 기본값

        Returns:
            포지션 비율 (0.0 ~ 1.0)
        """
        kelly = self.calculate_kelly(trades)

        if kelly is None:
            return default_fraction

        return kelly

    @staticmethod
    def expected_growth_rate(kelly: float, win_rate: float, win_loss_ratio: float) -> float:
        """
        예상 성장률 계산 (이론적)

        Args:
            kelly: Kelly fraction
            win_rate: 승률
            win_loss_ratio: 승패비 (평균 승리 / 평균 손실)

        Returns:
            예상 성장률 (per trade)
        """
        loss_rate = 1 - win_rate

        # Geometric Growth Rate
        growth = win_rate * np.log(1 + kelly * win_loss_ratio) + \
                 loss_rate * np.log(1 - kelly)

        return growth

    def analyze_kelly(self, trades: List[Dict]) -> Dict:
        """
        Kelly 분석 리포트

        Args:
            trades: 거래 목록

        Returns:
            분석 결과 딕셔너리
        """
        if len(trades) < self.min_trades:
            return {
                'kelly_available': False,
                'reason': f'Not enough trades ({len(trades)} < {self.min_trades})'
            }

        winning_trades = [t for t in trades if t.get('profit_loss', 0) > 0]
        losing_trades = [t for t in trades if t.get('profit_loss', 0) <= 0]

        if not winning_trades or not losing_trades:
            return {
                'kelly_available': False,
                'reason': 'Only winning or losing trades exist'
            }

        win_rate = len(winning_trades) / len(trades)
        avg_win = np.mean([abs(t['profit_loss']) for t in winning_trades])
        avg_loss = np.mean([abs(t['profit_loss']) for t in losing_trades])
        win_loss_ratio = avg_win / avg_loss

        kelly_raw = (win_rate * win_loss_ratio - (1 - win_rate)) / win_loss_ratio
        kelly_conservative = kelly_raw * self.conservative_fraction
        kelly_final = np.clip(kelly_conservative, self.min_position, self.max_position)

        expected_growth = self.expected_growth_rate(kelly_final, win_rate, win_loss_ratio)

        return {
            'kelly_available': True,
            'total_trades': len(trades),
            'win_rate': win_rate,
            'avg_win': avg_win,
            'avg_loss': avg_loss,
            'win_loss_ratio': win_loss_ratio,
            'kelly_raw': kelly_raw,
            'kelly_conservative': kelly_conservative,
            'kelly_final': kelly_final,
            'expected_growth_per_trade': expected_growth,
            'recommendation': self._get_recommendation(kelly_final, win_rate)
        }

    def _get_recommendation(self, kelly: float, win_rate: float) -> str:
        """Kelly 값 기반 추천"""
        if kelly >= 0.80:
            return "Very Strong: High win rate and good win/loss ratio"
        elif kelly >= 0.60:
            return "Strong: Favorable edge"
        elif kelly >= 0.40:
            return "Moderate: Positive edge"
        elif kelly >= 0.20:
            return "Weak: Small edge, reduce position size"
        else:
            return "Very Weak: Consider revising strategy"


# 사용 예제
if __name__ == "__main__":
    # 샘플 거래 데이터
    sample_trades = [
        {'profit_loss': 100000, 'profit_loss_pct': 5.0},
        {'profit_loss': -50000, 'profit_loss_pct': -2.5},
        {'profit_loss': 150000, 'profit_loss_pct': 7.5},
        {'profit_loss': -30000, 'profit_loss_pct': -1.5},
        {'profit_loss': 200000, 'profit_loss_pct': 10.0},
        {'profit_loss': -70000, 'profit_loss_pct': -3.5},
        {'profit_loss': 120000, 'profit_loss_pct': 6.0},
        {'profit_loss': 180000, 'profit_loss_pct': 9.0},
        {'profit_loss': -40000, 'profit_loss_pct': -2.0},
        {'profit_loss': 160000, 'profit_loss_pct': 8.0},
    ]

    kelly_calc = KellyCalculator()

    # Kelly 계산
    kelly_fraction = kelly_calc.calculate_kelly(sample_trades)
    print(f"Kelly Fraction: {kelly_fraction:.2%}")

    # 상세 분석
    analysis = kelly_calc.analyze_kelly(sample_trades)
    print("\n=== Kelly Analysis ===")
    for key, value in analysis.items():
        if isinstance(value, float):
            print(f"{key}: {value:.4f}")
        else:
            print(f"{key}: {value}")
