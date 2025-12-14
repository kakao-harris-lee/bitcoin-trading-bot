# 251214 Live Trading 준비 체크리스트 (Dual Paper 기반)

**작성일**: 2025-12-14

오늘 작업의 목표는 “튜닝된 운영형 레짐 라우팅(candidate)”을 **재현 가능하게 고정(pinned)** 하고,
Docker Compose paper-trading 경로에서 **동일 설정으로 안정적으로 동작**하는지 확인하는 것입니다.

---

## 1) 오늘 반영된 핵심 변경점

- 운영형 레짐 라우터(`live_trading/regime_router.py`)에 튜닝 파라미터 적용 가능
  - MFI/ADX 임계값(`router_config`)
  - 정책: `bull_policy(hold_long 포함)`, `sideways_policy`, `bear_*_policy`
  - Binance 게이트: `binance_gate_mode` (bear_only / bear_strong_only 등)
- Dual paper 엔진(`live_trading/dual_paper_trading.py`)이 candidate JSON을 로드 가능
  - `--candidate-json`, `--candidate-index`
  - Upbit/Binance 노출 multiplier 및 SideWaysV2 내부 파라미터 적용
- 포트폴리오 백테스트(`trading_engine_v2/scripts/backtest_operational_portfolio.py`)도 동일 candidate 로드 가능
  - paper 운영 경로와 동일한 설정으로 A+B(Upbit+Binance) 검증 가능
- pinned 설정 파일 추가
  - `analysis/selected_candidate.json`

---

## 2) 현재 pinned candidate (운영 기준)

- 파일: `analysis/selected_candidate.json`
- Docker Compose 기본 paper-trading 서비스는 이 파일을 자동 사용하도록 설정됨

---

## 3) 서버 배포 후 즉시 점검 순서 (권장)

### (A) 배포

```bash
./deployment/deploy_to_server.sh
```

### (B) 서버에서 설정 확인

```bash
ssh deploy@49.247.171.64
cd /home/deploy/bitcoin-trading-bot

# pinned candidate 확인
cat analysis/selected_candidate.json
```

### (C) 컨테이너 실행/로그 확인

```bash
docker compose ps
docker compose logs -f paper-trading
```

로그에서 아래 형태를 확인:

- Router 출력: `state=... regime=... | upbit=... | binance=...`
- candidate 적용 시 startup 메시지에 `Candidate 적용됨` 표기

---

## 4) 로컬/서버에서 candidate 교체 방법

### 방법 1) pinned 파일 교체 (운영 권장)

- `analysis/selected_candidate.json`의 `candidate`를 변경
- 재시작

```bash
docker compose restart paper-trading
```

### 방법 2) tuner 결과에서 다른 index 사용 (실험)

```bash
python live_trading/dual_paper_trading.py \
  --candidate-json analysis/tune_operational_router_results.json \
  --candidate-index 0
```

---

## 5) 백테스트로 운영 설정 재현성 확인

### 2025 검증 구간(예시)

```bash
/Users/harris/Development/private/bitcoin-trading-bot/.venv/bin/python \
  trading_engine_v2/scripts/backtest_operational_portfolio.py \
  --candidate-json analysis/selected_candidate.json \
  --start-date 2025-01-01 \
  --end-date 2025-12-11 \
  --by-year
```

### 전체 구간(권장)

```bash
/Users/harris/Development/private/bitcoin-trading-bot/.venv/bin/python \
  trading_engine_v2/scripts/backtest_operational_portfolio.py \
  --candidate-json analysis/selected_candidate.json \
  --by-year
```

---

## 6) Live Trading 전환 전 필수 확인사항

- [ ] paper-trading이 최소 24~72시간 무중단 실행
- [ ] Router regime 전환 시 전략 stickiness가 의도대로 동작
- [ ] 텔레그램 알림(옵션) 정상
- [ ] DB/CSV 마운트 경로 정상
- [ ] 리소스(CPU/메모리) 안정

> Live Trading(실거래) 엔진 경로는 별도 진입(키/주문/리스크) 검증이 필요하므로,
> 우선 paper 경로에서 “candidate 고정 + 재현성 + 안정성”을 확보한 뒤 단계적으로 전환합니다.

---

## 7) V2 엔진 LIVE 모드 (실주문) 전환 가이드

Dual V2 엔진은 `paper` / `live` 모드를 지원합니다.

### (A) LIVE 안전장치 (필수)

- LIVE는 실주문을 실행하므로 환경변수 opt-in이 필요합니다.
- `ENABLE_LIVE_TRADING=1` 없으면 실행이 차단됩니다.

예시:

```bash
ENABLE_LIVE_TRADING=1 \
  /Users/harris/Development/private/bitcoin-trading-bot/.venv/bin/python \
  -m live_trading.main \
  --engine dual_paper_v2 \
  --mode live \
  --candidate-json analysis/selected_candidate.json
```

### (B) 리스크 기본값 (pinned candidate에 포함됨)

`analysis/selected_candidate.json`의 `candidate.risk_config`로 고정됩니다.

- `kill_switch_file`: `analysis/KILL_SWITCH`
- `daily_max_loss_pct`: `2.0` (초과 시 **신규 진입만 차단**, 청산/리밸런스는 진행 가능)
- `max_upbit_entry_fraction`: `1.0`
- `max_binance_entry_fraction`: `1.0`
- `min_upbit_order_krw`: `5000.0`
- `min_binance_order_usdt`: `10.0`

추가로, LIVE 모드에서 “Kill Switch 권장” 알림을 위한 임계치도 `candidate.risk_config`로 설정할 수 있습니다.

- `recommend_kill_on_daily_loss_pct`: (예: `4.0`) — 일간 손실이 이 값 이상 커지면 Telegram으로 Kill Switch ON을 권장
- `recommend_kill_on_price_failures`: (예: `2`) — 가격 피드가 0/placeholder로 연속 실패하면 권장
- `recommend_kill_on_consecutive_errors`: (예: `3`) — 전략 실행 오류가 연속 누적되면 권장

주의: 권장 알림은 **자동으로 Kill Switch를 켜지 않습니다.** 운영자가 `/kill_on`으로 직접 켜야 합니다.

### (C) Kill-Switch 운영

#### 1) 파일 기반 (가장 단순/권장)

```bash
touch analysis/KILL_SWITCH
```

다음 iteration에서 LIVE 루프가 중단됩니다.

해제:

```bash
rm -f analysis/KILL_SWITCH
```

#### 2) 텔레그램 명령어 (옵션)

dual_paper_v2 실행 시 `--telegram-commands`를 켜면 polling 스레드가 활성화됩니다.

```bash
ENABLE_LIVE_TRADING=1 \
  /Users/harris/Development/private/bitcoin-trading-bot/.venv/bin/python \
  -m live_trading.main \
  --engine dual_paper_v2 \
  --mode live \
  --telegram-commands \
  --candidate-json analysis/selected_candidate.json
```

사용 명령:

- `/kill_on`
- `/kill_off`
- `/kill_status`

#### 3) 웹 대시보드 API (옵션)

`web/app.py`에 kill-switch API가 추가되어 있습니다.

- 상태: `GET /api/kill_switch/status`
- ON/OFF: `POST /api/kill_switch/on`, `POST /api/kill_switch/off`

보안상 쓰기 작업은 `WEB_ADMIN_TOKEN`과 `X-Admin-Token` 헤더가 필요합니다.

---

## 8) WEB 대시보드에 v2 엔진 거래내역 반영 여부

현재 웹은 DB 기반 “전략 비교 UI”가 완성된 상태는 아니며, API 중심으로 모니터링하는 구조입니다.

- v2 엔진은 매 iteration마다 다음 로그를 생성합니다:
  - `logs/v2_engine_upbit.json`
  - `logs/v2_engine_binance.json`
- 웹 API는 위 파일을 우선 읽고, 없으면 기존 paper 로그(`logs/paper_trading_*.json`)로 fallback 합니다.

따라서 **v2 엔진의 거래 내역/상태가 웹 API에 반영됩니다**.
