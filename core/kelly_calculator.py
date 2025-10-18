#!/usr/bin/env python3
"""
kelly_calculator.py
Kelly Criterion 계산 모듈
"""

from typing import List, Tuple
import numpy as np

class KellyCalculator:
    """Kelly Criterion 계산기"""

    @staticmethod
    def calculate(win_rate: float, avg_win: float, avg_loss: float) -> float:
        """
        Kelly Criterion 계산

        Formula: f* = (p * b - q) / b
        where:
            p = 승률 (win_rate)
            q = 1 - p (패배율)
            b = avg_win / avg_loss (승/패 비율)

        Args:
            win_rate: 승률 (0.0 ~ 1.0)
            avg_win: 평균 수익 (%)
            avg_loss: 평균 손실 (%, 양수값)

        Returns:
            Kelly 비율 (0.0 ~ 1.0)
        """
        if win_rate <= 0 or win_rate >= 1:
            return 0.0

        if avg_win <= 0 or avg_loss <= 0:
            return 0.0

        p = win_rate
        q = 1 - p
        b = avg_win / avg_loss

        kelly = (p * b - q) / b

        # Kelly 값이 음수면 배팅하지 않음
        return max(0.0, min(kelly, 1.0))

    @staticmethod
    def fractional_kelly(kelly: float, fraction: float = 0.25) -> float:
        """
        Fractional Kelly (보수적 접근)

        Args:
            kelly: Kelly Criterion 값
            fraction: 분수 (기본 0.25 = Quarter Kelly)

        Returns:
            조정된 Kelly 비율
        """
        return kelly * fraction

    @staticmethod
    def from_trades(trades: List[dict]) -> Tuple[float, dict]:
        """
        거래 기록으로부터 Kelly Criterion 계산

        Args:
            trades: 거래 기록 리스트
                [{"profit_loss_pct": 5.2}, {"profit_loss_pct": -2.1}, ...]

        Returns:
            (kelly_ratio, stats_dict) 튜플
        """
        if not trades:
            return 0.0, {}

        profits = [t["profit_loss_pct"] for t in trades]
        winning_trades = [p for p in profits if p > 0]
        losing_trades = [abs(p) for p in profits if p < 0]

        if not winning_trades or not losing_trades:
            return 0.0, {
                "win_rate": len(winning_trades) / len(trades),
                "avg_win": np.mean(winning_trades) if winning_trades else 0,
                "avg_loss": np.mean(losing_trades) if losing_trades else 0,
                "total_trades": len(trades)
            }

        win_rate = len(winning_trades) / len(trades)
        avg_win = np.mean(winning_trades)
        avg_loss = np.mean(losing_trades)

        kelly = KellyCalculator.calculate(win_rate, avg_win, avg_loss)

        stats = {
            "win_rate": win_rate,
            "avg_win": avg_win,
            "avg_loss": avg_loss,
            "total_trades": len(trades),
            "kelly_full": kelly,
            "kelly_quarter": KellyCalculator.fractional_kelly(kelly, 0.25),
            "kelly_half": KellyCalculator.fractional_kelly(kelly, 0.5)
        }

        return kelly, stats


# 사용 예제
if __name__ == "__main__":
    # 예제 거래 기록
    trades = [
        {"profit_loss_pct": 5.2},
        {"profit_loss_pct": -2.1},
        {"profit_loss_pct": 3.8},
        {"profit_loss_pct": -1.5},
        {"profit_loss_pct": 7.1},
        {"profit_loss_pct": -2.8},
    ]

    kelly, stats = KellyCalculator.from_trades(trades)

    print("✅ Kelly Criterion 계산 결과:")
    print(f"   승률: {stats['win_rate']:.1%}")
    print(f"   평균 수익: {stats['avg_win']:.2f}%")
    print(f"   평균 손실: {stats['avg_loss']:.2f}%")
    print(f"   Full Kelly: {stats['kelly_full']:.1%}")
    print(f"   Quarter Kelly: {stats['kelly_quarter']:.1%} (권장)")
