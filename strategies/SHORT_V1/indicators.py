#!/usr/bin/env python3
"""
SHORT_V1 - 기술적 지표 계산 모듈
EMA, ADX, +DI, -DI 및 진입/청산 신호 생성
"""

import pandas as pd
import numpy as np
from typing import Tuple, Dict, Optional


class TechnicalIndicators:
    """기술적 지표 계산기"""

    def __init__(self, config: Dict):
        """
        초기화

        Args:
            config: 설정 딕셔너리 (ema_fast, ema_slow, adx_period 등)
        """
        self.ema_fast_period = config.get('indicators', {}).get('ema_fast', 50)
        self.ema_slow_period = config.get('indicators', {}).get('ema_slow', 200)
        self.adx_period = config.get('indicators', {}).get('adx_period', 14)
        self.adx_threshold = config.get('indicators', {}).get('adx_threshold', 25)

    def calculate_ema(self, series: pd.Series, period: int) -> pd.Series:
        """
        지수 이동평균 (EMA) 계산

        Args:
            series: 가격 시리즈
            period: EMA 기간

        Returns:
            EMA 시리즈
        """
        return series.ewm(span=period, adjust=False).mean()

    def calculate_adx(self, df: pd.DataFrame, period: int = 14) -> Tuple[pd.Series, pd.Series, pd.Series]:
        """
        ADX, +DI, -DI 계산

        Args:
            df: OHLC 데이터프레임
            period: ADX 기간 (기본 14)

        Returns:
            (ADX, +DI, -DI) 튜플
        """
        high = df['high']
        low = df['low']
        close = df['close']

        # True Range (TR)
        tr1 = high - low
        tr2 = abs(high - close.shift(1))
        tr3 = abs(low - close.shift(1))
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

        # Directional Movement
        up_move = high - high.shift(1)
        down_move = low.shift(1) - low

        # +DM, -DM
        plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0)
        minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0)

        plus_dm = pd.Series(plus_dm, index=df.index)
        minus_dm = pd.Series(minus_dm, index=df.index)

        # Smoothed TR, +DM, -DM (Wilder's smoothing)
        atr = tr.ewm(alpha=1/period, adjust=False).mean()
        smooth_plus_dm = plus_dm.ewm(alpha=1/period, adjust=False).mean()
        smooth_minus_dm = minus_dm.ewm(alpha=1/period, adjust=False).mean()

        # +DI, -DI
        plus_di = 100 * smooth_plus_dm / atr
        minus_di = 100 * smooth_minus_dm / atr

        # DX
        di_sum = plus_di + minus_di
        di_diff = abs(plus_di - minus_di)
        dx = 100 * di_diff / di_sum.replace(0, np.nan)

        # ADX (smoothed DX)
        adx = dx.ewm(alpha=1/period, adjust=False).mean()

        return adx, plus_di, minus_di

    def add_all_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        모든 지표를 데이터프레임에 추가

        Args:
            df: OHLC 데이터프레임

        Returns:
            지표가 추가된 데이터프레임
        """
        df = df.copy()

        # EMA
        df['ema_fast'] = self.calculate_ema(df['close'], self.ema_fast_period)
        df['ema_slow'] = self.calculate_ema(df['close'], self.ema_slow_period)

        # ADX, +DI, -DI
        df['adx'], df['plus_di'], df['minus_di'] = self.calculate_adx(df, self.adx_period)

        # EMA 크로스오버 신호
        df['ema_cross'] = np.where(
            (df['ema_fast'] < df['ema_slow']) & (df['ema_fast'].shift(1) >= df['ema_slow'].shift(1)),
            -1,  # 데드 크로스 (숏 신호)
            np.where(
                (df['ema_fast'] > df['ema_slow']) & (df['ema_fast'].shift(1) <= df['ema_slow'].shift(1)),
                1,   # 골든 크로스 (청산 신호)
                0
            )
        )

        # 추세 상태
        df['trend'] = np.where(
            df['ema_fast'] > df['ema_slow'],
            'BULL',
            np.where(
                df['ema_fast'] < df['ema_slow'],
                'BEAR',
                'NEUTRAL'
            )
        )

        # DI 우위
        df['di_dominant'] = np.where(
            df['minus_di'] > df['plus_di'],
            'BEAR',
            np.where(
                df['plus_di'] > df['minus_di'],
                'BULL',
                'NEUTRAL'
            )
        )

        # 추세 강도
        df['trend_strength'] = np.where(
            df['adx'] >= self.adx_threshold,
            'STRONG',
            'WEAK'
        )

        return df

    def get_swing_high(self, df: pd.DataFrame, lookback: int = 10) -> pd.Series:
        """
        스윙 하이 계산 (손절 기준점)

        Args:
            df: 데이터프레임
            lookback: 룩백 기간

        Returns:
            스윙 하이 시리즈
        """
        return df['high'].rolling(window=lookback).max()

    def get_swing_low(self, df: pd.DataFrame, lookback: int = 10) -> pd.Series:
        """
        스윙 로우 계산 (익절 기준점)

        Args:
            df: 데이터프레임
            lookback: 룩백 기간

        Returns:
            스윙 로우 시리즈
        """
        return df['low'].rolling(window=lookback).min()


class SignalGenerator:
    """매매 신호 생성기"""

    def __init__(self, config: Dict):
        """
        초기화

        Args:
            config: 전략 설정
        """
        self.config = config
        self.indicators = TechnicalIndicators(config)

        # 진입 조건
        self.adx_min = config.get('entry', {}).get('adx_min', 25)
        self.require_death_cross = config.get('entry', {}).get('require_death_cross', True)
        self.di_negative_dominant = config.get('entry', {}).get('di_negative_dominant', True)
        self.require_bearish_candle = config.get('entry', {}).get('require_bearish_candle', False)

        # 청산 조건
        self.stop_loss_pct = config.get('exit', {}).get('stop_loss_pct', 3.0)
        self.max_stop_loss_pct = config.get('exit', {}).get('max_stop_loss_pct', 5.0)
        self.risk_reward_ratio = config.get('exit', {}).get('risk_reward_ratio', 2.5)
        self.exit_on_golden_cross = config.get('exit', {}).get('exit_on_golden_cross', True)

    def check_entry_signal(self, row: pd.Series, prev_row: Optional[pd.Series] = None) -> Dict:
        """
        숏 진입 신호 확인

        Args:
            row: 현재 캔들 데이터
            prev_row: 이전 캔들 데이터 (선택)

        Returns:
            {'signal': bool, 'reason': str, 'strength': float}
        """
        reasons = []
        strength = 0.0

        # 조건 1: EMA 데드 크로스 또는 이미 BEAR 추세
        if self.require_death_cross:
            if row.get('ema_cross', 0) == -1:
                reasons.append('DEATH_CROSS')
                strength += 0.4
            elif row.get('trend', '') == 'BEAR':
                reasons.append('BEAR_TREND')
                strength += 0.2
            else:
                return {'signal': False, 'reason': 'NO_BEAR_TREND', 'strength': 0}

        # 조건 2: ADX >= 임계값 (강한 추세)
        adx = row.get('adx', 0)
        if adx >= self.adx_min:
            reasons.append(f'ADX_{adx:.1f}')
            strength += 0.3
        else:
            return {'signal': False, 'reason': f'WEAK_TREND_ADX_{adx:.1f}', 'strength': 0}

        # 조건 3: -DI > +DI (하락 추세 우위)
        if self.di_negative_dominant:
            if row.get('di_dominant', '') == 'BEAR':
                reasons.append('DI_BEAR')
                strength += 0.2
            else:
                return {'signal': False, 'reason': 'DI_NOT_BEAR', 'strength': 0}

        # 조건 4: 음봉 확인 (선택)
        if self.require_bearish_candle:
            if row['close'] < row['open']:
                reasons.append('BEARISH_CANDLE')
                strength += 0.1
            else:
                return {'signal': False, 'reason': 'NOT_BEARISH_CANDLE', 'strength': 0}

        return {
            'signal': True,
            'reason': '+'.join(reasons),
            'strength': min(strength, 1.0)
        }

    def check_exit_signal(
        self,
        row: pd.Series,
        entry_price: float,
        stop_loss_price: float,
        take_profit_price: float
    ) -> Dict:
        """
        청산 신호 확인

        Args:
            row: 현재 캔들 데이터
            entry_price: 진입 가격
            stop_loss_price: 손절 가격
            take_profit_price: 익절 가격

        Returns:
            {'signal': bool, 'reason': str, 'type': 'SL'/'TP'/'REVERSAL'}
        """
        current_price = row['close']
        high_price = row['high']
        low_price = row['low']

        # 손절 확인 (숏이므로 가격이 오르면 손실)
        if high_price >= stop_loss_price:
            return {
                'signal': True,
                'reason': f'STOP_LOSS_HIT_{stop_loss_price:.2f}',
                'type': 'SL',
                'exit_price': stop_loss_price
            }

        # 익절 확인 (숏이므로 가격이 내리면 이익)
        if low_price <= take_profit_price:
            return {
                'signal': True,
                'reason': f'TAKE_PROFIT_HIT_{take_profit_price:.2f}',
                'type': 'TP',
                'exit_price': take_profit_price
            }

        # 골든 크로스 (추세 반전) 시 청산
        if self.exit_on_golden_cross:
            if row.get('ema_cross', 0) == 1:
                return {
                    'signal': True,
                    'reason': 'GOLDEN_CROSS_REVERSAL',
                    'type': 'REVERSAL',
                    'exit_price': current_price
                }

        return {'signal': False, 'reason': 'HOLDING', 'type': None}

    def calculate_position_levels(
        self,
        entry_price: float,
        swing_high: float,
        max_sl_pct: float = 5.0,
        rr_ratio: float = 2.5
    ) -> Dict:
        """
        포지션 레벨 계산 (손절/익절 가격)

        Args:
            entry_price: 진입 가격
            swing_high: 스윙 하이 (손절 기준)
            max_sl_pct: 최대 손절 비율 (%)
            rr_ratio: 리스크:리워드 비율

        Returns:
            {'stop_loss': float, 'take_profit': float, 'risk_pct': float}
        """
        # 스윙 하이를 손절로 사용 (최대 손절 비율 제한)
        sl_from_swing = swing_high
        sl_from_max = entry_price * (1 + max_sl_pct / 100)

        stop_loss = min(sl_from_swing, sl_from_max)

        # 실제 리스크 계산
        risk_pct = (stop_loss - entry_price) / entry_price * 100

        # 익절가 계산 (R:R 비율 적용)
        reward_pct = risk_pct * rr_ratio
        take_profit = entry_price * (1 - reward_pct / 100)

        return {
            'stop_loss': stop_loss,
            'take_profit': take_profit,
            'risk_pct': risk_pct,
            'reward_pct': reward_pct,
            'rr_ratio': rr_ratio
        }


if __name__ == '__main__':
    # 테스트
    import json
    from pathlib import Path

    config_path = Path(__file__).parent / 'config.json'
    with open(config_path) as f:
        config = json.load(f)

    # 더미 데이터로 테스트
    np.random.seed(42)
    dates = pd.date_range('2024-01-01', periods=100, freq='4h')
    prices = 40000 + np.cumsum(np.random.randn(100) * 500)

    df = pd.DataFrame({
        'open': prices,
        'high': prices + np.random.rand(100) * 200,
        'low': prices - np.random.rand(100) * 200,
        'close': prices + np.random.randn(100) * 100,
        'volume': np.random.rand(100) * 1000
    }, index=dates)

    # 지표 계산
    indicators = TechnicalIndicators(config)
    df = indicators.add_all_indicators(df)

    print("=== 지표 계산 결과 ===")
    print(df[['close', 'ema_fast', 'ema_slow', 'adx', 'plus_di', 'minus_di', 'trend']].tail(10))

    # 신호 생성
    signal_gen = SignalGenerator(config)
    last_row = df.iloc[-1]
    entry_signal = signal_gen.check_entry_signal(last_row)
    print(f"\n진입 신호: {entry_signal}")
