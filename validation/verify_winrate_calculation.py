#!/usr/bin/env python3
"""
승률 계산 검증 스크립트
개별 거래의 매수/매도 내역을 상세히 추적하여 수동 계산 결과와 비교
"""

import json
import sqlite3
import pandas as pd
from pathlib import Path
from datetime import timedelta

# 상수
INITIAL_CAPITAL = 10_000_000  # 10M KRW
TRADING_FEE = 0.0005  # 0.05% (진입)
SLIPPAGE = 0.0004     # 0.04%
TOTAL_FEE = TRADING_FEE + SLIPPAGE  # 0.09%

def load_signals(strategy_name: str, year: int = 2024):
    """시그널 로드"""
    signal_file = Path(f"strategies/validation/{strategy_name}/signals/{year}_signals.json")

    with open(signal_file, 'r', encoding='utf-8') as f:
        data = json.load(f)

    signals = []
    for sig in data['signals']:
        signals.append({
            'timestamp': pd.to_datetime(sig['timestamp']),
            'price': float(sig['price']),
            'score': sig.get('score'),
            'metadata': sig.get('metadata')
        })

    return pd.DataFrame(signals)

def load_price_data(year: int, timeframe: str):
    """가격 데이터 로드"""
    db_path = Path('upbit_bitcoin.db')
    table_name = f'bitcoin_{timeframe}'

    conn = sqlite3.connect(db_path)

    query = f"""
        SELECT timestamp,
               opening_price as open,
               high_price as high,
               low_price as low,
               trade_price as close,
               candle_acc_trade_volume as volume
        FROM {table_name}
        WHERE strftime('%Y', timestamp) = '{year}'
        ORDER BY timestamp ASC
    """

    df = pd.read_sql_query(query, conn)
    conn.close()

    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df = df.set_index('timestamp')

    return df

def simulate_trade_detailed(signal, price_data, holding_hours, take_profit=0.05, stop_loss=0.02):
    """
    단일 거래 시뮬레이션 (상세)

    Returns:
        dict with entry/exit details
    """
    entry_time = signal['timestamp']
    entry_price = signal['price']

    # 진입
    position_fraction = 1.0  # Fixed 100%
    entry_amount = INITIAL_CAPITAL * position_fraction
    entry_fee = entry_amount * TOTAL_FEE
    btc_amount = (entry_amount - entry_fee) / entry_price

    # 청산 타임 계산
    max_exit_time = entry_time + timedelta(hours=holding_hours)

    # 청산 체크
    exit_price = None
    exit_time = None
    exit_reason = None

    # 진입 시점 이후 데이터만 필터링
    future_data = price_data[price_data.index > entry_time]

    for timestamp, bar in future_data.iterrows():
        # Timeout
        if timestamp >= max_exit_time:
            exit_price = bar['close']
            exit_time = timestamp
            exit_reason = 'TIMEOUT'
            break

        # Take Profit 체크
        if bar['high'] >= entry_price * (1 + take_profit):
            exit_price = entry_price * (1 + take_profit)
            exit_time = timestamp
            exit_reason = 'TAKE_PROFIT'
            break

        # Stop Loss 체크
        if bar['low'] <= entry_price * (1 - stop_loss):
            exit_price = entry_price * (1 - stop_loss)
            exit_time = timestamp
            exit_reason = 'STOP_LOSS'
            break

    # 청산되지 않았으면 마지막 가격으로 강제 청산
    if exit_price is None:
        if len(future_data) > 0:
            last_bar = future_data.iloc[-1]
            exit_price = last_bar['close']
            exit_time = future_data.index[-1]
            exit_reason = 'END_OF_PERIOD'
        else:
            # 미래 데이터 없음 (연말 시그널 등) → 스킵
            return None

    # 청산
    sell_amount = btc_amount * exit_price
    sell_fee = sell_amount * TOTAL_FEE
    sell_revenue = sell_amount - sell_fee

    # 수익률 계산
    profit = sell_revenue - entry_amount
    return_pct = (sell_revenue - entry_amount) / entry_amount * 100

    # 보유 시간
    holding_hours_actual = (exit_time - entry_time).total_seconds() / 3600

    return {
        'entry_time': entry_time,
        'entry_price': entry_price,
        'entry_amount': entry_amount,
        'entry_fee': entry_fee,
        'btc_amount': btc_amount,
        'exit_time': exit_time,
        'exit_price': exit_price,
        'exit_reason': exit_reason,
        'sell_amount': sell_amount,
        'sell_fee': sell_fee,
        'sell_revenue': sell_revenue,
        'profit': profit,
        'return_pct': return_pct,
        'holding_hours': holding_hours_actual,
        'is_win': return_pct > 0
    }

def verify_strategy(strategy_name: str, timeframe: str, holding_hours: float, config: dict):
    """전략 검증 (수동 계산)"""

    print(f"\n{'='*80}")
    print(f"전략: {strategy_name}")
    print(f"타임프레임: {timeframe}")
    print(f"홀딩 피리어드: {holding_hours}h ({holding_hours/24:.1f}d)")
    print(f"설정: TP={config['take_profit']*100:.1f}%, SL={config['stop_loss']*100:.1f}%")
    print(f"{'='*80}\n")

    # 데이터 로드
    signals = load_signals(strategy_name)
    price_data = load_price_data(2024, timeframe)

    print(f"총 시그널: {len(signals)}개")
    print(f"가격 데이터: {len(price_data)}개 캔들\n")

    # 거래 시뮬레이션
    trades = []

    for idx, signal in signals.iterrows():
        trade = simulate_trade_detailed(
            signal.to_dict(),
            price_data,
            holding_hours,
            config['take_profit'],
            config['stop_loss']
        )
        if trade is not None:  # None 스킵 (연말 시그널 등)
            trades.append(trade)

    # DataFrame으로 변환
    trades_df = pd.DataFrame(trades)

    # 통계 계산
    total_trades = len(trades_df)
    winning_trades = trades_df[trades_df['is_win']]
    losing_trades = trades_df[~trades_df['is_win']]

    win_count = len(winning_trades)
    lose_count = len(losing_trades)
    win_rate = win_count / total_trades * 100 if total_trades > 0 else 0

    avg_return = trades_df['return_pct'].mean()
    avg_win_return = winning_trades['return_pct'].mean() if len(winning_trades) > 0 else 0
    avg_lose_return = losing_trades['return_pct'].mean() if len(losing_trades) > 0 else 0

    total_profit = trades_df['profit'].sum()
    final_capital = INITIAL_CAPITAL + total_profit
    total_return_pct = (final_capital - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100

    # 수수료 총합
    total_entry_fee = trades_df['entry_fee'].sum()
    total_exit_fee = trades_df['sell_fee'].sum()
    total_fees = total_entry_fee + total_exit_fee

    print(f"📊 거래 통계")
    print(f"{'─'*80}")
    print(f"총 거래: {total_trades}회")
    print(f"승리: {win_count}회 ({win_rate:.2f}%)")
    print(f"패배: {lose_count}회 ({100-win_rate:.2f}%)")
    print(f"\n평균 수익률: {avg_return:.2f}%")
    print(f"평균 승리 수익률: {avg_win_return:.2f}%")
    print(f"평균 패배 수익률: {avg_lose_return:.2f}%")
    print(f"\n최종 자본: {final_capital:,.0f}원")
    print(f"총 수익: {total_profit:,.0f}원 ({total_return_pct:.2f}%)")
    print(f"총 수수료: {total_fees:,.0f}원")

    # 청산 사유 분포
    print(f"\n📍 청산 사유 분포")
    print(f"{'─'*80}")
    exit_reasons = trades_df['exit_reason'].value_counts()
    for reason, count in exit_reasons.items():
        pct = count / total_trades * 100
        print(f"{reason}: {count}회 ({pct:.1f}%)")

    # 샘플 거래 (첫 10개)
    print(f"\n📝 샘플 거래 (첫 10개)")
    print(f"{'─'*80}")

    sample = trades_df.head(10)

    for idx, trade in sample.iterrows():
        result = "✅ 승" if trade['is_win'] else "❌ 패"
        print(f"\n{idx+1}. {result} | 수익률: {trade['return_pct']:+.2f}% | 사유: {trade['exit_reason']}")
        print(f"   매수: {trade['entry_time']} @ {trade['entry_price']:,.0f}원")
        print(f"   매도: {trade['exit_time']} @ {trade['exit_price']:,.0f}원")
        print(f"   투입: {trade['entry_amount']:,.0f}원 | 회수: {trade['sell_revenue']:,.0f}원")
        print(f"   수익: {trade['profit']:+,.0f}원 | 수수료: {trade['entry_fee'] + trade['sell_fee']:,.0f}원")
        print(f"   보유: {trade['holding_hours']:.1f}시간")

    # JSON 결과와 비교
    result_file = Path(f"strategies/validation/{strategy_name}/evaluation/full_matrix.json")

    if result_file.exists():
        with open(result_file, 'r', encoding='utf-8') as f:
            engine_result = json.load(f)

        # 해당 period 찾기
        period_key = None
        for key in engine_result['full_matrix'].keys():
            if key.startswith('2024_'):
                hrs = float(key.split('_')[1].replace('d', '')) * 24
                if abs(hrs - holding_hours) < 1:  # 오차 허용
                    period_key = key
                    break

        if period_key:
            engine_stats = engine_result['full_matrix'][period_key]

            print(f"\n🔍 엔진 결과 비교 ({period_key})")
            print(f"{'─'*80}")
            print(f"{'항목':<20} {'수동 계산':>15} {'엔진 결과':>15} {'차이':>15}")
            print(f"{'─'*80}")

            def compare(name, manual, engine):
                diff = manual - engine
                diff_str = f"{diff:+.2f}" if abs(diff) < 1000 else f"{diff:+,.0f}"
                print(f"{name:<20} {manual:>15.2f} {engine:>15.2f} {diff_str:>15}")

            compare("총 수익률 (%)", total_return_pct, engine_stats['total_return_pct'])
            compare("총 거래 (회)", total_trades, engine_stats['total_trades'])
            compare("승리 (회)", win_count, engine_stats['winning_trades'])
            compare("패배 (회)", lose_count, engine_stats['losing_trades'])
            compare("승률 (%)", win_rate, engine_stats['win_rate'])
            compare("평균 수익률 (%)", avg_return, engine_stats['avg_return'])
            compare("평균 승리 (%)", avg_win_return, engine_stats['avg_winning_return'])
            compare("평균 패배 (%)", avg_lose_return, engine_stats['avg_losing_return'])

            print(f"\n{'⚠️ 불일치!' if abs(win_rate - engine_stats['win_rate']) > 1 else '✅ 일치!'}")

    return trades_df

if __name__ == '__main__':
    # v_simple_rsi 검증 (14d)
    verify_strategy(
        strategy_name='v_simple_rsi',
        timeframe='day',
        holding_hours=14 * 24,  # 14d
        config={'take_profit': 0.05, 'stop_loss': 0.02}
    )

    # v_momentum 검증 (14d)
    verify_strategy(
        strategy_name='v_momentum',
        timeframe='day',
        holding_hours=14 * 24,  # 14d
        config={'take_profit': 0.05, 'stop_loss': 0.02}
    )

    # v_volume_spike 검증 (3d)
    verify_strategy(
        strategy_name='v_volume_spike',
        timeframe='minute240',
        holding_hours=3 * 24,  # 3d
        config={'take_profit': 0.04, 'stop_loss': 0.015}
    )
