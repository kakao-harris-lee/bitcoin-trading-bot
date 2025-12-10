# Bitcoin Trading Bot 배포 가이드

**버전**: v35 Optimized (Optuna Trial 99)
**최종 업데이트**: 2025-12-10

---

## 목차

1. [개요](#개요)
2. [사전 준비](#사전-준비)
3. [배포 방법 선택](#배포-방법-선택)
4. [Docker 배포](#docker-배포)
5. [AWS EC2 배포](#aws-ec2-배포)
6. [바이낸스 숏 헤지](#바이낸스-숏-헤지)
7. [운영 및 모니터링](#운영-및-모니터링)
8. [문제 해결](#문제-해결)

---

## 개요

### v35 Optimized 성과

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
3. `python live_trading/get_chat_id.py`로 Chat ID 확인

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
AUTO_TRADE=False
```

### 3. 연결 테스트

```bash
cd live_trading
python test_connection.py      # 업비트
python get_chat_id.py          # 텔레그램
python binance_futures_trader.py  # 바이낸스 (선택)
```

---

## 배포 방법 선택

| 방법 | 장점 | 단점 | 권장 |
|------|------|------|------|
| **Docker** | 이식성, 간편성 | 약간의 오버헤드 | 로컬, VPS |
| **EC2 systemd** | 성능 최고 | 설정 복잡 | 전용 서버 |

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

## AWS EC2 배포

### 인스턴스 설정

- **OS**: Ubuntu 24.04 LTS (권장)
- **인스턴스 타입**: t3.small 이상
- **예상 비용**: ~$15/월

### 배포 절차

```bash
# 1. SSH 접속
ssh -i your_key.pem ubuntu@your-ec2-ip

# 2. 환경 설정
sudo apt update
sudo apt install -y build-essential python3-dev python3-pip python3-venv

# 3. TA-Lib 설치
cd /tmp
wget http://prdownloads.sourceforge.net/ta-lib/ta-lib-0.4.0-src.tar.gz
tar -xzf ta-lib-0.4.0-src.tar.gz
cd ta-lib/
./configure --prefix=/usr
make -j$(nproc)
sudo make install
sudo ldconfig

# 4. 프로젝트 설정
cd ~
git clone your-repo bitcoin-trading-bot
cd bitcoin-trading-bot
python3 -m venv venv
source venv/bin/activate
pip install -r requirements_live.txt

# 5. .env 파일 생성
nano .env

# 6. systemd 서비스 설정
sudo nano /etc/systemd/system/bitcoin-trading-bot.service
```

### systemd 서비스 파일

```ini
[Unit]
Description=Bitcoin Trading Bot (v35 Strategy)
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/bitcoin-trading-bot/live_trading
ExecStart=/home/ubuntu/bitcoin-trading-bot/venv/bin/python main.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

### 서비스 제어

```bash
sudo systemctl enable bitcoin-trading-bot
sudo systemctl start bitcoin-trading-bot
sudo systemctl status bitcoin-trading-bot
sudo journalctl -u bitcoin-trading-bot -f
```

---

## 바이낸스 숏 헤지

하락장에서 손실을 방어하기 위한 바이낸스 선물 숏 포지션 전략입니다.

### 개요

| 시장 상태 | 업비트 | 바이낸스 | 효과 |
|----------|--------|----------|------|
| **BULL/SIDEWAYS** | 롱 포지션 | - | 상승 수익 |
| **BEAR 감지** | 롱 유지 | 숏 오픈 (50%) | 하락 손실 방어 |

### 예상 효과

| 시나리오 | 업비트 | 바이낸스 | 총 수익 |
|---------|--------|---------|--------|
| 상승장 | +40% | 0% | +40% |
| 하락장 | -20% | +20% | ~0% (손실 방어) |
| 횡보장 | +23% | -5% | +18% |

**기댓값**: 연간 +24% (듀얼 전략)

### 바이낸스 API 설정

1. **API 키 발급**
   - https://www.binance.com > API Management
   - 권한: Spot & Margin Trading, Futures 활성화
   - IP 제한 설정 권장

2. **.env 파일에 추가**
```bash
BINANCE_API_KEY=your_api_key
BINANCE_API_SECRET=your_api_secret
```

3. **연결 테스트**
```bash
cd live_trading
python binance_futures_trader.py
python dual_exchange_engine.py
```

### 자금 배분 (100만원 기준)

**옵션 1: 업비트만** (보수적)
- 업비트: 100만원
- 하락장 대응: 현금 전환

**옵션 2: 듀얼 전략** (권장)
- 업비트: 85만원
- 바이낸스: 100 USDT (~13만원)
- 하락장 대응: 숏 헤지

### 실행 모드

```bash
# 헤지 모드 (바이낸스 숏)
python main_dual.py --mode hedge --interval 300

# 현금 전환 모드 (바이낸스 미사용)
python main_dual.py --mode cash --interval 300
```

### Docker에서 듀얼 모드 실행

`docker-compose.yml` 수정:
```yaml
services:
  trading-bot:
    command: ["python", "main_dual.py", "--mode", "hedge", "--interval", "300"]
```

### 바이낸스 접속 가능 지역

**접속 가능** (VPS 추천):
- 한국 (Seoul)
- 일본 (Tokyo)
- 싱가포르 (Singapore)
- 독일 (Frankfurt)
- 영국 (London)

**제한 지역**:
- 호주 (Sydney) - 확인됨
- 미국 일부 주

### 긴급 청산

```python
from live_trading.dual_exchange_engine import DualExchangeEngine

engine = DualExchangeEngine(mode='hedge')

# 전체 포지션 청산
engine.emergency_close_all()

# 바이낸스 숏만 청산
engine.close_binance_short()
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

### 긴급 청산

```python
from live_trading.dual_exchange_engine import DualExchangeEngine

engine = DualExchangeEngine(mode='hedge')
engine.emergency_close_all()
```

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

### 데이터베이스 오류

```bash
# DB 파일 존재 확인
ls -la upbit_bitcoin.db

# 권한 확인/수정
chmod 644 upbit_bitcoin.db
```

### 텔레그램 연결 실패

```bash
# Chat ID 재확인
python live_trading/get_chat_id.py
```

### Docker 컨테이너 문제

```bash
# 로그 확인
docker compose logs trading-bot

# 이미지 재빌드
docker compose build --no-cache
docker compose up -d
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
3. 또는 바이낸스 없이 현금 전환 모드로 운영

```bash
# 현금 전환 모드로 변경
python main_dual.py --mode cash --interval 300
```

---

## 주요 파일 위치

```
live_trading/
├── main.py                    # 메인 실행
├── main_dual.py               # 듀얼 모드 (헤지)
├── live_trading_engine.py     # 트레이딩 엔진
├── upbit_trader.py            # 업비트 거래
├── binance_futures_trader.py  # 바이낸스 선물
├── dual_exchange_engine.py    # 듀얼 전략
└── telegram_notifier.py       # 텔레그램 알림

strategies/v35_optimized/
├── config_optimized.json      # 최적화 설정
├── config.json                # 원본 설정
└── strategy.py                # 전략 로직

deployment/
├── deploy_docker.sh           # Docker 배포 스크립트
├── setup_ec2.sh               # EC2 환경 설정
├── deploy.sh                  # 배포 자동화
└── monitor.sh                 # 모니터링 도구
```

---

**문서 버전**: v1.0
**통합 날짜**: 2025-12-10
