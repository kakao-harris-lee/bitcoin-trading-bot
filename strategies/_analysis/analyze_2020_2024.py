#!/usr/bin/env python3
"""
2020-2024 종합 데이터 분석

목표:
1. 연도별 시장 특성 파악
2. 타임프레임별 수익 패턴 분석
3. 기술 지표 효율성 검증
4. 유명 단타 전략 패턴 추출
"""

import sys
sys.path.append('..')

import sqlite3
import pandas as pd
import numpy as np
import talib
import json
from datetime import datetime

# 유명한 단타 전략 지표들
SCALPING_STRATEGIES = {
    'rsi_bollinger': {
        'name': 'RSI + Bollinger Bands (인기 #1)',
        'indicators': ['rsi', 'bb_upper', 'bb_lower', 'bb_middle'],
        'entry': 'RSI < 30 AND price < BB_lower',
        'exit': 'RSI > 70 OR price > BB_upper'
    },
    'breakout': {
        'name': 'Breakout Trading (인기 #2)',
        'indicators': ['atr', 'volume', 'resistance', 'support'],
        'entry': '가격이 저항선 돌파 + 강한 거래량',
        'exit': '모멘텀 약화 OR 손절'
    },
    'momentum': {
        'name': 'Momentum Trading (인기 #3)',
        'indicators': ['macd', 'rsi', 'ema'],
        'entry': 'MACD > Signal AND RSI > 50',
        'exit': 'MACD < Signal OR RSI < 45'
    },
    'range_trading': {
        'name': 'Range Trading (박스권, 인기 #4)',
        'indicators': ['bb', 'rsi', 'support', 'resistance'],
        'entry': '지지선 근처 매수, 저항선 근처 매도',
        'exit': '목표가 도달 OR 박스권 이탈'
    },
    'mean_reversion': {
        'name': 'Mean Reversion (평균회귀, 인기 #5)',
        'indicators': ['sma_20', 'z_score', 'stddev'],
        'entry': '가격이 평균에서 2 표준편차 이상 벗어남',
        'exit': '평균 회귀 시'
    },
    'grid_trading': {
        'name': 'Grid Trading (그리드, 인기 #6)',
        'indicators': ['price_range', 'volatility'],
        'entry': '일정 간격으로 매수/매도 주문 배치',
        'exit': '가격 격자 이동 시 자동 청산'
    },
    'stochastic_scalping': {
        'name': 'Stochastic Oscillator Scalping',
        'indicators': ['stoch_k', 'stoch_d', 'rsi'],
        'entry': 'Stoch K > D (골든크로스) AND K < 20',
        'exit': 'Stoch K < D (데드크로스) OR K > 80'
    }
}


def load_year_data(db_path, year, timeframe='day'):
    """연도별 데이터 로드"""
    conn = sqlite3.connect(db_path)

    table_map = {
        'day': 'bitcoin_day',
        'minute240': 'bitcoin_minute240',
        'minute60': 'bitcoin_minute60',
        'minute30': 'bitcoin_minute30',
        'minute15': 'bitcoin_minute15',
        'minute5': 'bitcoin_minute5'
    }

    table = table_map.get(timeframe, 'bitcoin_day')

    query = f"""
        SELECT
            timestamp,
            opening_price as open,
            high_price as high,
            low_price as low,
            trade_price as close,
            candle_acc_trade_volume as volume
        FROM {table}
        WHERE timestamp >= '{year}-01-01' AND timestamp < '{year+1}-01-01'
        ORDER BY timestamp
    """

    df = pd.read_sql_query(query, conn)
    conn.close()

    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df.set_index('timestamp', inplace=True)

    return df


def add_all_indicators(df):
    """모든 기술 지표 추가"""
    close = df['close'].values
    high = df['high'].values
    low = df['low'].values
    volume = df['volume'].values

    # 트렌드 지표
    df['sma_20'] = talib.SMA(close, timeperiod=20)
    df['sma_50'] = talib.SMA(close, timeperiod=50)
    df['sma_200'] = talib.SMA(close, timeperiod=200)
    df['ema_12'] = talib.EMA(close, timeperiod=12)
    df['ema_26'] = talib.EMA(close, timeperiod=26)
    df['ema_50'] = talib.EMA(close, timeperiod=50)

    # 모멘텀 지표
    df['rsi_14'] = talib.RSI(close, timeperiod=14)
    df['macd'], df['macd_signal'], df['macd_hist'] = talib.MACD(
        close, fastperiod=12, slowperiod=26, signalperiod=9
    )
    df['stoch_k'], df['stoch_d'] = talib.STOCH(
        high, low, close,
        fastk_period=14, slowk_period=3, slowd_period=3
    )

    # 변동성 지표
    df['bb_upper'], df['bb_middle'], df['bb_lower'] = talib.BBANDS(
        close, timeperiod=20, nbdevup=2, nbdevdn=2
    )
    df['atr'] = talib.ATR(high, low, close, timeperiod=14)

    # 거래량 지표
    df['mfi'] = talib.MFI(high, low, close, volume, timeperiod=14)
    df['obv'] = talib.OBV(close, volume)

    # 트렌드 강도
    df['adx'] = talib.ADX(high, low, close, timeperiod=14)

    # 추가 계산 지표
    df['price_to_sma20'] = (close / df['sma_20'].values - 1) * 100
    df['bb_width'] = (df['bb_upper'] - df['bb_lower']) / df['bb_middle'] * 100
    df['bb_position'] = (close - df['bb_lower']) / (df['bb_upper'] - df['bb_lower'] + 1e-10)

    # Z-score (Mean Reversion용)
    rolling_mean = df['close'].rolling(window=20).mean()
    rolling_std = df['close'].rolling(window=20).std()
    df['z_score'] = (df['close'] - rolling_mean) / (rolling_std + 1e-10)

    # Volume ratio
    df['volume_sma_20'] = talib.SMA(volume, timeperiod=20)
    df['volume_ratio'] = volume / (df['volume_sma_20'].values + 1e-10)

    return df


def analyze_year(db_path, year):
    """연도별 분석"""
    print(f"\n{'='*70}")
    print(f"  {year}년 분석")
    print(f"{'='*70}")

    df_day = load_year_data(db_path, year, 'day')
    df_day = add_all_indicators(df_day)

    # 기본 통계
    start_price = df_day['close'].iloc[0]
    end_price = df_day['close'].iloc[-1]
    year_return = (end_price / start_price - 1) * 100
    max_price = df_day['close'].max()
    min_price = df_day['close'].min()
    volatility = df_day['close'].pct_change().std() * 100

    print(f"\n[가격 변동]")
    print(f"  시작가: ${start_price:,.0f}")
    print(f"  종료가: ${end_price:,.0f}")
    print(f"  연간 수익률: {year_return:+.2f}%")
    print(f"  최고가: ${max_price:,.0f}")
    print(f"  최저가: ${min_price:,.0f}")
    print(f"  평균 일 변동성: {volatility:.2f}%")

    # 시장 상태 분류
    df_day['market_state'] = 'UNKNOWN'

    for i in range(len(df_day)):
        if pd.isna(df_day.iloc[i]['mfi']) or pd.isna(df_day.iloc[i]['adx']):
            continue

        mfi = df_day.iloc[i]['mfi']
        macd = df_day.iloc[i]['macd']
        macd_signal = df_day.iloc[i]['macd_signal']
        adx = df_day.iloc[i]['adx']

        # 시장 분류
        if mfi >= 55 and macd > macd_signal and adx >= 25:
            df_day.loc[df_day.index[i], 'market_state'] = 'BULL_STRONG'
        elif mfi >= 48 and macd > macd_signal and adx >= 18:
            df_day.loc[df_day.index[i], 'market_state'] = 'BULL_MODERATE'
        elif mfi >= 45 and macd > macd_signal:
            df_day.loc[df_day.index[i], 'market_state'] = 'SIDEWAYS_UP'
        elif mfi <= 35 and macd < macd_signal and adx >= 20:
            df_day.loc[df_day.index[i], 'market_state'] = 'BEAR_STRONG'
        elif mfi <= 42 and macd < macd_signal:
            df_day.loc[df_day.index[i], 'market_state'] = 'BEAR_MODERATE'
        elif 35 < mfi < 45 and abs(macd - macd_signal) < 100:
            df_day.loc[df_day.index[i], 'market_state'] = 'SIDEWAYS_DOWN'
        else:
            df_day.loc[df_day.index[i], 'market_state'] = 'SIDEWAYS_FLAT'

    # 시장 상태 분포
    state_counts = df_day['market_state'].value_counts()
    total = len(df_day)

    print(f"\n[시장 상태 분포]")
    for state in ['BULL_STRONG', 'BULL_MODERATE', 'SIDEWAYS_UP', 'SIDEWAYS_FLAT',
                  'SIDEWAYS_DOWN', 'BEAR_MODERATE', 'BEAR_STRONG']:
        count = state_counts.get(state, 0)
        pct = count / total * 100
        print(f"  {state:<20}: {count:>3}일 ({pct:>5.1f}%)")

    # 유명 단타 전략 시뮬레이션
    print(f"\n[유명 단타 전략 백테스팅]")

    # 1. RSI + Bollinger Bands
    rsi_bb_trades = simulate_rsi_bollinger(df_day)
    print(f"  RSI + BB 전략: {len(rsi_bb_trades)}회 거래, 평균 수익 {np.mean([t['return'] for t in rsi_bb_trades]) if rsi_bb_trades else 0:.2f}%")

    # 2. Breakout Trading
    breakout_trades = simulate_breakout(df_day)
    print(f"  Breakout 전략: {len(breakout_trades)}회 거래, 평균 수익 {np.mean([t['return'] for t in breakout_trades]) if breakout_trades else 0:.2f}%")

    # 3. Mean Reversion
    mean_rev_trades = simulate_mean_reversion(df_day)
    print(f"  Mean Reversion: {len(mean_rev_trades)}회 거래, 평균 수익 {np.mean([t['return'] for t in mean_rev_trades]) if mean_rev_trades else 0:.2f}%")

    # 4. Momentum Trading
    momentum_trades = simulate_momentum(df_day)
    print(f"  Momentum 전략: {len(momentum_trades)}회 거래, 평균 수익 {np.mean([t['return'] for t in momentum_trades]) if momentum_trades else 0:.2f}%")

    return {
        'year': year,
        'start_price': start_price,
        'end_price': end_price,
        'year_return': year_return,
        'volatility': volatility,
        'market_states': state_counts.to_dict(),
        'scalping_strategies': {
            'rsi_bollinger': {'trades': len(rsi_bb_trades), 'avg_return': np.mean([t['return'] for t in rsi_bb_trades]) if rsi_bb_trades else 0},
            'breakout': {'trades': len(breakout_trades), 'avg_return': np.mean([t['return'] for t in breakout_trades]) if breakout_trades else 0},
            'mean_reversion': {'trades': len(mean_rev_trades), 'avg_return': np.mean([t['return'] for t in mean_rev_trades]) if mean_rev_trades else 0},
            'momentum': {'trades': len(momentum_trades), 'avg_return': np.mean([t['return'] for t in momentum_trades]) if momentum_trades else 0}
        }
    }


def simulate_rsi_bollinger(df):
    """RSI + Bollinger Bands 전략 시뮬레이션"""
    trades = []
    in_position = False
    entry_price = 0

    for i in range(30, len(df)):
        if pd.isna(df.iloc[i]['rsi_14']) or pd.isna(df.iloc[i]['bb_lower']):
            continue

        rsi = df.iloc[i]['rsi_14']
        close = df.iloc[i]['close']
        bb_lower = df.iloc[i]['bb_lower']
        bb_upper = df.iloc[i]['bb_upper']

        # Entry: RSI < 30 AND price < BB_lower
        if not in_position and rsi < 30 and close < bb_lower:
            in_position = True
            entry_price = close

        # Exit: RSI > 70 OR price > BB_upper
        elif in_position and (rsi > 70 or close > bb_upper):
            profit = (close / entry_price - 1) * 100
            trades.append({'entry': entry_price, 'exit': close, 'return': profit})
            in_position = False

    return trades


def simulate_breakout(df):
    """Breakout 전략 시뮬레이션"""
    trades = []
    in_position = False
    entry_price = 0

    for i in range(50, len(df)):
        if pd.isna(df.iloc[i]['atr']):
            continue

        close = df.iloc[i]['close']
        high_50 = df.iloc[i-50:i]['high'].max()
        volume_ratio = df.iloc[i]['volume_ratio']

        # Entry: 가격이 50일 최고가 돌파 + 거래량 1.5배
        if not in_position and close > high_50 and volume_ratio > 1.5:
            in_position = True
            entry_price = close

        # Exit: 진입 후 ATR * 2 하락 OR 5% 이상 수익
        elif in_position:
            atr = df.iloc[i]['atr']
            if close < entry_price - (atr * 2) or close > entry_price * 1.05:
                profit = (close / entry_price - 1) * 100
                trades.append({'entry': entry_price, 'exit': close, 'return': profit})
                in_position = False

    return trades


def simulate_mean_reversion(df):
    """Mean Reversion 전략 시뮬레이션"""
    trades = []
    in_position = False
    entry_price = 0

    for i in range(30, len(df)):
        if pd.isna(df.iloc[i]['z_score']):
            continue

        close = df.iloc[i]['close']
        z_score = df.iloc[i]['z_score']

        # Entry: z-score < -2 (평균에서 2 표준편차 아래)
        if not in_position and z_score < -2:
            in_position = True
            entry_price = close

        # Exit: z-score > 0 (평균 회귀)
        elif in_position and z_score > 0:
            profit = (close / entry_price - 1) * 100
            trades.append({'entry': entry_price, 'exit': close, 'return': profit})
            in_position = False

    return trades


def simulate_momentum(df):
    """Momentum 전략 시뮬레이션"""
    trades = []
    in_position = False
    entry_price = 0

    for i in range(30, len(df)):
        if pd.isna(df.iloc[i]['macd']) or pd.isna(df.iloc[i]['rsi_14']):
            continue

        close = df.iloc[i]['close']
        macd = df.iloc[i]['macd']
        macd_signal = df.iloc[i]['macd_signal']
        rsi = df.iloc[i]['rsi_14']

        # Entry: MACD > Signal AND RSI > 50
        if not in_position and macd > macd_signal and rsi > 50:
            in_position = True
            entry_price = close

        # Exit: MACD < Signal OR RSI < 45
        elif in_position and (macd < macd_signal or rsi < 45):
            profit = (close / entry_price - 1) * 100
            trades.append({'entry': entry_price, 'exit': close, 'return': profit})
            in_position = False

    return trades


def main():
    db_path = '../../upbit_bitcoin.db'
    years = [2020, 2021, 2022, 2023, 2024]

    print("\n" + "="*70)
    print("  2020-2024 종합 데이터 분석")
    print("  유명 단타 전략 백테스팅 포함")
    print("="*70)

    all_results = []

    for year in years:
        result = analyze_year(db_path, year)
        all_results.append(result)

    # 종합 분석
    print(f"\n{'='*70}")
    print("  5년 종합 분석")
    print(f"{'='*70}")

    total_return = 1.0
    for r in all_results:
        total_return *= (1 + r['year_return'] / 100)

    compound_annual_return = (total_return ** (1/5) - 1) * 100
    avg_volatility = np.mean([r['volatility'] for r in all_results])

    print(f"\n누적 수익률: {(total_return - 1) * 100:.2f}%")
    print(f"연평균 수익률 (CAGR): {compound_annual_return:.2f}%")
    print(f"평균 변동성: {avg_volatility:.2f}%")

    # 최적 전략 추천
    print(f"\n{'='*70}")
    print("  유명 단타 전략 5년 평균 성과")
    print(f"{'='*70}")

    strategy_avg = {}
    for strategy_name in ['rsi_bollinger', 'breakout', 'mean_reversion', 'momentum']:
        avg_trades = np.mean([r['scalping_strategies'][strategy_name]['trades'] for r in all_results])
        avg_return = np.mean([r['scalping_strategies'][strategy_name]['avg_return'] for r in all_results])
        strategy_avg[strategy_name] = {'avg_trades': avg_trades, 'avg_return': avg_return}

        strategy_full_name = {
            'rsi_bollinger': 'RSI + Bollinger Bands',
            'breakout': 'Breakout Trading',
            'mean_reversion': 'Mean Reversion',
            'momentum': 'Momentum Trading'
        }[strategy_name]

        print(f"{strategy_full_name:<25}: {avg_trades:.1f}회/년, 평균 {avg_return:+.2f}%")

    # 결과 저장
    with open('2020_2024_analysis_results.json', 'w', encoding='utf-8') as f:
        json.dump({
            'yearly_results': all_results,
            'summary': {
                'total_return': (total_return - 1) * 100,
                'cagr': compound_annual_return,
                'avg_volatility': avg_volatility
            },
            'strategy_averages': strategy_avg,
            'scalping_strategies_info': SCALPING_STRATEGIES
        }, f, indent=2, ensure_ascii=False, default=str)

    print(f"\n결과 저장: 2020_2024_analysis_results.json")


if __name__ == '__main__':
    main()
