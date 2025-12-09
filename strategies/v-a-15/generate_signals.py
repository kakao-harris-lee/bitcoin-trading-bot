#!/usr/bin/env python3
"""v-a-15 Signal Generator - Simplified"""

import sys
from pathlib import Path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

import pandas as pd
import json
import importlib.util
from core.data_loader import DataLoader
from core.market_analyzer import MarketAnalyzer

va15_dir = Path(__file__).parent

# Market Classifier
spec = importlib.util.spec_from_file_location("mc", va15_dir / "core" / "market_classifier.py")
mc_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mc_module)
MarketClassifierV37 = mc_module.MarketClassifierV37

# Trend Following
spec = importlib.util.spec_from_file_location("trend", va15_dir / "strategies" / "trend_following_enhanced.py")
trend_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(trend_module)
EnhancedTrendFollowingStrategy = trend_module.EnhancedTrendFollowingStrategy

# SIDEWAYS Hybrid
spec = importlib.util.spec_from_file_location("sideways", va15_dir / "strategies" / "sideways_hybrid.py")
sideways_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sideways_module)
SidewaysHybridStrategy = sideways_module.SidewaysHybridStrategy


class V_A_15_SignalGenerator:
    def __init__(self, config: dict):
        self.config = config
        self.classifier = MarketClassifierV37()
        self.trend_config = config.get('trend_following_enhanced', {})
        self.sideways_config = config.get('sideways_hybrid', {})

    def _add_histogram_zscore(self, df: pd.DataFrame, lookback: int = 60):
        """MACD Histogram z-score 계산"""
        df = df.copy()

        # MACD Histogram (MACD - Signal)
        df['macd_histogram'] = df['macd'] - df['macd_signal']

        # Rolling 평균 및 표준편차
        df['histogram_mean'] = df['macd_histogram'].rolling(window=lookback).mean()
        df['histogram_std'] = df['macd_histogram'].rolling(window=lookback).std()

        # z-score 계산
        df['histogram_zscore'] = (df['macd_histogram'] - df['histogram_mean']) / df['histogram_std']
        df['histogram_zscore'] = df['histogram_zscore'].fillna(0)

        return df

    def generate_signals(self, df: pd.DataFrame, year: int):
        # MACD Histogram z-score 계산 (60일 rolling)
        df = self._add_histogram_zscore(df, lookback=60)

        signals = []
        market_states = []

        for i in range(30, len(df)):
            row = df.iloc[i]
            prev_row = df.iloc[i-1] if i > 0 else None
            df_recent = df.iloc[max(0, i-60):i+1]

            market_state = self.classifier.classify_market_state(row, prev_row, df_recent)
            market_states.append({'timestamp': row['timestamp'], 'market_state': market_state})

            signal = None

            # Trend Following (BULL 시장) - Stateless Entry Check
            if market_state in ['BULL_STRONG', 'BULL_MODERATE']:
                signal = self._check_trend_entry(row, prev_row, df_recent, market_state)

            # SIDEWAYS Hybrid
            if signal is None and market_state.startswith('SIDEWAYS'):
                signal = self._check_sideways_entry(row, prev_row, df_recent, market_state)

            if signal is not None:
                signals.append({
                    'timestamp': row['timestamp'],
                    'entry_price': row['close'],
                    'market_state': signal.get('market_state', market_state),
                    'strategy': signal.get('strategy', 'unknown'),
                    'reason': signal.get('reason', ''),
                    'fraction': signal.get('fraction', 0.5),
                    'confidence': signal.get('confidence', 0),
                    'level': signal.get('level'),
                    'rsi': row.get('rsi', 50),
                    'macd': row.get('macd', 0),
                    'adx': row.get('adx', 0),
                    'atr': row.get('atr', 0),
                    'histogram_zscore': row.get('histogram_zscore', 0)
                })

        return pd.DataFrame(signals), pd.DataFrame(market_states)

    def _check_trend_entry(self, row, prev_row, df_recent, market_state):
        """Stateless Trend Entry Check"""
        if prev_row is None or len(df_recent) < 20:
            return None

        macd = row.get('macd', 0)
        macd_signal = row.get('macd_signal', 0)
        prev_macd = prev_row.get('macd', 0)
        prev_signal = prev_row.get('macd_signal', 0)
        adx = row.get('adx', 20)
        rsi = row.get('rsi', 50)
        volume = row.get('volume', 0)
        avg_volume = df_recent['volume'].iloc[-20:].mean() if len(df_recent) >= 20 else volume

        # MACD 3일 연속 유지 조건 (False Signal 제거)
        if len(df_recent) < 3:
            return None

        # 최근 3일 모두 MACD > Signal 확인
        recent_3days = df_recent.iloc[-3:]
        macd_above_signal_3days = (recent_3days['macd'] > recent_3days['macd_signal']).all()

        if not macd_above_signal_3days:
            return None

        # Histogram z-score > 0.5 (통계적 유의성)
        histogram_zscore = row.get('histogram_zscore', 0)
        if histogram_zscore <= 0.5:
            return None

        # ADX >= threshold
        if adx < self.trend_config.get('adx_threshold', 15):
            return None

        # RSI < max
        if rsi >= self.trend_config.get('rsi_max', 70):
            return None

        # Volume > mult
        volume_mult = self.trend_config.get('volume_mult', 1.2)
        if volume < avg_volume * volume_mult:
            return None

        # Confidence Score
        confidence = self._calc_confidence(adx, rsi, volume / avg_volume if avg_volume > 0 else 1.0, market_state, macd, macd_signal)

        if confidence < self.trend_config.get('min_confidence', 50):
            return None

        return {
            'action': 'buy',
            'strategy': 'trend_enhanced',
            'fraction': self.trend_config.get('position_size', 0.7),
            'reason': f'TREND_ENHANCED (ADX={adx:.1f}, RSI={rsi:.1f}, Conf={confidence:.0f})',
            'confidence': confidence,
            'market_state': market_state
        }

    def _calc_confidence(self, adx, rsi, volume_ratio, market_state, macd, macd_signal):
        score = 0.0
        if adx >= 30: score += 30
        elif adx >= 25: score += 25
        elif adx >= 20: score += 20
        elif adx >= 15: score += 15
        
        if 40 <= rsi <= 55: score += 20
        elif 30 <= rsi < 40: score += 18
        elif 55 < rsi <= 60: score += 15
        elif 60 < rsi < 70: score += 10
        
        if volume_ratio >= 3.0: score += 20
        elif volume_ratio >= 2.5: score += 18
        elif volume_ratio >= 2.0: score += 15
        elif volume_ratio >= 1.2: score += 10
        
        if market_state == 'BULL_STRONG': score += 15
        elif market_state == 'BULL_MODERATE': score += 12
        
        macd_diff = abs(macd - macd_signal)
        macd_signal_abs = abs(macd_signal)
        if macd_signal_abs > 0:
            macd_strength = macd_diff / macd_signal_abs
            if macd_strength >= 0.10: score += 15
            elif macd_strength >= 0.05: score += 12
            elif macd_strength >= 0.02: score += 8
        
        return min(100, score)

    def _check_sideways_entry(self, row, prev_row, df_recent, market_state):
        """Stateless SIDEWAYS Entry Check"""
        # RSI + BB
        rsi = row.get('rsi', 50)
        bb_lower = row.get('bb_lower', 0)
        close = row['close']
        
        if self.sideways_config.get('use_rsi_bb', True):
            rsi_threshold = self.sideways_config.get('rsi_bb_oversold', 30)
            if rsi < rsi_threshold and close < bb_lower:
                return {
                    'action': 'buy',
                    'strategy': 'rsi_bb',
                    'fraction': self.sideways_config.get('position_size', 0.4),
                    'reason': f'SIDEWAYS_RSI_BB (RSI={rsi:.1f})',
                    'confidence': 0,
                    'market_state': market_state
                }
        
        # Stochastic
        if prev_row is not None and self.sideways_config.get('use_stoch', True):
            stoch_k = row.get('stoch_k', 50)
            stoch_d = row.get('stoch_d', 50)
            prev_k = prev_row.get('stoch_k', 50)
            prev_d = prev_row.get('stoch_d', 50)
            oversold = self.sideways_config.get('stoch_oversold', 20)
            
            golden_cross = (prev_k <= prev_d) and (stoch_k > stoch_d)
            if golden_cross and stoch_k < oversold:
                return {
                    'action': 'buy',
                    'strategy': 'stoch',
                    'fraction': self.sideways_config.get('position_size', 0.4),
                    'reason': f'SIDEWAYS_STOCH (K={stoch_k:.1f})',
                    'confidence': 0,
                    'market_state': market_state
                }
        
        return None


def main():
    config_path = Path(__file__).parent / 'config.json'
    with open(config_path, 'r') as f:
        config = json.load(f)

    TIMEFRAME = 'day'
    YEARS = [2024]

    print("="*70)
    print("  v-a-15 Signal Generator (Optimized)")
    print("="*70)

    db_path = Path(__file__).parent.parent.parent / 'upbit_bitcoin.db'

    for year in YEARS:
        print(f"\n{year}년 시그널 생성...")

        with DataLoader(str(db_path)) as loader:
            df = loader.load_timeframe(TIMEFRAME, f"{year}-01-01", f"{year}-12-31")

        if df is None:
            continue

        df = MarketAnalyzer.add_indicators(df, ['rsi', 'macd', 'adx', 'atr', 'bb', 'stoch'])

        generator = V_A_15_SignalGenerator(config)
        signals_df, market_states_df = generator.generate_signals(df, year)

        print(f"  생성된 시그널: {len(signals_df)}개")

        if len(signals_df) > 0:
            dist = signals_df['strategy'].value_counts().to_dict()
            print(f"  전략별: {dist}")
            
            market_dist = signals_df['market_state'].value_counts().to_dict()
            print(f"  시장별: {market_dist}")
            
            if 'confidence' in signals_df.columns:
                avg_conf = signals_df['confidence'].mean()
                print(f"  평균 신뢰도: {avg_conf:.1f}/100")

        output_dir = Path(__file__).parent / 'signals'
        output_dir.mkdir(exist_ok=True)
        output_file = output_dir / f'day_{year}_signals.json'

        signals_json = {
            'strategy': 'v-a-15',
            'year': year,
            'total_signals': len(signals_df),
            'signals': signals_df.to_dict('records') if len(signals_df) > 0 else []
        }

        for s in signals_json['signals']:
            if 'timestamp' in s:
                s['timestamp'] = s['timestamp'].isoformat()

        with open(output_file, 'w') as f:
            json.dump(signals_json, f, indent=2)

        print(f"  ✅ 저장: {output_file}")
        
        market_csv = output_dir / f'day_{year}_market_states.csv'
        market_states_df.to_csv(market_csv, index=False)

if __name__ == '__main__':
    main()
