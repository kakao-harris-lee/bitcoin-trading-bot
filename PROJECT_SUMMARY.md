# 업비트 비트코인 DB 생성 프로젝트 - 최종 정리

## 📋 프로젝트 개요

업비트 API를 사용하여 비트코인(KRW-BTC) 시계열 데이터를 수집하고 SQLite DB에 저장하는 프로젝트

**수집 완료 데이터:**
- **총 레코드: 4,174,195개**
- **DB 크기: 489 MB**
- **수집 기간: 2017년 9월 ~ 2025년 10월**

---

## 📁 프로젝트 구조

```
251015_봉봇/
├── upbit_bitcoin.db          # 최종 생성된 DB (489MB)
└── v1_db생성/                # 모든 소스 코드 및 도구
    ├── main.go               # Go 버전 (병렬 처리 + Rate Limiter)
    ├── upbit_bitcoin_collector.py  # Python 버전 (순차 처리)
    ├── db_cli.py             # DB 확인 CLI
    ├── check_db.sh           # 빠른 DB 확인 스크립트
    ├── run.sh                # 자동 실행 스크립트
    ├── verify_data.py        # 데이터 검증 스크립트
    ├── venv/                 # Python 가상환경
    └── 문서들/
        ├── readme.md
        ├── QUICK_START.md
        ├── HOW_TO_RUN.md
        └── DB_CHECK_GUIDE.md
```

---

## 🎯 주요 구현 사항

### 1. 데이터 수집기 (2가지 버전)

#### Go 버전 ⚡ (추천)
**파일:** `v1_db생성/main.go`

**특징:**
- ✅ 11개 goroutine으로 병렬 처리
- ✅ Rate Limiter (초당 9회, 업비트 제한: 10회)
- ✅ 429 에러 없이 안정적 수집
- ✅ 예상 수집 시간: 30분 ~ 2시간

**실행 방법:**
```bash
cd v1_db생성
go build -o upbit-collector main.go
./upbit-collector
```

#### Python 버전 🐍
**파일:** `v1_db생성/upbit_bitcoin_collector.py`

**특징:**
- ✅ 순차 처리로 안정적
- ✅ 디버깅 용이
- ✅ 예상 수집 시간: 2시간 ~ 8시간

**실행 방법:**
```bash
cd v1_db생성
source venv/bin/activate
python upbit_bitcoin_collector.py
```

---

### 2. DB 확인 도구 (3가지)

#### 2-1. 대화형 CLI (가장 강력)
**파일:** `v1_db생성/db_cli.py`

**기능:**
1. 전체 통계
2. 특정 시간단위 상세 정보
3. 최신 데이터 조회
4. 날짜별 데이터 조회
5. 보간 데이터 통계
6. DB 파일 정보

**실행:**
```bash
cd v1_db생성
python db_cli.py
```

#### 2-2. 빠른 확인 스크립트 (가장 간단)
**파일:** `v1_db생성/check_db.sh`

**실행:**
```bash
cd v1_db생성
./check_db.sh
```

#### 2-3. 검증 스크립트
**파일:** `v1_db생성/verify_data.py`

**실행:**
```bash
cd v1_db생성
source venv/bin/activate
python verify_data.py
```

---

### 3. 자동 실행 스크립트

**파일:** `v1_db생성/run.sh`

**기능:**
- 기존 DB 백업 여부 선택
- Go/Python 버전 선택
- 자동 빌드 및 실행

**실행:**
```bash
cd v1_db생성
./run.sh
```

---

## 💾 수집된 데이터 상세

### 시간단위별 통계

| 시간단위 | 레코드 수 | 데이터 기간 | 보간 데이터 |
|---------|----------|------------|------------|
| minute1 | 3,572,115개 | 2018-12-31 ~ 2025-10-16 | 23,315개 (0.65%) |
| minute3 | 95,123개 | 2025-04-01 ~ 2025-10-16 | 123개 (0.13%) |
| minute5 | 119,680개 | 2024-08-26 ~ 2025-10-16 | 280개 (0.23%) |
| minute10 | 95,215개 | 2023-12-25 ~ 2025-10-16 | 215개 (0.23%) |
| minute15 | 95,031개 | 2023-01-30 ~ 2025-10-16 | 231개 (0.24%) |
| minute30 | 119,243개 | 2018-12-28 ~ 2025-10-16 | 243개 (0.20%) |
| minute60 | 59,689개 | 2018-12-25 ~ 2025-10-16 | 89개 (0.15%) |
| minute240 | 15,001개 | 2018-12-12 ~ 2025-10-16 | 1개 (0.01%) |
| day | 2,600개 | 2018-09-04 ~ 2025-10-16 | 0개 |
| week | 400개 | 2018-02-19 ~ 2025-10-13 | 0개 |
| month | 98개 | 2017-09-01 ~ 2025-10-01 | 0개 |

**총 레코드:** 4,174,195개

---

## 🔑 핵심 기술

### 1. Rate Limiter 구현 (Go)
```go
type RateLimiter struct {
    mu       sync.Mutex
    lastCall time.Time
    minGap   time.Duration  // 111ms (초당 9회)
}
```

**업비트 API 제한:**
- 캔들 API: 초당 10회, 분당 600회
- 구현: 초당 9회로 안전하게 설정

### 2. 선형 보간 (Linear Interpolation)
결측 구간 발견 시 양쪽 값을 기준으로 선형보간하여 모든 시간 데이터 채움

**예시:**
```
01:00 - 10,000원 (원본)
01:05 - 10,250원 (보간)
01:10 - 10,500원 (보간)
01:15 - 10,750원 (보간)
01:20 - 11,000원 (원본)
```

### 3. 병렬 처리 (Goroutines)
11개 시간단위를 동시에 수집하면서도 전역 Rate Limiter로 API 제한 준수

---

## 📚 데이터베이스 스키마

### 테이블 구조
각 시간단위마다 테이블 생성: `bitcoin_{timeframe}`

**컬럼:**
```sql
CREATE TABLE bitcoin_minute1 (
    timestamp TEXT PRIMARY KEY,           -- KST 시간
    opening_price REAL NOT NULL,         -- 시가
    high_price REAL NOT NULL,            -- 고가
    low_price REAL NOT NULL,             -- 저가
    trade_price REAL NOT NULL,           -- 종가
    candle_acc_trade_volume REAL NOT NULL, -- 거래량
    candle_acc_trade_price REAL NOT NULL,  -- 거래대금
    is_interpolated INTEGER DEFAULT 0    -- 0: 원본, 1: 보간
);
```

---

## 🚀 사용 방법

### DB 확인 (추천 순서)

1. **빠른 확인**
   ```bash
   cd v1_db생성
   ./check_db.sh
   ```

2. **상세 확인**
   ```bash
   cd v1_db생성
   python db_cli.py
   ```

3. **직접 쿼리**
   ```bash
   sqlite3 upbit_bitcoin.db
   SELECT * FROM bitcoin_day LIMIT 10;
   ```

### 추가 데이터 수집
```bash
cd v1_db생성
./upbit-collector  # 중복 자동 체크하여 새 데이터만 추가
```

---

## 📊 성능 비교

| 항목 | Python 버전 | Go 버전 |
|------|------------|---------|
| 처리 방식 | 순차 | 병렬 (11 goroutines) |
| Rate Limit | 수동 대기 | 자동 제어 |
| 수집 속도 | ⭐⭐ | ⭐⭐⭐⭐⭐ |
| 안정성 | ✅ | ✅ |
| API 에러 | 없음 | 없음 (Rate Limiter) |
| 메모리 사용 | 낮음 | 낮음 |

---

## 🔧 기술 스택

- **Go 1.21+**
  - goroutines (병렬 처리)
  - sync.Mutex (동기화)
  - github.com/mattn/go-sqlite3

- **Python 3.12+**
  - requests (HTTP)
  - pandas (데이터 처리)
  - sqlite3 (DB)

---

## 📝 주요 문서

### v1_db생성 폴더 내 문서들

1. **readme.md** - 프로젝트 소개
2. **QUICK_START.md** - 빠른 시작 가이드
3. **HOW_TO_RUN.md** - 상세 실행 매뉴얼
4. **DB_CHECK_GUIDE.md** - DB 확인 가이드

---

## ⚠️ 주의사항

1. **API Rate Limit**
   - 업비트 제한: 초당 10회
   - Go 버전: 자동 제어 (초당 9회)
   - Python 버전: 200ms 대기

2. **디스크 용량**
   - 현재 DB: 489MB
   - 1분 단위 데이터가 대부분 차지

3. **데이터 보존**
   - DB 삭제 전 반드시 백업
   - 재수집 시 시간 소요

---

## 🎯 프로젝트 성과

✅ **4백만 개 이상의 시계열 데이터 수집**
✅ **2017년부터 현재까지의 비트코인 가격 데이터**
✅ **결측값 없는 완전한 데이터셋 (선형보간)**
✅ **Go 병렬 처리로 빠른 수집 속도**
✅ **Rate Limiter로 안정적 API 호출**
✅ **다양한 DB 확인 도구 제공**

---

## 📌 다음 단계 제안

1. **데이터 분석**
   - 가격 변동성 분석
   - 추세 분석
   - 기술적 지표 계산

2. **시각화**
   - 차트 생성
   - 대시보드 구축

3. **머신러닝**
   - 가격 예측 모델
   - 패턴 인식

4. **API 서버**
   - REST API 구축
   - 실시간 데이터 제공

---

## 📄 라이선스

MIT License

---

## 👥 제작

업비트 비트코인 DB 생성 프로젝트
생성일: 2025-10-16
