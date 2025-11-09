"""
텔레그램 알림 모듈
매매 신호와 거래 결과를 텔레그램으로 전송
"""

import os
from datetime import datetime
from typing import Optional, Dict, Any
import telegram
from dotenv import load_dotenv


class TelegramNotifier:
    """텔레그램 알림 전송"""

    def __init__(self):
        """환경변수에서 텔레그램 설정 로드"""
        load_dotenv()

        self.bot_token = os.getenv('TELEGRAM_BOT_TOKEN')
        self.chat_id = os.getenv('TELEGRAM_CHAT_ID')

        if not self.bot_token or not self.chat_id:
            raise ValueError("텔레그램 설정이 .env 파일에 없습니다")

        self.bot = telegram.Bot(token=self.bot_token)

    def send_message(self, message: str) -> bool:
        """텔레그램 메시지 전송"""
        try:
            self.bot.send_message(
                chat_id=self.chat_id,
                text=message,
                parse_mode='Markdown'
            )
            return True
        except Exception as e:
            print(f"❌ 텔레그램 전송 실패: {e}")
            return False

    def notify_start(self, strategy: str, capital: float):
        """봇 시작 알림"""
        message = f"""
🤖 *트레이딩 봇 시작*

📊 전략: `{strategy}`
💰 초기 자본: `{capital:,.0f}` KRW
🕐 시작 시간: `{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`

_알림을 받을 준비가 완료되었습니다._
"""
        return self.send_message(message)

    def notify_signal(self, signal_type: str, data: Dict[str, Any]):
        """매매 신호 알림"""

        if signal_type == "BUY":
            emoji = "🟢"
            action = "매수"
        elif signal_type == "SELL":
            emoji = "🔴"
            action = "매도"
        else:
            emoji = "⚪"
            action = "대기"

        message = f"""
{emoji} *매매 신호: {action}*

📅 날짜: `{data.get('date', 'N/A')}`
💵 현재가: `{data.get('price', 0):,.0f}` KRW
📊 시장 상태: `{data.get('market_state', 'N/A')}`
📈 전략: `{data.get('strategy', 'N/A')}`

"""

        if signal_type == "BUY":
            message += f"""
💰 매수 금액: `{data.get('amount', 0):,.0f}` KRW
📊 포지션 크기: `{data.get('position_pct', 0):.1f}%`
🎯 목표가 1: `{data.get('tp1', 0):,.0f}` KRW (+{data.get('tp1_pct', 0):.2f}%)
🎯 목표가 2: `{data.get('tp2', 0):,.0f}` KRW (+{data.get('tp2_pct', 0):.2f}%)
🎯 목표가 3: `{data.get('tp3', 0):,.0f}` KRW (+{data.get('tp3_pct', 0):.2f}%)
🛑 손절가: `{data.get('sl', 0):,.0f}` KRW ({data.get('sl_pct', 0):.2f}%)
"""
        elif signal_type == "SELL":
            message += f"""
💰 매도 금액: `{data.get('amount', 0):,.0f}` KRW
📊 수익률: `{data.get('profit_pct', 0):.2f}%`
💵 수익: `{data.get('profit', 0):,.0f}` KRW
📈 보유 일수: `{data.get('hold_days', 0)}일`
✅ 청산 이유: `{data.get('exit_reason', 'N/A')}`
"""

        return self.send_message(message)

    def notify_trade_executed(self, trade_type: str, result: Dict[str, Any]):
        """거래 실행 결과 알림"""

        if trade_type == "BUY":
            emoji = "✅"
            action = "매수 완료"
        else:
            emoji = "✅"
            action = "매도 완료"

        message = f"""
{emoji} *{action}*

📅 시간: `{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`
💵 체결가: `{result.get('executed_price', 0):,.0f}` KRW
📊 수량: `{result.get('executed_volume', 0):.8f}` BTC
💰 총액: `{result.get('executed_amount', 0):,.0f}` KRW
💸 수수료: `{result.get('fee', 0):,.0f}` KRW

📈 잔고 현황:
  • KRW: `{result.get('krw_balance', 0):,.0f}` KRW
  • BTC: `{result.get('btc_balance', 0):.8f}` BTC
  • 평가액: `{result.get('total_value', 0):,.0f}` KRW
"""

        return self.send_message(message)

    def notify_error(self, error_msg: str):
        """에러 알림"""
        message = f"""
⚠️ *오류 발생*

{error_msg}

_시스템을 확인해주세요._
"""
        return self.send_message(message)

    def notify_daily_report(self, report: Dict[str, Any]):
        """일일 리포트"""
        message = f"""
📊 *일일 리포트*

📅 날짜: `{report.get('date', 'N/A')}`

💰 *잔고*
  • KRW: `{report.get('krw_balance', 0):,.0f}` KRW
  • BTC: `{report.get('btc_balance', 0):.8f}` BTC
  • 평가액: `{report.get('total_value', 0):,.0f}` KRW

📈 *성과*
  • 일 수익률: `{report.get('daily_return', 0):.2f}%`
  • 누적 수익률: `{report.get('total_return', 0):.2f}%`
  • 누적 수익: `{report.get('total_profit', 0):,.0f}` KRW

📊 *거래*
  • 오늘 거래: `{report.get('today_trades', 0)}건`
  • 총 거래: `{report.get('total_trades', 0)}건`
  • 승률: `{report.get('win_rate', 0):.1f}%`
"""

        return self.send_message(message)
