# Session Summary (2026-02-18)

## 정리 범위
- 실험/튜닝/비교 과정에서 누적된 `reports/` 산출물(CSV/JSON/MD/TXT)을 정리했습니다.
- 임시 레짐 차트 검증 이미지(`*_fix_v2.png`, `*_fix_v3.png`)를 정리했습니다.
- 중복 연구 문서 초안(`docs/model_path_and_training_refresh_2026-02-18.md`, `docs/research_external_day_swing_2026-02-18.md`)은 제거했습니다.
- DL 실험 스크립트(`scripts/backtest/walkforward_dl_backtest.py`)를 정리했습니다.

## 현재 핵심 결론
- 운영 우선순위는 Long-only MLP 계열 전략입니다.
- 레짐 차트 표시 이슈(매수/매도 마커 미표시, 볼린저밴드 왜곡) 수정 반영:
  - 마커 addplot 경로 복구
  - 리샘플 구간 BB는 종가 기반으로 재계산
  - 마커 위치를 캔들 내부로 조정하여 가시성 개선

## 운영 전환 기준
- 7일 paper trading 검증 후 라이브 전환 판단:
  - 실행 안정성(프로세스/주문/데이터)
  - 백테스트 대비 성과 괴리
  - 손실 통제(MDD/연속손실) 기준 충족

## 비고
- 이 문서를 기준 요약 기록으로 유지합니다.
