"""
Report Notifier - Sends comparison reports via Telegram.

Handles formatting and delivery of daily backtest comparison reports.
"""
# pylint: disable=broad-exception-caught

import logging
from datetime import date
from typing import Optional

from ..notification.telegram_notifier import TelegramNotifier
from .comparison_models import DailyComparisonReport, Severity

logger = logging.getLogger(__name__)


class ReportNotifier:
    """Sends comparison reports via Telegram."""

    # Severity emoji mapping
    SEVERITY_EMOJI = {
        Severity.LOW: "🟢",
        Severity.MEDIUM: "🟡",
        Severity.HIGH: "🔴",
    }

    # P/L difference threshold for warning (5%)
    PNL_WARNING_THRESHOLD = 5.0

    def __init__(self, telegram_notifier: Optional[TelegramNotifier] = None) -> None:
        """
        Initialize the notifier.

        Args:
            telegram_notifier: Existing TelegramNotifier instance (creates new if None)
        """
        if telegram_notifier is None:
            try:
                self._notifier = TelegramNotifier()
            except ValueError as e:
                logger.warning("Could not initialize TelegramNotifier: %s", e)
                self._notifier = None
        else:
            self._notifier = telegram_notifier

    def send_report(self, report: DailyComparisonReport) -> bool:
        """
        Send report summary via Telegram.

        Args:
            report: Report to send

        Returns:
            True if sent successfully, False otherwise
        """
        if self._notifier is None:
            logger.warning("TelegramNotifier not available, skipping notification")
            return False

        try:
            message = self.format_report_message(report)
            result = self._notifier.send_message(message)

            if result:
                logger.info("Report notification sent for %s", report.report_date)
            else:
                logger.warning("Failed to send report notification for %s", report.report_date)

            return result

        except Exception as e:
            logger.error("Error sending report notification: %s", e)
            return False

    def send_failure_notification(self, report_date: date, error: Exception) -> bool:
        """
        Notify about report generation failure.

        Args:
            report_date: Date that failed
            error: Exception that caused failure

        Returns:
            True if notification sent, False otherwise
        """
        if self._notifier is None:
            logger.warning("TelegramNotifier not available, skipping failure notification")
            return False

        try:
            message = self._format_failure_message(report_date, error)
            result = self._notifier.send_message(message)

            if result:
                logger.info("Failure notification sent for %s", report_date)
            else:
                logger.warning("Failed to send failure notification for %s", report_date)

            return result

        except Exception as e:
            logger.error("Error sending failure notification: %s", e)
            return False

    def format_report_message(self, report: DailyComparisonReport) -> str:
        """
        Format report as Telegram-compatible message.

        Args:
            report: Report to format

        Returns:
            Markdown-formatted message string
        """
        severity_emoji = self.SEVERITY_EMOJI.get(report.max_severity, "⚪")

        # Calculate P/L difference
        pnl_diff = abs(report.actual_pnl_pct - report.backtest_pnl_pct)
        has_warning = pnl_diff > self.PNL_WARNING_THRESHOLD

        # Build warning indicator
        warning_text = ""
        if has_warning:
            warning_text = f"\n⚠️ *경고: P/L 차이 {pnl_diff:.1f}% (>{self.PNL_WARNING_THRESHOLD}%)*"

        # Build discrepancy summary
        discrepancy_text = ""
        if report.discrepancies:
            discrepancy_text = "\n\n📋 *주요 불일치:*"
            for i, d in enumerate(report.discrepancies[:3], 1):
                disc_emoji = self.SEVERITY_EMOJI.get(d.severity, "⚪")
                # Truncate explanation for Telegram
                explanation = d.explanation[:40] + "..." if len(d.explanation) > 40 else d.explanation
                discrepancy_text += f"\n  {i}. {disc_emoji} {explanation}"

            if len(report.discrepancies) > 3:
                discrepancy_text += f"\n  _... 외 {len(report.discrepancies) - 3}건_"

        message = f"""📊 *백테스트 비교 리포트*

📅 *날짜:* `{report.report_date}`
📈 *전략:* `{report.strategy_name}`

*거래 횟수:*
  실제: `{report.actual_trades_count}` / 백테스트: `{report.backtest_trades_count}`

*손익 (P/L):*
  실제: `{report.actual_pnl:,.0f}` (`{report.actual_pnl_pct:+.2f}%`)
  백테스트: `{report.backtest_pnl:,.0f}` (`{report.backtest_pnl_pct:+.2f}%`)

*승률:*
  실제: `{report.actual_win_rate:.1f}%` / 백테스트: `{report.backtest_win_rate:.1f}%`

*최대 낙폭:*
  실제: `{report.actual_max_drawdown:.2f}%` / 백테스트: `{report.backtest_max_drawdown:.2f}%`

{severity_emoji} *불일치:* `{report.discrepancy_count}건` (최대 심각도: `{report.max_severity.value}`){warning_text}{discrepancy_text}

_생성 시간: {report.created_at.strftime('%Y-%m-%d %H:%M:%S')}_"""

        return message

    def _format_failure_message(self, report_date: date, error: Exception) -> str:
        """Format failure notification message."""
        return f"""🔴 *백테스트 비교 리포트 실패*

📅 *날짜:* `{report_date}`
❌ *오류:* `{type(error).__name__}`

```
{str(error)[:200]}
```

_시스템을 확인해주세요._"""

    def send_all_reports(self, reports: list[DailyComparisonReport]) -> int:
        """
        Send multiple reports via Telegram.

        Args:
            reports: List of reports to send

        Returns:
            Number of successfully sent reports
        """
        success_count = 0

        for report in reports:
            if self.send_report(report):
                success_count += 1

        return success_count
