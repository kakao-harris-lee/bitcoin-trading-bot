#!/usr/bin/env python3
"""
Layer 3: Adaptive Position Sizing (Kelly Criterion)
- Half-Kelly (보수적 접근)
- 최근 50거래 기준 동적 계산
- 최소 10%, 최대 50% 범위 제한
"""

import numpy as np


class Layer3PositionSizer:
    """Kelly Criterion 기반 Position Sizing"""

    def __init__(self, config):
        self.config = config['layer3_kelly_criterion']

        self.lookback_trades = self.config['lookback_trades']
        self.min_trades_required = self.config['min_trades_required']
        self.default_size = self.config['default_size']

    def calculate_position_size(self, trade_history, layer, kelly_range):
        """
        Kelly Criterion으로 Position Size 계산

        Args:
            trade_history: 거래 이력 리스트
            layer: 레이어 번호 (1 or 2)
            kelly_range: [min, max] 범위

        Returns:
            position_size (0.0-1.0)
        """
        # 레이어별 거래만 필터링
        layer_trades = [t for t in trade_history if t.get('layer') == layer]

        # 최소 거래 수 미달 시 default
        if len(layer_trades) < self.min_trades_required:
            return self.default_size

        # 최근 N개 거래만 사용
        recent_trades = layer_trades[-self.lookback_trades:]

        returns = [t['return'] for t in recent_trades]
        wins = [r for r in returns if r > 0]
        losses = [r for r in returns if r < 0]

        if not wins or not losses:
            return self.default_size

        # Kelly Criterion 계산
        win_rate = len(wins) / len(returns)
        avg_win = np.mean(wins)
        avg_loss = abs(np.mean(losses))

        if avg_loss == 0:
            return self.default_size

        win_loss_ratio = avg_win / avg_loss

        # Kelly% = W - [(1-W) / R]
        # W = Win Rate
        # R = Win/Loss Ratio
        kelly_pct = win_rate - ((1 - win_rate) / win_loss_ratio)

        # Half-Kelly (보수적)
        half_kelly = kelly_pct * 0.5

        # 범위 제한
        min_size, max_size = kelly_range
        position_size = np.clip(half_kelly, min_size, max_size)

        return position_size

    def calculate_all_layers(self, layer1_trades, layer2_m60_trades, layer2_m240_trades, config):
        """
        모든 레이어의 Position Size 계산

        Args:
            layer1_trades: Layer 1 거래 이력
            layer2_m60_trades: Layer 2 Minute60 거래 이력
            layer2_m240_trades: Layer 2 Minute240 거래 이력
            config: 전체 설정

        Returns:
            dict: {'layer1': size, 'layer2_m60': size, 'layer2_m240': size}
        """
        layer1_config = config['layer1_master']
        layer2_m60_config = config['layer2_scalping']['minute60']
        layer2_m240_config = config['layer2_scalping']['minute240']

        return {
            'layer1': self.calculate_position_size(
                layer1_trades,
                layer=1,
                kelly_range=layer1_config['kelly_range']
            ),
            'layer2_m60': self.calculate_position_size(
                layer2_m60_trades,
                layer=2,
                kelly_range=layer2_m60_config['kelly_range']
            ),
            'layer2_m240': self.calculate_position_size(
                layer2_m240_trades,
                layer=2,
                kelly_range=layer2_m240_config['kelly_range']
            )
        }

    def get_statistics(self, trade_history, layer):
        """Kelly 계산에 사용된 통계 반환 (디버깅용)"""
        layer_trades = [t for t in trade_history if t.get('layer') == layer]

        if len(layer_trades) < self.min_trades_required:
            return None

        recent_trades = layer_trades[-self.lookback_trades:]
        returns = [t['return'] for t in recent_trades]
        wins = [r for r in returns if r > 0]
        losses = [r for r in returns if r < 0]

        if not wins or not losses:
            return None

        win_rate = len(wins) / len(returns)
        avg_win = np.mean(wins)
        avg_loss = abs(np.mean(losses))
        win_loss_ratio = avg_win / avg_loss if avg_loss > 0 else 0

        kelly_pct = win_rate - ((1 - win_rate) / win_loss_ratio) if win_loss_ratio > 0 else 0
        half_kelly = kelly_pct * 0.5

        return {
            'total_trades': len(recent_trades),
            'win_rate': win_rate,
            'avg_win': avg_win,
            'avg_loss': avg_loss,
            'win_loss_ratio': win_loss_ratio,
            'kelly_pct': kelly_pct,
            'half_kelly': half_kelly
        }
