# 실행 방법

## 1️⃣ DB 초기화 및 실행 (Go 버전 - 추천)

### 한 번에 실행
```bash
cd /Users/bongbong/SynologyDrive/vendor/sandbox/251015_봉봇

# DB 초기화 + 빌드 + 실행
rm -f upbit_bitcoin.db && \
go build -o upbit-collector main.go && \
./upbit-collector
```

### 단계별 실행
```bash
# 1. 디렉토리 이동
cd /Users/bongbong/SynologyDrive/vendor/sandbox/251015_봉봇

# 2. 기존 DB 삭제 (초기화)
rm -f upbit_bitcoin.db

# 3. Go 프로그램 빌드
go build -o upbit-collector main.go

# 4. 실행
./upbit-collector
```

## 2️⃣ DB 초기화 및 실행 (Python 버전)

### 한 번에 실행
```bash
cd /Users/bongbong/SynologyDrive/vendor/sandbox/251015_봉봇

# DB 초기화 + 실행
rm -f upbit_bitcoin.db && \
source venv/bin/activate && \
python upbit_bitcoin_collector.py
```

### 단계별 실행
```bash
# 1. 디렉토리 이동
cd /Users/bongbong/SynologyDrive/vendor/sandbox/251015_봉봇

# 2. 기존 DB 삭제 (초기화)
rm -f upbit_bitcoin.db

# 3. 가상환경 활성화
source venv/bin/activate

# 4. 실행
python upbit_bitcoin_collector.py
```

## 3️⃣ 데이터 검증

### Go 버전으로 수집한 경우
```bash
# Python 검증 스크립트 사용
source venv/bin/activate
python verify_data.py
```

### 직접 DB 확인
```bash
# SQLite로 직접 확인
sqlite3 upbit_bitcoin.db

# 테이블 목록 확인
.tables

# 특정 테이블 데이터 수 확인
SELECT COUNT(*) FROM bitcoin_minute1;
SELECT COUNT(*) FROM bitcoin_day;

# 종료
.quit
```

## 4️⃣ 실행 중 프로세스 관리

### 백그라운드 실행 (nohup)
```bash
# Go 버전
nohup ./upbit-collector > collector.log 2>&1 &

# Python 버전
nohup python upbit_bitcoin_collector.py > collector.log 2>&1 &
```

### 실행 중인 프로세스 확인
```bash
ps aux | grep upbit
```

### 프로세스 종료
```bash
# 프로세스 ID(PID) 확인 후 종료
kill <PID>

# 또는 강제 종료
killall upbit-collector
```

### 로그 확인 (백그라운드 실행 시)
```bash
tail -f collector.log
```

## 5️⃣ 테스트 실행

### 빠른 테스트 (일 단위만)
```bash
source venv/bin/activate
python test_collector.py
```

### 5분 단위 테스트
```bash
source venv/bin/activate
python test_minute5.py
```

## 6️⃣ 주의사항

### DB 초기화 시 주의
⚠️ **DB를 삭제하면 기존에 수집한 모든 데이터가 사라집니다!**

기존 데이터를 보존하려면:
```bash
# DB 백업
cp upbit_bitcoin.db upbit_bitcoin_backup_$(date +%Y%m%d_%H%M%S).db

# 백업 확인
ls -lh upbit_bitcoin*.db
```

### 디스크 용량 확인
```bash
# 현재 디스크 사용량 확인
df -h .

# DB 파일 크기 확인
ls -lh upbit_bitcoin.db
```

## 7️⃣ 추천 실행 방법

### 최초 실행 (Go 버전 추천)
```bash
cd /Users/bongbong/SynologyDrive/vendor/sandbox/251015_봉봇
rm -f upbit_bitcoin.db
go build -o upbit-collector main.go
nohup ./upbit-collector > collector.log 2>&1 &
tail -f collector.log
```

**특징:**
- ✅ 병렬 처리로 빠른 수집
- ✅ Rate Limiter로 안정적
- ✅ 백그라운드 실행으로 중단 없음
- ✅ 로그로 진행 상황 확인

### 추가 수집 (기존 DB 유지)
```bash
# DB를 삭제하지 않고 실행하면 자동으로 중복 체크하여 새로운 데이터만 추가
cd /Users/bongbong/SynologyDrive/vendor/sandbox/251015_봉봇
./upbit-collector
```

## 8️⃣ 문제 해결

### Go가 설치되지 않은 경우
```bash
brew install go
```

### Python 가상환경이 없는 경우
```bash
python3 -m venv venv
source venv/bin/activate
pip install requests pandas
```

### Permission denied 에러
```bash
chmod +x upbit-collector
```

### DB locked 에러
```bash
# 실행 중인 프로세스 종료 후 재시도
killall upbit-collector
killall python
```
