#!/usr/bin/env python3
"""
Phase 3-1: 2025년 Tier 분류 생성
- 2025년 캔들 데이터 로드
- 최적화된 가중치 적용 (score_optimization.json)
- Tier 분류 (S: 25+, A+: 20+, A: 15+)
- CSV 파일 생성 (tier_classified_2025.csv, SA_tier_2025.csv)
"""

import sqlite3
import pandas as pd
import numpy as np
import json
from pathlib import Path
import warnings
warnings.filterwarnings('ignore')

# 설정
DB_PATH = 'upbit_bitcoin.db'
OPTIMIZATION_DIR = Path('strategies/v41_scalping_voting/analysis/optimization')
OUTPUT_DIR = Path('strategies/v41_scalping_voting/analysis/tier_backtest')

# 최적화된 가중치 (score_optimization.json에서 로드)
OPTIMIZED_WEIGHTS = {
    'minute15': {
        'is_local_min': 27,
        'mfi_bullish': 20,
        'low_vol': 16,
        'volume_spike': 12,
        'breakout_20d': 11,
        'swing_end': 7,
        'rsi_oversold': 8
    },
    'minute60': {
        'low_vol': 37,
        'is_local_min': 26,
        'mfi_bullish': 16,
        'breakout_20d': 8,
        'volume_spike': 6,
        'swing_end': 2,
        'rsi_oversold': 8
    },
    'day': {
        'mfi_bullish': 28,
        'is_local_min': 20,
        'breakout_20d': 5,
        'swing_end': 15,
        'rsi_oversold': 8,
        'volume_spike': 7,
        'low_vol': 10
    }
}

# Tier 임계값
TIER_THRESHOLDS = {
    'S': 25,
    'A': 15,
    'B': 10
}


class TierClassifier2025:
    """2025년 Tier 분류기"""

    def __init__(self, timeframe):
        self.timeframe = timeframe
        self.weights = OPTIMIZED_WEIGHTS.get(timeframe, {})

    def load_2025_data(self):
        """2025년 데이터 로드"""
        table_name = f'bitcoin_{self.timeframe}'
        conn = sqlite3.connect(DB_PATH)

        query = f"""
        SELECT
            timestamp,
            opening_price as open,
            high_price as high,
            low_price as low,
            trade_price as close,
            candle_acc_trade_volume as volume
        FROM {table_name}
        WHERE strftime('%Y', timestamp) = '2025'
        ORDER BY timestamp
        """

        df = pd.read_sql_query(query, conn)
        conn.close()

        if len(df) == 0:
            print(f"⚠️ {self.timeframe} 2025년 데이터가 없습니다.")
            return None

        df['timestamp'] = pd.to_datetime(df['timestamp'])
        print(f"✅ {self.timeframe} 2025: {len(df)}개 캔들 ({df['timestamp'].min()} ~ {df['timestamp'].max()})")

        return df

    def calculate_indicators(self, df):
        """기술적 지표 계산"""
        if df is None or len(df) < 50:
            return df

        # RSI
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        df['rsi'] = 100 - (100 / (1 + rs))

        # MFI (Money Flow Index)
        typical_price = (df['high'] + df['low'] + df['close']) / 3
        money_flow = typical_price * df['volume']

        positive_flow = money_flow.where(typical_price > typical_price.shift(1), 0).rolling(window=14).sum()
        negative_flow = money_flow.where(typical_price < typical_price.shift(1), 0).rolling(window=14).sum()

        mfi_ratio = positive_flow / negative_flow
        df['mfi'] = 100 - (100 / (1 + mfi_ratio))

        # Volume
        df['volume_sma'] = df['volume'].rolling(window=20).mean()
        df['volume_ratio'] = df['volume'] / df['volume_sma']

        # MACD
        ema_fast = df['close'].ewm(span=12, adjust=False).mean()
        ema_slow = df['close'].ewm(span=26, adjust=False).mean()
        df['macd'] = ema_fast - ema_slow
        df['macd_signal'] = df['macd'].ewm(span=9, adjust=False).mean()

        # Bollinger Bands
        bb_period = 20
        df['bb_middle'] = df['close'].rolling(window=bb_period).mean()
        bb_std = df['close'].rolling(window=bb_period).std()
        df['bb_upper'] = df['bb_middle'] + (bb_std * 2)
        df['bb_lower'] = df['bb_middle'] - (bb_std * 2)
        df['bb_position'] = (df['close'] - df['bb_lower']) / (df['bb_upper'] - df['bb_lower'])

        # ADX (Average Directional Index)
        high_diff = df['high'].diff()
        low_diff = -df['low'].diff()

        plus_dm = high_diff.where((high_diff > low_diff) & (high_diff > 0), 0)
        minus_dm = low_diff.where((low_diff > high_diff) & (low_diff > 0), 0)

        tr = pd.concat([
            df['high'] - df['low'],
            abs(df['high'] - df['close'].shift(1)),
            abs(df['low'] - df['close'].shift(1))
        ], axis=1).max(axis=1)

        atr = tr.rolling(window=14).mean()
        plus_di = 100 * (plus_dm.rolling(window=14).mean() / atr)
        minus_di = 100 * (minus_dm.rolling(window=14).mean() / atr)

        dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di)
        df['adx'] = dx.rolling(window=14).mean()

        # ATR (Average True Range)
        df['atr'] = atr

        # Local Minima (지역 최저점)
        window = 20
        df['is_local_min'] = (
            (df['close'] == df['close'].rolling(window=window, center=True).min())
        ).astype(int)

        # Volatility (변동성)
        df['volatility'] = df['close'].pct_change().rolling(window=20).std()
        df['low_vol'] = (df['volatility'] < df['volatility'].rolling(window=100).quantile(0.2)).astype(int)

        return df

    def calculate_score(self, row):
        """최적화된 점수 계산"""
        score = 0

        # RSI Oversold
        if pd.notna(row.get('rsi')) and row['rsi'] <= 30:
            score += self.weights.get('rsi_oversold', 0)

        # MFI Bullish
        if pd.notna(row.get('mfi')) and row['mfi'] >= 50:
            score += self.weights.get('mfi_bullish', 0)

        # Local Minima
        if row.get('is_local_min', 0) == 1:
            score += self.weights.get('is_local_min', 0)

        # Low Volatility
        if row.get('low_vol', 0) == 1:
            score += self.weights.get('low_vol', 0)

        # Volume Spike
        if pd.notna(row.get('volume_ratio')) and row['volume_ratio'] >= 1.5:
            score += self.weights.get('volume_spike', 0)

        # Bollinger Band Breakout
        if pd.notna(row.get('bb_position')):
            if row['bb_position'] <= 0.2:  # 하단 돌파
                score += self.weights.get('breakout_20d', 0)

        # MACD Swing End
        if pd.notna(row.get('macd')) and pd.notna(row.get('macd_signal')):
            if row['macd'] > row['macd_signal']:  # 골든 크로스
                score += self.weights.get('swing_end', 0)

        return score

    def classify_tier(self, score):
        """점수 기반 Tier 분류"""
        if score >= TIER_THRESHOLDS['S']:
            return 'S'
        elif score >= TIER_THRESHOLDS['A']:
            return 'A'
        elif score >= TIER_THRESHOLDS['B']:
            return 'B'
        else:
            return 'C'

    def generate_tiers(self):
        """Tier 분류 생성"""
        df = self.load_2025_data()
        if df is None:
            return None, None

        # 지표 계산
        print(f"  지표 계산 중...")
        df = self.calculate_indicators(df)

        # 점수 계산
        print(f"  점수 계산 중...")
        df['optimized_score'] = df.apply(self.calculate_score, axis=1)

        # Tier 분류
        df['tier'] = df['optimized_score'].apply(self.classify_tier)

        # 통계
        tier_counts = df['tier'].value_counts().to_dict()
        print(f"  Tier 분포: {tier_counts}")

        score_stats = df['optimized_score'].describe()
        print(f"  점수 통계: mean={score_stats['mean']:.1f}, std={score_stats['std']:.1f}, "
              f"min={score_stats['min']:.1f}, max={score_stats['max']:.1f}")

        # S/A-Tier만 필터링
        sa_df = df[df['tier'].isin(['S', 'A'])].copy()
        print(f"  S/A-Tier: {len(sa_df)}개 시그널")

        return df, sa_df

    def save_results(self, df_all, df_sa):
        """결과 저장"""
        if df_all is None:
            return

        # 전체 Tier 분류 저장
        output_file = OUTPUT_DIR / f'{self.timeframe}_tier_classified_2025.csv'
        df_all.to_csv(output_file, index=False)
        print(f"  저장: {output_file}")

        # S/A-Tier만 저장
        if df_sa is not None and len(df_sa) > 0:
            sa_file = OUTPUT_DIR / f'{self.timeframe}_SA_tier_2025.csv'
            df_sa.to_csv(sa_file, index=False)
            print(f"  저장: {sa_file}")


def main():
    """메인 실행"""
    print("\n" + "=" * 80)
    print("Phase 3-1: 2025년 Tier 분류 생성")
    print("=" * 80)

    timeframes = ['day', 'minute15', 'minute60', 'minute240']
    results = {}

    for tf in timeframes:
        print(f"\n{'='*60}")
        print(f"{tf.upper()} 2025년 처리")
        print(f"{'='*60}")

        classifier = TierClassifier2025(tf)
        df_all, df_sa = classifier.generate_tiers()

        if df_all is not None:
            classifier.save_results(df_all, df_sa)

            results[tf] = {
                'total_candles': len(df_all),
                'tier_distribution': df_all['tier'].value_counts().to_dict(),
                'sa_signals': len(df_sa) if df_sa is not None else 0,
                'score_mean': float(df_all['optimized_score'].mean()),
                'score_std': float(df_all['optimized_score'].std()),
                'score_max': float(df_all['optimized_score'].max()),
            }

    # 요약 통계 저장
    summary_file = OUTPUT_DIR / 'tier_classification_2025_summary.json'
    with open(summary_file, 'w') as f:
        json.dump(results, f, indent=2)

    print(f"\n\n{'='*80}")
    print("📊 2025년 Tier 분류 요약")
    print(f"{'='*80}")

    for tf, stats in results.items():
        print(f"\n{tf.upper()}:")
        print(f"  전체 캔들: {stats['total_candles']}개")
        print(f"  S/A-Tier 시그널: {stats['sa_signals']}개")
        print(f"  Tier 분포: {stats['tier_distribution']}")
        print(f"  평균 점수: {stats['score_mean']:.1f} (±{stats['score_std']:.1f})")

    print(f"\n요약 저장: {summary_file}")
    print("\n✅ Phase 3-1 완료!")


if __name__ == '__main__':
    main()
