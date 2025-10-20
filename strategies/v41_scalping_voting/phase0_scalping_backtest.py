#!/usr/bin/env python3
"""
단타 전략 백테스팅 (2024년)
- 2024년 전체 데이터에 최적화된 점수 계산
- S/A Tier 시그널 추출
- 단타 전략: 목표가/손절가 도달 시 즉시 청산
- 동적 Hold 기간: 시장 상황별 조정
"""

import sys
sys.path.append('../..')

import json
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import sqlite3
import warnings
warnings.filterwarnings('ignore')

# TA-Lib import
try:
    import talib
except:
    print("TA-Lib 설치 필요: brew install ta-lib && pip install TA-Lib")
    sys.exit(1)


class ScalpingBacktest2024:
    """단타 전략 백테스팅"""

    def __init__(self):
        self.db_path = '../../upbit_bitcoin.db'
        self.initial_capital = 10_000_000
        self.fee_rate = 0.0005
        self.slippage = 0.0002

        # 최적화된 가중치
        self.weights = {
            'rsi_oversold': 8,
            'mfi_bullish': 28,  # day 최적값
            'volume_spike': 7,
            'low_vol': 10
        }

        # Tier 임계값
        self.thresholds = {
            'S': 25,
            'A': 15,
            'B': 10
        }

        # 단타 설정
        self.take_profit = 0.05  # 5% 익절
        self.stop_loss = -0.02   # -2% 손절
        self.max_hold_hours = 72  # 최대 72시간 (3일) 보유

    def load_2024_data(self, timeframe):
        """2024년 데이터 로드 및 지표 계산"""
        print(f"[{timeframe}] 2024년 데이터 로드 중...")

        conn = sqlite3.connect(self.db_path)

        table_map = {
            'minute15': 'bitcoin_minute15',
            'minute60': 'bitcoin_minute60',
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

        # 지표 계산
        print(f"  - 지표 계산 중...")
        df = self.calculate_indicators(df)

        print(f"  - 지표 계산 완료: {len(df):,}개")

        return df

    def calculate_indicators(self, df):
        """기술적 지표 계산"""
        # RSI
        df['rsi'] = talib.RSI(df['close'].values, timeperiod=14)

        # MFI
        df['mfi'] = talib.MFI(df['high'].values, df['low'].values,
                               df['close'].values, df['volume'].values,
                               timeperiod=14)

        # Volume 비율
        df['volume_sma'] = talib.SMA(df['volume'].values, timeperiod=20)
        df['volume_ratio'] = df['volume'] / df['volume_sma']

        # ATR (변동성)
        df['atr'] = talib.ATR(df['high'].values, df['low'].values,
                               df['close'].values, timeperiod=14)
        df['atr_sma'] = talib.SMA(df['atr'].values, timeperiod=20)
        df['atr_ratio'] = df['atr'] / df['atr_sma']

        # ADX (추세 강도)
        df['adx'] = talib.ADX(df['high'].values, df['low'].values,
                               df['close'].values, timeperiod=14)

        # NaN 제거
        df = df.dropna().reset_index(drop=True)

        return df

    def calculate_optimized_score(self, df):
        """최적화된 점수 계산"""
        print(f"최적화된 점수 계산 중...")

        scores = []
        for i in range(len(df)):
            score = 0

            # RSI oversold
            rsi = df.iloc[i]['rsi']
            if rsi < 30:
                score += self.weights['rsi_oversold']
            if rsi < 25:  # 극단적 oversold
                score += 5

            # MFI bullish
            mfi = df.iloc[i]['mfi']
            if mfi > 50:
                score += self.weights['mfi_bullish']
            if mfi > 60:
                score += 5

            # Volume spike
            volume_ratio = df.iloc[i]['volume_ratio']
            if volume_ratio > 2.0:
                score += self.weights['volume_spike']

            # Low volatility
            atr_ratio = df.iloc[i]['atr_ratio']
            if atr_ratio < 0.8:
                score += self.weights['low_vol']

            scores.append(score)

        df['optimized_score'] = scores

        print(f"  - 평균 점수: {df['optimized_score'].mean():.2f}")
        print(f"  - 최대 점수: {df['optimized_score'].max():.0f}")

        return df

    def classify_tiers(self, df):
        """Tier 분류"""
        df['tier'] = 'C'
        df.loc[df['optimized_score'] >= self.thresholds['B'], 'tier'] = 'B'
        df.loc[df['optimized_score'] >= self.thresholds['A'], 'tier'] = 'A'
        df.loc[df['optimized_score'] >= self.thresholds['S'], 'tier'] = 'S'

        tier_counts = df['tier'].value_counts()
        print(f"\nTier 분포:")
        for tier in ['S', 'A', 'B', 'C']:
            count = tier_counts.get(tier, 0)
            pct = count / len(df) * 100 if len(df) > 0 else 0
            print(f"  {tier}-Tier: {count:,}개 ({pct:.2f}%)")

        return df

    def scalping_backtest(self, df, tier='S'):
        """단타 백테스팅"""
        print(f"\n{'='*70}")
        print(f"{tier}-Tier 단타 백테스팅 시작")
        print(f"{'='*70}\n")

        # Tier 필터링
        signals = df[df['tier'] == tier].copy()
        print(f"{tier}-Tier 시그널: {len(signals):,}개")

        if len(signals) == 0:
            return None

        capital = self.initial_capital
        position = 0
        trades = []
        equity_curve = []

        buy_price = 0
        buy_time = None
        buy_idx = -1

        for idx in range(len(signals)):
            signal_row = signals.iloc[idx]
            signal_time = pd.to_datetime(signal_row['timestamp'])

            # 매수
            if position == 0:
                buy_price = signal_row['close']
                buy_time = signal_time
                buy_idx = df[df['timestamp'] == signal_row['timestamp']].index[0]

                # 전액 매수
                buy_cost = capital * (1 + self.fee_rate + self.slippage)
                position = capital / buy_cost
                capital = 0

                trades.append({
                    'type': 'buy',
                    'timestamp': signal_time,
                    'price': buy_price,
                    'amount': position
                })

                # 매수 후 청산 시점 찾기
                sell_idx = self.find_exit_point(df, buy_idx, buy_price)

                if sell_idx >= 0:
                    sell_row = df.iloc[sell_idx]
                    sell_price = sell_row['close']
                    sell_time = pd.to_datetime(sell_row['timestamp'])

                    # 매도
                    sell_revenue = position * sell_price * (1 - self.fee_rate - self.slippage)
                    capital = sell_revenue

                    profit = (sell_price - buy_price) / buy_price
                    hold_hours = (sell_time - buy_time).total_seconds() / 3600

                    trades.append({
                        'type': 'sell',
                        'timestamp': sell_time,
                        'price': sell_price,
                        'amount': position,
                        'profit': profit,
                        'hold_hours': hold_hours,
                        'capital': capital
                    })

                    position = 0
                    buy_price = 0
                    buy_time = None

                    # Equity curve 기록
                    equity_curve.append({
                        'timestamp': sell_time,
                        'value': capital
                    })

        # 미청산 포지션 처리
        if position > 0:
            final_row = df.iloc[-1]
            final_price = final_row['close']
            final_time = pd.to_datetime(final_row['timestamp'])

            sell_revenue = position * final_price * (1 - self.fee_rate - self.slippage)
            capital = sell_revenue

            profit = (final_price - buy_price) / buy_price if buy_price > 0 else 0
            hold_hours = (final_time - buy_time).total_seconds() / 3600 if buy_time else 0

            trades.append({
                'type': 'sell',
                'timestamp': final_time,
                'price': final_price,
                'amount': position,
                'profit': profit,
                'hold_hours': hold_hours,
                'capital': capital
            })

        final_capital = capital

        return {
            'trades': trades,
            'equity_curve': equity_curve,
            'final_capital': final_capital,
            'initial_capital': self.initial_capital
        }

    def find_exit_point(self, df, buy_idx, buy_price):
        """청산 시점 찾기 (목표가/손절가/시간)"""
        max_idx = min(buy_idx + self.max_hold_hours, len(df) - 1)

        for i in range(buy_idx + 1, max_idx + 1):
            current_price = df.iloc[i]['close']
            current_return = (current_price - buy_price) / buy_price

            # 익절 체크
            if current_return >= self.take_profit:
                return i

            # 손절 체크
            if current_return <= self.stop_loss:
                return i

        # 최대 보유 시간 도달
        return max_idx

    def calculate_metrics(self, backtest_results, df):
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
            win_trades = [p for p in profits if p > 0]
            loss_trades = [p for p in profits if p < 0]

            win_rate = len(win_trades) / len(profits) if len(profits) > 0 else 0
            avg_profit = np.mean(profits) if len(profits) > 0 else 0
            avg_win = np.mean(win_trades) if len(win_trades) > 0 else 0
            avg_loss = np.mean(loss_trades) if len(loss_trades) > 0 else 0
            avg_hold_hours = np.mean([t['hold_hours'] for t in sell_trades if 'hold_hours' in t])

            # Profit Factor
            total_win = sum(win_trades) if len(win_trades) > 0 else 0
            total_loss = abs(sum(loss_trades)) if len(loss_trades) > 0 else 0
            profit_factor = total_win / total_loss if total_loss > 0 else 0

            # Sharpe Ratio
            sharpe = (np.mean(profits) / np.std(profits)) if np.std(profits) > 0 else 0
        else:
            win_rate = 0
            avg_profit = 0
            avg_win = 0
            avg_loss = 0
            avg_hold_hours = 0
            profit_factor = 0
            sharpe = 0

        # Buy&Hold
        start_price = df.iloc[0]['close']
        end_price = df.iloc[-1]['close']
        buy_hold_return = (end_price - start_price) / start_price

        metrics = {
            'total_return': total_return,
            'final_capital': final_capital,
            'total_trades': len(sell_trades),
            'win_rate': win_rate,
            'avg_profit': avg_profit,
            'avg_win': avg_win,
            'avg_loss': avg_loss,
            'avg_hold_hours': avg_hold_hours,
            'profit_factor': profit_factor,
            'buy_hold_return': buy_hold_return,
            'outperformance': total_return - buy_hold_return,
            'sharpe_ratio': sharpe
        }

        return metrics

    def print_results(self, metrics, timeframe, tier):
        """결과 출력"""
        print(f"\n{'='*70}")
        print(f"[{timeframe}] {tier}-Tier 단타 백테스팅 결과")
        print(f"{'='*70}\n")

        print(f"=== 수익률 ===")
        print(f"전략 수익률: {metrics['total_return']:.2%}")
        print(f"Buy&Hold 수익률: {metrics['buy_hold_return']:.2%}")
        print(f"초과 수익: {metrics['outperformance']:.2%}p")

        # 목표 달성 여부
        target_return = metrics['buy_hold_return'] + 0.20
        achieved = metrics['total_return'] >= target_return

        print(f"\n목표 수익률: {target_return:.2%}")
        print(f"달성 여부: {'✅ 달성' if achieved else '❌ 미달성'}")

        print(f"\n=== 거래 통계 ===")
        print(f"총 거래: {metrics['total_trades']}회")
        print(f"승률: {metrics['win_rate']:.1%}")
        print(f"평균 수익: {metrics['avg_profit']:.2%}")
        print(f"평균 익절: {metrics['avg_win']:.2%}")
        print(f"평균 손절: {metrics['avg_loss']:.2%}")
        print(f"평균 보유: {metrics['avg_hold_hours']:.1f}시간")
        print(f"Profit Factor: {metrics['profit_factor']:.2f}")

        print(f"\n=== 리스크 지표 ===")
        print(f"Sharpe Ratio: {metrics['sharpe_ratio']:.2f}")

        print(f"{'='*70}\n")

        return achieved

    def run(self, timeframe, tier='S'):
        """전체 프로세스 실행"""
        print(f"\n{'='*70}")
        print(f"[{timeframe}] {tier}-Tier 단타 백테스팅")
        print(f"{'='*70}\n")

        # 1. 2024년 데이터 로드
        df = self.load_2024_data(timeframe)

        # 2. 최적화된 점수 계산
        df = self.calculate_optimized_score(df)

        # 3. Tier 분류
        df = self.classify_tiers(df)

        # 4. 단타 백테스팅
        backtest_results = self.scalping_backtest(df, tier)

        if not backtest_results:
            print(f"{tier}-Tier 시그널 없음")
            return None, False

        # 5. 성과 지표 계산
        metrics = self.calculate_metrics(backtest_results, df)

        # 6. 결과 출력
        achieved = self.print_results(metrics, timeframe, tier)

        # 7. 결과 저장
        output = {
            'timeframe': timeframe,
            'tier': tier,
            'metrics': metrics,
            'trades': backtest_results['trades']
        }

        file_path = f'analysis/scalping/scalping_{timeframe}_{tier}tier.json'
        with open(file_path, 'w') as f:
            json.dump(output, f, indent=2, default=str)

        print(f"결과 저장: {file_path}")

        return metrics, achieved


def main():
    """메인 실행"""
    print(f"\n{'='*70}")
    print(f"단타 전략 백테스팅 (2024년)")
    print(f"{'='*70}\n")

    start_time = datetime.now()

    # 출력 디렉토리 생성
    import os
    os.makedirs('analysis/scalping', exist_ok=True)

    backtester = ScalpingBacktest2024()

    # day 타임프레임, S/A Tier
    timeframes = ['day']
    tiers = ['S', 'A']

    results = {}

    for tf in timeframes:
        for tier in tiers:
            try:
                metrics, achieved = backtester.run(tf, tier)

                if metrics:
                    results[f'{tf}_{tier}'] = {
                        'metrics': metrics,
                        'achieved': achieved
                    }

            except Exception as e:
                print(f"\n[{tf} {tier}] 오류: {e}")
                import traceback
                traceback.print_exc()

    # 최종 요약
    print(f"\n{'='*70}")
    print(f"단타 백테스팅 최종 요약")
    print(f"{'='*70}\n")

    print(f"{'타임프레임-Tier':<15} {'전략 수익률':<15} {'거래 횟수':<12} {'승률':<10} {'달성'}")
    print(f"{'-'*70}")

    for key, data in results.items():
        m = data['metrics']
        achieved = '✅' if data['achieved'] else '❌'
        print(f"{key:<15} {m['total_return']:<15.2%} "
              f"{m['total_trades']:<12,} {m['win_rate']:<10.1%} {achieved}")

    elapsed = datetime.now() - start_time
    print(f"\n소요 시간: {elapsed}")
    print(f"{'='*70}\n")


if __name__ == '__main__':
    main()
