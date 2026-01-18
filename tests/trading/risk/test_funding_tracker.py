import pytest
from trading.risk.funding_tracker import FundingTracker


class TestFundingPaymentCalculation:
    """Test funding payment calculations."""

    def test_long_pays_positive_funding(self):
        """Long pays when funding rate is positive."""
        tracker = FundingTracker()

        payment = tracker.calculate_funding_payment(
            position_value=10000,  # $10k position
            rate=0.0001,           # 0.01% funding rate
            side="buy",
        )

        # Long pays: -10000 * 0.0001 = -1.0
        assert payment == pytest.approx(-1.0, rel=0.01)

    def test_short_receives_positive_funding(self):
        """Short receives when funding rate is positive."""
        tracker = FundingTracker()

        payment = tracker.calculate_funding_payment(
            position_value=10000,
            rate=0.0001,
            side="sell",
        )

        # Short receives: +10000 * 0.0001 = +1.0
        assert payment == pytest.approx(1.0, rel=0.01)

    def test_long_receives_negative_funding(self):
        """Long receives when funding rate is negative."""
        tracker = FundingTracker()

        payment = tracker.calculate_funding_payment(
            position_value=10000,
            rate=-0.0002,  # -0.02% negative rate
            side="buy",
        )

        # Long receives: -10000 * -0.0002 = +2.0
        assert payment == pytest.approx(2.0, rel=0.01)

    def test_short_pays_negative_funding(self):
        """Short pays when funding rate is negative."""
        tracker = FundingTracker()

        payment = tracker.calculate_funding_payment(
            position_value=10000,
            rate=-0.0002,
            side="sell",
        )

        # Short pays: +10000 * -0.0002 = -2.0
        assert payment == pytest.approx(-2.0, rel=0.01)
