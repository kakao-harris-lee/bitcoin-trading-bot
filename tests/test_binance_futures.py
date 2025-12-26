#!/usr/bin/env python3
"""
바이넨스 선물 API 연결 테스트 스크립트
- API 키 유효성 확인
- 선물 계좌 정보 조회
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


def test_binance_futures():
    """바이넨스 선물 API 연결 테스트"""

    # 환경 변수 로드
    load_dotenv()

    api_key = os.getenv('BINANCE_API_KEY')
    api_secret = os.getenv('BINANCE_API_SECRET')

    if not api_key or not api_secret:
        print("❌ 바이넨스 API 키가 .env 파일에 설정되지 않았습니다.")
        return False

    print("=" * 60)
    print("🔍 바이넨스 선물 API 연결 테스트")
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

        # 2. 선물 계좌 정보 조회
        print("✅ 2. 선물 계좌 정보 조회...")
        futures_account = client.futures_account()

        total_wallet_balance = float(futures_account.get('totalWalletBalance', 0))
        total_unrealized_profit = float(futures_account.get('totalUnrealizedProfit', 0))
        total_margin_balance = float(futures_account.get('totalMarginBalance', 0))
        available_balance = float(futures_account.get('availableBalance', 0))

        print(f"   총 지갑 잔액: {total_wallet_balance:.4f} USDT")
        print(f"   미실현 손익: {total_unrealized_profit:.4f} USDT")
        print(f"   총 증거금 잔액: {total_margin_balance:.4f} USDT")
        print(f"   사용 가능 잔액: {available_balance:.4f} USDT")
        print()

        # 3. 자산 상세 정보
        print("✅ 3. 자산 상세 정보...")
        assets = futures_account.get('assets', [])
        for asset in assets:
            wallet_balance = float(asset.get('walletBalance', 0))
            if wallet_balance > 0:
                asset_name = asset.get('asset', 'N/A')
                unrealized_profit = float(asset.get('unrealizedProfit', 0))
                available_balance = float(asset.get('availableBalance', 0))

                print(f"   {asset_name}:")
                print(f"     - 지갑 잔액: {wallet_balance:.4f}")
                print(f"     - 사용 가능: {available_balance:.4f}")
                print(f"     - 미실현 손익: {unrealized_profit:.4f}")
        print()

        # 4. 현재 포지션 확인
        print("✅ 4. 현재 포지션 확인...")
        positions = client.futures_position_information()
        active_positions = [p for p in positions if float(p.get('positionAmt', 0)) != 0]

        if active_positions:
            print(f"   활성 포지션: {len(active_positions)}개")
            for pos in active_positions:
                symbol = pos.get('symbol')
                position_amt = float(pos.get('positionAmt', 0))
                entry_price = float(pos.get('entryPrice', 0))
                unrealized_profit = float(pos.get('unRealizedProfit', 0))

                print(f"   {symbol}:")
                print(f"     - 포지션: {position_amt}")
                print(f"     - 진입가: {entry_price}")
                print(f"     - 미실현 손익: {unrealized_profit:.4f} USDT")
        else:
            print("   활성 포지션 없음")
        print()

        # 5. BTC/USDT 선물 현재 가격 확인
        print("✅ 5. BTC/USDT 선물 현재 가격...")
        ticker = client.futures_symbol_ticker(symbol="BTCUSDT")
        btc_price = float(ticker['price'])
        print(f"   BTC/USDT 선물: ${btc_price:,.2f}")
        print()

        # 6. 레버리지 확인
        print("✅ 6. BTC/USDT 레버리지 설정 확인...")
        try:
            leverage_info = client.futures_position_information(symbol="BTCUSDT")
            if leverage_info:
                leverage = leverage_info[0].get('leverage', 'N/A')
                print(f"   현재 레버리지: {leverage}x")
        except Exception as e:
            print(f"   레버리지 정보 조회 실패: {e}")
        print()

        print("=" * 60)
        print("✅ 바이넨스 선물 API 연결 성공!")
        print("=" * 60)

        # 잔액 경고
        if available_balance < 10:
            print("\n⚠️  주의: 사용 가능 잔액이 10 USDT 미만입니다.")
        else:
            print(f"\n✅ 충분한 잔액이 있습니다: {available_balance:.4f} USDT")

        return True

    except BinanceAPIException as e:
        print(f"❌ 바이넨스 API 오류: {e}")
        print(f"   상태 코드: {e.status_code}")
        print(f"   메시지: {e.message}")
        return False

    except Exception as e:
        print(f"❌ 예상치 못한 오류: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = test_binance_futures()
    sys.exit(0 if success else 1)
