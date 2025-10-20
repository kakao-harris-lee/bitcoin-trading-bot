#!/usr/bin/env python3
"""
Phase 0: 브루트포스 전수 매매 기회 탐색

목표:
- 모든 캔들에서 매수했을 때의 수익률 분포 파악
- N일 보유 시나리오별 수익/손실 분석
- 수익이 나는 지점의 공통 특성 추출

타임프레임: minute5, minute15, minute60, minute240, day
보유 기간: 1, 3, 5, 7, 14, 30일
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

class BruteforceAnalyzer:
    """전수 매매 기회 탐색기"""

    def __init__(self, config_path='config.json', db_path='../../upbit_bitcoin.db'):
        with open(config_path) as f:
            self.config = json.load(f)

        self.db_path = db_path
        self.timeframes = ['minute5', 'minute15', 'minute60', 'minute240', 'day']
        self.hold_periods = [1, 3, 5, 7, 14, 30]  # 보유 일수

        # 결과 저장
        self.results = {}

    def add_indicators(self, df, timeframe):
        """기술적 지표 추가"""
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

        # BB Position (0~1, 0=하단, 1=상단)
        df['bb_position'] = (df['close'] - df['bb_lower']) / (df['bb_upper'] - df['bb_lower'])

        # ADX
        df['adx'] = talib.ADX(df['high'], df['low'], df['close'], timeperiod=ind_config.get('adx_period', 14))

        # MFI
        df['mfi'] = talib.MFI(df['high'], df['low'], df['close'], df['volume'], timeperiod=ind_config.get('mfi_period', 14))

        # ATR
        if 'atr_period' in ind_config:
            df['atr'] = talib.ATR(df['high'], df['low'], df['close'], timeperiod=ind_config['atr_period'])

        # NaN 제거
        df = df.dropna()

        return df

    def calculate_future_returns(self, df, hold_periods):
        """미래 수익률 계산 (모든 보유 기간)"""
        for days in hold_periods:
            # 미래 종가
            df[f'future_close_{days}d'] = df['close'].shift(-days)

            # 수익률
            df[f'return_{days}d'] = (df[f'future_close_{days}d'] - df['close']) / df['close']

            # 수익/손실 구분
            df[f'profitable_{days}d'] = (df[f'return_{days}d'] > 0.01).astype(int)  # 1% 이상

            # 최대 낙폭 (보유 기간 동안)
            max_dd_list = []
            for i in range(len(df)):
                if i + days >= len(df):
                    max_dd_list.append(np.nan)
                    continue

                buy_price = df.iloc[i]['close']
                future_slice = df.iloc[i:i+days+1]
                max_dd = ((future_slice['close'].min() - buy_price) / buy_price).item()
                max_dd_list.append(max_dd)

            df[f'max_dd_{days}d'] = max_dd_list

        return df

    def analyze_timeframe(self, timeframe):
        """타임프레임별 전수 분석"""
        print(f"\n{'='*70}")
        print(f"[{timeframe}] 브루트포스 분석 시작")
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

        # 미래 수익률 계산
        print(f"[{timeframe}] 미래 수익률 계산 중...")
        df = self.calculate_future_returns(df, self.hold_periods)

        # NaN 제거 (미래 데이터가 없는 마지막 캔들들)
        df = df.dropna()
        print(f"[{timeframe}] 수익률 계산 완료: {len(df):,} 캔들")

        # 보유 기간별 분석
        print(f"\n[{timeframe}] 보유 기간별 수익률 분석:")
        print(f"{'='*70}")

        stats = {}
        for days in self.hold_periods:
            returns = df[f'return_{days}d']
            profitable = df[f'profitable_{days}d']
            max_dd = df[f'max_dd_{days}d']

            # 통계
            total = len(returns)
            profit_count = profitable.sum()
            win_rate = profit_count / total
            avg_return = returns.mean()
            median_return = returns.median()
            std_return = returns.std()
            sharpe = avg_return / std_return if std_return > 0 else 0

            # 수익 케이스만
            profit_returns = returns[profitable == 1]
            avg_profit = profit_returns.mean() if len(profit_returns) > 0 else 0

            # 손실 케이스만
            loss_returns = returns[profitable == 0]
            avg_loss = loss_returns.mean() if len(loss_returns) > 0 else 0

            # 평균 최대 낙폭
            avg_max_dd = max_dd.mean()

            stats[f'{days}d'] = {
                'total_signals': total,
                'profitable_signals': profit_count,
                'win_rate': win_rate,
                'avg_return': avg_return,
                'median_return': median_return,
                'std_return': std_return,
                'sharpe': sharpe,
                'avg_profit': avg_profit,
                'avg_loss': avg_loss,
                'avg_max_dd': avg_max_dd
            }

            print(f"\n{days}일 보유:")
            print(f"  총 시나리오: {total:,}개")
            print(f"  수익 시나리오: {profit_count:,}개 ({win_rate:.2%})")
            print(f"  평균 수익률: {avg_return:.2%}")
            print(f"  중앙 수익률: {median_return:.2%}")
            print(f"  Sharpe Ratio: {sharpe:.2f}")
            print(f"  평균 수익 (수익 시): {avg_profit:.2%}")
            print(f"  평균 손실 (손실 시): {avg_loss:.2%}")
            print(f"  평균 최대 낙폭: {avg_max_dd:.2%}")

        # 최적 보유 기간 선정
        best_days = max(stats.keys(), key=lambda k: stats[k]['sharpe'])
        print(f"\n{'='*70}")
        print(f"[{timeframe}] 최적 보유 기간: {best_days} (Sharpe {stats[best_days]['sharpe']:.2f})")
        print(f"{'='*70}")

        # 수익 케이스 특성 분석
        print(f"\n[{timeframe}] 수익 케이스 특성 분석 (최적 보유 기간: {best_days}):")
        print(f"{'='*70}")

        best_days_num = int(best_days.replace('d', ''))
        profitable_df = df[df[f'profitable_{best_days_num}d'] == 1].copy()
        losing_df = df[df[f'profitable_{best_days_num}d'] == 0].copy()

        features = ['rsi', 'volume_ratio', 'bb_position', 'macd', 'ema_fast', 'ema_slow', 'adx', 'mfi']

        print(f"\n지표별 평균값 비교:")
        print(f"{'':<20} {'수익 케이스':<15} {'손실 케이스':<15} {'차이':<15}")
        print(f"{'-'*70}")

        for feature in features:
            if feature not in df.columns:
                continue

            profit_mean = profitable_df[feature].mean()
            loss_mean = losing_df[feature].mean()
            diff = profit_mean - loss_mean

            print(f"{feature:<20} {profit_mean:<15.2f} {loss_mean:<15.2f} {diff:<15.2f}")

        # CSV 저장 (수익 케이스만)
        output_file = f'analysis/bruteforce/bruteforce_{timeframe}_{best_days}_profitable.csv'
        profitable_df.to_csv(output_file, index=False)
        print(f"\n수익 케이스 저장: {output_file}")
        print(f"  - 총 {len(profitable_df):,}개 케이스")

        # 전체 통계 저장
        self.results[timeframe] = {
            'stats': stats,
            'best_hold_period': best_days,
            'total_candles': len(df),
            'profitable_count': len(profitable_df),
            'losing_count': len(losing_df)
        }

    def run_full_analysis(self):
        """전체 타임프레임 브루트포스 분석"""
        print(f"{'='*70}")
        print(f"Phase 0: 브루트포스 전수 매매 기회 탐색")
        print(f"{'='*70}")
        print(f"분석 기간: 2020-01-01 ~ 2024-12-31")
        print(f"타임프레임: {', '.join(self.timeframes)}")
        print(f"보유 기간: {', '.join([f'{d}일' for d in self.hold_periods])}")
        print(f"{'='*70}\n")

        # 결과 디렉토리 생성
        import os
        os.makedirs('analysis/bruteforce', exist_ok=True)

        start_time = datetime.now()

        # 타임프레임별 분석
        for tf in self.timeframes:
            self.analyze_timeframe(tf)

        end_time = datetime.now()
        elapsed = end_time - start_time

        # 최종 요약
        print(f"\n{'='*70}")
        print(f"브루트포스 분석 완료!")
        print(f"{'='*70}")
        print(f"소요 시간: {elapsed}")
        print(f"\n타임프레임별 최적 보유 기간:")
        for tf, result in self.results.items():
            best_period = result['best_hold_period']
            sharpe = result['stats'][best_period]['sharpe']
            win_rate = result['stats'][best_period]['win_rate']
            print(f"  {tf:<10}: {best_period} (Sharpe {sharpe:.2f}, 승률 {win_rate:.2%})")

        # JSON 저장
        with open('analysis/bruteforce/bruteforce_summary.json', 'w') as f:
            # numpy types 변환
            def convert(obj):
                if isinstance(obj, np.integer):
                    return int(obj)
                elif isinstance(obj, np.floating):
                    return float(obj)
                elif isinstance(obj, np.ndarray):
                    return obj.tolist()
                return obj

            json.dump(self.results, f, indent=2, default=convert)

        print(f"\n요약 저장: analysis/bruteforce/bruteforce_summary.json")
        print(f"{'='*70}\n")


if __name__ == '__main__':
    analyzer = BruteforceAnalyzer()
    analyzer.run_full_analysis()
