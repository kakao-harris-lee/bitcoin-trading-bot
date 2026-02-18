# Paper Strategy Promotion Gates

Date: 2026-02-18  
Scope: Spot, long-only, paper trading strategy replacement and A/B start conditions.

## 1) Current Decision (Hard Rule)

- 신규 전략이 현재 운영 전략 대비 백테스트 우위를 증명하지 못하면:
  - 교체하지 않는다.
  - A/B 테스트도 시작하지 않는다.

## 2) Promotion Gate (All Required)

신규 전략이 아래를 모두 만족할 때만 교체 후보로 인정한다.

1. 동일 조건 비교
- 동일 기간
- 동일 포지션 비중 (current allocation 기준)
- 동일 수수료/슬리피지/데이터 소스(spot)

2. 수익 우위 (Primary)
- Portfolio `alpha_vs_bh > 0`
- 자산별 결과가 아닌 포트폴리오 기준으로 판정

3. 리스크 비열화 (Secondary)
- Portfolio MDD가 현재 운영 전략보다 악화되지 않아야 함
- 예외 허용은 사전 합의 시에만 적용

4. 재현성
- 최소 2개 구간(전체 구간 + 최근 구간)에서 동일 결론(우위) 확인

## 3) Promotion Workflow

1. Backtest: 동일 조건으로 current vs candidate 비교
2. Gate 판정: 2장 조건 전부 확인
3. Pass일 때만 제한된 paper A/B 진행
4. Fail이면 즉시 중단, current 유지

## 4) 2026-02-18 Baseline Status

아래 결과 기준으로 신규 확장 후보는 gate 미통과:

- `reports/optuna_mlp_extended_tuning_2020-01-01_2026-02-18_20260218_143832_summary.csv`
- `reports/optuna_mlp_extended_tuning_2020-01-01_2026-02-18_20260218_143832.md`

요약:
- ETH best alpha: -14.0443
- BNB best alpha: -36.9721
- BTC(동일 세션 집계) best alpha: -2.2616
- 결론: `alpha_vs_bh > 0` 미충족, 교체/A-B 중단 유지
