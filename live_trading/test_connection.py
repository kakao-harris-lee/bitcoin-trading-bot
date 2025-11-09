"""
연결 테스트 스크립트
업비트 API와 텔레그램 봇 연결 확인
"""

from upbit_trader import UpbitTrader
from telegram_notifier import TelegramNotifier


def test_upbit():
    """업비트 API 테스트"""
    print("\n" + "=" * 60)
    print("📊 업비트 API 테스트")
    print("=" * 60)

    try:
        trader = UpbitTrader()

        # 현재가 조회
        price = trader.get_current_price()
        print(f"✅ 현재가 조회: {price:,.0f} KRW")

        # 잔고 조회
        krw, btc = trader.get_balance()
        print(f"✅ KRW 잔고: {krw:,.0f} KRW")
        print(f"✅ BTC 잔고: {btc:.8f} BTC")

        # 총 평가액
        total = trader.get_total_value()
        print(f"✅ 총 평가액: {total:,.0f} KRW")

        print("\n✅ 업비트 API 테스트 성공!")
        return True

    except Exception as e:
        print(f"\n❌ 업비트 API 테스트 실패: {e}")
        return False


def test_telegram():
    """텔레그램 봇 테스트"""
    print("\n" + "=" * 60)
    print("📱 텔레그램 봇 테스트")
    print("=" * 60)

    try:
        notifier = TelegramNotifier()

        # 테스트 메시지 전송
        message = """
🧪 *연결 테스트*

텔레그램 봇이 정상적으로 작동합니다!

_이 메시지를 받으셨다면 설정이 올바르게 완료되었습니다._
"""

        success = notifier.send_message(message)

        if success:
            print("✅ 텔레그램 메시지 전송 성공!")
            print("📱 텔레그램 앱을 확인하세요.")
            return True
        else:
            print("❌ 텔레그램 메시지 전송 실패")
            return False

    except Exception as e:
        print(f"\n❌ 텔레그램 봇 테스트 실패: {e}")
        return False


def main():
    """메인 테스트"""
    print("\n" + "=" * 60)
    print("🔍 실시간 트레이딩 시스템 연결 테스트")
    print("=" * 60)

    # 업비트 테스트
    upbit_ok = test_upbit()

    # 텔레그램 테스트
    telegram_ok = test_telegram()

    # 결과
    print("\n" + "=" * 60)
    print("📋 테스트 결과")
    print("=" * 60)
    print(f"업비트 API: {'✅ 성공' if upbit_ok else '❌ 실패'}")
    print(f"텔레그램 봇: {'✅ 성공' if telegram_ok else '❌ 실패'}")

    if upbit_ok and telegram_ok:
        print("\n🎉 모든 연결 테스트 성공!")
        print("실시간 트레이딩 시스템을 사용할 준비가 되었습니다.\n")
        return True
    else:
        print("\n⚠️ 일부 테스트 실패")
        print(".env 파일의 설정을 확인하세요.\n")
        return False


if __name__ == "__main__":
    main()
