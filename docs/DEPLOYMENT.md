# Bitcoin Trading Bot 배포 가이드

**버전**: Trading Engine V2 (Redis 기반)
**최종 업데이트**: 2025-12-18

---

## 목차

1. [개요](#개요)
2. [사전 준비](#사전-준비)
3. [배포 방법 선택](#배포-방법-선택)
4. [운영 서버 배포 (Native)](#운영-서버-배포-native)
5. [Docker 배포](#docker-배포)
6. [운영 및 모니터링](#운영-및-모니터링)
7. [문제 해결](#문제-해결)

---

## 개요

### Trading Engine V2 성과

| 지표 | 값 |
|------|-----|
| **누적 수익률** | +261.87% (6년) |
| **CAGR** | 23.91% (연평균) |
| **2025 수익률** | +23.16% |
| **Sharpe Ratio** | 2.62 |
| **MDD** | -2.39% |

### 시스템 요구사항

| 항목 | 최소 | 권장 |
|------|------|------|
| CPU | 1 Core | 2 Core |
| 메모리 | 512MB | 1GB |
| 디스크 | 2GB | 5GB |
| Python | 3.10+ | 3.12 |
| Redis | 6.0+ | 7.0+ |

---

## 사전 준비

### 1. API 키 발급

#### 업비트 (필수)
1. 업비트 웹사이트 로그인
2. 마이페이지 > Open API 관리
3. API 키 발급 (자산조회, 주문조회, 주문하기 권한)

#### 텔레그램 (필수)
1. 텔레그램에서 @BotFather 검색
2. `/newbot` 명령어로 봇 생성
3. `python _archive/live_trading_legacy/get_chat_id.py`로 Chat ID 확인

#### 바이낸스 (선택, 헤지용)
1. https://www.binance.com > API Management
2. Spot & Margin Trading, Futures 권한 활성화

### 2. .env 파일 생성

```bash
# 프로젝트 루트에 .env 파일 생성
cp .env.example .env

# 내용 편집
UPBIT_ACCESS_KEY=your_access_key
UPBIT_SECRET_KEY=your_secret_key
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id
BINANCE_API_KEY=your_binance_key      # 선택
BINANCE_API_SECRET=your_binance_secret # 선택
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_PASSWORD=your_redis_password    # 선택
```

---

## 배포 방법 선택

| 방법 | 장점 | 단점 | 권장 |
|------|------|------|------|
| **Native (systemd)** | 성능 최고, 직접 제어 | 수동 설정 | 전용 서버 |
| **Docker** | 이식성, 간편성 | 약간의 오버헤드 | 로컬, VPS |

---

## 운영 서버 배포 (Native)

### 서버 정보

| 항목 | 값 |
|------|-----|
| **호스트** | chl_svr |
| **IP** | 49.247.171.64 |
| **계정** | deploy |
| **프로젝트 경로** | ~/project/bitcoin-trading-bot |
| **Python 환경** | .venv (Python 3.12) |

### 코드 동기화

```bash
# 로컬에서 실행 (SSH 접속)
ssh deploy@49.247.171.64

# 서버에서 git pull
cd ~/project/bitcoin-trading-bot
git pull origin main
```

### 가상환경 설정 (최초 1회)

```bash
cd ~/project/bitcoin-trading-bot

# 가상환경 생성
python3 -m venv .venv

# 활성화
source .venv/bin/activate

# 의존성 설치
pip install --upgrade pip
pip install -r requirements.txt
```

### 실행 방법

#### Paper Trading (테스트)
```bash
cd ~/project/bitcoin-trading-bot
source .venv/bin/activate
python run.py --mode paper --interval 5
```

#### Live Trading (실거래)
```bash
# ENABLE_LIVE_TRADING=1 환경변수 필수
ENABLE_LIVE_TRADING=1 python run.py --mode live --interval 5
```

#### 실행 옵션

| 옵션 | 설명 | 기본값 |
|------|------|--------|
| `--mode` | paper 또는 live | paper |
| `--interval` | 체크 간격 (분) | 5 |
| `--upbit-capital` | 업비트 시작 자본 (KRW) | 10,000,000 |
| `--binance-capital` | 바이낸스 시작 자본 (USDT) | 10,000 |
| `--fx-rate` | 원/달러 환율 | 1,350 |

### systemd 서비스 설정

```bash
sudo nano /etc/systemd/system/bitcoin-trading-bot.service
```

```ini
[Unit]
Description=Bitcoin Trading Bot (Trading Engine V2)
After=network.target redis.service

[Service]
Type=simple
User=deploy
WorkingDirectory=/home/deploy/project/bitcoin-trading-bot
Environment="PATH=/home/deploy/project/bitcoin-trading-bot/.venv/bin"
ExecStart=/home/deploy/project/bitcoin-trading-bot/.venv/bin/python run.py --mode paper --interval 5
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
# 서비스 등록 및 시작
sudo systemctl daemon-reload
sudo systemctl enable bitcoin-trading-bot
sudo systemctl start bitcoin-trading-bot

# 상태 확인
sudo systemctl status bitcoin-trading-bot

# 로그 확인
sudo journalctl -u bitcoin-trading-bot -f
```

### Redis 설정

```bash
# Redis 상태 확인
redis-cli ping

# 비밀번호 인증 필요시
redis-cli -a your_redis_password ping
```

---

## Docker 배포

### 빠른 시작

```bash
# 1. Docker 설치 확인
docker --version
docker compose version

# 2. 배포 실행
./deployment/deploy_docker.sh start

# 3. 상태 확인
./deployment/deploy_docker.sh status
./deployment/deploy_docker.sh logs
```

### Docker 설치

#### macOS
```bash
brew install --cask docker
```

#### Ubuntu/Debian
```bash
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh
sudo usermod -aG docker $USER
```

### 주요 명령어

```bash
# 시작/중지/재시작
./deployment/deploy_docker.sh start
./deployment/deploy_docker.sh stop
./deployment/deploy_docker.sh restart

# 로그 확인
./deployment/deploy_docker.sh logs
docker compose logs -f trading-bot

# 컨테이너 내부 접속
docker compose exec trading-bot bash
```

### 웹 대시보드

```
http://localhost:8000
```

---

## 운영 및 모니터링

### 배포 단계

| Phase | 기간 | 자금 | 목표 |
|-------|------|------|------|
| 1. Paper Trading | 1주일 | - | 시스템 안정성 확인 |
| 2. 실전 30% | 1주일 | 30만원 | 실제 성과 검증 |
| 3. 실전 100% | 이후 | 100만원 | 정상 운영 |

### 손실 한도

| 기간 | 한도 | 조치 |
|------|------|------|
| 일일 | -3% | 당일 거래 중단 |
| 주간 | -5% | Phase 하향 조정 |
| 월간 | -10% | 전략 중단 및 재검토 |

### 일일 체크리스트

- [ ] 포지션 상태 확인
- [ ] 당일 손익 확인
- [ ] 텔레그램 알림 확인
- [ ] 에러 로그 확인

---

## 문제 해결

### API 키 오류

```bash
# .env 파일 권한 확인
chmod 600 .env

# API 키 형식 확인 (따옴표 없이)
UPBIT_ACCESS_KEY=abc123...
```

### Redis 연결 오류

```bash
# Redis 서비스 상태 확인
sudo systemctl status redis

# Redis 재시작
sudo systemctl restart redis

# 연결 테스트
redis-cli -a your_password ping
```

### 데이터베이스 오류

```bash
# DB 파일 존재 확인
ls -la upbit_history_db/upbit_bitcoin.db

# 권한 확인/수정
chmod 644 upbit_history_db/upbit_bitcoin.db
```

### 텔레그램 연결 실패

```bash
# Chat ID 재확인
python _archive/live_trading_legacy/get_chat_id.py
```

### systemd 서비스 문제

```bash
# 상세 로그 확인
sudo journalctl -u bitcoin-trading-bot -n 100 --no-pager

# 서비스 재시작
sudo systemctl restart bitcoin-trading-bot
```

### 바이낸스 연결 실패

**에러**: "Service unavailable from a restricted location"

**원인**: VPS가 바이낸스 제한 지역에 있음

**해결**:
1. VPS 위치 확인 (바이낸스 허용 지역인지)
2. 허용 지역으로 VPS 이전 (서울, 도쿄, 싱가포르 등)
3. 또는 바이낸스 없이 업비트만 운영

---

## 주요 파일 위치

```
bitcoin-trading-bot/
├── run.py                           # 단일 진입점
│
├── trading/               # 메인 엔진
│   ├── trading_engine.py            # 트레이딩 엔진 (DualPaperTradingEngine)
│   ├── core/                        # 핵심 인프라
│   │   ├── redis_client.py          # Redis Streams
│   │   ├── config.py                # 설정
│   │   ├── risk_controls.py         # 위험 관리
│   │   └── trade_logger.py          # 거래 로그
│   ├── adapters/                    # 거래소 어댑터
│   │   ├── upbit_trader.py          # 업비트 API
│   │   ├── binance_trader.py        # 바이낸스 API
│   │   ├── paper_account.py         # Paper Trading
│   │   └── live_adapters.py         # Live Trading
│   ├── modules/                     # 실행 모듈
│   │   ├── regime_router.py         # 시장 상태 라우팅
│   │   └── strategies/              # 전략
│   │       └── sideways_v2.py
│   └── notifications/               # 알림
│       ├── telegram_notifier.py
│       └── telegram_commands.py
│
├── strategies/v35_optimized/        # 전략 설정
│   ├── config_optimized.json
│   └── strategy.py
│
├── web/                             # 대시보드
│
└── _archive/                        # 레거시 백업
    └── live_trading_legacy/
```

---

**문서 버전**: v2.0
**작성 날짜**: 2025-12-18
