#!/usr/bin/env python3
"""
바이넨스 API 연결 테스트 스크립트
- API 키 유효성 확인
- 계좌 정보 조회
- USDT 잔액 확인
"""

import os
import sys
from dotenv import load_dotenv

try:
    from binance.client import Client
    from binance.exceptions import BinanceAPIException
except ImportError:
    print("❌ python-binance 패키지가 설치되지 않았습니다.")
    print("다음 명령어로 설치하세요: pip install python-binance")
    sys.exit(1)


def test_binance_connection():
    """바이넨스 API 연결 테스트"""

    # 환경 변수 로드
    load_dotenv()

    api_key = os.getenv('BINANCE_API_KEY')
    api_secret = os.getenv('BINANCE_API_SECRET')

    if not api_key or not api_secret:
        print("❌ 바이넨스 API 키가 .env 파일에 설정되지 않았습니다.")
        return False

    print("=" * 60)
    print("🔍 바이넨스 API 연결 테스트")
    print("=" * 60)
    print(f"API Key: {api_key[:10]}...{api_key[-10:]}")
    print()

    try:
        # 바이넨스 클라이언트 생성
        client = Client(api_key, api_secret)

        # 1. 서버 시간 확인
        print("✅ 1. 서버 연결 테스트...")
        server_time = client.get_server_time()
        print(f"   서버 시간: {server_time['serverTime']}")
        print()

        # 2. 계좌 정보 조회
        print("✅ 2. 계좌 정보 조회...")
        account = client.get_account()
        print(f"   계좌 타입: {account.get('accountType', 'N/A')}")
        print(f"   거래 가능 여부: {account.get('canTrade', False)}")
        print(f"   입금 가능 여부: {account.get('canDeposit', False)}")
        print(f"   출금 가능 여부: {account.get('canWithdraw', False)}")
        print()

        # 3. USDT 잔액 확인
        print("✅ 3. USDT 잔액 확인...")
        balances = account['balances']
        usdt_balance = None

        for balance in balances:
            if balance['asset'] == 'USDT':
                usdt_balance = balance
                break

        if usdt_balance:
            free = float(usdt_balance['free'])
            locked = float(usdt_balance['locked'])
            total = free + locked

            print(f"   사용 가능: {free:.4f} USDT")
            print(f"   잠금: {locked:.4f} USDT")
            print(f"   총 잔액: {total:.4f} USDT")

            if total < 10:
                print(f"   ⚠️  잔액이 부족합니다 (최소 10 USDT 권장)")
            else:
                print(f"   ✅ 충분한 잔액이 있습니다")
        else:
            print("   ⚠️  USDT 잔액을 찾을 수 없습니다")
        print()

        # 4. 기타 자산 확인
        print("✅ 4. 기타 보유 자산...")
        other_assets = []
        for balance in balances:
            total_balance = float(balance['free']) + float(balance['locked'])
            if total_balance > 0 and balance['asset'] != 'USDT':
                other_assets.append({
                    'asset': balance['asset'],
                    'free': float(balance['free']),
                    'locked': float(balance['locked']),
                    'total': total_balance
                })

        if other_assets:
            for asset in other_assets[:5]:  # 상위 5개만 표시
                print(f"   {asset['asset']}: {asset['total']:.8f}")
            if len(other_assets) > 5:
                print(f"   ... 외 {len(other_assets) - 5}개")
        else:
            print("   보유 자산 없음")
        print()

        # 5. BTC/USDT 현재 가격 확인
        print("✅ 5. BTC/USDT 현재 가격...")
        ticker = client.get_symbol_ticker(symbol="BTCUSDT")
        btc_price = float(ticker['price'])
        print(f"   BTC/USDT: ${btc_price:,.2f}")
        print()

        print("=" * 60)
        print("✅ 바이넨스 API 연결 성공!")
        print("=" * 60)

        return True

    except BinanceAPIException as e:
        print(f"❌ 바이넨스 API 오류: {e}")
        print(f"   상태 코드: {e.status_code}")
        print(f"   메시지: {e.message}")
        return False

    except Exception as e:
        print(f"❌ 예상치 못한 오류: {e}")
        return False


if __name__ == "__main__":
    success = test_binance_connection()
    sys.exit(0 if success else 1)
