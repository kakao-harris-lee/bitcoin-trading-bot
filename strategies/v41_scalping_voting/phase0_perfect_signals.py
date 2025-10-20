#!/usr/bin/env python3
"""
Phase 0: 완벽한 매매 시그널 생성 ("정답지")

목표:
- 모든 타임프레임 (minute5, minute15, minute60, minute240, day)
- 모든 기간 (2020-2024, 연도별)
- 각 캔들마다 최적 보유 기간 자동 선택
- 100% 최대 수익 시그널 추출

용도:
- 이 데이터는 "완벽한 정답"
- v42 전략은 이 정답을 재현하는 것이 목표
- 재현율 = (전략 수익 / 완벽한 정답 수익) × 100
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


class PerfectSignalGenerator:
    """완벽한 매매 시그널 생성기"""

    def __init__(self, config_path='config.json', db_path='../../upbit_bitcoin.db'):
        with open(config_path) as f:
            self.config = json.load(f)

        self.db_path = db_path

        # 모든 타임프레임
        self.timeframes = ['minute5', 'minute15', 'minute60', 'minute240', 'day']

        # 모든 보유 기간 (일 단위)
        self.hold_periods = [1, 3, 5, 7, 14, 30]

        # 연도별 분석
        self.years = ['2020', '2021', '2022', '2023', '2024']

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
        df['bb_position'] = (df['close'] - df['bb_lower']) / (df['bb_upper'] - df['bb_lower'])

        # ADX
        df['adx'] = talib.ADX(df['high'], df['low'], df['close'],
                              timeperiod=ind_config.get('adx_period', 14))

        # MFI
        df['mfi'] = talib.MFI(df['high'], df['low'], df['close'], df['volume'],
                               timeperiod=ind_config.get('mfi_period', 14))

        # ATR
        if 'atr_period' in ind_config:
            df['atr'] = talib.ATR(df['high'], df['low'], df['close'],
                                   timeperiod=ind_config['atr_period'])
            df['atr_pct'] = df['atr'] / df['close']

        # NaN 제거
        df = df.dropna()

        return df

    def calculate_all_future_returns(self, df, hold_periods):
        """모든 보유 기간의 미래 수익률 계산"""
        print(f"  미래 수익률 계산 중 (보유 기간: {hold_periods}일)...")

        for days in hold_periods:
            # 미래 종가
            df[f'future_close_{days}d'] = df['close'].shift(-days)

            # 수익률
            df[f'return_{days}d'] = (df[f'future_close_{days}d'] - df['close']) / df['close']

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

    def select_best_holding_period(self, df, hold_periods):
        """각 캔들마다 최고 수익 보유 기간 선택"""
        print(f"  최적 보유 기간 선택 중...")

        best_periods = []
        best_returns = []
        best_max_dds = []

        for i in tqdm(range(len(df)), desc="  최적 기간 선택"):
            returns = {}
            max_dds = {}

            for days in hold_periods:
                ret = df.iloc[i][f'return_{days}d']
                mdd = df.iloc[i][f'max_dd_{days}d']

                if pd.notna(ret):
                    returns[days] = ret
                    max_dds[days] = mdd

            if len(returns) == 0:
                best_periods.append(np.nan)
                best_returns.append(np.nan)
                best_max_dds.append(np.nan)
                continue

            # 최대 수익 기간 선택
            best_day = max(returns, key=returns.get)
            best_periods.append(best_day)
            best_returns.append(returns[best_day])
            best_max_dds.append(max_dds[best_day])

        df['best_hold_days'] = best_periods
        df['best_return'] = best_returns
        df['best_max_dd'] = best_max_dds

        return df

    def extract_perfect_signals(self, df, min_return=0.01):
        """완벽한 시그널 추출 (최소 수익률 이상)"""
        print(f"  완벽한 시그널 추출 (최소 수익률: {min_return:.2%})...")

        # 수익 조건
        perfect_df = df[df['best_return'] > min_return].copy()

        print(f"  ✅ {len(perfect_df):,}개 완벽한 시그널 추출")

        return perfect_df

    def analyze_timeframe_year(self, timeframe, year):
        """타임프레임 × 연도별 분석"""
        print(f"\n{'='*70}")
        print(f"[{timeframe}] {year}년 완벽한 시그널 생성")
        print(f"{'='*70}\n")

        # 데이터 로드
        start_date = f"{year}-01-01"
        end_date = f"{year}-12-31"

        print(f"[{timeframe}] 데이터 로드 중 ({start_date} ~ {end_date})...")

        with DataLoader(self.db_path) as loader:
            df = loader.load_timeframe(timeframe, start_date=start_date, end_date=end_date)

        if df is None or len(df) == 0:
            print(f"  ❌ {timeframe} {year}년 데이터 없음")
            return None

        print(f"[{timeframe}] 로드 완료: {len(df):,} 캔들")

        # 지표 계산
        print(f"[{timeframe}] 지표 계산 중...")
        df = self.add_indicators(df, timeframe)
        print(f"[{timeframe}] 지표 계산 완료: {len(df):,} 캔들")

        # 미래 수익률 계산 (모든 보유 기간)
        df = self.calculate_all_future_returns(df, self.hold_periods)

        # NaN 제거 (미래 데이터가 없는 마지막 캔들들)
        df = df.dropna(subset=['best_return'] if 'best_return' in df.columns else [f'return_{self.hold_periods[0]}d'])

        # 최적 보유 기간 선택
        df = self.select_best_holding_period(df, self.hold_periods)

        # 완벽한 시그널 추출
        perfect_df = self.extract_perfect_signals(df, min_return=0.01)

        if len(perfect_df) == 0:
            print(f"  ⚠️ {timeframe} {year}년: 완벽한 시그널 0개")
            return None

        # 통계
        print(f"\n[{timeframe}] {year}년 통계:")
        print(f"{'='*70}")
        print(f"  총 캔들: {len(df):,}개")
        print(f"  완벽한 시그널: {len(perfect_df):,}개 ({len(perfect_df)/len(df):.2%})")
        print(f"  평균 수익률: {perfect_df['best_return'].mean():.2%}")
        print(f"  중앙 수익률: {perfect_df['best_return'].median():.2%}")
        print(f"  최대 수익률: {perfect_df['best_return'].max():.2%}")
        print(f"  평균 보유 기간: {perfect_df['best_hold_days'].mean():.1f}일")
        print(f"  평균 최대 낙폭: {perfect_df['best_max_dd'].mean():.2%}")

        # 보유 기간 분포
        period_counts = perfect_df['best_hold_days'].value_counts().sort_index()
        print(f"\n  보유 기간 분포:")
        for days, count in period_counts.items():
            pct = count / len(perfect_df) * 100
            print(f"    {int(days):2d}일: {count:5,}개 ({pct:5.2f}%)")

        # CSV 저장
        import os
        os.makedirs('analysis/perfect_signals', exist_ok=True)

        output_file = f'analysis/perfect_signals/{timeframe}_{year}_perfect.csv'
        perfect_df.to_csv(output_file, index=False)
        print(f"\n  💾 저장: {output_file}")

        # 결과 저장
        result = {
            'timeframe': timeframe,
            'year': year,
            'total_candles': len(df),
            'perfect_signals': len(perfect_df),
            'signal_rate': len(perfect_df) / len(df),
            'avg_return': perfect_df['best_return'].mean(),
            'median_return': perfect_df['best_return'].median(),
            'max_return': perfect_df['best_return'].max(),
            'avg_hold_days': perfect_df['best_hold_days'].mean(),
            'avg_max_dd': perfect_df['best_max_dd'].mean(),
            'period_distribution': period_counts.to_dict(),
            'output_file': output_file
        }

        return result

    def run_full_analysis(self):
        """전체 타임프레임 × 연도 분석"""
        print(f"{'='*70}")
        print(f"Phase 0: 완벽한 매매 시그널 생성")
        print(f"{'='*70}")
        print(f"타임프레임: {', '.join(self.timeframes)}")
        print(f"연도: {', '.join(self.years)}")
        print(f"보유 기간: {', '.join([f'{d}일' for d in self.hold_periods])}")
        print(f"{'='*70}\n")

        start_time = datetime.now()

        # 타임프레임 × 연도별 분석
        for timeframe in self.timeframes:
            for year in self.years:
                result = self.analyze_timeframe_year(timeframe, year)

                if result:
                    if timeframe not in self.results:
                        self.results[timeframe] = {}
                    self.results[timeframe][year] = result

        end_time = datetime.now()
        elapsed = end_time - start_time

        # 최종 요약
        self.generate_summary()

        print(f"\n{'='*70}")
        print(f"완벽한 시그널 생성 완료!")
        print(f"{'='*70}")
        print(f"소요 시간: {elapsed}")
        print(f"총 시그널 파일: {sum(len(years) for years in self.results.values())}개")
        print(f"{'='*70}\n")

    def generate_summary(self):
        """통합 요약 생성"""
        print(f"\n{'='*70}")
        print(f"통합 요약 생성 중...")
        print(f"{'='*70}\n")

        summary = {}
        total_signals = 0
        total_perfect_return = 0

        for timeframe, years in self.results.items():
            summary[timeframe] = {}

            for year, result in years.items():
                summary[timeframe][year] = {
                    'signals': result['perfect_signals'],
                    'max_return_pct': round(result['max_return'] * 100, 2),
                    'avg_return_pct': round(result['avg_return'] * 100, 2),
                    'avg_hold_days': round(result['avg_hold_days'], 1)
                }

                total_signals += result['perfect_signals']
                # 누적 수익 (복리 아닌 단순 합계)
                total_perfect_return += result['avg_return'] * result['perfect_signals']

        # 전체 평균 수익률
        avg_perfect_return = (total_perfect_return / total_signals * 100) if total_signals > 0 else 0

        summary['total_perfect_signals'] = total_signals
        summary['avg_perfect_return_pct'] = round(avg_perfect_return, 2)

        # 최고 성과 타임프레임/연도
        best_tf = max(self.results.keys(),
                      key=lambda tf: sum(r['perfect_signals'] for r in self.results[tf].values()))

        best_year_data = []
        for tf, years in self.results.items():
            for year, result in years.items():
                best_year_data.append((year, result['perfect_signals']))

        best_year = max(best_year_data, key=lambda x: x[1])[0] if best_year_data else 'N/A'

        summary['best_timeframe'] = best_tf
        summary['best_year'] = best_year

        # JSON 저장
        with open('analysis/perfect_signals/summary_all_timeframes.json', 'w') as f:
            json.dump(summary, f, indent=2)

        print(f"📊 통합 요약:")
        print(f"  총 완벽한 시그널: {total_signals:,}개")
        print(f"  평균 수익률: {avg_perfect_return:.2f}%")
        print(f"  최고 타임프레임: {best_tf}")
        print(f"  최고 연도: {best_year}")
        print(f"\n  💾 저장: analysis/perfect_signals/summary_all_timeframes.json")


if __name__ == '__main__':
    generator = PerfectSignalGenerator()
    generator.run_full_analysis()
