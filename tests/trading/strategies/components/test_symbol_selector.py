"""Tests for dynamic symbol selector and composite entry gating."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from trading.strategies.components.composite_task import CompositeStrategyTask
from trading.strategies.components.models import MarketContext, MarketData
from trading.strategies.components.symbol_selector import (
    DynamicSymbolSelector,
    SymbolSelectorConfig,
)


def _market_data(
    *,
    symbol: str,
    close: float,
    ema_20: float,
    ema_200: float,
    adx: float,
    volume_ratio: float,
) -> MarketData:
    return MarketData(
        symbol=symbol,
        close=close,
        mfi=55.0,
        adx=adx,
        rsi=50.0,
        timestamp=1700000000000,
        ema_20=ema_20,
        ema_200=ema_200,
        volume=1000.0 * volume_ratio,
        avg_volume_20=1000.0,
    )


def _context(regime: str) -> MarketContext:
    trend = "BULL" if "BULL" in regime else ("BEAR" if "BEAR" in regime else "NEUTRAL")
    return MarketContext(
        trend=trend,  # type: ignore[arg-type]
        regime=regime,  # type: ignore[arg-type]
        volatility_score=0.01,
        is_extreme_volatility=False,
        adx=25.0,
    )


def test_symbol_selector_picks_top_n_by_score() -> None:
    selector = DynamicSymbolSelector(
        SymbolSelectorConfig(
            enabled=True,
            top_n=2,
            refresh_seconds=5.0,
            min_score=-1.0,
            min_adx=10.0,
            min_volume_ratio=0.8,
            require_above_ema200=False,
            skip_bear_regime=False,
        ),
        fallback_symbols=["BTC", "ETH", "XRP"],
    )

    market_data = {
        "BTC": _market_data(
            symbol="BTC", close=110.0, ema_20=100.0, ema_200=95.0, adx=30.0, volume_ratio=1.4
        ),
        "ETH": _market_data(
            symbol="ETH", close=106.0, ema_20=100.0, ema_200=96.0, adx=24.0, volume_ratio=1.1
        ),
        "XRP": _market_data(
            symbol="XRP", close=99.0, ema_20=100.0, ema_200=100.0, adx=18.0, volume_ratio=1.0
        ),
    }
    contexts = {
        "BTC": _context("BULL_STRONG"),
        "ETH": _context("BULL_MODERATE"),
        "XRP": _context("SIDEWAYS_FLAT"),
    }

    changed = selector.refresh(
        now=100.0,
        symbols=["BTC", "ETH", "XRP"],
        market_data=market_data,
        contexts=contexts,
    )

    assert changed is True
    assert selector.selected_symbols == {"BTC", "ETH"}


def test_symbol_selector_keeps_previous_selection_on_empty_cycle() -> None:
    selector = DynamicSymbolSelector(
        SymbolSelectorConfig(
            enabled=True,
            top_n=1,
            refresh_seconds=5.0,
            min_score=0.0,
            min_adx=15.0,
            min_volume_ratio=0.9,
            require_above_ema200=True,
            skip_bear_regime=True,
            keep_previous_on_empty=True,
        ),
        fallback_symbols=["BTC", "ETH"],
    )

    first_market_data = {
        "BTC": _market_data(
            symbol="BTC", close=110.0, ema_20=100.0, ema_200=90.0, adx=28.0, volume_ratio=1.2
        ),
        "ETH": _market_data(
            symbol="ETH", close=98.0, ema_20=100.0, ema_200=102.0, adx=20.0, volume_ratio=1.1
        ),
    }
    first_contexts = {
        "BTC": _context("BULL_STRONG"),
        "ETH": _context("BEAR_STRONG"),
    }
    selector.refresh(
        now=100.0,
        symbols=["BTC", "ETH"],
        market_data=first_market_data,
        contexts=first_contexts,
    )
    assert selector.selected_symbols == {"BTC"}


def test_symbol_selector_rejects_stale_price_data() -> None:
    selector = DynamicSymbolSelector(
        SymbolSelectorConfig(
            enabled=True,
            top_n=2,
            refresh_seconds=5.0,
            min_score=-1.0,
            min_adx=1.0,
            min_volume_ratio=0.0,
            require_above_ema200=False,
            skip_bear_regime=False,
            max_price_age_seconds=5.0,
        ),
        fallback_symbols=["BTC", "ETH"],
    )

    now_ms = int(time.time() * 1000)
    fresh = _market_data(
        symbol="BTC",
        close=110.0,
        ema_20=100.0,
        ema_200=90.0,
        adx=30.0,
        volume_ratio=1.2,
    )
    stale = _market_data(
        symbol="ETH",
        close=109.0,
        ema_20=100.0,
        ema_200=90.0,
        adx=30.0,
        volume_ratio=1.2,
    )
    fresh = MarketData(**{**fresh.__dict__, "timestamp": now_ms})
    stale = MarketData(**{**stale.__dict__, "timestamp": now_ms - 60_000})

    selector.refresh(
        now=100.0,
        symbols=["BTC", "ETH"],
        market_data={"BTC": fresh, "ETH": stale},
        contexts={"BTC": _context("BULL_STRONG"), "ETH": _context("BULL_STRONG")},
    )

    assert selector.selected_symbols == {"BTC"}
    stale_eval = next(x for x in selector.evaluations if x.symbol == "ETH")
    assert stale_eval.eligible is False
    assert stale_eval.reason == "stale_price"

    second_market_data = {
        "BTC": _market_data(
            symbol="BTC", close=95.0, ema_20=100.0, ema_200=100.0, adx=10.0, volume_ratio=0.6
        ),
        "ETH": _market_data(
            symbol="ETH", close=94.0, ema_20=100.0, ema_200=101.0, adx=12.0, volume_ratio=0.7
        ),
    }
    second_contexts = {
        "BTC": _context("BEAR_MODERATE"),
        "ETH": _context("BEAR_STRONG"),
    }

    selector.refresh(
        now=106.0,
        symbols=["BTC", "ETH"],
        market_data=second_market_data,
        contexts=second_contexts,
    )
    assert selector.selected_symbols == {"BTC"}


@pytest.mark.asyncio
async def test_composite_task_symbol_selector_blocks_non_selected_entries() -> None:
    redis = MagicMock()
    redis.publish_event = AsyncMock()
    redis._client = MagicMock()
    redis._client.hset = AsyncMock()

    entry = MagicMock()
    entry.params = MagicMock()
    entry.params.mfi_bull = 52.0
    entry.params.mfi_bear = 48.0
    entry.params.adx_trend = 20.0

    exit_strat = MagicMock()
    exit_strat.params = MagicMock()

    task = CompositeStrategyTask(
        name="selector_test",
        symbols=["BTC", "ETH"],
        redis=redis,
        entry_strategy=entry,
        exit_strategy=exit_strat,
        market="spot",
        config={
            "symbol_selector": {
                "enabled": True,
                "top_n": 1,
                "refresh_seconds": 5,
                "min_score": -1.0,
                "require_above_ema200": False,
                "skip_bear_regime": False,
            }
        },
    )

    btc_md = _market_data(
        symbol="BTC", close=110.0, ema_20=100.0, ema_200=90.0, adx=30.0, volume_ratio=1.3
    )
    eth_md = _market_data(
        symbol="ETH", close=99.0, ema_20=100.0, ema_200=95.0, adx=15.0, volume_ratio=1.0
    )
    btc_ctx = _context("BULL_STRONG")
    eth_ctx = _context("SIDEWAYS_DOWN")

    task._update_symbol_selector_inputs("BTC", btc_md, btc_ctx)
    task._update_symbol_selector_inputs("ETH", eth_md, eth_ctx)
    await task._refresh_symbol_selector_if_due()

    assert task._passes_entry_gates("BTC", btc_md, btc_ctx) is True
    assert task._passes_entry_gates("ETH", eth_md, eth_ctx) is False


@pytest.mark.asyncio
async def test_composite_task_refreshes_selector_when_entry_eval_is_skipped() -> None:
    redis = MagicMock()
    redis.publish_event = AsyncMock()
    redis._client = MagicMock()
    redis._client.hset = AsyncMock()

    entry = MagicMock()
    entry.params = MagicMock()
    entry.params.mfi_bull = 52.0
    entry.params.mfi_bear = 48.0
    entry.params.adx_trend = 20.0

    exit_strat = MagicMock()
    exit_strat.params = MagicMock()

    task = CompositeStrategyTask(
        name="selector_refresh_skip_eval",
        symbols=["BTC", "ETH"],
        redis=redis,
        entry_strategy=entry,
        exit_strategy=exit_strat,
        market="spot",
        config={
            "symbol_selector": {
                "enabled": True,
                "top_n": 1,
                "refresh_seconds": 5,
                "min_score": -1.0,
                "require_above_ema200": False,
                "skip_bear_regime": False,
            }
        },
    )

    btc_md = _market_data(
        symbol="BTC", close=110.0, ema_20=100.0, ema_200=90.0, adx=30.0, volume_ratio=1.2
    )
    btc_ctx = _context("BULL_STRONG")

    task._get_cached_blocked = AsyncMock(return_value=False)  # type: ignore[method-assign]
    task._get_cached_position = AsyncMock(return_value=None)  # type: ignore[method-assign]
    task._should_evaluate_entry = MagicMock(return_value=False)  # type: ignore[method-assign]
    task._build_market_data = MagicMock(return_value=btc_md)  # type: ignore[method-assign]
    task._build_market_context = MagicMock(return_value=btc_ctx)  # type: ignore[method-assign]

    msg = {
        "symbol": "BTC",
        "price": 110.0,
        "timestamp": str(int(time.time() * 1000)),
        "market": "spot",
        "source": "binance",
    }

    await task._handle_message(msg)

    assert task._symbol_selector.selected_symbols == {"BTC"}
    entry.check_entry.assert_not_called()
    redis.publish_event.assert_awaited()
    redis._client.hset.assert_awaited()


def test_data_quality_low_tick_rate_does_not_apply_cooldown_by_default() -> None:
    redis = MagicMock()
    redis.publish_event = AsyncMock()
    redis._client = MagicMock()
    redis._client.hset = AsyncMock()

    entry = MagicMock()
    entry.params = MagicMock()
    entry.params.mfi_bull = 52.0
    entry.params.mfi_bear = 48.0
    entry.params.adx_trend = 20.0

    exit_strat = MagicMock()
    exit_strat.params = MagicMock()

    task = CompositeStrategyTask(
        name="dq_low_tick_default",
        symbols=["BTC"],
        redis=redis,
        entry_strategy=entry,
        exit_strategy=exit_strat,
        market="spot",
        config={
            "data_quality": {
                "enabled": True,
                "max_price_age_seconds": 60.0,
                "min_ticks_per_minute": 10.0,
                "tick_window_seconds": 60,
                "eviction_cooldown_seconds": 120,
            }
        },
    )

    md = _market_data(
        symbol="BTC", close=110.0, ema_20=100.0, ema_200=90.0, adx=30.0, volume_ratio=1.2
    )
    md = MarketData(**{**md.__dict__, "timestamp": int(time.time() * 1000)})

    assessment = task._assess_data_quality("BTC", md, mutate=True)
    assert assessment["allowed"] is False
    assert assessment["reason"] == "low_tick_rate"
    assert "BTC" not in task._dq_blocked_until


def test_data_quality_low_tick_rate_applies_cooldown_when_enabled() -> None:
    redis = MagicMock()
    redis.publish_event = AsyncMock()
    redis._client = MagicMock()
    redis._client.hset = AsyncMock()

    entry = MagicMock()
    entry.params = MagicMock()
    entry.params.mfi_bull = 52.0
    entry.params.mfi_bear = 48.0
    entry.params.adx_trend = 20.0

    exit_strat = MagicMock()
    exit_strat.params = MagicMock()

    task = CompositeStrategyTask(
        name="dq_low_tick_cooldown",
        symbols=["BTC"],
        redis=redis,
        entry_strategy=entry,
        exit_strategy=exit_strat,
        market="spot",
        config={
            "data_quality": {
                "enabled": True,
                "max_price_age_seconds": 60.0,
                "min_ticks_per_minute": 10.0,
                "tick_window_seconds": 60,
                "eviction_cooldown_seconds": 120,
                "cooldown_on_low_tick_rate": True,
            }
        },
    )

    md = _market_data(
        symbol="BTC", close=110.0, ema_20=100.0, ema_200=90.0, adx=30.0, volume_ratio=1.2
    )
    md = MarketData(**{**md.__dict__, "timestamp": int(time.time() * 1000)})

    assessment = task._assess_data_quality("BTC", md, mutate=True)
    assert assessment["allowed"] is False
    assert assessment["reason"] == "low_tick_rate"
    assert task._dq_blocked_until["BTC"] > time.time()


@pytest.mark.asyncio
async def test_composite_task_data_quality_blocks_stale_entry() -> None:
    redis = MagicMock()
    redis.publish_event = AsyncMock()
    redis._client = MagicMock()
    redis._client.hset = AsyncMock()

    entry = MagicMock()
    entry.params = MagicMock()
    entry.params.mfi_bull = 52.0
    entry.params.mfi_bear = 48.0
    entry.params.adx_trend = 20.0

    exit_strat = MagicMock()
    exit_strat.params = MagicMock()

    task = CompositeStrategyTask(
        name="dq_test",
        symbols=["BTC"],
        redis=redis,
        entry_strategy=entry,
        exit_strategy=exit_strat,
        market="spot",
        config={
            "data_quality": {
                "enabled": True,
                "max_price_age_seconds": 1.0,
                "min_ticks_per_minute": 0.0,
                "tick_window_seconds": 60,
                "eviction_cooldown_seconds": 60,
            }
        },
    )

    stale_md = _market_data(
        symbol="BTC", close=110.0, ema_20=100.0, ema_200=90.0, adx=30.0, volume_ratio=1.2
    )
    stale_md = MarketData(**{**stale_md.__dict__, "timestamp": int((time.time() - 30) * 1000)})
    assert task._passes_entry_gates("BTC", stale_md, _context("BULL_STRONG")) is False
