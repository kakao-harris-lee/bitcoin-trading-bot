"""
텔레그램 Chat ID 가져오기
봇에게 메시지를 보낸 후 이 스크립트를 실행하세요
"""

import os
from dotenv import load_dotenv
import telegram


def get_chat_id():
    """최근 업데이트에서 Chat ID 가져오기"""

    load_dotenv()
    bot_token = os.getenv('TELEGRAM_BOT_TOKEN')

    if not bot_token:
        print("❌ TELEGRAM_BOT_TOKEN이 .env 파일에 없습니다")
        return

    print(f"봇 토큰: {bot_token[:10]}...")

    try:
        bot = telegram.Bot(token=bot_token)

        # 봇 정보 확인
        bot_info = bot.get_me()
        print(f"\n✅ 봇 정보:")
        print(f"  이름: {bot_info.first_name}")
        print(f"  유저네임: @{bot_info.username}")
        print(f"  ID: {bot_info.id}")

        # 최근 업데이트 가져오기
        print(f"\n🔍 최근 메시지 확인 중...")
        updates = bot.get_updates()

        if not updates:
            print("\n⚠️ 메시지가 없습니다.")
            print("\n📱 다음 단계:")
            print(f"1. 텔레그램에서 @{bot_info.username} 봇 검색")
            print("2. /start 명령어 입력")
            print("3. 아무 메시지나 전송")
            print("4. 이 스크립트 다시 실행")
            return

        print(f"\n✅ {len(updates)}개 메시지 발견")

        # 가장 최근 메시지의 Chat ID
        for update in updates[-5:]:  # 최근 5개만
            if update.message:
                chat = update.message.chat
                print(f"\n📩 메시지:")
                print(f"  Chat ID: {chat.id}")
                print(f"  이름: {chat.first_name or 'N/A'}")
                print(f"  유저네임: @{chat.username or 'N/A'}")
                print(f"  메시지: {update.message.text}")

        # 마지막 Chat ID
        last_chat_id = updates[-1].message.chat.id if updates[-1].message else None

        if last_chat_id:
            print(f"\n✅ Chat ID: {last_chat_id}")
            print(f"\n이 Chat ID를 .env 파일의 TELEGRAM_CHAT_ID에 입력하세요:")
            print(f"TELEGRAM_CHAT_ID={last_chat_id}")

    except telegram.error.Unauthorized:
        print("\n❌ 봇 토큰이 잘못되었습니다.")
        print("BotFather에서 새 토큰을 받으세요:")
        print("1. 텔레그램에서 @BotFather 검색")
        print("2. /mybots 입력")
        print("3. 봇 선택 → API Token")

    except Exception as e:
        print(f"\n❌ 오류 발생: {e}")


if __name__ == "__main__":
    get_chat_id()
