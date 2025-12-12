#!/usr/bin/env python3
"""
v34 Supreme Strategy
2020-2024 데이터 기반 Multi-Strategy 통합

전략 구성:
1. BULL_STRONG: Momentum Trading (유명 전략 #1, 평균 +5.59%)
2. BULL_MODERATE: Momentum Trading (완화된 조건)
3. SIDEWAYS_UP: Breakout Trading (유명 전략 #2, 평균 +3.50%)
4. SIDEWAYS_FLAT: Range Trading (박스권 전략)
5. SIDEWAYS_DOWN: 거래 안함 (손실 방지)
6. BEAR_MODERATE: 거래 안함
7. BEAR_STRONG: 거래 안함

분석 결과 (2020-2024):
- Momentum Trading: 10회/년, 평균 +5.59% ⭐
- Breakout Trading: 4.2회/년, 평균 +3.50%
- RSI + BB: 1.6회/년, 평균 +2.80%
- Mean Reversion: 4.6회/년, 평균 -1.73% ❌ (제외)
"""

from typing import Dict, Optional
import pandas as pd
import numpy as np
from market_classifier_v34 import MarketClassifierV34


class V34SupremeStrategy:
    """
    v34 Supreme: 7-Level Market Adaptive Multi-Strategy
    """

    def __init__(self, config: Dict):
        """
        Args:
            config: 하이퍼파라미터 설정 딕셔너리
        """
        self.config = config
        self.classifier = MarketClassifierV34()
        self.in_position = False
        self.entry_price = 0
        self.entry_time = None
        self.market_state = 'UNKNOWN'

    def execute(self, df: pd.DataFrame, i: int) -> Dict:
        """
        전략 실행

        Args:
            df: 지표가 포함된 전체 데이터프레임
            i: 현재 인덱스

        Returns:
            {'action': 'buy'/'sell'/'hold', 'fraction': 0.0~1.0, 'reason': str}
        """
        if i < 30:  # 최소 30개 캔들 필요 (지표 계산)
            return {'action': 'hold', 'reason': 'INSUFFICIENT_DATA'}

        # 현재 시장 상태 분류
        prev_row = df.iloc[i-1] if i > 0 else None
        current_row = df.iloc[i]
        self.market_state = self.classifier.classify_market_state(current_row, prev_row)

        # 포지션 있을 때: Exit 전략
        if self.in_position:
            exit_signal = self._check_exit_conditions(df, i)
            if exit_signal:
                self.in_position = False
                self.entry_price = 0
                self.entry_time = None
                return exit_signal

        # 포지션 없을 때: Entry 전략
        else:
            entry_signal = self._check_entry_conditions(df, i)
            if entry_signal and entry_signal['action'] == 'buy':
                self.in_position = True
                self.entry_price = current_row['close']
                self.entry_time = current_row.name
                return entry_signal

        return {'action': 'hold', 'reason': f'NO_SIGNAL_{self.market_state}'}

    def _check_entry_conditions(self, df: pd.DataFrame, i: int) -> Optional[Dict]:
        """
        시장 상태별 Entry 조건 확인
        """
        row = df.iloc[i]

        # 1. BULL_STRONG: Momentum Trading (가장 강력)
        if self.market_state == 'BULL_STRONG':
            return self._momentum_entry(df, i, aggressive=True)

        # 2. BULL_MODERATE: Momentum Trading (완화)
        elif self.market_state == 'BULL_MODERATE':
            return self._momentum_entry(df, i, aggressive=False)

        # 3. SIDEWAYS_UP: Breakout Trading
        elif self.market_state == 'SIDEWAYS_UP':
            return self._breakout_entry(df, i)

        # 4. SIDEWAYS_FLAT: Range Trading
        elif self.market_state == 'SIDEWAYS_FLAT':
            return self._range_entry(df, i)

        # 5-7. SIDEWAYS_DOWN, BEAR_MODERATE, BEAR_STRONG: 거래 안함
        else:
            return None

    def _momentum_entry(self, df: pd.DataFrame, i: int, aggressive: bool = True) -> Optional[Dict]:
        """
        Momentum Trading Entry
        조건: MACD > Signal AND RSI > 50

        2020-2024 평균 성과: 10회/년, 평균 +5.59%
        """
        row = df.iloc[i]

        macd = row['macd']
        macd_signal = row['macd_signal']
        rsi = row['rsi']

        if aggressive:
            # BULL_STRONG: 공격적
            rsi_threshold = self.config.get('momentum_rsi_bull_strong', 52)
        else:
            # BULL_MODERATE: 보수적
            rsi_threshold = self.config.get('momentum_rsi_bull_moderate', 55)

        if macd > macd_signal and rsi > rsi_threshold:
            return {
                'action': 'buy',
                'fraction': self.config.get('position_size', 0.5),
                'reason': f'MOMENTUM_{"STRONG" if aggressive else "MODERATE"}'
            }

        return None

    def _breakout_entry(self, df: pd.DataFrame, i: int) -> Optional[Dict]:
        """
        Breakout Trading Entry
        조건: 가격이 저항선 돌파 + 강한 거래량

        2020-2024 평균 성과: 4.2회/년, 평균 +3.50%
        """
        if i < 20:
            return None

        row = df.iloc[i]
        prev_20 = df.iloc[i-20:i]

        # 20일 최고가 (저항선)
        resistance = prev_20['high'].max()

        # 현재 가격이 저항선 돌파
        if row['close'] > resistance * 1.005:  # 0.5% 돌파
            # 거래량 확인
            avg_volume = prev_20['volume'].mean()
            if row['volume'] > avg_volume * 1.3:  # 30% 이상 거래량
                return {
                    'action': 'buy',
                    'fraction': self.config.get('position_size', 0.5),
                    'reason': 'BREAKOUT_SIDEWAYS_UP'
                }

        return None

    def _range_entry(self, df: pd.DataFrame, i: int) -> Optional[Dict]:
        """
        Range Trading Entry (박스권 전략)
        조건: 지지선 근처 매수

        SIDEWAYS_FLAT: 2020-2024 평균 31% (가장 많은 시장)
        """
        if i < 20:
            return None

        row = df.iloc[i]
        prev_20 = df.iloc[i-20:i]

        # 20일 최저가 (지지선)
        support = prev_20['low'].min()
        # 20일 최고가 (저항선)
        resistance = prev_20['high'].max()

        # 현재 가격이 지지선 근처 (10% 범위)
        range_height = resistance - support
        if row['close'] < support + range_height * 0.15:  # 하단 15%
            # RSI 과매도 확인
            if row['rsi'] < self.config.get('range_rsi_oversold', 40):
                return {
                    'action': 'buy',
                    'fraction': self.config.get('position_size', 0.5),
                    'reason': 'RANGE_SUPPORT'
                }

        return None

    def _check_exit_conditions(self, df: pd.DataFrame, i: int) -> Optional[Dict]:
        """
        Exit 조건 확인 (공통)
        """
        row = df.iloc[i]
        profit = (row['close'] - self.entry_price) / self.entry_price

        # 1. Take Profit
        tp_levels = [
            self.config.get('take_profit_1', 0.02),  # 2%
            self.config.get('take_profit_2', 0.05),  # 5%
            self.config.get('take_profit_3', 0.10),  # 10%
        ]

        for tp in tp_levels:
            if profit >= tp:
                return {
                    'action': 'sell',
                    'fraction': 1.0,
                    'reason': f'TAKE_PROFIT_{int(tp*100)}%'
                }

        # 2. Stop Loss
        stop_loss = self.config.get('stop_loss', -0.015)  # -1.5%
        if profit <= stop_loss:
            return {
                'action': 'sell',
                'fraction': 1.0,
                'reason': f'STOP_LOSS_{int(abs(stop_loss)*100)}%'
            }

        # 3. Momentum Reverse (Momentum 전략 한정)
        if 'MOMENTUM' in getattr(self, 'entry_reason', ''):
            macd = row['macd']
            macd_signal = row['macd_signal']
            if macd < macd_signal:
                return {
                    'action': 'sell',
                    'fraction': 1.0,
                    'reason': 'MOMENTUM_REVERSE'
                }

        # 4. Market Switch to BEAR
        if self.market_state in ['BEAR_STRONG', 'BEAR_MODERATE']:
            return {
                'action': 'sell',
                'fraction': 1.0,
                'reason': f'MARKET_SWITCH_{self.market_state}'
            }

        return None


def v34_supreme_strategy(df: pd.DataFrame, i: int, params: Dict) -> Dict:
    """
    v34 Supreme 전략 래퍼 함수 (백테스팅 엔진 호환)

    Args:
        df: 전체 데이터프레임 (지표 포함)
        i: 현재 인덱스
        params: 하이퍼파라미터 딕셔너리

    Returns:
        {'action': 'buy'/'sell'/'hold', 'fraction': 0.0~1.0}
    """
    # 전역 변수로 전략 인스턴스 유지 (상태 보존)
    global _v34_strategy_instance

    if '_v34_strategy_instance' not in globals():
        _v34_strategy_instance = V34SupremeStrategy(params)

    return _v34_strategy_instance.execute(df, i)


if __name__ == '__main__':
    """테스트"""
    import sys
    sys.path.append('../..')
    from core.data_loader import DataLoader
    from core.market_analyzer import MarketAnalyzer
    import json

    # Config 로드
    with open('config.json') as f:
        config = json.load(f)

    print("="*70)
    print("  v34 Supreme Strategy - 2024 테스트")
    print("="*70)

    # 데이터 로드
    with DataLoader('../../upbit_bitcoin.db') as loader:
        df = loader.load_timeframe('day', start_date='2024-01-01', end_date='2024-12-31')

    # 지표 추가
    df = MarketAnalyzer.add_indicators(df, indicators=['rsi', 'macd', 'mfi', 'adx', 'atr'])

    # 시장 분류
    classifier = MarketClassifierV34()
    df = classifier.classify_dataframe(df)

    # 전략 테스트 (첫 100개 캔들)
    strategy = V34SupremeStrategy(config)
    signals = []

    for i in range(30, min(100, len(df))):
        signal = strategy.execute(df, i)
        if signal['action'] != 'hold':
            signals.append({
                'date': df.iloc[i].name,
                'action': signal['action'],
                'reason': signal['reason'],
                'price': df.iloc[i]['close'],
                'market_state': strategy.market_state
            })

    print(f"\n[시그널 발생: {len(signals)}개]")
    for sig in signals[:10]:  # 처음 10개만 출력
        print(f"  {sig['date']} | {sig['action']:4s} | {sig['reason']:25s} | {sig['market_state']:15s} | {sig['price']:,.0f}원")

    print(f"\n전략 테스트 완료!")
