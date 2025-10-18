#!/usr/bin/env python3
"""
strategy_cascade.py
멀티 타임프레임 Cascade 전략

핵심 로직:
1. DAY 레이어가 매수 포지션 보유 중 = 상승장
2. 상승장일 때만 다른 타임프레임 활성화
3. 각 레이어는 독립적으로 분할 매수/매도
4. Kelly Criterion으로 동적 포지션 사이징
"""

import sys
sys.path.append('../..')

import pandas as pd
import numpy as np
from typing import Dict, List, Optional
from layer_strategy import LayerStrategy
from kelly_calculator import KellyCalculator


class CascadeStrategy:
    """멀티 타임프레임 Cascade 전략"""

    def __init__(self, config: Dict):
        """
        Args:
            config: 전략 설정
        """
        self.config = config

        # 레이어별 전략 인스턴스
        self.layers: Dict[str, LayerStrategy] = {}

        for layer_name, layer_config in config['layers'].items():
            # 분할 매수/매도 설정
            layer_config['split_orders_enabled'] = config.get('split_orders', {}).get('enabled', True)

            # Kelly 활성화 여부
            kelly_enabled = config.get('kelly_criterion', {}).get('enabled', True)

            self.layers[layer_name] = LayerStrategy(
                layer_name=layer_name,
                config=layer_config['params'],
                kelly_enabled=kelly_enabled
            )

        # Kelly Calculator
        kelly_config = config.get('kelly_criterion', {})
        self.kelly_calculator = KellyCalculator(
            min_trades=kelly_config.get('min_trades_before_activation', 10),
            conservative_fraction=kelly_config.get('conservative_fraction', 0.5),
            max_position=kelly_config.get('max_position_fraction', 0.95),
            min_position=kelly_config.get('min_position_fraction', 0.20)
        )

        # 레이어별 거래 히스토리 (Kelly 계산용)
        self.trade_history: Dict[str, List[Dict]] = {layer: [] for layer in self.layers.keys()}

        # DAY 레이어 활성 상태
        self.day_position_active = False

    def generate_signals(
        self,
        dataframes: Dict[str, pd.DataFrame],
        tf_indices: Dict[str, int],
        current_time: pd.Timestamp,
        backtester,
        params: Dict = None
    ) -> List[Dict]:
        """
        전체 레이어 신호 생성

        Args:
            dataframes: {timeframe: DataFrame}
            tf_indices: {timeframe: current_index}
            current_time: 현재 시각
            backtester: MultiTimeframeBacktester 인스턴스
            params: 추가 파라미터

        Returns:
            신호 리스트 [{'layer': str, 'action': str, 'fraction': float, 'reason': str}, ...]
        """
        signals = []

        # 레이어 순서: DAY -> minute240 -> ... (DAY 먼저 처리)
        layer_order = ['day', 'minute240', 'minute60', 'minute30', 'minute15', 'minute5']

        for layer_name in layer_order:
            if layer_name not in self.layers:
                continue

            layer_config = self.config['layers'][layer_name]
            tf = layer_config['timeframe']

            # 해당 타임프레임 데이터 없으면 스킵
            if tf not in dataframes or tf not in tf_indices:
                continue

            # 레이어 활성화 조건 체크
            if not self._is_layer_enabled(layer_name):
                continue

            # 현재 인덱스
            i = tf_indices[tf]
            df = dataframes[tf]

            # 현재 자본 (레이어별)
            current_capital = backtester.cash_by_layer.get(layer_name, 0)

            # Kelly Fraction 계산
            kelly_fraction = None
            if self.layers[layer_name].kelly_enabled:
                kelly_fraction = self.kelly_calculator.get_position_fraction(
                    self.trade_history[layer_name],
                    default_fraction=layer_config['params']['position_fraction']
                )

            # 신호 생성
            signal = self.layers[layer_name].generate_signal(
                df=df,
                i=i,
                current_capital=current_capital,
                kelly_fraction=kelly_fraction
            )

            # 유효한 신호만 추가
            if signal['action'] in ['buy', 'sell']:
                signal['layer'] = layer_name
                signals.append(signal)

                # DAY 레이어 상태 업데이트
                if layer_name == 'day':
                    if signal['action'] == 'buy':
                        self.day_position_active = True
                    elif signal['action'] == 'sell':
                        self.day_position_active = False

        return signals

    def _is_layer_enabled(self, layer_name: str) -> bool:
        """레이어 활성화 여부 판단"""
        layer_config = self.config['layers'][layer_name]

        # DAY 레이어는 항상 활성화
        if layer_name == 'day':
            return True

        # DAY 포지션 활성화 시에만 다른 레이어 활성화
        if layer_config.get('enabled_when_day_active', False):
            if not self.day_position_active:
                return False

        # 최소 승률 조건 (minute15, minute5)
        min_win_rate = layer_config.get('min_win_rate', 0.0)
        if min_win_rate > 0.0:
            trades = self.trade_history[layer_name]
            if len(trades) >= 10:
                winning = [t for t in trades if t.get('profit_loss', 0) > 0]
                win_rate = len(winning) / len(trades)
                if win_rate < min_win_rate:
                    return False

        return True

    def on_trade_closed(self, layer_name: str, trade: Dict):
        """거래 종료 시 히스토리 업데이트"""
        if layer_name in self.trade_history:
            self.trade_history[layer_name].append(trade)

            # 최대 100개 거래만 유지 (메모리 절약)
            if len(self.trade_history[layer_name]) > 100:
                self.trade_history[layer_name] = self.trade_history[layer_name][-100:]

    def get_kelly_analysis(self) -> Dict[str, Dict]:
        """레이어별 Kelly 분석"""
        analysis = {}

        for layer_name, trades in self.trade_history.items():
            analysis[layer_name] = self.kelly_calculator.analyze_kelly(trades)

        return analysis

    def update_layer_params(self, layer_name: str, new_params: Dict):
        """레이어 파라미터 동적 업데이트 (Auto-tuning용)"""
        if layer_name in self.layers:
            self.layers[layer_name].update_params(new_params)


def cascade_strategy_wrapper(
    dataframes: Dict[str, pd.DataFrame],
    tf_indices: Dict[str, int],
    current_time: pd.Timestamp,
    backtester,
    params: Dict
) -> List[Dict]:
    """
    MultiTimeframeBacktester 호환 래퍼 함수

    Args:
        dataframes: {timeframe: DataFrame}
        tf_indices: {timeframe: current_index}
        current_time: 현재 시각
        backtester: MultiTimeframeBacktester 인스턴스
        params: {'strategy_instance': CascadeStrategy}

    Returns:
        신호 리스트
    """
    strategy: CascadeStrategy = params['strategy_instance']

    signals = strategy.generate_signals(
        dataframes=dataframes,
        tf_indices=tf_indices,
        current_time=current_time,
        backtester=backtester,
        params=params
    )

    # 레이어별 on_buy/on_sell 콜백 호출
    for signal in signals:
        layer_name = signal['layer']
        layer_strategy = strategy.layers[layer_name]

        if signal['action'] == 'buy':
            tf = strategy.config['layers'][layer_name]['timeframe']
            if tf in tf_indices:
                idx = tf_indices[tf]
                price = dataframes[tf].iloc[idx]['close']
                layer_strategy.on_buy(idx, price)

        elif signal['action'] == 'sell':
            layer_strategy.on_sell(signal['fraction'])

    return signals
