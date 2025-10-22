#!/usr/bin/env python3
"""
Dynamic Exit Manager
변동성 + 시장 상태 기반 동적 TP/SL/Timeout 계산
"""

import numpy as np
import pandas as pd
from typing import Dict, Optional


class DynamicExitManager:
    """
    동적 청산 관리자
    - ATR 기반 변동성 측정
    - 시장 상태별 TP/SL 조정
    - 타임프레임별 Timeout 조정
    """

    def __init__(self, config: Dict):
        """
        Args:
            config: 설정 dict
        """
        # 베이스 값 (v43 기준)
        base = config.get('base', {})
        self.base_tp = base.get('take_profit', 0.05)  # 5%
        self.base_sl = base.get('stop_loss', 0.02)    # 2%
        self.base_timeout = base.get('timeout_hours', 72)  # 72시간

        # 변동성 기준
        volatility = config.get('volatility', {})
        self.vol_reference = volatility.get('reference_pct', 0.02)  # 2% 기준
        self.vol_mult_range = volatility.get('multiplier_range', {'min': 0.5, 'max': 2.0})

        # 시장 상태별 승수
        self.regime_multipliers = config.get('regime_multipliers', {})

        # 최종 범위 제한
        limits = config.get('limits', {})
        self.tp_min = limits.get('tp_min', 0.02)
        self.tp_max = limits.get('tp_max', 0.20)
        self.sl_min = limits.get('sl_min', 0.01)
        self.sl_max = limits.get('sl_max', 0.05)
        self.timeout_min = limits.get('timeout_min', 12)
        self.timeout_max = limits.get('timeout_max', 168)

    def calculate_exit_levels(
        self,
        entry_price: float,
        market_data: pd.DataFrame,
        market_regime: str,
        timeframe: str = 'day'
    ) -> Dict:
        """
        동적 청산 레벨 계산

        Args:
            entry_price: 진입 가격
            market_data: 시장 데이터 (ATR 포함)
            market_regime: 시장 상태
            timeframe: 타임프레임

        Returns:
            청산 레벨 dict
        """
        # 1. 변동성 계산 (ATR)
        volatility_pct = self._calculate_volatility(market_data)

        # 2. 변동성 승수
        vol_multiplier = volatility_pct / self.vol_reference
        vol_multiplier = np.clip(vol_multiplier, self.vol_mult_range['min'], self.vol_mult_range['max'])

        # 3. 시장 상태 승수
        regime_mult = self.regime_multipliers.get(market_regime, {
            'tp': 1.0,
            'sl': 1.0,
            'timeout': 1.0
        })

        # 4. 타임프레임 승수
        tf_mult = self._get_timeframe_multiplier(timeframe)

        # 5. 최종 계산
        tp_pct = self.base_tp * regime_mult['tp'] * vol_multiplier
        sl_pct = self.base_sl * regime_mult['sl'] * vol_multiplier
        timeout_hours = self.base_timeout * regime_mult['timeout'] * tf_mult

        # 6. 범위 제한
        tp_pct = np.clip(tp_pct, self.tp_min, self.tp_max)
        sl_pct = np.clip(sl_pct, self.sl_min, self.sl_max)
        timeout_hours = np.clip(timeout_hours, self.timeout_min, self.timeout_max)

        # 7. 가격 레벨 계산
        take_profit_price = entry_price * (1 + tp_pct)
        stop_loss_price = entry_price * (1 - sl_pct)

        return {
            'take_profit': take_profit_price,
            'stop_loss': stop_loss_price,
            'timeout_hours': timeout_hours,
            'tp_pct': tp_pct,
            'sl_pct': sl_pct,
            'volatility_pct': volatility_pct,
            'vol_multiplier': vol_multiplier,
            'regime_mult': regime_mult,
            'tf_mult': tf_mult
        }

    def check_exit_signal(
        self,
        position: Dict,
        current_data: pd.DataFrame,
        exit_levels: Dict
    ) -> Optional[Dict]:
        """
        청산 시그널 체크

        Args:
            position: 활성 포지션
            current_data: 현재 데이터
            exit_levels: 청산 레벨

        Returns:
            청산 시그널 or None
        """
        if current_data is None or len(current_data) == 0:
            return None

        latest = current_data.iloc[-1]
        current_price = latest['close']
        current_time = pd.to_datetime(latest['timestamp'])
        entry_time = pd.to_datetime(position['entry_timestamp'])

        # 1. Take Profit 체크
        if current_price >= exit_levels['take_profit']:
            return_pct = (current_price - position['entry_price']) / position['entry_price']
            return {
                'action': 'exit',
                'reason': 'take_profit',
                'price': current_price,
                'timestamp': latest['timestamp'],
                'return_pct': return_pct,
                'tp_target': exit_levels['tp_pct']
            }

        # 2. Stop Loss 체크
        if current_price <= exit_levels['stop_loss']:
            return_pct = (current_price - position['entry_price']) / position['entry_price']
            return {
                'action': 'exit',
                'reason': 'stop_loss',
                'price': current_price,
                'timestamp': latest['timestamp'],
                'return_pct': return_pct,
                'sl_target': exit_levels['sl_pct']
            }

        # 3. Timeout 체크
        hours_held = (current_time - entry_time).total_seconds() / 3600
        if hours_held >= exit_levels['timeout_hours']:
            return_pct = (current_price - position['entry_price']) / position['entry_price']
            return {
                'action': 'exit',
                'reason': 'timeout',
                'price': current_price,
                'timestamp': latest['timestamp'],
                'return_pct': return_pct,
                'hours_held': hours_held
            }

        return None

    def _calculate_volatility(self, market_data: pd.DataFrame) -> float:
        """ATR 기반 변동성 계산"""
        if 'atr' in market_data.columns:
            atr = market_data['atr'].iloc[-1]
            current_price = market_data['close'].iloc[-1]
            return atr / current_price
        else:
            # ATR 없으면 최근 14일 수익률 표준편차 사용
            if len(market_data) < 14:
                return self.vol_reference

            returns = market_data['close'].pct_change().tail(14)
            return returns.std()

    def _get_timeframe_multiplier(self, timeframe: str) -> float:
        """타임프레임별 승수 반환"""
        multipliers = {
            'day': 1.0,
            'minute240': 0.7,
            'minute60': 0.5,
            'minute15': 0.3,
            'minute5': 0.2
        }
        return multipliers.get(timeframe, 1.0)


# 테스트 코드
if __name__ == "__main__":
    print("=" * 80)
    print("Dynamic Exit Manager 테스트")
    print("=" * 80)

    config = {
        'base': {
            'take_profit': 0.05,
            'stop_loss': 0.02,
            'timeout_hours': 72
        },
        'volatility': {
            'reference_pct': 0.02,
            'multiplier_range': {'min': 0.5, 'max': 2.0}
        },
        'regime_multipliers': {
            'BULL_STRONG': {'tp': 1.5, 'sl': 0.8, 'timeout': 1.2},
            'SIDEWAYS_FLAT': {'tp': 0.8, 'sl': 1.0, 'timeout': 0.8},
            'BEAR_STRONG': {'tp': 0.6, 'sl': 1.5, 'timeout': 0.5}
        },
        'limits': {
            'tp_min': 0.02, 'tp_max': 0.20,
            'sl_min': 0.01, 'sl_max': 0.05,
            'timeout_min': 12, 'timeout_max': 168
        }
    }

    manager = DynamicExitManager(config)

    # 시뮬레이션 데이터 생성
    dates = pd.date_range('2024-01-01', periods=50, freq='D')
    np.random.seed(42)

    market_data = pd.DataFrame({
        'timestamp': dates,
        'close': 100000 * (1 + np.random.randn(50).cumsum() * 0.01),
        'atr': np.random.uniform(1500, 2500, 50)
    })

    entry_price = 100000

    print("\n시나리오 1: BULL_STRONG (변동성 정상)")
    print("-" * 80)
    levels = manager.calculate_exit_levels(
        entry_price, market_data, 'BULL_STRONG', 'day'
    )
    print(f"진입 가격: {entry_price:,.0f}원")
    print(f"익절 가격: {levels['take_profit']:,.0f}원 (+{levels['tp_pct']:.2%})")
    print(f"손절 가격: {levels['stop_loss']:,.0f}원 (-{levels['sl_pct']:.2%})")
    print(f"Timeout: {levels['timeout_hours']:.1f}시간")
    print(f"변동성: {levels['volatility_pct']:.2%}")

    print("\n시나리오 2: SIDEWAYS_FLAT (변동성 정상)")
    print("-" * 80)
    levels = manager.calculate_exit_levels(
        entry_price, market_data, 'SIDEWAYS_FLAT', 'day'
    )
    print(f"익절 가격: {levels['take_profit']:,.0f}원 (+{levels['tp_pct']:.2%})")
    print(f"손절 가격: {levels['stop_loss']:,.0f}원 (-{levels['sl_pct']:.2%})")
    print(f"Timeout: {levels['timeout_hours']:.1f}시간")

    print("\n시나리오 3: BEAR_STRONG (변동성 정상)")
    print("-" * 80)
    levels = manager.calculate_exit_levels(
        entry_price, market_data, 'BEAR_STRONG', 'day'
    )
    print(f"익절 가격: {levels['take_profit']:,.0f}원 (+{levels['tp_pct']:.2%})")
    print(f"손절 가격: {levels['stop_loss']:,.0f}원 (-{levels['sl_pct']:.2%})")
    print(f"Timeout: {levels['timeout_hours']:.1f}시간")

    print("\n시나리오 4: 타임프레임별 차이")
    print("-" * 80)
    for tf in ['day', 'minute240', 'minute60']:
        levels = manager.calculate_exit_levels(
            entry_price, market_data, 'BULL_STRONG', tf
        )
        print(f"{tf:12}: Timeout {levels['timeout_hours']:6.1f}시간")

    print("\n" + "=" * 80)
    print("테스트 완료")
    print("=" * 80)
