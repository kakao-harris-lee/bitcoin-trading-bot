# 빠른 시작 가이드

## 🚀 가장 간단한 방법

### 방법 1: 자동 실행 스크립트 (추천)
```bash
cd /Users/bongbong/SynologyDrive/vendor/sandbox/251015_봉봇
./run.sh
```

스크립트가 자동으로:
1. 기존 DB 백업 (선택 사항)
2. Go 또는 Python 버전 선택
3. 빌드 및 실행

---

### 방법 2: 수동 실행 (Go 버전 - 가장 빠름)

```bash
# 1단계: 디렉토리 이동
cd /Users/bongbong/SynologyDrive/vendor/sandbox/251015_봉봇

# 2단계: DB 초기화 (선택 사항)
rm -f upbit_bitcoin.db

# 3단계: 빌드 및 실행
go build -o upbit-collector main.go && ./upbit-collector
```

---

### 방법 3: Python 버전

```bash
# 1단계: 디렉토리 이동
cd /Users/bongbong/SynologyDrive/vendor/sandbox/251015_봉봇

# 2단계: DB 초기화 (선택 사항)
rm -f upbit_bitcoin.db

# 3단계: 실행
source venv/bin/activate
python upbit_bitcoin_collector.py
```

---

## 📊 데이터 확인

### 수집 완료 후 검증
```bash
source venv/bin/activate
python verify_data.py
```

### SQLite로 직접 확인
```bash
sqlite3 upbit_bitcoin.db

# 테이블 목록
.tables

# 데이터 개수 확인
SELECT COUNT(*) FROM bitcoin_day;
SELECT COUNT(*) FROM bitcoin_minute1;

# 최신 데이터 확인
SELECT * FROM bitcoin_day ORDER BY timestamp DESC LIMIT 5;

# 종료
.quit
```

---

## 💡 주요 명령어

### DB 초기화 (모든 데이터 삭제)
```bash
cd /Users/bongbong/SynologyDrive/vendor/sandbox/251015_봉봇
rm -f upbit_bitcoin.db
```

### DB 백업
```bash
cd /Users/bongbong/SynologyDrive/vendor/sandbox/251015_봉봇
cp upbit_bitcoin.db upbit_bitcoin_backup_$(date +%Y%m%d_%H%M%S).db
```

### DB 크기 확인
```bash
cd /Users/bongbong/SynologyDrive/vendor/sandbox/251015_봉봇
ls -lh upbit_bitcoin.db
```

---

## ⚡ 성능 비교

| 버전 | 속도 | 안정성 | 추천 상황 |
|------|------|--------|----------|
| **Go** | ⚡⚡⚡⚡⚡ | ✅ | 빠른 수집 필요 시 |
| Python | ⚡⚡ | ✅ | 디버깅 필요 시 |

---

## 🔧 문제 해결

### "Go not found" 에러
```bash
brew install go
```

### "venv not found" 에러
```bash
python3 -m venv venv
source venv/bin/activate
pip install requests pandas
```

### "Permission denied" 에러
```bash
chmod +x run.sh
chmod +x upbit-collector
```

---

## 📝 예상 실행 시간

- **Go 버전 (병렬)**: 약 30분 ~ 2시간 (데이터 양에 따라)
- **Python 버전 (순차)**: 약 2시간 ~ 8시간

**팁**: 백그라운드로 실행하려면:
```bash
nohup ./upbit-collector > collector.log 2>&1 &
tail -f collector.log
```
