#!/usr/bin/env python3
"""
v-a-06 Backtesting with Bear Market Filter
===========================================
v37 Exit + Bear Market Sideways Block
"""

import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

import json
import pandas as pd
import numpy as np
from datetime import datetime

from core.data_loader import DataLoader
from core.market_analyzer import MarketAnalyzer


class V37ExitManager:
    """v37 스타일 Exit 관리자"""

    def __init__(self, config: dict):
        self.config = config

    def check_exit(
        self,
        strategy: str,
        entry_price: float,
        entry_time: pd.Timestamp,
        current_row: pd.Series,
        prev_row: pd.Series,
        highest_price: float,
        hold_days: int
    ) -> dict:
        """
        전략별 Exit 조건 체크

        Returns:
            {'should_exit': bool, 'reason': str, 'fraction': float}
        """
        current_price = current_row['close']
        profit = (current_price - entry_price) / entry_price

        if strategy == 'trend_following':
            return self._check_trend_exit(current_row, prev_row, profit, highest_price, hold_days)
        elif strategy == 'swing_trading':
            return self._check_swing_exit(current_row, prev_row, profit, highest_price, hold_days)
        elif strategy == 'sideways':
            return self._check_sideways_exit(current_row, prev_row, profit, highest_price, hold_days)
        elif strategy == 'defensive':
            return self._check_defensive_exit(current_row, prev_row, profit, highest_price, hold_days)
        else:
            return {'should_exit': False, 'reason': 'UNKNOWN_STRATEGY', 'fraction': 0}

    def _check_trend_exit(self, row, prev_row, profit, highest_price, hold_days):
        """Trend Following Exit (v37)"""
        macd = row.get('macd', 0)
        macd_signal = row.get('macd_signal', 0)
        prev_macd = prev_row.get('macd', 0)
        prev_signal = prev_row.get('macd_signal', 0)

        # 1. MACD 데드크로스 (최우선)
        dead_cross = (prev_macd >= prev_signal) and (macd < macd_signal)
        if dead_cross:
            return {'should_exit': True, 'reason': 'TREND_DEAD_CROSS', 'fraction': 1.0}

        # 2. Trailing Stop
        trailing_trigger = self.config.get('trend_trailing_trigger', 0.20)
        trailing_stop = self.config.get('trend_trailing_stop', -0.05)

        if profit >= trailing_trigger:
            current_price = row['close']
            drawdown_from_peak = (current_price - highest_price) / highest_price
            if drawdown_from_peak <= trailing_stop:
                return {'should_exit': True, 'reason': 'TREND_TRAILING_STOP', 'fraction': 1.0}

        # 3. Stop Loss
        stop_loss = self.config.get('trend_stop_loss', -0.08)
        if profit <= stop_loss:
            return {'should_exit': True, 'reason': 'TREND_STOP_LOSS', 'fraction': 1.0}

        # 4. Max Hold Days
        max_hold = self.config.get('trend_max_hold_days', 61)
        if hold_days >= max_hold:
            return {'should_exit': True, 'reason': 'TREND_TIMEOUT', 'fraction': 1.0}

        return {'should_exit': False, 'reason': 'TREND_HOLD', 'fraction': 0}

    def _check_swing_exit(self, row, prev_row, profit, highest_price, hold_days):
        """Swing Trading Exit (v37) - 2단계 TP"""
        tp1 = self.config.get('swing_tp_1', 0.085)
        tp2 = self.config.get('swing_tp_2', 0.148)
        stop_loss = self.config.get('swing_stop_loss', -0.034)
        max_hold = self.config.get('swing_max_hold_days', 26)

        # Take Profit (분할 청산은 단순화: 전량 청산)
        if profit >= tp2:
            return {'should_exit': True, 'reason': 'SWING_TP2', 'fraction': 1.0}
        if profit >= tp1:
            return {'should_exit': True, 'reason': 'SWING_TP1', 'fraction': 1.0}

        # Stop Loss
        if profit <= stop_loss:
            return {'should_exit': True, 'reason': 'SWING_STOP_LOSS', 'fraction': 1.0}

        # Timeout
        if hold_days >= max_hold:
            return {'should_exit': True, 'reason': 'SWING_TIMEOUT', 'fraction': 1.0}

        return {'should_exit': False, 'reason': 'SWING_HOLD', 'fraction': 0}

    def _check_sideways_exit(self, row, prev_row, profit, highest_price, hold_days):
        """Sideways Exit (v06) - v37 원본 (v-a-04와 동일)"""
        tp1 = self.config.get('sideways_tp_1', 0.02)  # 2%
        tp2 = self.config.get('sideways_tp_2', 0.04)  # 4%
        tp3 = self.config.get('sideways_tp_3', 0.06)  # 6%
        stop_loss = self.config.get('sideways_stop_loss', -0.02)
        max_hold = self.config.get('sideways_max_hold_days', 20)

        # Take Profit (분할 청산 단순화)
        if profit >= tp3:
            return {'should_exit': True, 'reason': 'SIDEWAYS_TP3', 'fraction': 1.0}
        if profit >= tp2:
            return {'should_exit': True, 'reason': 'SIDEWAYS_TP2', 'fraction': 1.0}
        if profit >= tp1:
            return {'should_exit': True, 'reason': 'SIDEWAYS_TP1', 'fraction': 1.0}

        # Stop Loss
        if profit <= stop_loss:
            return {'should_exit': True, 'reason': 'SIDEWAYS_STOP_LOSS', 'fraction': 1.0}

        # Timeout
        if hold_days >= max_hold:
            return {'should_exit': True, 'reason': 'SIDEWAYS_TIMEOUT', 'fraction': 1.0}

        return {'should_exit': False, 'reason': 'SIDEWAYS_HOLD', 'fraction': 0}

    def _check_defensive_exit(self, row, prev_row, profit, highest_price, hold_days):
        """Defensive Exit (v37)"""
        tp1 = self.config.get('defensive_take_profit_1', 0.05)
        tp2 = self.config.get('defensive_take_profit_2', 0.10)
        stop_loss = self.config.get('defensive_stop_loss', -0.05)
        max_hold = self.config.get('defensive_max_hold_days', 20)

        # Take Profit
        if profit >= tp2:
            return {'should_exit': True, 'reason': 'DEFENSIVE_TP2', 'fraction': 1.0}
        if profit >= tp1:
            return {'should_exit': True, 'reason': 'DEFENSIVE_TP1', 'fraction': 1.0}

        # Stop Loss
        if profit <= stop_loss:
            return {'should_exit': True, 'reason': 'DEFENSIVE_STOP_LOSS', 'fraction': 1.0}

        # Timeout
        if hold_days >= max_hold:
            return {'should_exit': True, 'reason': 'DEFENSIVE_TIMEOUT', 'fraction': 1.0}

        return {'should_exit': False, 'reason': 'DEFENSIVE_HOLD', 'fraction': 0}


def backtest_year(year: int, config: dict, db_path: Path) -> dict:
    """연도별 백테스팅"""

    print(f"\n{'='*70}")
    print(f"  {year}년 백테스팅")
    print(f"{'='*70}")

    # 시그널 로드
    signal_file = Path(__file__).parent / 'signals' / f'day_{year}_signals.json'
    if not signal_file.exists():
        print(f"  ❌ 시그널 파일 없음: {signal_file}")
        return None

    with open(signal_file, 'r') as f:
        signal_data = json.load(f)

    if signal_data['total_signals'] == 0:
        print(f"  ⚠️ 시그널 0개")
        return None

    # 시그널 DataFrame
    signals = []
    for sig in signal_data['signals']:
        signals.append({
            'timestamp': pd.to_datetime(sig['timestamp']),
            'entry_price': sig['entry_price'],
            'strategy': sig['strategy'],
            'market_state': sig['market_state'],
            'reason': sig['reason'],
            'fraction': sig['fraction']
        })
    signals_df = pd.DataFrame(signals)

    print(f"  시그널: {len(signals_df)}개")
    print(f"    Trend: {(signals_df['strategy']=='trend_following').sum()}개")
    print(f"    Swing: {(signals_df['strategy']=='swing_trading').sum()}개")
    print(f"    Sideways: {(signals_df['strategy']=='sideways').sum()}개")
    print(f"    Defensive: {(signals_df['strategy']=='defensive').sum()}개")

    # 가격 데이터 로드
    with DataLoader(str(db_path)) as loader:
        df = loader.load_timeframe('day', f'{year}-01-01', f'{year}-12-31')

    if df is None or len(df) == 0:
        print(f"  ❌ 가격 데이터 없음")
        return None

    df = MarketAnalyzer.add_indicators(df, ['macd'])

    # Exit Manager
    exit_manager = V37ExitManager(config)

    # 백테스팅
    initial_capital = 10_000_000
    capital = initial_capital
    fee_rate = 0.0005
    slippage = 0.0002
    total_fee = fee_rate + slippage

    trades = []

    for _, signal in signals_df.iterrows():
        entry_time = signal['timestamp']
        entry_price = signal['entry_price']
        strategy = signal['strategy']
        position_fraction = signal['fraction']

        # Entry 비용
        position_capital = capital * position_fraction
        entry_cost = position_capital * (1 + total_fee)
        btc_amount = position_capital / entry_price

        # Entry 이후 데이터
        future_df = df[df['timestamp'] > entry_time].sort_values('timestamp')

        if len(future_df) == 0:
            continue

        # Exit 추적
        highest_price = entry_price
        exit_price = None
        exit_time = None
        exit_reason = None
        hold_days = 0

        for idx, row in future_df.iterrows():
            hold_days += 1
            current_price = row['close']

            # 최고가 업데이트
            if current_price > highest_price:
                highest_price = current_price

            # Exit 체크
            prev_idx = future_df.index.get_loc(idx) - 1
            if prev_idx >= 0:
                prev_row = future_df.iloc[prev_idx]
            else:
                prev_row = row  # 첫날

            exit_check = exit_manager.check_exit(
                strategy=strategy,
                entry_price=entry_price,
                entry_time=entry_time,
                current_row=row,
                prev_row=prev_row,
                highest_price=highest_price,
                hold_days=hold_days
            )

            if exit_check['should_exit']:
                exit_price = current_price
                exit_time = row['timestamp']
                exit_reason = exit_check['reason']
                break

        # Exit 없으면 마지막 날 강제 청산
        if exit_price is None:
            last_row = future_df.iloc[-1]
            exit_price = last_row['close']
            exit_time = last_row['timestamp']
            exit_reason = 'FORCED_EXIT'
            hold_days = len(future_df)

        # 수익 계산
        exit_revenue = btc_amount * exit_price * (1 - total_fee)
        profit = exit_revenue - position_capital
        profit_pct = (profit / position_capital) * 100

        # 자본 업데이트
        capital += profit

        trades.append({
            'entry_time': entry_time,
            'entry_price': entry_price,
            'exit_time': exit_time,
            'exit_price': exit_price,
            'strategy': strategy,
            'hold_days': hold_days,
            'profit': profit,
            'profit_pct': profit_pct,
            'exit_reason': exit_reason,
            'capital_after': capital
        })

    # 결과 계산
    if len(trades) == 0:
        print(f"  ⚠️ 거래 0개")
        return None

    trades_df = pd.DataFrame(trades)

    total_return = ((capital - initial_capital) / initial_capital) * 100
    win_trades = trades_df[trades_df['profit'] > 0]
    win_rate = (len(win_trades) / len(trades_df)) * 100

    avg_profit = win_trades['profit_pct'].mean() if len(win_trades) > 0 else 0
    loss_trades = trades_df[trades_df['profit'] <= 0]
    avg_loss = loss_trades['profit_pct'].mean() if len(loss_trades) > 0 else 0

    # Buy&Hold
    buy_hold = ((df.iloc[-1]['close'] - df.iloc[0]['close']) / df.iloc[0]['close']) * 100

    print(f"\n  [성과]")
    print(f"    수익률: {total_return:.2f}%")
    print(f"    Buy&Hold: {buy_hold:.2f}%")
    print(f"    초과수익: {total_return - buy_hold:+.2f}%p")
    print(f"\n  [거래]")
    print(f"    총 거래: {len(trades_df)}회")
    print(f"    승률: {win_rate:.1f}%")
    print(f"    평균 익절: {avg_profit:.2f}%")
    print(f"    평균 손절: {avg_loss:.2f}%")

    return {
        'year': year,
        'total_return': total_return,
        'buy_hold': buy_hold,
        'excess_return': total_return - buy_hold,
        'total_trades': len(trades_df),
        'win_rate': win_rate,
        'avg_profit': avg_profit,
        'avg_loss': avg_loss,
        'trades': trades_df.to_dict('records')
    }


def main():
    """메인 실행"""

    print("="*70)
    print("  v-a-06 Backtesting (Bear Market Filter)")
    print("="*70)

    # Config 로드
    config_path = Path(__file__).parent / 'config.json'
    with open(config_path, 'r') as f:
        config = json.load(f)

    # DB 경로
    db_path = Path(__file__).parent.parent.parent / 'upbit_bitcoin.db'

    # 연도별 백테스팅
    years = [2020, 2021, 2022, 2023, 2024, 2025]
    all_results = {}

    for year in years:
        result = backtest_year(year, config, db_path)
        if result:
            all_results[year] = result

    # 결과 저장
    output_file = Path(__file__).parent / 'results' / 'backtest_v06_results.json'
    output_file.parent.mkdir(exist_ok=True)

    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump({
            'strategy': 'v-a-06',
            'description': 'v37 Entry + v37 Exit + Bear Market Filter',
            'backtest_date': datetime.now().isoformat(),
            'results': {str(k): v for k, v in all_results.items()}
        }, f, indent=2, ensure_ascii=False, default=str)

    print(f"\n{'='*70}")
    print(f"  백테스팅 완료!")
    print(f"{'='*70}\n")

    # 요약
    print("[연도별 요약]")
    print(f"{'연도':>6s} | {'수익률':>8s} | {'Buy&Hold':>8s} | {'초과':>8s} | {'거래':>5s} | {'승률':>6s}")
    print("-"*70)

    for year, result in all_results.items():
        print(f"{year:>6d} | {result['total_return']:>7.2f}% | "
              f"{result['buy_hold']:>7.2f}% | "
              f"{result['excess_return']:>+7.2f}%p | "
              f"{result['total_trades']:>4d}회 | "
              f"{result['win_rate']:>5.1f}%")

    print(f"\n결과 저장: {output_file}")


if __name__ == '__main__':
    main()
