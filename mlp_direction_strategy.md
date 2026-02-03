# MLP Direction Strategy 논문 재현 상태 (s00500-025-10980-7)

## 1) 논문 핵심 요약 (재현 기준)
- **데이터셋**: Binance USDT 페어, 4시간 봉(1 sample/4h). 400개 이상(본문: 402~403개) 코인으로 학습/테스트용 데이터셋 구성. BTC/ETH는 학습에서 제외하고 별도 검증(백테스트+포워드) 사용.
- **기간**: 학습/테스트용 다중 코인 데이터는 2017-08-17 ~ 2022-12-04. BTC/ETH 포워드 테스트는 2022-12-23 ~ 2024-11-11까지 포함.
- **피처(총 36개)**
  - **캔들 패턴 23개**(bull/bear) — Pring(1991) 기반
  - **기술지표 6개**: Bollinger bands(14), ULTOSC(7/14/28), RSI(14), Close % change, Z-Score(30), Volume Z-Score(30)
  - **EMA 크로스 4개**: EMA(1/20), EMA(20/50), EMA(50/100), EMA(1/50)
  - **시간 피처 3개**: 하루 내 샘플 인덱스(4h 봉 기준), 요일, 월
- **라벨링(3-class)**: Buy/Hold/Sell
  - Forward/Backward window(BWin/FWin) 기반
  - 수익률 기준 파라미터 **α=0.038(85th)**, **β=0.24(99.7th)**
  - FWin 증가 시 β를 10%씩 증가(0.024씩 가산)
  - 거래 수수료 0.1% 반영
  - **BWin EMA(5EMA) 기준가** 사용 (Algorithm 1 / Fig. 3)
- **모델**: MLP (LeakyReLU)
  - 입력 128, 은닉 64/32, 출력 3(softmax)
- **검증(트레이딩 시뮬레이션)**
  - **Buy-only 진입**, **MLP SELL 청산 + Stop Loss 10%**, 수수료 0.1%
  - FWin 기반 청산은 사용하지 않는 해석으로 수정
  - 더미(랜덤 Buy/Hold/Sell)와 비교
  - BTC 최적 (BWin=5, FWin=2), ETH 최적 (BWin=4, FWin=2)
- **피처 중요도(SHAP)**
  - EMA 크로스/클래식 지표 중요
  - 캔들 패턴은 상위 중요도에 들지 않아 **비효과적**으로 결론

## 2) 레포 매핑 (핵심 파일)
- **피처 추출**: `trading/indicators/mlp_features.py`
- **라벨링**: `core/mlp_labeling.py`
- **모델**: `mlp_trainer/src/mlp_model.py`
- **데이터셋 빌더**: `mlp_trainer/src/dataset_builder.py`
- **전략 진입/청산**:
  - `trading/strategies/components/mlp_direction_entry.py`
  - `trading/strategies/components/mlp_direction_exit.py`
- **백테스트 예측 캐싱**: `core/component_adapter.py`
- **전략 설정**: `config/strategies/allocation.json`

## 3) 현재 코드 기준 재현 상태
### A. 논문 재현을 위해 반영된 변경점
- **피처 36개 구현** (`paper_36`): 캔들 패턴 + 지표 + EMA 크로스 + 시간 피처 추가
- **지표 파라미터 정합**: Bollinger 14, EMA 1/20/50/100
- **라벨링 기준가**: EMA(close, BWin) 기준가 사용
- **모델 아키텍처**: 기본 설정을 논문 구조에 맞게(드롭아웃 0, 배치정규화 없음)
- **전략 설정**: `mlp_feature_set="paper_36"`, `buy_confidence_threshold=0.0`, `use_mlp_sell_exit=True`, `sell_confidence_threshold=0.0`, `fwin_exit_enabled=False`, `position_size=1.0`, `drawdown_enabled=False`, `stop_loss_cooldown=0`
  - 적용 위치: `config/strategies/allocation.json`의 `mlp_direction_btc` / `mlp_direction_eth` (mode=paper와 동일한 설정)
- **검증 데이터 분리 지원**: BTC/ETH validation을 backtest/forward로 분리 저장 가능
- **BTC/ETH 모델 분리**: BTC(BWin=5,FWin=2), ETH(BWin=4,FWin=2) 모델 경로 분리 적용

### B. 현재 데이터/모델 상태 (2026-02-02 기준)
- **학습 데이터**: `data/multi_asset_4h/train_4h.parquet`
  - 심볼 **207개**, **2017-11-06 ~ 2022-12-22**, 총 **996,954** rows
- **검증 데이터**: `data/multi_asset_4h/validation_4h.parquet`
  - BTCUSDT/ETHUSDT 각 **15,842** rows
  - 기간 **2017-08-17 ~ 2024-11-11**
- **데이터셋 파일**
  - BTC: `data/mlp_datasets/mlp_dataset_bwin5_fwin2.npz`
  - ETH: `data/mlp_datasets/mlp_dataset_bwin4_fwin2.npz`
- **학습 모델**
  - BTC: `models/mlp_direction/btc_bwin5_fwin2/model_final.pt`
  - ETH: `models/mlp_direction/eth_bwin4_fwin2/model_final.pt`

### C. 검증 결과 (mode=paper 백테스트, 4h)
> 설정: buy_confidence_threshold=0.0, stop_loss=10%, use_mlp_sell_exit=True, sell_confidence_threshold=0.0, fwin_exit_enabled=False, position_size=1.0, drawdown/cooldown off, feature_set=paper_36
- **BTC backtest (2017-08-17 ~ 2022-12-22)**  
  - Total Return **+86.83%**, CAGR **+23.42%**, MDD **-61.24%**, Sharpe **+0.55**  
  - Trades **118**, WinRate **75.4%**, ProfitFactor **1.15**
- **BTC forward (2022-12-23 ~ 2024-11-11)**  
  - Total Return **+493.47%**, CAGR **+78.20%**, MDD **-25.64%**, Sharpe **+1.40**  
  - Trades **57**, WinRate **86.0%**, ProfitFactor **2.72**
- **ETH backtest (2017-08-17 ~ 2022-12-22)**  
  - Total Return **+814.10%**, CAGR **+110.62%**, MDD **-50.08%**, Sharpe **+1.20**  
  - Trades **171**, WinRate **78.9%**, ProfitFactor **1.36**
- **ETH forward (2022-12-23 ~ 2024-11-11)**  
  - Total Return **+341.18%**, CAGR **+52.24%**, MDD **-49.81%**, Sharpe **+1.00**  
  - Trades **61**, WinRate **82.0%**, ProfitFactor **1.62**
> 초기 구간(지표 워밍업)에는 MLP 예측 캐시가 비어 경고가 출력되지만, 이후 구간은 precompute 캐시로 동작.  
> CAGR은 equity_curve 시작/종료 값을 사용하므로 total_return과 부호가 다를 수 있음.

### D. 아직 남은 차이/주의점
1) **캔들 패턴 23개 목록 불명확**
   - 논문이 패턴 이름을 명시하지 않아 **TA-Lib의 일반적인 Pring 계열 23개 패턴으로 가정**해 구현함.
   - 정확한 목록을 확보하면 `CANDLE_PATTERNS_PAPER`를 수정 필요.

2) **데이터 규모/기간 불일치**
   - 현재 `train_4h.parquet`은 **207개 심볼**, 기간 **2017-11-06 ~ 2022-12-22**.
   - 논문: **400+ 심볼**, 2017-08-17~2022-12-04 (BTC/ETH는 2024-11-11까지)
   - → 데이터셋 확보가 핵심 재현 리스크.

3) **성과 해석 주의**
   - 수익률은 크게 개선되었으나 MDD가 큰 편이며, 논문 결과와의 직접 비교는 여전히 불확실.
   - 논문 대비 **심볼 수 부족/데이터 범위 차이**는 계속된 주요 리스크.

### E. Optuna 튜닝 포인트 (후보)
- **라벨링**: `bwin`, `fwin`, `alpha`, `beta`, `beta_increment`, `fee`
- **모델**: `hidden_dims`, `dropout`, `lr`, `weight_decay`
- **트레이딩**: `buy_confidence_threshold`, `stop_loss_pct`, `use_mlp_sell_exit`, `sell_confidence_threshold`, `fwin_periods`, `trailing_*`, `take_profit_*`

## 4) 재현 완료를 위한 추가 작업
1) **정확한 23개 캔들 패턴 목록 확보** 후 `CANDLE_PATTERNS_PAPER` 수정
2) **논문 기간/심볼 수에 맞는 데이터 확보** (400+ 코인, 2017~2022)
3) **라벨링 파라미터 재검증** (α/β, FWin별 β 증가 규칙)
4) **재현 성과 개선 검증** (논문 Table 3 지표와 비교)

---
요약: **모델/데이터 파이프라인은 논문 구조에 맞게 구현 완료**했으나, **데이터 규모 격차와 결과 해석 불확실성**이 핵심 갭입니다.
