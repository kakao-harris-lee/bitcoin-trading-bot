#!/usr/bin/env python3
"""
market_analyzer.py
시장 분석 모듈 - TA-Lib 기반 기술 지표
"""

import pandas as pd
import numpy as np

try:
    import talib
    TALIB_AVAILABLE = True
except ImportError:
    TALIB_AVAILABLE = False
    print("⚠️  TA-Lib not installed. Install: brew install ta-lib && pip install TA-Lib")

class MarketAnalyzer:
    """시장 분석기"""

    @staticmethod
    def add_indicators(df: pd.DataFrame, indicators: list = None) -> pd.DataFrame:
        """
        기술 지표 추가

        Args:
            df: 가격 데이터 (open, high, low, close, volume)
            indicators: 추가할 지표 리스트 ['rsi', 'macd', 'bb', ...]

        Returns:
            지표가 추가된 DataFrame
        """
        if not TALIB_AVAILABLE:
            return df

        df = df.copy()

        if indicators is None:
            indicators = ['sma', 'rsi', 'macd']

        if 'sma' in indicators:
            df['sma_20'] = talib.SMA(df['close'], timeperiod=20)
            df['sma_50'] = talib.SMA(df['close'], timeperiod=50)

        if 'ema' in indicators:
            df['ema_12'] = talib.EMA(df['close'], timeperiod=12)
            df['ema_26'] = talib.EMA(df['close'], timeperiod=26)

        if 'rsi' in indicators:
            df['rsi'] = talib.RSI(df['close'], timeperiod=14)

        if 'macd' in indicators:
            macd, signal, hist = talib.MACD(df['close'])
            df['macd'] = macd
            df['macd_signal'] = signal
            df['macd_hist'] = hist

        if 'bb' in indicators:
            upper, middle, lower = talib.BBANDS(df['close'])
            df['bb_upper'] = upper
            df['bb_middle'] = middle
            df['bb_lower'] = lower

        if 'atr' in indicators:
            df['atr'] = talib.ATR(df['high'], df['low'], df['close'], timeperiod=14)

        if 'adx' in indicators:
            df['adx'] = talib.ADX(df['high'], df['low'], df['close'], timeperiod=14)

        if 'mfi' in indicators:
            df['mfi'] = talib.MFI(df['high'], df['low'], df['close'], df['volume'], timeperiod=14)

        if 'roc' in indicators:
            df['roc'] = talib.ROC(df['close'], timeperiod=10)

        if 'stoch' in indicators:
            slowk, slowd = talib.STOCH(df['high'], df['low'], df['close'])
            df['stoch_k'] = slowk
            df['stoch_d'] = slowd

        return df

    @staticmethod
    def classify_market_condition(df: pd.DataFrame, window: int = 20) -> pd.DataFrame:
        """
        시장 조건 분류 (상승/하락/횡보)

        Args:
            df: 가격 데이터
            window: 판단 윈도우

        Returns:
            market_condition 컬럼이 추가된 DataFrame
        """
        df = df.copy()
        df['sma'] = df['close'].rolling(window=window).mean()
        df['market_condition'] = 'sideways'

        # 상승장
        df.loc[df['close'] > df['sma'] * 1.02, 'market_condition'] = 'bull'

        # 하락장
        df.loc[df['close'] < df['sma'] * 0.98, 'market_condition'] = 'bear'

        return df
