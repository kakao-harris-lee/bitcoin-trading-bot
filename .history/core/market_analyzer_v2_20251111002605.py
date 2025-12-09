#!/usr/bin/env python3
"""
market_analyzer_v2.py
AI Agent 기반 시장 분석 엔진 - Phase 1

Phase 1 목표:
1. 기존 market_analyzer.py 완전 호환
2. 기본 AI Agent 구조 구축
3. v35_optimized 등 기존 전략에서 문제없이 동작
4. 확장 가능한 아키텍처 준비
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Any
from pathlib import Path
import logging

# 기존 market_analyzer 호환을 위한 임포트
try:
    import talib
    TALIB_AVAILABLE = True
except ImportError:
    TALIB_AVAILABLE = False
    print("⚠️  TA-Lib not installed. Install: brew install ta-lib && pip install TA-Lib")

# 로깅 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class MarketAnalyzerV2:
    """
    AI Agent 기반 시장 분석 엔진 v2

    Phase 1: 기존 호환성 유지하면서 AI 기반 구조 준비
    """

    def __init__(self, config: Optional[Dict] = None):
        """
        초기화

        Args:
            config: 설정 딕셔너리
                {
                    'ai_mode': bool (기본 False - 기존 TA-Lib 모드)
                    'agents_enabled': List[str] (활성화할 에이전트)
                    'confidence_threshold': float (신뢰도 임계값)
                    'timeframes': List[str] (분석 타임프레임)
                }
        """
        self.config = config or {}

        # 기본 설정
        self.ai_mode = self.config.get('ai_mode', False)
        self.agents_enabled = self.config.get('agents_enabled', [])
        self.confidence_threshold = self.config.get('confidence_threshold', 0.7)
        self.timeframes = self.config.get('timeframes', ['day'])

        # AI Agents 초기화 (Phase 1에서는 기본 구조만)
        self.agents = {}
        if self.ai_mode:
            self._initialize_agents()

        logger.info(f"MarketAnalyzerV2 초기화 완료 - AI 모드: {self.ai_mode}")

    def _initialize_agents(self):
        """AI Agents 초기화 (Phase 1: 기본 구조)"""
        # Phase 1에서는 placeholder agents
        if 'trend' in self.agents_enabled:
            self.agents['trend'] = BasicTrendAgent()
        if 'volatility' in self.agents_enabled:
            self.agents['volatility'] = BasicVolatilityAgent()

        logger.info(f"Agents 초기화 완료: {list(self.agents.keys())}")

    # =================================================================
    # 기존 market_analyzer.py 완전 호환 메소드들
    # =================================================================

    @staticmethod
    def add_indicators(df: pd.DataFrame, indicators: list = None) -> pd.DataFrame:
        """
        기술 지표 추가 (기존 market_analyzer.py 완전 호환)

        Args:
            df: 가격 데이터 (open, high, low, close, volume)
            indicators: 추가할 지표 리스트 ['rsi', 'macd', 'bb', ...]

        Returns:
            지표가 추가된 DataFrame
        """
        if not TALIB_AVAILABLE:
            logger.warning("TA-Lib 없음, 원본 DataFrame 반환")
            return df

        df = df.copy()

        if indicators is None:
            indicators = ['sma', 'rsi', 'macd']

        # SMA
        if 'sma' in indicators:
            df['sma_20'] = talib.SMA(df['close'], timeperiod=20)
            df['sma_50'] = talib.SMA(df['close'], timeperiod=50)

        # EMA
        if 'ema' in indicators:
            df['ema_12'] = talib.EMA(df['close'], timeperiod=12)
            df['ema_26'] = talib.EMA(df['close'], timeperiod=26)

        # RSI
        if 'rsi' in indicators:
            df['rsi'] = talib.RSI(df['close'], timeperiod=14)

        # MACD
        if 'macd' in indicators:
            macd, signal, hist = talib.MACD(df['close'])
            df['macd'] = macd
            df['macd_signal'] = signal
            df['macd_hist'] = hist

        # Bollinger Bands
        if 'bb' in indicators:
            bb_upper, bb_middle, bb_lower = talib.BBANDS(df['close'])
            df['bb_upper'] = bb_upper
            df['bb_middle'] = bb_middle
            df['bb_lower'] = bb_lower
            df['bb_width'] = (bb_upper - bb_lower) / bb_middle
            df['bb_position'] = (df['close'] - bb_lower) / (bb_upper - bb_lower)

        # Stochastic
        if 'stoch' in indicators:
            k, d = talib.STOCH(df['high'], df['low'], df['close'])
            df['stoch_k'] = k
            df['stoch_d'] = d

        # Williams %R
        if 'willr' in indicators:
            df['willr'] = talib.WILLR(df['high'], df['low'], df['close'])

        # ATR
        if 'atr' in indicators:
            df['atr'] = talib.ATR(df['high'], df['low'], df['close'])

        # ADX
        if 'adx' in indicators:
            df['adx'] = talib.ADX(df['high'], df['low'], df['close'])

        # Volume indicators
        if 'volume' in indicators:
            df['volume_sma'] = talib.SMA(df['volume'], timeperiod=20)
            df['volume_ratio'] = df['volume'] / df['volume_sma']

        logger.debug(f"지표 추가 완료: {indicators}")
        return df

    # =================================================================
    # 새로운 AI 기반 분석 메소드들 (Phase 1: 기본 구조)
    # =================================================================

    def analyze_market_state(self, df: pd.DataFrame) -> Dict[str, Any]:
        """
        AI 기반 시장 상태 분석 (새로운 기능)

        Args:
            df: 지표가 포함된 가격 데이터

        Returns:
            {
                'market_state': str (v35 호환 7-level),
                'market_state_v2': Dict (AI 확장 분석),
                'confidence': float (0.0-1.0),
                'agent_results': Dict,
                'timestamp': str
            }
        """
        if not self.ai_mode or len(self.agents) == 0:
            # AI 모드가 아니면 기본 분류
            return self._basic_market_classification(df)

        # AI Agents 결과 수집
        agent_results = {}
        for agent_name, agent in self.agents.items():
            try:
                agent_results[agent_name] = agent.analyze(df)
            except Exception as e:
                logger.warning(f"Agent {agent_name} 분석 실패: {e}")
                agent_results[agent_name] = {'error': str(e)}

        # 결과 통합 (Phase 1: 기본 로직)
        market_state = self._integrate_agent_results(agent_results, df)

        return {
            'market_state': market_state['v35_compatible'],
            'market_state_v2': market_state,
            'confidence': market_state.get('confidence', 0.5),
            'agent_results': agent_results,
            'timestamp': pd.Timestamp.now().isoformat()
        }

    def _basic_market_classification(self, df: pd.DataFrame) -> Dict[str, Any]:
        """기본 시장 분류 (AI 없이)"""
        if len(df) < 20:
            state = 'SIDEWAYS_NEUTRAL'
        else:
            # 간단한 SMA 기반 분류
            current_price = df['close'].iloc[-1]
            sma_20 = df['close'].rolling(20).mean().iloc[-1]
            sma_50 = df['close'].rolling(50).mean().iloc[-1] if len(df) >= 50 else sma_20

            if current_price > sma_20 > sma_50:
                state = 'BULL_STRONG'
            elif current_price > sma_20:
                state = 'BULL_WEAK'
            elif current_price < sma_20 < sma_50:
                state = 'BEAR_STRONG'
            elif current_price < sma_20:
                state = 'BEAR_WEAK'
            else:
                state = 'SIDEWAYS_NEUTRAL'

        return {
            'market_state': state,
            'market_state_v2': {'basic_classification': state},
            'confidence': 0.5,
            'agent_results': {},
            'timestamp': pd.Timestamp.now().isoformat()
        }

    def _integrate_agent_results(self, agent_results: Dict, df: pd.DataFrame) -> Dict[str, Any]:
        """Agent 결과 통합 (Phase 1: 기본 로직)"""
        # Phase 1에서는 첫 번째 agent 결과 우선 사용
        if agent_results:
            first_result = list(agent_results.values())[0]
            if 'error' not in first_result:
                return {
                    'v35_compatible': first_result.get('market_state', 'SIDEWAYS_NEUTRAL'),
                    'confidence': first_result.get('confidence', 0.5),
                    'ai_analysis': first_result
                }

        # Fallback to basic
        return self._basic_market_classification(df)


class BasicTrendAgent:
    """기본 트렌드 분석 Agent (Phase 1)"""

    def __init__(self):
        self.name = "BasicTrendAgent"

    def analyze(self, df: pd.DataFrame) -> Dict[str, Any]:
        """기본 트렌드 분석"""
        if len(df) < 50:
            return {
                'market_state': 'SIDEWAYS_NEUTRAL',
                'confidence': 0.3,
                'trend_strength': 0.0
            }

        # SMA 기반 트렌드 분석
        sma_20 = df['close'].rolling(20).mean().iloc[-1]
        sma_50 = df['close'].rolling(50).mean().iloc[-1]
        current_price = df['close'].iloc[-1]

        # 트렌드 강도 계산
        trend_strength = abs(sma_20 - sma_50) / sma_50

        # 상태 분류
        if current_price > sma_20 > sma_50:
            if trend_strength > 0.05:
                state = 'BULL_STRONG'
                confidence = 0.8
            else:
                state = 'BULL_WEAK'
                confidence = 0.6
        elif current_price < sma_20 < sma_50:
            if trend_strength > 0.05:
                state = 'BEAR_STRONG'
                confidence = 0.8
            else:
                state = 'BEAR_WEAK'
                confidence = 0.6
        else:
            state = 'SIDEWAYS_NEUTRAL'
            confidence = 0.5

        return {
            'market_state': state,
            'confidence': confidence,
            'trend_strength': trend_strength,
            'sma_20': sma_20,
            'sma_50': sma_50
        }


class BasicVolatilityAgent:
    """기본 변동성 분석 Agent (Phase 1)"""

    def __init__(self):
        self.name = "BasicVolatilityAgent"

    def analyze(self, df: pd.DataFrame) -> Dict[str, Any]:
        """기본 변동성 분석"""
        if len(df) < 20:
            return {
                'volatility_regime': 'NORMAL',
                'confidence': 0.3
            }

        # ATR 기반 변동성 계산
        returns = df['close'].pct_change().fillna(0)
        volatility = returns.rolling(20).std().iloc[-1]
        avg_volatility = returns.rolling(100).std().mean() if len(df) >= 100 else volatility

        # 변동성 구분
        vol_ratio = volatility / avg_volatility if avg_volatility > 0 else 1.0

        if vol_ratio > 1.5:
            regime = 'HIGH'
            confidence = 0.7
        elif vol_ratio < 0.7:
            regime = 'LOW'
            confidence = 0.7
        else:
            regime = 'NORMAL'
            confidence = 0.6

        return {
            'volatility_regime': regime,
            'volatility_ratio': vol_ratio,
            'current_volatility': volatility,
            'avg_volatility': avg_volatility,
            'confidence': confidence
        }


# 기존 호환성을 위한 클래스 (legacy)
class MarketAnalyzer:
    """기존 market_analyzer.py 호환 클래스"""

    @staticmethod
    def add_indicators(df: pd.DataFrame, indicators: list = None) -> pd.DataFrame:
        """기존 호환성을 위해 v2로 위임"""
        return MarketAnalyzerV2.add_indicators(df, indicators)


if __name__ == "__main__":
    # 테스트
    print("MarketAnalyzerV2 Phase 1 테스트")

    # 기본 모드 테스트
    analyzer_basic = MarketAnalyzerV2()
    print(f"기본 모드: {analyzer_basic.ai_mode}")

    # AI 모드 테스트
    analyzer_ai = MarketAnalyzerV2({
        'ai_mode': True,
        'agents_enabled': ['trend', 'volatility']
    })
    print(f"AI 모드: {analyzer_ai.ai_mode}")
    print(f"활성화된 Agents: {list(analyzer_ai.agents.keys())}")

    # 더미 데이터로 테스트
    import numpy as np
    dates = pd.date_range('2024-01-01', periods=100, freq='D')
    prices = 50000 + np.cumsum(np.random.randn(100) * 1000)

    test_df = pd.DataFrame({
        'timestamp': dates,
        'open': prices,
        'high': prices * 1.02,
        'low': prices * 0.98,
        'close': prices,
        'volume': np.random.randint(1000, 10000, 100)
    })

    # 지표 추가 테스트
    test_df = analyzer_ai.add_indicators(test_df, ['sma', 'rsi'])
    print(f"추가된 컬럼: {[col for col in test_df.columns if col not in ['timestamp', 'open', 'high', 'low', 'close', 'volume']]}")

    # AI 분석 테스트
    result = analyzer_ai.analyze_market_state(test_df)
    print(f"분석 결과: {result['market_state']}")
    print(f"신뢰도: {result['confidence']:.2f}")

    print("\n✅ Phase 1 기본 구조 테스트 완료!")