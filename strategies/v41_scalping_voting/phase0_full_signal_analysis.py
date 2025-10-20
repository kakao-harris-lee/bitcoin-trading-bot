#!/usr/bin/env python3
"""
Phase 0-1: 전수 신호 분석 (2020~2024, 모든 타임프레임)

목표:
- 756,375개 캔들 전수 분석
- 76,300개 예상 매수 신호 추출
- 타임프레임별 CSV 저장 (생략 없음)

타임프레임:
- minute5: 525,600 캔들
- minute15: 175,200 캔들
- minute60: 43,800 캔들
- minute240: 10,950 캔들
- day: 1,825 캔들
"""

import sys
sys.path.append('../..')

import json
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import talib
from tqdm import tqdm
import warnings
warnings.filterwarnings('ignore')

from core import DataLoader
from voting_ensemble import VotingEnsemble


class FullSignalAnalyzer:
    """전수 신호 분석기"""

    def __init__(self, config_path='config.json', db_path='../../upbit_bitcoin.db'):
        # Config 로드
        with open(config_path) as f:
            self.config = json.load(f)

        self.db_path = db_path
        self.timeframes = ['day']  # day만

        # 통계
        self.total_candles_analyzed = 0
        self.total_signals_found = 0

    def add_indicators(self, df, timeframe):
        """타임프레임별 지표 추가"""
        ind_config = self.config['indicators'][timeframe]

        # RSI
        df['rsi'] = talib.RSI(df['close'], timeperiod=ind_config['rsi_period'])

        # Volume SMA
        df['volume_sma'] = talib.SMA(df['volume'], timeperiod=ind_config['volume_sma'])

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
        if 'ema_mid' in ind_config:
            df['ema_mid'] = talib.EMA(df['close'], timeperiod=ind_config['ema_mid'])

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

        # ADX + DI (일부 타임프레임)
        if 'adx_period' in ind_config:
            df['adx'] = talib.ADX(df['high'], df['low'], df['close'], timeperiod=ind_config['adx_period'])
            df['plus_di'] = talib.PLUS_DI(df['high'], df['low'], df['close'], timeperiod=ind_config['adx_period'])
            df['minus_di'] = talib.MINUS_DI(df['high'], df['low'], df['close'], timeperiod=ind_config['adx_period'])

        # MFI (일부 타임프레임)
        if 'mfi_period' in ind_config:
            df['mfi'] = talib.MFI(
                df['high'], df['low'], df['close'], df['volume'],
                timeperiod=ind_config['mfi_period']
            )

        # ATR (일부 타임프레임)
        if 'atr_period' in ind_config:
            df['atr'] = talib.ATR(df['high'], df['low'], df['close'], timeperiod=ind_config['atr_period'])

        return df.dropna().reset_index(drop=True)

    def analyze_timeframe(self, timeframe, start_date='2020-01-01', end_date='2024-12-31'):
        """
        단일 타임프레임 전수 분석

        Returns:
            signals_df: 모든 매수 신호 DataFrame
        """
        print(f"\n{'='*70}")
        print(f"[{timeframe}] 전수 분석 시작")
        print(f"기간: {start_date} ~ {end_date}")
        print(f"{'='*70}\n")

        # 데이터 로드
        print(f"[{timeframe}] 데이터 로드 중...")
        with DataLoader(self.db_path) as loader:
            df = loader.load_timeframe(timeframe, start_date=start_date, end_date=end_date)

        print(f"[{timeframe}] 로드 완료: {len(df):,} 캔들")

        # 지표 추가
        print(f"[{timeframe}] 지표 계산 중...")
        df = self.add_indicators(df, timeframe)
        print(f"[{timeframe}] 지표 계산 완료: {len(df):,} 캔들 (NaN 제거 후)")

        self.total_candles_analyzed += len(df)

        # VotingEnsemble 초기화
        print(f"[{timeframe}] VotingEnsemble 초기화...")
        ensemble = VotingEnsemble(timeframe, self.config, db_path=self.db_path)

        # 전수 신호 추출
        print(f"[{timeframe}] 전수 신호 추출 중 (0/{len(df):,} 캔들)...")

        signals = []

        for i in tqdm(range(len(df)), desc=f"[{timeframe}] Signal Extraction"):
            # 투표 실행
            signal, votes = ensemble.get_signal(df, i, 'none')

            if signal == 'buy':
                # 현재 캔들 정보
                current = df.iloc[i]

                # BB Position 계산
                bb_width = current['bb_upper'] - current['bb_lower']
                if bb_width > 0:
                    bb_position = (current['close'] - current['bb_lower']) / bb_width
                    bb_width_pct = bb_width / current['bb_middle']
                else:
                    bb_position = 0.5
                    bb_width_pct = 0.0

                # Volume Ratio
                volume_ratio = current['volume'] / current['volume_sma'] if current['volume_sma'] > 0 else 1.0

                # 신호 기록
                record = {
                    # 기본 정보
                    'timestamp': current['timestamp'],
                    'price': current['close'],
                    'high': current['high'],
                    'low': current['low'],
                    'volume': current['volume'],

                    # 기술 지표
                    'rsi': current['rsi'],
                    'volume_sma': current['volume_sma'],
                    'volume_ratio': volume_ratio,
                    'macd': current['macd'],
                    'macd_signal': current['macd_signal'],
                    'macd_hist': current['macd_hist'],
                    'ema_fast': current['ema_fast'],
                    'ema_slow': current['ema_slow'],
                    'ema_mid': current.get('ema_mid', np.nan),
                    'bb_upper': current['bb_upper'],
                    'bb_middle': current['bb_middle'],
                    'bb_lower': current['bb_lower'],
                    'bb_position': bb_position,
                    'bb_width_pct': bb_width_pct,
                    'adx': current.get('adx', np.nan),
                    'plus_di': current.get('plus_di', np.nan),
                    'minus_di': current.get('minus_di', np.nan),
                    'mfi': current.get('mfi', np.nan),
                    'atr': current.get('atr', np.nan),

                    # 투표 상세
                    'layer1_rsi_vote': votes['layer1']['details']['rsi_extreme'],
                    'layer1_volume_vote': votes['layer1']['details']['volume_spike'],
                    'layer1_macd_vote': votes['layer1']['details']['macd_cross'],
                    'layer2_ema_vote': votes['layer2']['details']['ema_crossover'],
                    'layer2_bb_vote': votes['layer2']['details']['bb_reversion'],
                    'layer2_adx_vote': votes['layer2']['details']['adx_strength'],
                    'layer3_day_vote': votes['layer3']['details']['day_market_state'],
                    'layer3_market_state': votes['layer3']['details']['market_state'],
                    'total_buy_votes': votes['total_buy_votes'],
                    'total_sell_votes': votes['total_sell_votes'],
                    'total_hold_votes': votes['total_hold_votes'],
                    'turn_of_candle': votes.get('turn_of_candle', False),
                    'vote_boost_applied': votes.get('vote_boost_applied', False),

                    # 시간 정보
                    'hour': pd.to_datetime(current['timestamp']).hour,
                    'weekday': pd.to_datetime(current['timestamp']).weekday(),
                    'month': pd.to_datetime(current['timestamp']).month,
                    'quarter': (pd.to_datetime(current['timestamp']).month - 1) // 3 + 1,
                    'year': pd.to_datetime(current['timestamp']).year,

                    # 인덱스 (Lookforward 분석용)
                    'candle_idx': i
                }

                signals.append(record)

        signals_df = pd.DataFrame(signals)
        self.total_signals_found += len(signals_df)

        print(f"\n[{timeframe}] 신호 추출 완료")
        print(f"  - 분석 캔들: {len(df):,} 개")
        print(f"  - 매수 신호: {len(signals_df):,} 개")
        print(f"  - 신호 발생률: {len(signals_df) / len(df) * 100:.2f}%")

        # CSV 저장
        output_path = f'analysis/signals/signals_{timeframe}_buy.csv'
        signals_df.to_csv(output_path, index=False)
        print(f"  - 저장 완료: {output_path}")

        return signals_df, df

    def run_full_analysis(self):
        """전체 타임프레임 전수 분석 실행"""
        print(f"\n{'='*70}")
        print(f"v41 전수 신호 분석 시작")
        print(f"{'='*70}")
        print(f"분석 기간: 2020-01-01 ~ 2024-12-31 (1,825일)")
        print(f"타임프레임: {', '.join(self.timeframes)}")
        print(f"예상 총 캔들: 756,375개")
        print(f"예상 총 신호: ~76,300개")
        print(f"{'='*70}\n")

        start_time = datetime.now()

        # 타임프레임별 분석
        for tf in self.timeframes:
            self.analyze_timeframe(tf)

        end_time = datetime.now()
        elapsed = end_time - start_time

        # 최종 요약
        print(f"\n{'='*70}")
        print(f"전수 분석 완료!")
        print(f"{'='*70}")
        print(f"총 분석 캔들: {self.total_candles_analyzed:,} 개")
        print(f"총 매수 신호: {self.total_signals_found:,} 개")
        print(f"전체 신호 발생률: {self.total_signals_found / self.total_candles_analyzed * 100:.2f}%")
        print(f"소요 시간: {elapsed}")
        print(f"{'='*70}\n")

        # 타임프레임별 요약
        print(f"타임프레임별 신호 수:")
        for tf in self.timeframes:
            signals_file = f'analysis/signals/signals_{tf}_buy.csv'
            try:
                df_signals = pd.read_csv(signals_file)
                print(f"  - {tf:12s}: {len(df_signals):>6,} 개")
            except:
                print(f"  - {tf:12s}: ERROR")

        print(f"\n다음 단계: Lookforward 성과 분석")


if __name__ == "__main__":
    analyzer = FullSignalAnalyzer()
    analyzer.run_full_analysis()
