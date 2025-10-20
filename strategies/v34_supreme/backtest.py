#!/usr/bin/env python3
"""
v34 Supreme Backtesting Script
2020-2024 학습, 2025 검증
"""

import sys
sys.path.append('../..')

from core.data_loader import DataLoader
from core.market_analyzer import MarketAnalyzer
from market_classifier_v34 import MarketClassifierV34
from strategy import V34SupremeStrategy
import pandas as pd
import numpy as np
import json
from datetime import datetime
from typing import Dict


class SimpleBacktester:
    """간단한 백테스팅 엔진"""

    def __init__(self, initial_capital: float, fee_rate: float = 0.0005, slippage: float = 0.0002):
        self.initial_capital = initial_capital
        self.capital = initial_capital
        self.fee_rate = fee_rate
        self.slippage = slippage
        self.position = 0.0
        self.trades = []
        self.equity_curve = []

    def run(self, df: pd.DataFrame, strategy: V34SupremeStrategy) -> Dict:
        """백테스팅 실행"""
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
                        'amount': buy_amount,
                        'fee': fee,
                        'reason': signal.get('reason', 'UNKNOWN')
                    })

            # Sell
            elif signal['action'] == 'sell' and self.position > 0:
                sell_price = row['close'] * (1 - self.slippage)
                sell_amount = self.position * sell_price
                fee = sell_amount * self.fee_rate
                proceeds = sell_amount - fee

                self.capital += proceeds
                self.trades.append({
                    'type': 'sell',
                    'time': row.name,
                    'price': sell_price,
                    'shares': self.position,
                    'amount': sell_amount,
                    'fee': fee,
                    'reason': signal.get('reason', 'UNKNOWN')
                })
                self.position = 0.0

            # Equity curve
            current_equity = self.capital
            if self.position > 0:
                current_equity += self.position * row['close']

            self.equity_curve.append({
                'time': row.name,
                'equity': current_equity
            })

        # 마지막 포지션 정리
        if self.position > 0:
            last_price = df.iloc[-1]['close']
            self.capital += self.position * last_price * (1 - self.slippage - self.fee_rate)
            self.position = 0.0

        return self._calculate_metrics(df)

    def _calculate_metrics(self, df: pd.DataFrame) -> Dict:
        """성과 지표 계산"""
        final_capital = self.capital
        total_return = (final_capital - self.initial_capital) / self.initial_capital * 100

        # 거래 분석
        buy_trades = [t for t in self.trades if t['type'] == 'buy']
        sell_trades = [t for t in self.trades if t['type'] == 'sell']

        # 거래 쌍 매칭
        profits = []
        for i in range(min(len(buy_trades), len(sell_trades))):
            buy = buy_trades[i]
            sell = sell_trades[i]
            profit_pct = (sell['price'] - buy['price']) / buy['price'] * 100
            profits.append(profit_pct)

        wins = [p for p in profits if p > 0]
        losses = [p for p in profits if p <= 0]

        # Equity curve 분석
        equity_series = pd.Series([e['equity'] for e in self.equity_curve])
        returns = equity_series.pct_change().dropna()

        # Sharpe Ratio
        if len(returns) > 0 and returns.std() > 0:
            sharpe = returns.mean() / returns.std() * np.sqrt(252)
        else:
            sharpe = 0

        # Max Drawdown
        cummax = equity_series.cummax()
        drawdown = (equity_series - cummax) / cummax * 100
        max_drawdown = drawdown.min()

        # Buy&Hold 계산
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


def run_backtest(year: str, config: Dict):
    """연도별 백테스팅 실행"""
    print(f"\n{'='*70}")
    print(f"  {year}년 백테스팅")
    print(f"{'='*70}")

    # 데이터 로드
    with DataLoader('../../upbit_bitcoin.db') as loader:
        df = loader.load_timeframe(
            config['timeframe'],
            start_date=f'{year}-01-01',
            end_date=f'{year}-12-31' if year != '2025' else '2025-10-17'
        )

    print(f"데이터: {len(df)}개 캔들")
    print(f"기간: {df.iloc[0].name} ~ {df.iloc[-1].name}")

    # 지표 추가
    df = MarketAnalyzer.add_indicators(df, indicators=['rsi', 'macd', 'mfi', 'adx', 'atr'])

    # 시장 분류
    classifier = MarketClassifierV34()
    df = classifier.classify_dataframe(df)

    # 시장 상태 분포
    distribution = classifier.get_market_distribution(df)
    print("\n[시장 상태 분포]")
    for state, pct in sorted(distribution.items(), key=lambda x: x[1], reverse=True):
        count = int(len(df) * pct / 100)
        print(f"  {state:20s}: {count:3d}일 ({pct:5.1f}%)")

    # 백테스팅
    strategy = V34SupremeStrategy(config)
    backtester = SimpleBacktester(
        initial_capital=config['backtesting']['initial_capital'],
        fee_rate=config['backtesting']['fee_rate'],
        slippage=config['backtesting']['slippage']
    )

    results = backtester.run(df, strategy)

    # 결과 출력
    print(f"\n{'='*70}")
    print(f"  백테스팅 결과 ({year})")
    print(f"{'='*70}")
    print(f"\n[수익률]")
    print(f"  초기 자본: {results['initial_capital']:,.0f}원")
    print(f"  최종 자본: {results['final_capital']:,.0f}원")
    print(f"  절대 수익: {results['final_capital'] - results['initial_capital']:+,.0f}원")
    print(f"  수익률: {results['total_return']:+.2f}%")
    print(f"\n[vs Buy&Hold]")
    print(f"  Buy&Hold: {results['buy_hold_return']:+.2f}%")
    print(f"  초과 수익: {results['excess_return']:+.2f}%p")
    print(f"\n[리스크 지표]")
    print(f"  Sharpe Ratio: {results['sharpe_ratio']:.2f}")
    print(f"  Max Drawdown: {results['max_drawdown']:.2f}%")
    print(f"  Profit Factor: {results['profit_factor']:.2f}")
    print(f"\n[거래 통계]")
    print(f"  총 거래: {results['total_trades']}회")
    print(f"  승리: {results['wins']}회 | 패배: {results['losses']}회")
    print(f"  승률: {results['win_rate']:.1f}%")
    print(f"  평균 수익: {results['avg_profit']:+.2f}%")
    print(f"  평균 손실: {results['avg_loss']:+.2f}%")

    # 상세 거래 내역 (처음 10개)
    print(f"\n[거래 내역 (처음 10개)]")
    for i, trade in enumerate(results['trades'][:10]):
        print(f"  {i+1:2d}. {trade['time']} | {trade['type']:4s} | {trade['price']:,.0f}원 | {trade['reason']}")

    return results


if __name__ == '__main__':
    # Config 로드
    with open('config.json') as f:
        config = json.load(f)

    print("="*70)
    print("  v34 Supreme - Multi-Year Backtesting")
    print("="*70)
    print(f"Strategy: {config['strategy_name']} v{config['version']}")
    print(f"Timeframe: {config['timeframe']}")
    print(f"Train Period: {config['backtesting']['train_period']}")
    print(f"Test Period: {config['backtesting']['test_period']}")

    # 2020-2024 백테스팅 (학습 기간)
    all_results = {}
    for year in ['2020', '2021', '2022', '2023', '2024']:
        results = run_backtest(year, config)
        all_results[year] = results

    # 2025 백테스팅 (검증 기간)
    print(f"\n{'='*70}")
    print(f"  ⭐ 2025 검증 백테스팅 (Out-of-Sample)")
    print(f"{'='*70}")
    results_2025 = run_backtest('2025', config)
    all_results['2025'] = results_2025

    # 종합 요약
    print(f"\n{'='*70}")
    print(f"  종합 요약 (2020-2025)")
    print(f"{'='*70}")
    print(f"\n{'연도':^10s} | {'수익률':^10s} | {'B&H':^10s} | {'초과':^10s} | {'Sharpe':^8s} | {'MDD':^8s} | {'거래':^6s} | {'승률':^6s}")
    print(f"{'-'*10}|{'-'*12}|{'-'*12}|{'-'*12}|{'-'*10}|{'-'*10}|{'-'*8}|{'-'*8}")

    for year, res in all_results.items():
        print(f"{year:^10s} | {res['total_return']:>9.2f}% | {res['buy_hold_return']:>9.2f}% | "
              f"{res['excess_return']:>+9.2f}%p | {res['sharpe_ratio']:>7.2f} | "
              f"{res['max_drawdown']:>7.2f}% | {res['total_trades']:>5d}회 | {res['win_rate']:>5.1f}%")

    # 결과 저장
    output = {
        'version': 'v34',
        'strategy_name': 'supreme',
        'backtest_date': datetime.now().isoformat(),
        'config': config,
        'results': {
            year: {
                'total_return': res['total_return'],
                'buy_hold_return': res['buy_hold_return'],
                'excess_return': res['excess_return'],
                'sharpe_ratio': res['sharpe_ratio'],
                'max_drawdown': res['max_drawdown'],
                'total_trades': res['total_trades'],
                'win_rate': res['win_rate']
            }
            for year, res in all_results.items()
        }
    }

    with open('backtest_results.json', 'w') as f:
        json.dump(output, f, indent=2)

    print(f"\n결과 저장: backtest_results.json")
    print(f"\n백테스팅 완료!")
