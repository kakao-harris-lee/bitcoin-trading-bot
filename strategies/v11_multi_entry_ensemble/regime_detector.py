#!/usr/bin/env python3
"""
Market Regime Detector for v11

시장 상황을 분류하여 적응형 파라미터 적용
- Strong Bull: ADX > 30, EMA 상승 > 10%
- Bull: ADX > 25, EMA 상승 > 5%
- Sideways: ADX < 20
- Bear: 그 외
"""

import numpy as np
import pandas as pd


class MarketRegimeDetector:
    """시장 상황 탐지기"""

    def __init__(self, config: dict):
        self.config = config['regime_detection']

    def detect(self, df: pd.DataFrame, i: int) -> str:
        """
        현재 시장 상황 판단

        Args:
            df: 데이터프레임 (adx, ema12, ema26 포함)
            i: 현재 인덱스

        Returns:
            'strong_bull' | 'bull' | 'sideways' | 'bear'
        """
        if i < 30:
            return 'sideways'  # 데이터 부족 시 보수적 접근

        row = df.iloc[i]
        adx = row.get('adx', 20)
        ema12 = row.get('ema12', row['close'])
        ema26 = row.get('ema26', row['close'])

        # EMA Slope 계산 (최근 20일 변화율)
        ema12_slope = self._calculate_slope(df, i, 'ema12', window=20)

        # Strong Bull: 강한 상승 추세
        if (adx >= self.config['strong_bull']['min_adx'] and
            ema12_slope >= self.config['strong_bull']['min_ema_slope'] and
            ema12 > ema26):
            return 'strong_bull'

        # Bull: 상승 추세
        if (adx >= self.config['bull']['min_adx'] and
            ema12_slope >= self.config['bull']['min_ema_slope'] and
            ema12 > ema26):
            return 'bull'

        # Sideways: 횡보
        if adx < self.config['sideways']['max_adx']:
            return 'sideways'

        # Bear: 하락 또는 기타
        return 'bear'

    def _calculate_slope(self, df: pd.DataFrame, i: int, column: str, window: int = 20) -> float:
        """
        지표의 기울기 계산

        Args:
            df: 데이터프레임
            i: 현재 인덱스
            column: 계산할 컬럼명
            window: 계산 윈도우

        Returns:
            변화율 (0.1 = 10% 증가)
        """
        if i < window:
            return 0.0

        start_val = df.iloc[i - window][column]
        end_val = df.iloc[i][column]

        if start_val == 0 or pd.isna(start_val) or pd.isna(end_val):
            return 0.0

        slope = (end_val - start_val) / start_val
        return slope

    def get_params(self, regime: str) -> dict:
        """
        시장 상황별 파라미터 반환

        Args:
            regime: 시장 상황 ('strong_bull', 'bull', 'sideways', 'bear')

        Returns:
            {'trailing_stop_pct': float, 'stop_loss_pct': float}
        """
        if regime not in self.config:
            regime = 'sideways'  # 기본값

        return {
            'trailing_stop_pct': self.config[regime]['trailing_stop_pct'],
            'stop_loss_pct': self.config[regime]['stop_loss_pct']
        }


if __name__ == '__main__':
    """테스트"""
    import sys
    sys.path.append('../..')

    import json
    from core.data_loader import DataLoader
    from core.market_analyzer import MarketAnalyzer

    print("=" * 80)
    print("Market Regime Detector Test")
    print("=" * 80)

    # Config 로드
    with open('config.json') as f:
        config = json.load(f)

    # 데이터 로드
    print("\n[1/3] 데이터 로드...")
    with DataLoader('../../upbit_bitcoin.db') as loader:
        df = loader.load_timeframe('day', start_date='2024-01-01', end_date='2024-12-30')

    # 지표 추가
    print("\n[2/3] 지표 추가...")
    df = MarketAnalyzer.add_indicators(df, indicators=['ema', 'adx'])
    df = df.rename(columns={'ema_12': 'ema12', 'ema_26': 'ema26'})

    print(f"  ✅ {len(df)}개 캔들")

    # Regime Detector 생성
    print("\n[3/3] Regime Detection...")
    detector = MarketRegimeDetector(config)

    # 전체 기간 분석
    regimes = []
    for i in range(30, len(df)):
        regime = detector.detect(df, i)
        regimes.append(regime)

    # 통계
    from collections import Counter
    regime_counts = Counter(regimes)

    print(f"\n시장 상황 분포 (2024년):")
    print(f"  Strong Bull: {regime_counts['strong_bull']}일 ({regime_counts['strong_bull']/len(regimes)*100:.1f}%)")
    print(f"  Bull:        {regime_counts['bull']}일 ({regime_counts['bull']/len(regimes)*100:.1f}%)")
    print(f"  Sideways:    {regime_counts['sideways']}일 ({regime_counts['sideways']/len(regimes)*100:.1f}%)")
    print(f"  Bear:        {regime_counts['bear']}일 ({regime_counts['bear']/len(regimes)*100:.1f}%)")

    # 예시
    print(f"\n최근 10일 시장 상황:")
    for i in range(len(df)-10, len(df)):
        regime = detector.detect(df, i)
        params = detector.get_params(regime)
        date = df.iloc[i]['timestamp']
        close = df.iloc[i]['close']
        adx = df.iloc[i].get('adx', 0)

        print(f"  {date}: {regime:12s} | ADX {adx:5.1f} | Close {close:13,.0f} | TS {params['trailing_stop_pct']*100:.0f}% / SL {params['stop_loss_pct']*100:.0f}%")

    print("\n" + "=" * 80)
    print("✅ Regime Detector 테스트 완료")
    print("=" * 80)
