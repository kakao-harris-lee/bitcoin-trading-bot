#!/usr/bin/env python3
"""
Phase 2: A-Tier 고도화 전략
- A+ Tier 추가 (점수 20-24점, 품질 향상)
- 동적 포지션 사이징 (Tier별 차등)
- 거래 타이밍 최적화 (우선순위 기반)
- 손익비 개선 (Tier별 차등 TP/SL)
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
OUTPUT_DIR = Path('strategies/v41_scalping_voting/validation/optimized_results')
OUTPUT_DIR.mkdir(exist_ok=True)

# 기본 파라미터
FEE_RATE = 0.0005
SLIPPAGE = 0.0002

# Tier별 전략 파라미터
TIER_CONFIGS = {
    'S': {
        'score_min': 25,
        'score_max': 100,
        'position_size': 1.0,  # 100% 자본
        'take_profit': 0.07,   # +7%
        'stop_loss': -0.02,    # -2%
        'trailing_stop': 0.015, # 고점 -1.5%
        'max_hold_hours': 72,
        'min_interval_hours': 0,  # 제한 없음
    },
    'A+': {
        'score_min': 20,
        'score_max': 24,
        'position_size': 0.7,  # 70% 자본
        'take_profit': 0.05,   # +5%
        'stop_loss': -0.015,   # -1.5%
        'trailing_stop': 0.01,  # 고점 -1%
        'max_hold_hours': 48,
        'min_interval_hours': 2,  # 최소 2시간 간격
    },
    'A': {
        'score_min': 15,
        'score_max': 19,
        'position_size': 0.4,  # 40% 자본
        'take_profit': 0.03,   # +3%
        'stop_loss': -0.01,    # -1%
        'trailing_stop': 0,     # 없음
        'max_hold_hours': 24,
        'min_interval_hours': 4,  # 최소 4시간 간격
    },
}


class OptimizedBacktest:
    """최적화된 고빈도 백테스팅"""

    def __init__(self, timeframe, year, tiers=['S', 'A+', 'A']):
        self.timeframe = timeframe
        self.year = year
        self.tiers = tiers
        self.capital = 10_000_000
        self.initial_capital = 10_000_000
        self.position = None
        self.trades = []
        self.last_exit_time = None

    def load_tier_data(self):
        """Tier 분류 데이터 로드 (점수 포함)"""
        tier_file = TIER_DATA_DIR / f'{self.timeframe}_tier_classified.csv'
        if not tier_file.exists():
            print(f"⚠️ {tier_file} 파일이 없습니다.")
            return pd.DataFrame()

        df = pd.read_csv(tier_file)
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df = df[df['timestamp'].dt.year == self.year]

        # optimized_score 컬럼 확인
        if 'optimized_score' not in df.columns:
            print(f"⚠️ optimized_score 컬럼이 없습니다.")
            return pd.DataFrame()

        # 점수 기반 Tier 재분류
        def classify_tier(score):
            if score >= 25:
                return 'S'
            elif score >= 20:
                return 'A+'
            elif score >= 15:
                return 'A'
            else:
                return 'B'

        df['tier_optimized'] = df['optimized_score'].apply(classify_tier)

        # 선택된 Tier만 필터링
        df = df[df['tier_optimized'].isin(self.tiers)]

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
        """진입 가능 여부 확인 (간격 제한)"""
        if self.last_exit_time is None:
            return True

        config = TIER_CONFIGS[tier]
        min_interval = timedelta(hours=config['min_interval_hours'])
        time_since_last = signal_time - self.last_exit_time

        return time_since_last >= min_interval

    def check_exit(self, entry_price, high_price, current_price, hours_held, tier, peak_price):
        """청산 조건 체크 (Tier별 차등)"""
        config = TIER_CONFIGS[tier]
        pnl = (current_price - entry_price) / entry_price

        # 익절
        if pnl >= config['take_profit']:
            return True, 'take_profit', pnl

        # 손절
        if pnl <= config['stop_loss']:
            return True, 'stop_loss', pnl

        # Trailing Stop (S, A+만)
        if config['trailing_stop'] > 0:
            trailing_threshold = (peak_price - current_price) / entry_price
            if trailing_threshold >= config['trailing_stop']:
                return True, 'trailing_stop', pnl

        # 시간 초과
        if hours_held >= config['max_hold_hours']:
            return True, 'timeout', pnl

        return False, None, pnl

    def run(self):
        """백테스팅 실행"""
        signals = self.load_tier_data()
        price_df = self.load_price_data()

        if len(signals) == 0:
            return self.get_empty_result()

        print(f"\n{self.timeframe} {self.year} {'+'.join(self.tiers)}: {len(signals)} signals")

        # Tier별 우선순위 정렬 (점수 높은 순)
        signals = signals.sort_values(['timestamp', 'optimized_score'], ascending=[True, False])

        for idx, signal in signals.iterrows():
            signal_time = signal['timestamp']
            signal_tier = signal['tier_optimized']
            signal_score = signal['optimized_score']

            # 포지션이 있으면 청산 체크
            if self.position:
                entry_time = self.position['entry_time']
                entry_price = self.position['entry_price']
                tier = self.position['tier']
                peak_price = self.position['peak_price']

                # 청산 체크
                future_prices = price_df[price_df['timestamp'] > entry_time]
                for _, row in future_prices.iterrows():
                    hours_held = (row['timestamp'] - entry_time).total_seconds() / 3600

                    # 고점 업데이트
                    if row['high'] > peak_price:
                        peak_price = row['high']
                        self.position['peak_price'] = peak_price

                    should_exit, reason, pnl = self.check_exit(
                        entry_price, row['high'], row['close'], hours_held, tier, peak_price
                    )

                    if should_exit:
                        # 청산
                        exit_price = row['close']
                        trade_pnl = pnl - (FEE_RATE + SLIPPAGE) * 2

                        # 포지션 크기 고려
                        position_size = TIER_CONFIGS[tier]['position_size']
                        capital_change = self.capital * position_size * trade_pnl
                        self.capital += capital_change

                        self.trades.append({
                            'entry_time': entry_time,
                            'entry_price': entry_price,
                            'exit_time': row['timestamp'],
                            'exit_price': exit_price,
                            'pnl': trade_pnl,
                            'capital_change': capital_change,
                            'capital': self.capital,
                            'reason': reason,
                            'hold_hours': hours_held,
                            'tier': tier,
                            'score': self.position['score']
                        })

                        self.last_exit_time = row['timestamp']
                        self.position = None
                        break

            # 신규 진입 (포지션이 없고 간격 조건 만족 시)
            if not self.position and self.can_enter(signal_time, signal_tier):
                signal_row = price_df[price_df['timestamp'] == signal_time]
                if len(signal_row) > 0:
                    entry_price = signal_row.iloc[0]['close'] * (1 + SLIPPAGE)
                    peak_price = signal_row.iloc[0]['high']

                    self.position = {
                        'entry_time': signal_time,
                        'entry_price': entry_price,
                        'peak_price': peak_price,
                        'tier': signal_tier,
                        'score': signal_score
                    }

        # 마지막 포지션 강제 청산
        if self.position:
            last_row = price_df.iloc[-1]
            entry_price = self.position['entry_price']
            tier = self.position['tier']
            pnl = (last_row['close'] - entry_price) / entry_price - (FEE_RATE + SLIPPAGE) * 2

            position_size = TIER_CONFIGS[tier]['position_size']
            capital_change = self.capital * position_size * pnl
            self.capital += capital_change

            hours_held = (last_row['timestamp'] - self.position['entry_time']).total_seconds() / 3600

            self.trades.append({
                'entry_time': self.position['entry_time'],
                'entry_price': entry_price,
                'exit_time': last_row['timestamp'],
                'exit_price': last_row['close'],
                'pnl': pnl,
                'capital_change': capital_change,
                'capital': self.capital,
                'reason': 'forced_close',
                'hold_hours': hours_held,
                'tier': tier,
                'score': self.position['score']
            })

            self.position = None

        # Buy & Hold 계산
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
            'sharpe_ratio': 0,
            'max_drawdown': 0,
            'buy_hold_return': 0,
            'outperformance': 0,
        }

    def get_results(self, buy_hold_return):
        """결과 정리"""
        if len(self.trades) == 0:
            result = self.get_empty_result()
            result['buy_hold_return'] = buy_hold_return
            result['outperformance'] = 0 - buy_hold_return
            return result

        df = pd.DataFrame(self.trades)

        wins = df[df['pnl'] > 0]
        losses = df[df['pnl'] <= 0]

        total_return = (self.capital - self.initial_capital) / self.initial_capital
        win_rate = len(wins) / len(df) if len(df) > 0 else 0

        # Sharpe Ratio
        returns = df['pnl'].values
        sharpe = returns.mean() / returns.std() if returns.std() > 0 else 0

        # Max Drawdown
        capital_series = df['capital'].values
        running_max = np.maximum.accumulate(capital_series)
        drawdowns = (capital_series - running_max) / running_max
        max_dd = drawdowns.min() if len(drawdowns) > 0 else 0

        # Tier별 통계
        tier_stats = df.groupby('tier').agg({
            'pnl': ['count', 'mean', lambda x: (x > 0).sum() / len(x) if len(x) > 0 else 0]
        }).round(4)

        result = {
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
            'tier_stats': tier_stats.to_dict() if len(tier_stats) > 0 else {},
            'trades_per_tier': df.groupby('tier').size().to_dict(),
        }

        return result


def main():
    """메인 실행"""
    print("\n" + "=" * 80)
    print("Phase 2: A-Tier 고도화 전략 백테스팅")
    print("=" * 80)

    # 테스트 조합
    test_cases = [
        ('minute60', 2020, ['S'], "보수적: S-Tier만"),
        ('minute60', 2020, ['S', 'A+'], "균형: S + A+"),
        ('minute60', 2020, ['S', 'A+', 'A'], "공격적: 전체 ⭐"),
        ('minute60', 2020, ['A+'], "실험: A+만"),
        ('minute60', 2020, ['A'], "실험: A만"),

        ('minute60', 2024, ['S'], "보수적: S-Tier만"),
        ('minute60', 2024, ['S', 'A+'], "균형: S + A+"),
        ('minute60', 2024, ['S', 'A+', 'A'], "공격적: 전체 ⭐"),
        ('minute60', 2024, ['A+'], "실험: A+만"),
        ('minute60', 2024, ['A'], "실험: A만"),

        ('day', 2020, ['S'], "보수적: S-Tier만"),
        ('day', 2020, ['S', 'A+', 'A'], "공격적: 전체"),

        ('day', 2024, ['S'], "보수적: S-Tier만"),
        ('day', 2024, ['S', 'A+', 'A'], "공격적: 전체"),
    ]

    all_results = []

    for timeframe, year, tiers, desc in test_cases:
        print(f"\n{'='*60}")
        print(f"{timeframe} {year} - {desc}")
        print(f"{'='*60}")

        bt = OptimizedBacktest(timeframe, year, tiers)
        result = bt.run()

        if result['total_trades'] > 0:
            print(f"  총 거래: {result['total_trades']}회")
            print(f"  수익률: {result['total_return']:.2%}")
            print(f"  승률: {result['win_rate']:.1%}")
            print(f"  Sharpe: {result['sharpe_ratio']:.2f}")
            print(f"  MDD: {result['max_drawdown']:.2%}")
            print(f"  Buy&Hold: {result['buy_hold_return']:.2%}")
            print(f"  초과수익: {result['outperformance']:.2%}")

            if 'trades_per_tier' in result:
                print(f"  Tier별 거래: {result['trades_per_tier']}")

        all_results.append(result)

    # 결과 저장
    output_file = OUTPUT_DIR / 'optimized_backtest_results.json'
    with open(output_file, 'w') as f:
        json.dump(all_results, f, indent=2, default=str)

    print(f"\n\n결과 저장: {output_file}")

    # 요약 통계
    print("\n" + "=" * 80)
    print("📊 전략 비교")
    print("=" * 80)

    df_results = pd.DataFrame(all_results)
    df_results = df_results[df_results['total_trades'] > 0]

    if len(df_results) > 0:
        for tf in df_results['timeframe'].unique():
            print(f"\n{tf.upper()}:")
            tf_data = df_results[df_results['timeframe'] == tf]

            for _, row in tf_data.iterrows():
                print(f"  {row['year']} {row['tiers']:15s}: "
                      f"{row['total_return']:7.1%} "
                      f"({row['total_trades']:4.0f}회, "
                      f"승률 {row['win_rate']:5.1%}, "
                      f"Sharpe {row['sharpe_ratio']:4.2f})")

    print("\n✅ Phase 2 완료!")


if __name__ == '__main__':
    main()
