#!/usr/bin/env python3
"""
Reproduction Rate Calculator
완벽한 시그널 재현율 계산 유틸리티
"""

import pandas as pd
from typing import Dict, Tuple
from datetime import timedelta


class ReproductionCalculator:
    """재현율 계산기"""

    def __init__(self, tolerance_days: int = 1):
        """
        Args:
            tolerance_days: 시그널 매칭 허용 오차 (±일)
        """
        self.tolerance_days = tolerance_days

    def calculate_reproduction_rate(
        self,
        strategy_signals: pd.DataFrame,
        perfect_signals: pd.DataFrame,
        strategy_return: float,
        perfect_return: float
    ) -> Dict:
        """
        재현율 계산

        Args:
            strategy_signals: 전략 시그널 DataFrame (timestamp 필수)
            perfect_signals: 완벽한 시그널 DataFrame (timestamp 필수)
            strategy_return: 전략 수익률 (e.g., 0.15 = 15%)
            perfect_return: 완벽한 정답 수익률 (e.g., 0.23 = 23%)

        Returns:
            {
                'signal_reproduction_rate': 시그널 재현율 (0-1),
                'return_reproduction_rate': 수익 재현율 (0-1),
                'total_reproduction_rate': 종합 재현율 (0-1),
                'tier': 'S', 'A', 'B', 'C',
                'matched_signals': 매칭된 시그널 수,
                'total_strategy_signals': 전략 총 시그널 수,
                'total_perfect_signals': 완벽한 정답 총 시그널 수,
                'strategy_return': 전략 수익률,
                'perfect_return': 완벽한 정답 수익률
            }
        """
        # 시그널 재현율 계산
        matched_count = self._match_signals(
            strategy_signals['timestamp'],
            perfect_signals['timestamp']
        )

        signal_rate = matched_count / len(perfect_signals) if len(perfect_signals) > 0 else 0

        # 수익 재현율 계산
        if perfect_return > 0:
            return_rate = min(strategy_return / perfect_return, 1.0)
        else:
            return_rate = 0

        # 종합 재현율 (가중 평균)
        total_rate = (signal_rate * 0.4) + (return_rate * 0.6)

        # Tier 분류
        tier = self._classify_tier(total_rate)

        return {
            'signal_reproduction_rate': signal_rate,
            'return_reproduction_rate': return_rate,
            'total_reproduction_rate': total_rate,
            'tier': tier,
            'matched_signals': matched_count,
            'total_strategy_signals': len(strategy_signals),
            'total_perfect_signals': len(perfect_signals),
            'strategy_return': strategy_return,
            'perfect_return': perfect_return
        }

    def _match_signals(
        self,
        strategy_timestamps: pd.Series,
        perfect_timestamps: pd.Series
    ) -> int:
        """
        시그널 매칭 (±tolerance_days 허용)

        Args:
            strategy_timestamps: 전략 시그널 타임스탬프
            perfect_timestamps: 완벽한 시그널 타임스탬프

        Returns:
            매칭된 시그널 수
        """
        matched_count = 0
        tolerance = timedelta(days=self.tolerance_days)

        # 효율을 위해 set으로 변환
        strategy_set = set(strategy_timestamps)

        for perfect_ts in perfect_timestamps:
            # ±tolerance_days 범위 체크
            for delta_days in range(-self.tolerance_days, self.tolerance_days + 1):
                check_ts = perfect_ts + timedelta(days=delta_days)

                if check_ts in strategy_set:
                    matched_count += 1
                    break  # 중복 카운트 방지

        return matched_count

    def _classify_tier(self, total_rate: float) -> str:
        """
        Tier 분류

        Args:
            total_rate: 종합 재현율 (0-1)

        Returns:
            'S', 'A', 'B', 'C'
        """
        if total_rate >= 0.70:
            return 'S'
        elif total_rate >= 0.50:
            return 'A'
        elif total_rate >= 0.30:
            return 'B'
        else:
            return 'C'

    def calculate_multi_timeframe_reproduction(
        self,
        results_by_timeframe: Dict[str, Dict]
    ) -> Dict:
        """
        멀티 타임프레임 통합 재현율 계산

        Args:
            results_by_timeframe: {
                'day': {재현율 결과},
                'minute60': {재현율 결과},
                ...
            }

        Returns:
            통합 재현율 결과
        """
        if not results_by_timeframe:
            return {}

        # 가중 평균 (day > minute60 > minute240 > minute15 > minute5)
        weights = {
            'day': 0.30,
            'minute60': 0.25,
            'minute240': 0.20,
            'minute15': 0.15,
            'minute5': 0.10
        }

        total_signal_rate = 0
        total_return_rate = 0
        total_weight = 0

        for tf, result in results_by_timeframe.items():
            weight = weights.get(tf, 0.10)
            total_signal_rate += result['signal_reproduction_rate'] * weight
            total_return_rate += result['return_reproduction_rate'] * weight
            total_weight += weight

        # 정규화
        if total_weight > 0:
            avg_signal_rate = total_signal_rate / total_weight
            avg_return_rate = total_return_rate / total_weight
        else:
            avg_signal_rate = 0
            avg_return_rate = 0

        total_rate = (avg_signal_rate * 0.4) + (avg_return_rate * 0.6)
        tier = self._classify_tier(total_rate)

        return {
            'timeframes': results_by_timeframe,
            'weighted_signal_rate': avg_signal_rate,
            'weighted_return_rate': avg_return_rate,
            'total_reproduction_rate': total_rate,
            'tier': tier
        }


if __name__ == '__main__':
    # 테스트
    import pandas as pd
    from datetime import datetime

    # 샘플 데이터
    perfect_signals = pd.DataFrame({
        'timestamp': pd.to_datetime([
            '2024-01-01', '2024-02-01', '2024-03-01', '2024-04-01', '2024-05-01'
        ])
    })

    # 시나리오 1: 높은 재현율 (80%)
    strategy_signals_good = pd.DataFrame({
        'timestamp': pd.to_datetime([
            '2024-01-01', '2024-02-02', '2024-03-01', '2024-04-01'  # 4/5 매칭
        ])
    })

    # 시나리오 2: 낮은 재현율 (40%)
    strategy_signals_bad = pd.DataFrame({
        'timestamp': pd.to_datetime([
            '2024-01-01', '2024-02-15'  # 2/5 매칭
        ])
    })

    calc = ReproductionCalculator(tolerance_days=1)

    # 테스트 1: 좋은 재현율
    print("📊 Test 1: Good Reproduction (4/5 signals, 20% vs 25% return)")
    result_good = calc.calculate_reproduction_rate(
        strategy_signals=strategy_signals_good,
        perfect_signals=perfect_signals,
        strategy_return=0.20,  # 20%
        perfect_return=0.25    # 25%
    )

    print(f"  Signal Reproduction: {result_good['signal_reproduction_rate']:.2%}")
    print(f"  Return Reproduction: {result_good['return_reproduction_rate']:.2%}")
    print(f"  Total Reproduction: {result_good['total_reproduction_rate']:.2%}")
    print(f"  Tier: {result_good['tier']}")
    print(f"  Matched: {result_good['matched_signals']}/{result_good['total_perfect_signals']}")

    # 테스트 2: 나쁜 재현율
    print("\n📊 Test 2: Bad Reproduction (2/5 signals, 10% vs 25% return)")
    result_bad = calc.calculate_reproduction_rate(
        strategy_signals=strategy_signals_bad,
        perfect_signals=perfect_signals,
        strategy_return=0.10,  # 10%
        perfect_return=0.25    # 25%
    )

    print(f"  Signal Reproduction: {result_bad['signal_reproduction_rate']:.2%}")
    print(f"  Return Reproduction: {result_bad['return_reproduction_rate']:.2%}")
    print(f"  Total Reproduction: {result_bad['total_reproduction_rate']:.2%}")
    print(f"  Tier: {result_bad['tier']}")
    print(f"  Matched: {result_bad['matched_signals']}/{result_bad['total_perfect_signals']}")

    # 테스트 3: 멀티 타임프레임
    print("\n📊 Test 3: Multi-Timeframe Reproduction")
    multi_results = {
        'day': result_good,
        'minute60': result_bad
    }

    multi = calc.calculate_multi_timeframe_reproduction(multi_results)
    print(f"  Weighted Signal Rate: {multi['weighted_signal_rate']:.2%}")
    print(f"  Weighted Return Rate: {multi['weighted_return_rate']:.2%}")
    print(f"  Total Reproduction: {multi['total_reproduction_rate']:.2%}")
    print(f"  Tier: {multi['tier']}")
