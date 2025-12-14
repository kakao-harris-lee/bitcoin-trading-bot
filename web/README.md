# 비트코인 트레이딩 봇 - 웹 대시보드

## 🌐 개요

Flask 기반 모니터링 대시보드입니다.

- `logs/`의 로그 파일을 읽어 상태/거래내역 API를 제공합니다.
- v2 엔진은 `logs/v2_engine_*.json`을 생성하며(우선 사용), 없으면 기존 `logs/paper_trading_*.json`을 fallback으로 사용합니다.

## ✅ 상태

현재 UI는 기본 템플릿 수준이며, 실제 모니터링은 아래 API 호출로 확인하는 형태가 더 정확합니다.

## 🚀 사용 방법

### 1. 웹 서버 시작

```bash
# 프로젝트 루트에서
cd web
python app.py
```

### 2. 브라우저 접속

```
http://localhost:8080
```

### 3. API 엔드포인트

**상태**:

```
GET http://localhost:8080/api/status
```

**거래 내역(최근 50개)**:

```
GET http://localhost:8080/api/trades/upbit
GET http://localhost:8080/api/trades/binance
```

**통합 통계**:

```
GET http://localhost:8080/api/statistics
```

## ⛔ Kill-Switch (웹에서 제어)

실거래 LIVE 모드의 kill-switch 파일(`analysis/KILL_SWITCH`)을 웹 API로 제어할 수 있습니다.

보안상, 쓰기 작업은 `WEB_ADMIN_TOKEN` 환경변수와 요청 헤더 `X-Admin-Token`이 필요합니다.

**상태 확인**

```
GET http://localhost:8080/api/kill_switch/status
```

**ON/OFF**

```
POST http://localhost:8080/api/kill_switch/on
POST http://localhost:8080/api/kill_switch/off
```

## 📁 로그 파일

대시보드는 아래 파일을 읽습니다.

- 우선: `logs/v2_engine_upbit.json`, `logs/v2_engine_binance.json`
- fallback: `logs/paper_trading_upbit.json`, `logs/paper_trading_binance.json`

## 📁 파일 구조

```
web/
├── app.py                    # Flask 앱 (API 제공)
├── README.md                 # 이 파일
├── templates/
│   └── dashboard.html        # 대시보드 HTML (기본 템플릿)
└── static/
  ├── css/style.css
  └── js/dashboard.js
```

## 🔧 문제 해결

### 포트 8000 이미 사용 중

```bash
---

**업데이트**: 2025-12-14
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
