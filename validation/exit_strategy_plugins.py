#!/usr/bin/env python3
"""
Exit Strategy Plugins
======================
청산 전략 플러그인 모음

작성일: 2025-10-21
버전: 1.0

플러그인:
- FixedExitPlugin: 고정 TP/SL (v30, v31 스타일)
- DynamicExitPlugin: 동적 TP/SL (v35 스타일, 시장 상태 기반)
- TrailingStopPlugin: Trailing Stop (v35 DynamicExitManager)
- TimeoutExitPlugin: 시간 기반 청산
- CompositeExitPlugin: 복합 청산 (여러 플러그인 조합)
"""

from typing import Dict, Optional, Any
from dataclasses import dataclass
import pandas as pd


# ========================================
# Base Exit Plugin
# ========================================

class BaseExitPlugin:
    """청산 전략 플러그인 베이스 클래스"""

    def check_exit(
        self,
        position: Any,
        current_bar: pd.Series,
        timestamp: pd.Timestamp,
        config: Dict
    ) -> Dict[str, Any]:
        """
        청산 조건 체크

        Args:
            position: Position 객체
            current_bar: 현재 캔들 (Series with open, high, low, close)
            timestamp: 현재 시각
            config: 청산 설정

        Returns:
            {
                'should_exit': bool,
                'exit_price': float (if should_exit),
                'reason': str (if should_exit)
            }
        """
        raise NotImplementedError


# ========================================
# Fixed TP/SL Plugin
# ========================================

class FixedExitPlugin(BaseExitPlugin):
    """
    고정 익절/손절 플러그인

    기존 전략: v30, v31
    설정 예시:
    {
        "enabled": true,
        "take_profit": 0.05,  # 5%
        "stop_loss": 0.02      # 2%
    }
    """

    def check_exit(
        self,
        position,
        current_bar,
        timestamp,
        config
    ) -> Dict[str, Any]:
        if not config.get('enabled', False):
            return {'should_exit': False}

        take_profit = config.get('take_profit', 0.05)
        stop_loss = config.get('stop_loss', 0.02)

        entry_price = position.entry_price
        current_price = current_bar['close']

        profit_pct = (current_price - entry_price) / entry_price

        # 익절 체크
        if profit_pct >= take_profit:
            return {
                'should_exit': True,
                'exit_price': current_price,
                'reason': f'TAKE_PROFIT ({profit_pct*100:.2f}%)'
            }

        # 손절 체크
        if profit_pct <= -stop_loss:
            return {
                'should_exit': True,
                'exit_price': current_price,
                'reason': f'STOP_LOSS ({profit_pct*100:.2f}%)'
            }

        return {'should_exit': False}


# ========================================
# Dynamic TP/SL Plugin
# ========================================

class DynamicExitPlugin(BaseExitPlugin):
    """
    동적 익절/손절 플러그인 (시장 상태 기반)

    기존 전략: v35
    설정 예시:
    {
        "enabled": true,
        "market_based": true,
        "tp_by_market": {
            "BULL_STRONG": [0.10, 0.15, 0.20],
            "BULL_MODERATE": [0.07, 0.10, 0.15],
            "SIDEWAYS": [0.03, 0.05, 0.08],
            "BEAR": [0.02, 0.03, 0.05]
        },
        "sl_multiplier": 0.5  # TP의 50%
    }
    """

    def __init__(self):
        self.tp_levels_hit = {}  # position_id -> [TP1 hit, TP2 hit, TP3 hit]

    def check_exit(
        self,
        position,
        current_bar,
        timestamp,
        config
    ) -> Dict[str, Any]:
        if not config.get('enabled', False):
            return {'should_exit': False}

        # 시장 상태 가져오기
        market_state = getattr(position, 'signal_metadata', {}).get('market_state', 'SIDEWAYS')

        # TP 레벨 선택
        tp_by_market = config.get('tp_by_market', {})
        tp_levels = tp_by_market.get(market_state, [0.05, 0.10, 0.15])

        entry_price = position.entry_price
        current_price = current_bar['close']
        profit_pct = (current_price - entry_price) / entry_price

        # 손절
        sl_multiplier = config.get('sl_multiplier', 0.5)
        stop_loss = tp_levels[0] * sl_multiplier

        if profit_pct <= -stop_loss:
            return {
                'should_exit': True,
                'exit_price': current_price,
                'reason': f'DYNAMIC_SL ({profit_pct*100:.2f}%)'
            }

        # 익절 (TP3까지 체크)
        for i, tp in enumerate(tp_levels):
            if profit_pct >= tp:
                return {
                    'should_exit': True,
                    'exit_price': current_price,
                    'reason': f'DYNAMIC_TP{i+1} ({profit_pct*100:.2f}%)'
                }

        return {'should_exit': False}


# ========================================
# Trailing Stop Plugin
# ========================================

class TrailingStopPlugin(BaseExitPlugin):
    """
    Trailing Stop 플러그인

    기존 전략: v35
    설정 예시:
    {
        "enabled": true,
        "activation": 0.02,   # 2% 수익 후 활성화
        "distance": 0.005      # 고점 대비 -0.5%
    }
    """

    def check_exit(
        self,
        position,
        current_bar,
        timestamp,
        config
    ) -> Dict[str, Any]:
        if not config.get('enabled', False):
            return {'should_exit': False}

        activation = config.get('activation', 0.02)
        distance = config.get('distance', 0.005)

        entry_price = position.entry_price
        peak_price = position.peak_price
        current_price = current_bar['close']

        profit_pct = (current_price - entry_price) / entry_price

        # Trailing Stop 활성화 체크
        if profit_pct < activation:
            return {'should_exit': False}

        # Peak 대비 하락 체크
        drop_from_peak = (peak_price - current_price) / peak_price

        if drop_from_peak >= distance:
            return {
                'should_exit': True,
                'exit_price': current_price,
                'reason': f'TRAILING_STOP (peak {peak_price:.0f}, drop {drop_from_peak*100:.2f}%)'
            }

        return {'should_exit': False}


# ========================================
# Timeout Exit Plugin
# ========================================

class TimeoutExitPlugin(BaseExitPlugin):
    """
    시간 기반 청산 플러그인

    기존 전략: v31
    설정 예시:
    {
        "enabled": true,
        "hours": 72  # 3일, null이면 holding_period 사용
    }
    """

    def check_exit(
        self,
        position,
        current_bar,
        timestamp,
        config
    ) -> Dict[str, Any]:
        if not config.get('enabled', False):
            return {'should_exit': False}

        timeout_hours = config.get('hours')

        if timeout_hours is None:
            # holding_period가 timeout 역할 (UniversalEvaluationEngine에서 처리)
            return {'should_exit': False}

        holding_hours = (timestamp - position.entry_time).total_seconds() / 3600

        if holding_hours >= timeout_hours:
            return {
                'should_exit': True,
                'exit_price': current_bar['close'],
                'reason': f'TIMEOUT ({holding_hours:.1f}h)'
            }

        return {'should_exit': False}


# ========================================
# Composite Exit Plugin
# ========================================

class CompositeExitPlugin(BaseExitPlugin):
    """
    복합 청산 플러그인 (여러 플러그인 조합)

    기존 전략: v35 (fixed + dynamic + trailing)
    설정 예시:
    {
        "type": "composite",
        "fixed": {"enabled": true, "take_profit": 0.05, "stop_loss": 0.02},
        "dynamic": {"enabled": true, ...},
        "trailing": {"enabled": true, "activation": 0.02, "distance": 0.005}
    }
    """

    def __init__(self, plugin_registry: Dict[str, BaseExitPlugin]):
        """
        Args:
            plugin_registry: {'fixed': FixedExitPlugin(), 'dynamic': ...}
        """
        self.plugins = plugin_registry

    def check_exit(
        self,
        position,
        current_bar,
        timestamp,
        config
    ) -> Dict[str, Any]:
        """
        모든 활성화된 플러그인 체크, 하나라도 청산 조건이면 청산

        우선순위:
        1. Stop Loss (고정/동적)
        2. Take Profit (고정/동적)
        3. Trailing Stop
        4. Timeout
        """
        # 1. Fixed SL 체크 (최우선)
        if 'fixed' in config and config['fixed'].get('enabled'):
            result = self.plugins['fixed'].check_exit(position, current_bar, timestamp, config['fixed'])
            if result['should_exit'] and 'STOP_LOSS' in result['reason']:
                return result

        # 2. Dynamic SL 체크
        if 'dynamic' in config and config['dynamic'].get('enabled'):
            result = self.plugins['dynamic'].check_exit(position, current_bar, timestamp, config['dynamic'])
            if result['should_exit'] and 'SL' in result['reason']:
                return result

        # 3. Fixed TP 체크
        if 'fixed' in config and config['fixed'].get('enabled'):
            result = self.plugins['fixed'].check_exit(position, current_bar, timestamp, config['fixed'])
            if result['should_exit'] and 'TAKE_PROFIT' in result['reason']:
                return result

        # 4. Dynamic TP 체크
        if 'dynamic' in config and config['dynamic'].get('enabled'):
            result = self.plugins['dynamic'].check_exit(position, current_bar, timestamp, config['dynamic'])
            if result['should_exit'] and 'TP' in result['reason']:
                return result

        # 5. Trailing Stop 체크
        if 'trailing' in config and config['trailing'].get('enabled'):
            result = self.plugins['trailing'].check_exit(position, current_bar, timestamp, config['trailing'])
            if result['should_exit']:
                return result

        # 6. Timeout 체크
        if 'timeout' in config and config['timeout'].get('enabled'):
            result = self.plugins['timeout'].check_exit(position, current_bar, timestamp, config['timeout'])
            if result['should_exit']:
                return result

        return {'should_exit': False}


# ========================================
# 미래 확장 예시
# ========================================

class MLConfidenceExitPlugin(BaseExitPlugin):
    """
    ML 신뢰도 기반 청산 (미래 전략용)

    설정 예시:
    {
        "enabled": true,
        "min_confidence": 0.3  # 신뢰도 0.3 이하면 청산
    }
    """

    def check_exit(
        self,
        position,
        current_bar,
        timestamp,
        config
    ) -> Dict[str, Any]:
        if not config.get('enabled', False):
            return {'should_exit': False}

        # ML 모델로 현재 신뢰도 재평가 (미래 구현)
        current_confidence = self._evaluate_confidence(current_bar)

        min_confidence = config.get('min_confidence', 0.3)

        if current_confidence < min_confidence:
            return {
                'should_exit': True,
                'exit_price': current_bar['close'],
                'reason': f'ML_CONFIDENCE_DROP ({current_confidence:.2f})'
            }

        return {'should_exit': False}

    def _evaluate_confidence(self, bar):
        """ML 모델로 신뢰도 재평가 (미래 구현)"""
        # TODO: ML 모델 통합
        return 0.5


# ========================================
# 플러그인 레지스트리 (간편 사용)
# ========================================

def get_default_plugins():
    """기본 플러그인 세트 반환"""
    plugins = {
        'fixed': FixedExitPlugin(),
        'dynamic': DynamicExitPlugin(),
        'trailing': TrailingStopPlugin(),
        'timeout': TimeoutExitPlugin()
    }

    plugins['composite'] = CompositeExitPlugin(plugins)

    return plugins
