#!/usr/bin/env python3
"""
ml_model.py
Random Forest 기반 거래 신호 검증 모델
"""

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import TimeSeriesSplit
from sklearn.metrics import accuracy_score, classification_report
import pickle
from pathlib import Path
from typing import Optional


class MLSignalValidator:
    """Random Forest 기반 거래 신호 검증"""

    def __init__(
        self,
        n_estimators: int = 100,
        max_depth: int = 10,
        confidence_threshold: float = 0.7,
        model_path: Optional[str] = None
    ):
        """
        Args:
            n_estimators: RF 트리 개수
            max_depth: 트리 최대 깊이
            confidence_threshold: 신호 승인 최소 확률
            model_path: 저장된 모델 경로 (.pkl)
        """
        self.n_estimators = n_estimators
        self.max_depth = max_depth
        self.confidence_threshold = confidence_threshold
        self.model_path = model_path

        self.model = None
        self.is_trained = False

        # 모델 로드 (있으면)
        if model_path and Path(model_path).exists():
            self.load_model(model_path)

    def prepare_features(self, df, idx: int, window: int = 30) -> np.ndarray:
        """
        현재 시점의 특징 벡터 생성

        Features (총 15개):
        - RSI (1)
        - MACD, MACD Signal, MACD Hist (3)
        - ADX (1)
        - ATR ratio (1)
        - ROC (1)
        - 최근 5개 캔들 수익률 (5)
        - 볼륨 비율 (1)
        - 가격 대비 위치 (최근 30개 high/low 대비) (2)
        """
        if idx < window:
            return np.zeros(15)

        features = []

        # 1. 기술 지표
        features.append(df.iloc[idx]['rsi'])
        features.append(df.iloc[idx]['macd'])
        features.append(df.iloc[idx]['macd_signal'])
        features.append(df.iloc[idx]['macd_hist'])
        features.append(df.iloc[idx]['adx'])
        features.append(df.iloc[idx]['atr'] / df.iloc[idx]['close'])  # ATR ratio
        features.append(df.iloc[idx]['roc'])

        # 2. 최근 5개 캔들 수익률
        for i in range(1, 6):
            if idx >= i:
                ret = (df.iloc[idx]['close'] - df.iloc[idx - i]['close']) / df.iloc[idx - i]['close']
                features.append(ret)
            else:
                features.append(0.0)

        # 3. 볼륨 비율 (최근 평균 대비)
        recent_volume = df.iloc[idx - window:idx]['volume'].mean()
        current_volume = df.iloc[idx]['volume']
        volume_ratio = current_volume / recent_volume if recent_volume > 0 else 1.0
        features.append(volume_ratio)

        # 4. 가격 위치 (최근 window 기간의 high/low 대비)
        recent_high = df.iloc[idx - window:idx]['high'].max()
        recent_low = df.iloc[idx - window:idx]['low'].min()
        current_close = df.iloc[idx]['close']

        if recent_high > recent_low:
            price_position = (current_close - recent_low) / (recent_high - recent_low)
        else:
            price_position = 0.5

        features.append(price_position)

        # 5. High/Low 대비 현재가 비율
        high_diff = (recent_high - current_close) / current_close if current_close > 0 else 0
        features.append(high_diff)

        return np.array(features)

    def train(self, df, lookahead: int = 20, profit_threshold: float = 0.02):
        """
        모델 학습

        Args:
            df: 학습 데이터 (지표 포함)
            lookahead: 미래 N개 캔들 후 수익률 계산
            profit_threshold: 수익 기준 (2% 이상 상승 = 1, 아니면 0)

        Returns:
            학습 정확도
        """
        X = []
        y = []

        for i in range(30, len(df) - lookahead):
            # 특징 추출
            features = self.prepare_features(df, i)
            X.append(features)

            # 레이블: lookahead 후 수익률
            future_price = df.iloc[i + lookahead]['close']
            current_price = df.iloc[i]['close']
            future_return = (future_price - current_price) / current_price

            # 이진 분류: 수익 (1) vs 비수익 (0)
            label = 1 if future_return > profit_threshold else 0
            y.append(label)

        X = np.array(X)
        y = np.array(y)

        # Random Forest 학습
        self.model = RandomForestClassifier(
            n_estimators=self.n_estimators,
            max_depth=self.max_depth,
            random_state=42,
            n_jobs=-1
        )

        self.model.fit(X, y)
        self.is_trained = True

        # 학습 정확도
        y_pred = self.model.predict(X)
        accuracy = accuracy_score(y, y_pred)

        print(f"✅ 모델 학습 완료 (정확도: {accuracy:.2%})")
        print(f"   - 학습 샘플: {len(X)}")
        print(f"   - 수익 레이블 비율: {y.mean():.2%}")

        return accuracy

    def predict(self, df, idx: int) -> dict:
        """
        거래 신호 검증

        Returns:
            {
                'signal': 'buy' | 'sell' | 'hold',
                'confidence': float (0~1),
                'approved': bool
            }
        """
        if not self.is_trained:
            return {'signal': 'hold', 'confidence': 0.0, 'approved': False}

        # 특징 추출
        features = self.prepare_features(df, idx).reshape(1, -1)

        # 예측
        proba = self.model.predict_proba(features)[0]
        predicted_class = np.argmax(proba)
        confidence = proba[predicted_class]

        # 신호 생성
        if predicted_class == 1 and confidence >= self.confidence_threshold:
            signal = 'buy'
            approved = True
        elif predicted_class == 0 and confidence >= self.confidence_threshold:
            signal = 'sell'
            approved = True
        else:
            signal = 'hold'
            approved = False

        return {
            'signal': signal,
            'confidence': float(confidence),
            'approved': approved
        }

    def save_model(self, path: str):
        """모델 저장"""
        if not self.is_trained:
            print("⚠️  학습되지 않은 모델은 저장할 수 없습니다.")
            return

        Path(path).parent.mkdir(parents=True, exist_ok=True)

        with open(path, 'wb') as f:
            pickle.dump(self.model, f)

        print(f"✅ 모델 저장 완료: {path}")

    def load_model(self, path: str):
        """모델 로드"""
        with open(path, 'rb') as f:
            self.model = pickle.load(f)

        self.is_trained = True
        print(f"✅ 모델 로드 완료: {path}")
