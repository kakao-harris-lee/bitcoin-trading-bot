#!/usr/bin/env python3
"""
Ensemble Coordinator
- 모든 레이어 통합 관리
- 자본 배분 및 레버리지 제어
- 리스크 관리
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../v42_ultimate_scalping/core'))

import pandas as pd
import numpy as np
from datetime import datetime
import json

from data_loader import MultiTimeframeDataLoader
from score_engine import UnifiedScoreEngine
from layer1_master import Layer1Master
from layer2_scalper import Layer2Scalper
from layer3_position_sizer import Layer3PositionSizer
from layer4_exit_manager import Layer4ExitManager


class EnsembleCoordinator:
    """모든 레이어를 조율하는 메인 컨트롤러"""

    def __init__(self, config_path='../config/base_config.json'):
        # 설정 로드
        with open(config_path) as f:
            self.config = json.load(f)

        # 백테스트 설정
        self.initial_capital = self.config['backtest']['initial_capital']
        self.fee_rate = self.config['backtest']['fee_rate']
        self.slippage = self.config['backtest']['slippage']

        # 자본 배분
        self.capital_allocation = self.config['capital_allocation']
        self.max_leverage = self.capital_allocation['max_total_leverage']

        # v42 엔진 로드
        self.data_loader = MultiTimeframeDataLoader()

        with open('../../v42_ultimate_scalping/config/base_config.json') as f:
            v42_config = json.load(f)
        self.score_engine = UnifiedScoreEngine(v42_config)

        # Layer 인스턴스 생성
        self.layer1 = Layer1Master(self.config)
        self.layer2_m60 = Layer2Scalper(self.config, 'minute60')
        self.layer2_m240 = Layer2Scalper(self.config, 'minute240')
        self.layer3 = Layer3PositionSizer(self.config)
        self.layer4 = Layer4ExitManager(self.config)

        # 리스크 관리
        self.risk_config = self.config['risk_management']

        # 상태
        self.capital = self.initial_capital
        self.daily_pnl = 0.0
        self.consecutive_losses = 0
        self.is_trading_allowed = True
        self.cooldown_until = None

        # 통합 거래 이력
        self.all_trades = []

    def run_backtest(self, start_date, end_date):
        """
        백테스트 실행

        Args:
            start_date: 시작일 (YYYY-MM-DD)
            end_date: 종료일 (YYYY-MM-DD)

        Returns:
            결과 dict
        """
        print(f"\n{'='*80}")
        print(f"v44 Supreme Hybrid Scalping Backtest")
        print(f"기간: {start_date} ~ {end_date}")
        print(f"{'='*80}\n")

        # 1. 데이터 로드
        print("데이터 로드 중...")
        data = self.data_loader.load_all_timeframes(start_date, end_date)

        # 2. 점수 계산
        print("점수 계산 중...")
        scored_data = self.score_engine.score_all_timeframes(data)

        # 3. 시뮬레이션
        print("시뮬레이션 시작...\n")
        self._simulate(scored_data)

        # 4. 결과 계산
        results = self._calculate_results()

        return results

    def _simulate(self, scored_data):
        """
        시뮬레이션 메인 루프

        Args:
            scored_data: 점수 계산된 다중 타임프레임 데이터
        """
        # Day 데이터 기준으로 순회 (가장 긴 타임프레임)
        day_df = scored_data['day']

        if day_df is None or len(day_df) == 0:
            print("Day 데이터 없음")
            return

        for idx in range(len(day_df)):
            # 현재 시점 데이터 추출
            current_day = day_df.iloc[:idx+1]
            current_time = current_day.iloc[-1]['timestamp']

            # 모든 타임프레임의 현재 시점 데이터
            current_data = self._get_current_data(scored_data, current_time)

            # 1. Exit 체크 (먼저 처리)
            self._check_all_exits(current_data)

            # 2. Entry 체크
            if self.is_trading_allowed:
                self._check_all_entries(current_data)

            # 진행상황 출력 (10% 단위)
            if idx % (len(day_df) // 10) == 0:
                progress = (idx / len(day_df)) * 100
                print(f"진행률: {progress:.0f}% | 자본: {self.capital:,.0f}원 | "
                      f"Layer1: {'활성' if self.layer1.is_active() else '대기'} | "
                      f"M60: {'활성' if self.layer2_m60.is_active() else '대기'} | "
                      f"M240: {'활성' if self.layer2_m240.is_active() else '대기'}")

    def _get_current_data(self, scored_data, current_time):
        """현재 시점의 모든 타임프레임 데이터 추출"""
        current = {}

        for tf in ['day', 'minute240', 'minute60']:
            df = scored_data[tf]
            if df is not None and len(df) > 0:
                # 현재 시간 이전 데이터만
                mask = pd.to_datetime(df['timestamp']) <= pd.to_datetime(current_time)
                current[tf] = df[mask]
            else:
                current[tf] = None

        return current

    def _check_all_entries(self, current_data):
        """모든 레이어의 Entry 체크"""
        # Layer 1 Entry
        layer1_signal = self.layer1.check_entry_signal(current_data)
        if layer1_signal and not self.layer1.is_active():
            self._execute_layer1_entry(layer1_signal)

        # Layer 2 Entry (Layer 1이 활성화되어 있을 때만)
        layer1_active = self.layer1.is_active()

        if layer1_active:
            # Minute60
            m60_signal = self.layer2_m60.check_entry_signal(current_data, layer1_active)
            if m60_signal and not self.layer2_m60.is_active():
                self._execute_layer2_entry(m60_signal, self.layer2_m60)

            # Minute240
            m240_signal = self.layer2_m240.check_entry_signal(current_data, layer1_active)
            if m240_signal and not self.layer2_m240.is_active():
                self._execute_layer2_entry(m240_signal, self.layer2_m240)

    def _check_all_exits(self, current_data):
        """모든 레이어의 Exit 체크"""
        # Layer 1 Exit (Dynamic Exit 포함)
        if self.layer1.is_active():
            # 기본 Exit
            exit_signal = self.layer1.check_exit_signal(current_data)

            # Dynamic Exit (Layer 4)
            if not exit_signal and self.layer4.config['enabled']:
                day_df = current_data['day']
                if day_df is not None and len(day_df) > 0:
                    latest = day_df.iloc[-1]
                    dynamic_exit = self.layer4.check_dynamic_exit(
                        self.layer1.current_position,
                        latest['close'],
                        latest['timestamp']
                    )

                    if dynamic_exit:
                        # Partial 또는 Full Exit 처리
                        self._execute_dynamic_exit(dynamic_exit, latest)

            if exit_signal:
                self._execute_layer1_exit(exit_signal)

        # Layer 2 Minute60 Exit
        if self.layer2_m60.is_active():
            exit_signal = self.layer2_m60.check_exit_signal(current_data)
            if exit_signal:
                self._execute_layer2_exit(exit_signal, self.layer2_m60)

        # Layer 2 Minute240 Exit
        if self.layer2_m240.is_active():
            exit_signal = self.layer2_m240.check_exit_signal(current_data)
            if exit_signal:
                self._execute_layer2_exit(exit_signal, self.layer2_m240)

    def _execute_layer1_entry(self, signal):
        """Layer 1 Entry 실행"""
        # Kelly Position Size 계산
        position_sizes = self.layer3.calculate_all_layers(
            self.layer1.trade_history,
            self.layer2_m60.trade_history,
            self.layer2_m240.trade_history,
            self.config
        )

        kelly_size = position_sizes['layer1']
        # 🔧 FIX: 초기 자본 기준 배분 (남은 현금 기준 X)
        allocated_capital = self.initial_capital * self.capital_allocation['layer1_day']
        position_capital = allocated_capital * kelly_size

        # 수수료 + 슬리피지
        buy_cost = position_capital * (1 + self.fee_rate + self.slippage)

        # 현금 부족 체크
        if buy_cost > self.capital:
            print(f"\n⚠️ Layer 1 Entry 취소: 현금 부족 (필요: {buy_cost:,.0f}원, 보유: {self.capital:,.0f}원)\n")
            return

        amount = position_capital / signal['price']

        # Layer 1 실행
        self.layer1.execute_entry(signal, kelly_size)
        self.layer1.current_position['amount'] = amount
        self.layer1.current_position['capital_used'] = buy_cost

        # 자본 차감
        self.capital -= buy_cost

        print(f"\n[Layer 1 Entry] {signal['timestamp']}")
        print(f"  가격: {signal['price']:,.0f}원 | Score: {signal['score']:.1f}")
        print(f"  Kelly Size: {kelly_size*100:.1f}% | 투입: {buy_cost:,.0f}원")
        print(f"  남은 자본: {self.capital:,.0f}원\n")

    def _execute_layer1_exit(self, signal):
        """Layer 1 Exit 실행"""
        pos = self.layer1.current_position
        sell_amount = pos['amount']
        sell_value = sell_amount * signal['price']

        # 수수료 + 슬리피지
        sell_proceeds = sell_value * (1 - self.fee_rate - self.slippage)

        # 수익 계산
        pnl = sell_proceeds - pos['capital_used']

        # Layer 1 청산
        trade = self.layer1.execute_exit(signal)
        trade['pnl'] = pnl
        trade['sell_proceeds'] = sell_proceeds

        # 자본 회수
        self.capital += sell_proceeds

        # 리스크 관리
        self._update_risk_management(pnl)

        # 통합 이력에 추가
        self.all_trades.append(trade)

        print(f"\n[Layer 1 Exit] {signal['timestamp']}")
        print(f"  이유: {signal['reason']}")
        print(f"  수익: {pnl:,.0f}원 ({trade['return']*100:.2f}%)")
        print(f"  현재 자본: {self.capital:,.0f}원\n")

        # Layer 4 상태 초기화
        self.layer4.reset_position_state(pos)

    def _execute_layer2_entry(self, signal, layer):
        """Layer 2 Entry 실행"""
        # Kelly Position Size
        position_sizes = self.layer3.calculate_all_layers(
            self.layer1.trade_history,
            self.layer2_m60.trade_history,
            self.layer2_m240.trade_history,
            self.config
        )

        kelly_key = 'layer2_m60' if signal['timeframe'] == 'minute60' else 'layer2_m240'
        kelly_size = position_sizes[kelly_key]

        allocation_key = 'layer2_minute60' if signal['timeframe'] == 'minute60' else 'layer2_minute240'
        # 🔧 FIX: 초기 자본 기준 배분
        allocated_capital = self.initial_capital * self.capital_allocation[allocation_key]
        position_capital = allocated_capital * kelly_size

        buy_cost = position_capital * (1 + self.fee_rate + self.slippage)

        # 현금 부족 체크
        if buy_cost > self.capital:
            print(f"\n⚠️ Layer 2 {signal['timeframe']} Entry 취소: 현금 부족 (필요: {buy_cost:,.0f}원, 보유: {self.capital:,.0f}원)\n")
            return

        amount = position_capital / signal['price']

        # Layer 2 실행
        layer.execute_entry(signal, kelly_size)
        layer.current_position['amount'] = amount
        layer.current_position['capital_used'] = buy_cost

        # 자본 차감
        self.capital -= buy_cost

        print(f"\n[Layer 2 {signal['timeframe']} Entry] {signal['timestamp']}")
        print(f"  가격: {signal['price']:,.0f}원 | Score: {signal['score']:.1f}")
        print(f"  Kelly: {kelly_size*100:.1f}% | 투입: {buy_cost:,.0f}원")
        print(f"  남은 자본: {self.capital:,.0f}원\n")

    def _execute_layer2_exit(self, signal, layer):
        """Layer 2 Exit 실행"""
        pos = layer.current_position
        sell_value = pos['amount'] * signal['price']
        sell_proceeds = sell_value * (1 - self.fee_rate - self.slippage)
        pnl = sell_proceeds - pos['capital_used']

        trade = layer.execute_exit(signal)
        trade['pnl'] = pnl
        trade['sell_proceeds'] = sell_proceeds

        self.capital += sell_proceeds
        self._update_risk_management(pnl)
        self.all_trades.append(trade)

        print(f"\n[Layer 2 {signal['layer']} Exit] {signal['timestamp']}")
        print(f"  이유: {signal['reason']}")
        print(f"  수익: {pnl:,.0f}원 ({trade['return']*100:.2f}%)")
        print(f"  자본: {self.capital:,.0f}원\n")

    def _execute_dynamic_exit(self, dynamic_signal, latest_candle):
        """Layer 4 Dynamic Exit 실행"""
        if dynamic_signal['action'] == 'full_exit':
            # 전체 청산
            exit_signal = {
                'action': 'SELL',
                'reason': dynamic_signal['reason'],
                'timestamp': latest_candle['timestamp'],
                'price': latest_candle['close'],
                'return': (latest_candle['close'] - self.layer1.current_position['buy_price']) / self.layer1.current_position['buy_price'],
                'hold_hours': 0,  # 계산 생략
                'layer': 1
            }
            self._execute_layer1_exit(exit_signal)

        elif dynamic_signal['action'] == 'partial_exit':
            # 부분 청산 (단순화: 전체 청산으로 처리)
            # 실제로는 포지션 분할 관리 필요
            print(f"\n[Dynamic Partial Exit] Stage {dynamic_signal['stage']}")
            print(f"  비율: {dynamic_signal['ratio']*100:.1f}%")
            print(f"  (단순화: 부분 청산 미구현, 전체 유지)\n")

    def _update_risk_management(self, pnl):
        """리스크 관리 업데이트"""
        self.daily_pnl += pnl

        # 연속 손실
        if pnl < 0:
            self.consecutive_losses += 1
        else:
            self.consecutive_losses = 0

        # 일일 최대 손실
        if self.daily_pnl / self.initial_capital <= self.risk_config['max_daily_loss']:
            self.is_trading_allowed = False
            print(f"\n⚠️  일일 최대 손실 도달! 거래 중지\n")

        # 연속 손실
        if self.consecutive_losses >= self.risk_config['max_consecutive_losses']:
            self.is_trading_allowed = False
            print(f"\n⚠️  연속 {self.consecutive_losses}회 손실! 거래 중지\n")

    def _calculate_results(self):
        """최종 결과 계산"""
        if not self.all_trades:
            return {
                'initial_capital': self.initial_capital,
                'final_capital': self.capital,
                'total_return': 0.0,
                'total_return_pct': 0.0,
                'total_trades': 0
            }

        returns = [t['return'] for t in self.all_trades]
        wins = [r for r in returns if r > 0]
        losses = [r for r in returns if r < 0]

        total_return = (self.capital - self.initial_capital) / self.initial_capital

        # Sharpe Ratio
        if len(returns) > 1:
            sharpe = np.mean(returns) / np.std(returns) * np.sqrt(len(returns))
        else:
            sharpe = 0.0

        # Layer별 통계
        layer1_trades = [t for t in self.all_trades if t['layer'] == 1]
        layer2_trades = [t for t in self.all_trades if t['layer'] == 2]

        results = {
            'initial_capital': self.initial_capital,
            'final_capital': self.capital,
            'total_return': total_return,
            'total_return_pct': total_return * 100,
            'total_trades': len(self.all_trades),
            'wins': len(wins),
            'losses': len(losses),
            'win_rate': len(wins) / len(returns) if returns else 0.0,
            'avg_return': np.mean(returns) if returns else 0.0,
            'avg_win': np.mean(wins) if wins else 0.0,
            'avg_loss': np.mean(losses) if losses else 0.0,
            'sharpe_ratio': sharpe,
            'layer1_trades': len(layer1_trades),
            'layer2_trades': len(layer2_trades),
            'layer1_stats': self.layer1.get_statistics(),
            'layer2_m60_stats': self.layer2_m60.get_statistics(),
            'layer2_m240_stats': self.layer2_m240.get_statistics()
        }

        return results

    def print_results(self, results):
        """결과 출력"""
        print(f"\n{'='*80}")
        print("백테스트 결과")
        print(f"{'='*80}\n")

        print(f"초기 자본:     {results['initial_capital']:>15,}원")
        print(f"최종 자본:     {results['final_capital']:>15,.0f}원")
        print(f"총 수익률:     {results['total_return_pct']:>14.2f}%\n")

        print(f"총 거래:       {results['total_trades']:>15}회")
        print(f"  - Layer 1:   {results['layer1_trades']:>15}회")
        print(f"  - Layer 2:   {results['layer2_trades']:>15}회\n")

        print(f"승/패:         {results['wins']:>7}/{results['losses']:<7}회")
        print(f"승률:          {results['win_rate']*100:>14.1f}%")
        print(f"평균 수익:     {results['avg_return']*100:>14.2f}%")
        print(f"Sharpe Ratio:  {results['sharpe_ratio']:>14.2f}\n")

        # Layer별 상세
        print(f"{'='*80}")
        print("Layer별 상세")
        print(f"{'='*80}\n")

        for layer_name, stats in [
            ('Layer 1 (Day)', results['layer1_stats']),
            ('Layer 2 (M60)', results['layer2_m60_stats']),
            ('Layer 2 (M240)', results['layer2_m240_stats'])
        ]:
            print(f"{layer_name}:")
            if stats and stats['total_trades'] > 0:
                print(f"  거래: {stats['total_trades']}회")
                print(f"  승률: {stats['win_rate']*100:.1f}%")
                print(f"  평균: {stats['avg_return']*100:.2f}%\n")
            else:
                print(f"  거래 없음\n")
