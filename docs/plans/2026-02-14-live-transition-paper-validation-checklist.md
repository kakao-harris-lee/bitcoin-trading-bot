# Live 전환 전 Paper 검증 체크리스트 (Long-Only)

기준일: 2026-02-14

## 1) 목적

`paper` 구간에서 전략/리스크/운영 안정성을 검증한 뒤에만 `live`로 전환한다.  
현재 시스템은 `run.py`에서 live 시작 시 `paper readiness` 게이트를 강제한다.

## 2) 코드상 강제 게이트 (필수)

- live 시작 시 `ENABLE_LIVE_TRADING=1` 필요
- readiness 실패 시 live 기동 거부
- 기본 readiness 기준:
  - 전략별 `EXIT >= 10`
  - 전체 `EXIT >= 40`
  - `win_rate >= 45%`
  - `profit_factor >= 1.0`
  - 총 PnL 양수

실행 명령:

```bash
.venv/bin/python scripts/paper_readiness_check.py \
  --config config/strategies/allocation.json \
  --trades-log logs/trades.runtime.jsonl
```

진행 모니터링:

```bash
.venv/bin/python scripts/paper_readiness_progress.py \
  --config config/strategies/allocation.json \
  --trades-log logs/trades.runtime.jsonl \
  --watch-seconds 60
```

## 3) Long-Only 검증 (필수)

1. 설정 검증: 활성 전략의 `entry.params.skip_bear_regime == true`
2. 로그 검증: `SHORT/COVER` 주문 이벤트 0건
3. Bear/Sideways 구간에서 신규 진입 억제, Bull 구간 중심 진입 확인

예시 로그 점검:

```bash
rg -n '"side":"SHORT"|"position_side":"SHORT"|COVER' logs/trades.runtime.jsonl
rg -n '"event":"ENTRY"|"event":"EXIT"|"event":"DECISION"' logs/trades.runtime.jsonl | tail -n 50
```

## 4) 리스크/운영 검증 (필수)

1. `analysis/KILL_SWITCH` 파일이 없어야 함
2. 일손실 가드/엔트리 차단 동작 확인
3. 봇 프로세스, 크론, 텔레그램 알림 정상 동작
4. 데이터 수신/가격 업데이트 지연 없음

점검 명령:

```bash
./bot.sh status
[ -f analysis/KILL_SWITCH ] && echo "KILL_SWITCH=ON" || echo "KILL_SWITCH=OFF"
ls -1t logs/paper_soak/cron_daily_*.log | head -n 1
tail -n 120 "$(ls -1t logs/paper_soak/cron_daily_*.log | head -n 1)"
```

## 5) GO / NO-GO 기준

- GO:
  - readiness `Ready: YES`
  - long-only 위반 없음(숏 이벤트 0)
  - 최근 운영 로그 에러 반복 없음
  - 리스크 가드 정상
- NO-GO:
  - readiness 미달
  - 숏 이벤트 또는 의도치 않은 시장/포지션 동작 발견
  - 크론/알림/데이터 수집 실패 반복

## 6) Live 전환 절차

1. paper 최종 체크 실행:

```bash
.venv/bin/python scripts/paper_readiness_check.py \
  --config config/strategies/allocation.json \
  --trades-log logs/trades.runtime.jsonl
```

2. readiness 통과 확인 후 전환:

```bash
./bot.sh restart --trend=live
```

3. 전환 직후 10~30분 집중 모니터링:
   - 신규 주문/포지션/잔고 반영
   - 예상과 다른 체결(시장, 수량, 방향) 여부
   - 에러/예외 및 텔레그램 알림

## 7) 즉시 롤백 절차

문제 발생 시:

```bash
./bot.sh restart --trend=paper
```

필요 시 kill switch:

```bash
touch analysis/KILL_SWITCH
```

원복 후 원인 분석:

- 최근 `logs/bot.log*`
- 최근 `logs/trades.runtime.jsonl`
- 최근 `logs/paper_soak/cron_*.log`

