#!/usr/bin/env python3
"""
수정된 엔진의 거래 내역 상세 출력
"""

import sys
import json
import sqlite3
import pandas as pd
from pathlib import Path
from datetime import timedelta

sys.path.insert(0, str(Path(__file__).parent))
from universal_evaluation_engine import UniversalEvaluationEngine

def load_config(strategy_name):
    """Config 로드"""
    config_file = Path(f"strategies/validation/{strategy_name}/evaluation/config.json")
    with open(config_file, 'r') as f:
        return json.load(f)

def get_all_trades_detailed(strategy_name):
    """엔진으로 모든 거래 상세 추적"""

    config = load_config(strategy_name)

    # 엔진 초기화
    engine = UniversalEvaluationEngine(
        initial_capital=10_000_000,
        fee_rate=0.0005,
        slippage=0.0004
    )

    # 시그널 로드
    signals_dir = Path(f"strategies/validation/{strategy_name}/signals")
    signals = engine.load_signals(signals_dir / "2024_signals.json")

    # 가격 데이터 로드
    price_data = engine.load_price_data(2024, config['timeframe'])

    # 최적 holding period 찾기
    holding_periods = config['holding_periods']
    best_period = None
    best_sharpe = -999

    for period_name, hours in holding_periods.items():
        result = engine.backtest_single_combination(
            signals=signals,
            price_data=price_data,
            holding_period_hours=hours,
            exit_config=config['exit_strategy'],
            position_config=config['position_sizing'],
            year=2024,
            period_name=period_name
        )

        if result['sharpe_ratio'] > best_sharpe:
            best_sharpe = result['sharpe_ratio']
            best_period = period_name

    # 최적 period로 다시 실행하여 거래 내역 추출
    best_hours = holding_periods[best_period]

    # 거래 내역 추출을 위해 엔진 수정 필요 → 직접 시뮬레이션
    return simulate_with_trade_details(
        engine, signals, price_data, best_hours,
        config['exit_strategy'], config['position_sizing'],
        strategy_name, best_period
    )

def simulate_with_trade_details(engine, signals, price_data, holding_hours, exit_config, position_config, strategy_name, period_name):
    """거래 상세 내역과 함께 시뮬레이션"""

    from universal_evaluation_engine import Position, Trade

    # 초기화
    capital = engine.initial_capital
    position = None
    trades = []

    # Exit 플러그인
    exit_type = exit_config.get('type', 'fixed')
    exit_plugin = engine.exit_strategies.get(exit_type)

    # Position 플러그인
    position_type = position_config.get('type', 'fixed')
    position_plugin = engine.position_strategies.get(position_type)

    signal_idx = 0

    for timestamp, bar in price_data.iterrows():
        # 포지션 없음 → 시그널 체크
        if position is None:
            while signal_idx < len(signals):
                signal = signals[signal_idx]

                if signal.timestamp > timestamp:
                    break

                if signal.timestamp <= timestamp:
                    # 진입
                    fraction = position_plugin.calculate_position_size(
                        signal=signal,
                        capital=capital,
                        config=position_config
                    )

                    entry_amount = capital * fraction
                    entry_fee = entry_amount * engine.total_fee
                    btc_amount = (entry_amount - entry_fee) / signal.price

                    position = Position(
                        entry_time=signal.timestamp,
                        entry_price=signal.price,
                        btc_amount=btc_amount,
                        capital_at_entry=entry_amount,
                        entry_fee=entry_fee,
                        peak_price=signal.price,
                        signal_score=signal.score,
                        signal_metadata=signal.metadata
                    )

                    capital -= entry_amount
                    signal_idx += 1
                    break

        # 포지션 있음 → 청산 조건 체크
        else:
            # Peak 업데이트
            if bar['high'] > position.peak_price:
                position.peak_price = bar['high']

            # Timeout 체크
            holding_hours_current = (timestamp - position.entry_time).total_seconds() / 3600

            exit_price = None
            exit_reason = None

            if holding_hours_current >= holding_hours:
                exit_price = bar['close']
                exit_reason = 'TIMEOUT'
            else:
                # Exit 플러그인으로 청산 조건 체크
                exit_result = exit_plugin.check_exit(
                    position=position,
                    current_bar=bar,
                    timestamp=timestamp,
                    config=exit_config
                )

                if exit_result['should_exit']:
                    exit_price = exit_result['exit_price']
                    exit_reason = exit_result['reason']

            # 청산 실행
            if exit_price is not None:
                sell_amount = position.btc_amount * exit_price
                sell_fee = sell_amount * engine.total_fee
                sell_revenue = sell_amount - sell_fee

                capital += sell_revenue

                return_pct = (sell_revenue - position.capital_at_entry) / position.capital_at_entry * 100
                holding_hours_actual = (timestamp - position.entry_time).total_seconds() / 3600

                trade = {
                    'entry_time': position.entry_time,
                    'entry_price': position.entry_price,
                    'entry_amount': position.capital_at_entry,
                    'entry_fee': position.entry_fee,
                    'btc_amount': position.btc_amount,
                    'exit_time': timestamp,
                    'exit_price': exit_price,
                    'exit_reason': exit_reason,
                    'sell_amount': sell_amount,
                    'sell_fee': sell_fee,
                    'sell_revenue': sell_revenue,
                    'profit': sell_revenue - position.capital_at_entry,
                    'return_pct': return_pct,
                    'holding_hours': holding_hours_actual,
                    'is_win': return_pct > 0,
                    'peak_price': position.peak_price,
                    'signal_metadata': position.signal_metadata
                }

                trades.append(trade)
                position = None

    # 미청산 포지션 강제 청산
    if position is not None:
        last_bar = price_data.iloc[-1]
        last_timestamp = price_data.index[-1]

        sell_amount = position.btc_amount * last_bar['close']
        sell_fee = sell_amount * engine.total_fee
        sell_revenue = sell_amount - sell_fee
        capital += sell_revenue

        return_pct = (sell_revenue - position.capital_at_entry) / position.capital_at_entry * 100
        holding_hours_actual = (last_timestamp - position.entry_time).total_seconds() / 3600

        trade = {
            'entry_time': position.entry_time,
            'entry_price': position.entry_price,
            'entry_amount': position.capital_at_entry,
            'entry_fee': position.entry_fee,
            'btc_amount': position.btc_amount,
            'exit_time': last_timestamp,
            'exit_price': last_bar['close'],
            'exit_reason': 'END_OF_PERIOD',
            'sell_amount': sell_amount,
            'sell_fee': sell_fee,
            'sell_revenue': sell_revenue,
            'profit': sell_revenue - position.capital_at_entry,
            'return_pct': return_pct,
            'holding_hours': holding_hours_actual,
            'is_win': return_pct > 0,
            'peak_price': position.peak_price,
            'signal_metadata': position.signal_metadata
        }

        trades.append(trade)

    return {
        'strategy': strategy_name,
        'period': period_name,
        'holding_hours': holding_hours,
        'trades': trades,
        'final_capital': capital,
        'initial_capital': engine.initial_capital
    }

def print_trades_table(result):
    """거래 내역 테이블 출력"""

    trades = result['trades']
    strategy = result['strategy']
    period = result['period']
    holding_hours = result['holding_hours']

    print(f"\n{'='*120}")
    print(f"전략: {strategy} | 최적 홀딩: {period} ({holding_hours}h)")
    print(f"{'='*120}\n")

    # 통계
    total_trades = len(trades)
    winning_trades = [t for t in trades if t['is_win']]
    losing_trades = [t for t in trades if not t['is_win']]

    win_count = len(winning_trades)
    lose_count = len(losing_trades)
    win_rate = win_count / total_trades * 100 if total_trades > 0 else 0

    total_profit = sum(t['profit'] for t in trades)
    total_return_pct = (result['final_capital'] - result['initial_capital']) / result['initial_capital'] * 100

    avg_return = sum(t['return_pct'] for t in trades) / total_trades if trades else 0
    avg_win_return = sum(t['return_pct'] for t in winning_trades) / win_count if winning_trades else 0
    avg_lose_return = sum(t['return_pct'] for t in losing_trades) / lose_count if losing_trades else 0

    print(f"📊 전체 통계")
    print(f"{'─'*120}")
    print(f"총 거래: {total_trades}회 | 승리: {win_count}회 ({win_rate:.1f}%) | 패배: {lose_count}회 ({100-win_rate:.1f}%)")
    print(f"평균 수익률: {avg_return:+.2f}% | 평균 승리: {avg_win_return:+.2f}% | 평균 패배: {avg_lose_return:+.2f}%")
    print(f"총 수익: {total_profit:,.0f}원 ({total_return_pct:+.2f}%) | 최종 자본: {result['final_capital']:,.0f}원")

    # 청산 사유
    exit_reasons = {}
    for t in trades:
        reason = t['exit_reason']
        exit_reasons[reason] = exit_reasons.get(reason, 0) + 1

    print(f"\n청산 사유: ", end="")
    for reason, count in exit_reasons.items():
        pct = count / total_trades * 100
        print(f"{reason} {count}회({pct:.1f}%) | ", end="")
    print()

    # 거래 내역 테이블
    print(f"\n{'─'*120}")
    print(f"{'No':<4} {'결과':<4} {'진입 시간':<20} {'진입가':<12} {'청산 시간':<20} {'청산가':<12} {'수익률':<10} {'수익금':<12} {'사유':<15}")
    print(f"{'─'*120}")

    for idx, trade in enumerate(trades, 1):
        result_icon = "✅" if trade['is_win'] else "❌"

        entry_time_str = trade['entry_time'].strftime('%Y-%m-%d %H:%M')
        exit_time_str = trade['exit_time'].strftime('%Y-%m-%d %H:%M')

        print(f"{idx:<4} {result_icon:<4} {entry_time_str:<20} {trade['entry_price']:>11,.0f}원 {exit_time_str:<20} {trade['exit_price']:>11,.0f}원 {trade['return_pct']:>+9.2f}% {trade['profit']:>+11,.0f}원 {trade['exit_reason']:<15}")

    print(f"{'─'*120}\n")

def save_trades_csv(result, output_file):
    """거래 내역 CSV 저장"""

    trades = result['trades']

    # DataFrame 변환
    df = pd.DataFrame(trades)

    # 시간 포맷 변환
    df['entry_time'] = pd.to_datetime(df['entry_time'])
    df['exit_time'] = pd.to_datetime(df['exit_time'])

    # 저장
    df.to_csv(output_file, index=False, encoding='utf-8-sig')
    print(f"💾 거래 내역 저장: {output_file}")

if __name__ == '__main__':
    # 3개 전략 테스트
    strategies = ['v_simple_rsi', 'v_momentum', 'v_volume_spike']

    for strategy in strategies:
        try:
            result = get_all_trades_detailed(strategy)
            print_trades_table(result)

            # CSV 저장
            output_file = Path(f"strategies/validation/{strategy}/evaluation/trades_detailed.csv")
            save_trades_csv(result, output_file)

        except Exception as e:
            print(f"\n❌ Error: {strategy}: {e}")
            import traceback
            traceback.print_exc()
