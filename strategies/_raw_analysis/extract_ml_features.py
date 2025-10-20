#!/usr/bin/env python3
"""
ML Feature Extraction - Phase 0
PCA, LSTM embeddings, Clustering, Autoencoders
"""

import sys
import pandas as pd
import numpy as np
import json
from pathlib import Path
from sklearn.decomposition import PCA
from sklearn.preprocessing import StandardScaler
from sklearn.cluster import KMeans
import warnings
warnings.filterwarnings('ignore')

OUTPUT_DIR = Path(__file__).parent

TIMEFRAMES = ['minute5', 'minute15', 'minute30', 'minute60', 'minute240', 'day']

# ========================
# PCA Analysis
# ========================

def perform_pca_analysis(df, timeframe, n_components=10):
    """PCA 차원 축소 및 주요 성분 추출"""

    # 지표 컬럼만 선택 (timestamp, OHLCV 제외)
    indicator_cols = [col for col in df.columns if col not in
                     ['timestamp', 'open', 'high', 'low', 'close', 'volume']]

    df_indicators = df[indicator_cols].copy()

    # NaN/Inf 제거
    df_indicators = df_indicators.replace([np.inf, -np.inf], np.nan)
    df_indicators = df_indicators.fillna(method='ffill').fillna(method='bfill').fillna(0)

    # Standardize
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(df_indicators)

    # PCA
    pca = PCA(n_components=n_components)
    X_pca = pca.fit_transform(X_scaled)

    # 결과
    pca_results = {
        'timeframe': timeframe,
        'n_components': n_components,
        'explained_variance_ratio': pca.explained_variance_ratio_.tolist(),
        'cumulative_variance': np.cumsum(pca.explained_variance_ratio_).tolist(),
        'total_variance_explained': float(np.sum(pca.explained_variance_ratio_)),
        'component_loadings': {}
    }

    # 각 성분의 주요 지표
    for i in range(n_components):
        loadings = pca.components_[i]
        top_indices = np.argsort(np.abs(loadings))[-10:][::-1]
        top_features = [(indicator_cols[idx], float(loadings[idx])) for idx in top_indices]
        pca_results['component_loadings'][f'PC{i+1}'] = top_features

    return pca_results, X_pca

# ========================
# Clustering Analysis
# ========================

def perform_clustering(df, timeframe, n_clusters=5):
    """K-Means 클러스터링으로 시장 상태 분류"""

    # 주요 지표만 선택
    feature_cols = ['rsi_14', 'macd', 'adx', 'bb_position', 'volume_ratio',
                   'price_change_5d', 'volatility_10', 'stoch_k']

    # NaN 처리
    df_features = df[feature_cols].copy()
    df_features = df_features.replace([np.inf, -np.inf], np.nan)
    df_features = df_features.fillna(method='ffill').fillna(method='bfill').fillna(0)

    # Standardize
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(df_features)

    # K-Means
    kmeans = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
    clusters = kmeans.fit_predict(X_scaled)

    # 각 클러스터 특성 분석
    cluster_stats = []
    for cluster_id in range(n_clusters):
        cluster_mask = clusters == cluster_id
        cluster_data = df[cluster_mask].copy()

        if len(cluster_data) < 10:
            continue

        # 수익률 분석 (다음 5일)
        future_returns = []
        for i in range(len(cluster_data) - 5):
            idx = cluster_data.index[i]
            future_idx = cluster_data.index[min(i+5, len(cluster_data)-1)]
            ret = (df.loc[future_idx, 'close'] / df.loc[idx, 'close'] - 1) * 100
            future_returns.append(ret)

        avg_future_return = np.mean(future_returns) if future_returns else 0

        cluster_stats.append({
            'cluster_id': int(cluster_id),
            'size': int(cluster_mask.sum()),
            'percentage': float(cluster_mask.sum() / len(df) * 100),
            'avg_future_return_5d': float(avg_future_return),
            'characteristics': {
                'rsi': float(cluster_data['rsi_14'].mean()),
                'macd': float(cluster_data['macd'].mean()),
                'adx': float(cluster_data['adx'].mean()),
                'bb_position': float(cluster_data['bb_position'].mean()),
                'volatility': float(cluster_data['volatility_10'].mean())
            }
        })

    # 수익률 기준 정렬
    cluster_stats = sorted(cluster_stats, key=lambda x: x['avg_future_return_5d'], reverse=True)

    return {
        'timeframe': timeframe,
        'n_clusters': n_clusters,
        'clusters': cluster_stats
    }

# ========================
# Temporal Features
# ========================

def extract_temporal_features(df, timeframe):
    """시계열 특징 추출 (Lag, Rolling)"""

    temporal_features = {
        'timeframe': timeframe,
        'autocorrelation': {},
        'lag_features': {},
        'seasonality': {}
    }

    # Autocorrelation (Lag 1-30)
    close_prices = df['close'].values
    for lag in [1, 5, 10, 20, 30]:
        if len(close_prices) > lag:
            autocorr = np.corrcoef(close_prices[lag:], close_prices[:-lag])[0, 1]
            temporal_features['autocorrelation'][f'lag_{lag}'] = float(autocorr)

    # Lag return correlation
    returns = df['close'].pct_change()
    for lag in [1, 5, 10]:
        if len(returns) > lag:
            lag_corr = returns.autocorr(lag=lag)
            temporal_features['lag_features'][f'return_lag_{lag}_corr'] = float(lag_corr)

    # 요일별 수익률 (day/week만)
    if timeframe in ['day', 'week']:
        df_temp = df.copy()
        df_temp['timestamp'] = pd.to_datetime(df_temp['timestamp'])
        df_temp['weekday'] = df_temp['timestamp'].dt.dayofweek
        df_temp['return'] = df_temp['close'].pct_change()

        weekday_returns = df_temp.groupby('weekday')['return'].mean()
        temporal_features['seasonality']['weekday_returns'] = weekday_returns.to_dict()

    return temporal_features

# ========================
# Main Execution
# ========================

def main():
    print("="*60)
    print("ML Feature Extraction - PCA, Clustering, Temporal")
    print("="*60)

    all_results = {
        'pca': [],
        'clustering': [],
        'temporal': []
    }

    for tf in TIMEFRAMES:
        print(f"\n[{tf}] Loading indicators...")

        csv_file = OUTPUT_DIR / 'indicators' / f'full_indicators_{tf}.csv'
        if not csv_file.exists():
            print(f"  ⚠️  File not found: {csv_file.name}")
            continue

        df = pd.read_csv(csv_file)
        print(f"  ✅ Loaded {len(df):,} records")

        # PCA
        print(f"  🔬 PCA analysis...")
        pca_results, X_pca = perform_pca_analysis(df, tf, n_components=10)
        all_results['pca'].append(pca_results)
        print(f"     Total variance explained: {pca_results['total_variance_explained']:.2%}")

        # Clustering
        print(f"  🎯 Clustering analysis...")
        cluster_results = perform_clustering(df, tf, n_clusters=5)
        all_results['clustering'].append(cluster_results)
        print(f"     Best cluster avg return: {cluster_results['clusters'][0]['avg_future_return_5d']:.2f}%")

        # Temporal
        print(f"  ⏱️  Temporal features...")
        temporal_results = extract_temporal_features(df, tf)
        all_results['temporal'].append(temporal_results)

    # Save results
    output_file = OUTPUT_DIR / 'ml_features' / 'pca_clustering_temporal.json'
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with open(output_file, 'w') as f:
        json.dump(all_results, f, indent=2)

    print(f"\n{'='*60}")
    print(f"✅ ML feature extraction complete!")
    print(f"📄 Results: {output_file}")
    print(f"{'='*60}")

if __name__ == '__main__':
    main()
