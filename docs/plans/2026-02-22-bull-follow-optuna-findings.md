# Bull-Follow Optuna Findings (2026-02-22)

## 목적
`bull_follow` 포트폴리오 실행 파라미터(`top_k`, `min_score`, `min_adx`, `breakout_floor`, `risk_on_breadth`)를 Optuna로 탐색하여 baseline 대비 개선 가능성을 검증.

## 데이터/평가 셋
- 데이터: `data/universe_backtest_4h` (spot, minute240)
- 기간: `2020-01-01` ~ `2026-02-22`
- 학습 종료: `2024-12-31`
- 유효 심볼: train/test 교집합 `64`

## Baseline
- config: `top_k=8, min_score=0.001, min_adx=10.0, breakout_floor=-0.01, risk_on_breadth=0.45`
- return: `-60.48%`
- alpha(vs EW B&H): `+17.04%p`
- mdd: `-64.36%`
- sharpe: `-1.746`

## 탐색 결과 요약
1) unconstrained alpha-max (10 trials)
- summary: `reports/bull_follow_optuna_20260222_012707_summary.md`
- 최적 trial은 `return=0.00%, mdd=0.00%` (거의 무거래)로 alpha만 최대화하는 퇴행 해.

2) constrained activity (8 trials)
- constraints: `avg_selected_count >= 1.0`, `risk_on_bars >= 500`
- summary: `reports/bull_follow_optuna_20260222_013750_summary.md`
- best valid trial: `return=-70.41%, alpha=+7.11%p, mdd=-71.63%`
- baseline 대비 전 항목 악화.

## 결론
- 현재 고정 모델 + 실행 파라미터만으로는 baseline을 상회하지 못함.
- 유효 개선은 실행 파라미터보다 **모델 신호 품질(예측력/랭킹 IC)** 개선이 선행되어야 함.

## 권장 후속
- baseline 유지 (paper 설정 교체 보류).
- 다음 실험 우선순위:
  - 목적함수를 거래 PnL 직접 최적화로 재학습(분류→회귀/랭킹 재정의).
  - cross-sectional target을 `forward excess return`으로 교체.
  - 진입 점수 자체에 volume/liquidity 품질 feature 확장 후 모델 재학습.
