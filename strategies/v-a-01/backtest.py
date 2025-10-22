#!/usr/bin/env python3
"""
v-a-01 Backtest
===============
생성된 시그널을 백테스팅하고 재현율 계산
"""

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent.parent))

import json
import pandas as pd
from datetime import datetime, timedelta
from utils.perfect_signal_loader import PerfectSignalLoader
from utils.reproduction_calculator import ReproductionCalculator
from core.data_loader import DataLoader


def load_signals_from_json(json_file: Path) -> pd.DataFrame:
    """
    JSON 시그널 파일 로드

    Args:
        json_file: signals JSON 파일

    Returns:
        시그널 DataFrame
    """
    with open(json_file, 'r') as f:
        data = json.load(f)

    signals = []
    for sig in data['signals']:
        signals.append({
            'timestamp': pd.to_datetime(sig['timestamp']),
            'entry_price': sig['entry_price']
        })

    return pd.DataFrame(signals)


def simple_backtest(
    signals: pd.DataFrame,
    price_data: pd.DataFrame,
    holding_period: str = '30d',
    initial_capital: float = 10_000_000,
    fee_rate: float = 0.0005
) -> dict:
    """
    단순 백테스팅

    Args:
        signals: 시그널 DataFrame
        price_data: 가격 데이터
        holding_period: 보유 기간 (예: '30d' = 30일)
        initial_capital: 초기 자본
        fee_rate: 거래 수수료율

    Returns:
        백테스팅 결과
    """
    # 보유 기간 파싱
    if holding_period.endswith('d'):
        hold_days = int(holding_period[:-1])
    elif holding_period.endswith('h'):
        hold_days = int(holding_period[:-1]) / 24
    else:
        hold_days = 30  # 기본값

    capital = initial_capital
    trades = []
    position = None

    # Price data를 timestamp 인덱스로 설정
    price_data = price_data.set_index('timestamp') if 'timestamp' in price_data.columns else price_data

    for _, signal in signals.iterrows():
        entry_time = signal['timestamp']
        entry_price = signal['entry_price']

        # Exit 시간 계산
        exit_time = entry_time + timedelta(days=hold_days)

        # Exit price 찾기
        exit_data = price_data[price_data.index >= exit_time]
        if len(exit_data) == 0:
            continue

        exit_price = exit_data.iloc[0]['close']
        actual_exit_time = exit_data.index[0]

        # 수수료 포함 거래
        buy_amount = capital * (1 - fee_rate)
        btc_amount = buy_amount / entry_price

        sell_amount = btc_amount * exit_price
        sell_revenue = sell_amount * (1 - fee_rate)

        capital = sell_revenue

        # 수익률
        return_pct = (sell_revenue - initial_capital) / initial_capital

        # 보유 기간
        holding_hours = (actual_exit_time - entry_time).total_seconds() / 3600

        trades.append({
            'entry_time': entry_time,
            'entry_price': entry_price,
            'exit_time': actual_exit_time,
            'exit_price': exit_price,
            'return_pct': return_pct,
            'holding_hours': holding_hours,
            'profit': sell_revenue - initial_capital
        })

        # 복리 적용하려면 여기서 capital을 업데이트 (단순 비교를 위해 초기 자본 유지)
        capital = initial_capital

    # 통계 계산
    if len(trades) == 0:
        return {
            'total_trades': 0,
            'total_return': 0.0,
            'avg_return': 0.0,
            'win_rate': 0.0,
            'sharpe_ratio': 0.0
        }

    trades_df = pd.DataFrame(trades)

    total_return = trades_df['return_pct'].sum()
    avg_return = trades_df['return_pct'].mean()
    winning_trades = (trades_df['return_pct'] > 0).sum()
    win_rate = winning_trades / len(trades) if len(trades) > 0 else 0

    # Sharpe Ratio (간이 계산)
    if trades_df['return_pct'].std() > 0:
        sharpe = avg_return / trades_df['return_pct'].std()
    else:
        sharpe = 0

    return {
        'total_trades': len(trades),
        'total_return': total_return,
        'avg_return': avg_return,
        'win_rate': win_rate,
        'winning_trades': int(winning_trades),
        'losing_trades': len(trades) - int(winning_trades),
        'sharpe_ratio': sharpe,
        'avg_holding_hours': trades_df['holding_hours'].mean(),
        'trades': trades
    }


def main():
    """메인 실행"""

    print("=" * 60)
    print("v-a-01 Backtest: Perfect Signal Reproduction")
    print("=" * 60)
    print()

    # 설정
    TIMEFRAME = 'day'
    YEAR = 2024
    HOLDING_PERIOD = '30d'  # 완벽한 시그널 평균 보유 기간

    # 1. 시그널 로드
    print("📊 Loading signals...")
    signal_file = Path(__file__).parent / 'signals' / f'{TIMEFRAME}_{YEAR}_signals.json'
    strategy_signals = load_signals_from_json(signal_file)
    print(f"  Strategy signals: {len(strategy_signals)}개")

    # 2. 완벽한 시그널 로드
    print("📈 Loading perfect signals...")
    loader = PerfectSignalLoader()
    perfect_signals = loader.load_perfect_signals(TIMEFRAME, YEAR)
    perfect_stats = loader.analyze_perfect_signals(perfect_signals)
    print(f"  Perfect signals: {len(perfect_signals)}개")
    print(f"  Perfect avg return: {perfect_stats['avg_return']:.2%}")
    print()

    # 3. 가격 데이터 로드
    print("📊 Loading market data...")
    db_path = Path(__file__).parent.parent.parent / 'upbit_bitcoin.db'
    data_loader = DataLoader(str(db_path))
    price_data = data_loader.load_timeframe(
        timeframe=TIMEFRAME,
        start_date=f'{YEAR}-01-01',
        end_date=f'{YEAR}-12-31'
    )
    print(f"  Market data: {len(price_data)} candles")
    print()

    # 4. 백테스팅
    print(f"🎯 Running backtest (holding period: {HOLDING_PERIOD})...")
    backtest_result = simple_backtest(
        signals=strategy_signals,
        price_data=price_data,
        holding_period=HOLDING_PERIOD
    )

    print(f"  Total trades: {backtest_result['total_trades']}")
    print(f"  Total return: {backtest_result['total_return']:.2%}")
    print(f"  Avg return: {backtest_result['avg_return']:.2%}")
    print(f"  Win rate: {backtest_result['win_rate']:.2%}")
    print(f"  Sharpe Ratio: {backtest_result['sharpe_ratio']:.2f}")
    print()

    # 5. 재현율 계산
    print("📊 Calculating reproduction rate...")
    calc = ReproductionCalculator(tolerance_days=1)

    reproduction_result = calc.calculate_reproduction_rate(
        strategy_signals=strategy_signals,
        perfect_signals=perfect_signals,
        strategy_return=backtest_result['total_return'],
        perfect_return=perfect_stats['avg_return'] * len(perfect_signals)  # 총 수익
    )

    print(f"  Signal Reproduction: {reproduction_result['signal_reproduction_rate']:.2%}")
    print(f"  Return Reproduction: {reproduction_result['return_reproduction_rate']:.2%}")
    print(f"  Total Reproduction: {reproduction_result['total_reproduction_rate']:.2%}")
    print(f"  Tier: {reproduction_result['tier']}")
    print()

    # 6. 결과 저장
    print("💾 Saving results...")

    results_dir = Path(__file__).parent / 'results'
    results_dir.mkdir(exist_ok=True)

    results_file = results_dir / f'{TIMEFRAME}_{YEAR}_backtest.json'

    final_results = {
        'strategy': 'v-a-01',
        'timeframe': TIMEFRAME,
        'year': YEAR,
        'holding_period': HOLDING_PERIOD,
        'backtest': {
            'total_trades': backtest_result['total_trades'],
            'total_return': float(backtest_result['total_return']),
            'avg_return': float(backtest_result['avg_return']),
            'win_rate': float(backtest_result['win_rate']),
            'winning_trades': backtest_result['winning_trades'],
            'losing_trades': backtest_result['losing_trades'],
            'sharpe_ratio': float(backtest_result['sharpe_ratio']),
            'avg_holding_hours': float(backtest_result['avg_holding_hours'])
        },
        'reproduction': {
            'signal_reproduction_rate': float(reproduction_result['signal_reproduction_rate']),
            'return_reproduction_rate': float(reproduction_result['return_reproduction_rate']),
            'total_reproduction_rate': float(reproduction_result['total_reproduction_rate']),
            'tier': reproduction_result['tier'],
            'matched_signals': reproduction_result['matched_signals'],
            'total_strategy_signals': reproduction_result['total_strategy_signals'],
            'total_perfect_signals': reproduction_result['total_perfect_signals']
        },
        'perfect_signals': {
            'total': len(perfect_signals),
            'avg_return': float(perfect_stats['avg_return']),
            'avg_hold_days': float(perfect_stats['avg_hold_days'])
        }
    }

    with open(results_file, 'w', encoding='utf-8') as f:
        json.dump(final_results, f, indent=2, ensure_ascii=False)

    print(f"✅ Results saved: {results_file}")
    print()

    # 7. 최종 요약
    print("=" * 60)
    print("📊 Final Summary")
    print("=" * 60)
    print(f"Strategy: v-a-01 (Simple RSI + MFI)")
    print(f"Timeframe: {TIMEFRAME}, Year: {YEAR}")
    print()
    print(f"✅ Backtest Results:")
    print(f"  - Total Return: {backtest_result['total_return']:.2%}")
    print(f"  - Win Rate: {backtest_result['win_rate']:.2%}")
    print(f"  - Sharpe Ratio: {backtest_result['sharpe_ratio']:.2f}")
    print()
    print(f"🎯 Reproduction Rate:")
    print(f"  - Signal: {reproduction_result['signal_reproduction_rate']:.2%}")
    print(f"  - Return: {reproduction_result['return_reproduction_rate']:.2%}")
    print(f"  - Total: {reproduction_result['total_reproduction_rate']:.2%}")
    print(f"  - Tier: {reproduction_result['tier']}")
    print()

    if reproduction_result['tier'] in ['S', 'A']:
        print("🌟 Excellent! 높은 재현율 달성!")
    elif reproduction_result['tier'] == 'B':
        print("👍 Good! 개선 여지 있음")
    else:
        print("⚠️  낮은 재현율. 전략 개선 필요")

    print()


if __name__ == '__main__':
    main()
