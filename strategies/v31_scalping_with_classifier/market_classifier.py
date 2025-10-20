#!/usr/bin/env python3
"""
Market Classifier - Day-level signal generator
Determines if market is BULL, BEAR, or SIDEWAYS
"""

import sqlite3
import pandas as pd
import talib
import numpy as np

class MarketClassifier:
    """Day-level market state classifier using MFI + MACD"""

    def __init__(self, db_path, config):
        self.db_path = db_path
        self.config = config
        self.day_data = None
        self.current_state = 'SIDEWAYS'

    def load_day_data(self, start_date, end_date):
        """Load day-level data and calculate indicators"""
        conn = sqlite3.connect(self.db_path)
        query = f"""
            SELECT timestamp, opening_price as open, high_price as high,
                   low_price as low, trade_price as close,
                   candle_acc_trade_volume as volume
            FROM bitcoin_day
            WHERE timestamp >= '{start_date}' AND timestamp <= '{end_date}'
            ORDER BY timestamp ASC
        """
        df = pd.read_sql_query(query, conn)
        conn.close()

        df['timestamp'] = pd.to_datetime(df['timestamp'])

        # Calculate indicators
        close = df['close'].values
        high = df['high'].values
        low = df['low'].values
        volume = df['volume'].values

        df['mfi'] = talib.MFI(high, low, close, volume,
                              timeperiod=self.config['indicators']['mfi_period'])

        macd, macd_signal, macd_hist = talib.MACD(
            close,
            fastperiod=self.config['indicators']['macd_fast'],
            slowperiod=self.config['indicators']['macd_slow'],
            signalperiod=self.config['indicators']['macd_signal']
        )
        df['macd'] = macd
        df['macd_signal'] = macd_signal
        df['macd_hist'] = macd_hist

        self.day_data = df
        return df

    def classify_market_at_date(self, target_date):
        """
        Classify market state at a specific date

        Returns: 'BULL', 'BEAR', or 'SIDEWAYS'
        """
        if self.day_data is None:
            raise ValueError("Day data not loaded. Call load_day_data() first.")

        # Find the day record for target_date (or most recent before it)
        target_date = pd.to_datetime(target_date)

        # Filter to dates on or before target
        valid_data = self.day_data[self.day_data['timestamp'] <= target_date]

        if len(valid_data) == 0:
            return 'SIDEWAYS'  # Default if no data

        # Get most recent day
        latest = valid_data.iloc[-1]

        mfi = latest['mfi']
        macd = latest['macd']
        macd_signal = latest['macd_signal']

        # Check for NaN
        if pd.isna(mfi) or pd.isna(macd) or pd.isna(macd_signal):
            return 'SIDEWAYS'

        # Bull conditions
        bull_mfi = mfi >= self.config['classifier_settings']['bull_conditions']['mfi_min']
        bull_macd = macd > macd_signal

        if bull_mfi and bull_macd:
            self.current_state = 'BULL'
            return 'BULL'

        # Bear conditions
        bear_mfi = mfi <= self.config['classifier_settings']['bear_conditions']['mfi_max']
        bear_macd = macd < macd_signal

        if bear_mfi and bear_macd:
            self.current_state = 'BEAR'
            return 'BEAR'

        # Default: Sideways
        self.current_state = 'SIDEWAYS'
        return 'SIDEWAYS'

    def get_current_state(self):
        """Get most recent classification"""
        return self.current_state

    def get_day_indicators(self, target_date):
        """Get day-level indicators for a specific date"""
        if self.day_data is None:
            return None

        target_date = pd.to_datetime(target_date)
        valid_data = self.day_data[self.day_data['timestamp'] <= target_date]

        if len(valid_data) == 0:
            return None

        return valid_data.iloc[-1].to_dict()
