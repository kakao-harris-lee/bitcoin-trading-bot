"""
v-a-13: Nested Timeframe Backtester

Day Sideways 신호 기간 내에서 4H/1H 레벨 단타 실행
"""

import json
import sqlite3
from pathlib import Path
from datetime import datetime, timedelta
import pandas as pd
import numpy as np
from signal_extractors_nested import (
    calculate_indicators_4h,
    calculate_indicators_1h,
    extract_4h_signals,
    extract_1h_signals
)


class NestedBacktester:
    """
    Nested Timeframe Backtesting Engine

    Day 시그널 기간 내에서 4H/1H 단타 실행
    """

    def __init__(self, config_path: str = 'config.json'):
        with open(config_path, 'r') as f:
            self.config = json.load(f)

        self.capital = self.config['base_capital']
        self.initial_capital = self.capital
        self.fee_rate = self.config['fee_rate']
        self.slippage = self.config['slippage']
        self.total_fee = self.fee_rate + self.slippage

        self.trades = []
        self.positions = {}  # {position_id: position_info}
        self.position_counter = 0

    def load_day_signals(self, year: int) -> pd.DataFrame:
        """v-a-11 시그널 로드 (config에 따라 SIDEWAYS 또는 BULL/BEAR)"""
        signal_path = Path(__file__).parent.parent / 'v-a-11' / 'signals' / f'day_{year}_signals.json'

        if not signal_path.exists():
            print(f"⚠️  {year}년 Day 시그널 없음: {signal_path}")
            return pd.DataFrame()

        with open(signal_path, 'r') as f:
            data = json.load(f)

        # Check config for market states
        market_states = self.config['day_config'].get('market_states', ['SIDEWAYS'])

        # Extract signals matching market states
        signals = [s for s in data['signals'] if s['market_state'] in market_states]

        if len(signals) == 0:
            print(f"⚠️  {year}년 {market_states} 시그널 없음")
            return pd.DataFrame()

        df = pd.DataFrame(signals)
        print(f"✅ {year}년 {market_states} 시그널: {len(df)}개 (전체 {data['total_signals']}개)")
        return df

    def load_intraday_data(self, timeframe: str, start: str, end: str) -> pd.DataFrame:
        """4H or 1H 데이터 로드"""
        db_path = Path(__file__).parent.parent.parent / 'upbit_bitcoin.db'
        conn = sqlite3.connect(db_path)

        table_map = {'4h': 'bitcoin_minute240', '1h': 'bitcoin_minute60'}
        table = table_map[timeframe]

        query = f"""
        SELECT
            timestamp,
            opening_price as open,
            high_price as high,
            low_price as low,
            trade_price as close,
            candle_acc_trade_volume as volume
        FROM {table}
        WHERE timestamp >= '{start}' AND timestamp < '{end}'
        ORDER BY timestamp
        """

        df = pd.read_sql_query(query, conn)
        conn.close()

        return df

    def check_exit(self, pos: dict, row: pd.Series, timeframe: str) -> tuple:
        """
        Exit 조건 체크

        Returns:
            (should_exit, exit_type, exit_ratio)
        """
        cfg = self.config[f'{timeframe}_config']['exit']

        current_price = row['close']
        entry_price = pos['entry_price']
        highest_price = pos['highest_price']
        profit = (current_price - entry_price) / entry_price

        # Update highest price
        if current_price > highest_price:
            pos['highest_price'] = current_price
            highest_price = current_price

        # Stop Loss
        if profit <= cfg['stop_loss']:
            return (True, 'stop_loss', 1.0)

        # Trailing Stop
        drawdown_from_peak = (current_price - highest_price) / highest_price
        if drawdown_from_peak <= cfg['trailing_from_peak']:
            return (True, 'trailing_stop', 1.0)

        # Take Profit 1
        if profit >= cfg['tp1']:
            return (True, 'tp1', cfg['tp1_ratio'])

        # Take Profit 2
        if profit >= cfg['tp2']:
            return (True, 'tp2', cfg['tp2_ratio'])

        # Timeout
        hours_held = (pd.to_datetime(row['timestamp']) - pd.to_datetime(pos['entry_time'])).total_seconds() / 3600
        if hours_held >= cfg['max_hold_hours']:
            return (True, 'timeout', 1.0)

        return (False, None, 0)

    def execute_trade(self, pos_id: int, entry_time: str, entry_price: float,
                     exit_time: str, exit_price: float, exit_type: str,
                     exit_ratio: float, timeframe: str):
        """거래 실행 및 기록"""
        pos = self.positions[pos_id]

        # Entry fee
        entry_cost = pos['capital'] * (1 + self.total_fee)
        btc_amount = (pos['capital'] - pos['capital'] * self.total_fee) / entry_price

        # Exit fee
        exit_amount = btc_amount * exit_ratio
        exit_gross = exit_amount * exit_price
        exit_fee = exit_gross * self.total_fee
        exit_net = exit_gross - exit_fee

        # Profit
        invested = pos['capital'] * exit_ratio
        profit = exit_net - invested
        profit_pct = profit / invested

        # Update capital - 청산 수익금 전체 복구!
        self.capital += exit_net

        # Reduce position or close
        if exit_ratio >= 0.99:
            del self.positions[pos_id]
        else:
            pos['capital'] *= (1 - exit_ratio)

        # Record trade
        self.trades.append({
            'position_id': pos_id,
            'timeframe': timeframe,
            'entry_time': entry_time,
            'entry_price': entry_price,
            'exit_time': exit_time,
            'exit_price': exit_price,
            'exit_type': exit_type,
            'exit_ratio': exit_ratio,
            'invested': invested,
            'profit': profit,
            'profit_pct': profit_pct,
            'capital_after': self.capital
        })

    def backtest_within_day_signal(self, day_signal: pd.Series, df_4h: pd.DataFrame, df_1h: pd.DataFrame):
        """
        단일 Day 신호 기간 내 4H/1H 거래 실행
        """
        day_entry = pd.to_datetime(day_signal['timestamp'])
        max_hold_days = self.config['day_config'].get('max_hold_days', 30)
        day_exit = day_entry + timedelta(days=max_hold_days)

        # Filter intraday data within this period
        df_4h_period = df_4h[(pd.to_datetime(df_4h['timestamp']) >= day_entry) &
                             (pd.to_datetime(df_4h['timestamp']) < day_exit)].copy()

        df_1h_period = df_1h[(pd.to_datetime(df_1h['timestamp']) >= day_entry) &
                             (pd.to_datetime(df_1h['timestamp']) < day_exit)].copy()

        if len(df_4h_period) == 0 or len(df_1h_period) == 0:
            return

        # Calculate indicators
        df_4h_period = calculate_indicators_4h(df_4h_period)
        df_1h_period = calculate_indicators_1h(df_1h_period)

        # Extract signals
        signals_4h = extract_4h_signals(df_4h_period, self.config['4h_config'])
        signals_1h = extract_1h_signals(df_1h_period, self.config['1h_config'])

        # Execute 4H trades
        max_4h = self.config['4h_config']['max_entries_per_day_signal']
        count_4h = 0

        for idx, sig in signals_4h.iterrows():
            if count_4h >= max_4h:
                break

            # Signal strength filter
            signal_strength_min = self.config['4h_config'].get('signal_strength_min', 0)
            if sig['signal_strength'] < signal_strength_min:
                continue

            # Check capital availability
            position_size = self.config['4h_config']['position_size']
            required_capital = self.capital * position_size  # 현재 자본 기준!

            if required_capital < 100000:  # 최소 10만원
                continue

            # Open position
            entry_price = sig['close']
            self.position_counter += 1
            pos_id = self.position_counter

            self.positions[pos_id] = {
                'entry_time': sig['timestamp'],
                'entry_price': entry_price,
                'capital': required_capital,
                'highest_price': entry_price,
                'timeframe': '4h'
            }

            self.capital -= required_capital
            count_4h += 1

            # Monitor exit
            entry_time = pd.to_datetime(sig['timestamp'])
            for exit_idx, exit_row in df_4h_period[pd.to_datetime(df_4h_period['timestamp']) > entry_time].iterrows():
                if pos_id not in self.positions:
                    break

                should_exit, exit_type, exit_ratio = self.check_exit(self.positions[pos_id], exit_row, '4h')

                if should_exit:
                    self.execute_trade(
                        pos_id, sig['timestamp'], entry_price,
                        exit_row['timestamp'], exit_row['close'],
                        exit_type, exit_ratio, '4h'
                    )

        # Execute 1H trades
        max_1h = self.config['1h_config']['max_entries_per_day_signal']
        count_1h = 0

        for idx, sig in signals_1h.iterrows():
            if count_1h >= max_1h:
                break

            # Signal strength filter
            signal_strength_min = self.config['1h_config'].get('signal_strength_min', 0)
            if sig['signal_strength'] < signal_strength_min:
                continue

            # Check capital availability
            position_size = self.config['1h_config']['position_size']
            required_capital = self.capital * position_size  # 현재 자본 기준!

            if required_capital < 100000:  # 최소 10만원
                continue

            # Open position
            entry_price = sig['close']
            self.position_counter += 1
            pos_id = self.position_counter

            self.positions[pos_id] = {
                'entry_time': sig['timestamp'],
                'entry_price': entry_price,
                'capital': required_capital,
                'highest_price': entry_price,
                'timeframe': '1h'
            }

            self.capital -= required_capital
            count_1h += 1

            # Monitor exit
            entry_time = pd.to_datetime(sig['timestamp'])
            for exit_idx, exit_row in df_1h_period[pd.to_datetime(df_1h_period['timestamp']) > entry_time].iterrows():
                if pos_id not in self.positions:
                    break

                should_exit, exit_type, exit_ratio = self.check_exit(self.positions[pos_id], exit_row, '1h')

                if should_exit:
                    self.execute_trade(
                        pos_id, sig['timestamp'], entry_price,
                        exit_row['timestamp'], exit_row['close'],
                        exit_type, exit_ratio, '1h'
                    )

    def run_year(self, year: int) -> dict:
        """연도별 백테스팅"""
        print(f"\n{'='*70}")
        print(f"  {year}년 백테스팅")
        print(f"{'='*70}")

        # Reset
        self.capital = self.initial_capital
        self.trades = []
        self.positions = {}

        # Load Day signals
        day_signals = self.load_day_signals(year)

        if len(day_signals) == 0:
            return {
                'year': year,
                'total_return': 0,
                'total_trades': 0,
                'trades_4h': 0,
                'trades_1h': 0,
                'win_rate': 0,
                'avg_profit': 0,
                'avg_win': 0,
                'avg_loss': 0,
                'final_capital': self.initial_capital
            }

        # Load intraday data for the year
        start_date = f'{year}-01-01'
        end_date = f'{year+1}-01-01'

        df_4h = self.load_intraday_data('4h', start_date, end_date)
        df_1h = self.load_intraday_data('1h', start_date, end_date)

        print(f"4H 데이터: {len(df_4h)}개 캔들")
        print(f"1H 데이터: {len(df_1h)}개 캔들")

        # Backtest each Day signal
        for idx, day_sig in day_signals.iterrows():
            self.backtest_within_day_signal(day_sig, df_4h, df_1h)

        # Calculate results
        total_return = (self.capital - self.initial_capital) / self.initial_capital * 100
        total_trades = len(self.trades)

        if total_trades > 0:
            wins = sum(1 for t in self.trades if t['profit'] > 0)
            win_rate = wins / total_trades * 100
            avg_profit = np.mean([t['profit_pct'] * 100 for t in self.trades])
            avg_win = np.mean([t['profit_pct'] * 100 for t in self.trades if t['profit'] > 0]) if wins > 0 else 0
            avg_loss = np.mean([t['profit_pct'] * 100 for t in self.trades if t['profit'] <= 0]) if wins < total_trades else 0
        else:
            win_rate = avg_profit = avg_win = avg_loss = 0

        # Count by timeframe
        count_4h = sum(1 for t in self.trades if t['timeframe'] == '4h')
        count_1h = sum(1 for t in self.trades if t['timeframe'] == '1h')

        result = {
            'year': year,
            'total_return': round(total_return, 2),
            'total_trades': total_trades,
            'trades_4h': count_4h,
            'trades_1h': count_1h,
            'win_rate': round(win_rate, 2),
            'avg_profit': round(avg_profit, 2),
            'avg_win': round(avg_win, 2),
            'avg_loss': round(avg_loss, 2),
            'final_capital': round(self.capital, 0)
        }

        print(f"\n[결과]")
        print(f"  수익률: {result['total_return']:+.2f}%")
        print(f"  거래: {total_trades}회 (4H: {count_4h}, 1H: {count_1h})")
        print(f"  승률: {win_rate:.1f}%")
        print(f"  평균 수익: {avg_profit:+.2f}%")

        return result


def main():
    """전체 백테스팅 실행 (2020-2025)"""
    print("="*70)
    print("  v-a-13: Nested Timeframe Strategy Backtest")
    print("="*70)

    backtester = NestedBacktester()

    results = {}
    for year in range(2020, 2026):
        result = backtester.run_year(year)
        results[year] = result

    # Summary
    print(f"\n{'='*70}")
    print("  전체 결과 요약")
    print(f"{'='*70}\n")

    total_trades = sum(r['total_trades'] for r in results.values())
    avg_return = np.mean([r['total_return'] for r in results.values()])

    print(f"{'연도':<8} {'수익률':>10} {'거래':>8} {'4H':>6} {'1H':>6} {'승률':>8} {'평균수익':>10}")
    print("-"*70)

    for year, r in results.items():
        print(f"{year:<8} {r['total_return']:>9.2f}% {r['total_trades']:>7}회 "
              f"{r['trades_4h']:>5}회 {r['trades_1h']:>5}회 "
              f"{r['win_rate']:>7.1f}% {r['avg_profit']:>9.2f}%")

    print("-"*70)
    print(f"{'평균':<8} {avg_return:>9.2f}% {total_trades:>7}회")

    # Save results
    output_path = Path(__file__).parent / 'results' / 'backtest_nested.json'
    output_path.parent.mkdir(exist_ok=True)

    with open(output_path, 'w') as f:
        json.dump({
            'results': results,
            'summary': {
                'avg_return': round(avg_return, 2),
                'total_trades': total_trades
            }
        }, f, indent=2)

    print(f"\n✅ 결과 저장: {output_path}")

    # Compare with v-a-11
    print(f"\n{'='*70}")
    print("  v-a-11 vs v-a-13 비교")
    print(f"{'='*70}\n")

    v11_avg = 66.00  # v-a-11 평균
    improvement = avg_return - v11_avg
    improvement_pct = (improvement / v11_avg) * 100

    print(f"v-a-11 평균: {v11_avg:+.2f}%")
    print(f"v-a-13 평균: {avg_return:+.2f}%")
    print(f"개선: {improvement:+.2f}%p ({improvement_pct:+.1f}%)")

    if avg_return > v11_avg:
        print(f"\n🎉 목표 달성! v-a-11 초과 성공!")
    else:
        print(f"\n⚠️  목표 미달. 추가 최적화 필요.")


if __name__ == '__main__':
    main()
