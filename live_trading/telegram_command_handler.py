"""
텔레그램 명령어 핸들러
봇 명령어를 처리하고 응답
"""

import os
import time
import threading
import requests
from typing import Optional, Callable, Dict, Any
from dotenv import load_dotenv


class TelegramCommandHandler:
    """텔레그램 명령어 처리"""

    def __init__(self, notifier):
        """
        Args:
            notifier: TelegramNotifier 인스턴스
        """
        load_dotenv()

        self.bot_token = os.getenv('TELEGRAM_BOT_TOKEN')
        self.chat_id = os.getenv('TELEGRAM_CHAT_ID')

        if not self.bot_token or not self.chat_id:
            raise ValueError("텔레그램 설정이 .env 파일에 없습니다")

        self.api_url = f"https://api.telegram.org/bot{self.bot_token}"
        self.notifier = notifier

        # 명령어 핸들러 등록
        self.command_handlers: Dict[str, Callable] = {}

        # 마지막 update_id (중복 처리 방지)
        self.last_update_id = 0

        # 명령어 처리 스레드
        self.polling_thread = None
        self.is_polling = False

        print("✅ 텔레그램 명령어 핸들러 초기화 완료")

    def register_command(self, command: str, handler: Callable):
        """
        명령어 핸들러 등록

        Args:
            command: 명령어 (예: "monitor", "status")
            handler: 핸들러 함수
        """
        self.command_handlers[command] = handler
        print(f"✅ 명령어 등록: /{command}")

    def get_updates(self, timeout: int = 30) -> list:
        """
        텔레그램 업데이트 가져오기 (long polling)

        Args:
            timeout: 타임아웃 (초)

        Returns:
            업데이트 리스트
        """
        try:
            url = f"{self.api_url}/getUpdates"
            params = {
                'offset': self.last_update_id + 1,
                'timeout': timeout,
                'allowed_updates': ['message']
            }

            response = requests.get(url, params=params, timeout=timeout + 5)
            response.raise_for_status()

            data = response.json()
            if data.get('ok'):
                return data.get('result', [])
            else:
                print(f"❌ getUpdates 실패: {data}")
                return []

        except requests.exceptions.Timeout:
            # 타임아웃은 정상 (long polling)
            return []
        except Exception as e:
            print(f"❌ getUpdates 에러: {e}")
            return []

    def process_update(self, update: Dict[str, Any]):
        """
        업데이트 처리

        Args:
            update: 텔레그램 업데이트
        """
        try:
            # update_id 업데이트
            self.last_update_id = update.get('update_id', 0)

            # 메시지 추출
            message = update.get('message')
            if not message:
                return

            # chat_id 확인 (보안)
            chat_id = str(message.get('chat', {}).get('id', ''))
            if chat_id != self.chat_id:
                print(f"⚠️  허용되지 않은 chat_id: {chat_id}")
                return

            # 텍스트 메시지인지 확인
            text = message.get('text', '').strip()
            if not text:
                return

            # 명령어인지 확인
            if not text.startswith('/'):
                return

            # 명령어 파싱
            parts = text.split(maxsplit=1)
            command = parts[0][1:]  # '/' 제거
            args = parts[1] if len(parts) > 1 else ''

            print(f"📥 명령어 수신: /{command} {args}")

            # 명령어 처리
            if command in self.command_handlers:
                try:
                    self.command_handlers[command](args)
                except Exception as e:
                    error_msg = f"명령어 처리 실패: {e}"
                    print(f"❌ {error_msg}")
                    self.notifier.send_message(f"⚠️ {error_msg}")
            else:
                # 알 수 없는 명령어
                available_commands = ', '.join([f'/{cmd}' for cmd in self.command_handlers.keys()])
                self.notifier.send_message(
                    f"⚠️ 알 수 없는 명령어: /{command}\n\n"
                    f"사용 가능한 명령어:\n{available_commands}"
                )

        except Exception as e:
            print(f"❌ 업데이트 처리 에러: {e}")

    def start_polling(self):
        """명령어 polling 시작 (백그라운드 스레드)"""
        if self.is_polling:
            print("⚠️  이미 polling 중입니다")
            return

        self.is_polling = True

        def polling_worker():
            print("🔄 텔레그램 명령어 polling 시작...")

            while self.is_polling:
                try:
                    updates = self.get_updates(timeout=30)

                    for update in updates:
                        self.process_update(update)

                except KeyboardInterrupt:
                    break
                except Exception as e:
                    print(f"❌ Polling 에러: {e}")
                    time.sleep(5)

            print("⏸️  텔레그램 명령어 polling 중지")

        self.polling_thread = threading.Thread(target=polling_worker, daemon=True)
        self.polling_thread.start()

        print("✅ 텔레그램 명령어 polling 시작됨")

    def stop_polling(self):
        """명령어 polling 중지"""
        if not self.is_polling:
            return

        self.is_polling = False

        if self.polling_thread:
            self.polling_thread.join(timeout=5)

        print("✅ 텔레그램 명령어 polling 중지됨")
