#!/usr/bin/env python3
"""
Phase 1: 오버플로우 실체 분석
- A-Tier 고빈도 거래의 실제 수익 패턴 분석
- 거래별 수익률 분포, 승률, Profit Factor 계산
- 복리 대신 실현 가능한 수익률 산출
"""

import sqlite3
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import json
from pathlib import Path
from collections import defaultdict

# 설정
DB_PATH = 'upbit_bitcoin.db'
TIER_DATA_DIR = Path('strategies/v41_scalping_voting/analysis/tier_backtest')
OUTPUT_DIR = Path('strategies/v41_scalping_voting/validation/overflow_analysis')
OUTPUT_DIR.mkdir(exist_ok=True)

# 단타 파라미터
TAKE_PROFIT = 0.05  # +5%
STOP_LOSS = -0.02   # -2%
MAX_HOLD_HOURS = 72  # 3일
FEE_RATE = 0.0005
SLIPPAGE = 0.0002


class OverflowAnalyzer:
    """오버플로우 실체 분석기"""

    def __init__(self, timeframe, year, tier='A'):
        self.timeframe = timeframe
        self.year = year
        self.tier = tier
        self.trades = []
        self.signals = []

    def load_signals(self):
        """S/A-Tier 시그널 로드"""
        tier_file = TIER_DATA_DIR / f'{self.timeframe}_SA_tier.csv'
        if not tier_file.exists():
            print(f"⚠️ {tier_file} 파일이 없습니다.")
            return pd.DataFrame()

        df = pd.read_csv(tier_file)
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df = df[df['timestamp'].dt.year == self.year]
        df = df[df['tier'] == self.tier]

        return df.sort_values('timestamp').reset_index(drop=True)

    def load_price_data(self):
        """가격 데이터 로드"""
        table_name = f'bitcoin_{self.timeframe}'
        conn = sqlite3.connect(DB_PATH)

        query = f"""
        SELECT
            timestamp,
            opening_price as open,
            high_price as high,
            low_price as low,
            trade_price as close
        FROM {table_name}
        WHERE strftime('%Y', timestamp) = '{self.year}'
        ORDER BY timestamp
        """

        df = pd.read_sql_query(query, conn)
        conn.close()

        df['timestamp'] = pd.to_datetime(df['timestamp'])
        return df

    def check_exit(self, entry_price, current_row):
        """청산 조건 체크 (단순화)"""
        current_price = current_row['close']
        pnl = (current_price - entry_price) / entry_price

        if pnl >= TAKE_PROFIT:
            return True, 'take_profit', pnl
        if pnl <= STOP_LOSS:
            return True, 'stop_loss', pnl

        return False, None, pnl

    def simulate_trades(self):
        """거래 시뮬레이션 (복리 없이 개별 거래만)"""
        signals = self.load_signals()
        price_df = self.load_price_data()

        if len(signals) == 0:
            print(f"⚠️ {self.timeframe} {self.year} {self.tier}-Tier: 시그널 없음")
            return []

        print(f"\n{self.timeframe} {self.year} {self.tier}-Tier: {len(signals)} signals")
        self.signals = signals

        position = None
        trades = []

        for idx, signal in signals.iterrows():
            signal_time = signal['timestamp']

            # 기존 포지션 청산 체크
            if position:
                entry_time = position['entry_time']
                entry_price = position['entry_price']

                future_prices = price_df[price_df['timestamp'] > entry_time]
                for _, row in future_prices.iterrows():
                    hours_held = (row['timestamp'] - entry_time).total_seconds() / 3600

                    if hours_held >= MAX_HOLD_HOURS:
                        # 타임아웃
                        pnl = (row['close'] - entry_price) / entry_price - (FEE_RATE + SLIPPAGE) * 2
                        trades.append({
                            'entry_time': entry_time,
                            'entry_price': entry_price,
                            'exit_time': row['timestamp'],
                            'exit_price': row['close'],
                            'pnl': pnl,
                            'reason': 'timeout',
                            'hold_hours': hours_held
                        })
                        position = None
                        break

                    should_exit, reason, raw_pnl = self.check_exit(entry_price, row)

                    if should_exit:
                        pnl = raw_pnl - (FEE_RATE + SLIPPAGE) * 2
                        trades.append({
                            'entry_time': entry_time,
                            'entry_price': entry_price,
                            'exit_time': row['timestamp'],
                            'exit_price': row['close'],
                            'pnl': pnl,
                            'reason': reason,
                            'hold_hours': hours_held
                        })
                        position = None
                        break

            # 신규 진입
            if not position:
                signal_row = price_df[price_df['timestamp'] == signal_time]
                if len(signal_row) > 0:
                    entry_price = signal_row.iloc[0]['close'] * (1 + SLIPPAGE)
                    position = {
                        'entry_time': signal_time,
                        'entry_price': entry_price
                    }

        # 마지막 포지션 강제 청산
        if position:
            last_row = price_df.iloc[-1]
            pnl = (last_row['close'] - position['entry_price']) / position['entry_price'] - (FEE_RATE + SLIPPAGE) * 2
            hours_held = (last_row['timestamp'] - position['entry_time']).total_seconds() / 3600
            trades.append({
                'entry_time': position['entry_time'],
                'entry_price': position['entry_price'],
                'exit_time': last_row['timestamp'],
                'exit_price': last_row['close'],
                'pnl': pnl,
                'reason': 'forced_close',
                'hold_hours': hours_held
            })

        self.trades = trades
        return trades

    def analyze_trades(self):
        """거래 상세 분석"""
        if len(self.trades) == 0:
            return None

        df = pd.DataFrame(self.trades)

        wins = df[df['pnl'] > 0]
        losses = df[df['pnl'] <= 0]

        total_pnl = df['pnl'].sum()
        avg_pnl = df['pnl'].mean()

        win_count = len(wins)
        loss_count = len(losses)
        win_rate = win_count / len(df) if len(df) > 0 else 0

        avg_win = wins['pnl'].mean() if len(wins) > 0 else 0
        avg_loss = losses['pnl'].mean() if len(losses) > 0 else 0

        total_win = wins['pnl'].sum() if len(wins) > 0 else 0
        total_loss = abs(losses['pnl'].sum()) if len(losses) > 0 else 0
        profit_factor = total_win / total_loss if total_loss > 0 else 0

        # 거래 이유별 통계
        reason_stats = df.groupby('reason').agg({
            'pnl': ['count', 'mean', 'sum']
        }).round(4)

        # 수익률 분포
        pnl_percentiles = df['pnl'].quantile([0.1, 0.25, 0.5, 0.75, 0.9]).to_dict()

        # 보유 시간 분석
        avg_hold_hours = df['hold_hours'].mean()

        # 실현 가능 수익률 계산
        simple_sum_return = total_pnl  # 단순 합산

        # 제한 복리 (최대 10배 제한)
        limited_compound = 1.0
        for pnl in df['pnl']:
            limited_compound *= (1 + pnl)
            if limited_compound > 10:
                limited_compound = 10
        limited_compound_return = limited_compound - 1

        analysis = {
            'timeframe': self.timeframe,
            'year': self.year,
            'tier': self.tier,
            'total_signals': len(self.signals),
            'total_trades': len(df),
            'trade_signal_ratio': len(df) / len(self.signals) if len(self.signals) > 0 else 0,

            # 수익률
            'total_pnl_sum': total_pnl,
            'avg_pnl': avg_pnl,
            'simple_annual_return': total_pnl,  # 복리 없는 단순 수익률
            'limited_compound_return': limited_compound_return,  # 10배 제한 복리

            # 승률
            'win_count': int(win_count),
            'loss_count': int(loss_count),
            'win_rate': win_rate,

            # 수익/손실
            'avg_win': avg_win,
            'avg_loss': avg_loss,
            'total_win': total_win,
            'total_loss': total_loss,
            'profit_factor': profit_factor,

            # 분포
            'pnl_p10': pnl_percentiles[0.1],
            'pnl_p25': pnl_percentiles[0.25],
            'pnl_median': pnl_percentiles[0.5],
            'pnl_p75': pnl_percentiles[0.75],
            'pnl_p90': pnl_percentiles[0.9],

            # 보유 시간
            'avg_hold_hours': avg_hold_hours,

            # 이유별 통계 (JSON 직렬화 가능하도록 변환)
            'reason_stats': {str(k): v for k, v in reason_stats.to_dict().items()} if len(reason_stats) > 0 else {}
        }

        return analysis


def main():
    """메인 실행"""
    print("\n" + "=" * 80)
    print("Phase 1: 오버플로우 실체 분석")
    print("=" * 80)

    # 분석 대상 (오버플로우 발생 케이스)
    overflow_cases = [
        ('minute60', 2020, 'A'),
        ('minute60', 2021, 'A'),
        ('minute60', 2022, 'A'),
        ('minute60', 2023, 'A'),
        ('minute60', 2024, 'A'),
        ('minute15', 2023, 'S'),
        ('minute15', 2023, 'A'),
        ('minute15', 2024, 'S'),
        ('minute15', 2024, 'A'),
    ]

    # 비교용 정상 케이스
    normal_cases = [
        ('day', 2020, 'S'),
        ('day', 2024, 'S'),
        ('minute60', 2020, 'S'),
        ('minute60', 2024, 'S'),
    ]

    all_results = []

    print("\n🔥 오버플로우 케이스 분석:")
    for timeframe, year, tier in overflow_cases:
        analyzer = OverflowAnalyzer(timeframe, year, tier)
        trades = analyzer.simulate_trades()

        if trades:
            analysis = analyzer.analyze_trades()
            all_results.append(analysis)

            print(f"\n{timeframe} {year} {tier}-Tier:")
            print(f"  총 거래: {analysis['total_trades']}회")
            print(f"  승률: {analysis['win_rate']:.1%}")
            print(f"  평균 수익: {analysis['avg_pnl']:.2%}")
            print(f"  단순 합산 수익률: {analysis['simple_annual_return']:.2%}")
            print(f"  제한 복리 수익률: {analysis['limited_compound_return']:.2%}")
            print(f"  Profit Factor: {analysis['profit_factor']:.2f}")

    print("\n\n✅ 정상 케이스 비교:")
    for timeframe, year, tier in normal_cases:
        analyzer = OverflowAnalyzer(timeframe, year, tier)
        trades = analyzer.simulate_trades()

        if trades:
            analysis = analyzer.analyze_trades()
            all_results.append(analysis)

            print(f"\n{timeframe} {year} {tier}-Tier:")
            print(f"  총 거래: {analysis['total_trades']}회")
            print(f"  승률: {analysis['win_rate']:.1%}")
            print(f"  평균 수익: {analysis['avg_pnl']:.2%}")
            print(f"  단순 합산 수익률: {analysis['simple_annual_return']:.2%}")
            print(f"  Profit Factor: {analysis['profit_factor']:.2f}")

    # 결과 저장
    output_file = OUTPUT_DIR / 'overflow_reality_analysis.json'
    with open(output_file, 'w') as f:
        json.dump(all_results, f, indent=2, default=str)

    print(f"\n\n결과 저장: {output_file}")

    # 요약 통계
    print("\n" + "=" * 80)
    print("📊 요약 통계")
    print("=" * 80)

    df_results = pd.DataFrame(all_results)

    print("\n오버플로우 그룹 (A-Tier):")
    overflow_df = df_results[df_results['tier'] == 'A']
    if len(overflow_df) > 0:
        print(f"  평균 거래수: {overflow_df['total_trades'].mean():.0f}회/년")
        print(f"  평균 승률: {overflow_df['win_rate'].mean():.1%}")
        print(f"  평균 Profit Factor: {overflow_df['profit_factor'].mean():.2f}")
        print(f"  평균 단순 수익률: {overflow_df['simple_annual_return'].mean():.2%}")

    print("\n정상 그룹 (S-Tier):")
    normal_df = df_results[df_results['tier'] == 'S']
    if len(normal_df) > 0:
        print(f"  평균 거래수: {normal_df['total_trades'].mean():.0f}회/년")
        print(f"  평균 승률: {normal_df['win_rate'].mean():.1%}")
        print(f"  평균 Profit Factor: {normal_df['profit_factor'].mean():.2f}")
        print(f"  평균 단순 수익률: {normal_df['simple_annual_return'].mean():.2%}")

    print("\n✅ Phase 1 완료!")


if __name__ == '__main__':
    main()
