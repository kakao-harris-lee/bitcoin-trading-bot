# Bull-Follow Step 1+2 Results (2026-02-22)

## 실행 순서
1. Step 1: `target_mode=excess`, `feature_profile=base`
2. Step 2: `target_mode=excess`, `feature_profile=liquidity`

동일 백테스트 조건:
- 데이터: `data/universe_backtest_4h` (spot, minute240)
- 기간: `2020-01-01` ~ `2026-02-22`
- 학습 종료: `2024-12-31`
- 포트폴리오 규칙: `top_k=8`, `min_score=0.001`, `min_adx=10`, `breakout_floor=-0.01`, `risk_on_breadth=0.45`

## 결과 요약

| Variant | Return % | MDD % | Sharpe | EW B&H % | Alpha %p | IC | Avg Selected |
|---|---:|---:|---:|---:|---:|---:|---:|
| base+forward (baseline) | -60.48 | -64.36 | -1.746 | -77.52 | +17.04 | -0.00657 | 1.22 |
| base+excess (Step 1) | -72.05 | -75.77 | -2.529 | -77.52 | +5.47 | -0.00761 | 1.50 |
| liquidity+excess (Step 2) | -74.56 | -78.23 | -2.789 | -77.52 | +2.96 | -0.00554 | 1.50 |

## 산출물
- baseline: `reports/bull_follow_v1_base_forward_20260222_035553_summary.md`
- step1: `reports/bull_follow_v1_base_excess_20260222_035718_summary.md`
- step2: `reports/bull_follow_v1_liquidity_excess_20260222_035848_summary.md`

## 결론
- 요청한 순서(1번 → 2번)로 구현/검증 완료.
- 두 단계 모두 baseline 대비 **수익률, MDD, Sharpe가 악화**.
- 현재 운영 기준에서는 `base+forward` baseline 유지가 타당.
