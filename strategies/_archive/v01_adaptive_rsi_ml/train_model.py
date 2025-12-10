#!/usr/bin/env python3
"""
train_model.py
ML 모델 학습 스크립트
"""

import sys
sys.path.append('../..')

import json
from pathlib import Path
from core.data_loader import DataLoader
from market_classifier import add_market_indicators
from ml_model import MLSignalValidator


def main():
    print("="*60)
    print("v01 ML 모델 학습")
    print("="*60)

    # 1. Config 로드
    config_path = Path(__file__).parent / 'config.json'
    with open(config_path) as f:
        config = json.load(f)

    print(f"\n📋 Config: {config['strategy_name']} v{config['version']}")
    print(f"   Timeframe: {config['timeframe']}")
    print(f"   Training window: {config['ml_model']['training_window']}")

    # 2. 데이터 로드
    db_path = Path(__file__).parent / '../../upbit_bitcoin.db'
    print(f"\n📊 데이터 로드 중...")

    with DataLoader(str(db_path)) as loader:
        # 학습용 데이터: 2024-09-01 ~ 2024-12-31
        df_train = loader.load_timeframe(
            config['timeframe'],
            start_date='2024-09-01',
            end_date='2024-12-31'
        )

    print(f"   ✅ 학습 데이터: {len(df_train)} 레코드")
    print(f"   기간: {df_train.iloc[0]['timestamp']} ~ {df_train.iloc[-1]['timestamp']}")

    # 3. 지표 추가
    print(f"\n🔧 기술 지표 계산 중...")
    df_train = add_market_indicators(df_train)
    print(f"   ✅ 지표 추가 완료")

    # 4. ML 모델 생성 및 학습
    print(f"\n🤖 Random Forest 학습 중...")
    ml_model = MLSignalValidator(
        n_estimators=config['ml_model']['n_estimators'],
        max_depth=config['ml_model']['max_depth'],
        confidence_threshold=config['ml_model']['confidence_threshold']
    )

    accuracy = ml_model.train(
        df_train,
        lookahead=20,  # 20개 캔들 후 수익률 예측
        profit_threshold=0.02  # 2% 이상 상승 = 수익
    )

    # 5. 모델 저장
    model_path = Path(__file__).parent / 'v01_model.pkl'
    ml_model.save_model(str(model_path))

    print(f"\n{'='*60}")
    print(f"✅ 학습 완료!")
    print(f"   정확도: {accuracy:.2%}")
    print(f"   모델 경로: {model_path}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
