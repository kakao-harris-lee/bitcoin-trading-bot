#!/usr/bin/env python3
"""
Raw Data Complete Analysis - Phase 0
모든 타임프레임 (11개)에서 100+ 지표 계산 및 분석
"""

import sys
sys.path.append('../..')

import sqlite3
import pandas as pd
import numpy as np
import talib
import json
from datetime import datetime
from pathlib import Path

# ========================
# Configuration
# ========================

DB_PATH = '../../upbit_bitcoin.db'
OUTPUT_DIR = Path(__file__).parent

TIMEFRAMES = [
    'minute1', 'minute3', 'minute5', 'minute10', 'minute15',
    'minute30', 'minute60', 'minute240', 'day', 'week', 'month'
]

# 분석 기간 (2022-2025)
START_DATE = '2022-01-01'
END_DATE = '2025-12-31'

# ========================
# Data Loading
# ========================

def load_timeframe_data(db_path, timeframe, start_date, end_date):
    """타임프레임별 데이터 로드"""
    conn = sqlite3.connect(db_path)
    query = f"""
        SELECT timestamp, opening_price as open, high_price as high,
               low_price as low, trade_price as close,
               candle_acc_trade_volume as volume
        FROM bitcoin_{timeframe}
        WHERE timestamp >= '{start_date}' AND timestamp <= '{end_date}'
        ORDER BY timestamp ASC
    """
    df = pd.read_sql_query(query, conn)
    conn.close()

    if df.empty:
        return None

    df['timestamp'] = pd.to_datetime(df['timestamp'])
    return df

# ========================
# 100+ Indicators Calculation
# ========================

def calculate_all_indicators(df):
    """100+ 기술 지표 계산"""

    close = df['close'].values
    high = df['high'].values
    low = df['low'].values
    open_price = df['open'].values
    volume = df['volume'].values

    indicators = {}

    # ==================
    # 1. TREND (12개)
    # ==================
    try:
        indicators['sma_5'] = talib.SMA(close, timeperiod=5)
        indicators['sma_10'] = talib.SMA(close, timeperiod=10)
        indicators['sma_20'] = talib.SMA(close, timeperiod=20)
        indicators['sma_50'] = talib.SMA(close, timeperiod=50)
        indicators['sma_100'] = talib.SMA(close, timeperiod=100)
        indicators['sma_200'] = talib.SMA(close, timeperiod=200)

        indicators['ema_12'] = talib.EMA(close, timeperiod=12)
        indicators['ema_26'] = talib.EMA(close, timeperiod=26)
        indicators['ema_50'] = talib.EMA(close, timeperiod=50)
        indicators['ema_100'] = talib.EMA(close, timeperiod=100)

        indicators['wma_20'] = talib.WMA(close, timeperiod=20)
        indicators['dema_20'] = talib.DEMA(close, timeperiod=20)
    except Exception as e:
        print(f"  [WARN] Trend indicators error: {e}")

    # ==================
    # 2. MOMENTUM (15개)
    # ==================
    try:
        indicators['rsi_14'] = talib.RSI(close, timeperiod=14)
        indicators['rsi_21'] = talib.RSI(close, timeperiod=21)

        slowk, slowd = talib.STOCH(high, low, close, fastk_period=14,
                                     slowk_period=3, slowd_period=3)
        indicators['stoch_k'] = slowk
        indicators['stoch_d'] = slowd

        indicators['cci'] = talib.CCI(high, low, close, timeperiod=14)
        indicators['roc'] = talib.ROC(close, timeperiod=10)
        indicators['mom'] = talib.MOM(close, timeperiod=10)
        indicators['willr'] = talib.WILLR(high, low, close, timeperiod=14)
        indicators['trix'] = talib.TRIX(close, timeperiod=30)

        indicators['adx'] = talib.ADX(high, low, close, timeperiod=14)
        indicators['dx'] = talib.DX(high, low, close, timeperiod=14)
        indicators['plus_di'] = talib.PLUS_DI(high, low, close, timeperiod=14)
        indicators['minus_di'] = talib.MINUS_DI(high, low, close, timeperiod=14)

        aroon_down, aroon_up = talib.AROON(high, low, timeperiod=25)
        indicators['aroon_up'] = aroon_up
        indicators['aroon_down'] = aroon_down

        indicators['ppo'] = talib.PPO(close, fastperiod=12, slowperiod=26)
    except Exception as e:
        print(f"  [WARN] Momentum indicators error: {e}")

    # ==================
    # 3. VOLATILITY (8개)
    # ==================
    try:
        upper, middle, lower = talib.BBANDS(close, timeperiod=20,
                                             nbdevup=2, nbdevdn=2)
        indicators['bb_upper'] = upper
        indicators['bb_middle'] = middle
        indicators['bb_lower'] = lower
        indicators['bb_width'] = (upper - lower) / middle

        indicators['atr'] = talib.ATR(high, low, close, timeperiod=14)
        indicators['natr'] = talib.NATR(high, low, close, timeperiod=14)
        indicators['trange'] = talib.TRANGE(high, low, close)

        # Keltner Channels (EMA ± 2*ATR)
        ema_20 = talib.EMA(close, timeperiod=20)
        atr_10 = talib.ATR(high, low, close, timeperiod=10)
        indicators['kc_upper'] = ema_20 + 2 * atr_10
        indicators['kc_lower'] = ema_20 - 2 * atr_10
    except Exception as e:
        print(f"  [WARN] Volatility indicators error: {e}")

    # ==================
    # 4. VOLUME (6개)
    # ==================
    try:
        indicators['obv'] = talib.OBV(close, volume)
        indicators['ad'] = talib.AD(high, low, close, volume)
        indicators['adosc'] = talib.ADOSC(high, low, close, volume,
                                          fastperiod=3, slowperiod=10)
        indicators['mfi'] = talib.MFI(high, low, close, volume, timeperiod=14)

        # CMF (Chaikin Money Flow)
        mfv = ((close - low) - (high - close)) / (high - low) * volume
        indicators['cmf'] = talib.SMA(mfv, timeperiod=20) / talib.SMA(volume, timeperiod=20)

        # VWAP (Volume Weighted Average Price)
        indicators['vwap'] = (close * volume).cumsum() / volume.cumsum()
    except Exception as e:
        print(f"  [WARN] Volume indicators error: {e}")

    # ==================
    # 5. PATTERN (10개)
    # ==================
    try:
        indicators['macd'], indicators['macd_signal'], indicators['macd_hist'] = \
            talib.MACD(close, fastperiod=12, slowperiod=26, signalperiod=9)

        indicators['sar'] = talib.SAR(high, low, acceleration=0.02, maximum=0.2)

        indicators['bop'] = talib.BOP(open_price, high, low, close)

        # Ichimoku Cloud components
        period9_high = pd.Series(high).rolling(window=9).max().values
        period9_low = pd.Series(low).rolling(window=9).min().values
        indicators['tenkan_sen'] = (period9_high + period9_low) / 2

        period26_high = pd.Series(high).rolling(window=26).max().values
        period26_low = pd.Series(low).rolling(window=26).min().values
        indicators['kijun_sen'] = (period26_high + period26_low) / 2

        indicators['senkou_span_a'] = (indicators['tenkan_sen'] + indicators['kijun_sen']) / 2

        period52_high = pd.Series(high).rolling(window=52).max().values
        period52_low = pd.Series(low).rolling(window=52).min().values
        indicators['senkou_span_b'] = (period52_high + period52_low) / 2
    except Exception as e:
        print(f"  [WARN] Pattern indicators error: {e}")

    # ==================
    # 6. CUSTOM (20개)
    # ==================
    try:
        # Price Position
        indicators['price_to_sma20'] = close / indicators.get('sma_20', close)
        indicators['price_to_ema50'] = close / indicators.get('ema_50', close)

        # BB Position
        bb_upper = indicators.get('bb_upper', close)
        bb_lower = indicators.get('bb_lower', close)
        indicators['bb_position'] = (close - bb_lower) / (bb_upper - bb_lower + 1e-10)

        # Volume Ratio
        sma_vol_20 = talib.SMA(volume, timeperiod=20)
        indicators['volume_ratio'] = volume / (sma_vol_20 + 1e-10)

        # Price Change
        indicators['price_change_1d'] = close / np.roll(close, 1) - 1
        indicators['price_change_5d'] = close / np.roll(close, 5) - 1
        indicators['price_change_10d'] = close / np.roll(close, 10) - 1
        indicators['price_change_20d'] = close / np.roll(close, 20) - 1

        # High/Low Range
        indicators['hl_range'] = (high - low) / close

        # Close Position in Candle
        indicators['close_position'] = (close - low) / (high - low + 1e-10)

        # Rolling Volatility
        returns = pd.Series(close).pct_change()
        indicators['volatility_10'] = returns.rolling(10).std().values
        indicators['volatility_30'] = returns.rolling(30).std().values

        # Support/Resistance (간단 버전: 50일 최고/최저)
        indicators['resistance_50'] = pd.Series(high).rolling(50).max().values
        indicators['support_50'] = pd.Series(low).rolling(50).min().values

        # Distance to Support/Resistance
        indicators['dist_to_resistance'] = (indicators['resistance_50'] - close) / close
        indicators['dist_to_support'] = (close - indicators['support_50']) / close

        # Pivot Points (Classic)
        pivot = (high + low + close) / 3
        indicators['pivot'] = pivot
        indicators['r1'] = 2 * pivot - low
        indicators['s1'] = 2 * pivot - high
        indicators['r2'] = pivot + (high - low)
        indicators['s2'] = pivot - (high - low)
    except Exception as e:
        print(f"  [WARN] Custom indicators error: {e}")

    # DataFrame 변환
    df_indicators = pd.DataFrame(indicators, index=df.index)
    df_full = pd.concat([df, df_indicators], axis=1)

    return df_full

# ========================
# Statistical Analysis
# ========================

def analyze_timeframe_statistics(df, timeframe):
    """타임프레임별 통계 분석"""

    stats = {
        'timeframe': timeframe,
        'total_records': len(df),
        'date_range': {
            'start': str(df['timestamp'].min()),
            'end': str(df['timestamp'].max())
        },
        'price_stats': {
            'min': float(df['close'].min()),
            'max': float(df['close'].max()),
            'mean': float(df['close'].mean()),
            'std': float(df['close'].std())
        },
        'returns': {
            'total_return': float((df['close'].iloc[-1] / df['close'].iloc[0] - 1) * 100),
            'mean_return': float(df['close'].pct_change().mean() * 100),
            'volatility': float(df['close'].pct_change().std() * 100)
        },
        'volume_stats': {
            'mean': float(df['volume'].mean()),
            'max': float(df['volume'].max())
        }
    }

    # Yearly breakdown
    df_yearly = df.copy()
    df_yearly['year'] = df_yearly['timestamp'].dt.year
    yearly_stats = {}

    for year in df_yearly['year'].unique():
        df_year = df_yearly[df_yearly['year'] == year]
        if len(df_year) < 2:
            continue
        yearly_return = (df_year['close'].iloc[-1] / df_year['close'].iloc[0] - 1) * 100
        yearly_stats[int(year)] = {
            'records': len(df_year),
            'return': float(yearly_return),
            'volatility': float(df_year['close'].pct_change().std() * 100)
        }

    stats['yearly_breakdown'] = yearly_stats

    return stats

# ========================
# Main Execution
# ========================

def main():
    print("="*60)
    print("Raw Data Complete Analysis - All Timeframes")
    print("="*60)

    all_stats = []

    for tf in TIMEFRAMES:
        print(f"\n[{tf}] Loading data...")
        df = load_timeframe_data(DB_PATH, tf, START_DATE, END_DATE)

        if df is None or len(df) < 100:
            print(f"  ⚠️  Insufficient data (records: {len(df) if df is not None else 0})")
            continue

        print(f"  ✅ Loaded {len(df):,} records from {df['timestamp'].min()} to {df['timestamp'].max()}")

        # Calculate indicators
        print(f"  📊 Calculating 100+ indicators...")
        df_full = calculate_all_indicators(df)

        # Statistical analysis
        print(f"  📈 Analyzing statistics...")
        stats = analyze_timeframe_statistics(df, tf)
        all_stats.append(stats)

        # Save full data with indicators
        output_file = OUTPUT_DIR / 'indicators' / f'full_indicators_{tf}.csv'
        output_file.parent.mkdir(parents=True, exist_ok=True)
        df_full.to_csv(output_file, index=False)
        print(f"  💾 Saved to {output_file.name}")

        # Save summary stats
        stats_file = OUTPUT_DIR / 'timeframe_data' / f'{tf}_stats.json'
        stats_file.parent.mkdir(parents=True, exist_ok=True)
        with open(stats_file, 'w') as f:
            json.dump(stats, f, indent=2)

    # Save combined summary
    summary_file = OUTPUT_DIR / 'timeframe_data' / 'all_timeframes_summary.json'
    with open(summary_file, 'w') as f:
        json.dump({
            'analysis_date': datetime.now().isoformat(),
            'timeframes_analyzed': len(all_stats),
            'date_range': {'start': START_DATE, 'end': END_DATE},
            'timeframe_stats': all_stats
        }, f, indent=2)

    print(f"\n{'='*60}")
    print(f"✅ Analysis complete! Analyzed {len(all_stats)} timeframes")
    print(f"📄 Summary: {summary_file}")
    print(f"{'='*60}")

if __name__ == '__main__':
    main()
