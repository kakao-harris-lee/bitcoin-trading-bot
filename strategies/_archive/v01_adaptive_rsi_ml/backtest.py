#!/usr/bin/env python3
"""
backtest.py
v01 백테스팅 실행 스크립트
"""

import sys
sys.path.append('../..')

import json
from pathlib import Path
from core.data_loader import DataLoader
from core.backtester import Backtester
from core.evaluator import Evaluator
from market_classifier import add_market_indicators
from ml_model import MLSignalValidator
from strategy import AdaptiveRSIMLStrategy, v01_strategy_wrapper


def main():
    print("="*60)
    print("v01 백테스팅 시작")
    print("="*60)

    # 1. Config 로드
    config_path = Path(__file__).parent / 'config.json'
    with open(config_path) as f:
        config = json.load(f)

    print(f"\n📋 전략: {config['strategy_name']} v{config['version']}")
    print(f"   타임프레임: {config['timeframe']}")
    print(f"   초기 자본: {config['initial_capital']:,}원")

    # 2. 데이터 로드
    db_path = Path(__file__).parent / '../../upbit_bitcoin.db'
    print(f"\n📊 데이터 로드 중...")

    with DataLoader(str(db_path)) as loader:
        # 백테스트: 2024-09-01 ~ 2024-12-31 (학습과 동일 기간)
        df = loader.load_timeframe(
            config['timeframe'],
            start_date='2024-09-01',
            end_date='2024-12-31'
        )

    print(f"   ✅ {len(df)} 레코드 로드")
    print(f"   기간: {df.iloc[0]['timestamp']} ~ {df.iloc[-1]['timestamp']}")

    # 3. 지표 추가
    print(f"\n🔧 기술 지표 계산 중...")
    df = add_market_indicators(df)

    # 4. ML 모델 로드
    model_path = Path(__file__).parent / 'v01_model.pkl'

    if not model_path.exists():
        print(f"\n⚠️  모델 파일이 없습니다: {model_path}")
        print(f"   먼저 'python train_model.py'를 실행하세요.")
        return

    print(f"\n🤖 ML 모델 로드 중...")
    ml_model = MLSignalValidator(
        n_estimators=config['ml_model']['n_estimators'],
        max_depth=config['ml_model']['max_depth'],
        confidence_threshold=config['ml_model']['confidence_threshold'],
        model_path=str(model_path)
    )

    # 5. 전략 인스턴스 생성
    strategy_instance = AdaptiveRSIMLStrategy(config, ml_model)

    # 6. 백테스팅 실행
    print(f"\n🚀 백테스팅 실행 중...")
    backtester = Backtester(
        initial_capital=config['initial_capital'],
        fee_rate=config['fee_rate'],
        slippage=config['slippage']
    )

    results = backtester.run(
        df,
        v01_strategy_wrapper,
        {'strategy_instance': strategy_instance}
    )

    # 7. 평가
    print(f"\n📈 성과 평가 중...")
    evaluator = Evaluator()
    metrics = evaluator.calculate_all_metrics(results)

    # 8. 결과 출력
    print(f"\n{'='*60}")
    print(f"백테스팅 결과")
    print(f"{'='*60}")
    print(f"총 수익률:        {metrics['total_return']:>10.2f}%")
    print(f"최종 자본:        {metrics['final_capital']:>10,.0f}원")
    print(f"Sharpe Ratio:     {metrics['sharpe_ratio']:>10.2f}")
    print(f"Max Drawdown:     {metrics['max_drawdown']:>10.2f}%")
    print(f"승률:             {metrics['win_rate']:>10.1%}")
    print(f"Profit Factor:    {metrics['profit_factor']:>10.2f}")
    print(f"총 거래 횟수:     {metrics['total_trades']:>10d}")
    print(f"승리 거래:        {metrics['winning_trades']:>10d}")
    print(f"패배 거래:        {metrics['losing_trades']:>10d}")
    print(f"평균 수익:        {metrics['avg_profit']:>10.2f}%")
    print(f"평균 손실:        {metrics['avg_loss']:>10.2f}%")
    print(f"{'='*60}\n")

    # 9. 결과 저장
    results_path = Path(__file__).parent / 'results.json'
    with open(results_path, 'w', encoding='utf-8') as f:
        json.dump({
            'version': config['version'],
            'strategy_name': config['strategy_name'],
            'config': config,
            'metrics': metrics,
            'data_period': {
                'start': str(df.iloc[0]['timestamp']),
                'end': str(df.iloc[-1]['timestamp']),
                'records': len(df)
            }
        }, f, indent=2, default=str, ensure_ascii=False)

    print(f"✅ 결과 저장 완료: {results_path}")

    # 10. 목표 달성 여부
    print(f"\n{'='*60}")
    print(f"목표 달성 여부")
    print(f"{'='*60}")

    target_return = 10.0  # 10%
    target_sharpe = 1.0
    target_mdd = 30.0

    checks = []
    checks.append(('총 수익률 >= 10%', metrics['total_return'] >= target_return))
    checks.append(('Sharpe Ratio >= 1.0', metrics['sharpe_ratio'] >= target_sharpe))
    checks.append(('Max Drawdown <= 30%', abs(metrics['max_drawdown']) <= target_mdd))

    for desc, passed in checks:
        status = "✅" if passed else "❌"
        print(f"{status} {desc}")

    all_passed = all(check[1] for check in checks)

    if all_passed:
        print(f"\n🎉 목표 달성! 다음 단계로 진행 가능합니다.")
    else:
        print(f"\n⚠️  목표 미달. 하이퍼파라미터 조정 또는 전략 개선이 필요합니다.")

    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
