#!/usr/bin/env python3
"""
올바른 복리 백테스트 (Correct Compound Returns)
v43의 버그를 수정한 정상적인 복리 계산
"""

import sys
import os
import sqlite3
import pandas as pd
import numpy as np
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, Optional

# 상위 디렉터리 경로 추가
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from core.market_analyzer import MarketAnalyzer


class CorrectCompoundEngine:
    """올바른 복리 엔진"""

    def __init__(self, initial_capital: float, fee_rate: float, slippage: float):
        self.initial_capital = initial_capital
        self.current_capital = initial_capital
        self.fee_rate = fee_rate
        self.slippage = slippage
        self.total_fee = fee_rate + slippage

        self.active_position = None
        self.trade_history = []
        self.total_trades = 0
        self.wins = 0
        self.losses = 0

    def enter_position(self, signal: Dict) -> Optional[Dict]:
        """포지션 진입 (올바른 방식)"""
        if self.active_position is not None:
            return None

        entry_price = signal['price']
        capital = self.current_capital

        # 올바른 매수: 수수료 제외 후 BTC 수량 계산
        buy_fee = capital * self.total_fee
        buy_amount = capital - buy_fee
        btc_amount = buy_amount / entry_price  # 실제 BTC 수량

        self.active_position = {
            'entry_price': entry_price,
            'entry_timestamp': signal['timestamp'],
            'btc_amount': btc_amount,
            'capital_at_entry': capital,
            'score': signal.get('score', 0),
            'timeframe': signal.get('timeframe', 'unknown')
        }

        self.total_trades += 1
        return self.active_position

    def exit_position(self, exit_price: float, exit_timestamp: str, reason: str) -> Dict:
        """포지션 청산 (올바른 방식)"""
        if self.active_position is None:
            raise ValueError("활성 포지션이 없습니다!")

        pos = self.active_position

        # 올바른 매도: 실제 BTC 수량으로 계산
        sell_gross = pos['btc_amount'] * exit_price
        sell_fee = sell_gross * self.total_fee
        sell_net = sell_gross - sell_fee

        # 자본 업데이트
        capital_before = self.current_capital
        self.current_capital = sell_net

        # 수익률 계산
        price_return = (exit_price - pos['entry_price']) / pos['entry_price']
        capital_return = (self.current_capital - capital_before) / capital_before

        # 거래 기록
        trade = {
            'entry_price': pos['entry_price'],
            'entry_timestamp': pos['entry_timestamp'],
            'exit_price': exit_price,
            'exit_timestamp': exit_timestamp,
            'btc_amount': pos['btc_amount'],
            'sell_revenue': sell_net,
            'return_pct': price_return,
            'capital_return': capital_return,
            'score': pos['score'],
            'timeframe': pos['timeframe'],
            'reason': reason,
            'capital_before': capital_before,
            'capital_after': self.current_capital
        }

        self.trade_history.append(trade)

        if capital_return > 0:
            self.wins += 1
        else:
            self.losses += 1

        self.active_position = None
        return trade

    def get_current_capital(self) -> float:
        return self.current_capital

    def get_total_return_pct(self) -> float:
        return (self.current_capital - self.initial_capital) / self.initial_capital


class CorrectCompoundBacktest:
    """올바른 복리 백테스트"""

    def __init__(self):
        self.db_path = str(project_root / 'upbit_bitcoin.db')
        self.initial_capital = 10_000_000
        self.fee_rate = 0.0005
        self.slippage = 0.0002

        # Exit 조건
        self.take_profit = 0.05
        self.stop_loss = -0.02
        self.max_hold_hours = 72

        self.market_analyzer = MarketAnalyzer()
        self.compound_engine = CorrectCompoundEngine(
            initial_capital=self.initial_capital,
            fee_rate=self.fee_rate,
            slippage=self.slippage
        )

        self.trade_history = []
        self.active_position = None

    def run_backtest(
        self,
        timeframe: str,
        min_score: float,
        start_date: str,
        end_date: str
    ) -> Dict:
        """백테스트 실행"""
        print(f"\n{'='*80}")
        print(f"올바른 복리 백테스트 (Correct Compound Returns)")
        print(f"{timeframe} / Score >= {min_score}")
        print(f"기간: {start_date} ~ {end_date}")
        print(f"초기 자본: {self.initial_capital:,}원")
        print(f"{'='*80}\n")

        # 1. 데이터 로드
        data = self._load_data(timeframe, start_date, end_date)
        if data.empty:
            return self._empty_result()

        print(f"데이터 로드 완료: {len(data):,}개 캔들\n")

        # 2. 지표 계산
        data = self._calculate_indicators(data, timeframe)

        # 3. 메인 루프
        for i in range(len(data)):
            current = data.iloc[i]
            current_time = pd.to_datetime(current['timestamp'])

            # 포지션 청산 체크
            if self.active_position is not None:
                exit_signal = self._check_exit(data, i)
                if exit_signal:
                    self._exit_position(exit_signal)

            # 진입 체크
            if self.active_position is None:
                score = self._calculate_score(current)
                if score >= min_score:
                    signal = {
                        'timestamp': current['timestamp'],
                        'price': current['close'],
                        'score': score
                    }

                    position = self.compound_engine.enter_position(signal)
                    if position:
                        self.active_position = {
                            **position,
                            'entry_idx': i
                        }

                        print(f"[진입] {current_time.strftime('%Y-%m-%d %H:%M')} | "
                              f"가격: {current['close']:,.0f}원 | "
                              f"점수: {score:.1f} | "
                              f"BTC: {position['btc_amount']:.8f} | "
                              f"자본: {self.compound_engine.get_current_capital():,.0f}원")

        # 4. 미청산 포지션 강제 청산
        if self.active_position is not None:
            final = data.iloc[-1]
            exit_signal = {
                'action': 'exit',
                'reason': 'backtest_end',
                'price': final['close'],
                'timestamp': final['timestamp']
            }
            self._exit_position(exit_signal)

        # 5. 결과 집계
        result = self._calculate_results()

        print(f"\n{'='*80}")
        print("백테스트 완료")
        print(f"{'='*80}")

        return result

    def _exit_position(self, exit_signal: Dict):
        """포지션 청산"""
        trade = self.compound_engine.exit_position(
            exit_price=exit_signal['price'],
            exit_timestamp=exit_signal['timestamp'],
            reason=exit_signal['reason']
        )

        if trade:
            self.trade_history.append(trade)
            exit_time = pd.to_datetime(exit_signal['timestamp'])

            print(f"[청산] {exit_time.strftime('%Y-%m-%d %H:%M')} | "
                  f"가격: {trade['exit_price']:,.0f}원 | "
                  f"수익: {trade['capital_return']:+.2%} | "
                  f"사유: {exit_signal['reason']} | "
                  f"자본: {self.compound_engine.get_current_capital():,.0f}원 | "
                  f"누적: {self.compound_engine.get_total_return_pct():+.2%}")

        self.active_position = None

    def _check_exit(self, data: pd.DataFrame, current_idx: int) -> Optional[Dict]:
        """청산 조건 체크"""
        if self.active_position is None:
            return None

        current = data.iloc[current_idx]
        entry_price = self.active_position['entry_price']
        entry_idx = self.active_position['entry_idx']

        return_pct = (current['close'] - entry_price) / entry_price

        # 익절
        if return_pct >= self.take_profit:
            return {
                'action': 'exit',
                'reason': 'take_profit',
                'price': current['close'],
                'timestamp': current['timestamp']
            }

        # 손절
        if return_pct <= self.stop_loss:
            return {
                'action': 'exit',
                'reason': 'stop_loss',
                'price': current['close'],
                'timestamp': current['timestamp']
            }

        # 시간 초과
        if current_idx - entry_idx >= self.max_hold_hours:
            return {
                'action': 'exit',
                'reason': 'timeout',
                'price': current['close'],
                'timestamp': current['timestamp']
            }

        return None

    def _load_data(self, timeframe: str, start_date: str, end_date: str) -> pd.DataFrame:
        """데이터 로드"""
        table_map = {
            'day': 'bitcoin_day',
            'minute240': 'bitcoin_minute240',
            'minute60': 'bitcoin_minute60'
        }

        table = table_map.get(timeframe)
        if not table:
            return pd.DataFrame()

        conn = sqlite3.connect(self.db_path)
        query = f"""
            SELECT
                timestamp,
                opening_price as open,
                high_price as high,
                low_price as low,
                trade_price as close,
                candle_acc_trade_volume as volume
            FROM {table}
            WHERE timestamp >= '{start_date}' AND timestamp <= '{end_date}'
            ORDER BY timestamp
        """
        df = pd.read_sql(query, conn)
        conn.close()

        return df

    def _calculate_indicators(self, data: pd.DataFrame, timeframe: str) -> pd.DataFrame:
        """지표 계산"""
        if data.empty:
            return data

        analyzed = self.market_analyzer.add_indicators(
            data.copy(),
            timeframe
        )

        return analyzed

    def _calculate_score(self, candle: pd.Series) -> float:
        """점수 계산 (v42/v43 기준)"""
        score = 0.0

        # 1. MFI Bullish (28점)
        mfi = candle.get('mfi', 50)
        if 45 <= mfi <= 55:
            score += 28
        elif 40 <= mfi < 45 or 55 < mfi <= 60:
            score += 14

        # 2. Local Minima (20점)
        if candle.get('is_local_min', False):
            score += 20

        # 3. Low Volatility (16점)
        atr_pct = candle.get('atr', 0) / candle.get('close', 1)
        if atr_pct < 0.015:
            score += 16
        elif atr_pct < 0.025:
            score += 8

        # 4. RSI (8점 × 2)
        rsi = candle.get('rsi', 50)
        if rsi <= 30:
            score += 8
        if 40 <= rsi <= 60:
            score += 8

        # 5. Volume Spike (12점)
        volume_ratio = candle.get('volume_ratio', 1.0)
        if volume_ratio >= 1.5:
            score += 12
        elif volume_ratio >= 1.2:
            score += 6

        # 6. Swing End (7점)
        if candle.get('swing_end', False):
            score += 7

        return score

    def _calculate_results(self) -> Dict:
        """결과 집계"""
        if not self.trade_history:
            return self._empty_result()

        trades = pd.DataFrame(self.trade_history)

        total_return = self.compound_engine.get_total_return_pct()
        total_trades = len(trades)
        wins = trades[trades['capital_return'] > 0]
        losses = trades[trades['capital_return'] <= 0]
        win_rate = len(wins) / total_trades if total_trades > 0 else 0

        # Sharpe Ratio
        if len(trades) >= 2:
            returns = trades['capital_return'].values
            sharpe = np.mean(returns) / np.std(returns) * np.sqrt(252) if np.std(returns) > 0 else 0
        else:
            sharpe = 0

        # MDD
        equity_curve = [self.initial_capital]
        for trade in self.trade_history:
            equity_curve.append(trade['capital_after'])

        peak = equity_curve[0]
        max_dd = 0
        for capital in equity_curve:
            if capital > peak:
                peak = capital
            dd = (capital - peak) / peak
            if dd < max_dd:
                max_dd = dd

        # 평균 보유 시간
        avg_hold_hours = 0
        if total_trades > 0:
            hold_times = []
            for trade in self.trade_history:
                entry = pd.to_datetime(trade['entry_timestamp'])
                exit = pd.to_datetime(trade['exit_timestamp'])
                hours = (exit - entry).total_seconds() / 3600
                hold_times.append(hours)
            avg_hold_hours = np.mean(hold_times)

        result = {
            'total_return_pct': total_return * 100,
            'final_capital': self.compound_engine.get_current_capital(),
            'total_trades': total_trades,
            'win_rate': win_rate * 100,
            'avg_win': wins['capital_return'].mean() * 100 if len(wins) > 0 else 0,
            'avg_loss': losses['capital_return'].mean() * 100 if len(losses) > 0 else 0,
            'sharpe_ratio': sharpe,
            'max_drawdown': max_dd * 100,
            'avg_hold_hours': avg_hold_hours,
            'profit_factor': abs(wins['capital_return'].sum() / losses['capital_return'].sum()) if len(losses) > 0 and losses['capital_return'].sum() != 0 else float('inf'),
            'trades': self.trade_history
        }

        # 출력
        print(f"\n최종 결과:")
        print(f"  총 수익률: {result['total_return_pct']:+.2f}%")
        print(f"  최종 자본: {result['final_capital']:,.0f}원")
        print(f"  총 거래: {result['total_trades']}회")
        print(f"  승률: {result['win_rate']:.1f}%")
        print(f"  평균 익절: {result['avg_win']:+.2f}%")
        print(f"  평균 손절: {result['avg_loss']:+.2f}%")
        print(f"  Sharpe: {result['sharpe_ratio']:.2f}")
        print(f"  MDD: {result['max_drawdown']:.2f}%")
        print(f"  평균 보유: {result['avg_hold_hours']:.1f}시간")
        print(f"  Profit Factor: {result['profit_factor']:.2f}")

        return result

    def _empty_result(self) -> Dict:
        """빈 결과"""
        return {
            'total_return_pct': 0,
            'final_capital': self.initial_capital,
            'total_trades': 0,
            'win_rate': 0,
            'avg_win': 0,
            'avg_loss': 0,
            'sharpe_ratio': 0,
            'max_drawdown': 0,
            'avg_hold_hours': 0,
            'profit_factor': 0,
            'trades': []
        }

    def save_results(self, result: Dict, output_path: str):
        """결과 저장"""
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        result_copy = result.copy()
        if 'trades' in result_copy:
            result_copy['trades'] = [
                {k: (str(v) if isinstance(v, (pd.Timestamp, datetime)) else v)
                 for k, v in trade.items()}
                for trade in result_copy['trades']
            ]

        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(result_copy, f, indent=2, ensure_ascii=False)

        print(f"\n결과 저장 완료: {output_path}")


if __name__ == "__main__":
    print("=" * 80)
    print("올바른 복리 백테스트 (Correct Compound Returns)")
    print("=" * 80)

    backtest = CorrectCompoundBacktest()

    # 2024년 Day Score 40 테스트
    result = backtest.run_backtest(
        timeframe='day',
        min_score=40,
        start_date='2024-01-01',
        end_date='2024-12-31'
    )

    # 결과 저장
    output_path = Path(__file__).parent.parent / 'results' / 'correct_compound_day_2024.json'
    backtest.save_results(result, str(output_path))

    print("\n" + "=" * 80)
    print("비교:")
    print(f"v43 (버그): +1,276.99%")
    print(f"올바른 복리: {result['total_return_pct']:+.2f}%")
    print("=" * 80)
