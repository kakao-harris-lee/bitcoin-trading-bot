#!/usr/bin/env python3
"""
trader.py
실시간 거래 로직 (추후 Upbit API 연동용)
"""

class RealTimeTrader:
    """실시간 거래 실행기 (수익 모델만 적용)"""

    def __init__(self, api_key: str = None, secret_key: str = None):
        """
        Args:
            api_key: Upbit API 키
            secret_key: Upbit Secret 키
        """
        self.api_key = api_key
        self.secret_key = secret_key
        # TODO: Upbit API 클라이언트 초기화

    def get_current_price(self, market: str = "KRW-BTC") -> float:
        """현재가 조회"""
        # TODO: Upbit API 호출
        raise NotImplementedError("실시간 거래는 수익 모델만 적용됩니다")

    def buy(self, market: str, volume: float):
        """매수"""
        # TODO: Upbit API 호출
        raise NotImplementedError("실시간 거래는 수익 모델만 적용됩니다")

    def sell(self, market: str, volume: float):
        """매도"""
        # TODO: Upbit API 호출
        raise NotImplementedError("실시간 거래는 수익 모델만 적용됩니다")
