# v41 Phase 0 전수 신호 분석 - 최종 요약

## 📊 분석 완료 현황

### ✅ 완료된 타임프레임 (3개)

| 타임프레임 | 기간 | 캔들 수 | 매수 신호 | 신호 발생률 | 파일 크기 |
|-----------|------|--------|---------|-----------|---------|
| **minute5** | 2024-01-01 ~ 2024-12-28 | 105,123 | 2,332 | 2.22% | 889KB |
| **minute15** | 2023-01-31 ~ 2024-12-30 | 67,189 | 36,568 | 54.43% | 16.5MB |
| **minute60** | 2020-01-02 ~ 2024-12-29 | 43,790 | 6,185 | 14.12% | 2.8MB |

**총합**: 216,102 캔들 분석 → **45,085개 매수 신호** 추출

---

## 📁 생성된 파일

```
strategies/v41_scalping_voting/analysis/signals/
├── signals_minute5_buy.csv    (889KB, 2,332 신호)
├── signals_minute15_buy.csv   (16.5MB, 36,568 신호)
└── signals_minute60_buy.csv   (2.8MB, 6,185 신호)
```

---

## 🔍 주요 발견사항

### 1. 신호 발생률 차이
- **minute15: 54.43%** → 매우 높음 (과도한 신호?)
- **minute60: 14.12%** → 적정 수준
- **minute5: 2.22%** → 매우 낮음 (보수적)

### 2. 데이터 커버리지
- **minute60**: 5년 데이터 (2020~2024) ✅ 최고
- **minute15**: 2년 데이터 (2023~2024)
- **minute5**: 1년 데이터 (2024)

### 3. 파일 크기 vs 신호 수
- minute15가 minute60보다 6배 큰 파일 → 더 많은 지표 데이터 저장?
- 평균 신호당 크기: minute5 (381B), minute15 (451B), minute60 (452B)

---

## 📋 다음 단계 (Phase 0 Lookforward Analysis)

### 1. 신호별 성과 추적
각 신호 발생 후 N 캔들 동안의 성과 측정:

```python
# 예시: +1 캔들, +3 캔들, +5 캔들, +10 캔들 후 수익률
lookforward_periods = [1, 3, 5, 10, 20, 50]

for signal in signals:
    for n in lookforward_periods:
        future_return = calculate_return(signal, n)
        win = future_return > 0
        # 승률, 평균수익, 평균손실 집계
```

### 2. RSI 구간별 분석
RSI 범위별 승률 비교:

```
RSI 0~20:  극 과매도 → 승률 ?%
RSI 20~30: 과매도 → 승률 ?%
RSI 30~40: 중립 하단 → 승률 ?%
RSI 40~50: 중립 → 승률 ?%
```

### 3. 투표 수별 분석
투표 수에 따른 성과 차이:

```
7/7 만장일치: 승률 ?%, 평균 수익 ?%
6/7 투표: 승률 ?%, 평균 수익 ?%
5/7 투표: 승률 ?%, 평균 수익 ?%
4/7 투표: 승률 ?%, 평균 수익 ?%
```

### 4. 시간대별 분석
거래 시간대별 성과:

```
00:00~06:00 (새벽): ?% 승률
06:00~12:00 (오전): ?% 승률
12:00~18:00 (오후): ?% 승률
18:00~24:00 (저녁): ?% 승률
```

### 5. 시장 상태별 분석
Day 시장 상태에 따른 성과:

```
BULLISH_STRONG: ?% 승률
BULLISH_MODERATE: ?% 승률
SIDEWAYS_BULLISH: ?% 승률
SIDEWAYS_BEARISH: ?% 승률
BEARISH_MODERATE: ?% 승률
BEARISH_STRONG: ?% 승률
```

---

## 🚀 실행 명령어

```bash
cd /Users/bongbong/SynologyDrive/vendor/sandbox/251015_봉봇/strategies/v41_scalping_voting

# Lookforward 분석 실행
python phase0_lookforward_analysis.py

# 예상 출력:
# - analysis/lookforward/minute5_performance.csv
# - analysis/lookforward/minute15_performance.csv
# - analysis/lookforward/minute60_performance.csv
# - analysis/lookforward/summary.md
```

---

## 📈 예상 분석 결과

### 최적 진입 조건 발견 예시:
```
✅ 최고 승률 조합 발견:
  - RSI: 25~35
  - 투표: 6/7 이상
  - 시장 상태: SIDEWAYS_BULLISH
  - 시간대: 09:00~11:00
  - 승률: 72%
  - 평균 수익: +3.2%
  - 평균 손실: -1.1%
  - Profit Factor: 2.1
```

---

## ⏱️ 소요 시간

- minute5: ~42초
- minute15: ~26초
- minute60: ~17초 (진행 중)
- **총 예상 시간**: ~1.5분

---

**생성 일시**: 2025-10-20 06:14:00
**프로세스 ID**: e90897
**스크립트**: phase0_full_signal_analysis.py
