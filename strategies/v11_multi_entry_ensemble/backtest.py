#!/usr/bin/env python3
"""
v11 Multi-Entry Ensemble 백테스팅 스크립트
"""

import sys
sys.path.append('../..')

import json
import pandas as pd
from datetime import datetime
from typing import Dict, List

from core.data_loader import DataLoader
from core.market_analyzer import MarketAnalyzer
from strategy import V11Strategy


class V11Backtester:
    """v11 전략 백테스터"""

    def __init__(self, config: dict):
        self.config = config
        self.strategy = V11Strategy(config)

        self.initial_capital = config['initial_capital']
        self.fee_rate = config['fee_rate']
        self.slippage = config['slippage']

        # 상태 변수
        self.cash = self.initial_capital
        self.btc_balance = 0.0
        self.position_entry_price = 0.0
        self.position_highest_price = 0.0
        self.position_entry_idx = 0
        self.position_entry_reason = ''
        self.position_entry_regime = ''

        # 거래 기록
        self.trades = []
        self.equity_curve = []

    def run(self, df: pd.DataFrame) -> Dict:
        """
        백테스팅 실행

        Args:
            df: 지표가 추가된 데이터프레임

        Returns:
            결과 딕셔너리
        """
        self._reset()

        for i in range(30, len(df)):
            row = df.iloc[i]
            timestamp = row['timestamp']
            close = row['close']

            # 현재 equity 계산
            current_equity = self.cash + self.btc_balance * close
            self.equity_curve.append({
                'timestamp': timestamp,
                'equity': current_equity,
                'close': close,
                'position': self.btc_balance
            })

            # 포지션 보유 중인 경우
            if self.btc_balance > 0:
                # 최고가 업데이트
                if close > self.position_highest_price:
                    self.position_highest_price = close

                # 청산 신호 체크
                exit_signal = self.strategy.check_exit(
                    df, i,
                    self.position_entry_price,
                    self.position_highest_price,
                    self.position_entry_reason
                )

                if exit_signal:
                    self._execute_sell(i, row, exit_signal['reason'])
                    continue

            # 포지션 없는 경우 진입 신호 체크
            else:
                entry_signal = self.strategy.check_entry(df, i)

                if entry_signal:
                    self._execute_buy(i, row, entry_signal)
                    continue

        # 마지막 날 포지션 정리
        if self.btc_balance > 0:
            last_row = df.iloc[-1]
            self._execute_sell(len(df)-1, last_row, 'FINAL_EXIT')

        # 성과 계산
        results = self._calculate_results(df)

        return results

    def _execute_buy(self, i: int, row: pd.Series, signal: Dict):
        """매수 실행"""
        timestamp = row['timestamp']
        price = row['close']

        # Slippage 적용
        effective_price = price * (1 + self.slippage)

        # 매수 금액
        buy_amount = self.cash * signal['fraction']

        # 수수료
        fee = buy_amount * self.fee_rate

        # BTC 매수
        btc_bought = (buy_amount - fee) / effective_price

        # 상태 업데이트
        self.btc_balance += btc_bought
        self.cash -= buy_amount
        self.position_entry_price = effective_price
        self.position_highest_price = effective_price
        self.position_entry_idx = i
        self.position_entry_reason = signal['reason']
        self.position_entry_regime = self.strategy.get_regime(pd.DataFrame([row]), 0)

        # 거래 기록
        self.trades.append({
            'timestamp': timestamp,
            'action': 'BUY',
            'price': effective_price,
            'btc': btc_bought,
            'krw': buy_amount,
            'fee': fee,
            'reason': signal['reason'],
            'regime': self.position_entry_regime
        })

    def _execute_sell(self, i: int, row: pd.Series, reason: str):
        """매도 실행"""
        timestamp = row['timestamp']
        price = row['close']

        # Slippage 적용
        effective_price = price * (1 - self.slippage)

        # 매도 금액
        sell_amount = self.btc_balance * effective_price

        # 수수료
        fee = sell_amount * self.fee_rate

        # 손익 계산
        profit_pct = (effective_price - self.position_entry_price) / self.position_entry_price

        # 상태 업데이트
        self.cash += (sell_amount - fee)
        btc_sold = self.btc_balance
        self.btc_balance = 0.0

        # 거래 기록
        self.trades.append({
            'timestamp': timestamp,
            'action': 'SELL',
            'price': effective_price,
            'btc': btc_sold,
            'krw': sell_amount,
            'fee': fee,
            'reason': reason,
            'profit_pct': profit_pct,
            'entry_price': self.position_entry_price,
            'entry_reason': self.position_entry_reason,
            'entry_regime': self.position_entry_regime,
            'hold_days': i - self.position_entry_idx
        })

        # 포지션 리셋
        self.position_entry_price = 0.0
        self.position_highest_price = 0.0
        self.position_entry_idx = 0
        self.position_entry_reason = ''
        self.position_entry_regime = ''

    def _reset(self):
        """상태 초기화"""
        self.cash = self.initial_capital
        self.btc_balance = 0.0
        self.position_entry_price = 0.0
        self.position_highest_price = 0.0
        self.position_entry_idx = 0
        self.position_entry_reason = ''
        self.position_entry_regime = ''
        self.trades = []
        self.equity_curve = []

    def _calculate_results(self, df: pd.DataFrame) -> Dict:
        """성과 계산"""
        final_equity = self.cash
        total_return = ((final_equity - self.initial_capital) / self.initial_capital) * 100

        # 거래 통계
        completed_trades = [t for t in self.trades if t['action'] == 'SELL' and 'profit_pct' in t]
        total_trades = len(completed_trades)

        if total_trades > 0:
            wins = [t for t in completed_trades if t['profit_pct'] > 0]
            losses = [t for t in completed_trades if t['profit_pct'] <= 0]

            win_rate = len(wins) / total_trades
            avg_win = sum(t['profit_pct'] for t in wins) / len(wins) if wins else 0
            avg_loss = sum(t['profit_pct'] for t in losses) / len(losses) if losses else 0
            profit_factor = abs(sum(t['profit_pct'] for t in wins) / sum(t['profit_pct'] for t in losses)) if losses and sum(t['profit_pct'] for t in losses) != 0 else 0
        else:
            win_rate = 0
            avg_win = 0
            avg_loss = 0
            profit_factor = 0

        # Sharpe Ratio (간단한 근사)
        equity_df = pd.DataFrame(self.equity_curve)
        if len(equity_df) > 1:
            returns = equity_df['equity'].pct_change().dropna()
            sharpe = (returns.mean() / returns.std()) * (252 ** 0.5) if returns.std() != 0 else 0
        else:
            sharpe = 0

        # Max Drawdown
        equity_series = equity_df['equity']
        running_max = equity_series.cummax()
        drawdown = (equity_series - running_max) / running_max
        max_drawdown = abs(drawdown.min()) * 100 if len(drawdown) > 0 else 0

        # Buy & Hold 계산
        start_price = df.iloc[30]['close']
        end_price = df.iloc[-1]['close']
        buyhold_return = ((end_price - start_price) / start_price) * 100

        return {
            'initial_capital': self.initial_capital,
            'final_equity': final_equity,
            'total_return': total_return,
            'buyhold_return': buyhold_return,
            'excess_return': total_return - buyhold_return,
            'sharpe_ratio': sharpe,
            'max_drawdown': max_drawdown,
            'total_trades': total_trades,
            'win_rate': win_rate,
            'avg_win': avg_win,
            'avg_loss': avg_loss,
            'profit_factor': profit_factor,
            'trades': completed_trades,
            'equity_curve': self.equity_curve
        }


if __name__ == '__main__':
    """메인 실행"""
    print("=" * 80)
    print("v11 Multi-Entry Ensemble Backtest")
    print("=" * 80)

    # Config 로드
    with open('config.json') as f:
        config = json.load(f)

    # 2024년 백테스팅
    print("\n[Phase 1] 2024 Backtest (Target: 350%+)")
    print("=" * 80)

    with DataLoader('../../upbit_bitcoin.db') as loader:
        df_2024 = loader.load_timeframe('day', start_date='2024-01-01', end_date='2024-12-30')

    df_2024 = MarketAnalyzer.add_indicators(df_2024, indicators=['ema', 'rsi', 'macd', 'adx'])
    df_2024 = df_2024.rename(columns={'ema_12': 'ema12', 'ema_26': 'ema26'})

    backtester = V11Backtester(config)
    results_2024 = backtester.run(df_2024)

    # 결과 출력
    print(f"\n{'='*80}")
    print(f"2024 Backtest Results")
    print(f"{'='*80}")
    print(f"초기 자본: {results_2024['initial_capital']:>15,.0f}원")
    print(f"최종 자본: {results_2024['final_equity']:>15,.0f}원")
    print(f"수익률:    {results_2024['total_return']:>14.2f}%")
    print(f"Buy&Hold:  {results_2024['buyhold_return']:>14.2f}%")
    print(f"초과 수익: {results_2024['excess_return']:>+14.2f}%p")
    print(f"\nSharpe Ratio:  {results_2024['sharpe_ratio']:>10.2f}")
    print(f"Max Drawdown:  {results_2024['max_drawdown']:>10.2f}%")
    print(f"\n총 거래:       {results_2024['total_trades']:>10d}회")
    print(f"승률:          {results_2024['win_rate']:>10.1%}")
    print(f"평균 수익:     {results_2024['avg_win']:>+10.2%}")
    print(f"평균 손실:     {results_2024['avg_loss']:>+10.2%}")
    print(f"Profit Factor: {results_2024['profit_factor']:>10.2f}")
    print(f"{'='*80}")

    # 거래 내역
    print(f"\n거래 내역 (최근 10개):")
    print(f"  {'날짜':20s} {'행동':6s} {'가격':>15s} {'수익률':>10s} {'이유':30s}")
    print(f"  {'-'*90}")

    for trade in results_2024['trades'][-10:]:
        date_str = str(trade['timestamp'])[:10]
        action = trade['action']
        price = f"{trade['price']:,.0f}"
        profit = f"{trade.get('profit_pct', 0)*100:+.2f}%" if action == 'SELL' else '-'
        reason = trade.get('entry_reason', trade['reason']) if action == 'SELL' else trade['reason']

        print(f"  {date_str:20s} {action:6s} {price:>15s} {profit:>10s} {reason:30s}")

    # 결과 저장
    results_json = {
        'version': 'v11',
        'timestamp': datetime.now().isoformat(),
        'config': config,
        'results_2024': {
            'total_return': results_2024['total_return'],
            'buyhold_return': results_2024['buyhold_return'],
            'excess_return': results_2024['excess_return'],
            'sharpe_ratio': results_2024['sharpe_ratio'],
            'max_drawdown': results_2024['max_drawdown'],
            'total_trades': results_2024['total_trades'],
            'win_rate': results_2024['win_rate'],
            'profit_factor': results_2024['profit_factor']
        }
    }

    with open('backtest_results_2024.json', 'w', encoding='utf-8') as f:
        json.dump(results_json, f, indent=2, ensure_ascii=False, default=str)

    print(f"\n✅ 결과 저장: backtest_results_2024.json")
    print("=" * 80)
