#!/usr/bin/env python3
"""
v-a-04 Backtest
===============
생성된 시그널을 백테스팅하고 성과 측정
"""

import sys
from pathlib import Path

# 프로젝트 루트 추가
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

import json
import pandas as pd
from datetime import timedelta

from core.data_loader import DataLoader


def load_signals(signal_file: Path) -> pd.DataFrame:
    """JSON 시그널 파일 로드"""
    with open(signal_file, 'r') as f:
        data = json.load(f)

    signals = []
    for sig in data['signals']:
        signals.append({
            'timestamp': pd.to_datetime(sig['timestamp']),
            'entry_price': sig['entry_price'],
            'market_state': sig.get('market_state', 'UNKNOWN')
        })

    return pd.DataFrame(signals)


def simple_backtest(
    signals: pd.DataFrame,
    price_data: pd.DataFrame,
    take_profit: float = 0.05,
    stop_loss: float = -0.02,
    max_hold_days: int = 30,
    initial_capital: float = 10_000_000,
    fee_rate: float = 0.0005,
    slippage: float = 0.0002
) -> dict:
    """
    단순 백테스팅 (고정 TP/SL)

    Args:
        signals: 시그널 DataFrame
        price_data: 가격 데이터
        take_profit: 익절 (+5%)
        stop_loss: 손절 (-2%)
        max_hold_days: 최대 보유 (30일)
        initial_capital: 초기 자본
        fee_rate: 수수료
        slippage: 슬리피지

    Returns:
        백테스팅 결과
    """
    capital = initial_capital
    trades = []

    # Price data 인덱스 설정
    if 'timestamp' in price_data.columns:
        price_data = price_data.set_index('timestamp')

    total_fee = fee_rate + slippage

    for _, signal in signals.iterrows():
        entry_time = signal['timestamp']
        entry_price = signal['entry_price']

        # Entry 이후 데이터만
        future_data = price_data[price_data.index > entry_time]

        if len(future_data) == 0:
            continue

        # Exit 추적
        exit_price = None
        exit_time = None
        exit_reason = None

        for i, (ts, row) in enumerate(future_data.iterrows()):
            current_price = row['close']
            profit = (current_price - entry_price) / entry_price

            # 익절
            if profit >= take_profit:
                exit_price = current_price
                exit_time = ts
                exit_reason = 'TP'
                break

            # 손절
            if profit <= stop_loss:
                exit_price = current_price
                exit_time = ts
                exit_reason = 'SL'
                break

            # 타임아웃
            if (ts - entry_time).days >= max_hold_days:
                exit_price = current_price
                exit_time = ts
                exit_reason = 'TIMEOUT'
                break

        # Exit 못 찾으면 스킵
        if exit_price is None:
            continue

        # 거래 수행
        buy_amount = capital * (1 - total_fee)
        btc_amount = buy_amount / entry_price

        sell_gross = btc_amount * exit_price
        sell_revenue = sell_gross * (1 - total_fee)

        trade_profit = sell_revenue - capital
        trade_profit_pct = (trade_profit / capital) * 100

        capital = sell_revenue

        trades.append({
            'entry_time': entry_time,
            'exit_time': exit_time,
            'entry_price': entry_price,
            'exit_price': exit_price,
            'profit_pct': trade_profit_pct,
            'profit': trade_profit,
            'capital': capital,
            'hold_days': (exit_time - entry_time).days,
            'exit_reason': exit_reason,
            'market_state': signal['market_state']
        })

    # 결과 계산
    if len(trades) == 0:
        return {
            'total_return_pct': 0,
            'final_capital': initial_capital,
            'total_trades': 0,
            'win_rate': 0,
            'avg_profit': 0,
            'max_drawdown': 0
        }

    trades_df = pd.DataFrame(trades)

    total_return = ((capital - initial_capital) / initial_capital) * 100
    win_trades = len(trades_df[trades_df['profit_pct'] > 0])
    win_rate = win_trades / len(trades_df) * 100

    avg_win = trades_df[trades_df['profit_pct'] > 0]['profit_pct'].mean() if win_trades > 0 else 0
    avg_loss = trades_df[trades_df['profit_pct'] <= 0]['profit_pct'].mean() if len(trades_df) - win_trades > 0 else 0

    # Max Drawdown
    capital_series = trades_df['capital']
    peak = capital_series.expanding().max()
    drawdown = ((capital_series - peak) / peak) * 100
    max_dd = drawdown.min()

    return {
        'total_return_pct': total_return,
        'final_capital': capital,
        'total_trades': len(trades_df),
        'win_rate': win_rate,
        'avg_win_pct': avg_win,
        'avg_loss_pct': avg_loss,
        'max_drawdown': max_dd,
        'avg_hold_days': trades_df['hold_days'].mean(),
        'exit_reasons': trades_df['exit_reason'].value_counts().to_dict(),
        'market_states': trades_df['market_state'].value_counts().to_dict(),
        'trades': trades_df.to_dict('records')
    }


def main():
    """메인 실행"""

    TIMEFRAME = 'day'
    YEAR = 2024

    print("="*70)
    print(f"  v-a-04 Backtest")
    print("="*70)
    print(f"  Timeframe: {TIMEFRAME}")
    print(f"  Year: {YEAR}")
    print()

    # 1. 시그널 로드
    signal_file = Path(__file__).parent / 'signals' / f'{TIMEFRAME}_{YEAR}_signals.json'

    if not signal_file.exists():
        print(f"❌ Signal file not found: {signal_file}")
        print(f"\n먼저 generate_signals.py를 실행하세요.")
        return

    print(f"📊 Loading signals...")
    signals = load_signals(signal_file)
    print(f"  Loaded: {len(signals)} signals")

    # 2. 가격 데이터 로드
    print(f"\n📈 Loading price data...")
    db_path = Path(__file__).parent.parent.parent / 'upbit_bitcoin.db'
    loader = DataLoader(str(db_path))

    df = loader.load_timeframe(
        timeframe=TIMEFRAME,
        start_date=f'{YEAR}-01-01',
        end_date=f'{YEAR}-12-31'
    )
    print(f"  Loaded: {len(df)} candles")

    # 3. 백테스팅
    print(f"\n🔄 Running backtest...")
    print(f"  Exit Rules: TP +5%, SL -2%, Timeout 30일")

    result = simple_backtest(
        signals=signals,
        price_data=df,
        take_profit=0.05,
        stop_loss=-0.02,
        max_hold_days=30
    )

    # 4. 결과 저장
    results_dir = Path(__file__).parent / 'results'
    results_dir.mkdir(exist_ok=True)

    result_file = results_dir / f'{TIMEFRAME}_{YEAR}_backtest.json'

    # Trades는 너무 크므로 제외
    result_summary = {k: v for k, v in result.items() if k != 'trades'}

    with open(result_file, 'w', encoding='utf-8') as f:
        json.dump(result_summary, f, indent=2, ensure_ascii=False)

    print(f"\n✅ Results saved: {result_file}")

    # 5. 결과 출력
    print("\n" + "="*70)
    print("📊 Backtest Results")
    print("="*70)
    print(f"Total Return: {result['total_return_pct']:.2f}%")
    print(f"Final Capital: {result['final_capital']:,.0f}원")
    print(f"Total Trades: {result['total_trades']}")
    print(f"Win Rate: {result['win_rate']:.1f}%")
    print(f"Avg Win: {result['avg_win_pct']:.2f}%")
    print(f"Avg Loss: {result['avg_loss_pct']:.2f}%")
    print(f"Max Drawdown: {result['max_drawdown']:.2f}%")
    print(f"Avg Hold: {result['avg_hold_days']:.1f}일")

    print(f"\nExit Reasons:")
    for reason, count in result['exit_reasons'].items():
        print(f"  {reason:10s}: {count:3d} ({count/result['total_trades']*100:5.1f}%)")

    print(f"\nMarket States:")
    for state, count in result['market_states'].items():
        print(f"  {state:20s}: {count:3d} ({count/result['total_trades']*100:5.1f}%)")

    print()


if __name__ == '__main__':
    main()
