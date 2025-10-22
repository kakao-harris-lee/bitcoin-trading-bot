"""
v-a-14: BULL Trend Strategy

새로운 BULL 시장 추세 추종 전략
"""

import pandas as pd


class BullTrendChecker:
    """
    BULL 시장 추세 추종 전략

    Entry 조건:
    - BULL_STRONG 또는 BULL_MODERATE 시장
    - ADX >= 20 (강한 추세)
    - MACD > Signal (상승 모멘텀)
    - RSI < 70 (과매수 회피)

    Exit:
    - TP: 8%/15%/25% (공격적)
    - SL: -5%
    - Trailing Stop: 고점 -3%
    - Max Hold: 40일
    """

    def __init__(self, config: dict):
        self.config = config.get('bull_trend', {})

    def check_entry(self, row: pd.Series, prev_row: pd.Series, market_state: str) -> dict:
        """
        BULL Trend Entry 조건 체크

        Args:
            row: 현재 캔들
            prev_row: 이전 캔들
            market_state: 시장 상태

        Returns:
            시그널 dict 또는 None
        """
        # 시장 상태 필터
        if market_state not in ['BULL_STRONG', 'BULL_MODERATE']:
            return None

        # ADX 체크 (강한 추세 필수)
        adx_threshold = self.config.get('adx_threshold', 20)
        adx = row.get('adx', 0)

        if adx < adx_threshold:
            return None

        # MACD 상승 모멘텀
        macd_bullish = self.config.get('macd_bullish', True)
        if macd_bullish:
            macd = row.get('macd', 0)
            macd_signal = row.get('macd_signal', 0)

            if macd <= macd_signal:
                return None

        # RSI 과매수 회피
        rsi_max = self.config.get('rsi_max', 70)
        rsi = row.get('rsi', 50)

        if rsi >= rsi_max:
            return None

        # Volume 체크 (Phase 2: 충분한 거래량 필수)
        volume_min = self.config.get('volume_min', 0)
        if volume_min > 0:
            volume_ratio = row.get('volume_ratio', 1.0)
            if volume_ratio < volume_min:
                return None

        # Entry 시그널 생성
        position_fraction = self.config.get('position_size', 0.6)

        return {
            'strategy': 'bull_trend',
            'reason': f'BULL_TREND (ADX={adx:.1f}, MACD>{macd_signal:.0f}, RSI={rsi:.1f})',
            'fraction': position_fraction,
            'market_state': market_state
        }
