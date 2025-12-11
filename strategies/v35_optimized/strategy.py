#!/usr/bin/env python3
"""
v35 Optimized Strategy
v34 + Optuna 최적화 + 동적 익절 + SIDEWAYS 강화

목표: 2025년 +15% (v34 +8.43% 대비 +6.57%p 개선)

핵심 개선:
1. 동적 익절/손절 (시장 상태별 TP 조정, Trailing Stop, 분할 익절)
2. SIDEWAYS 전략 3종 추가 (RSI+BB, Stochastic, Volume Breakout)
3. Optuna 하이퍼파라미터 최적화
"""

from typing import Dict, Optional
import pandas as pd
import numpy as np
import sys
import os

# 프로젝트 루트 경로 추가 (상대 경로 지원)
_current_dir = os.path.dirname(os.path.abspath(__file__))
_strategies_dir = os.path.dirname(_current_dir)
_project_root = os.path.dirname(_strategies_dir)
sys.path.insert(0, _project_root)
sys.path.insert(0, _current_dir)
sys.path.insert(0, os.path.join(_strategies_dir, '_deprecated', 'v34_supreme'))

from market_classifier_v34 import MarketClassifierV34
from dynamic_exit_manager import DynamicExitManager
from sideways_enhanced import SidewaysEnhancedStrategies
# AI 모드 제거: MarketAnalyzerV2 import 비활성화
# from core.market_analyzer_v2 import MarketAnalyzerV2


class V35OptimizedStrategy:
    """
    v35 Optimized: 최적화된 Multi-Strategy
    """

    def __init__(self, config: Dict):
        """
        Args:
            config: 하이퍼파라미터 설정 딕셔너리
        """
        self.config = config
        self.classifier = MarketClassifierV34()
        self.exit_manager = DynamicExitManager(config)
        self.sideways_strategies = SidewaysEnhancedStrategies(config)

        # AI 모드 완전 비활성화 (v35 순수 버전)
        self.ai_enabled = False
        self.ai_test_mode = False
        self.ai_filter_mode = False
        self.ai_filter_strict = False
        self.ai_analysis_history = []
        self.ai_filter_stats = {}

        # 포지션 상태
        self.in_position = False
        self.entry_price = 0
        self.entry_time = None
        self.entry_market_state = 'UNKNOWN'
        self.entry_strategy = 'unknown'  # 어떤 전략으로 진입했는지

    def execute(self, df: pd.DataFrame, i: int) -> Dict:
        """
        전략 실행

        Args:
            df: 지표가 포함된 전체 데이터프레임
            i: 현재 인덱스

        Returns:
            {'action': 'buy'/'sell'/'hold', 'fraction': 0.0~1.0, 'reason': str}
        """
        if i < 30:
            return {'action': 'hold', 'reason': 'INSUFFICIENT_DATA'}

        # 현재 시장 상태 분류 (v34 classifier)
        prev_row = df.iloc[i-1] if i > 0 else None
        current_row = df.iloc[i]
        market_state = self.classifier.classify_market_state(current_row, prev_row)

        # 🆕 BEAR 감지 시 즉시 청산 (하락장 보호)
        if self.in_position and market_state in ['BEAR_MODERATE', 'BEAR_STRONG']:
            self.in_position = False
            self.entry_price = 0
            self.entry_time = None
            self.entry_market_state = 'UNKNOWN'
            self.entry_strategy = 'unknown'
            self.exit_manager.reset()

            return {
                'action': 'sell',
                'fraction': 1.0,
                'reason': f'BEAR_PROTECTION_{market_state}'
            }

        # 포지션 있을 때: Exit 전략
        if self.in_position:
            exit_signal = self._check_exit_conditions(df, i, market_state)
            if exit_signal:
                self.in_position = False
                self.entry_price = 0
                self.entry_time = None
                self.entry_market_state = 'UNKNOWN'
                self.entry_strategy = 'unknown'
                self.exit_manager.reset()

                return exit_signal

        # 포지션 없을 때: Entry 전략
        else:
            entry_signal = self._check_entry_conditions(df, i, market_state, prev_row)
            if entry_signal and entry_signal['action'] == 'buy':
                self.in_position = True
                self.entry_price = current_row['close']
                self.entry_time = current_row.name
                self.entry_market_state = market_state
                self.entry_strategy = entry_signal.get('strategy', 'unknown')

                # Exit Manager 초기화
                self.exit_manager.set_entry(self.entry_price, market_state)

                return entry_signal

        return {'action': 'hold', 'reason': f'NO_SIGNAL_{market_state}'}

    # AI 모드 제거: _ai_filter_check() 메서드 비활성화
    # def _ai_filter_check(self, v35_signal: str, market_state: str,
    #                     df: pd.DataFrame, i: int) -> Dict:
    #     """Phase 2-B AI 필터 (사용 안함)"""
    #     return {'approved': True, 'ai_state': 'N/A', 'ai_confidence': 0.0,
    #             'match_type': 'DISABLED', 'reason': 'AI disabled'}

    def _check_entry_conditions(self, df: pd.DataFrame, i: int,
                                market_state: str, prev_row: pd.Series) -> Optional[Dict]:
        """
        시장 상태별 Entry 조건 확인
        """
        row = df.iloc[i]

        # 1. BULL_STRONG: Momentum Trading (공격적)
        if market_state == 'BULL_STRONG':
            return self._momentum_entry(row, aggressive=True)

        # 2. BULL_MODERATE: Momentum Trading (보수적)
        elif market_state == 'BULL_MODERATE':
            return self._momentum_entry(row, aggressive=False)

        # 3. SIDEWAYS_UP: Breakout Trading
        elif market_state == 'SIDEWAYS_UP':
            return self._breakout_entry(df, i)

        # 4. SIDEWAYS_FLAT: Enhanced SIDEWAYS Strategies ⭐ (강화됨)
        elif market_state == 'SIDEWAYS_FLAT':
            # v34의 기본 Range Trading
            range_signal = self._range_entry(df, i)
            if range_signal:
                return range_signal

            # v35 추가: RSI+BB, Stochastic, Volume Breakout
            sideways_signal = self.sideways_strategies.check_all_entries(row, prev_row, df, i)
            if sideways_signal:
                return sideways_signal

        # 5-7. SIDEWAYS_DOWN, BEAR_MODERATE, BEAR_STRONG: 거래 안함
        return None

    def _momentum_entry(self, row: pd.Series, aggressive: bool = True) -> Optional[Dict]:
        """Momentum Trading Entry (v34와 동일)"""
        macd = row['macd']
        macd_signal = row['macd_signal']
        rsi = row['rsi']

        if aggressive:
            rsi_threshold = self.config.get('momentum_rsi_bull_strong', 52)
        else:
            rsi_threshold = self.config.get('momentum_rsi_bull_moderate', 55)

        if macd > macd_signal and rsi > rsi_threshold:
            return {
                'action': 'buy',
                'fraction': self.config.get('position_size', 0.5),
                'reason': f'MOMENTUM_{"STRONG" if aggressive else "MODERATE"}',
                'strategy': 'momentum'
            }

        return None

    def _breakout_entry(self, df: pd.DataFrame, i: int) -> Optional[Dict]:
        """Breakout Trading Entry (v34와 동일)"""
        if i < 20:
            return None

        row = df.iloc[i]
        prev_20 = df.iloc[i-20:i]

        resistance = prev_20['high'].max()
        breakout_threshold = self.config.get('breakout_threshold', 0.005)

        if row['close'] > resistance * (1 + breakout_threshold):
            avg_volume = prev_20['volume'].mean()
            volume_mult = self.config.get('breakout_volume_mult', 1.3)

            if row['volume'] > avg_volume * volume_mult:
                return {
                    'action': 'buy',
                    'fraction': self.config.get('position_size', 0.5),
                    'reason': 'BREAKOUT_SIDEWAYS_UP',
                    'strategy': 'breakout'
                }

        return None

    def _range_entry(self, df: pd.DataFrame, i: int) -> Optional[Dict]:
        """Range Trading Entry (v34와 동일)"""
        if i < 20:
            return None

        row = df.iloc[i]
        prev_20 = df.iloc[i-20:i]

        support = prev_20['low'].min()
        resistance = prev_20['high'].max()

        range_height = resistance - support
        support_zone = self.config.get('range_support_zone', 0.15)

        if row['close'] < support + range_height * support_zone:
            rsi_oversold = self.config.get('range_rsi_oversold', 40)
            if row['rsi'] < rsi_oversold:
                return {
                    'action': 'buy',
                    'fraction': self.config.get('position_size', 0.5),
                    'reason': 'RANGE_SUPPORT',
                    'strategy': 'range'
                }

        return None

    def _check_exit_conditions(self, df: pd.DataFrame, i: int, market_state: str) -> Optional[Dict]:
        """
        Exit 조건 확인 (v35 동적 익절 시스템 사용) ⭐
        """
        row = df.iloc[i]
        prev_row = df.iloc[i-1] if i > 0 else None

        # 1. Dynamic Exit Manager 우선 (TP, SL, Trailing Stop)
        exit_signal = self.exit_manager.check_exit(
            current_price=row['close'],
            current_market_state=market_state,
            macd=row.get('macd', 0),
            macd_signal=row.get('macd_signal', 0)
        )

        if exit_signal:
            return exit_signal

        # 2. SIDEWAYS 전략별 Exit 조건 (추가)
        if self.entry_strategy == 'rsi_bb':
            exit_signal = self.sideways_strategies.check_rsi_bb_exit(row, self.entry_strategy)
            if exit_signal:
                return exit_signal

        elif self.entry_strategy == 'stoch':
            exit_signal = self.sideways_strategies.check_stoch_exit(row, prev_row, self.entry_strategy)
            if exit_signal:
                return exit_signal

        elif self.entry_strategy == 'volume_breakout':
            exit_signal = self.sideways_strategies.check_volume_breakout_exit(
                row, df, i, self.entry_price, self.entry_strategy
            )
            if exit_signal:
                return exit_signal

        return None

    def get_ai_analysis_summary(self) -> Dict:
        """
        AI 분석 통계 (AI 비활성화 상태)

        Returns:
            AI 비활성화 메시지
        """
        return {
            'ai_enabled': False,
            'message': 'AI 모드 완전 비활성화 - v35 순수 버전 사용 중'
        }


if __name__ == '__main__':
    """테스트"""
    import json
    from core.data_loader import DataLoader
    from core.market_analyzer import MarketAnalyzer

    # 기본 Config (Optuna 최적화 전)
    config = {
        # 시장 분류기
        'mfi_bull_strong': 52,
        'mfi_bull_moderate': 45,
        'mfi_sideways_up': 42,
        'mfi_bear_moderate': 38,
        'mfi_bear_strong': 35,
        'adx_strong_trend': 20,
        'adx_moderate_trend': 15,

        # Entry
        'momentum_rsi_bull_strong': 52,
        'momentum_rsi_bull_moderate': 55,
        'breakout_threshold': 0.005,
        'breakout_volume_mult': 1.3,
        'range_support_zone': 0.15,
        'range_rsi_oversold': 40,

        # Exit (동적 익절)
        'tp_bull_strong_1': 0.05,
        'tp_bull_strong_2': 0.10,
        'tp_bull_strong_3': 0.20,
        'trailing_bull_strong': 0.05,
        'tp_bull_moderate_1': 0.03,
        'tp_bull_moderate_2': 0.07,
        'tp_bull_moderate_3': 0.12,
        'trailing_bull_moderate': 0.03,
        'tp_sideways_1': 0.02,
        'tp_sideways_2': 0.04,
        'tp_sideways_3': 0.06,
        'stop_loss': -0.015,
        'exit_fraction_1': 0.4,
        'exit_fraction_2': 0.3,
        'exit_fraction_3': 0.3,

        # Position Sizing
        'position_size': 0.5,

        # SIDEWAYS 전략
        'use_rsi_bb': True,
        'use_stoch': True,
        'use_volume_breakout': True,
        'rsi_bb_oversold': 30,
        'rsi_bb_overbought': 70,
        'stoch_oversold': 20,
        'stoch_overbought': 80,
        'volume_breakout_mult': 2.0
    }

    print("="*70)
    print("  v35 Optimized Strategy - 테스트")
    print("="*70)

    # 2024 데이터로 테스트
    with DataLoader('../../upbit_bitcoin.db') as loader:
        df = loader.load_timeframe('day', start_date='2024-01-01', end_date='2024-12-31')

    df = MarketAnalyzer.add_indicators(df, indicators=['rsi', 'macd', 'mfi', 'adx', 'atr', 'bb', 'stoch'])

    # 전략 테스트
    strategy = V35OptimizedStrategy(config)
    signals = []

    for i in range(30, min(100, len(df))):
        signal = strategy.execute(df, i)
        if signal['action'] != 'hold':
            signals.append({
                'date': df.iloc[i].name,
                'action': signal['action'],
                'reason': signal['reason'],
                'price': df.iloc[i]['close']
            })

    print(f"\n[시그널 발생: {len(signals)}개]")
    for sig in signals[:10]:
        print(f"  {sig['date']} | {sig['action']:4s} | {sig['reason']:30s} | {sig['price']:,.0f}원")

    print(f"\nv35 전략 테스트 완료!")
    print(f"다음 단계: Optuna 최적화 (500 trials)")
