#!/usr/bin/env python3
"""
v11 Multi-Entry Ensemble Strategy

4가지 진입 조건:
A. EMA Golden Cross (v05 기본)
B. RSI Oversold Bounce (추가)
C. Breakout (추가)
D. Momentum Surge (추가)

Adaptive Parameters:
- 시장 상황별 Trailing Stop/Stop Loss 동적 조정
"""

import sys
sys.path.append('../..')

import numpy as np
import pandas as pd
from typing import Dict, Optional
from regime_detector import MarketRegimeDetector


class V11Strategy:
    """v11 Multi-Entry Ensemble 전략"""

    def __init__(self, config: dict):
        self.config = config
        self.regime_detector = MarketRegimeDetector(config)

        # 진입 조건 활성화 플래그
        self.enable_ema_cross = config['entry_conditions']['enable_ema_cross']
        self.enable_rsi_bounce = config['entry_conditions']['enable_rsi_bounce']
        self.enable_breakout = config['entry_conditions']['enable_breakout']
        self.enable_momentum = config['entry_conditions']['enable_momentum']

    def check_entry(self, df: pd.DataFrame, i: int) -> Optional[Dict]:
        """
        진입 신호 확인 (4가지 조건 OR)

        Returns:
            {'action': 'buy', 'fraction': float, 'reason': str} or None
        """
        if i < 30:
            return None

        row = df.iloc[i]
        prev_row = df.iloc[i-1]

        # Entry A: EMA Golden Cross
        if self.enable_ema_cross:
            if self._check_ema_cross(df, i):
                return {
                    'action': 'buy',
                    'fraction': self.config['base_params']['position_fraction'],
                    'reason': 'EMA_GOLDEN_CROSS'
                }

        # Entry B: RSI Oversold Bounce
        if self.enable_rsi_bounce:
            if self._check_rsi_bounce(df, i):
                return {
                    'action': 'buy',
                    'fraction': self.config['base_params']['position_fraction'],
                    'reason': 'RSI_OVERSOLD_BOUNCE'
                }

        # Entry C: Breakout
        if self.enable_breakout:
            if self._check_breakout(df, i):
                return {
                    'action': 'buy',
                    'fraction': self.config['base_params']['position_fraction'],
                    'reason': 'BREAKOUT'
                }

        # Entry D: Momentum Surge
        if self.enable_momentum:
            if self._check_momentum(df, i):
                return {
                    'action': 'buy',
                    'fraction': self.config['base_params']['position_fraction'],
                    'reason': 'MOMENTUM_SURGE'
                }

        return None

    def _check_ema_cross(self, df: pd.DataFrame, i: int) -> bool:
        """Entry A: EMA Golden Cross (v05 기본 전략)"""
        row = df.iloc[i]
        prev_row = df.iloc[i-1]

        ema12 = row.get('ema12', row['close'])
        ema26 = row.get('ema26', row['close'])
        prev_ema12 = prev_row.get('ema12', prev_row['close'])
        prev_ema26 = prev_row.get('ema26', prev_row['close'])

        # 골든크로스: 이전 캔들에서 EMA12 <= EMA26, 현재 캔들에서 EMA12 > EMA26
        golden_cross = (prev_ema12 <= prev_ema26) and (ema12 > ema26)

        return golden_cross

    def _check_rsi_bounce(self, df: pd.DataFrame, i: int) -> bool:
        """Entry B: RSI Oversold Bounce"""
        row = df.iloc[i]
        prev_row = df.iloc[i-1]

        rsi = row.get('rsi', 50)
        prev_rsi = prev_row.get('rsi', 50)
        close = row['close']
        ema26 = row.get('ema26', close)

        # RSI < 30 (과매도) AND 가격 > EMA26 (추세 확인) AND RSI 반등 시작
        oversold = rsi < self.config['rsi_params']['oversold']
        above_trend = close > ema26
        bouncing = rsi > prev_rsi + self.config['rsi_params']['min_bounce']

        return oversold and above_trend and bouncing

    def _check_breakout(self, df: pd.DataFrame, i: int) -> bool:
        """Entry C: Breakout (신고가 돌파 + 거래량 급증)"""
        lookback = self.config['breakout_params']['lookback_period']

        if i < lookback:
            return False

        row = df.iloc[i]
        close = row['close']
        volume = row.get('volume', 0)

        # 최근 N일 최고가
        recent_highs = df.iloc[i-lookback:i]['high']
        rolling_high = recent_highs.max()

        # 평균 거래량
        recent_volumes = df.iloc[i-lookback:i]['volume']
        avg_volume = recent_volumes.mean()

        # 신고가 돌파 AND 거래량 급증
        breakout = close > rolling_high
        volume_surge = volume > avg_volume * self.config['breakout_params']['volume_multiplier']

        return breakout and volume_surge

    def _check_momentum(self, df: pd.DataFrame, i: int) -> bool:
        """Entry D: Momentum Surge (강한 상승 모멘텀)"""
        momentum_period = self.config['momentum_params']['period']

        if i < momentum_period:
            return False

        row = df.iloc[i]
        close = row['close']
        past_close = df.iloc[i - momentum_period]['close']

        # Momentum 계산 (N일 수익률)
        momentum = (close - past_close) / past_close

        # ADX, MACD 확인
        adx = row.get('adx', 0)
        macd = row.get('macd', 0)
        macd_signal = row.get('macd_signal', 0)

        # 강한 모멘텀 AND 추세 확인 AND MACD 양수
        strong_momentum = momentum > self.config['momentum_params']['min_momentum']
        strong_trend = adx > self.config['momentum_params']['min_adx']
        macd_positive = macd > macd_signal

        return strong_momentum and strong_trend and macd_positive

    def check_exit(
        self,
        df: pd.DataFrame,
        i: int,
        entry_price: float,
        highest_price: float,
        entry_reason: str
    ) -> Optional[Dict]:
        """
        청산 신호 확인 (Adaptive Trailing Stop/Stop Loss)

        Args:
            df: 데이터프레임
            i: 현재 인덱스
            entry_price: 진입 가격
            highest_price: 진입 이후 최고가
            entry_reason: 진입 이유

        Returns:
            {'action': 'sell', 'fraction': 1.0, 'reason': str} or None
        """
        row = df.iloc[i]
        current_price = row['close']

        # 현재 시장 상황 판단
        regime = self.regime_detector.detect(df, i)
        params = self.regime_detector.get_params(regime)

        # Trailing Stop 체크
        trailing_threshold = params['trailing_stop_pct']
        drop_from_high = (highest_price - current_price) / highest_price

        if drop_from_high >= trailing_threshold:
            return {
                'action': 'sell',
                'fraction': 1.0,
                'reason': f'TRAILING_STOP_{regime.upper()}_{trailing_threshold*100:.0f}PCT'
            }

        # Stop Loss 체크
        stop_loss_threshold = params['stop_loss_pct']
        loss_from_entry = (entry_price - current_price) / entry_price

        if loss_from_entry >= stop_loss_threshold:
            return {
                'action': 'sell',
                'fraction': 1.0,
                'reason': f'STOP_LOSS_{regime.upper()}_{stop_loss_threshold*100:.0f}PCT'
            }

        return None

    def get_regime(self, df: pd.DataFrame, i: int) -> str:
        """현재 시장 상황 반환"""
        return self.regime_detector.detect(df, i)


if __name__ == '__main__':
    """전략 테스트"""
    import json
    from core.data_loader import DataLoader
    from core.market_analyzer import MarketAnalyzer

    print("=" * 80)
    print("v11 Multi-Entry Strategy Test")
    print("=" * 80)

    # Config 로드
    with open('config.json') as f:
        config = json.load(f)

    # 데이터 로드
    print("\n[1/3] 데이터 로드...")
    with DataLoader('../../upbit_bitcoin.db') as loader:
        df = loader.load_timeframe('day', start_date='2024-01-01', end_date='2024-12-30')

    # 지표 추가
    print("\n[2/3] 지표 추가...")
    df = MarketAnalyzer.add_indicators(df, indicators=['ema', 'rsi', 'macd', 'adx'])
    df = df.rename(columns={'ema_12': 'ema12', 'ema_26': 'ema26'})

    print(f"  ✅ {len(df)}개 캔들")

    # 전략 생성
    print("\n[3/3] 전략 테스트...")
    strategy = V11Strategy(config)

    # 진입 신호 탐지
    entry_signals = []
    for i in range(30, len(df)):
        signal = strategy.check_entry(df, i)
        if signal:
            date = df.iloc[i]['timestamp']
            price = df.iloc[i]['close']
            regime = strategy.get_regime(df, i)

            entry_signals.append({
                'index': i,
                'date': date,
                'price': price,
                'reason': signal['reason'],
                'regime': regime
            })

    print(f"\n진입 신호 발견: {len(entry_signals)}개")
    print("\n진입 신호 상세:")
    print(f"  {'날짜':20s} {'가격':>15s} {'이유':20s} {'시장상황':15s}")
    print(f"  {'-'*75}")

    for sig in entry_signals[:20]:  # 최대 20개만 출력
        print(f"  {str(sig['date']):20s} {sig['price']:>15,.0f} {sig['reason']:20s} {sig['regime']:15s}")

    # Entry 유형별 통계
    from collections import Counter
    entry_types = Counter([sig['reason'] for sig in entry_signals])

    print(f"\nEntry 유형별 빈도:")
    for entry_type, count in entry_types.most_common():
        print(f"  {entry_type:25s}: {count:3d}회 ({count/len(entry_signals)*100:5.1f}%)")

    print("\n" + "=" * 80)
    print("✅ 전략 테스트 완료")
    print("=" * 80)
