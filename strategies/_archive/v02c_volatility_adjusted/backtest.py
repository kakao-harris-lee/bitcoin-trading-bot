#!/usr/bin/env python3
"""
backtest.py
v02b 백테스팅 - 분할 매도
"""

import sys
sys.path.append('../..')

import json
from pathlib import Path
from datetime import datetime
from core.data_loader import DataLoader
from core.backtester import Backtester
from core.evaluator import Evaluator
from market_classifier import add_market_indicators
from ml_model import MLSignalValidator
from strategy import VolatilityAdjustedStrategy, v02c_strategy_wrapper


def main():
    print("="*70)
    print("v02c 백테스팅: 동적 Kelly + 분할 매도 + 변동성 조정")
    print("="*70)

    # Config 로드
    config_path = Path(__file__).parent / 'config.json'
    with open(config_path) as f:
        config = json.load(f)

    # 데이터 로드
    db_path = Path(__file__).parent / '../../upbit_bitcoin.db'
    
    with DataLoader(str(db_path)) as loader:
        df = loader.load_timeframe(
            config['timeframe'],
            start_date='2024-09-01',
            end_date='2024-12-31'
        )

    # 지표 추가
    df = add_market_indicators(df)

    # Buy&Hold 기준선 계산
    start_price = df.iloc[0]['close']
    end_price = df.iloc[-1]['close']
    buy_hold_return = ((end_price - start_price) / start_price) * 100
    target_return = buy_hold_return + 20  # Buy&Hold + 20%p

    # ML 모델 로드
    model_path = Path(__file__).parent / 'v01_model.pkl'
    ml_model = MLSignalValidator(
        n_estimators=config['ml_model']['n_estimators'],
        max_depth=config['ml_model']['max_depth'],
        confidence_threshold=config['ml_model']['confidence_threshold'],
        model_path=str(model_path)
    )

    # 전략 인스턴스
    strategy_instance = VolatilityAdjustedStrategy(config, ml_model)

    # 백테스팅
    backtester = Backtester(
        initial_capital=config['initial_capital'],
        fee_rate=config['fee_rate'],
        slippage=config['slippage']
    )

    results = backtester.run(df, v02c_strategy_wrapper,
                            {'strategy_instance': strategy_instance})

    # 평가
    evaluator = Evaluator()
    metrics = evaluator.calculate_all_metrics(results)

    # Kelly 이력
    kelly_history = strategy_instance.get_kelly_history()

    # 개선된 보고서
    print(f"\n{'='*70}")
    print("백테스팅 기간")
    print(f"{'='*70}")
    print(f"시작: {df.iloc[0]['timestamp']} (시작가: {start_price:,.0f}원)")
    print(f"종료: {df.iloc[-1]['timestamp']} (종료가: {end_price:,.0f}원)")
    
    start_date = datetime.strptime(str(df.iloc[0]['timestamp']), '%Y-%m-%d %H:%M:%S')
    end_date = datetime.strptime(str(df.iloc[-1]['timestamp']), '%Y-%m-%d %H:%M:%S')
    days = (end_date - start_date).days
    months = days / 30
    
    print(f"기간: {days}일 ({months:.1f}개월) | 캔들: {len(df):,}개")

    print(f"\n{'='*70}")
    print("Buy&Hold 기준선")
    print(f"{'='*70}")
    print(f"시작가: {start_price:,.0f}원")
    print(f"종료가: {end_price:,.0f}원")
    print(f"수익률: {buy_hold_return:+.2f}%")
    print(f"목표: Buy&Hold + 20%p = {target_return:+.2f}%")

    print(f"\n{'='*70}")
    print("전략 성과")
    print(f"{'='*70}")
    print(f"초기 자본:   {metrics['initial_capital']:>15,.0f}원")
    print(f"최종 자본:   {metrics['final_capital']:>15,.0f}원")
    abs_profit = metrics['final_capital'] - metrics['initial_capital']
    print(f"절대 수익:   {abs_profit:>+15,.0f}원")
    diff_from_buyhold = metrics['total_return'] - buy_hold_return
    print(f"수익률:      {metrics['total_return']:>+15.2f}% (vs Buy&Hold: {diff_from_buyhold:+.2f}%p)")
    
    target_achieved = metrics['total_return'] >= target_return
    print(f"목표 달성:   {'✅ YES' if target_achieved else '❌ NO'}")

    print(f"\n{'='*70}")
    print("리스크 지표")
    print(f"{'='*70}")
    sharpe_achieved = metrics['sharpe_ratio'] >= 1.0
    mdd_achieved = abs(metrics['max_drawdown']) <= 30
    print(f"Sharpe Ratio:  {metrics['sharpe_ratio']:>10.2f} (목표 >= 1.0) {'✅' if sharpe_achieved else '❌'}")
    print(f"Max Drawdown:  {metrics['max_drawdown']:>10.2f}% (목표 <= 30%) {'✅' if mdd_achieved else '❌'}")
    print(f"Sortino Ratio: {metrics.get('sortino_ratio', 0):>10.2f}")

    print(f"\n{'='*70}")
    print("거래 통계")
    print(f"{'='*70}")
    print(f"총 거래:     {metrics['total_trades']:>10d}회")
    print(f"승리/패배:   {metrics['winning_trades']:>10d}회 / {metrics['losing_trades']}회")
    print(f"승률:        {metrics['win_rate']:>10.1%}")
    print(f"평균 수익:   {metrics.get('avg_profit_pct', 0):>10.2f}%")
    print(f"평균 손실:   {metrics.get('avg_loss_pct', 0):>10.2f}%")
    print(f"Profit Factor: {metrics['profit_factor']:>8.2f}")

    print(f"\n{'='*70}")
    print("Kelly Criterion 추적")
    print(f"{'='*70}")
    print(f"초기 Kelly:  {config['kelly_settings']['initial_fraction']:.2%}")
    
    if len(strategy_instance.trade_history) >= 50:
        print(f"50회 후:     {kelly_history[0]['kelly_quarter']:.2%} (승률: {kelly_history[0]['win_rate']:.1%})")
        if len(kelly_history) > 1:
            print(f"100회 후:    {kelly_history[1]['kelly_quarter']:.2%} (승률: {kelly_history[1]['win_rate']:.1%})")
        print(f"최종 Kelly:  {strategy_instance.current_kelly:.2%}")
    else:
        print(f"최종 Kelly:  {strategy_instance.current_kelly:.2%} (거래 부족, 동적 Kelly 미적용)")

    print(f"\n{'='*70}")
    print("종합 평가")
    print(f"{'='*70}")
    
    all_checks = [
        ('수익률 >= 목표', target_achieved),
        ('Sharpe >= 1.0', sharpe_achieved),
        ('MDD <= 30%', mdd_achieved)
    ]
    
    for desc, passed in all_checks:
        print(f"{'✅' if passed else '❌'} {desc}")
    
    all_passed = all(check[1] for check in all_checks)
    
    if all_passed:
        print(f"\n🎉 모든 목표 달성!")
    else:
        print(f"\n⚠️  일부 목표 미달")
    
    print(f"{'='*70}\n")

    # 결과 저장
    results_path = Path(__file__).parent / 'results.json'
    with open(results_path, 'w', encoding='utf-8') as f:
        json.dump({
            'version': config['version'],
            'strategy_name': config['strategy_name'],
            'metrics': metrics,
            'buy_hold': {
                'start_price': float(start_price),
                'end_price': float(end_price),
                'return': float(buy_hold_return),
                'target': float(target_return)
            },
            'kelly_history': kelly_history,
            'final_kelly': float(strategy_instance.current_kelly)
        }, f, indent=2, default=str, ensure_ascii=False)

    print(f"✅ 결과 저장: {results_path}")


if __name__ == "__main__":
    main()
