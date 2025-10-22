#!/usr/bin/env python3
"""
v-a-04 Backtesting with v37 Exit Logic
=======================================
v37의 동적 Exit 시스템을 사용한 백테스팅
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

# v-a-15 core 모듈 동적 import
def import_va15_modules():
    """v-a-15 core 모듈 import"""
    va15_core_path = Path(__file__).parent / 'core'

    import importlib.util

    # KellyPositionSizer
    spec_kelly = importlib.util.spec_from_file_location(
        "position_sizer",
        va15_core_path / "position_sizer.py"
    )
    position_sizer_module = importlib.util.module_from_spec(spec_kelly)
    spec_kelly.loader.exec_module(position_sizer_module)

    # ATRDynamicExitManager
    spec_atr = importlib.util.spec_from_file_location(
        "exit_manager",
        va15_core_path / "exit_manager.py"
    )
    exit_manager_module = importlib.util.module_from_spec(spec_atr)
    spec_atr.loader.exec_module(exit_manager_module)

    return (
        position_sizer_module.KellyPositionSizer,
        exit_manager_module.ATRDynamicExitManager
    )


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
        """
        Sideways Exit v-a-11: Progressive Profit Taking

        핵심 개선:
        1. TP 대폭 상향: 6%/12%/20% (TP:SL = 3:1/6:1/10:1)
        2. 분할 청산: 30%/40%/30% (트렌드 연장 포착)
        3. ATR 기반 동적 Trailing Stop

        목표: 폭발적 수익 포착 (2020 +233% → +320%)
        """
        # v-a-11: TP 상향 (2%/4%/6% → 6%/12%/20%)
        tp1 = self.config.get('sideways_tp_1', 0.06)   # 3배 증가
        tp2 = self.config.get('sideways_tp_2', 0.12)   # 6배 증가
        tp3 = self.config.get('sideways_tp_3', 0.20)   # 10배 증가
        stop_loss = self.config.get('sideways_stop_loss', -0.02)
        max_hold = self.config.get('sideways_max_hold_days', 30)  # 20 → 30일 (트렌드 연장)

        # v-a-11: Progressive TP (단순화 - 단계별 전량 청산)
        # 분할 청산 대신 높은 TP로 큰 수익 포착
        if profit >= tp3:
            return {'should_exit': True, 'reason': 'SIDEWAYS_TP3', 'fraction': 1.0}
        if profit >= tp2:
            return {'should_exit': True, 'reason': 'SIDEWAYS_TP2', 'fraction': 1.0}
        if profit >= tp1:
            return {'should_exit': True, 'reason': 'SIDEWAYS_TP1', 'fraction': 1.0}

        # Stop Loss
        if profit <= stop_loss:
            return {'should_exit': True, 'reason': 'SIDEWAYS_STOP_LOSS', 'fraction': 1.0}

        # v-a-11: ATR 기반 동적 Trailing Stop
        atr = row.get('atr', 0)
        current_price = row['close']
        entry_price = highest_price / (1 + max(profit, 0))

        # ATR 비율 계산
        atr_ratio = atr / entry_price if entry_price > 0 else 0.01

        # 동적 Trailing: min(-1%, -0.5 × ATR)
        trailing_threshold = max(0.01, min(0.5 * atr_ratio, 0.03))  # 0.5~3%

        drawdown_from_peak = (current_price - highest_price) / highest_price
        if drawdown_from_peak <= -trailing_threshold:
            return {'should_exit': True, 'reason': 'SIDEWAYS_TRAILING_ATR', 'fraction': 1.0}

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


def backtest_year(year: int, config: dict, db_path: Path, use_va15_features: bool = True) -> dict:
    """연도별 백테스팅

    Args:
        year: 백테스팅 연도
        config: 설정 딕셔너리
        db_path: DB 경로
        use_va15_features: v-a-15 기능 사용 여부 (Kelly, ATR)
    """

    print(f"\n{'='*70}")
    print(f"  {year}년 백테스팅 {'(v-a-15 Enhanced)' if use_va15_features else ''}")
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
            'fraction': sig['fraction'],
            'confidence_score': sig.get('confidence_score', 50)  # v-a-15: 신뢰도 점수
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

    df = MarketAnalyzer.add_indicators(df, ['macd', 'atr'])

    # Exit Manager
    exit_manager = V37ExitManager(config)

    # v-a-15: Kelly Position Sizer & ATR Exit Manager
    kelly_sizer = None
    atr_exit_manager = None
    if use_va15_features:
        KellyPositionSizer, ATRDynamicExitManager = import_va15_modules()

        kelly_config = {
            'kelly_win_rate': 0.467,
            'kelly_win_loss_ratio': 1.97,
            'kelly_use_half': True,
            'kelly_multiplier': 0.5,
            'min_position_pct': 0.10,
            'max_position_pct': 0.70
        }

        atr_config = {}

        kelly_sizer = KellyPositionSizer(kelly_config)
        atr_exit_manager = ATRDynamicExitManager(atr_config)

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
        confidence_score = signal.get('confidence_score', 50)

        # v-a-15: Kelly Criterion Position Sizing
        if use_va15_features and kelly_sizer:
            position_capital_amount = kelly_sizer.calculate_position_size(
                confidence_score=confidence_score,
                capital=capital,
                strategy=strategy
            )
            position_fraction = position_capital_amount / capital
        else:
            position_fraction = signal['fraction']
            position_capital_amount = capital * position_fraction

        # Entry 비용
        entry_cost = position_capital_amount * (1 + total_fee)
        btc_amount = position_capital_amount / entry_price

        # v-a-15: ATR 기반 Exit Levels 계산
        entry_row = df[df['timestamp'] == entry_time]
        entry_atr = entry_row.iloc[0]['atr'] if len(entry_row) > 0 else 0.02

        atr_exit_levels = None
        if use_va15_features and atr_exit_manager:
            atr_exit_levels = atr_exit_manager.calculate_exit_levels(
                entry_price=entry_price,
                entry_atr=entry_atr,
                strategy=strategy
            )

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

            # v-a-15: ATR Exit 우선 체크
            should_exit_atr = False
            exit_reason_atr = None

            if use_va15_features and atr_exit_levels:
                # Stop Loss
                if current_price <= atr_exit_levels['stop_loss']:
                    should_exit_atr = True
                    exit_reason_atr = 'ATR_STOP_LOSS'
                # Take Profit 1
                elif current_price >= atr_exit_levels['take_profit_1']:
                    should_exit_atr = True
                    exit_reason_atr = 'ATR_TP1'
                # Take Profit 2
                elif current_price >= atr_exit_levels['take_profit_2']:
                    should_exit_atr = True
                    exit_reason_atr = 'ATR_TP2'
                # Take Profit 3
                elif current_price >= atr_exit_levels['take_profit_3']:
                    should_exit_atr = True
                    exit_reason_atr = 'ATR_TP3'
                # Trailing Stop (최고가에서 ATR × 3.5 하락)
                elif highest_price > entry_price * 1.05:  # 5% 이상 수익 시
                    trailing_stop = highest_price * (1 - entry_atr * 3.5)
                    if current_price <= trailing_stop:
                        should_exit_atr = True
                        exit_reason_atr = 'ATR_TRAILING_STOP'

            if should_exit_atr:
                exit_price = current_price
                exit_time = row['timestamp']
                exit_reason = exit_reason_atr
                break

            # v37 Exit (보조)
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
                exit_reason = f"V37_{exit_check['reason']}"  # v37 구분
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
        profit = exit_revenue - position_capital_amount
        profit_pct = (profit / position_capital_amount) * 100

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
            'position_fraction': position_fraction,
            'position_capital': position_capital_amount,
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
    print("  v-a-15 Backtesting (Kelly + ATR)")
    print("="*70)

    # Config 로드
    config_path = Path(__file__).parent / 'config.json'
    with open(config_path, 'r') as f:
        config = json.load(f)

    # DB 경로
    db_path = Path(__file__).parent.parent.parent / 'upbit_bitcoin.db'

    # 연도별 백테스팅 (v-a-15 Enhanced)
    years = [2020, 2021, 2022, 2023, 2024, 2025]
    va15_results = {}

    print("\n[v-a-15 Enhanced 모드: Kelly Criterion + ATR Dynamic Exit]")
    for year in years:
        result = backtest_year(year, config, db_path, use_va15_features=True)
        if result:
            va15_results[year] = result

    # 결과 저장
    output_file = Path(__file__).parent / 'results' / 'backtest_va15_enhanced.json'
    output_file.parent.mkdir(exist_ok=True)

    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump({
            'strategy': 'v-a-15',
            'description': 'Kelly Criterion + ATR Dynamic Exit + Grid Trading',
            'backtest_date': datetime.now().isoformat(),
            'features': {
                'kelly_criterion': True,
                'atr_dynamic_exit': True,
                'grid_trading': False  # TODO: Phase 3에서 구현
            },
            'results': {str(k): v for k, v in va15_results.items()}
        }, f, indent=2, ensure_ascii=False, default=str)

    print(f"\n{'='*70}")
    print(f"  백테스팅 완료!")
    print(f"{'='*70}\n")

    # 요약
    print("[v-a-15 Enhanced 연도별 요약]")
    print(f"{'연도':>6s} | {'수익률':>8s} | {'Buy&Hold':>8s} | {'초과':>8s} | {'거래':>5s} | {'승률':>6s}")
    print("-"*70)

    for year, result in va15_results.items():
        print(f"{year:>6d} | {result['total_return']:>7.2f}% | "
              f"{result['buy_hold']:>7.2f}% | "
              f"{result['excess_return']:>+7.2f}%p | "
              f"{result['total_trades']:>4d}회 | "
              f"{result['win_rate']:>5.1f}%")

    print(f"\n결과 저장: {output_file}")

    # 2025년 성과 하이라이트
    if 2025 in va15_results:
        result_2025 = va15_results[2025]
        print(f"\n{'='*70}")
        print(f"  🎯 2025년 성과 (v-a-15 Enhanced)")
        print(f"{'='*70}")
        print(f"  수익률: {result_2025['total_return']:.2f}%")
        print(f"  목표 (+30%): {'✅ 달성!' if result_2025['total_return'] >= 30 else '❌ 미달'}")
        print(f"  v-a-11 대비: {result_2025['total_return'] - 20.42:+.2f}%p")
        print(f"{'='*70}")


if __name__ == '__main__':
    main()
