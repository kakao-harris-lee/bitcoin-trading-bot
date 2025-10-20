#!/usr/bin/env python3
"""
Step 5: 2024년 실제 백테스팅
- Tier별 시그널을 2024년 실제 데이터에 적용
- 목표: 170% 수익률 달성 검증
"""

import sys
sys.path.append('../..')

import json
import pandas as pd
import numpy as np
from datetime import datetime
import sqlite3
import warnings
warnings.filterwarnings('ignore')


class FinalBacktest2024:
    """2024년 최종 백테스팅"""

    def __init__(self):
        self.db_path = '../../upbit_bitcoin.db'
        self.initial_capital = 10_000_000
        self.fee_rate = 0.0005
        self.slippage = 0.0002

    def load_2024_data(self, timeframe):
        """2024년 데이터 로드"""
        print(f"[{timeframe}] 2024년 데이터 로드 중...")

        conn = sqlite3.connect(self.db_path)

        # 타임프레임에 따른 테이블명
        table_map = {
            'minute5': 'bitcoin_minute5',
            'minute15': 'bitcoin_minute15',
            'minute60': 'bitcoin_minute60',
            'minute240': 'bitcoin_minute240',
            'day': 'bitcoin_day'
        }

        table = table_map.get(timeframe, 'bitcoin_day')

        query = f"""
            SELECT timestamp,
                   opening_price as open,
                   high_price as high,
                   low_price as low,
                   trade_price as close,
                   candle_acc_trade_volume as volume
            FROM {table}
            WHERE timestamp >= '2024-01-01' AND timestamp < '2025-01-01'
            ORDER BY timestamp ASC
        """

        df = pd.read_sql_query(query, conn)
        conn.close()

        print(f"  - {len(df):,}개 캔들 로드")
        print(f"  - 기간: {df['timestamp'].min()} ~ {df['timestamp'].max()}")

        return df

    def load_tier_signals(self, timeframe):
        """Tier 분류된 시그널 로드"""
        file_path = f'analysis/tier_backtest/{timeframe}_SA_tier.csv'
        print(f"[{timeframe}] S/A Tier 시그널 로드: {file_path}")

        df = pd.read_csv(file_path)
        print(f"  - {len(df):,}개 시그널 (S-Tier: {(df['tier']=='S').sum():,}, A-Tier: {(df['tier']=='A').sum():,})")

        return df

    def backtest_with_signals(self, price_df, signals_df, timeframe):
        """시그널 기반 백테스팅"""
        print(f"\n[{timeframe}] 백테스팅 실행 중...")

        # 시그널을 timestamp 기준으로 정렬
        signals_df = signals_df.sort_values('timestamp')

        capital = self.initial_capital
        position = 0  # BTC 보유량
        trades = []
        equity_curve = []

        buy_price = 0
        buy_timestamp = None

        for idx, signal_row in signals_df.iterrows():
            signal_time = pd.to_datetime(signal_row['timestamp'])

            # 2024년 범위 확인
            if signal_time.year != 2024:
                continue

            # 해당 시점의 가격 찾기
            price_match = price_df[price_df['timestamp'] == signal_row['timestamp']]

            if len(price_match) == 0:
                continue

            current_price = price_match.iloc[0]['close']

            # 포지션 없으면 매수
            if position == 0:
                # 전액 매수
                buy_cost = capital * (1 + self.fee_rate + self.slippage)
                position = capital / buy_cost
                buy_price = current_price
                buy_timestamp = signal_time

                trades.append({
                    'type': 'buy',
                    'timestamp': signal_time,
                    'price': current_price,
                    'amount': position,
                    'capital': capital
                })

                capital = 0

            # 포지션 있으면 30일 후 청산 확인
            elif position > 0 and buy_timestamp:
                # 30일 경과 체크
                days_held = (signal_time - buy_timestamp).days

                if days_held >= 30:
                    # 매도
                    sell_revenue = position * current_price * (1 - self.fee_rate - self.slippage)
                    capital = sell_revenue

                    profit = (current_price - buy_price) / buy_price

                    trades.append({
                        'type': 'sell',
                        'timestamp': signal_time,
                        'price': current_price,
                        'amount': position,
                        'capital': capital,
                        'profit': profit,
                        'days_held': days_held
                    })

                    position = 0
                    buy_price = 0
                    buy_timestamp = None

            # Equity curve 기록
            total_value = capital if position == 0 else position * current_price
            equity_curve.append({
                'timestamp': signal_time,
                'value': total_value
            })

        # 미청산 포지션 처리 (2024-12-31 종가로 청산)
        if position > 0:
            final_price = price_df.iloc[-1]['close']
            final_time = pd.to_datetime(price_df.iloc[-1]['timestamp'])

            sell_revenue = position * final_price * (1 - self.fee_rate - self.slippage)
            capital = sell_revenue

            profit = (final_price - buy_price) / buy_price if buy_price > 0 else 0
            days_held = (final_time - buy_timestamp).days if buy_timestamp else 0

            trades.append({
                'type': 'sell',
                'timestamp': final_time,
                'price': final_price,
                'amount': position,
                'capital': capital,
                'profit': profit,
                'days_held': days_held
            })

            position = 0

        # 최종 자본
        final_capital = capital

        print(f"\n백테스팅 완료:")
        print(f"  초기 자본: {self.initial_capital:,}원")
        print(f"  최종 자본: {final_capital:,.0f}원")
        print(f"  총 거래: {len(trades)}회")

        return {
            'trades': trades,
            'equity_curve': equity_curve,
            'final_capital': final_capital,
            'initial_capital': self.initial_capital
        }

    def calculate_metrics(self, backtest_results, price_df):
        """성과 지표 계산"""
        trades = backtest_results['trades']
        final_capital = backtest_results['final_capital']
        initial_capital = backtest_results['initial_capital']

        # 기본 지표
        total_return = (final_capital - initial_capital) / initial_capital

        # 거래 통계
        sell_trades = [t for t in trades if t['type'] == 'sell']

        if len(sell_trades) > 0:
            profits = [t['profit'] for t in sell_trades if 'profit' in t]
            win_rate = len([p for p in profits if p > 0]) / len(profits) if len(profits) > 0 else 0
            avg_profit = np.mean(profits) if len(profits) > 0 else 0
            avg_days_held = np.mean([t['days_held'] for t in sell_trades if 'days_held' in t])
        else:
            win_rate = 0
            avg_profit = 0
            avg_days_held = 0

        # Buy&Hold 계산
        start_price = price_df.iloc[0]['close']
        end_price = price_df.iloc[-1]['close']
        buy_hold_return = (end_price - start_price) / start_price

        # Sharpe Ratio (간이 계산)
        if len(sell_trades) > 0:
            returns = [t['profit'] for t in sell_trades if 'profit' in t]
            sharpe = (np.mean(returns) / np.std(returns)) if np.std(returns) > 0 else 0
        else:
            sharpe = 0

        metrics = {
            'total_return': total_return,
            'final_capital': final_capital,
            'total_trades': len(trades),
            'sell_trades': len(sell_trades),
            'win_rate': win_rate,
            'avg_profit': avg_profit,
            'avg_days_held': avg_days_held,
            'buy_hold_return': buy_hold_return,
            'outperformance': total_return - buy_hold_return,
            'sharpe_ratio': sharpe
        }

        return metrics

    def print_results(self, metrics, timeframe):
        """결과 출력"""
        print(f"\n{'='*70}")
        print(f"[{timeframe}] 2024년 백테스팅 결과")
        print(f"{'='*70}\n")

        print(f"=== 수익률 ===")
        print(f"전략 수익률: {metrics['total_return']:.2%}")
        print(f"Buy&Hold 수익률: {metrics['buy_hold_return']:.2%}")
        print(f"초과 수익: {metrics['outperformance']:.2%}p")

        # 목표 달성 여부
        target_return = metrics['buy_hold_return'] + 0.20  # Buy&Hold + 20%p
        achieved = metrics['total_return'] >= target_return

        print(f"\n목표 수익률: {target_return:.2%}")
        print(f"달성 여부: {'✅ 달성' if achieved else '❌ 미달성'}")

        print(f"\n=== 거래 통계 ===")
        print(f"총 거래: {metrics['total_trades']}회")
        print(f"매도 거래: {metrics['sell_trades']}회")
        print(f"승률: {metrics['win_rate']:.1%}")
        print(f"평균 수익: {metrics['avg_profit']:.2%}")
        print(f"평균 보유 기간: {metrics['avg_days_held']:.1f}일")

        print(f"\n=== 리스크 지표 ===")
        print(f"Sharpe Ratio: {metrics['sharpe_ratio']:.2f}")

        print(f"{'='*70}\n")

        return achieved

    def save_results(self, backtest_results, metrics, timeframe):
        """결과 저장"""
        output = {
            'timeframe': timeframe,
            'metrics': metrics,
            'trades': backtest_results['trades']
        }

        file_path = f'analysis/final_backtest/backtest_2024_{timeframe}.json'
        with open(file_path, 'w') as f:
            json.dump(output, f, indent=2, default=str)

        print(f"결과 저장: {file_path}")

    def run(self, timeframe):
        """전체 프로세스 실행"""
        print(f"\n{'='*70}")
        print(f"[{timeframe}] 2024년 최종 백테스팅 시작")
        print(f"{'='*70}\n")

        try:
            # 1. 2024년 가격 데이터 로드
            price_df = self.load_2024_data(timeframe)

            # 2. Tier 시그널 로드
            signals_df = self.load_tier_signals(timeframe)

            # 3. 백테스팅 실행
            backtest_results = self.backtest_with_signals(price_df, signals_df, timeframe)

            # 4. 성과 지표 계산
            metrics = self.calculate_metrics(backtest_results, price_df)

            # 5. 결과 출력
            achieved = self.print_results(metrics, timeframe)

            # 6. 결과 저장
            self.save_results(backtest_results, metrics, timeframe)

            return metrics, achieved

        except Exception as e:
            print(f"[{timeframe}] 오류: {e}")
            import traceback
            traceback.print_exc()
            return None, False


def main():
    """메인 실행"""
    print(f"\n{'='*70}")
    print(f"2024년 최종 백테스팅 시작")
    print(f"{'='*70}\n")

    start_time = datetime.now()

    # 출력 디렉토리 생성
    import os
    os.makedirs('analysis/final_backtest', exist_ok=True)

    backtester = FinalBacktest2024()

    timeframes = ['day', 'minute60', 'minute15']

    results = {}
    achievements = {}

    for tf in timeframes:
        metrics, achieved = backtester.run(tf)

        if metrics:
            results[tf] = metrics
            achievements[tf] = achieved

    # 전체 요약
    print(f"\n{'='*70}")
    print(f"2024년 백테스팅 최종 요약")
    print(f"{'='*70}\n")

    print(f"{'타임프레임':<12} {'전략 수익률':<15} {'Buy&Hold':<15} {'초과 수익':<12} {'달성'}")
    print(f"{'-'*70}")

    for tf, metrics in results.items():
        achieved = '✅' if achievements[tf] else '❌'
        print(f"{tf:<12} {metrics['total_return']:<15.2%} "
              f"{metrics['buy_hold_return']:<15.2%} "
              f"{metrics['outperformance']:<12.2%}p {achieved}")

    # 최종 저장
    summary = {
        'timeframes': results,
        'achievements': achievements
    }

    with open('analysis/final_backtest/backtest_2024_summary.json', 'w') as f:
        json.dump(summary, f, indent=2, default=str)

    elapsed = datetime.now() - start_time
    print(f"\n소요 시간: {elapsed}")
    print(f"{'='*70}\n")


if __name__ == '__main__':
    main()
