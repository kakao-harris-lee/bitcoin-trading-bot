#!/usr/bin/env python3
"""
v37 Supreme Market Classifier
선행 지표 기반 5단계 시장 분류

핵심 개선:
1. 선행 지표 사용 (20일 MA 기울기, 실시간 변동성)
2. 5단계 정밀 분류 (BULL_STRONG/MODERATE, SIDEWAYS, BEAR_MODERATE/STRONG)
3. 동적 임계값 (시장 상황별 자동 조정)
"""

import pandas as pd
import numpy as np
from typing import Dict, Tuple


class MarketClassifierV37:
    """v37 고급 시장 분류기 (선행 지표 기반)"""

    def __init__(self):
        self.current_state = 'UNKNOWN'
        self.confidence = 0.0

        # 기본 임계값 (동적으로 조정됨)
        self.thresholds = {
            # 20일 MA 기울기 (일별 % 변화)
            'ma20_slope_bull_strong': 0.015,      # 1.5% 이상/일
            'ma20_slope_bull_moderate': 0.005,    # 0.5-1.5%/일
            'ma20_slope_sideways': 0.002,         # -0.2~0.2%/일
            'ma20_slope_bear_moderate': -0.005,   # -1.5~-0.5%/일
            'ma20_slope_bear_strong': -0.015,     # -1.5% 이하/일

            # ADX (추세 강도)
            'adx_strong_trend': 25,
            'adx_moderate_trend': 20,
            'adx_weak_trend': 15,

            # 20일 변동성
            'volatility_high': 0.03,   # 3% 이상
            'volatility_low': 0.015,   # 1.5% 이하

            # RSI 분포 (최근 20일)
            'rsi_overbought_ratio': 0.3,   # 30% 이상이 RSI > 70
            'rsi_oversold_ratio': 0.3      # 30% 이상이 RSI < 30
        }

    def classify_market_state(self, current_row: pd.Series, prev_row: pd.Series = None,
                               df_recent: pd.DataFrame = None) -> str:
        """
        시장 상태 분류 (선행 지표 기반)

        Args:
            current_row: 현재 캔들 데이터
            prev_row: 이전 캔들 데이터
            df_recent: 최근 60일 데이터 (동적 임계값 계산용)

        Returns:
            'BULL_STRONG', 'BULL_MODERATE', 'SIDEWAYS', 'BEAR_MODERATE', 'BEAR_STRONG'
        """

        # 1. 동적 임계값 조정 (최근 데이터 기반)
        if df_recent is not None and len(df_recent) >= 20:
            self._adjust_dynamic_thresholds(df_recent)

        # 2. 핵심 지표 추출
        ma20_slope = self._calculate_ma20_slope(current_row, df_recent)
        adx = current_row.get('adx', 20)
        volatility = current_row.get('volatility_20', self._calculate_volatility(df_recent))
        rsi_distribution = self._analyze_rsi_distribution(df_recent) if df_recent is not None else {'overbought': 0, 'oversold': 0}

        # 3. 분류 로직
        state, confidence = self._classify(ma20_slope, adx, volatility, rsi_distribution)

        self.current_state = state
        self.confidence = confidence

        return state

    def _adjust_dynamic_thresholds(self, df_recent: pd.DataFrame):
        """동적 임계값 조정 (최근 60일 데이터 기반)"""

        # 최근 20일 수익률의 표준편차로 변동성 계산
        returns_20d = df_recent['close'].pct_change().iloc[-20:]
        recent_volatility = returns_20d.std()

        # 변동성이 높으면 임계값 완화, 낮으면 강화
        volatility_multiplier = recent_volatility / 0.02  # 기준: 2% 변동성

        self.thresholds['ma20_slope_bull_strong'] = 0.015 * volatility_multiplier
        self.thresholds['ma20_slope_bear_strong'] = -0.015 * volatility_multiplier

    def _calculate_ma20_slope(self, current_row: pd.Series, df_recent: pd.DataFrame = None) -> float:
        """20일 이동평균 기울기 계산 (선행 지표)"""

        if df_recent is None or len(df_recent) < 25:
            return 0.0

        # 최근 25일 MA20 계산
        ma20_series = df_recent['close'].rolling(20).mean().iloc[-5:]

        if len(ma20_series) < 2:
            return 0.0

        # 선형 회귀로 기울기 계산
        x = np.arange(len(ma20_series))
        y = ma20_series.values

        # 최소자승법
        slope = np.polyfit(x, y, 1)[0]

        # 일별 % 변화로 정규화
        avg_price = ma20_series.mean()
        slope_pct = (slope / avg_price) if avg_price > 0 else 0.0

        return slope_pct

    def _calculate_volatility(self, df_recent: pd.DataFrame = None) -> float:
        """20일 변동성 계산"""

        if df_recent is None or len(df_recent) < 20:
            return 0.02  # 기본값

        returns = df_recent['close'].pct_change().iloc[-20:]
        return returns.std()

    def _analyze_rsi_distribution(self, df_recent: pd.DataFrame) -> Dict[str, float]:
        """최근 20일 RSI 분포 분석"""

        if df_recent is None or len(df_recent) < 20 or 'rsi' not in df_recent.columns:
            return {'overbought': 0.0, 'oversold': 0.0, 'neutral': 1.0}

        recent_rsi = df_recent['rsi'].iloc[-20:]

        overbought_ratio = (recent_rsi > 70).sum() / len(recent_rsi)
        oversold_ratio = (recent_rsi < 30).sum() / len(recent_rsi)
        neutral_ratio = 1.0 - overbought_ratio - oversold_ratio

        return {
            'overbought': overbought_ratio,
            'oversold': oversold_ratio,
            'neutral': neutral_ratio
        }

    def _classify(self, ma20_slope: float, adx: float, volatility: float,
                  rsi_dist: Dict[str, float]) -> Tuple[str, float]:
        """
        종합 분류 로직

        Returns:
            (state, confidence)
        """

        # Score 기반 분류
        bull_score = 0.0
        bear_score = 0.0
        sideways_score = 0.0

        # 1. MA20 기울기 (가장 중요 - 가중치 40%)
        if ma20_slope > self.thresholds['ma20_slope_bull_strong']:
            bull_score += 4.0
        elif ma20_slope > self.thresholds['ma20_slope_bull_moderate']:
            bull_score += 2.0
        elif ma20_slope < self.thresholds['ma20_slope_bear_strong']:
            bear_score += 4.0
        elif ma20_slope < self.thresholds['ma20_slope_bear_moderate']:
            bear_score += 2.0
        else:  # 약한 기울기
            sideways_score += 3.0

        # 2. ADX (추세 강도 - 가중치 30%)
        if adx > self.thresholds['adx_strong_trend']:
            if ma20_slope > 0:
                bull_score += 2.0
            else:
                bear_score += 2.0
        elif adx > self.thresholds['adx_moderate_trend']:
            if ma20_slope > 0:
                bull_score += 1.0
            else:
                bear_score += 1.0
        else:  # 약한 추세 → 횡보
            sideways_score += 2.0

        # 3. 변동성 (가중치 15%)
        if volatility > self.thresholds['volatility_high']:
            # 고변동성 + 상승 → BULL_STRONG
            # 고변동성 + 하락 → BEAR_STRONG
            if ma20_slope > 0:
                bull_score += 1.0
            else:
                bear_score += 1.0
        elif volatility < self.thresholds['volatility_low']:
            # 저변동성 → 횡보
            sideways_score += 1.0

        # 4. RSI 분포 (가중치 15%)
        if rsi_dist['overbought'] > self.thresholds['rsi_overbought_ratio']:
            bull_score += 1.0  # 과매수 빈번 = 상승장
        if rsi_dist['oversold'] > self.thresholds['rsi_oversold_ratio']:
            bear_score += 1.0  # 과매도 빈번 = 하락장 또는 변동성

        # 5. 최종 분류
        max_score = max(bull_score, bear_score, sideways_score)
        total_score = bull_score + bear_score + sideways_score
        confidence = max_score / total_score if total_score > 0 else 0.5

        if bull_score == max_score:
            # BULL 강도 세분화
            if bull_score >= 6.0:
                return 'BULL_STRONG', confidence
            else:
                return 'BULL_MODERATE', confidence

        elif bear_score == max_score:
            # BEAR 강도 세분화
            if bear_score >= 6.0:
                return 'BEAR_STRONG', confidence
            else:
                return 'BEAR_MODERATE', confidence

        else:
            return 'SIDEWAYS', confidence

    def get_classification_details(self) -> Dict:
        """분류 상세 정보 반환 (디버깅용)"""
        return {
            'state': self.current_state,
            'confidence': self.confidence,
            'thresholds': self.thresholds
        }


if __name__ == '__main__':
    """테스트"""
    print("="*70)
    print("  v37 Market Classifier - 테스트")
    print("="*70)

    # 샘플 데이터 생성
    dates = pd.date_range('2024-01-01', periods=60, freq='D')

    # 상승장 시뮬레이션
    prices_bull = 100000 * (1 + np.random.randn(60).cumsum() * 0.01)
    prices_bull = prices_bull * (1 + np.arange(60) * 0.002)  # 상승 트렌드

    # 하락장 시뮬레이션
    prices_bear = 100000 * (1 + np.random.randn(60).cumsum() * 0.01)
    prices_bear = prices_bear * (1 - np.arange(60) * 0.001)  # 하락 트렌드

    # 횡보장 시뮬레이션
    prices_sideways = 100000 + np.random.randn(60).cumsum() * 500

    for scenario, prices in [('BULL', prices_bull), ('BEAR', prices_bear), ('SIDEWAYS', prices_sideways)]:
        df = pd.DataFrame({
            'close': prices,
            'adx': np.random.uniform(15, 30, 60),
            'rsi': np.random.uniform(30, 70, 60)
        }, index=dates)

        classifier = MarketClassifierV37()

        result = classifier.classify_market_state(
            current_row=df.iloc[-1],
            prev_row=df.iloc[-2],
            df_recent=df
        )

        details = classifier.get_classification_details()

        print(f"\n시나리오: {scenario}")
        print(f"  분류 결과: {result}")
        print(f"  신뢰도: {details['confidence']:.2%}")
        print(f"  MA20 기울기 임계값: {details['thresholds']['ma20_slope_bull_strong']:.4f}")

    print("\n테스트 완료!")
