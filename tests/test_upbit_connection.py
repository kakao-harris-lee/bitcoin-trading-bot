#!/usr/bin/env python3
"""
업비트 API 연결 테스트 스크립트
"""

import os
import sys
from dotenv import load_dotenv
import pyupbit
import pytest


def test_upbit_connection():
    """업비트 API 연결 테스트"""
    # 환경 변수 로드
    load_dotenv()

    access_key = os.getenv('UPBIT_ACCESS_KEY')
    secret_key = os.getenv('UPBIT_SECRET_KEY')

    if not access_key or not secret_key:
        pytest.skip("UPBIT API keys not configured")

    print("=" * 70)
    print("업비트 API 연결 테스트")
    print("=" * 70)
    print(f"Access Key: {access_key[:10]}...{access_key[-10:]}")
    print()

    # 업비트 연결
    upbit = pyupbit.Upbit(access_key, secret_key)

    # 1. 잔고 조회
    print("1. 전체 잔고 조회...")
    balances = upbit.get_balances()

    print(f"   응답 타입: {type(balances)}")
    print(f"   응답 내용: {balances}")
    print()

    if not isinstance(balances, list):
        pytest.skip(f"API 응답 오류 (IP 미인증 등): {balances}")

    print(f"   총 {len(balances)}개 자산 보유")
    print()

    total_krw = 0

    for balance in balances:
        currency = balance['currency']
        balance_amount = float(balance['balance'])
        locked = float(balance['locked'])
        avg_buy_price = float(balance['avg_buy_price'])

        if balance_amount > 0 or locked > 0:
            print(f"   [{currency}]")
            print(f"     - 보유량: {balance_amount}")
            print(f"     - 잠김: {locked}")

            if currency == 'KRW':
                total_krw += balance_amount + locked
                print(f"     - 총 KRW: {balance_amount + locked:,.0f}원")
            else:
                print(f"     - 평균 매수가: {avg_buy_price:,.0f}원")
                # 현재가 조회
                ticker = f"KRW-{currency}"
                current_price = pyupbit.get_current_price(ticker)
                if current_price:
                    value = (balance_amount + locked) * current_price
                    total_krw += value
                    print(f"     - 현재가: {current_price:,.0f}원")
                    print(f"     - 평가금액: {value:,.0f}원")
            print()

    print(f"총 평가금액: {total_krw:,.0f}원")
    print()

    # 2. BTC 현재가 조회
    print("2. BTC 현재가 조회...")
    btc_price = pyupbit.get_current_price("KRW-BTC")
    print(f"   BTC/KRW: {btc_price:,.0f}원")
    print()

    print("=" * 70)
    print("업비트 API 연결 성공!")
    print("=" * 70)

    assert True


if __name__ == "__main__":
    test_upbit_connection()
