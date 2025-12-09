#!/usr/bin/env python3
"""
v35 Optimized Backtesting Script
최적화 전 기본 성과 확인 (2025 목표: +15%)
"""

import sys
sys.path.append('../..')

from core.data_loader import DataLoader
from core.market_analyzer import MarketAnalyzer
from strategy import V35OptimizedStrategy
import pandas as pd
import numpy as np
import json
from datetime import datetime
from typing import Dict


class V35Backtester:
    """v35 백테스팅 엔진 (분할 익절 지원)"""

    def __init__(self, initial_capital: float, fee_rate: float = 0.0005, slippage: float = 0.0002):
        self.initial_capital = initial_capital
        self.capital = initial_capital
        self.fee_rate = fee_rate
        self.slippage = slippage
        self.position = 0.0
        self.trades = []
        self.equity_curve = []

    def run(self, df: pd.DataFrame, strategy: V35OptimizedStrategy) -> Dict:
        """백테스팅 실행 (분할 익절 지원)"""
        self.capital = self.initial_capital
        self.position = 0.0
        self.trades = []
        self.equity_curve = []

        for i in range(30, len(df)):
            signal = strategy.execute(df, i)
            row = df.iloc[i]

            # Buy
            if signal['action'] == 'buy' and self.position == 0:
                fraction = signal.get('fraction', 0.5)
                buy_amount = self.capital * fraction
                buy_price = row['close'] * (1 + self.slippage)
                fee = buy_amount * self.fee_rate
                shares = (buy_amount - fee) / buy_price

                if shares > 0:
                    self.position = shares
                    self.capital -= buy_amount
                    self.trades.append({
                        'type': 'buy',
                        'time': row.name,
                        'price': buy_price,
                        'shares': shares,
                        'reason': signal.get('reason', 'UNKNOWN')
                    })

            # Sell (분할 익절 지원)
            elif signal['action'] == 'sell' and self.position > 0:
                sell_fraction = signal.get('fraction', 1.0)
                sell_shares = self.position * sell_fraction
                sell_price = row['close'] * (1 - self.slippage)
                proceeds = sell_shares * sell_price * (1 - self.fee_rate)

                self.capital += proceeds
                self.position -= sell_shares

                self.trades.append({
                    'type': 'sell',
                    'time': row.name,
                    'price': sell_price,
                    'shares': sell_shares,
                    'fraction': sell_fraction,
                    'reason': signal.get('reason', 'UNKNOWN')
                })

            # Equity
            current_equity = self.capital + (self.position * row['close'] if self.position > 0 else 0)
            self.equity_curve.append(current_equity)

        # 마지막 포지션 정리
        if self.position > 0:
            self.capital += self.position * df.iloc[-1]['close'] * (1 - self.slippage - self.fee_rate)
            self.position = 0

        return self._calculate_metrics(df)

    def _calculate_metrics(self, df: pd.DataFrame) -> Dict:
        """성과 지표 계산"""
        final_capital = self.capital
        total_return = (final_capital - self.initial_capital) / self.initial_capital * 100

        # 거래 분석
        buy_trades = [t for t in self.trades if t['type'] == 'buy']
        sell_trades = [t for t in self.trades if t['type'] == 'sell']

        profits = []
        for i in range(min(len(buy_trades), len(sell_trades))):
            profit_pct = (sell_trades[i]['price'] - buy_trades[i]['price']) / buy_trades[i]['price'] * 100
            profits.append(profit_pct)

        wins = [p for p in profits if p > 0]
        losses = [p for p in profits if p <= 0]

        # Sharpe Ratio
        equity_series = pd.Series(self.equity_curve)
        returns = equity_series.pct_change().dropna()
        sharpe = returns.mean() / returns.std() * np.sqrt(252) if len(returns) > 0 and returns.std() > 0 else 0

        # Max Drawdown
        cummax = equity_series.cummax()
        drawdown = (equity_series - cummax) / cummax * 100
        max_drawdown = drawdown.min()

        # Buy&Hold
        start_price = df.iloc[30]['close']
        end_price = df.iloc[-1]['close']
        buy_hold_return = (end_price - start_price) / start_price * 100

        return {
            'initial_capital': self.initial_capital,
            'final_capital': final_capital,
            'total_return': total_return,
            'buy_hold_return': buy_hold_return,
            'excess_return': total_return - buy_hold_return,
            'total_trades': len(profits),
            'wins': len(wins),
            'losses': len(losses),
            'win_rate': len(wins) / len(profits) * 100 if len(profits) > 0 else 0,
            'avg_profit': np.mean(wins) if len(wins) > 0 else 0,
            'avg_loss': np.mean(losses) if len(losses) > 0 else 0,
            'sharpe_ratio': sharpe,
            'max_drawdown': max_drawdown,
            'profit_factor': abs(sum(wins) / sum(losses)) if len(losses) > 0 and sum(losses) != 0 else 0,
            'trades': self.trades,
            'equity_curve': self.equity_curve
        }


def run_backtest_single(year: str, config: Dict):
    """단일 연도 백테스팅"""
    print(f"\n{'='*70}")
    print(f"  {year}년 백테스팅")
    print(f"{'='*70}")

    with DataLoader('../../upbit_bitcoin.db') as loader:
        df = loader.load_timeframe(
            'day',
            start_date=f'{year}-01-01',
            end_date=f'{year}-12-31' if year != '2025' else '2025-10-17'
        )

    print(f"데이터: {len(df)}개 캔들 ({df.iloc[0].name} ~ {df.iloc[-1].name})")

    df = MarketAnalyzer.add_indicators(df, indicators=['rsi', 'macd', 'mfi', 'adx', 'atr', 'bb', 'stoch'])

    strategy = V35OptimizedStrategy(config)
    backtester = V35Backtester(
        initial_capital=config.get('initial_capital', 10000000),
        fee_rate=config.get('fee_rate', 0.0005),
        slippage=config.get('slippage', 0.0002)
    )

    results = backtester.run(df, strategy)

    print(f"\n[수익률]")
    print(f"  초기 자본: {results['initial_capital']:,.0f}원")
    print(f"  최종 자본: {results['final_capital']:,.0f}원")
    print(f"  수익률: {results['total_return']:+.2f}%")
    print(f"\n[vs Buy&Hold]")
    print(f"  Buy&Hold: {results['buy_hold_return']:+.2f}%")
    print(f"  초과 수익: {results['excess_return']:+.2f}%p")
    print(f"\n[리스크]")
    print(f"  Sharpe: {results['sharpe_ratio']:.2f}")
    print(f"  MDD: {results['max_drawdown']:.2f}%")
    print(f"\n[거래]")
    print(f"  총 거래: {results['total_trades']}회")
    print(f"  승률: {results['win_rate']:.1f}%")

    return results


if __name__ == '__main__':
    # Config 로드 (Optuna 최적화 버전)
    with open('config_optimized.json') as f:
        config = json.load(f)

    # Config 병합 (depth 제거)
    merged_config = {}
    for key, value in config.items():
        if isinstance(value, dict):
            merged_config.update(value)
        else:
            merged_config[key] = value

    print("="*70)
    print("  v35 Optimized - 백테스팅 (최적화 전)")
    print("="*70)
    print(f"Strategy: {config['strategy_name']} {config['version']}")
    print(f"Timeframe: {config['timeframe']}")

    # 백테스팅 실행 (2020~2025)
    results_2020 = run_backtest_single('2020', merged_config)
    results_2021 = run_backtest_single('2021', merged_config)
    results_2022 = run_backtest_single('2022', merged_config)
    results_2023 = run_backtest_single('2023', merged_config)
    results_2024 = run_backtest_single('2024', merged_config)
    results_2025 = run_backtest_single('2025', merged_config)

    # 종합 요약
    print(f"\n{'='*70}")
    print(f"  종합 요약 (2020~2025)")
    print(f"{'='*70}")
    print(f"\n{'연도':^10s} | {'수익률':^10s} | {'B&H':^10s} | {'초과':^10s} | {'Sharpe':^8s} | {'MDD':^8s} | {'거래':^6s} | {'승률':^6s}")
    print(f"{'-'*10}|{'-'*12}|{'-'*12}|{'-'*12}|{'-'*10}|{'-'*10}|{'-'*8}|{'-'*8}")

    for year, res in [('2020', results_2020), ('2021', results_2021), ('2022', results_2022), ('2023', results_2023), ('2024', results_2024), ('2025', results_2025)]:
        print(f"{year:^10s} | {res['total_return']:>9.2f}% | {res['buy_hold_return']:>9.2f}% | "
              f"{res['excess_return']:>+9.2f}%p | {res['sharpe_ratio']:>7.2f} | "
              f"{res['max_drawdown']:>7.2f}% | {res['total_trades']:>5d}회 | {res['win_rate']:>5.1f}%")

    # v34 대비 개선 여부
    print(f"\n{'='*70}")
    print(f"  v34 vs v35 비교 (2025년)")
    print(f"{'='*70}")
    print(f"v34 수익률: +8.43%")
    print(f"v35 수익률: {results_2025['total_return']:+.2f}%")
    improvement = results_2025['total_return'] - 8.43
    print(f"개선: {improvement:+.2f}%p")

    if results_2025['total_return'] >= 15.0:
        print(f"\n✅ 목표 달성! (2025년 +15% 이상)")
    else:
        needed = 15.0 - results_2025['total_return']
        print(f"\n⚠️  목표 미달성 (추가 +{needed:.2f}%p 필요)")
        print(f"다음 단계: Optuna 최적화 (500 trials)")

    # 결과 저장
    output = {
        'version': 'v35',
        'optimization_status': 'before_optuna',
        'backtest_date': datetime.now().isoformat(),
        'config': config,
        'results': {
            '2020': {k: v for k, v in results_2020.items() if k not in ['trades', 'equity_curve']},
            '2021': {k: v for k, v in results_2021.items() if k not in ['trades', 'equity_curve']},
            '2022': {k: v for k, v in results_2022.items() if k not in ['trades', 'equity_curve']},
            '2023': {k: v for k, v in results_2023.items() if k not in ['trades', 'equity_curve']},
            '2024': {k: v for k, v in results_2024.items() if k not in ['trades', 'equity_curve']},
            '2025': {k: v for k, v in results_2025.items() if k not in ['trades', 'equity_curve']}
        }
    }

    with open('backtest_results_before_optuna.json', 'w') as f:
        json.dump(output, f, indent=2, default=str)

    print(f"\n결과 저장: backtest_results_before_optuna.json")
    print(f"\n백테스팅 완료!")
