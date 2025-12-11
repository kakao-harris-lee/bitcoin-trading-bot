#!/usr/bin/env python3
"""
v09 전략 Optuna 하이퍼파라미터 최적화

학습: 2018-09-04 ~ 2023-12-31 (5.3년)
검증: 2024-01-01 ~ 2024-12-31
테스트: 2025-01-01 ~ 2025-10-17
"""

import sys
sys.path.append('../..')

import json
import optuna
from optuna.samplers import TPESampler
from optuna.pruners import MedianPruner
from backtest_simple import run_backtest
from core.data_loader import DataLoader


def objective(trial):
    """Optuna 목적 함수"""
    # 파라미터 샘플링
    params = {
        'trailing_stop_pct': trial.suggest_float('trailing_stop_pct', 0.08, 0.25),
        'stop_loss_pct': trial.suggest_float('stop_loss_pct', 0.05, 0.20),
        'position_fraction': 0.95  # 고정
    }

    # 백테스팅 (2018-09-04 ~ 2023-12-31)
    try:
        results = run_backtest('2018-09-04', '2023-12-31', params)
    except Exception as e:
        print(f"Trial {trial.number} 실패: {e}")
        return -999

    # 제약 조건
    if results['total_trades'] < 5:
        return -999

    if results['sharpe_ratio'] < 0.5:
        return -999

    if results['max_drawdown'] > 70:
        return -999

    # 다중 목표 최적화
    return_score = results['total_return'] / 400  # 목표 400% (5년)
    sharpe_score = results['sharpe_ratio'] / 1.5
    mdd_penalty = max(0, results['max_drawdown'] - 50) / 20

    score = 0.5 * return_score + 0.3 * sharpe_score - 0.2 * mdd_penalty

    # 진행 상황
    if trial.number % 10 == 0:
        print(f"\nTrial {trial.number}: "
              f"Return={results['total_return']:.1f}%, "
              f"Sharpe={results['sharpe_ratio']:.2f}, "
              f"MDD={results['max_drawdown']:.1f}%, "
              f"Score={score:.4f}")

    return score


def main():
    print("="*80)
    print("v09 하이퍼파라미터 최적화 (Optuna)")
    print("="*80)
    print(f"\n학습 기간: 2018-09-04 ~ 2023-12-31 (5.3년)")
    print(f"Trials: 300회")
    print(f"예상 시간: 10~15분\n")

    # Optuna Study
    study = optuna.create_study(
        direction='maximize',
        sampler=TPESampler(seed=42),
        pruner=MedianPruner(n_startup_trials=20, n_warmup_steps=10)
    )

    # 최적화 실행
    study.optimize(objective, n_trials=300, show_progress_bar=True)

    # 최적 파라미터
    print("\n" + "="*80)
    print("최적화 완료")
    print("="*80)

    best_params = study.best_params
    best_value = study.best_value

    print(f"\n최고 점수: {best_value:.4f}")
    print(f"\n최적 파라미터:")
    for key, value in best_params.items():
        print(f"  {key}: {value:.4f}")

    # 최적 파라미터로 재실행
    full_params = {**best_params, 'position_fraction': 0.95}

    print(f"\n{'='*80}")
    print("최적 파라미터 재검증")
    print(f"{'='*80}\n")

    # 학습 데이터
    print("[1/3] 학습 데이터 (2018-09-04 ~ 2023-12-31)")
    results_train = run_backtest('2018-09-04', '2023-12-31', full_params)
    print(f"  수익률: {results_train['total_return']:.2f}%")
    print(f"  Sharpe: {results_train['sharpe_ratio']:.2f}")
    print(f"  MDD: {results_train['max_drawdown']:.2f}%")
    print(f"  거래: {results_train['total_trades']}회")
    print(f"  승률: {results_train['win_rate']:.1%}\n")

    # 2024년 검증
    print("[2/3] 2024년 Out-of-Sample 검증")
    results_2024 = run_backtest('2024-01-01', '2024-12-31', full_params)

    with DataLoader('../../upbit_bitcoin.db') as loader:
        df_2024 = loader.load_timeframe('day', start_date='2024-01-01', end_date='2024-12-31')
    bh_2024 = ((df_2024.iloc[-1]['close'] - df_2024.iloc[0]['close']) / df_2024.iloc[0]['close']) * 100

    print(f"  수익률: {results_2024['total_return']:.2f}%")
    print(f"  Sharpe: {results_2024['sharpe_ratio']:.2f}")
    print(f"  MDD: {results_2024['max_drawdown']:.2f}%")
    print(f"  Buy&Hold: {bh_2024:.2f}%")
    print(f"  초과: {results_2024['total_return'] - bh_2024:+.2f}%p\n")

    # 2025년 테스트
    print("[3/3] 2025년 Final Test")
    results_2025 = run_backtest('2025-01-01', '2025-10-17', full_params)

    with DataLoader('../../upbit_bitcoin.db') as loader:
        df_2025 = loader.load_timeframe('day', start_date='2025-01-01', end_date='2025-10-17')
    bh_2025 = ((df_2025.iloc[-1]['close'] - df_2025.iloc[0]['close']) / df_2025.iloc[0]['close']) * 100

    print(f"  수익률: {results_2025['total_return']:.2f}%")
    print(f"  Sharpe: {results_2025['sharpe_ratio']:.2f}")
    print(f"  MDD: {results_2025['max_drawdown']:.2f}%")
    print(f"  Buy&Hold: {bh_2025:.2f}%")
    print(f"  초과: {results_2025['total_return'] - bh_2025:+.2f}%p\n")

    # 오버피팅 분석
    degradation = ((results_2024['total_return'] - results_2025['total_return']) / results_2024['total_return']) * 100 if results_2024['total_return'] > 0 else 0

    print(f"{'='*80}")
    print("오버피팅 분석")
    print(f"{'='*80}")
    print(f"2024년: {results_2024['total_return']:.2f}%")
    print(f"2025년: {results_2025['total_return']:.2f}%")
    print(f"성능 저하: {degradation:.2f}%")

    status = "✅ 목표 달성" if degradation < 70 else "❌ 목표 미달"
    print(f"{status} (목표: < 70%)\n")

    # 결과 저장
    output = {
        'best_params': full_params,
        'best_score': float(best_value),
        'train_results': {
            'period': '2018-09-04 ~ 2023-12-31',
            'total_return': float(results_train['total_return']),
            'sharpe_ratio': float(results_train['sharpe_ratio']),
            'max_drawdown': float(results_train['max_drawdown']),
            'total_trades': int(results_train['total_trades']),
            'win_rate': float(results_train['win_rate'])
        },
        '2024_validation': {
            'total_return': float(results_2024['total_return']),
            'sharpe_ratio': float(results_2024['sharpe_ratio']),
            'max_drawdown': float(results_2024['max_drawdown']),
            'buyhold_return': float(bh_2024),
            'excess_return': float(results_2024['total_return'] - bh_2024)
        },
        '2025_test': {
            'total_return': float(results_2025['total_return']),
            'sharpe_ratio': float(results_2025['sharpe_ratio']),
            'max_drawdown': float(results_2025['max_drawdown']),
            'buyhold_return': float(bh_2025),
            'excess_return': float(results_2025['total_return'] - bh_2025)
        },
        'overfitting': {
            'degradation_pct': float(degradation),
            'passed': degradation < 70
        }
    }

    with open('optuna_results.json', 'w') as f:
        json.dump(output, f, indent=2)

    print(f"결과 저장: optuna_results.json\n")


if __name__ == '__main__':
    main()
