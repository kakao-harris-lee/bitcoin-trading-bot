"""
ATR Dynamic Exit Manager
변동성 기반 동적 익절/손절 관리
"""

import numpy as np
import pandas as pd
from typing import Dict, Optional
from dataclasses import dataclass
from datetime import datetime


@dataclass
class ExitLevels:
    """청산 레벨 정보"""
    take_profit: float      # 익절 가격
    stop_loss: float        # 손절 가격
    trailing_stop: float    # Trailing Stop 가격
    entry_atr: float        # 진입 시 ATR
    peak_price: float       # 최고가 (Trailing 계산용)


class ATRExitManager:
    """
    ATR 기반 동적 청산 관리자

    변동성에 따라 익절/손절 수준을 자동 조정하여
    - 변동성 높을 때: 넓은 TP/SL
    - 변동성 낮을 때: 좁은 TP/SL

    Trailing Stop으로 수익 보호
    """

    def __init__(self, config: Dict):
        """
        Args:
            config: 설정
                - tp_atr_multiplier: 익절 ATR 배수 (6.0 권장)
                - sl_atr_multiplier: 손절 ATR 배수 (3.0 권장)
                - trailing_atr_multiplier: Trailing Stop ATR 배수 (3.5 권장)
                - trailing_activation_pct: Trailing 활성화 수익률 (10% 권장)
                - use_market_state_exit: 시장 상태 변화 시 즉시 청산
        """
        self.tp_multiplier = config.get('tp_atr_multiplier', 6.0)
        self.sl_multiplier = config.get('sl_atr_multiplier', 3.0)
        self.trailing_multiplier = config.get('trailing_atr_multiplier', 3.5)
        self.trailing_activation = config.get('trailing_activation_pct', 0.10)
        self.use_market_exit = config.get('use_market_state_exit', True)

        # 현재 포지션 정보
        self.exit_levels: Optional[ExitLevels] = None
        self.entry_price: float = 0.0
        self.entry_market_state: str = ""

    def set_entry(
        self,
        entry_price: float,
        entry_atr: float,
        market_state: str = ""
    ) -> ExitLevels:
        """
        진입 시 청산 레벨 설정

        Args:
            entry_price: 진입 가격
            entry_atr: 진입 시 ATR 값
            market_state: 진입 시 시장 상태 (선택)

        Returns:
            청산 레벨
        """
        # TP/SL 계산 (2:1 reward-risk)
        take_profit = entry_price + (entry_atr * self.tp_multiplier)
        stop_loss = entry_price - (entry_atr * self.sl_multiplier)

        self.exit_levels = ExitLevels(
            take_profit=take_profit,
            stop_loss=stop_loss,
            trailing_stop=stop_loss,  # 초기엔 SL과 동일
            entry_atr=entry_atr,
            peak_price=entry_price
        )

        self.entry_price = entry_price
        self.entry_market_state = market_state

        return self.exit_levels

    def update_trailing_stop(self, current_price: float) -> Optional[float]:
        """
        Trailing Stop 업데이트

        Args:
            current_price: 현재 가격

        Returns:
            업데이트된 Trailing Stop 가격 또는 None
        """
        if self.exit_levels is None:
            return None

        # 현재 수익률
        profit_pct = (current_price - self.entry_price) / self.entry_price

        # Trailing Stop 활성화 조건 (10%+ 수익)
        if profit_pct < self.trailing_activation:
            return None

        # 최고가 업데이트
        if current_price > self.exit_levels.peak_price:
            self.exit_levels.peak_price = current_price

        # Trailing Stop 계산
        new_trailing = self.exit_levels.peak_price - (
            self.exit_levels.entry_atr * self.trailing_multiplier
        )

        # Trailing Stop은 항상 상승만 가능 (하락 금지)
        if new_trailing > self.exit_levels.trailing_stop:
            self.exit_levels.trailing_stop = new_trailing
            return new_trailing

        return None

    def check_exit(
        self,
        current_price: float,
        current_market_state: str = ""
    ) -> Optional[Dict]:
        """
        청산 시그널 확인

        Args:
            current_price: 현재 가격
            current_market_state: 현재 시장 상태 (선택)

        Returns:
            청산 시그널 또는 None
        """
        if self.exit_levels is None:
            return None

        # 현재 수익률
        profit_pct = (current_price - self.entry_price) / self.entry_price

        # 1. Take Profit 도달
        if current_price >= self.exit_levels.take_profit:
            return {
                'action': 'sell',
                'reason': 'TAKE_PROFIT',
                'price': current_price,
                'profit_pct': profit_pct * 100,
                'tp_level': self.exit_levels.take_profit
            }

        # 2. Stop Loss 도달
        if current_price <= self.exit_levels.stop_loss:
            return {
                'action': 'sell',
                'reason': 'STOP_LOSS',
                'price': current_price,
                'profit_pct': profit_pct * 100,
                'sl_level': self.exit_levels.stop_loss
            }

        # 3. Trailing Stop 도달 (수익 중일 때만)
        if profit_pct >= self.trailing_activation:
            if current_price <= self.exit_levels.trailing_stop:
                return {
                    'action': 'sell',
                    'reason': 'TRAILING_STOP',
                    'price': current_price,
                    'profit_pct': profit_pct * 100,
                    'trailing_level': self.exit_levels.trailing_stop,
                    'peak_price': self.exit_levels.peak_price
                }

        # 4. 시장 상태 변화 (선택)
        if self.use_market_exit and current_market_state:
            if self._should_exit_on_market_change(current_market_state):
                return {
                    'action': 'sell',
                    'reason': 'MARKET_STATE_CHANGE',
                    'price': current_price,
                    'profit_pct': profit_pct * 100,
                    'from_state': self.entry_market_state,
                    'to_state': current_market_state
                }

        return None

    def _should_exit_on_market_change(self, current_state: str) -> bool:
        """
        시장 상태 변화로 청산 여부 판단

        Args:
            current_state: 현재 시장 상태

        Returns:
            청산 여부
        """
        if not self.entry_market_state:
            return False

        # BULL → BEAR 변화 시 즉시 청산
        if self.entry_market_state.startswith('BULL') and current_state.startswith('BEAR'):
            return True

        # BULL_STRONG → BULL_MODERATE 이하 변화
        if self.entry_market_state == 'BULL_STRONG':
            if current_state in ['BULL_MODERATE', 'SIDEWAYS_UP', 'SIDEWAYS_FLAT', 'SIDEWAYS_DOWN']:
                return True

        return False

    def get_exit_info(self) -> Optional[Dict]:
        """
        현재 청산 레벨 정보 조회

        Returns:
            청산 정보 또는 None
        """
        if self.exit_levels is None:
            return None

        return {
            'entry_price': self.entry_price,
            'take_profit': self.exit_levels.take_profit,
            'stop_loss': self.exit_levels.stop_loss,
            'trailing_stop': self.exit_levels.trailing_stop,
            'peak_price': self.exit_levels.peak_price,
            'entry_atr': self.exit_levels.entry_atr,
            'tp_distance_pct': (self.exit_levels.take_profit - self.entry_price) / self.entry_price * 100,
            'sl_distance_pct': (self.entry_price - self.exit_levels.stop_loss) / self.entry_price * 100,
            'reward_risk_ratio': (self.exit_levels.take_profit - self.entry_price) / (self.entry_price - self.exit_levels.stop_loss)
        }

    def calculate_optimal_atr_multipliers(
        self,
        df: pd.DataFrame,
        entry_idx: int,
        lookback: int = 100
    ) -> Dict:
        """
        최적 ATR 배수 계산 (백테스팅용)

        Args:
            df: 가격 데이터
            entry_idx: 진입 인덱스
            lookback: 과거 데이터 기간

        Returns:
            최적 배수 추천
        """
        if entry_idx < lookback:
            return {
                'tp_multiplier': self.tp_multiplier,
                'sl_multiplier': self.sl_multiplier,
                'reason': 'insufficient_data'
            }

        # 과거 변동성 분석
        lookback_data = df.iloc[entry_idx - lookback:entry_idx]
        avg_atr = lookback_data['atr'].mean()
        current_atr = df.iloc[entry_idx]['atr']
        atr_ratio = current_atr / avg_atr if avg_atr > 0 else 1.0

        # 변동성에 따른 배수 조정
        if atr_ratio > 1.5:  # 높은 변동성
            tp_mult = self.tp_multiplier * 1.2
            sl_mult = self.sl_multiplier * 1.2
            reason = 'high_volatility'
        elif atr_ratio < 0.7:  # 낮은 변동성
            tp_mult = self.tp_multiplier * 0.8
            sl_mult = self.sl_multiplier * 0.8
            reason = 'low_volatility'
        else:  # 정상 변동성
            tp_mult = self.tp_multiplier
            sl_mult = self.sl_multiplier
            reason = 'normal_volatility'

        return {
            'tp_multiplier': tp_mult,
            'sl_multiplier': sl_mult,
            'atr_ratio': atr_ratio,
            'reason': reason
        }

    def reset(self):
        """청산 레벨 초기화"""
        self.exit_levels = None
        self.entry_price = 0.0
        self.entry_market_state = ""


if __name__ == "__main__":
    """ATR Exit Manager 테스트"""
    print("=" * 60)
    print("  ATR Dynamic Exit Manager 테스트")
    print("=" * 60)

    # 설정
    config = {
        'tp_atr_multiplier': 6.0,
        'sl_atr_multiplier': 3.0,
        'trailing_atr_multiplier': 3.5,
        'trailing_activation_pct': 0.10,
        'use_market_state_exit': True
    }

    manager = ATRExitManager(config)

    # 진입 시나리오
    entry_price = 100_000_000
    entry_atr = 2_000_000  # ATR 2M (2% 변동성)

    print(f"\n📍 진입 시나리오:")
    print(f"  진입 가격: {entry_price:,.0f} KRW")
    print(f"  ATR: {entry_atr:,.0f} KRW")

    # 청산 레벨 설정
    exit_levels = manager.set_entry(
        entry_price=entry_price,
        entry_atr=entry_atr,
        market_state='BULL_STRONG'
    )

    info = manager.get_exit_info()
    print(f"\n🎯 청산 레벨:")
    print(f"  Take Profit: {info['take_profit']:,.0f} KRW (+{info['tp_distance_pct']:.2f}%)")
    print(f"  Stop Loss: {info['stop_loss']:,.0f} KRW (-{info['sl_distance_pct']:.2f}%)")
    print(f"  Reward/Risk: {info['reward_risk_ratio']:.2f}:1")

    # 가격 상승 시나리오
    print(f"\n📈 가격 상승 시나리오:")

    # 10% 상승 (Trailing 활성화)
    price_10pct = entry_price * 1.10
    manager.update_trailing_stop(price_10pct)
    print(f"\n  가격 +10%: {price_10pct:,.0f} KRW")
    print(f"  → Trailing Stop 활성화: {manager.exit_levels.trailing_stop:,.0f} KRW")

    # 15% 상승 (최고가 갱신)
    price_15pct = entry_price * 1.15
    manager.update_trailing_stop(price_15pct)
    print(f"\n  가격 +15%: {price_15pct:,.0f} KRW")
    print(f"  → Trailing Stop 상승: {manager.exit_levels.trailing_stop:,.0f} KRW")

    # 2%로 하락 (Trailing Stop 도달)
    price_drop = entry_price * 1.02
    current_profit = (price_drop - entry_price) / entry_price * 100
    print(f"\n  Trailing Stop 레벨: {manager.exit_levels.trailing_stop:,.0f} KRW")
    print(f"  가격 하락: {price_drop:,.0f} KRW (수익률: {current_profit:.2f}%)")

    exit_signal = manager.check_exit(price_drop)

    if exit_signal:
        print(f"  🔔 청산 시그널:")
        print(f"    사유: {exit_signal['reason']}")
        print(f"    수익률: {exit_signal['profit_pct']:+.2f}%")
        if 'trailing_level' in exit_signal:
            print(f"    Trailing 레벨: {exit_signal['trailing_level']:,.0f} KRW")
        if 'peak_price' in exit_signal:
            print(f"    최고가: {exit_signal['peak_price']:,.0f} KRW")
    else:
        print(f"  ⚠️  시그널 없음 (수익 {current_profit:.1f}% < Trailing 활성화 10%)")

    # 시장 상태 변화 시나리오
    print(f"\n📊 시장 상태 변화 시나리오:")
    manager.reset()
    manager.set_entry(entry_price, entry_atr, market_state='BULL_STRONG')

    # BULL → BEAR 변화
    current_price = entry_price * 1.05
    exit_signal = manager.check_exit(current_price, current_market_state='BEAR_MODERATE')

    if exit_signal:
        print(f"  현재 가격: {current_price:,.0f} KRW (+5%)")
        print(f"  🔔 청산 시그널:")
        print(f"    사유: {exit_signal['reason']}")
        print(f"    수익률: {exit_signal['profit_pct']:+.2f}%")
        print(f"    시장 변화: {exit_signal['from_state']} → {exit_signal['to_state']}")

    # 변동성 적응 테스트
    print(f"\n🔬 변동성 적응 테스트:")

    # 테스트 데이터 생성
    dates = pd.date_range('2024-01-01', periods=150, freq='D')
    prices = 100_000_000 + np.random.randn(150) * 2_000_000
    df = pd.DataFrame({
        'close': prices,
        'atr': np.random.uniform(1_500_000, 3_000_000, 150)
    }, index=dates)

    # 높은 변동성 (ATR 1.8배)
    df.iloc[-1, df.columns.get_loc('atr')] = 3_600_000
    optimal = manager.calculate_optimal_atr_multipliers(df, len(df) - 1)

    print(f"\n  높은 변동성 시나리오:")
    print(f"    ATR 비율: {optimal['atr_ratio']:.2f}x")
    print(f"    TP 배수: {optimal['tp_multiplier']:.1f}x (기본 6.0x)")
    print(f"    SL 배수: {optimal['sl_multiplier']:.1f}x (기본 3.0x)")
    print(f"    사유: {optimal['reason']}")

    # 낮은 변동성 (ATR 0.6배)
    df.iloc[-1, df.columns.get_loc('atr')] = 1_200_000
    optimal = manager.calculate_optimal_atr_multipliers(df, len(df) - 1)

    print(f"\n  낮은 변동성 시나리오:")
    print(f"    ATR 비율: {optimal['atr_ratio']:.2f}x")
    print(f"    TP 배수: {optimal['tp_multiplier']:.1f}x (기본 6.0x)")
    print(f"    SL 배수: {optimal['sl_multiplier']:.1f}x (기본 3.0x)")
    print(f"    사유: {optimal['reason']}")

    print(f"\n✅ ATR Exit Manager 테스트 완료!")
