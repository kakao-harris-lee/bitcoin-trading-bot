# Bull-Follow PnL Target Step 1+2 Results (2026-02-22)

## 목적
`목적함수 자체를 PnL 직접 최적화`하기 위해 target을 `forward return`에서 `pnl utility`로 변경하고,
요청 순서대로 1) base, 2) liquidity 확장까지 수행.

PnL utility 정의:
- `target_forward_pnl_utility = target_forward_return - fee_buffer - downside_penalty * abs(min(target_worst_drawdown, 0))`
- 이번 실행값: `fee_buffer=0.0012`, `downside_penalty=1.0`

## 공통 조건
- 데이터: `data/universe_backtest_4h` (spot, minute240)
- 기간: `2020-01-01` ~ `2026-02-22`
- 학습 종료: `2024-12-31`
- 포트폴리오 규칙: `top_k=8`, `min_adx=10`, `breakout_floor=-0.01`, `risk_on_breadth=0.45`

## 결과 비교

| Variant | min_score | Return % | MDD % | Sharpe | Alpha %p | Avg Selected |
|---|---:|---:|---:|---:|---:|---:|
| baseline (base+forward) | 0.001 | -60.48 | -64.36 | -1.746 | +17.04 | 1.221 |
| step1 (base+pnl) | 0.001 | -8.30 | -11.23 | -0.724 | +69.23 | 0.030 |
| step2 (liquidity+pnl) | 0.001 | -15.85 | -15.85 | -1.919 | +61.67 | 0.022 |
| step1 (base+pnl) | -0.02 | -63.58 | -65.52 | -2.933 | +13.94 | 1.168 |
| step2 (liquidity+pnl) | -0.02 | -60.95 | -63.72 | -2.827 | +16.57 | 1.168 |

## 해석
- `min_score=0.001`에서는 평균 진입 수가 0.03/0.02 수준으로 사실상 무거래에 가까움.
- 거래 빈도를 baseline 수준으로 맞춘(`min_score=-0.02`) 경우:
  - `liquidity+pnl`이 MDD는 소폭 개선(-63.72 vs -64.36)되지만,
  - Return/Sharpe가 baseline을 넘지 못함.
- 따라서 현재 시점에서는 **baseline(base+forward) 유지**가 타당.

## 산출물
- baseline: `reports/bull_follow_v1_base_forward_20260222_035553_summary.md`
- step1 (pnl, ms=0.001): `reports/bull_follow_v1_base_pnl_20260222_040607_summary.md`
- step2 (liq+pnl, ms=0.001): `reports/bull_follow_v1_liquidity_pnl_20260222_040727_summary.md`
- step1 (pnl, ms=-0.02): `reports/bull_follow_v1_base_pnl_20260222_040906_summary.md`
- step2 (liq+pnl, ms=-0.02): `reports/bull_follow_v1_liquidity_pnl_20260222_041030_summary.md`
