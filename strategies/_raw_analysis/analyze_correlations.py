#!/usr/bin/env python3
"""
Correlation Analysis - Phase 0
Cross-indicator, Cross-timeframe, Lag correlations
"""

import sys
import pandas as pd
import numpy as np
import json
from pathlib import Path
import warnings
warnings.filterwarnings('ignore')

OUTPUT_DIR = Path(__file__).parent
TIMEFRAMES = ['minute5', 'minute15', 'minute30', 'minute60', 'minute240', 'day']

# ========================
# Cross-Indicator Correlation
# ========================

def analyze_cross_indicator_correlation(df, timeframe):
    """지표 간 상관관계 분석"""

    # 주요 지표 선택
    key_indicators = [
        'rsi_14', 'macd', 'macd_signal', 'adx', 'stoch_k', 'stoch_d',
        'bb_position', 'bb_width', 'volume_ratio', 'atr', 'mfi',
        'price_change_5d', 'price_change_10d', 'volatility_10', 'volatility_30',
        'obv', 'cmf', 'cci', 'roc', 'willr'
    ]

    # 존재하는 컬럼만 선택
    available_cols = [col for col in key_indicators if col in df.columns]
    df_indicators = df[available_cols].copy()

    # NaN/Inf 처리
    df_indicators = df_indicators.replace([np.inf, -np.inf], np.nan)
    df_indicators = df_indicators.fillna(method='ffill').fillna(method='bfill').fillna(0)

    # 상관행렬
    corr_matrix = df_indicators.corr()

    # 강한 상관관계 추출 (|r| > 0.7, 자기 자신 제외)
    strong_correlations = []
    for i in range(len(corr_matrix.columns)):
        for j in range(i+1, len(corr_matrix.columns)):
            corr_value = corr_matrix.iloc[i, j]
            if abs(corr_value) > 0.7:
                strong_correlations.append({
                    'indicator_1': corr_matrix.columns[i],
                    'indicator_2': corr_matrix.columns[j],
                    'correlation': float(corr_value)
                })

    # 상관관계 크기 순 정렬
    strong_correlations = sorted(strong_correlations,
                                key=lambda x: abs(x['correlation']),
                                reverse=True)

    return {
        'timeframe': timeframe,
        'n_indicators': len(available_cols),
        'strong_correlations': strong_correlations[:20]  # Top 20
    }

# ========================
# Indicator vs Future Return
# ========================

def analyze_predictive_power(df, timeframe, horizon=5):
    """지표의 미래 수익률 예측력 분석"""

    # Future return 계산
    df['future_return'] = df['close'].shift(-horizon) / df['close'] - 1

    # 주요 지표
    key_indicators = [
        'rsi_14', 'macd', 'adx', 'stoch_k', 'bb_position',
        'volume_ratio', 'atr', 'mfi', 'price_change_5d', 'volatility_10'
    ]

    available_cols = [col for col in key_indicators if col in df.columns]

    predictive_power = []
    for indicator in available_cols:
        df_clean = df[[indicator, 'future_return']].copy()
        df_clean = df_clean.replace([np.inf, -np.inf], np.nan).dropna()

        if len(df_clean) < 100:
            continue

        corr = df_clean[indicator].corr(df_clean['future_return'])

        # Quantile analysis (4분위수별 평균 수익률)
        df_clean['quantile'] = pd.qcut(df_clean[indicator], q=4, labels=False, duplicates='drop')
        quantile_returns = df_clean.groupby('quantile')['future_return'].mean()

        predictive_power.append({
            'indicator': indicator,
            'correlation_with_future_return': float(corr),
            'q1_avg_return': float(quantile_returns.get(0, 0)) * 100,
            'q2_avg_return': float(quantile_returns.get(1, 0)) * 100,
            'q3_avg_return': float(quantile_returns.get(2, 0)) * 100,
            'q4_avg_return': float(quantile_returns.get(3, 0)) * 100,
            'q4_minus_q1': float((quantile_returns.get(3, 0) - quantile_returns.get(0, 0)) * 100)
        })

    # 예측력 순 정렬 (Q4 - Q1 차이 기준)
    predictive_power = sorted(predictive_power,
                             key=lambda x: abs(x['q4_minus_q1']),
                             reverse=True)

    return {
        'timeframe': timeframe,
        'horizon_days': horizon,
        'predictive_indicators': predictive_power
    }

# ========================
# Main Execution
# ========================

def main():
    print("="*60)
    print("Correlation Analysis - Cross-Indicator & Predictive Power")
    print("="*60)

    all_results = {
        'cross_indicator': [],
        'predictive_power': []
    }

    for tf in TIMEFRAMES:
        print(f"\n[{tf}] Loading indicators...")

        csv_file = OUTPUT_DIR / 'indicators' / f'full_indicators_{tf}.csv'
        if not csv_file.exists():
            print(f"  ⚠️  File not found")
            continue

        df = pd.read_csv(csv_file)
        print(f"  ✅ Loaded {len(df):,} records")

        # Cross-indicator correlation
        print(f"  🔗 Cross-indicator correlation...")
        cross_corr = analyze_cross_indicator_correlation(df, tf)
        all_results['cross_indicator'].append(cross_corr)
        print(f"     Found {len(cross_corr['strong_correlations'])} strong correlations")

        # Predictive power
        print(f"  🔮 Predictive power analysis...")
        predictive = analyze_predictive_power(df, tf, horizon=5)
        all_results['predictive_power'].append(predictive)
        if predictive['predictive_indicators']:
            top_predictor = predictive['predictive_indicators'][0]
            print(f"     Best predictor: {top_predictor['indicator']} (Q4-Q1: {top_predictor['q4_minus_q1']:.2f}%)")

    # Save results
    output_file = OUTPUT_DIR / 'correlations' / 'cross_indicator_and_predictive.json'
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with open(output_file, 'w') as f:
        json.dump(all_results, f, indent=2)

    print(f"\n{'='*60}")
    print(f"✅ Correlation analysis complete!")
    print(f"📄 Results: {output_file}")
    print(f"{'='*60}")

if __name__ == '__main__':
    main()
