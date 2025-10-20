#!/usr/bin/env python3
"""
Phase 0 고도화: 7차원 다각도 시장 분석

7가지 분석 차원:
1. Local Minima/Maxima - 국지적 저점/고점
2. Swing Trading - 상승/하락 스윙 구간
3. Support/Resistance - 지지/저항선 레벨
4. Volatility Regime - 변동성 국면 분류
5. Multi-TF Confluence - 다중 시간대 일치
6. Mean Reversion - 이동평균 이탈 후 복귀
7. Momentum Breakout - N일 최고가 돌파
"""

import sys
sys.path.append('../..')

import json
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import talib
from tqdm import tqdm
from scipy.signal import argrelextrema
from sklearn.cluster import DBSCAN
import warnings
warnings.filterwarnings('ignore')

from core import DataLoader


class AdvancedSignalAnalyzer:
    """7차원 고급 시그널 분석기"""

    def __init__(self, config_path='config.json', db_path='../../upbit_bitcoin.db'):
        with open(config_path) as f:
            self.config = json.load(f)

        self.db_path = db_path
        self.timeframes = ['minute5', 'minute15', 'minute60', 'minute240', 'day']

        # 분석 결과 저장
        self.signals = {}

    def add_indicators(self, df, timeframe):
        """기술적 지표 추가 (브루트포스와 동일)"""
        ind_config = self.config['indicators'][timeframe]

        # RSI
        df['rsi'] = talib.RSI(df['close'], timeperiod=ind_config['rsi_period'])

        # Volume SMA
        df['volume_sma'] = talib.SMA(df['volume'], timeperiod=ind_config['volume_sma'])
        df['volume_ratio'] = df['volume'] / df['volume_sma']

        # MACD
        macd, macd_signal, macd_hist = talib.MACD(
            df['close'],
            fastperiod=ind_config['macd_fast'],
            slowperiod=ind_config['macd_slow'],
            signalperiod=ind_config['macd_signal']
        )
        df['macd'] = macd
        df['macd_signal'] = macd_signal
        df['macd_hist'] = macd_hist

        # EMA
        df['ema_fast'] = talib.EMA(df['close'], timeperiod=ind_config['ema_fast'])
        df['ema_slow'] = talib.EMA(df['close'], timeperiod=ind_config['ema_slow'])

        # Moving Averages (MA20, MA50, MA200)
        df['ma20'] = talib.SMA(df['close'], timeperiod=20)
        df['ma50'] = talib.SMA(df['close'], timeperiod=50)
        if len(df) >= 200:
            df['ma200'] = talib.SMA(df['close'], timeperiod=200)
        else:
            df['ma200'] = df['ma50']  # fallback

        # Bollinger Bands
        bb_upper, bb_middle, bb_lower = talib.BBANDS(
            df['close'],
            timeperiod=ind_config['bb_period'],
            nbdevup=ind_config['bb_std'],
            nbdevdn=ind_config['bb_std']
        )
        df['bb_upper'] = bb_upper
        df['bb_middle'] = bb_middle
        df['bb_lower'] = bb_lower
        df['bb_position'] = (df['close'] - df['bb_lower']) / (df['bb_upper'] - df['bb_lower'])

        # ADX
        df['adx'] = talib.ADX(df['high'], df['low'], df['close'], timeperiod=ind_config.get('adx_period', 14))

        # MFI
        df['mfi'] = talib.MFI(df['high'], df['low'], df['close'], df['volume'], timeperiod=ind_config.get('mfi_period', 14))

        # ATR
        df['atr'] = talib.ATR(df['high'], df['low'], df['close'], timeperiod=ind_config.get('atr_period', 14))
        df['atr_pct'] = df['atr'] / df['close']

        # NaN 제거
        df = df.dropna()

        return df

    # ========== 1. Local Minima/Maxima ==========
    def detect_local_extrema(self, df, window=5):
        """국지적 저점/고점 탐지"""
        # Local minima (저점)
        local_min_idx = argrelextrema(df['close'].values, np.less, order=window)[0]

        # Local maxima (고점)
        local_max_idx = argrelextrema(df['close'].values, np.greater, order=window)[0]

        df['is_local_min'] = False
        df['is_local_max'] = False

        df.iloc[local_min_idx, df.columns.get_loc('is_local_min')] = True
        df.iloc[local_max_idx, df.columns.get_loc('is_local_max')] = True

        return df

    # ========== 2. Swing Trading ==========
    def detect_swing(self, df, consecutive_days=3):
        """스윙 구간 탐지"""
        df['swing_type'] = 'neutral'  # up_swing, down_swing, neutral

        for i in range(consecutive_days, len(df)):
            # 하락 스윙 종료 (연속 하락 후 반등)
            recent_closes = df.iloc[i-consecutive_days:i]['close'].values
            is_declining = all(recent_closes[j] > recent_closes[j+1] for j in range(len(recent_closes)-1))

            if is_declining and df.iloc[i]['close'] > df.iloc[i-1]['close']:
                df.iloc[i, df.columns.get_loc('swing_type')] = 'down_swing_end'

            # 상승 스윙 중간 (연속 2-3일 상승)
            recent_ups = df.iloc[i-2:i]['close'].values
            is_rising = all(recent_ups[j] < recent_ups[j+1] for j in range(len(recent_ups)-1))

            if is_rising:
                df.iloc[i, df.columns.get_loc('swing_type')] = 'up_swing_middle'

        return df

    # ========== 3. Support/Resistance ==========
    def detect_support_resistance(self, df, lookback=90, tolerance=0.02):
        """지지/저항선 레벨 탐지 (DBSCAN Clustering)"""
        if len(df) < lookback:
            df['near_support'] = False
            df['near_resistance'] = False
            return df

        # 최근 lookback 일의 저점/고점 추출
        recent_lows = df['low'].iloc[-lookback:].values
        recent_highs = df['high'].iloc[-lookback:].values

        # Clustering으로 지지선 찾기
        lows_reshaped = recent_lows.reshape(-1, 1)
        clustering = DBSCAN(eps=np.mean(recent_lows) * tolerance, min_samples=3).fit(lows_reshaped)
        labels = clustering.labels_

        support_levels = []
        for label in set(labels):
            if label == -1:  # noise
                continue
            cluster_lows = recent_lows[labels == label]
            support_levels.append(np.mean(cluster_lows))

        # Clustering으로 저항선 찾기
        highs_reshaped = recent_highs.reshape(-1, 1)
        clustering = DBSCAN(eps=np.mean(recent_highs) * tolerance, min_samples=3).fit(highs_reshaped)
        labels = clustering.labels_

        resistance_levels = []
        for label in set(labels):
            if label == -1:
                continue
            cluster_highs = recent_highs[labels == label]
            resistance_levels.append(np.mean(cluster_highs))

        # 현재 가격이 지지/저항선 근처인지 확인
        df['near_support'] = False
        df['near_resistance'] = False

        for i in range(len(df)):
            current_price = df.iloc[i]['close']

            # 지지선 근처 (±2%)
            for support in support_levels:
                if abs(current_price - support) / support < 0.02:
                    df.iloc[i, df.columns.get_loc('near_support')] = True

            # 저항선 근처 (±2%)
            for resistance in resistance_levels:
                if abs(current_price - resistance) / resistance < 0.02:
                    df.iloc[i, df.columns.get_loc('near_resistance')] = True

        return df

    # ========== 4. Volatility Regime ==========
    def classify_volatility(self, df):
        """변동성 국면 분류"""
        df['vol_regime'] = 'medium'  # low, medium, high

        # ATR 백분율 기준
        df.loc[df['atr_pct'] < 0.02, 'vol_regime'] = 'low'
        df.loc[df['atr_pct'] > 0.05, 'vol_regime'] = 'high'

        return df

    # ========== 5. Multi-TF Confluence (생략, 차후 구현) ==========

    # ========== 6. Mean Reversion Distance ==========
    def calculate_ma_distance(self, df):
        """이동평균선과의 거리 계산"""
        df['ma20_distance'] = (df['close'] - df['ma20']) / df['ma20']
        df['ma50_distance'] = (df['close'] - df['ma50']) / df['ma50']
        df['ma200_distance'] = (df['close'] - df['ma200']) / df['ma200']

        # 극단적 이탈
        df['extreme_below_ma'] = (df['ma20_distance'] < -0.10)  # MA20 대비 -10% 이하
        df['extreme_above_ma'] = (df['ma20_distance'] > 0.15)   # MA20 대비 +15% 이상

        return df

    # ========== 7. Momentum Breakout ==========
    def detect_breakout(self, df, lookback=20):
        """N일 최고가 돌파 탐지"""
        df['high_20d'] = df['high'].rolling(window=lookback).max()
        df['breakout_20d'] = (df['close'] > df['high_20d'].shift(1)) & (df['volume_ratio'] > 2.0)

        return df

    # ========== 종합 시그널 계산 ==========
    def calculate_composite_score(self, df):
        """7차원 종합 점수 계산"""
        scores = []

        for i in range(len(df)):
            score = 0
            components = {}

            # 1. Local Minimum (+20점)
            if df.iloc[i]['is_local_min']:
                score += 20
                components['local_min'] = True

            # 2. Swing 종료 (+15점)
            if df.iloc[i]['swing_type'] == 'down_swing_end':
                score += 15
                components['swing_end'] = True

            # 3. Support 근처 (+15점)
            if df.iloc[i]['near_support']:
                score += 15
                components['near_support'] = True

            # 4. Low Volatility (+10점)
            if df.iloc[i]['vol_regime'] == 'low':
                score += 10
                components['low_vol'] = True

            # 6. Extreme Below MA (+10점)
            if df.iloc[i]['extreme_below_ma']:
                score += 10
                components['extreme_below_ma'] = True

            # 7. Breakout (+5점)
            if df.iloc[i]['breakout_20d']:
                score += 5
                components['breakout'] = True

            # 추가 보너스
            if df.iloc[i]['rsi'] < 30:
                score += 8
                components['rsi_oversold'] = True

            if df.iloc[i]['volume_ratio'] > 2.0:
                score += 7
                components['volume_spike'] = True

            if df.iloc[i]['mfi'] > 50:
                score += 5
                components['mfi_bullish'] = True

            scores.append({
                'score': score,
                'components': components
            })

        df['signal_score'] = [s['score'] for s in scores]
        df['signal_components'] = [s['components'] for s in scores]

        return df

    def analyze_timeframe(self, timeframe):
        """타임프레임별 7차원 분석"""
        print(f"\n{'='*70}")
        print(f"[{timeframe}] 7차원 고급 분석 시작")
        print(f"{'='*70}\n")

        # 데이터 로드
        print(f"[{timeframe}] 데이터 로드 중...")
        with DataLoader(self.db_path) as loader:
            df = loader.load_timeframe(timeframe, start_date='2020-01-01', end_date='2024-12-31')

        if df is None or len(df) == 0:
            print(f"  ❌ {timeframe} 데이터 없음")
            return

        print(f"[{timeframe}] 로드 완료: {len(df):,} 캔들")

        # 지표 계산
        print(f"[{timeframe}] 지표 계산 중...")
        df = self.add_indicators(df, timeframe)
        print(f"[{timeframe}] 지표 계산 완료: {len(df):,} 캔들")

        # 7차원 분석 실행
        print(f"[{timeframe}] 7차원 분석 실행 중...")

        df = self.detect_local_extrema(df, window=5)
        df = self.detect_swing(df, consecutive_days=3)
        df = self.detect_support_resistance(df, lookback=90)
        df = self.classify_volatility(df)
        df = self.calculate_ma_distance(df)
        df = self.detect_breakout(df, lookback=20)

        # 종합 점수 계산
        df = self.calculate_composite_score(df)

        print(f"[{timeframe}] 7차원 분석 완료")

        # 시그널 등급 분류
        df['signal_tier'] = 'C'  # 기본: C
        df.loc[df['signal_score'] >= 40, 'signal_tier'] = 'B'
        df.loc[df['signal_score'] >= 55, 'signal_tier'] = 'A'
        df.loc[df['signal_score'] >= 70, 'signal_tier'] = 'S'

        # Tier별 통계
        print(f"\n[{timeframe}] Tier별 시그널 통계:")
        print(f"{'='*70}")

        for tier in ['S', 'A', 'B', 'C']:
            tier_signals = df[df['signal_tier'] == tier]
            print(f"{tier}-Tier: {len(tier_signals):,}개 시그널 (점수 범위: {tier_signals['signal_score'].min():.0f}~{tier_signals['signal_score'].max():.0f})")

        # CSV 저장 (A-Tier 이상만)
        high_quality = df[df['signal_tier'].isin(['S', 'A'])].copy()
        output_file = f'analysis/advanced/signals_{timeframe}_advanced.csv'
        high_quality.to_csv(output_file, index=False)
        print(f"\n저장 완료: {output_file}")
        print(f"  - 고품질 시그널 (S+A Tier): {len(high_quality):,}개")

        # 통계 저장
        self.signals[timeframe] = {
            'total_signals': len(df),
            'S_tier': len(df[df['signal_tier'] == 'S']),
            'A_tier': len(df[df['signal_tier'] == 'A']),
            'B_tier': len(df[df['signal_tier'] == 'B']),
            'C_tier': len(df[df['signal_tier'] == 'C'])
        }

    def run_full_analysis(self):
        """전체 타임프레임 7차원 분석"""
        print(f"{'='*70}")
        print(f"Phase 0 고도화: 7차원 다각도 시장 분석")
        print(f"{'='*70}")
        print(f"분석 기간: 2020-01-01 ~ 2024-12-31")
        print(f"타임프레임: {', '.join(self.timeframes)}")
        print(f"{'='*70}\n")

        # 결과 디렉토리 생성
        import os
        os.makedirs('analysis/advanced', exist_ok=True)

        start_time = datetime.now()

        # 타임프레임별 분석
        for tf in self.timeframes:
            self.analyze_timeframe(tf)

        end_time = datetime.now()
        elapsed = end_time - start_time

        # 최종 요약
        print(f"\n{'='*70}")
        print(f"7차원 분석 완료!")
        print(f"{'='*70}")
        print(f"소요 시간: {elapsed}")
        print(f"\nTier별 시그널 요약:")
        print(f"{'':<12} {'S-Tier':<10} {'A-Tier':<10} {'B-Tier':<10} {'C-Tier':<10}")
        print(f"{'-'*70}")
        for tf, stats in self.signals.items():
            print(f"{tf:<12} {stats['S_tier']:<10} {stats['A_tier']:<10} {stats['B_tier']:<10} {stats['C_tier']:<10}")

        # JSON 저장
        with open('analysis/advanced/advanced_summary.json', 'w') as f:
            json.dump(self.signals, f, indent=2)

        print(f"\n요약 저장: analysis/advanced/advanced_summary.json")
        print(f"{'='*70}\n")


if __name__ == '__main__':
    analyzer = AdvancedSignalAnalyzer()
    analyzer.run_full_analysis()
