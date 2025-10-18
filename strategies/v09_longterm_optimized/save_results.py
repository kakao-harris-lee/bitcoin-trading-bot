import json

output = {
    'best_params': {
        'trailing_stop_pct': 0.1752,
        'stop_loss_pct': 0.0540,
        'position_fraction': 0.95
    },
    'best_score': 2.1029,
    'train_results': {
        'period': '2018-09-04 ~ 2023-12-31',
        'total_return': 1612.06,
        'sharpe_ratio': 1.17,
        'max_drawdown': 64.60,
        'total_trades': 29,
        'win_rate': 0.207
    },
    '2024_validation': {
        'total_return': 100.36,
        'sharpe_ratio': 1.63,
        'max_drawdown': 33.15,
        'buyhold_return': 134.35,
        'excess_return': -33.99
    },
    '2025_test': {
        'total_return': 13.03,
        'sharpe_ratio': 0.64,
        'max_drawdown': 17.88,
        'buyhold_return': 20.15,
        'excess_return': -7.12
    },
    'overfitting': {
        'degradation_pct': 87.02,
        'passed': False
    }
}

with open('optuna_results.json', 'w') as f:
    json.dump(output, f, indent=2)

print("결과 저장 완료")
