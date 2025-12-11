#!/usr/bin/env python3
"""
manual_verification.py
v11 Multi-Entry Ensemble 전략 거래를 수동으로 계산하여 정답 확정

전략: EMA Cross + RSI Bounce + Breakout + Momentum (4-way entry)
"""

import sys
sys.path.append('../..')

import json
from decimal import Decimal, ROUND_DOWN
from core.data_loader import DataLoader
from core.market_analyzer import MarketAnalyzer

# v11 설정 로드
with open('config.json') as f:
    config = json.load(f)

INITIAL_CAPITAL = config['initial_capital']
FEE_RATE = config['fee_rate']
SLIPPAGE = config['slippage']
POSITION_FRACTION = config['base_params']['position_fraction']
EMA_FAST = config['base_params']['ema_fast']
EMA_SLOW = config['base_params']['ema_slow']

RSI_PERIOD = config['rsi_params']['period']
RSI_OVERSOLD = config['rsi_params']['oversold']
RSI_MIN_BOUNCE = config['rsi_params']['min_bounce']

BREAKOUT_LOOKBACK = config['breakout_params']['lookback_period']
BREAKOUT_VOL_MULT = config['breakout_params']['volume_multiplier']

MOMENTUM_PERIOD = config['momentum_params']['period']
MOMENTUM_MIN = config['momentum_params']['min_momentum']
MOMENTUM_ADX = config['momentum_params']['min_adx']

# Regime별 파라미터
REGIME_PARAMS = config['regime_detection']

print("="*80)
print("v11 Multi-Entry Ensemble 전략 수동 계산 검증")
print("="*80)

# 데이터 로드
with DataLoader('../../upbit_bitcoin.db') as loader:
    df = loader.load_timeframe('day', start_date='2024-01-01', end_date='2024-12-31')

# 지표 추가
df = MarketAnalyzer.add_indicators(df, indicators=['ema', 'rsi', 'adx'])

# MACD 수동 추가 (momentum 계산용)
import talib
df['macd'], df['macd_signal'], df['macd_hist'] = talib.MACD(
    df['close'].values, fastperiod=12, slowperiod=26, signalperiod=9
)

print(f"\n초기 설정:")
print(f"  초기 자본: {INITIAL_CAPITAL:,}원")
print(f"  포지션 비율: {POSITION_FRACTION:.2%}")
print(f"  RSI Oversold: {RSI_OVERSOLD}")
print(f"  Breakout Lookback: {BREAKOUT_LOOKBACK}일")
print(f"  Momentum Min: {MOMENTUM_MIN:.2%}")

# Market Regime 판단 함수
def detect_regime(df, i):
    if i < 26:
        return 'bear'

    adx = df.iloc[i]['adx']
    ema12 = df.iloc[i][f'ema_{EMA_FAST}']
    ema26 = df.iloc[i][f'ema_{EMA_SLOW}']

    if i < 5:
        ema_slope = 0
    else:
        ema_slope = (ema12 - df.iloc[i-5][f'ema_{EMA_FAST}']) / df.iloc[i-5][f'ema_{EMA_FAST}']

    # Strong Bull
    if adx >= REGIME_PARAMS['strong_bull']['min_adx'] and ema_slope >= REGIME_PARAMS['strong_bull']['min_ema_slope']:
        return 'strong_bull'

    # Bull
    if adx >= REGIME_PARAMS['bull']['min_adx'] and ema_slope >= REGIME_PARAMS['bull']['min_ema_slope']:
        return 'bull'

    # Sideways
    if adx <= REGIME_PARAMS['sideways']['max_adx']:
        return 'sideways'

    return 'bear'

# 진입 조건 확인 함수들
def check_ema_cross(df, i):
    if i < 26:
        return False
    prev = df.iloc[i-1]
    curr = df.iloc[i]
    return (prev[f'ema_{EMA_FAST}'] <= prev[f'ema_{EMA_SLOW}']) and (curr[f'ema_{EMA_FAST}'] > curr[f'ema_{EMA_SLOW}'])

def check_rsi_bounce(df, i):
    if i < RSI_PERIOD + RSI_MIN_BOUNCE:
        return False
    curr = df.iloc[i]
    prev = df.iloc[i - RSI_MIN_BOUNCE]
    return prev['rsi'] < RSI_OVERSOLD and curr['rsi'] >= RSI_OVERSOLD

def check_breakout(df, i):
    if i < BREAKOUT_LOOKBACK:
        return False
    lookback_high = df.iloc[i-BREAKOUT_LOOKBACK:i]['high'].max()
    curr_price = df.iloc[i]['close']
    avg_volume = df.iloc[i-BREAKOUT_LOOKBACK:i]['volume'].mean()
    curr_volume = df.iloc[i]['volume']

    return curr_price > lookback_high and curr_volume > avg_volume * BREAKOUT_VOL_MULT

def check_momentum(df, i):
    if i < MOMENTUM_PERIOD:
        return False
    curr = df.iloc[i]
    past = df.iloc[i - MOMENTUM_PERIOD]
    momentum = (curr['close'] - past['close']) / past['close']

    return momentum >= MOMENTUM_MIN and curr['adx'] >= MOMENTUM_ADX

# 거래 신호 생성
trades_history = []
in_position = False
entry_price = 0.0
highest_price = 0.0
entry_regime = None

for i in range(len(df)):
    if i < max(26, BREAKOUT_LOOKBACK, MOMENTUM_PERIOD):
        continue

    current = df.iloc[i]
    price = current['close']
    regime = detect_regime(df, i)

    # 매수 신호
    if not in_position:
        reason = None

        if config['entry_conditions']['enable_ema_cross'] and check_ema_cross(df, i):
            reason = 'EMA_GOLDEN_CROSS'
        elif config['entry_conditions']['enable_rsi_bounce'] and check_rsi_bounce(df, i):
            reason = 'RSI_OVERSOLD_BOUNCE'
        elif config['entry_conditions']['enable_breakout'] and check_breakout(df, i):
            reason = 'BREAKOUT'
        elif config['entry_conditions']['enable_momentum'] and check_momentum(df, i):
            reason = 'MOMENTUM_SURGE'

        if reason:
            trades_history.append({
                'type': 'BUY',
                'index': i,
                'timestamp': current['timestamp'],
                'price': price,
                'reason': reason,
                'regime': regime
            })
            in_position = True
            entry_price = price
            highest_price = price
            entry_regime = regime

    # 매도 신호
    else:
        if price > highest_price:
            highest_price = price

        pnl_ratio = (price - entry_price) / entry_price
        drop_from_high = (highest_price - price) / highest_price

        regime_param = REGIME_PARAMS.get(entry_regime, REGIME_PARAMS['bear'])
        trailing_stop = drop_from_high >= regime_param['trailing_stop_pct']
        stop_loss = pnl_ratio <= -regime_param['stop_loss_pct']

        if trailing_stop or stop_loss:
            reason = "TRAILING_STOP" if trailing_stop else "STOP_LOSS"
            trades_history.append({
                'type': 'SELL',
                'index': i,
                'timestamp': current['timestamp'],
                'price': price,
                'reason': reason,
                'regime': regime
            })
            in_position = False

# 마지막 포지션 청산
if in_position:
    last = df.iloc[-1]
    trades_history.append({
        'type': 'SELL',
        'index': len(df)-1,
        'timestamp': last['timestamp'],
        'price': last['close'],
        'reason': 'FINAL_EXIT',
        'regime': detect_regime(df, len(df)-1)
    })

print(f"\n발견된 거래 신호: {len(trades_history)}개")
buy_count = len([t for t in trades_history if t['type'] == 'BUY'])
print(f"  매수: {buy_count}개")
print(f"  매도: {len(trades_history) - buy_count}개")

# 진입 이유 통계
buy_reasons = {}
for t in trades_history:
    if t['type'] == 'BUY':
        reason = t['reason']
        buy_reasons[reason] = buy_reasons.get(reason, 0) + 1

print(f"\n진입 이유 분포:")
for reason, count in buy_reasons.items():
    print(f"  {reason}: {count}회")

# 수동 계산
print("\n" + "="*80)
print("수동 계산 (Decimal 정밀도)")
print("="*80)

cash = Decimal(str(INITIAL_CAPITAL))
position = Decimal('0')

for idx, trade in enumerate(trades_history, 1):
    print(f"\n[거래 {idx}] {trade['type']} @ {trade['timestamp']} ({trade.get('reason', 'N/A')}, Regime: {trade.get('regime', 'N/A')})")
    print(f"  시장 가격: {trade['price']:,.0f}원")

    if trade['type'] == 'BUY':
        market_price = Decimal(str(trade['price']))
        available_cash = cash * Decimal(str(POSITION_FRACTION))
        execution_price = market_price * (Decimal('1') + Decimal(str(SLIPPAGE)))
        quantity = available_cash / (execution_price * (Decimal('1') + Decimal(str(FEE_RATE))))
        cost = quantity * execution_price * (Decimal('1') + Decimal(str(FEE_RATE)))

        print(f"  구매 수량: {quantity:.8f} BTC")
        print(f"  비용: {cost:,.2f}원")

        cash_after = cash - cost
        position_after = position + quantity

        cash = cash_after
        position = position_after
        entry_price_d = execution_price

    else:  # SELL
        market_price = Decimal(str(trade['price']))
        sell_quantity = position
        execution_price = market_price * (Decimal('1') - Decimal(str(SLIPPAGE)))
        proceeds = sell_quantity * execution_price * (Decimal('1') - Decimal(str(FEE_RATE)))

        pnl = (execution_price - entry_price_d) * sell_quantity
        pnl_pct = (execution_price - entry_price_d) / entry_price_d * Decimal('100')

        print(f"  매도 수량: {sell_quantity:.8f} BTC")
        print(f"  수령액: {proceeds:,.2f}원")
        print(f"  손익: {pnl:+,.2f}원 ({pnl_pct:+.2f}%)")

        cash_after = cash + proceeds
        position_after = position - sell_quantity

        cash = cash_after
        position = position_after

# 최종 결과
print("\n" + "="*80)
print("최종 결과 (수동 계산)")
print("="*80)

final_capital = cash
total_return = (final_capital - Decimal(str(INITIAL_CAPITAL))) / Decimal(str(INITIAL_CAPITAL)) * Decimal('100')

print(f"\n초기 자본: {INITIAL_CAPITAL:,}원")
print(f"최종 자본: {float(final_capital):,.2f}원")
print(f"수익: {float(final_capital - Decimal(str(INITIAL_CAPITAL))):+,.2f}원")
print(f"수익률: {float(total_return):.2f}%")

# 비교
print("\n" + "="*80)
print("기존 결과와 비교")
print("="*80)

comparisons = {
    'v11 (Multi-Entry)': 79.76,
    '수동 계산 (정답)': float(total_return)
}

for name, return_pct in comparisons.items():
    diff = return_pct - float(total_return)
    status = "✅" if abs(diff) < 1.0 else "❌"
    print(f"{name:30s}: {return_pct:7.2f}%  (차이: {diff:+7.2f}%p) {status}")

# 결과 저장
result = {
    'strategy': 'v11_multi_entry_ensemble',
    'manual_verification': {
        'total_return_pct': float(total_return),
        'initial_capital': INITIAL_CAPITAL,
        'final_capital': float(final_capital),
        'trades': len(trades_history),
        'buy_count': buy_count,
        'entry_reasons': buy_reasons
    },
    'comparison': comparisons
}

with open('manual_verification_result.json', 'w') as f:
    json.dump(result, f, indent=2)

print("\n결과가 manual_verification_result.json에 저장되었습니다.")
print("="*80)
