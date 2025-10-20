#!/usr/bin/env python3
"""
Phase 3-2 완전판: 모든 타임프레임 2025년 백테스팅
- day, minute15, minute60, minute240 전체 검증
- S-Tier, A-Tier, S+A 조합 모두 테스트
"""

import sqlite3
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import json
from pathlib import Path

# 설정
DB_PATH = 'upbit_bitcoin.db'
TIER_DATA_DIR = Path('strategies/v41_scalping_voting/analysis/tier_backtest')
OUTPUT_DIR = Path('strategies/v41_scalping_voting/validation/results_2025')
OUTPUT_DIR.mkdir(exist_ok=True)

FEE_RATE = 0.0005
SLIPPAGE = 0.0002

# Tier별 전략 파라미터
TIER_CONFIGS = {
    'S': {
        'position_size': 1.0,
        'take_profit': 0.07,
        'stop_loss': -0.02,
        'trailing_stop': 0.015,
        'max_hold_hours': 72,
        'min_interval_hours': 0,
    },
    'A': {
        'position_size': 0.4,
        'take_profit': 0.03,
        'stop_loss': -0.01,
        'trailing_stop': 0,
        'max_hold_hours': 24,
        'min_interval_hours': 4,
    },
}


class BacktestAllTimeframes:
    """전체 타임프레임 백테스팅"""

    def __init__(self, timeframe, year, tiers=['S']):
        self.timeframe = timeframe
        self.year = year
        self.tiers = tiers
        self.capital = 10_000_000
        self.initial_capital = 10_000_000
        self.position = None
        self.trades = []
        self.last_exit_time = None

    def load_tier_data(self):
        """Tier 데이터 로드"""
        if self.year == 2025:
            tier_file = TIER_DATA_DIR / f'{self.timeframe}_SA_tier_2025.csv'
        else:
            tier_file = TIER_DATA_DIR / f'{self.timeframe}_tier_classified.csv'

        if not tier_file.exists():
            return pd.DataFrame()

        df = pd.read_csv(tier_file)
        df['timestamp'] = pd.to_datetime(df['timestamp'])

        if self.year != 2025:
            df = df[df['timestamp'].dt.year == self.year]

        if 'tier' in df.columns:
            df = df[df['tier'].isin(self.tiers)]

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

    def can_enter(self, signal_time, tier):
        """진입 가능 여부"""
        if self.last_exit_time is None:
            return True

        config = TIER_CONFIGS.get(tier, TIER_CONFIGS['S'])
        min_interval = timedelta(hours=config['min_interval_hours'])
        return (signal_time - self.last_exit_time) >= min_interval

    def check_exit(self, entry_price, high_price, current_price, hours_held, tier, peak_price):
        """청산 조건"""
        config = TIER_CONFIGS.get(tier, TIER_CONFIGS['S'])
        pnl = (current_price - entry_price) / entry_price

        if pnl >= config['take_profit']:
            return True, 'take_profit', pnl
        if pnl <= config['stop_loss']:
            return True, 'stop_loss', pnl

        if config['trailing_stop'] > 0:
            if (peak_price - current_price) / entry_price >= config['trailing_stop']:
                return True, 'trailing_stop', pnl

        if hours_held >= config['max_hold_hours']:
            return True, 'timeout', pnl

        return False, None, pnl

    def run(self):
        """백테스팅 실행"""
        signals = self.load_tier_data()
        price_df = self.load_price_data()

        if len(signals) == 0 or len(price_df) == 0:
            return self.get_empty_result()

        for idx, signal in signals.iterrows():
            signal_time = signal['timestamp']
            signal_tier = signal.get('tier', 'S')

            # 포지션 청산
            if self.position:
                entry_time = self.position['entry_time']
                entry_price = self.position['entry_price']
                tier = self.position['tier']
                peak_price = self.position['peak_price']

                future_prices = price_df[price_df['timestamp'] > entry_time]
                for _, row in future_prices.iterrows():
                    hours_held = (row['timestamp'] - entry_time).total_seconds() / 3600

                    if row['high'] > peak_price:
                        peak_price = row['high']
                        self.position['peak_price'] = peak_price

                    should_exit, reason, pnl = self.check_exit(
                        entry_price, row['high'], row['close'], hours_held, tier, peak_price
                    )

                    if should_exit:
                        trade_pnl = pnl - (FEE_RATE + SLIPPAGE) * 2
                        position_size = TIER_CONFIGS.get(tier, TIER_CONFIGS['S'])['position_size']
                        capital_change = self.capital * position_size * trade_pnl
                        self.capital += capital_change

                        self.trades.append({
                            'entry_time': entry_time,
                            'exit_time': row['timestamp'],
                            'pnl': trade_pnl,
                            'capital': self.capital,
                            'reason': reason,
                            'hold_hours': hours_held,
                            'tier': tier
                        })

                        self.last_exit_time = row['timestamp']
                        self.position = None
                        break

            # 신규 진입
            if not self.position and self.can_enter(signal_time, signal_tier):
                signal_row = price_df[price_df['timestamp'] == signal_time]
                if len(signal_row) > 0:
                    entry_price = signal_row.iloc[0]['close'] * (1 + SLIPPAGE)
                    peak_price = signal_row.iloc[0]['high']

                    self.position = {
                        'entry_time': signal_time,
                        'entry_price': entry_price,
                        'peak_price': peak_price,
                        'tier': signal_tier
                    }

        # 마지막 포지션 강제 청산
        if self.position:
            last_row = price_df.iloc[-1]
            tier = self.position['tier']
            pnl = (last_row['close'] - self.position['entry_price']) / self.position['entry_price'] - (FEE_RATE + SLIPPAGE) * 2

            position_size = TIER_CONFIGS.get(tier, TIER_CONFIGS['S'])['position_size']
            capital_change = self.capital * position_size * pnl
            self.capital += capital_change

            hours_held = (last_row['timestamp'] - self.position['entry_time']).total_seconds() / 3600

            self.trades.append({
                'entry_time': self.position['entry_time'],
                'exit_time': last_row['timestamp'],
                'pnl': pnl,
                'capital': self.capital,
                'reason': 'forced_close',
                'hold_hours': hours_held,
                'tier': tier
            })

            self.position = None

        # Buy & Hold
        first_price = price_df.iloc[0]['close']
        last_price = price_df.iloc[-1]['close']
        buy_hold_return = (last_price - first_price) / first_price

        return self.get_results(buy_hold_return)

    def get_empty_result(self):
        """빈 결과"""
        return {
            'timeframe': self.timeframe,
            'year': self.year,
            'tiers': '+'.join(self.tiers),
            'total_return': 0,
            'total_trades': 0,
            'win_rate': 0,
        }

    def get_results(self, buy_hold_return):
        """결과 정리"""
        if len(self.trades) == 0:
            result = self.get_empty_result()
            result['buy_hold_return'] = buy_hold_return
            return result

        df = pd.DataFrame(self.trades)
        wins = df[df['pnl'] > 0]
        total_return = (self.capital - self.initial_capital) / self.initial_capital
        win_rate = len(wins) / len(df) if len(df) > 0 else 0

        returns = df['pnl'].values
        sharpe = returns.mean() / returns.std() if returns.std() > 0 else 0

        capital_series = df['capital'].values
        running_max = np.maximum.accumulate(capital_series)
        drawdowns = (capital_series - running_max) / running_max
        max_dd = drawdowns.min() if len(drawdowns) > 0 else 0

        return {
            'timeframe': self.timeframe,
            'year': self.year,
            'tiers': '+'.join(self.tiers),
            'total_return': total_return,
            'final_capital': self.capital,
            'total_trades': len(df),
            'win_rate': win_rate,
            'avg_pnl': df['pnl'].mean(),
            'sharpe_ratio': sharpe,
            'max_drawdown': max_dd,
            'buy_hold_return': buy_hold_return,
            'outperformance': total_return - buy_hold_return,
            'avg_hold_hours': df['hold_hours'].mean(),
        }


def main():
    """메인 실행"""
    print("\n" + "=" * 80)
    print("Phase 3-2 완전판: 모든 타임프레임 2025년 백테스팅")
    print("=" * 80)

    # 모든 타임프레임 × 모든 Tier 조합
    timeframes = ['day', 'minute15', 'minute60', 'minute240']
    years = [2020, 2021, 2022, 2023, 2024, 2025]
    tier_combos = [
        (['S'], 'S'),
        (['A'], 'A'),
        (['S', 'A'], 'S+A')
    ]

    test_cases = []
    for tf in timeframes:
        for year in years:
            for tiers, tier_name in tier_combos:
                test_cases.append((tf, year, tiers, f"{year} {tf:8s} {tier_name}"))

    all_results = []

    for timeframe, year, tiers, desc in test_cases:
        bt = BacktestAllTimeframes(timeframe, year, tiers)
        result = bt.run()
        all_results.append(result)

        if result['total_trades'] > 0:
            print(f"  {desc:25s}: {result['total_return']:7.1%} "
                  f"({result['total_trades']:4.0f}회, 승률 {result['win_rate']:5.1%}, "
                  f"Sharpe {result['sharpe_ratio']:5.2f})")

    # 결과 저장
    output_file = OUTPUT_DIR / 'all_timeframes_2025_results.json'
    with open(output_file, 'w') as f:
        json.dump(all_results, f, indent=2, default=str)

    # 요약 통계
    df_results = pd.DataFrame(all_results)
    df_results = df_results[df_results['total_trades'] > 0]

    print("\n" + "=" * 80)
    print("📊 2025년 Out-of-Sample 타임프레임별 비교")
    print("=" * 80)

    df_2025 = df_results[df_results['year'] == 2025]

    if len(df_2025) > 0:
        # S-Tier만
        print("\n🥇 S-Tier 전용:")
        s_only = df_2025[df_2025['tiers'] == 'S'].sort_values('total_return', ascending=False)
        for _, row in s_only.iterrows():
            print(f"  {row['timeframe']:10s}: {row['total_return']:7.1%} "
                  f"({row['total_trades']:4.0f}회, 승률 {row['win_rate']:5.1%}, "
                  f"Sharpe {row['sharpe_ratio']:5.2f})")

        # S+A 조합
        print("\n🥈 S+A 조합:")
        sa_combo = df_2025[df_2025['tiers'] == 'S+A'].sort_values('total_return', ascending=False)
        for _, row in sa_combo.iterrows():
            print(f"  {row['timeframe']:10s}: {row['total_return']:7.1%} "
                  f"({row['total_trades']:4.0f}회, 승률 {row['win_rate']:5.1%}, "
                  f"Sharpe {row['sharpe_ratio']:5.2f})")

    # 6년 평균
    print("\n" + "=" * 80)
    print("📊 6년 평균 성과 (2020-2025)")
    print("=" * 80)

    for tf in timeframes:
        tf_data = df_results[df_results['timeframe'] == tf]
        if len(tf_data) > 0:
            print(f"\n{tf.upper()}:")
            for tier_name in ['S', 'S+A']:
                tier_data = tf_data[tf_data['tiers'] == tier_name]
                if len(tier_data) > 0:
                    avg_return = tier_data['total_return'].mean()
                    avg_trades = tier_data['total_trades'].mean()
                    avg_winrate = tier_data['win_rate'].mean()
                    avg_sharpe = tier_data['sharpe_ratio'].mean()

                    print(f"  {tier_name:5s}: {avg_return:7.1%} "
                          f"({avg_trades:5.0f}회/년, 승률 {avg_winrate:5.1%}, "
                          f"Sharpe {avg_sharpe:5.2f})")

    print(f"\n\n결과 저장: {output_file}")
    print("\n✅ 모든 타임프레임 검증 완료!")


if __name__ == '__main__':
    main()
