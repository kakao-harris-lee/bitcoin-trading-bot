#!/usr/bin/env python3
"""
backtest.py
v03 전략 백테스팅 실행 스크립트
"""

import sys
sys.path.append('../..')

import json
import pandas as pd
import numpy as np
from datetime import datetime

from core.data_loader import DataLoader
from core.backtester import Backtester
from core.evaluator import Evaluator
from core.market_analyzer import MarketAnalyzer

from strategies.v01_adaptive_rsi_ml.ml_model import MLSignalValidator
from strategy import BullTrendHoldStrategy, v03_strategy_wrapper


def main():
    print("\n" + "="*60)
    print("v03: Bull Trend Hold 전략 백테스팅")
    print("="*60 + "\n")

    # 1. Config 로드
    with open('config.json', 'r') as f:
        config = json.load(f)

    print(f"✅ 전략: {config['strategy_name']} v{config['version']}")
    print(f"   타임프레임: {config['timeframe']}")
    print(f"   Kelly 비율: {config['kelly_fraction']}")
    print(f"   상승장 익절: {config['bull_hold']['take_profit']:.1%}")
    print(f"   상승장 손절: {config['bull_hold']['stop_loss']:.1%}\n")

    # 2. 데이터 로드
    print("📊 데이터 로드 중...")
    with DataLoader('../../upbit_bitcoin.db') as loader:
        df = loader.load_timeframe(
            config['timeframe'],
            start_date='2024-08-26',
            end_date='2024-12-30'
        )

    print(f"   기간: {df.iloc[0]['timestamp']} ~ {df.iloc[-1]['timestamp']}")
    print(f"   캔들 수: {len(df):,}개\n")

    # Buy&Hold 기준 계산
    start_price = df.iloc[0]['close']
    end_price = df.iloc[-1]['close']
    buy_hold_return = ((end_price - start_price) / start_price) * 100

    print(f"📈 Buy&Hold 기준:")
    print(f"   시작가: {start_price:,.0f}원")
    print(f"   종료가: {end_price:,.0f}원")
    print(f"   수익률: {buy_hold_return:+.2f}%\n")

    # 3. 지표 계산
    print("🔧 기술 지표 계산 중...")
    df = MarketAnalyzer.add_indicators(df, indicators=['rsi', 'macd', 'adx', 'atr', 'roc'])
    print(f"   완료 (RSI, MACD, ADX, ATR)\n")

    # 4. ML 모델 학습
    print("🤖 ML 모델 학습 중...")
    ml_model = MLSignalValidator(
        
        n_estimators=config['ml_model']['n_estimators'],
        max_depth=config['ml_model']['max_depth'],
        confidence_threshold=config['ml_model']['confidence_threshold']
    )

    training_window = min(config['ml_model']['training_window'], len(df) // 2)
    ml_model.train(df)
    print(f"   완료 (학습 데이터: {training_window}개)\n")

    # 5. 전략 인스턴스 생성
    strategy = BullTrendHoldStrategy(config, ml_model)

    # 6. 백테스팅 실행
    print("⚙️  백테스팅 실행 중...\n")
    backtester = Backtester(
        initial_capital=config['initial_capital'],
        fee_rate=config['fee_rate'],
        slippage=config['slippage']
    )

    results = backtester.run(
        df,
        v03_strategy_wrapper,
        {'strategy_instance': strategy}
    )

    # 7. 평가 지표 계산
    metrics = Evaluator.calculate_all_metrics(results)

    # 8. 결과 출력
    print("\n" + "="*60)
    print("📊 백테스팅 결과")
    print("="*60 + "\n")

    print(f"기간: {df.iloc[0]['timestamp']} ~ {df.iloc[-1]['timestamp']}")
    print(f"캔들 수: {len(df):,}개 ({config['timeframe']})\n")

    print(f"초기 자본: {metrics['initial_capital']:,.0f}원")
    print(f"최종 자본: {metrics['final_capital']:,.0f}원")
    print(f"총 수익: {metrics['final_capital'] - metrics['initial_capital']:,.0f}원\n")

    print(f"총 수익률: {metrics['total_return']:+.2f}%")
    print(f"Buy&Hold: {buy_hold_return:+.2f}%")
    print(f"초과 수익: {metrics['total_return'] - buy_hold_return:+.2f}%p\n")

    print(f"Sharpe Ratio: {metrics.get('sharpe_ratio', 0):.2f}")
    print(f"Max Drawdown: {metrics.get('max_drawdown', 0):.2f}%\n")

    print(f"총 거래: {metrics['total_trades']}회")
    print(f"승리 거래: {metrics.get('winning_trades', 0)}회")
    print(f"패배 거래: {metrics.get('losing_trades', 0)}회")
    print(f"승률: {metrics.get('win_rate', 0):.1%}\n")

    if metrics.get('avg_profit', 0) > 0:
        print(f"평균 수익: {metrics['avg_profit']:,.0f}원")
    if metrics.get('avg_loss', 0) > 0:
        print(f"평균 손실: {metrics['avg_loss']:,.0f}원")
    if metrics.get('profit_factor', 0) > 0:
        print(f"Profit Factor: {metrics['profit_factor']:.2f}\n")

    # 9. 목표 달성 여부
    print("="*60)
    print("🎯 목표 달성 여부")
    print("="*60 + "\n")

    target_return = buy_hold_return + 20
    sharpe_target = 1.0

    return_ok = "✅" if metrics['total_return'] >= target_return else "❌"
    sharpe_ok = "✅" if metrics.get('sharpe_ratio', 0) >= sharpe_target else "❌"

    print(f"{return_ok} 수익률: {metrics['total_return']:.2f}% (목표: {target_return:.2f}%)")
    print(f"{sharpe_ok} Sharpe Ratio: {metrics.get('sharpe_ratio', 0):.2f} (목표: {sharpe_target:.1f})\n")

    # 10. 결과 저장
    output = {
        'version': 'v03',
        'strategy_name': config['strategy_name'],
        'timeframe': config['timeframe'],
        'period': {
            'start': str(df.iloc[0]['timestamp']),
            'end': str(df.iloc[-1]['timestamp']),
            'candles': len(df)
        },
        'buy_hold': {
            'start_price': float(start_price),
            'end_price': float(end_price),
            'return': float(buy_hold_return)
        },
        'metrics': {
            'initial_capital': float(metrics['initial_capital']),
            'final_capital': float(metrics['final_capital']),
            'total_return': float(metrics['total_return']),
            'sharpe_ratio': float(metrics.get('sharpe_ratio', 0)),
            'max_drawdown': float(metrics.get('max_drawdown', 0)),
            'total_trades': int(metrics['total_trades']),
            'winning_trades': int(metrics.get('winning_trades', 0)),
            'losing_trades': int(metrics.get('losing_trades', 0)),
            'win_rate': float(metrics.get('win_rate', 0)),
            'avg_profit': float(metrics.get('avg_profit', 0)),
            'avg_loss': float(metrics.get('avg_loss', 0)),
            'profit_factor': float(metrics.get('profit_factor', 0))
        },
        'config': config,
        'timestamp': datetime.now().isoformat()
    }

    with open('results.json', 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print("💾 결과 저장 완료: results.json\n")


if __name__ == "__main__":
    main()
