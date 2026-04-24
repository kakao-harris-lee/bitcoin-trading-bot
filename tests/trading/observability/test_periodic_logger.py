from __future__ import annotations

import logging

import pytest

from trading.observability.periodic_logger import PeriodicLoggerTask


class _FakeRedisClient:
    def __init__(self, prices: list[dict[str, str]]) -> None:
        self._prices = prices
        self.published_events: list[tuple[str, dict[str, str], int | None]] = []

    async def xrevrange(self, stream: str, *args, **kwargs):  # type: ignore[no-untyped-def]
        if stream == "market:prices":
            return [
                (f"{idx}-0", payload)
                for idx, payload in enumerate(reversed(self._prices), start=1)
            ]
        if stream == "strategy:decisions":
            return []
        return []

    async def xadd(self, stream: str, data: dict[str, str], maxlen: int | None = None) -> None:
        self.published_events.append((stream, data, maxlen))


class _FakeRedis:
    def __init__(
        self,
        positions: dict[tuple[str, str], dict[str, str]],
        prices: list[dict[str, str]],
        risk: dict[str, str] | None = None,
    ) -> None:
        self._positions = positions
        self._risk = risk or {
            "mode": "paper",
            "blocked": "false",
            "kill_switch": "false",
            "daily_pnl": "0",
        }
        self._client = _FakeRedisClient(prices)

    async def get_position(self, symbol: str, market: str) -> dict[str, str]:
        payload = dict(self._positions.get((symbol, market), {}))
        if payload:
            payload["symbol"] = symbol
            payload["market"] = market
        return payload

    async def get_risk(self) -> dict[str, str]:
        return dict(self._risk)


@pytest.mark.asyncio
async def test_periodic_logger_counts_spot_positions(caplog: pytest.LogCaptureFixture) -> None:
    redis = _FakeRedis(
        positions={
            ("BTC", "spot"): {
                "quantity": "0.25",
                "entry_price": "100000",
                "strategy": "mlp_direction_btc",
            }
        },
        prices=[{"symbol": "BTC", "price": "101000"}],
    )
    task = PeriodicLoggerTask(redis=redis, symbols=["BTC"], interval_seconds=300)

    with caplog.at_level(logging.INFO):
        await task._log_system_state()

    snapshot = next(
        record.message for record in caplog.records if "SYSTEM SNAPSHOT" in record.message
    )
    assert "positions=1" in snapshot

    _, payload, _ = redis._client.published_events[-1]
    assert payload["position_qty"] == "0.25"
    assert payload["position_market"] == "spot"
    assert payload["position_count"] == "1"


@pytest.mark.asyncio
async def test_periodic_logger_ignores_non_spot_positions(
    caplog: pytest.LogCaptureFixture,
) -> None:
    redis = _FakeRedis(
        positions={
            ("BTC", "spot"): {
                "quantity": "0.10",
                "entry_price": "100000",
                "strategy": "mlp_direction_btc",
            },
            ("BTC", "margin"): {
                "quantity": "0.05",
                "entry_price": "99000",
                "strategy": "mlp_direction_btc",
            },
        },
        prices=[{"symbol": "BTC", "price": "101000"}],
    )
    task = PeriodicLoggerTask(redis=redis, symbols=["BTC"], interval_seconds=300)

    with caplog.at_level(logging.INFO):
        await task._log_system_state()

    snapshot = next(
        record.message for record in caplog.records if "SYSTEM SNAPSHOT" in record.message
    )
    assert "positions=1" in snapshot

    _, payload, _ = redis._client.published_events[-1]
    assert payload["position_count"] == "1"
    assert "positions_json" not in payload
