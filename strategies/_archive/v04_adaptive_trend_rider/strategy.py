#!/usr/bin/env python3
"""
strategy.py
v04 전략: Adaptive Trend Rider

핵심 전략:
1. Day 타임프레임으로 시장 상태 분류 (Strong Bull / Moderate Bull / Neutral-Bear)
2. 4개 신호 투표 시스템 (RSI, MACD, BB, Price Drop)
3. 시장 상태별 적응형 청산 (Trailing Stop, Take Profit, Stop Loss)
4. 변동성 기반 포지션 사이징 (ATR + Kelly)
5. 피라미딩 (Strong Bull 시 추가 매수)
"""

import sys
sys.path.append('../..')

import pandas as pd
import numpy as np
from typing import Dict, Optional

from regime_classifier import RegimeClassifier
from signal_ensemble import SignalEnsemble
from exit_manager import ExitManager
from position_sizer import PositionSizer


class AdaptiveTrendRiderStrategy:
    """v04: 적응형 추세 추종 전략"""

    def __init__(self, config: dict, df_day: pd.DataFrame):
        """
        Args:
            config: config.json 내용
            df_day: Day 타임프레임 데이터 (지표 포함)
        """
        self.config = config
        self.df_day = df_day

        # === 모듈 초기화 ===

        # 1. 시장 상태 분류기
        self.regime_classifier = RegimeClassifier(
            strong_bull_adx=config['regime']['strong_bull_adx'],
            moderate_bull_adx=config['regime']['moderate_bull_adx'],
            bull_return_threshold=config['regime']['bull_return_threshold'],
            recent_period=config['regime']['recent_period']
        )

        # 2. 신호 앙상블
        self.signal_ensemble = SignalEnsemble(
            rsi_threshold=config['signals']['rsi_threshold'],
            price_drop_threshold=config['signals']['price_drop_threshold'],
            lookback_period=config['signals']['lookback_period']
        )

        # 3. 청산 관리자
        self.exit_manager = ExitManager()

        # 4. 포지션 사이징
        self.position_sizer = PositionSizer(
            base_kelly_fraction=config['position_sizing']['base_kelly_fraction'],
            min_fraction=config['position_sizing']['min_fraction'],
            max_fraction=config['position_sizing']['max_fraction'],
            risk_per_trade=config['position_sizing']['risk_per_trade']
        )

        # === 상태 추적 ===
        self.position = None  # None | 'long'
        self.pyramided = False  # 피라미딩 여부 (1회만 허용)
        self.current_regime = 'neutral_bear'

    def generate_signal(
        self,
        df_trade: pd.DataFrame,
        i: int,
        current_capital: float
    ) -> Dict:
        """
        매 캔들마다 호출되는 신호 생성 함수

        Args:
            df_trade: 거래 타임프레임 데이터 (minute240 등, day_idx 포함)
            i: 현재 인덱스
            current_capital: 현재 자본

        Returns:
            {
                'action': 'buy' | 'sell' | 'hold',
                'fraction': float (0~1),
                'reason': str
            }
        """
        # === 최소 데이터 확보 ===
        if i < 50:
            return {'action': 'hold', 'fraction': 0.0, 'reason': 'insufficient_data'}

        # === Day 인덱스 확인 ===
        day_idx = int(df_trade.iloc[i]['day_idx'])
        if day_idx == -1 or day_idx >= len(self.df_day):
            return {'action': 'hold', 'fraction': 0.0, 'reason': 'invalid_day_idx'}

        # === 1. 시장 상태 분류 (Day 타임프레임) ===
        regime_info = self.regime_classifier.classify(self.df_day, day_idx)
        regime = regime_info['regime']
        self.current_regime = regime

        # 시장 상태별 파라미터
        regime_params = self.regime_classifier.get_regime_params(regime)

        # === 포지션 없을 때: 매수 신호 ===
        if self.position is None:
            # 2. 매수 신호 생성 (4개 투표)
            entry_signals = self.signal_ensemble.generate_signals(df_trade, i)

            # 3. 투표 수 확인 (시장 상태별 요구 신호 수)
            required_votes = regime_params['entry_signals_needed']

            if self.signal_ensemble.should_buy(entry_signals, required_votes):
                # 4. 포지션 사이징
                position_info = self.position_sizer.calculate_position_size(
                    df_trade,
                    i,
                    regime,
                    current_capital,
                    stop_loss_pct=regime_params['stop_loss']
                )

                return {
                    'action': 'buy',
                    'fraction': position_info['fraction'],
                    'reason': (
                        f"{regime} | Signals({entry_signals['vote_count']}/{required_votes}) | "
                        f"{entry_signals['details']} | {position_info['reason']}"
                    ),
                    'regime': regime,
                    'regime_params': regime_params
                }

        # === 포지션 있을 때: 매도 신호 또는 피라미딩 ===
        elif self.position == 'long':
            current_price = df_trade.iloc[i]['close']

            # 5. 매도 신호 확인
            exit_signals = self.signal_ensemble.generate_exit_signals(df_trade, i)
            exit_decision = self.exit_manager.check_exit(
                df_trade, i, regime_params, exit_signals
            )

            if exit_decision['should_exit']:
                return {
                    'action': 'sell',
                    'fraction': exit_decision['fraction'],
                    'reason': f"{regime} | {exit_decision['reason']}"
                }

            # 6. 피라미딩 확인 (Strong Bull + 아직 피라미딩 안 함)
            if (regime == 'strong_bull' and
                regime_params['pyramid_enabled'] and
                not self.pyramided):

                pnl_ratio = (current_price - self.exit_manager.entry_price) / self.exit_manager.entry_price
                existing_position_size = current_capital * 0.3  # 예상값 (실제는 Backtester에서 관리)

                pyramid_info = self.position_sizer.calculate_pyramid_size(
                    df_trade, i, current_capital, existing_position_size, pnl_ratio
                )

                if pyramid_info['should_pyramid']:
                    self.pyramided = True
                    return {
                        'action': 'buy',
                        'fraction': pyramid_info['fraction'],
                        'reason': f"{regime} | {pyramid_info['reason']}"
                    }

        # 홀드
        return {'action': 'hold', 'fraction': 0.0, 'reason': f'{regime} | no_signal'}

    def on_buy(
        self,
        idx: int,
        price: float,
        regime_params: Dict
    ):
        """매수 체결 시 호출"""
        if self.position is None:
            # 신규 진입
            self.position = 'long'
            self.pyramided = False
            self.exit_manager.on_entry(idx, price, regime_params)
        # 피라미딩은 추가 진입만 (exit_manager는 갱신하지 않음)

    def on_sell(self):
        """매도 체결 시 호출"""
        self.position = None
        self.pyramided = False
        self.exit_manager.on_exit()


def v04_strategy_wrapper(df_trade, i, params):
    """
    Backtester 호환 래퍼 함수

    Args:
        df_trade: 거래 타임프레임 데이터 (day_idx 포함)
        i: 현재 인덱스
        params: {
            'strategy_instance': AdaptiveTrendRiderStrategy 인스턴스,
            'backtester': Backtester 인스턴스
        }

    Returns:
        {'action': 'buy'|'sell'|'hold', 'fraction': float}
    """
    strategy = params['strategy_instance']
    backtester = params['backtester']

    # 현재 자본 = 현금 + 포지션 가치
    current_capital = backtester.cash + backtester.position_value

    signal = strategy.generate_signal(df_trade, i, current_capital)

    # 매수/매도 시 상태 업데이트
    if signal['action'] == 'buy':
        regime_params = signal.get('regime_params')
        if regime_params is None:
            # 피라미딩 케이스 (regime_params 없음)
            regime_params = strategy.regime_classifier.get_regime_params(strategy.current_regime)
        strategy.on_buy(i, df_trade.iloc[i]['close'], regime_params)

    elif signal['action'] == 'sell':
        strategy.on_sell()

    return signal
