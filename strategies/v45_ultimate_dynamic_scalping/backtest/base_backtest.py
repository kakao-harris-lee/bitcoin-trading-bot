#!/usr/bin/env python3
"""
v45 Unified Backtest Engine
- 복리 재투자 (CompoundReturnsEngine)
- 동적 Kelly (DynamicKellyCriterion)
- 동적 청산 (DynamicExitManager)
- 시장 상태 감지 (MarketRegimeDetector)
"""

import sys
import os
import sqlite3
import pandas as pd
import numpy as np
import json
import yaml
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

# 상위 디렉터리 경로 추가
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from core.market_analyzer import MarketAnalyzer
from strategies.v45_ultimate_dynamic_scalping.core.compound_engine import CompoundReturnsEngine
from strategies.v45_ultimate_dynamic_scalping.core.dynamic_kelly import DynamicKellyCriterion
from strategies.v45_ultimate_dynamic_scalping.core.dynamic_exit import DynamicExitManager
from strategies.v45_ultimate_dynamic_scalping.core.market_regime import MarketRegimeDetector


class V45BaseBacktest:
    """
    v45 기본 백테스트 엔진
    - 단일 타임프레임
    - 점수 기반 진입
    - 동적 Kelly + 동적 청산
    """

    def __init__(self, config_path: str):
        """
        Args:
            config_path: 설정 파일 경로
        """
        with open(config_path, 'r', encoding='utf-8') as f:
            self.config = yaml.safe_load(f)

        # DB 경로
        self.db_path = str(project_root / 'upbit_bitcoin.db')

        # 백테스트 파라미터
        bt_config = self.config['backtest']
        self.initial_capital = bt_config['initial_capital']
        self.fee_rate = bt_config['fee_rate']
        self.slippage = bt_config['slippage']

        # 핵심 엔진 초기화
        self.compound_engine = CompoundReturnsEngine(
            initial_capital=self.initial_capital,
            fee_rate=self.fee_rate,
            slippage=self.slippage
        )

        self.kelly_calculator = DynamicKellyCriterion(
            self.config['dynamic_kelly']
        )

        self.exit_manager = DynamicExitManager(
            self.config['dynamic_exit']
        )

        self.regime_detector = MarketRegimeDetector(
            self.config['market_regime']
        )

        # 시장 분석기 (지표 계산)
        self.market_analyzer = MarketAnalyzer()

        # 거래 기록
        self.trade_history = []
        self.active_position = None
        self.exit_levels = None

    def run_backtest(
        self,
        timeframe: str,
        min_score: float,
        start_date: str,
        end_date: str
    ) -> Dict:
        """
        백테스트 실행

        Args:
            timeframe: 타임프레임 (day, minute240, minute60, ...)
            min_score: 최소 진입 점수
            start_date: 시작일 (YYYY-MM-DD)
            end_date: 종료일 (YYYY-MM-DD)

        Returns:
            백테스트 결과 dict
        """
        print(f"\n{'='*80}")
        print(f"v45 백테스트 시작: {timeframe} / Score >= {min_score}")
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

        # 3. Day-level 시장 상태 계산 (필터용)
        day_data = self._load_data('day', start_date, end_date)
        day_data = self._calculate_indicators(day_data, 'day')

        # 4. 메인 루프
        for i in range(len(data)):
            current = data.iloc[i:i+1]
            current_time = pd.to_datetime(current.iloc[0]['timestamp'])

            # Day-level 시장 상태
            day_current = day_data[day_data['timestamp'] <= current.iloc[0]['timestamp']]
            if len(day_current) == 0:
                continue

            market_regime = self.regime_detector.detect_regime(day_current)

            # 포지션 청산 체크
            if self.active_position is not None:
                exit_signal = self.exit_manager.check_exit_signal(
                    self.active_position,
                    current,
                    self.exit_levels
                )

                if exit_signal:
                    self._exit_position(exit_signal)

            # 진입 체크 (포지션 없을 때만)
            if self.active_position is None:
                # 점수 계산
                score = self._calculate_score(current.iloc[0], timeframe)

                if score >= min_score:
                    # BEAR 필터링
                    if market_regime in ['BEAR_STRONG', 'BEAR_MODERATE']:
                        continue

                    # Kelly 계산
                    kelly = self.kelly_calculator.calculate(
                        self.trade_history,
                        market_regime
                    )

                    # 진입
                    signal = {
                        'timestamp': current.iloc[0]['timestamp'],
                        'price': current.iloc[0]['close'],
                        'score': score,
                        'regime': market_regime,
                        'timeframe': timeframe
                    }

                    position = self.compound_engine.enter_position(signal, kelly)
                    if position:
                        # 청산 레벨 계산
                        self.exit_levels = self.exit_manager.calculate_exit_levels(
                            entry_price=position['entry_price'],
                            market_data=day_current,
                            market_regime=market_regime,
                            timeframe=timeframe
                        )

                        self.active_position = position
                        print(f"[진입] {current_time.strftime('%Y-%m-%d %H:%M')} | "
                              f"점수: {score:.1f} | Kelly: {kelly:.2%} | "
                              f"상태: {market_regime} | "
                              f"자본: {self.compound_engine.current_capital:,.0f}원")

        # 5. 미청산 포지션 강제 청산
        if self.active_position is not None:
            final_price = data.iloc[-1]['close']
            final_time = data.iloc[-1]['timestamp']
            exit_signal = {
                'action': 'exit',
                'reason': 'backtest_end',
                'price': final_price,
                'timestamp': final_time,
                'return_pct': (final_price - self.active_position['entry_price']) / self.active_position['entry_price']
            }
            self._exit_position(exit_signal)

        # 6. 결과 집계
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
                  f"수익: {trade['return_pct']:+.2%} | "
                  f"사유: {exit_signal['reason']} | "
                  f"자본: {self.compound_engine.current_capital:,.0f}원 | "
                  f"누적: {self.compound_engine.get_total_return_pct():+.2%}")

        self.active_position = None
        self.exit_levels = None

    def _load_data(self, timeframe: str, start_date: str, end_date: str) -> pd.DataFrame:
        """데이터 로드"""
        table_map = {
            'day': 'bitcoin_day',
            'minute240': 'bitcoin_minute240',
            'minute60': 'bitcoin_minute60',
            'minute15': 'bitcoin_minute15',
            'minute5': 'bitcoin_minute5'
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

        # MarketAnalyzer 사용
        analyzed = self.market_analyzer.add_indicators(
            data.copy(),
            timeframe
        )

        return analyzed

    def _calculate_score(self, candle: pd.Series, timeframe: str) -> float:
        """
        점수 계산 (v42 스타일)
        MFI 중심의 7-dimension scoring
        """
        score = 0.0

        # 1. MFI Bullish (28점) - 가장 강력
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
        if atr_pct < 0.015:  # 1.5% 미만
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

        # 기본 통계
        total_return = self.compound_engine.get_total_return_pct()
        total_trades = len(trades)
        wins = trades[trades['return_pct'] > 0]
        losses = trades[trades['return_pct'] <= 0]
        win_rate = len(wins) / total_trades if total_trades > 0 else 0

        # Sharpe Ratio
        if len(trades) >= 2:
            returns = trades['return_pct'].values
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
            'total_return_pct': total_return,
            'final_capital': self.compound_engine.current_capital,
            'total_trades': total_trades,
            'win_rate': win_rate * 100,
            'avg_win': wins['return_pct'].mean() * 100 if len(wins) > 0 else 0,
            'avg_loss': losses['return_pct'].mean() * 100 if len(losses) > 0 else 0,
            'sharpe_ratio': sharpe,
            'max_drawdown': max_dd * 100,
            'avg_hold_hours': avg_hold_hours,
            'profit_factor': abs(wins['return_pct'].sum() / losses['return_pct'].sum()) if len(losses) > 0 and losses['return_pct'].sum() != 0 else float('inf'),
            'trades': self.trade_history
        }

        # 출력
        print(f"\n최종 결과:")
        print(f"  총 수익률: {result['total_return_pct']:+.2%}")
        print(f"  최종 자본: {result['final_capital']:,.0f}원")
        print(f"  총 거래: {result['total_trades']}회")
        print(f"  승률: {result['win_rate']:.1f}%")
        print(f"  평균 익절: {result['avg_win']:+.2%}")
        print(f"  평균 손절: {result['avg_loss']:+.2%}")
        print(f"  Sharpe: {result['sharpe_ratio']:.2f}")
        print(f"  MDD: {result['max_drawdown']:.2%}")
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

        # trades를 JSON 직렬화 가능하게 변환
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


# 테스트 코드
if __name__ == "__main__":
    print("=" * 80)
    print("v45 Base Backtest 테스트")
    print("=" * 80)

    config_path = Path(__file__).parent.parent / 'config' / 'base_config.yaml'

    backtest = V45BaseBacktest(str(config_path))

    # 2024년 Day Score 40 테스트 (v43 복제)
    result = backtest.run_backtest(
        timeframe='day',
        min_score=40,
        start_date='2024-01-01',
        end_date='2024-12-31'
    )

    # 결과 저장
    output_path = Path(__file__).parent.parent / 'results' / 'test_day_score40_2024.json'
    backtest.save_results(result, str(output_path))

    print("\n" + "=" * 80)
    print("테스트 완료")
    print("=" * 80)
