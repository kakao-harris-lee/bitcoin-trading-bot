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
