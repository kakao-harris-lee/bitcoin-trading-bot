# 비트코인 트레이딩 봇 - 웹 대시보드

## 🌐 개요

FastAPI 기반 실시간 전략 성과 모니터링 대시보드

## ✅ 설치 완료 (2025-11-12)

모든 설정이 완료되었습니다!

- ✅ FastAPI 패키지 설치
- ✅ DB 스키마 생성
- ✅ 테스트 데이터 삽입 (v35, v34, v31, v-a-02)
- ✅ 웹 서버 실행 테스트 통과

## 🚀 사용 방법

### 1. 웹 서버 시작

```bash
# 프로젝트 루트에서
cd web
python app.py

# 또는 uvicorn 직접 실행
uvicorn app:app --host 0.0.0.0 --port 8000 --reload
```

### 2. 브라우저 접속

```
http://localhost:8000
```

### 3. API 엔드포인트

**메인 대시보드**:
```
GET http://localhost:8000/
```

**전략 목록 API**:
```
GET http://localhost:8000/api/strategies
```

**응답 예시**:
```json
{
  "strategies": [
    [1, "v35", "optimized", "Optuna 최적화 + 동적 익절 + SIDEWAYS 강화", "day", "2025-11-12 09:48:49"],
    [2, "v34", "supreme", "7-Level 시장 분류 + Multi-Strategy", "day", "2025-11-12 09:48:49"],
    ...
  ]
}
```

## 📊 현재 데이터

**등록된 전략** (4개):

| 버전 | 전략명 | 수익률 | Sharpe | MDD | 승률 |
|------|--------|--------|--------|-----|------|
| v35 | optimized | 14.20% | 2.24 | -2.33% | 25.0% |
| v-a-02 | multi_indicator_score | 11.28% | 1.85 | -3.50% | 75.0% |
| v34 | supreme | 8.43% | 1.34 | -2.83% | 60.0% |
| v31 | scalping_with_classifier | 6.33% | 1.94 | -8.96% | 45.0% |

## 🛠️ DB 관리

### DB 스키마 재생성

```bash
sqlite3 trading_results.db < web/init_db.sql
```

### 테스트 데이터 재삽입

```bash
sqlite3 trading_results.db < web/insert_test_data.sql
```

### DB 직접 조회

```bash
sqlite3 trading_results.db

# 전략 목록
SELECT * FROM strategies;

# 백테스팅 결과
SELECT * FROM backtest_results;

# 실시간 거래 (아직 없음)
SELECT * FROM trades;
```

## 📁 파일 구조

```
web/
├── app.py                    # FastAPI 메인 애플리케이션
├── init_db.sql               # DB 스키마 (strategies, backtest_results, trades)
├── insert_test_data.sql      # 테스트 데이터 (v35, v34, v31, v-a-02)
├── README.md                 # 이 파일
├── templates/
│   └── dashboard.html        # 대시보드 HTML 템플릿
└── static/
    ├── css/style.css         # 스타일시트
    └── js/dashboard.js       # 자바스크립트 (TODO: 차트)
```

## 🔧 문제 해결

### 포트 8000 이미 사용 중

```bash
# 프로세스 확인
lsof -i :8000

# 프로세스 종료
kill -9 <PID>

# 또는 다른 포트 사용
uvicorn app:app --port 8001
```

### DB 파일 없음

```bash
# DB 재생성
sqlite3 ../trading_results.db < init_db.sql
sqlite3 ../trading_results.db < insert_test_data.sql
```

## 📈 향후 개선 사항

- [ ] 실시간 차트 (Plotly)
- [ ] WebSocket 연동 (실시간 업데이트)
- [ ] 실시간 거래 내역 표시
- [ ] 전략 비교 차트
- [ ] 포지션 현황 대시보드
- [ ] 텔레그램 알림 연동

## 🚀 AWS 배포

### 1. EC2 보안 그룹

포트 8000 인바운드 허용:
```
Type: Custom TCP
Port Range: 8000
Source: 0.0.0.0/0 (또는 특정 IP)
```

### 2. systemd 서비스 생성

```bash
sudo nano /etc/systemd/system/dashboard.service
```

```ini
[Unit]
Description=Bitcoin Trading Bot Web Dashboard
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/bitcoin-trading-bot/web
ExecStart=/home/ubuntu/bitcoin-trading-bot/venv/bin/uvicorn app:app --host 0.0.0.0 --port 8000
Restart=always

[Install]
WantedBy=multi-user.target
```

### 3. 서비스 시작

```bash
sudo systemctl daemon-reload
sudo systemctl enable dashboard
sudo systemctl start dashboard
sudo systemctl status dashboard
```

### 4. Nginx 리버스 프록시 (선택)

```nginx
location /dashboard {
    proxy_pass http://127.0.0.1:8000;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
}
```

## 📞 지원

문제가 있으면 로그 확인:
```bash
tail -f /tmp/dashboard.log
```

---

**생성일**: 2025-11-12
**버전**: 1.0
**상태**: ✅ Production Ready
