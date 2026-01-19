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


class TestFundingTimeDetection:
    """Test funding time detection methods."""

    def test_get_next_funding_time_returns_datetime(self):
        """get_next_funding_time should return a datetime."""
        from datetime import datetime, timezone
        tracker = FundingTracker()

        next_time = tracker.get_next_funding_time()

        assert isinstance(next_time, datetime)
        assert next_time.tzinfo == timezone.utc

    def test_funding_times_are_at_8_hour_intervals(self):
        """Funding times should be at 00:00, 08:00, 16:00 UTC."""
        tracker = FundingTracker()

        next_time = tracker.get_next_funding_time()

        # Hour should be 0, 8, or 16
        assert next_time.hour in [0, 8, 16]
        assert next_time.minute == 0
        assert next_time.second == 0


class TestGetFundingRateAsync:
    """Test async get_funding_rate method."""

    @pytest.mark.asyncio
    async def test_get_funding_rate_without_client_returns_none(self):
        """Without a client, should return None."""
        tracker = FundingTracker(binance_client=None)

        result = await tracker.get_funding_rate("BTC")

        assert result is None

    @pytest.mark.asyncio
    async def test_get_funding_rate_with_mock_client(self):
        """With mock client, should return FundingRate."""
        from unittest.mock import AsyncMock, MagicMock
        from trading.risk.funding_tracker import FundingRate

        # Create mock client
        mock_client = MagicMock()
        mock_client.get_funding_rate = AsyncMock(return_value={
            "symbol": "BTCUSDT",
            "lastFundingRate": "0.0001",
            "nextFundingTime": "1705600000000",
        })

        tracker = FundingTracker(binance_client=mock_client)
        result = await tracker.get_funding_rate("BTC")

        assert result is not None
        assert isinstance(result, FundingRate)
        assert result.symbol == "BTC"
        assert result.rate == pytest.approx(0.0001, rel=0.01)

    @pytest.mark.asyncio
    async def test_get_funding_rate_caches_result(self):
        """Should cache the result after successful fetch."""
        from unittest.mock import AsyncMock, MagicMock

        mock_client = MagicMock()
        mock_client.get_funding_rate = AsyncMock(return_value={
            "symbol": "BTCUSDT",
            "lastFundingRate": "0.0002",
            "nextFundingTime": "1705600000000",
        })

        tracker = FundingTracker(binance_client=mock_client)

        # First call
        result1 = await tracker.get_funding_rate("BTC")
        assert result1 is not None
        assert result1.rate == pytest.approx(0.0002, rel=0.01)

        # Verify it's cached
        assert "BTC" in tracker._rate_cache
        assert tracker._rate_cache["BTC"].rate == pytest.approx(0.0002, rel=0.01)

    @pytest.mark.asyncio
    async def test_get_funding_rate_returns_cache_on_error(self):
        """On API error, should return cached rate if available."""
        from unittest.mock import AsyncMock, MagicMock
        from trading.risk.funding_tracker import FundingRate
        from datetime import datetime, timezone

        mock_client = MagicMock()
        # First call succeeds, second fails
        mock_client.get_funding_rate = AsyncMock(side_effect=[
            {"symbol": "BTCUSDT", "lastFundingRate": "0.0001", "nextFundingTime": "1705600000000"},
            None,  # Simulates failure (returns None)
        ])

        tracker = FundingTracker(binance_client=mock_client)

        # First call - should succeed and cache
        result1 = await tracker.get_funding_rate("BTC")
        assert result1 is not None

        # Second call - API fails but returns cached
        result2 = await tracker.get_funding_rate("BTC")
        assert result2 is not None
        assert result2.rate == result1.rate


class TestIsFundingTime:
    """Test is_funding_time method."""

    def test_is_funding_time_at_midnight_utc(self):
        """is_funding_time should return True at 00:00 UTC."""
        from unittest.mock import patch
        from datetime import datetime, timezone

        tracker = FundingTracker()

        # Mock datetime.now() to return 00:00:30 UTC
        mock_now = datetime(2026, 1, 19, 0, 0, 30, tzinfo=timezone.utc)
        with patch('trading.risk.funding_tracker.datetime') as mock_datetime:
            mock_datetime.now.return_value = mock_now

            result = tracker.is_funding_time()
            assert result is True

    def test_is_funding_time_at_8am_utc(self):
        """is_funding_time should return True at 08:00 UTC."""
        from unittest.mock import patch
        from datetime import datetime, timezone

        tracker = FundingTracker()

        mock_now = datetime(2026, 1, 19, 8, 0, 45, tzinfo=timezone.utc)
        with patch('trading.risk.funding_tracker.datetime') as mock_datetime:
            mock_datetime.now.return_value = mock_now

            result = tracker.is_funding_time()
            assert result is True

    def test_is_funding_time_at_4pm_utc(self):
        """is_funding_time should return True at 16:00 UTC."""
        from unittest.mock import patch
        from datetime import datetime, timezone

        tracker = FundingTracker()

        mock_now = datetime(2026, 1, 19, 16, 0, 15, tzinfo=timezone.utc)
        with patch('trading.risk.funding_tracker.datetime') as mock_datetime:
            mock_datetime.now.return_value = mock_now

            result = tracker.is_funding_time()
            assert result is True

    def test_is_funding_time_false_at_other_times(self):
        """is_funding_time should return False at non-funding times."""
        from unittest.mock import patch
        from datetime import datetime, timezone

        tracker = FundingTracker()

        # Test at 10:30 UTC (not a funding time)
        mock_now = datetime(2026, 1, 19, 10, 30, 0, tzinfo=timezone.utc)
        with patch('trading.risk.funding_tracker.datetime') as mock_datetime:
            mock_datetime.now.return_value = mock_now

            result = tracker.is_funding_time()
            assert result is False

    def test_is_funding_time_false_after_first_minute(self):
        """is_funding_time should return False after 1 minute past funding."""
        from unittest.mock import patch
        from datetime import datetime, timezone

        tracker = FundingTracker()

        # Test at 00:01:30 UTC (past the 1 minute window)
        mock_now = datetime(2026, 1, 19, 0, 1, 30, tzinfo=timezone.utc)
        with patch('trading.risk.funding_tracker.datetime') as mock_datetime:
            mock_datetime.now.return_value = mock_now

            result = tracker.is_funding_time()
            assert result is False
