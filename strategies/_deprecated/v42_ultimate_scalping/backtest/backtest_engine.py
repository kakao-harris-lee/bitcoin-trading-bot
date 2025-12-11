#!/usr/bin/env python3
"""
v42 Unified Backtest Engine
- Multi-Timeframe 통합 백테스팅
- Score Engine + Confluence + Position + Exit 통합
- 단일/멀티 타임프레임 모드
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'core'))

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import json

from data_loader import MultiTimeframeDataLoader
from score_engine import UnifiedScoreEngine
from confluence import MultiTimeframeConfluence
from position_manager import PositionManager
from exit_manager import DynamicExitManager


class V42BacktestEngine:
    """v42 통합 백테스팅 엔진"""

    def __init__(self, config_path='../config/base_config.json'):
        # Config 로드
        with open(config_path) as f:
            self.config = json.load(f)

        # 모듈 초기화
        self.data_loader = MultiTimeframeDataLoader()
        self.score_engine = UnifiedScoreEngine(self.config)
        self.confluence = MultiTimeframeConfluence(self.config)
        self.position_manager = None  # 백테스트 시작 시 초기화
        self.exit_manager = DynamicExitManager(self.config)

        # 설정
        self.initial_capital = self.config['trading']['initial_capital']

    def load_and_prepare_data(self, start_date, end_date):
        """데이터 로드 및 전처리"""

        print(f"\n{'='*70}")
        print(f"데이터 준비: {start_date} ~ {end_date}")
        print(f"{'='*70}\n")

        # 1. 데이터 로드
        data = self.data_loader.load_all_timeframes(start_date, end_date)

        # 2. 점수 계산
        scored_data = self.score_engine.score_all_timeframes(data)

        # 3. Confluence 적용
        enhanced_data = self.confluence.apply_confluence(scored_data)

        # 4. Day 필터 (선택적)
        # filtered_data = self.confluence.filter_by_day(enhanced_data, 'B')

        return enhanced_data

    def run_single_timeframe(self, timeframe, start_date, end_date, min_tier='S', min_score=None):
        """단일 타임프레임 백테스팅"""

        print(f"\n{'='*70}")
        print(f"백테스팅: {timeframe} ({start_date} ~ {end_date})")
        print(f"{'='*70}\n")

        # 데이터 준비
        data = self.load_and_prepare_data(start_date, end_date)

        df = data.get(timeframe)
        if df is None or len(df) == 0:
            print(f"[{timeframe}] 데이터 없음")
            return None

        # Position Manager 초기화
        self.position_manager = PositionManager(self.config, self.initial_capital)

        # 시그널만 필터링
        if min_tier == 'S':
            signals = df[df['tier'] == 'S'].copy()
        else:
            signals = df[df['tier'].isin(['S', 'A'])].copy()

        # 점수 필터 (선택적)
        if min_score:
            signals = signals[signals['score'] >= min_score].copy()

        print(f"총 시그널: {len(signals)}개 ({min_tier}-Tier 이상"
              + (f", Score >= {min_score}" if min_score else "") + ")\n")

        # 백테스팅 루프
        for idx, signal_row in signals.iterrows():
            timestamp = signal_row['timestamp']
            price = signal_row['close']
            tier = signal_row['tier']
            score = signal_row['score']
            signal_list = signal_row['signals']

            # 포지션 진입
            position, reason = self.position_manager.open_position(
                timestamp=timestamp,
                price=price,
                tier=tier,
                timeframe=timeframe,
                score=score,
                signals=signal_list
            )

            if position:
                # 청산 시뮬레이션
                self._simulate_exit(position, df, idx, timeframe)

        # 남은 포지션 강제 청산
        self._close_all_positions(df.iloc[-1]['timestamp'], df.iloc[-1]['close'])

        # 결과
        stats = self.position_manager.get_statistics()

        return stats

    def _simulate_exit(self, position, df, entry_idx, timeframe):
        """청산 시뮬레이션"""

        entry_time = position['entry_timestamp']
        max_hold_hours = self.config['timeframes'][timeframe].get('max_hold_hours', 72)

        # 진입 이후 데이터
        future_data = df.iloc[entry_idx + 1:]

        for idx, row in future_data.iterrows():
            current_time = row['timestamp']
            current_price = row['close']

            # 시간 제한 체크
            elapsed_hours = (current_time - entry_time).total_seconds() / 3600
            if elapsed_hours > max_hold_hours:
                break

            # Peak 업데이트
            self.position_manager.update_peak_price(position, current_price)

            # 청산 체크
            should_exit, reason, ratio = self.exit_manager.should_exit(
                position, current_price, current_time, 'BULL'
            )

            if should_exit:
                self.position_manager.close_position(position, current_time, current_price, reason)
                break

    def _close_all_positions(self, timestamp, price):
        """모든 열린 포지션 강제 청산"""

        for position in self.position_manager.open_positions[:]:
            self.position_manager.close_position(position, timestamp, price, 'END_OF_PERIOD')

    def run_multi_timeframe(self, start_date, end_date, timeframes=['minute15', 'minute60']):
        """멀티 타임프레임 백테스팅"""

        print(f"\n{'='*70}")
        print(f"Multi-Timeframe 백테스팅: {timeframes}")
        print(f"{'='*70}\n")

        # 데이터 준비
        data = self.load_and_prepare_data(start_date, end_date)

        # Position Manager 초기화
        self.position_manager = PositionManager(self.config, self.initial_capital)

        # 타임프레임별 시그널 수집
        all_signals = []

        for tf in timeframes:
            df = data.get(tf)
            if df is None or len(df) == 0:
                continue

            # S/A-Tier만
            signals = df[df['tier'].isin(['S', 'A'])].copy()
            signals['source_tf'] = tf

            all_signals.append(signals)

        # 통합 및 시간순 정렬
        if not all_signals:
            print("시그널 없음")
            return None

        combined = pd.concat(all_signals, ignore_index=True)
        combined = combined.sort_values('timestamp').reset_index(drop=True)

        print(f"총 시그널: {len(combined)}개\n")

        # 백테스팅 루프
        for idx, signal_row in combined.iterrows():
            timestamp = signal_row['timestamp']
            price = signal_row['close']
            tier = signal_row['tier']
            score = signal_row['score']
            signal_list = signal_row['signals']
            source_tf = signal_row['source_tf']

            # 포지션 진입
            position, reason = self.position_manager.open_position(
                timestamp=timestamp,
                price=price,
                tier=tier,
                timeframe=source_tf,
                score=score,
                signals=signal_list
            )

            if position:
                # 해당 타임프레임 데이터로 청산 시뮬레이션
                tf_df = data[source_tf]
                signal_idx = tf_df[tf_df['timestamp'] == timestamp].index[0]
                self._simulate_exit(position, tf_df, signal_idx, source_tf)

            # 기존 포지션 청산 체크
            self._check_all_positions(data, timestamp)

        # 남은 포지션 강제 청산
        last_price = combined.iloc[-1]['close']
        self._close_all_positions(combined.iloc[-1]['timestamp'], last_price)

        # 결과
        stats = self.position_manager.get_statistics()

        return stats

    def _check_all_positions(self, data, current_timestamp):
        """모든 열린 포지션 청산 체크"""

        for position in self.position_manager.open_positions[:]:
            tf = position['timeframe']
            tf_df = data.get(tf)

            if tf_df is None:
                continue

            # 현재 시점의 가격
            current_data = tf_df[tf_df['timestamp'] == current_timestamp]

            if len(current_data) > 0:
                current_price = current_data.iloc[0]['close']

                # Peak 업데이트
                self.position_manager.update_peak_price(position, current_price)

                # 청산 체크
                should_exit, reason, ratio = self.exit_manager.should_exit(
                    position, current_price, current_timestamp, 'BULL'
                )

                if should_exit:
                    self.position_manager.close_position(position, current_timestamp, current_price, reason)

    def print_results(self, stats, title="백테스팅 결과"):
        """결과 출력"""

        if not stats:
            print("결과 없음")
            return

        print(f"\n{'='*70}")
        print(f"{title}")
        print(f"{'='*70}\n")

        print(f"초기 자본:     {stats['initial_capital']:>15,}원")
        print(f"최종 자본:     {stats['current_capital']:>15,.0f}원")
        print(f"총 수익률:     {stats['total_return']*100:>14.2f}%")
        print(f"\n총 거래:       {stats['total_trades']:>15}회")
        print(f"승/패:         {stats['wins']:>7}/{stats['losses']:<7}회")
        print(f"승률:          {stats['win_rate']*100:>14.1f}%")
        print(f"\n평균 익절:     {stats['avg_win']*100:>14.2f}%")
        print(f"평균 손절:     {stats['avg_loss']*100:>14.2f}%")
        print(f"Profit Factor: {stats['profit_factor']:>14.2f}")
        print(f"\n평균 보유:     {stats['avg_hold_hours']:>14.1f}시간")

        # Sharpe Ratio 계산
        if self.position_manager and len(self.position_manager.trade_history) > 0:
            returns = [t['pnl_pct'] for t in self.position_manager.trade_history]
            sharpe = np.mean(returns) / np.std(returns) * np.sqrt(252) if np.std(returns) > 0 else 0
            print(f"Sharpe Ratio:  {sharpe:>14.2f}")

        print()


def main():
    """메인 테스트"""

    engine = V42BacktestEngine()

    # 1. 단일 타임프레임 (minute15, 2024년 1-2월)
    print("\n" + "="*70)
    print("테스트 1: minute15 (2024-01 ~ 2024-02)")
    print("="*70)

    stats1 = engine.run_single_timeframe(
        timeframe='minute15',
        start_date='2024-01-01',
        end_date='2024-03-01',
        min_tier='S'
    )

    engine.print_results(stats1, "minute15 S-Tier 결과")

    # 2. 멀티 타임프레임 (minute15 + minute60)
    print("\n" + "="*70)
    print("테스트 2: Multi-TF (minute15 + minute60)")
    print("="*70)

    engine2 = V42BacktestEngine()

    stats2 = engine2.run_multi_timeframe(
        start_date='2024-01-01',
        end_date='2024-03-01',
        timeframes=['minute15', 'minute60']
    )

    engine2.print_results(stats2, "Multi-TF 결과")


if __name__ == '__main__':
    main()
