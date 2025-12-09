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
sys.path.append('../..')

from strategies.v34_supreme.market_classifier_v34 import MarketClassifierV34
from strategies.v35_optimized.dynamic_exit_manager import DynamicExitManager
from strategies.v35_optimized.sideways_enhanced import SidewaysEnhancedStrategies
from core.market_analyzer_v2 import MarketAnalyzerV2


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

        # AI Analyzer v2 초기화 (기본은 비활성화)
        ai_config = config.get('ai_analyzer', {})
        self.analyzer_v2 = MarketAnalyzerV2({
            'ai_mode': ai_config.get('enabled', False),
            'agents_enabled': ai_config.get('agents', ['trend']),
            'confidence_threshold': ai_config.get('confidence_threshold', 0.8)
        })
        self.ai_enabled = ai_config.get('enabled', False)
        self.ai_test_mode = ai_config.get('test_mode', False)  # True: 로그만 기록

        # AI 분석 히스토리 (디버깅/모니터링용)
        self.ai_analysis_history = []

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

        # 현재 시장 상태 분류 (기존 v34 classifier)
        prev_row = df.iloc[i-1] if i > 0 else None
        current_row = df.iloc[i]
        market_state = self.classifier.classify_market_state(current_row, prev_row)
        
        # AI 분석 추가 (10캔들마다 또는 중요 시점에)
        ai_confirmation = None
        confidence_boost = 1.0
        ai_reason = ""
        
        if self.ai_enabled and i % 10 == 0:
            try:
                ai_result = self.analyzer_v2.analyze_market_state(df.iloc[:i+1])
                ai_confidence = ai_result.get('confidence', 0.0)
                ai_market_state = ai_result.get('market_state', market_state)
                
                # AI 분석 기록 (모니터링용)
                self.ai_analysis_history.append({
                    'index': i,
                    'timestamp': current_row.name,
                    'v34_state': market_state,
                    'ai_state': ai_market_state,
                    'ai_confidence': ai_confidence,
                    'ai_result': ai_result
                })
                
                # 고신뢰도 AI 분석 활용
                if ai_confidence >= self.analyzer_v2.confidence_threshold:
                    if ai_market_state == market_state:
                        # AI가 기존 분석 확인 → 신뢰도 증가
                        confidence_boost = 1.2
                        ai_confirmation = 'CONFIRMED'
                        ai_reason = f"_AI_CONF_{ai_confidence:.2f}"
                    elif ai_confidence >= 0.9 and not self.ai_test_mode:
                        # AI 신뢰도 매우 높음 → 상태 보정 (test_mode가 아닐 때만)
                        market_state = ai_market_state
                        confidence_boost = 1.1
                        ai_confirmation = 'OVERRIDE'
                        ai_reason = f"_AI_OVER_{ai_confidence:.2f}"
                    elif self.ai_test_mode:
                        # test_mode: 로그만 기록
                        ai_reason = f"_AI_TEST_{ai_confidence:.2f}"
                        
            except Exception as e:
                # AI 분석 실패해도 기존 로직은 계속 실행
                print(f"AI 분석 오류 (무시): {e}")

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
                
                # AI 정보 추가
                if ai_reason:
                    exit_signal['reason'] = exit_signal.get('reason', '') + ai_reason
                if ai_confirmation:
                    exit_signal['ai_confirmation'] = ai_confirmation
                    
                return exit_signal

        # 포지션 없을 때: Entry 전략
        else:
            entry_signal = self._check_entry_conditions(df, i, market_state, prev_row)
            if entry_signal and entry_signal['action'] == 'buy':
                # AI 신뢰도 기반 포지션 크기 조정
                original_fraction = entry_signal.get('fraction', 0.5)
                if not self.ai_test_mode and confidence_boost > 1.0:
                    adjusted_fraction = min(1.0, original_fraction * confidence_boost)
                    entry_signal['fraction'] = adjusted_fraction
                
                self.in_position = True
                self.entry_price = current_row['close']
                self.entry_time = current_row.name
                self.entry_market_state = market_state
                self.entry_strategy = entry_signal.get('strategy', 'unknown')

                # Exit Manager 초기화
                self.exit_manager.set_entry(self.entry_price, market_state)
                
                # AI 정보 추가
                if ai_reason:
                    entry_signal['reason'] = entry_signal.get('reason', '') + ai_reason
                if ai_confirmation:
                    entry_signal['ai_confirmation'] = ai_confirmation
                    entry_signal['confidence_boost'] = confidence_boost

                return entry_signal

        reason = f'NO_SIGNAL_{market_state}'
        if ai_reason:
            reason += ai_reason
            
        return {'action': 'hold', 'reason': reason}

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
