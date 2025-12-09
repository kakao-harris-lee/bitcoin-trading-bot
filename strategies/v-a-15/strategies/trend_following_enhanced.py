#!/usr/bin/env python3
"""
Enhanced Trend Following Strategy (v-a-15)

v-a-11 대비 개선:
  1. ADX 임계값 완화: 25 → 20 (더 많은 추세 포착)
  2. MACD + RSI + Volume 복합 조건
  3. 진입 신뢰도 점수 시스템
  4. ATR Dynamic Exit 통합

목표: Trend 거래 +30%, 수익 +2-4%p
"""

import pandas as pd
import numpy as np
from typing import Dict, Optional
import sys
import os

# 상위 디렉토리 import를 위한 경로 추가
sys.path.append(os.path.dirname(os.path.dirname(__file__)))

try:
    from core.atr_exit_manager import ATRExitManager
except ImportError:
    ATRExitManager = None


class EnhancedTrendFollowingStrategy:
    """강화된 추세 추종 전략 (BULL_STRONG/MODERATE용)"""

    def __init__(self, config: Dict):
        self.config = config
        self.in_position = False
        self.entry_price = 0
        self.entry_time = None
        self.entry_idx = 0
        self.highest_price = 0
        self.hold_days = 0

        # ATR Exit Manager (선택적)
        self.use_atr_exit = config.get('use_atr_exit', True) and ATRExitManager is not None
        if self.use_atr_exit:
            self.atr_exit = ATRExitManager({
                'tp_atr_multiplier': config.get('trend_tp_atr_mult', 6.0),
                'sl_atr_multiplier': config.get('trend_sl_atr_mult', 3.0),
                'trailing_atr_multiplier': config.get('trend_trailing_atr_mult', 3.5),
                'trailing_activation_pct': config.get('trend_trailing_activation', 0.15),  # 15%
                'use_market_state_exit': True
            })
        else:
            self.atr_exit = None

    def execute(self, df: pd.DataFrame, i: int, market_state: str = 'UNKNOWN') -> Dict:
        """
        전략 실행

        진입 조건 (모두 만족):
          1. MACD 골든크로스
          2. ADX >= 20 (완화됨, v-a-11: 25)
          3. RSI < 65 (과매수 아님)
          4. Volume > 평균 × 1.5
          5. 신뢰도 점수 >= 60점

        청산 조건 (ATR Dynamic Exit 또는 전통적):
          - ATR 사용 시: TP/SL/Trailing 자동
          - 미사용 시: MACD 데드크로스, 최대 90일
        """

        if i < 30:
            return {'action': 'hold', 'reason': 'INSUFFICIENT_DATA'}

        row = df.iloc[i]
        prev_row = df.iloc[i-1] if i > 0 else None

        # 포지션 있을 때
        if self.in_position:
            self.hold_days += 1

            # ATR Exit 업데이트
            if self.use_atr_exit and self.atr_exit:
                self.atr_exit.update_trailing_stop(row['close'])

            exit_signal = self._check_exit(row, prev_row, market_state, df, i)
            if exit_signal:
                self.in_position = False
                self.entry_price = 0
                self.entry_time = None
                self.entry_idx = 0
                self.highest_price = 0
                self.hold_days = 0
                if self.atr_exit:
                    self.atr_exit.reset()
                return exit_signal

            # 최고가 업데이트
            if row['close'] > self.highest_price:
                self.highest_price = row['close']

        # 포지션 없을 때
        else:
            entry_signal = self._check_entry(row, prev_row, df, i, market_state)
            if entry_signal:
                self.in_position = True
                self.entry_price = row['close']
                self.entry_time = row.name
                self.entry_idx = i
                self.highest_price = row['close']
                self.hold_days = 0

                # ATR Exit 설정
                if self.use_atr_exit and self.atr_exit:
                    entry_atr = row.get('atr', row['close'] * 0.02)  # 기본 2%
                    self.atr_exit.set_entry(
                        entry_price=row['close'],
                        entry_atr=entry_atr,
                        market_state=market_state
                    )

                return entry_signal

        return {'action': 'hold', 'reason': 'TREND_HOLD'}

    def _check_entry(self, row: pd.Series, prev_row: pd.Series,
                     df: pd.DataFrame, i: int, market_state: str) -> Optional[Dict]:
        """진입 조건 확인 (강화된 버전)"""

        if prev_row is None or i < 20:
            return None

        # 기본 지표
        macd = row.get('macd', 0)
        macd_signal = row.get('macd_signal', 0)
        prev_macd = prev_row.get('macd', 0)
        prev_signal = prev_row.get('macd_signal', 0)
        adx = row.get('adx', 20)
        rsi = row.get('rsi', 50)
        volume = row.get('volume', 0)

        # 평균 거래량
        avg_volume = df['volume'].iloc[i-20:i].mean() if i >= 20 else volume

        # 1. MACD 골든크로스 (필수)
        golden_cross = (prev_macd <= prev_signal) and (macd > macd_signal)
        if not golden_cross:
            return None

        # 2. ADX >= 20 (완화됨, v-a-11: 25)
        adx_threshold = self.config.get('trend_adx_threshold', 20)
        if adx < adx_threshold:
            return None

        # 3. RSI < 65 (과매수 아님)
        rsi_threshold = self.config.get('trend_rsi_max', 65)
        if rsi >= rsi_threshold:
            return None

        # 4. Volume > 평균 × 1.5
        volume_mult = self.config.get('trend_volume_mult', 1.5)
        if volume < avg_volume * volume_mult:
            return None

        # 5. 신뢰도 점수 계산 (0-100점)
        confidence = self._calculate_confidence(
            adx=adx,
            rsi=rsi,
            volume_ratio=volume / avg_volume if avg_volume > 0 else 1.0,
            market_state=market_state,
            macd=macd,
            macd_signal=macd_signal
        )

        min_confidence = self.config.get('trend_min_confidence', 60)
        if confidence < min_confidence:
            return None

        # 진입 성공
        return {
            'action': 'buy',
            'fraction': self.config.get('trend_position_size', 0.7),  # 70% (v-a-11: 80%)
            'reason': f'TREND_ENHANCED (ADX={adx:.1f}, RSI={rsi:.1f}, Vol={volume/avg_volume:.1f}x, Conf={confidence:.0f})',
            'strategy': 'trend_enhanced',
            'confidence': confidence
        }

    def _calculate_confidence(self, adx: float, rsi: float, volume_ratio: float,
                             market_state: str, macd: float, macd_signal: float) -> float:
        """
        진입 신뢰도 점수 계산 (0-100)

        ADX (0-30점) + RSI (0-20점) + Volume (0-20점) +
        Market State (0-15점) + MACD (0-15점)
        """
        score = 0.0

        # ADX (추세 강도) - 최대 30점
        if adx >= 30:
            score += 30
        elif adx >= 25:
            score += 25
        elif adx >= 20:
            score += 20
        elif adx >= 15:
            score += 15

        # RSI (적정 범위) - 최대 20점
        if 40 <= rsi <= 55:  # 이상적인 진입 구간
            score += 20
        elif 30 <= rsi < 40:  # 과매도에서 반등
            score += 18
        elif 55 < rsi <= 60:  # 약간 높지만 OK
            score += 15
        elif 60 < rsi < 65:  # 경계 구간
            score += 10

        # Volume (거래량 비율) - 최대 20점
        if volume_ratio >= 3.0:
            score += 20
        elif volume_ratio >= 2.5:
            score += 18
        elif volume_ratio >= 2.0:
            score += 15
        elif volume_ratio >= 1.5:
            score += 10

        # Market State - 최대 15점
        if market_state == 'BULL_STRONG':
            score += 15
        elif market_state == 'BULL_MODERATE':
            score += 12
        elif market_state.startswith('SIDEWAYS'):
            score += 5

        # MACD 강도 - 최대 15점
        macd_diff = abs(macd - macd_signal)
        macd_signal_abs = abs(macd_signal)

        if macd_signal_abs > 0:
            macd_strength = macd_diff / macd_signal_abs
            if macd_strength >= 0.10:  # 10% 이상 차이
                score += 15
            elif macd_strength >= 0.05:
                score += 12
            elif macd_strength >= 0.02:
                score += 8

        return min(100, score)

    def _check_exit(self, row: pd.Series, prev_row: pd.Series,
                    market_state: str, df: pd.DataFrame, i: int) -> Optional[Dict]:
        """청산 조건 확인"""

        current_price = row['close']
        profit = (current_price - self.entry_price) / self.entry_price

        # ATR Exit 우선
        if self.use_atr_exit and self.atr_exit:
            atr_exit = self.atr_exit.check_exit(current_price, market_state)
            if atr_exit:
                return {
                    'action': 'sell',
                    'fraction': 1.0,
                    'reason': f"TREND_ATR_{atr_exit['reason']} (profit={profit:.2%}, hold={self.hold_days}d)",
                    'strategy': 'trend_enhanced',
                    'atr_reason': atr_exit['reason']
                }

        # 전통적 청산 (ATR 미사용 또는 백업)
        if prev_row is None:
            return None

        macd = row.get('macd', 0)
        macd_signal = row.get('macd_signal', 0)
        prev_macd = prev_row.get('macd', 0)
        prev_signal = prev_row.get('macd_signal', 0)

        # 1. MACD 데드크로스
        dead_cross = (prev_macd >= prev_signal) and (macd < macd_signal)
        if dead_cross:
            return {
                'action': 'sell',
                'fraction': 1.0,
                'reason': f'TREND_DEAD_CROSS (profit={profit:.2%}, hold={self.hold_days}d)',
                'strategy': 'trend_enhanced'
            }

        # 2. 최대 보유 기간 (90일)
        max_hold = self.config.get('trend_max_hold_days', 90)
        if self.hold_days >= max_hold:
            return {
                'action': 'sell',
                'fraction': 1.0,
                'reason': f'TREND_MAX_HOLD (profit={profit:.2%}, {max_hold}d)',
                'strategy': 'trend_enhanced'
            }

        # 3. 손절 (-8%, ATR 없을 때만)
        if not self.use_atr_exit:
            stop_loss = self.config.get('trend_stop_loss', -0.08)
            if profit <= stop_loss:
                return {
                    'action': 'sell',
                    'fraction': 1.0,
                    'reason': f'TREND_STOP_LOSS ({stop_loss:.0%})',
                    'strategy': 'trend_enhanced'
                }

        # 4. Trailing Stop (ATR 없을 때만, 수익 20% 이상)
        if not self.use_atr_exit and profit > 0.20:
            trailing_pct = self.config.get('trend_trailing_stop', 0.05)
            drawdown = (current_price - self.highest_price) / self.highest_price

            if drawdown <= -trailing_pct:
                return {
                    'action': 'sell',
                    'fraction': 1.0,
                    'reason': f'TREND_TRAILING (profit={profit:.2%}, peak-{trailing_pct:.0%})',
                    'strategy': 'trend_enhanced'
                }

        return None


if __name__ == '__main__':
    """테스트"""
    print("="*70)
    print("  Enhanced Trend Following Strategy - 테스트")
    print("="*70)

    # 샘플 데이터
    dates = pd.date_range('2024-01-01', periods=120, freq='D')

    base_price = 100_000_000
    prices = base_price * (1 + np.arange(120) * 0.008)  # 일 0.8% 상승
    prices += np.random.randn(120) * 1_000_000

    # MACD 시뮬레이션
    macd = np.zeros(120)
    macd_signal = np.zeros(120)

    macd[:15] = -1000
    macd_signal[:15] = -500

    macd[15:90] = 1000  # 골든크로스 후 유지
    macd_signal[15:90] = 500

    macd[90:] = 300  # 데드크로스
    macd_signal[90:] = 700

    # ADX, RSI 시뮬레이션
    adx_values = np.random.uniform(22, 28, 120)
    rsi_values = np.random.uniform(45, 60, 120)

    # Volume
    volumes = np.random.uniform(1000, 2000, 120)
    volumes[15:90] *= 2.0  # 추세 시 거래량 증가

    # ATR
    atr_values = prices * 0.02  # 2% 변동성

    df = pd.DataFrame({
        'close': prices,
        'macd': macd,
        'macd_signal': macd_signal,
        'adx': adx_values,
        'rsi': rsi_values,
        'volume': volumes,
        'atr': atr_values
    }, index=dates)

    # 테스트 1: ATR Exit 사용
    print("\n[테스트 1: ATR Dynamic Exit 사용]")
    config_atr = {
        'trend_adx_threshold': 20,
        'trend_rsi_max': 65,
        'trend_volume_mult': 1.5,
        'trend_min_confidence': 60,
        'trend_position_size': 0.7,
        'use_atr_exit': True,
        'trend_tp_atr_mult': 6.0,
        'trend_sl_atr_mult': 3.0
    }

    strategy_atr = EnhancedTrendFollowingStrategy(config_atr)

    for i in range(30, len(df)):
        signal = strategy_atr.execute(df, i, market_state='BULL_STRONG')

        if signal['action'] == 'buy':
            print(f"\n  매수: {df.index[i].date()}")
            print(f"    {signal['reason']}")
            print(f"    신뢰도: {signal.get('confidence', 0):.0f}/100")

        elif signal['action'] == 'sell':
            print(f"\n  매도: {df.index[i].date()}")
            print(f"    {signal['reason']}")

    # 테스트 2: 전통적 Exit
    print("\n\n[테스트 2: 전통적 Exit (ATR 미사용)]")
    config_trad = {
        'trend_adx_threshold': 20,
        'trend_rsi_max': 65,
        'trend_volume_mult': 1.5,
        'trend_min_confidence': 60,
        'trend_position_size': 0.7,
        'use_atr_exit': False,
        'trend_stop_loss': -0.08,
        'trend_trailing_stop': 0.05,
        'trend_max_hold_days': 90
    }

    strategy_trad = EnhancedTrendFollowingStrategy(config_trad)

    for i in range(30, len(df)):
        signal = strategy_trad.execute(df, i, market_state='BULL_STRONG')

        if signal['action'] == 'buy':
            print(f"\n  매수: {df.index[i].date()}")
            print(f"    {signal['reason']}")

        elif signal['action'] == 'sell':
            print(f"\n  매도: {df.index[i].date()}")
            print(f"    {signal['reason']}")

    print("\n✅ Enhanced Trend Following 테스트 완료!")
    print("\n개선 사항:")
    print("  ✓ ADX 임계값 25 → 20 (더 많은 추세 포착)")
    print("  ✓ MACD + RSI + Volume 복합 조건")
    print("  ✓ 신뢰도 점수 시스템 (0-100점)")
    print("  ✓ ATR Dynamic Exit 통합")
