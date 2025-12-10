#!/usr/bin/env python3
"""
업비트 API 연결 테스트 스크립트
"""

import os
import sys
from dotenv import load_dotenv
import pyupbit

# 환경 변수 로드
load_dotenv()

access_key = os.getenv('UPBIT_ACCESS_KEY')
secret_key = os.getenv('UPBIT_SECRET_KEY')

print("=" * 70)
print("🔍 업비트 API 연결 테스트")
print("=" * 70)
print(f"Access Key: {access_key[:10]}...{access_key[-10:]}")
print()

try:
    # 업비트 연결
    upbit = pyupbit.Upbit(access_key, secret_key)

    # 1. 잔고 조회
    print("✅ 1. 전체 잔고 조회...")
    balances = upbit.get_balances()

    print(f"   응답 타입: {type(balances)}")
    print(f"   응답 내용: {balances}")
    print()

    if not isinstance(balances, list):
        print(f"   ⚠️  예상치 못한 응답 형식입니다.")
        print(f"   응답: {balances}")
        sys.exit(1)

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

    print(f"✅ 총 평가금액: {total_krw:,.0f}원")
    print()

    # 2. BTC 현재가 조회
    print("✅ 2. BTC 현재가 조회...")
    btc_price = pyupbit.get_current_price("KRW-BTC")
    print(f"   BTC/KRW: {btc_price:,.0f}원")
    print()

    # 3. API 권한 확인 (주문 가능한지 테스트)
    print("✅ 3. API 권한 확인...")
    try:
        # 최소 주문 금액보다 작은 금액으로 테스트 (실제 주문 안됨)
        test_result = upbit.buy_limit_order("KRW-BTC", 1, 1)
        print(f"   ⚠️  주문 테스트 결과: {test_result}")
    except Exception as e:
        error_msg = str(e)
        if "less than min" in error_msg.lower() or "최소" in error_msg:
            print(f"   ✅ 거래 권한 있음 (최소 주문 금액 에러 - 정상)")
        elif "permission" in error_msg.lower() or "권한" in error_msg:
            print(f"   ❌ 거래 권한 없음: {error_msg}")
        else:
            print(f"   ⚠️  알 수 없는 에러: {error_msg}")
    print()

    print("=" * 70)
    print("✅ 업비트 API 연결 성공!")
    print("=" * 70)

except Exception as e:
    print(f"❌ 업비트 API 오류: {e}")
    import traceback
    traceback.print_exc()
