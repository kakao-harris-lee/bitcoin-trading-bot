# mplfinance 레짐 차트 설계

## 개요

백테스트 및 실시간 대시보드에서 레짐 판단 지표를 시각화하기 위한 mplfinance 기반 차트 추가.

## 목표

1. 레짐 판단 지표(MFI, ADX, BB, Volume, EMA200)가 잘 동작하는지 시각적으로 확인
2. 매매 신호와 레짐 상태를 한눈에 파악
3. 백테스트 결과 분석 및 실시간 모니터링 지원

## 차트 레이아웃 (컴팩트 3패널)

```
┌─────────────────────────────────────────────────┐
│  [캔들차트]                                      │
│  - OHLC 캔들                                     │
│  - EMA200 (파란선)                               │
│  - Bollinger Bands (회색 음영)                   │
│  - 매수/매도 신호 마커 (▲/▼)                     │
│  - 수익률 곡선 (핑크선, 보조 Y축) ✅             │
│                                          (70%)  │
├─────────────────────────────────────────────────┤
│  [MFI + ADX 오버레이]                            │
│  - MFI (녹색선, 0-100)                          │
│  - ADX (주황선, 0-100)                          │
│  - MFI 52/48 기준선 (점선)                      │
│                                          (15%)  │
├─────────────────────────────────────────────────┤
│  [Volume + Regime]                              │
│  - Volume 바 (회색)                             │
│  - Regime 색상 배경 (BULL=녹색, BEAR=빨강)       │
│                                          (15%)  │
└─────────────────────────────────────────────────┘
```

## 레짐 색상 매핑

| Regime | Color | Hex |
|--------|-------|-----|
| BULL_STRONG | 진한 녹색 | #4CAF50 |
| BULL_MODERATE | 연한 녹색 | #81C784 |
| SIDEWAYS_UP | 연한 회색-녹색 | #B0BEC5 |
| SIDEWAYS_FLAT | 회색 | #90A4AE |
| SIDEWAYS_DOWN | 연한 회색-빨강 | #FFAB91 |
| BEAR_MODERATE | 연한 빨강 | #EF5350 |
| BEAR_STRONG | 진한 빨강 | #C62828 |

## 데이터 요구사항

### 필수 컬럼 (OHLCV)
- `open`, `high`, `low`, `close`, `volume`, `timestamp`

### 지표 컬럼 (add_all_indicators로 생성)
- `mfi`, `adx`, `ema_200`, `bb_upper`, `bb_lower`, `bb_middle`, `avg_volume_20`

### 레짐 컬럼
- `regime` - build_market_context()로 생성

## 구현 범위

### 파일 변경 (✅ 완료)

1. **core/backtest_visualizer.py** ✅
   - `create_regime_chart()` 메서드 추가
   - `_create_trade_markers()` 헬퍼 메서드 추가
   - `_add_regime_background()` 헬퍼 메서드 추가
   - `_add_regime_legend()` 헬퍼 메서드 추가
   - `REGIME_COLORS` 상수 추가
   - mplfinance 의존성 추가 (조건부 임포트)
   - **수익률 곡선 오버레이 추가 (보조 Y축, 핑크선 #E91E63)** ✅

2. **web/services/backtest_runner.py** ✅
   - `_generate_visualization()` 함수에 레짐 차트 생성 추가
   - `regime_chart_path` 결과에 추가
   - **equity_curve 데이터 전달 추가** ✅

3. **web/templates/dashboard.html** ✅
   - `backtest-regime-chart` 컨테이너 추가

4. **web/static/js/dashboard.js** ✅
   - `renderBacktestRegimeChart()` 함수 추가
   - 백테스트 결과 표시 시 레짐 차트 렌더링 호출

5. **web/static/css/style.css** ✅
   - `.chart-description` 스타일 추가

## API

```python
def create_regime_chart(
    self,
    df: pd.DataFrame,
    trades: list[dict] | None = None,
    equity_curve: list[dict] | None = None,
    output_path: str | None = None,
    title: str = "Regime Analysis Chart",
) -> str | None:
    """mplfinance 기반 레짐 분석 차트 생성.

    Args:
        df: OHLCV + 지표 데이터프레임
        trades: 매매 내역 (선택)
        equity_curve: 수익 곡선 데이터 [{'date': str, 'equity': float}, ...]
        output_path: 저장 경로 (선택)
        title: 차트 제목

    Returns:
        저장된 파일 경로 또는 None
    """
```

## 의존성

- mplfinance >= 0.12.10

## 테스트 계획

1. 단위 테스트: create_regime_chart() 메서드
2. 통합 테스트: 백테스트 실행 후 차트 생성 확인
3. 수동 테스트: 대시보드에서 차트 표시 확인
