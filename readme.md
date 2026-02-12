# Bitcoin Trading Bot

Binance Futures 자동 트레이딩 봇

## 빠른 시작

```bash
# Paper Trading (시뮬레이션)
python run.py --trend paper

# Live Trading (실거래)
ENABLE_LIVE_TRADING=1 python run.py --trend live

# 서버 실행
./bot.sh start --trend=live
./bot.sh status
./bot.sh logs
./bot.sh stop
```

`live` 실행 전에는 최근 paper 성과 검증이 자동으로 수행됩니다.
수동 점검:

```bash
python scripts/paper_readiness_check.py --config config/strategies/allocation.json --trades-log logs/trades.runtime.jsonl

# 활성 전략 기간별 수익률 vs BnH 비교 (문제 구간 탐지)
python scripts/backtest/period_vs_bnh.py --start-date 2025-01-01 --end-date 2026-01-11 --timeframe minute240

# readiness 진행률 추적 (전략별 EXIT 부족분 확인)
python scripts/paper_readiness_progress.py --trades-log logs/trades.runtime.jsonl --watch-seconds 60
```

## 프로젝트 구조

```
bitcoin-trading-bot/
├── run.py                      # 진입점
├── bot.sh                      # 서버 실행 스크립트
├── trading/                    # 메인 트레이딩 엔진
│   ├── multi_asset_engine.py   # MultiAssetTradingEngine
│   ├── data/                   # 데이터 피드
│   ├── strategy/               # 모든 전략 + 레짐 분류
│   ├── execution/              # 주문 실행, 포지션 관리
│   ├── risk/                   # 리스크 관리
│   ├── notification/           # 텔레그램 알림
│   └── adapters/               # 거래소 API 어댑터
├── core/                       # 공통 라이브러리
│   ├── data_loader.py          # 히스토리 데이터 로딩
│   ├── backtester.py           # 백테스트 엔진
│   └── types.py                # 공유 데이터 타입
├── config/                     # 설정 파일
│   ├── strategies/             # 전략 파라미터
│   └── tuned/                  # 튜닝된 설정
├── scripts/                    # CLI 도구
│   ├── backtest.py             # 백테스트
│   ├── optimize.py             # 파라미터 최적화
│   └── auto_collect_data.py    # 데이터 자동 수집
├── data/                       # 데이터베이스 파일
├── tests/                      # 테스트
├── web/                        # 대시보드
└── docs/                       # 문서
```

## 데이터 수집

```bash
# Binance 데이터 자동 수집
python scripts/auto_collect_data.py

# Binance 데이터 수집 (Python)
python scripts/collectors/binance_collector.py --start 2020-01-01
```

### 데이터 사용

```python
from core.data_loader import DataLoader

with DataLoader() as loader:
    # Binance
    df = loader.load_binance('minute240', start_date='2024-01-01')
```

## 전략

| 전략 | 거래소 | 레짐 | 파일 |
|------|--------|------|------|
| MLP Direction | Binance | ALL | `config/strategies/allocation.json` |
| Short V1 | Binance | BEAR | `config/strategies/allocation.json` |
| Sideways V2 | Binance | SIDEWAYS | `config/strategies/allocation.json` |

## 환경 설정

### .env

```env
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

--trend {paper,live}          실행 모드 (기본: paper)
--config PATH                 설정 파일 경로 (기본: config/strategies/allocation.json)
```

## 문서

- [배포 가이드](docs/DEPLOYMENT.md)
- [엔진 설계](docs/TRADING_ENGINE_DESIGN.md)
