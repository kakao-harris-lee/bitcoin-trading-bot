#!/usr/bin/env python3
"""
v36 Multi-Timeframe Backtesting Script
Day + Minute240 + Minute60 통합 백테스팅

학습 기간: 2020-2024
테스트 기간: 2025
목표: 2025년 +25-30%
"""

import sys
sys.path.append('../..')

from core.data_loader import DataLoader
from core.market_analyzer import MarketAnalyzer
from strategies.v35_optimized.strategy import V35OptimizedStrategy
from strategies.v36_multi_timeframe.strategies.minute240_strategy import Minute240SwingStrategy
from strategies.v36_multi_timeframe.strategies.minute60_strategy import Minute60ScalpingStrategy
from strategies.v36_multi_timeframe.ensemble_manager import EnsembleManager

import pandas as pd
import numpy as np
import json
from datetime import datetime
from typing import Dict, List, Tuple


class MultiTimeframeBacktester:
    """Multi-Timeframe 백테스팅 엔진"""

    def __init__(self, config: Dict):
        self.config = config
        self.initial_capital = config['backtesting']['initial_capital']
        self.fee_rate = config['backtesting']['fee_rate']
        self.slippage = config['backtesting']['slippage']

        # 자본 배분
        self.capital_allocation = {
            'day': config['capital_allocation']['day_capital'],
            'minute240': config['capital_allocation']['m240_capital'],
            'minute60': config['capital_allocation']['m60_capital']
        }

        # 타임프레임별 자본
        self.capital = {
            'day': self.initial_capital * self.capital_allocation['day'],
            'minute240': self.initial_capital * self.capital_allocation['minute240'],
            'minute60': self.initial_capital * self.capital_allocation['minute60']
        }

        # 포지션
        self.positions = {
            'day': 0.0,
            'minute240': 0.0,
            'minute60': 0.0
        }

        # 거래 기록
        self.trades = {
            'day': [],
            'minute240': [],
            'minute60': []
        }

        # 손익 곡선
        self.equity_curve = []

    def run(self, day_df: pd.DataFrame, m240_df: pd.DataFrame, m60_df: pd.DataFrame,
            v35_strategy: V35OptimizedStrategy, m240_strategy: Minute240SwingStrategy,
            m60_strategy: Minute60ScalpingStrategy, ensemble_manager: EnsembleManager) -> Dict:
        """백테스팅 실행"""

        # 초기화
        self.capital = {
            'day': self.initial_capital * self.capital_allocation['day'],
            'minute240': self.initial_capital * self.capital_allocation['minute240'],
            'minute60': self.initial_capital * self.capital_allocation['minute60']
        }
        self.positions = {'day': 0.0, 'minute240': 0.0, 'minute60': 0.0}
        self.trades = {'day': [], 'minute240': [], 'minute60': []}
        self.equity_curve = []

        # Day 타임프레임 기준으로 순회
        for day_idx in range(30, len(day_df)):
            day_row = day_df.iloc[day_idx]
            day_time = day_row.name
            prev_day_row = day_df.iloc[day_idx-1] if day_idx > 0 else None

            # Day 시장 상태 분류
            day_market_state = v35_strategy.classifier.classify_market_state(day_row, prev_day_row)

            # Debug: 시장 상태 분포 확인
            if day_idx == 50:  # 50일차에 한 번만 출력
                print(f"  [DEBUG] Day market state sample: {day_market_state}")

            # Day 전략 시그널
            day_signal = v35_strategy.execute(day_df, day_idx)

            # EnsembleManager에 Day 상태 전달
            ensemble_manager.set_day_market_state(day_market_state)
            m240_strategy.set_day_filter(day_market_state)
            m60_strategy.set_day_filter(day_market_state)

            # M240, M60 해당 시점 찾기
            m240_idx = self._find_matching_index(m240_df, day_time)
            m60_idx = self._find_matching_index(m60_df, day_time)

            # M240, M60 시그널
            m240_signal = {'action': 'hold'}
            m60_signal = {'action': 'hold'}

            if m240_idx is not None:
                m240_signal = m240_strategy.execute(m240_df, m240_idx)
                # Debug: 첫 10일간 로그
                if day_idx < 40 and m240_signal['action'] != 'hold':
                    print(f"  [DEBUG] Day={day_time} | M240_signal={m240_signal['action']} | Day_state={day_market_state}")

            if m60_idx is not None:
                m60_signal = m60_strategy.execute(m60_df, m60_idx)
                if day_idx < 40 and m60_signal['action'] != 'hold':
                    print(f"  [DEBUG] Day={day_time} | M60_signal={m60_signal['action']} | Day_state={day_market_state}")

            # EnsembleManager로 시그널 통합
            actions = ensemble_manager.process_signals(day_signal, m240_signal, m60_signal)

            # 실행
            for action in actions:
                tf = action['timeframe']
                act = action['action']

                if tf == 'day':
                    price = day_row['close']
                    self._execute_trade(tf, act, price, day_time, action)
                elif tf == 'minute240' and m240_idx is not None:
                    price = m240_df.iloc[m240_idx]['close']
                    self._execute_trade(tf, act, price, day_time, action)
                elif tf == 'minute60' and m60_idx is not None:
                    price = m60_df.iloc[m60_idx]['close']
                    self._execute_trade(tf, act, price, day_time, action)

            # 포지션 상태 업데이트
            for tf in ['day', 'minute240', 'minute60']:
                in_pos = self.positions[tf] > 0
                if in_pos:
                    price = day_row['close'] if tf == 'day' else (
                        m240_df.iloc[m240_idx]['close'] if tf == 'minute240' and m240_idx is not None else
                        m60_df.iloc[m60_idx]['close'] if tf == 'minute60' and m60_idx is not None else 0
                    )
                    ensemble_manager.update_position(tf, 'buy', entry_price=price, shares=self.positions[tf])
                else:
                    ensemble_manager.update_position(tf, 'sell')

            # Equity 계산
            total_equity = sum(self.capital.values())
            for tf in ['day', 'minute240', 'minute60']:
                if self.positions[tf] > 0:
                    if tf == 'day':
                        total_equity += self.positions[tf] * day_row['close']
                    elif tf == 'minute240' and m240_idx is not None:
                        total_equity += self.positions[tf] * m240_df.iloc[m240_idx]['close']
                    elif tf == 'minute60' and m60_idx is not None:
                        total_equity += self.positions[tf] * m60_df.iloc[m60_idx]['close']

            self.equity_curve.append({
                'time': day_time,
                'equity': total_equity
            })

        # 마지막 포지션 정리
        final_price = day_df.iloc[-1]['close']
        for tf in ['day', 'minute240', 'minute60']:
            if self.positions[tf] > 0:
                self.capital[tf] += self.positions[tf] * final_price * (1 - self.slippage - self.fee_rate)
                self.positions[tf] = 0

        return self._calculate_metrics(day_df)

    def _execute_trade(self, timeframe: str, action: str, price: float, timestamp, action_dict: Dict):
        """거래 실행"""
        if action == 'buy' and self.positions[timeframe] == 0:
            fraction = action_dict.get('fraction', 0.5)
            available_capital = self.capital[timeframe]
            buy_amount = available_capital * fraction
            buy_price = price * (1 + self.slippage)
            fee = buy_amount * self.fee_rate
            shares = (buy_amount - fee) / buy_price

            if shares > 0:
                self.positions[timeframe] = shares
                self.capital[timeframe] -= buy_amount
                self.trades[timeframe].append({
                    'type': 'buy',
                    'time': timestamp,
                    'price': buy_price,
                    'shares': shares,
                    'reason': action_dict.get('reason', 'UNKNOWN')
                })

        elif action == 'sell' and self.positions[timeframe] > 0:
            sell_fraction = action_dict.get('fraction', 1.0)
            sell_shares = self.positions[timeframe] * sell_fraction
            sell_price = price * (1 - self.slippage)
            proceeds = sell_shares * sell_price * (1 - self.fee_rate)

            self.capital[timeframe] += proceeds
            self.positions[timeframe] -= sell_shares

            self.trades[timeframe].append({
                'type': 'sell',
                'time': timestamp,
                'price': sell_price,
                'shares': sell_shares,
                'fraction': sell_fraction,
                'reason': action_dict.get('reason', 'UNKNOWN')
            })

    def _find_matching_index(self, df: pd.DataFrame, target_time) -> int:
        """Day 타임스탬프에 해당하는 인덱스 찾기 (가장 가까운 이전 시점)"""
        try:
            # target_time 이전의 가장 가까운 인덱스
            mask = df.index <= target_time
            if mask.any():
                matching_indices = mask[mask].index
                if len(matching_indices) > 0:
                    # DataFrame의 integer position 반환
                    return df.index.get_loc(matching_indices[-1])
            return None
        except Exception as e:
            return None

    def _get_market_state(self, strategy: V35OptimizedStrategy) -> str:
        """v35 전략에서 현재 시장 상태 가져오기"""
        try:
            return strategy.classifier.current_state if hasattr(strategy.classifier, 'current_state') else 'UNKNOWN'
        except:
            return 'UNKNOWN'

    def _calculate_metrics(self, day_df: pd.DataFrame) -> Dict:
        """성과 지표 계산"""
        # 최종 자본
        final_capital = sum(self.capital.values())
        total_return = (final_capital - self.initial_capital) / self.initial_capital * 100

        # Buy&Hold
        start_price = day_df.iloc[30]['close']
        end_price = day_df.iloc[-1]['close']
        buy_hold_return = (end_price - start_price) / start_price * 100

        # 거래 분석
        all_trades = []
        for tf in ['day', 'minute240', 'minute60']:
            all_trades.extend(self.trades[tf])

        total_trades = len([t for t in all_trades if t['type'] == 'buy'])

        # Sharpe Ratio
        equity_series = pd.Series([e['equity'] for e in self.equity_curve])
        returns = equity_series.pct_change().dropna()
        sharpe_ratio = np.sqrt(252) * returns.mean() / returns.std() if returns.std() > 0 else 0

        # MDD
        running_max = equity_series.expanding().max()
        drawdown = (equity_series - running_max) / running_max * 100
        max_drawdown = drawdown.min()

        # 타임프레임별 성과
        tf_metrics = {}
        for tf in ['day', 'minute240', 'minute60']:
            buy_trades = [t for t in self.trades[tf] if t['type'] == 'buy']
            sell_trades = [t for t in self.trades[tf] if t['type'] == 'sell']

            tf_capital = self.capital[tf]
            initial_tf_capital = self.initial_capital * self.capital_allocation[tf]
            tf_return = (tf_capital - initial_tf_capital) / initial_tf_capital * 100 if initial_tf_capital > 0 else 0

            tf_metrics[tf] = {
                'return': tf_return,
                'trades': len(buy_trades),
                'capital_contribution': (tf_capital - initial_tf_capital)
            }

        return {
            'initial_capital': self.initial_capital,
            'final_capital': final_capital,
            'total_return': total_return,
            'buy_hold_return': buy_hold_return,
            'excess_return': total_return - buy_hold_return,
            'total_trades': total_trades,
            'sharpe_ratio': sharpe_ratio,
            'max_drawdown': max_drawdown,
            'timeframe_metrics': tf_metrics
        }


def backtest_by_year(start_year: int, end_year: int, config: Dict) -> Dict:
    """연도별 백테스팅"""
    results = {}

    with DataLoader('../../upbit_bitcoin.db') as loader:
        for year in range(start_year, end_year + 1):
            print(f"\n{'='*70}")
            print(f"  백테스팅: {year}년")
            print(f"{'='*70}")

            start_date = f"{year}-01-01"
            end_date = f"{year}-12-31"

            # 데이터 로드
            day_df = loader.load_timeframe('day', start_date=start_date, end_date=end_date)
            m240_df = loader.load_timeframe('minute240', start_date=start_date, end_date=end_date)
            m60_df = loader.load_timeframe('minute60', start_date=start_date, end_date=end_date)

            # 지표 추가
            day_df = MarketAnalyzer.add_indicators(day_df, indicators=['sma', 'ema', 'rsi', 'macd', 'bb', 'atr', 'adx', 'mfi', 'roc', 'stoch'])
            m240_df = MarketAnalyzer.add_indicators(m240_df, indicators=['rsi', 'macd', 'bb', 'adx', 'atr'])
            m60_df = MarketAnalyzer.add_indicators(m60_df, indicators=['rsi', 'macd', 'bb', 'atr'])

            # 전략 초기화
            v35_config = {
                'market_classifier': config.get('market_classifier', {}),
                'entry_conditions': config.get('entry_conditions', {}),
                'exit_conditions': config.get('exit_conditions', {}),
                'position_sizing': config.get('position_sizing', {}),
                'sideways_strategies': config.get('sideways_strategies', {})
            }
            v35_strategy = V35OptimizedStrategy(v35_config)

            m240_strategy = Minute240SwingStrategy(config.get('minute240_strategy', {}))
            m60_strategy = Minute60ScalpingStrategy(config.get('minute60_strategy', {}))

            ensemble_manager = EnsembleManager(config['capital_allocation'])

            # 백테스팅
            backtester = MultiTimeframeBacktester(config)
            year_results = backtester.run(day_df, m240_df, m60_df, v35_strategy, m240_strategy, m60_strategy, ensemble_manager)

            results[str(year)] = year_results

            # 출력
            print(f"  총 수익률: {year_results['total_return']:.2f}%")
            print(f"  Buy&Hold: {year_results['buy_hold_return']:.2f}%")
            print(f"  초과 수익: {year_results['excess_return']:.2f}%p")
            print(f"  Sharpe Ratio: {year_results['sharpe_ratio']:.2f}")
            print(f"  Max Drawdown: {year_results['max_drawdown']:.2f}%")
            print(f"  총 거래: {year_results['total_trades']}회")

            print(f"\n  타임프레임별 성과:")
            for tf, metrics in year_results['timeframe_metrics'].items():
                print(f"    {tf:10s}: {metrics['return']:>8.2f}% ({metrics['trades']:>3d} trades)")

    return results


if __name__ == '__main__':
    print("="*70)
    print("  v36 Multi-Timeframe Backtesting")
    print("="*70)

    # Config 로드
    with open('config.json', 'r') as f:
        config = json.load(f)

    # v35 config 추가 (Day 전략용)
    v35_config_path = '../v35_optimized/config.json'
    with open(v35_config_path, 'r') as f:
        v35_config = json.load(f)
        config['market_classifier'] = v35_config.get('market_classifier', {})
        config['entry_conditions'] = v35_config.get('entry_conditions', {})
        config['exit_conditions'] = v35_config.get('exit_conditions', {})
        config['position_sizing'] = v35_config.get('position_sizing', {})
        config['sideways_strategies'] = v35_config.get('sideways_strategies', {})

    # 연도별 백테스팅
    all_results = backtest_by_year(2020, 2025, config)

    # 결과 저장
    output = {
        'version': 'v36',
        'strategy_name': 'multi_timeframe',
        'backtest_date': datetime.now().isoformat(),
        'config': config,
        'results': all_results
    }

    with open('backtest_results.json', 'w') as f:
        json.dump(output, f, indent=2, default=str)

    print("\n" + "="*70)
    print("  백테스팅 완료!")
    print("  결과 저장: backtest_results.json")
    print("="*70)
