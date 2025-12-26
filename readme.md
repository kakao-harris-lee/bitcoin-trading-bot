# Bitcoin Trading Bot

비트코인 자동 트레이딩 봇 - Upbit(현물) + Binance(선물) 듀얼 엔진

## 빠른 시작

```bash
# Paper Trading (시뮬레이션)
python run.py --mode paper

# Live Trading (실거래)
ENABLE_LIVE_TRADING=1 python run.py --mode live

# 서버 실행
./bot.sh start live h4_conservative h4_short bear_only
./bot.sh status
./bot.sh logs
./bot.sh stop
```

## 프로젝트 구조

```
bitcoin-trading-bot/
├── run.py                      # 진입점
├── bot.sh                      # 서버 실행 스크립트
├── trading/                    # 메인 트레이딩 엔진
│   ├── engine.py               # DualPaperTradingEngine
│   ├── adapters/               # 거래소 API 어댑터
│   ├── modules/                # 전략 및 레짐 라우팅
│   └── notifications/          # 텔레그램 알림
├── core/                       # 공통 라이브러리
├── upbit_history_db/           # 데이터 수집/저장
├── strategies/                 # 전략 설정/백테스트
├── web/                        # 대시보드
└── docs/                       # 문서
```

## 데이터 수집

```bash
# Upbit 데이터 (Go)
cd upbit_history_db && ./upbit-collector

# Binance 데이터 (Python)
python upbit_history_db/binance_collector.py --start 2020-01-01
```

### 데이터 사용

```python
from core.data_loader import DataLoader

with DataLoader() as loader:
    # Upbit
    df = loader.load_timeframe('minute240', start_date='2024-01-01')
    # Binance
    df = loader.load_binance('minute240', start_date='2024-01-01')
```

## 전략

| 전략 | 거래소 | 레짐 | 설명 |
|------|--------|------|------|
| V35 Optimized | Upbit | BULL | 모멘텀 추종 |
| H4 Conservative | Upbit | SIDEWAYS | 4시간봉 롱 |
| H4 Short | Binance | BEAR | 4시간봉 숏 |

## 환경 설정

### .env

```env
UPBIT_ACCESS_KEY=your_key
UPBIT_SECRET_KEY=your_secret
BINANCE_API_KEY=your_key
BINANCE_API_SECRET=your_secret
TELEGRAM_BOT_TOKEN=your_token
TELEGRAM_CHAT_ID=your_chat_id
```

### 의존성

```bash
# macOS
brew install ta-lib && pip install -r requirements.txt

# Ubuntu
sudo apt-get install build-essential libta-lib-dev && pip install -r requirements.txt
```

## CLI 옵션

```
python run.py --help

--mode {paper,live}           실행 모드 (기본: paper)
--interval INT                실행 간격 분 (기본: 60)
--sideways-policy {sideways_v2,h4_conservative,v35,hold}
--binance-policy {short_v1,h4_short,hold}
--binance-gate {bear_only,sideways_and_bear,always}
--no-telegram                 텔레그램 비활성화
```

## 문서

- [배포 가이드](docs/DEPLOYMENT.md)
- [엔진 설계](docs/TRADING_ENGINE_DESIGN.md)
