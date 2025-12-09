"""
Kelly Criterion Position Sizing
승률과 수익/손실 비율 기반 최적 포지션 크기 계산
"""

import numpy as np
from typing import Dict, List, Optional
from dataclasses import dataclass


@dataclass
class TradingStats:
    """거래 통계"""
    total_trades: int
    winning_trades: int
    losing_trades: int
    avg_win: float
    avg_loss: float
    win_rate: float
    reward_risk_ratio: float


class KellyCalculator:
    """
    Kelly Criterion Position Sizing Calculator

    Kelly % = W - (1 - W) / R
    where:
        W = 승률 (win rate)
        R = 평균 수익 / |평균 손실| (reward-risk ratio)

    Half Kelly 사용으로 안전성 확보
    """

    def __init__(self, config: Dict):
        """
        Args:
            config: 설정
                - use_half_kelly: Half Kelly 사용 여부 (기본 True)
                - min_position: 최소 포지션 크기 (기본 0.10 = 10%)
                - max_position: 최대 포지션 크기 (기본 0.80 = 80%)
                - min_trades_for_kelly: Kelly 적용 최소 거래 횟수 (기본 10)
        """
        self.use_half_kelly = config.get('use_half_kelly', True)
        self.min_position = config.get('min_position', 0.10)
        self.max_position = config.get('max_position', 0.80)
        self.min_trades = config.get('min_trades_for_kelly', 10)

        # 거래 이력
        self.trade_history: List[Dict] = []

    def add_trade(self, profit_pct: float, winning: bool):
        """
        거래 추가

        Args:
            profit_pct: 수익률 (%)
            winning: 승리 여부
        """
        self.trade_history.append({
            'profit_pct': profit_pct,
            'winning': winning
        })

    def get_trading_stats(self) -> Optional[TradingStats]:
        """
        거래 통계 계산

        Returns:
            거래 통계 또는 None (데이터 부족 시)
        """
        if len(self.trade_history) < self.min_trades:
            return None

        winning_trades = [t for t in self.trade_history if t['winning']]
        losing_trades = [t for t in self.trade_history if not t['winning']]

        if not winning_trades or not losing_trades:
            return None

        total = len(self.trade_history)
        wins = len(winning_trades)
        losses = len(losing_trades)

        avg_win = np.mean([t['profit_pct'] for t in winning_trades])
        avg_loss = abs(np.mean([t['profit_pct'] for t in losing_trades]))

        win_rate = wins / total
        reward_risk = avg_win / avg_loss if avg_loss > 0 else 0

        return TradingStats(
            total_trades=total,
            winning_trades=wins,
            losing_trades=losses,
            avg_win=avg_win,
            avg_loss=avg_loss,
            win_rate=win_rate,
            reward_risk_ratio=reward_risk
        )

    def calculate_kelly_pct(self, win_rate: float, reward_risk_ratio: float) -> float:
        """
        Kelly % 계산

        Args:
            win_rate: 승률 (0.0 ~ 1.0)
            reward_risk_ratio: 평균 수익 / |평균 손실|

        Returns:
            Kelly % (0.0 ~ 1.0)
        """
        if reward_risk_ratio <= 0:
            return 0.0

        # Kelly % = W - (1 - W) / R
        kelly_pct = win_rate - (1 - win_rate) / reward_risk_ratio

        # Half Kelly 적용
        if self.use_half_kelly:
            kelly_pct = kelly_pct / 2

        # 음수이면 0
        kelly_pct = max(0.0, kelly_pct)

        return kelly_pct

    def calculate_confidence_score(self, market_data: Dict, signal_data: Dict) -> float:
        """
        신뢰도 점수 계산 (0-100)

        Args:
            market_data: 시장 데이터
                - adx: ADX 값
                - volume_ratio: 거래량 비율 (현재 / 평균)
                - rsi: RSI 값
                - volatility: 변동성
            signal_data: 신호 데이터
                - strategy: 전략 종류
                - market_state: 시장 상태

        Returns:
            신뢰도 점수 (0-100)
        """
        score = 0

        # ADX (추세 강도) - 최대 25점
        adx = market_data.get('adx', 0)
        if adx > 25:
            score += 25
        elif adx > 20:
            score += 20
        elif adx > 15:
            score += 15
        elif adx > 10:
            score += 10

        # Volume (거래량) - 최대 20점
        volume_ratio = market_data.get('volume_ratio', 1.0)
        if volume_ratio > 3.0:
            score += 20
        elif volume_ratio > 2.0:
            score += 15
        elif volume_ratio > 1.5:
            score += 10
        elif volume_ratio > 1.0:
            score += 5

        # RSI (과매도/과매수) - 최대 25점
        rsi = market_data.get('rsi', 50)
        if rsi < 20:  # 극단 과매도
            score += 25
        elif rsi < 30:
            score += 20
        elif rsi < 40:
            score += 15
        elif rsi > 80:  # 극단 과매수 (매수 시 부정적)
            score -= 10
        elif rsi > 70:
            score -= 5

        # 변동성 - 최대 15점
        volatility = market_data.get('volatility', 0)
        if 0.02 <= volatility <= 0.05:  # 적절한 변동성
            score += 15
        elif 0.01 <= volatility < 0.02:  # 낮은 변동성
            score += 10
        elif volatility < 0.01:  # 너무 낮음
            score += 5
        elif volatility > 0.10:  # 너무 높음
            score -= 10

        # 전략 종류 - 최대 15점
        strategy = signal_data.get('strategy', 'unknown')
        if strategy == 'trend_following':
            score += 15  # Trend Following 최고 신뢰도
        elif strategy == 'grid':
            score += 12
        elif strategy == 'momentum':
            score += 10
        elif strategy == 'range':
            score += 8

        # 시장 상태 보정
        market_state = signal_data.get('market_state', 'UNKNOWN')
        if market_state in ['BULL_STRONG', 'BULL_MODERATE']:
            score += 5
        elif market_state == 'SIDEWAYS_UP':
            score += 3

        # 0-100 범위로 제한
        score = max(0, min(100, score))

        return score

    def calculate_position_size(
        self,
        market_data: Dict,
        signal_data: Dict,
        capital: float
    ) -> Dict:
        """
        최적 포지션 크기 계산

        Args:
            market_data: 시장 데이터
            signal_data: 신호 데이터
            capital: 사용 가능 자본

        Returns:
            포지션 정보
        """
        # 거래 통계
        stats = self.get_trading_stats()

        if stats is None:
            # 통계 부족 시 기본값 사용
            base_position = 0.50  # 50%
            confidence = self.calculate_confidence_score(market_data, signal_data)
            position_pct = base_position * (confidence / 100)
        else:
            # Kelly % 계산
            kelly_pct = self.calculate_kelly_pct(stats.win_rate, stats.reward_risk_ratio)

            # 신뢰도 점수
            confidence = self.calculate_confidence_score(market_data, signal_data)

            # 최종 포지션 = Kelly % × (신뢰도 / 100)
            position_pct = kelly_pct * (confidence / 100)

        # 최소/최대 제한
        position_pct = max(self.min_position, min(self.max_position, position_pct))

        # 포지션 금액
        position_amount = capital * position_pct

        return {
            'position_pct': position_pct,
            'position_amount': position_amount,
            'confidence_score': confidence if 'confidence' in locals() else 0,
            'kelly_pct': kelly_pct if stats else None,
            'win_rate': stats.win_rate if stats else None,
            'reward_risk': stats.reward_risk_ratio if stats else None,
            'total_trades': len(self.trade_history)
        }

    def get_statistics(self) -> Dict:
        """
        통계 조회

        Returns:
            통계 정보
        """
        stats = self.get_trading_stats()

        if stats is None:
            return {
                'total_trades': len(self.trade_history),
                'sufficient_data': False,
                'min_required': self.min_trades
            }

        kelly_pct = self.calculate_kelly_pct(stats.win_rate, stats.reward_risk_ratio)

        return {
            'total_trades': stats.total_trades,
            'winning_trades': stats.winning_trades,
            'losing_trades': stats.losing_trades,
            'win_rate': stats.win_rate,
            'avg_win_pct': stats.avg_win,
            'avg_loss_pct': stats.avg_loss,
            'reward_risk_ratio': stats.reward_risk_ratio,
            'kelly_pct': kelly_pct,
            'half_kelly': kelly_pct / 2 if not self.use_half_kelly else kelly_pct,
            'sufficient_data': True
        }

    def reset(self):
        """이력 초기화"""
        self.trade_history = []


if __name__ == "__main__":
    """Kelly Calculator 테스트"""
    print("=" * 60)
    print("  Kelly Criterion Calculator 테스트")
    print("=" * 60)

    # 설정
    config = {
        'use_half_kelly': True,
        'min_position': 0.10,
        'max_position': 0.80,
        'min_trades_for_kelly': 10
    }

    calculator = KellyCalculator(config)

    # 샘플 거래 추가 (v-a-11 기반)
    # 승률 46.7%, 평균 수익 6.51%, 평균 손실 -3.31%
    np.random.seed(42)

    for i in range(30):
        if i < 14:  # 14승
            profit = np.random.normal(6.51, 2.0)
            calculator.add_trade(profit, True)
        else:  # 16패
            profit = np.random.normal(-3.31, 1.0)
            calculator.add_trade(profit, False)

    # 통계 조회
    stats = calculator.get_statistics()
    print(f"\n📊 거래 통계:")
    print(f"  총 거래: {stats['total_trades']}회")
    print(f"  승률: {stats['win_rate'] * 100:.1f}%")
    print(f"  평균 수익: {stats['avg_win_pct']:.2f}%")
    print(f"  평균 손실: {stats['avg_loss_pct']:.2f}%")
    print(f"  R/R 비율: {stats['reward_risk_ratio']:.2f}")
    print(f"  Kelly %: {stats['kelly_pct'] * 100:.1f}%")
    print(f"  Half Kelly: {stats['half_kelly'] * 100:.1f}%")

    # 포지션 크기 계산
    market_data = {
        'adx': 28,
        'volume_ratio': 2.5,
        'rsi': 25,
        'volatility': 0.03
    }

    signal_data = {
        'strategy': 'trend_following',
        'market_state': 'BULL_STRONG'
    }

    position = calculator.calculate_position_size(market_data, signal_data, capital=10_000_000)

    print(f"\n💰 포지션 계산:")
    print(f"  신뢰도 점수: {position['confidence_score']:.0f}/100")
    print(f"  Kelly %: {position['kelly_pct'] * 100:.1f}%")
    print(f"  최종 포지션: {position['position_pct'] * 100:.1f}%")
    print(f"  투입 금액: {position['position_amount']:,.0f} KRW")

    print(f"\n✅ Kelly Calculator 테스트 완료!")
