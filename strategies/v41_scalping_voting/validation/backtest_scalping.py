#!/usr/bin/env python3
"""
v41 S/A-Tier 단타 전략 백테스팅
- 모든 타임프레임 (day, minute60, minute15, minute240)
- 모든 연도 (2020-2024 학습, 2025 검증)
- 단타 설정: TP +5%, SL -2%, 최대 보유 72시간
"""

import sqlite3
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import json
from pathlib import Path
import sys

# 설정
DB_PATH = 'upbit_bitcoin.db'
TIER_DATA_DIR = Path('strategies/v41_scalping_voting/analysis/tier_backtest')
OUTPUT_DIR = Path('strategies/v41_scalping_voting/validation')

# 단타 파라미터
TAKE_PROFIT = 0.05  # +5%
STOP_LOSS = -0.02   # -2%
MAX_HOLD_HOURS = 72  # 3일
INITIAL_CAPITAL = 10_000_000
POSITION_SIZE = 1.0  # 100%
FEE_RATE = 0.0005
SLIPPAGE = 0.0002


class ScalpingBacktest:
    def __init__(self, timeframe, year, tier='S'):
        self.timeframe = timeframe
        self.year = year
        self.tier = tier
        self.capital = INITIAL_CAPITAL
        self.position = None
        self.trades = []

    def load_signals(self):
        """S/A-Tier 시그널 로드"""
        tier_file = TIER_DATA_DIR / f'{self.timeframe}_SA_tier.csv'
        df = pd.read_csv(tier_file)

        # 연도 필터링
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df = df[df['timestamp'].dt.year == self.year]

        # Tier 필터링
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

    def get_price_at(self, timestamp, price_df):
        """특정 시간의 가격 조회"""
        row = price_df[price_df['timestamp'] == timestamp]
        if len(row) == 0:
            return None
        return row.iloc[0]

    def check_exit(self, entry_price, entry_time, current_row, hours_held):
        """청산 조건 체크"""
        current_price = current_row['close']
        pnl = (current_price - entry_price) / entry_price

        # 익절
        if pnl >= TAKE_PROFIT:
            return True, 'take_profit', pnl

        # 손절
        if pnl <= STOP_LOSS:
            return True, 'stop_loss', pnl

        # 시간 초과
        if hours_held >= MAX_HOLD_HOURS:
            return True, 'timeout', pnl

        return False, None, pnl

    def run(self):
        """백테스팅 실행"""
        signals = self.load_signals()
        price_df = self.load_price_data()

        if len(signals) == 0:
            return self.get_results([], 0, 0)

        print(f"\n{self.timeframe} {self.year} {self.tier}-Tier: {len(signals)} signals")

        for idx, signal in signals.iterrows():
            signal_time = signal['timestamp']

            # 포지션이 있으면 청산 체크
            if self.position:
                entry_time = self.position['entry_time']
                entry_price = self.position['entry_price']

                # 청산 체크
                future_prices = price_df[price_df['timestamp'] > entry_time]
                for _, row in future_prices.iterrows():
                    hours_held = (row['timestamp'] - entry_time).total_seconds() / 3600

                    should_exit, reason, pnl = self.check_exit(
                        entry_price, entry_time, row, hours_held
                    )

                    if should_exit:
                        # 청산
                        exit_price = row['close']
                        trade_pnl = pnl - (FEE_RATE + SLIPPAGE) * 2  # 진입 + 청산 비용

                        self.capital *= (1 + trade_pnl)

                        self.trades.append({
                            'entry_time': entry_time,
                            'entry_price': entry_price,
                            'exit_time': row['timestamp'],
                            'exit_price': exit_price,
                            'pnl': trade_pnl,
                            'reason': reason,
                            'hold_hours': hours_held
                        })

                        self.position = None
                        break

            # 신규 진입 (포지션이 없을 때만)
            if not self.position:
                signal_row = self.get_price_at(signal_time, price_df)
                if signal_row is not None:
                    entry_price = signal_row['close'] * (1 + SLIPPAGE)

                    self.position = {
                        'entry_time': signal_time,
                        'entry_price': entry_price
                    }

        # 마지막 포지션이 남아있으면 강제 청산
        if self.position:
            last_row = price_df.iloc[-1]
            entry_price = self.position['entry_price']
            exit_price = last_row['close']
            pnl = (exit_price - entry_price) / entry_price - (FEE_RATE + SLIPPAGE) * 2

            self.capital *= (1 + pnl)

            hours_held = (last_row['timestamp'] - self.position['entry_time']).total_seconds() / 3600

            self.trades.append({
                'entry_time': self.position['entry_time'],
                'entry_price': entry_price,
                'exit_time': last_row['timestamp'],
                'exit_price': exit_price,
                'pnl': pnl,
                'reason': 'forced_close',
                'hold_hours': hours_held
            })

            self.position = None

        # Buy & Hold 계산
        first_price = price_df.iloc[0]['close']
        last_price = price_df.iloc[-1]['close']
        buy_hold_return = (last_price - first_price) / first_price

        return self.get_results(self.trades, self.capital, buy_hold_return)

    def get_results(self, trades, final_capital, buy_hold_return):
        """결과 정리"""
        if len(trades) == 0:
            return {
                'timeframe': self.timeframe,
                'year': self.year,
                'tier': self.tier,
                'total_trades': 0,
                'total_return': 0,
                'final_capital': INITIAL_CAPITAL,
                'win_rate': 0,
                'avg_profit': 0,
                'avg_win': 0,
                'avg_loss': 0,
                'avg_hold_hours': 0,
                'sharpe_ratio': 0,
                'max_drawdown': 0,
                'buy_hold_return': buy_hold_return,
                'outperformance': 0 - buy_hold_return,
                'profit_factor': 0
            }

        df_trades = pd.DataFrame(trades)

        wins = df_trades[df_trades['pnl'] > 0]
        losses = df_trades[df_trades['pnl'] <= 0]

        total_return = (final_capital - INITIAL_CAPITAL) / INITIAL_CAPITAL

        # Sharpe Ratio
        returns = df_trades['pnl'].values
        sharpe = np.mean(returns) / np.std(returns) if np.std(returns) > 0 else 0

        # Max Drawdown
        cumulative = (1 + df_trades['pnl']).cumprod()
        running_max = cumulative.cummax()
        drawdown = (cumulative - running_max) / running_max
        max_dd = drawdown.min()

        # Profit Factor
        total_profit = wins['pnl'].sum() if len(wins) > 0 else 0
        total_loss = abs(losses['pnl'].sum()) if len(losses) > 0 else 1e-10
        profit_factor = total_profit / total_loss if total_loss > 0 else 0

        return {
            'timeframe': self.timeframe,
            'year': self.year,
            'tier': self.tier,
            'total_trades': len(trades),
            'total_return': total_return,
            'final_capital': final_capital,
            'win_rate': len(wins) / len(trades) if len(trades) > 0 else 0,
            'avg_profit': df_trades['pnl'].mean(),
            'avg_win': wins['pnl'].mean() if len(wins) > 0 else 0,
            'avg_loss': losses['pnl'].mean() if len(losses) > 0 else 0,
            'avg_hold_hours': df_trades['hold_hours'].mean(),
            'sharpe_ratio': sharpe,
            'max_drawdown': max_dd,
            'buy_hold_return': buy_hold_return,
            'outperformance': total_return - buy_hold_return,
            'profit_factor': profit_factor,
            'trades': trades
        }


def run_all_backtests():
    """모든 타임프레임 × 모든 연도 백테스팅"""
    timeframes = ['day', 'minute60', 'minute15']
    years = [2020, 2021, 2022, 2023, 2024, 2025]
    tiers = ['S', 'A']

    all_results = []

    for timeframe in timeframes:
        for year in years:
            for tier in tiers:
                try:
                    bt = ScalpingBacktest(timeframe, year, tier)
                    result = bt.run()
                    all_results.append(result)

                    # 요약 출력
                    print(f"{timeframe} {year} {tier}-Tier: "
                          f"Return={result['total_return']:.2%}, "
                          f"Trades={result['total_trades']}, "
                          f"Win Rate={result['win_rate']:.1%}, "
                          f"Sharpe={result['sharpe_ratio']:.2f}")

                    # 개별 파일 저장
                    output_file = OUTPUT_DIR / f"backtest_{timeframe}_{year}_{tier}tier.json"
                    with open(output_file, 'w') as f:
                        json.dump(result, f, indent=2, default=str)

                except Exception as e:
                    print(f"Error: {timeframe} {year} {tier}-Tier - {e}")

    # 전체 결과 저장
    summary_file = OUTPUT_DIR / "backtest_summary_all.json"
    with open(summary_file, 'w') as f:
        json.dump(all_results, f, indent=2, default=str)

    # Summary 테이블 생성
    create_summary_table(all_results)

    return all_results


def create_summary_table(results):
    """요약 테이블 생성"""
    df = pd.DataFrame([{
        'timeframe': r['timeframe'],
        'year': r['year'],
        'tier': r['tier'],
        'return': r['total_return'],
        'trades': r['total_trades'],
        'win_rate': r['win_rate'],
        'sharpe': r['sharpe_ratio'],
        'mdd': r['max_drawdown'],
        'buy_hold': r['buy_hold_return'],
        'outperf': r['outperformance']
    } for r in results])

    # 타임프레임별 평균
    print("\n\n=== TIMEFRAME SUMMARY (2020-2024 Average) ===")
    tf_summary = df[df['year'].isin([2020, 2021, 2022, 2023, 2024])].groupby(['timeframe', 'tier']).agg({
        'return': 'mean',
        'trades': 'mean',
        'win_rate': 'mean',
        'sharpe': 'mean',
        'mdd': 'mean',
        'outperf': 'mean'
    }).reset_index()

    print(tf_summary.to_string(index=False))

    # 2025년 검증 결과
    print("\n\n=== 2025 VALIDATION (Out-of-Sample) ===")
    val_2025 = df[df['year'] == 2025]
    print(val_2025.to_string(index=False))

    # 최고 성과
    print("\n\n=== TOP 5 STRATEGIES (2025) ===")
    top5 = df[df['year'] == 2025].nlargest(5, 'return')
    print(top5[['timeframe', 'tier', 'return', 'trades', 'win_rate', 'sharpe']].to_string(index=False))

    # CSV 저장
    df.to_csv(OUTPUT_DIR / 'backtest_summary.csv', index=False)
    tf_summary.to_csv(OUTPUT_DIR / 'timeframe_summary.csv', index=False)


if __name__ == '__main__':
    print("v41 S/A-Tier 단타 백테스팅 시작...")
    print(f"설정: TP={TAKE_PROFIT:.1%}, SL={STOP_LOSS:.1%}, Max Hold={MAX_HOLD_HOURS}h")
    print("="*80)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    results = run_all_backtests()

    print("\n\n완료! 결과 파일:")
    print(f"  - {OUTPUT_DIR}/backtest_summary.csv")
    print(f"  - {OUTPUT_DIR}/timeframe_summary.csv")
    print(f"  - {OUTPUT_DIR}/backtest_summary_all.json")
