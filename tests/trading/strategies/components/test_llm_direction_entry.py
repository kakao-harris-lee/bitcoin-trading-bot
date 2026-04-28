import pytest
import pandas as pd

from trading.strategies.components.llm_direction_entry import (
    LLMDecisionClient,
    LLMDecisionEntryParams,
    LLMDecisionEntryStrategy,
    LLMTradeDecision,
    create_llm_decision_client,
)
from trading.strategies.components.models import MarketData, TradingContext, build_market_context


class StubDecisionClient:
    def __init__(self, decision: LLMTradeDecision | None = None, exc: Exception | None = None):
        self.decision = decision
        self.exc = exc
        self.sync_calls = 0
        self.async_calls = 0

    async def generate_decision_async(self, *, system_prompt: str, user_prompt: str, prompt_version: str) -> LLMTradeDecision:
        self.async_calls += 1
        if self.exc is not None:
            raise self.exc
        assert system_prompt
        assert user_prompt
        assert prompt_version
        return self.decision

    def generate_decision(self, *, system_prompt: str, user_prompt: str, prompt_version: str) -> LLMTradeDecision:
        self.sync_calls += 1
        if self.exc is not None:
            raise self.exc
        assert system_prompt
        assert user_prompt
        assert prompt_version
        return self.decision


def _ctx(
    *,
    symbol: str = "BTC",
    close: float = 100000.0,
    mfi: float = 60.0,
    adx: float = 25.0,
    ema_120: float = 99000.0,
    ema_200: float = 98000.0,
    volume: float = 120.0,
    avg_volume_20: float = 100.0,
    timestamp: int = 1_700_000_000_000,
) -> TradingContext:
    market = MarketData(
        symbol=symbol,
        open=close,
        high=close * 1.01,
        low=close * 0.99,
        close=close,
        volume=volume,
        avg_volume_20=avg_volume_20,
        mfi=mfi,
        adx=adx,
        rsi=58.0,
        atr=1000.0,
        ema_20=close * 0.995,
        ema_120=ema_120,
        ema_200=ema_200,
        timestamp=timestamp,
    )
    regime = build_market_context(mfi=mfi, adx=adx, atr=1000.0, close=close, volume=volume, avg_volume=avg_volume_20)
    return TradingContext(symbol=symbol, timestamp=timestamp, market=market, regime=regime, positions={})


def _history(ts: int) -> pd.DataFrame:
    rows = []
    base = 99_000.0
    for i in range(6):
        rows.append(
            {
                "timestamp": ts - (5 - i) * 14_400_000,
                "open": base + i * 50,
                "high": base + i * 60,
                "low": base + i * 40,
                "close": base + i * 55,
                "volume": 100 + i,
                "mfi": 55 + i * 0.5,
                "adx": 20 + i * 0.5,
                "rsi": 56 + i * 0.3,
                "atr": 900 + i * 5,
                "ema_20": base + i * 45,
                "ema_120": base - 500 + i * 20,
                "ema_200": base - 800 + i * 10,
            }
        )
    return pd.DataFrame(rows)


def test_sync_prepare_and_check_entry_emits_buy_signal():
    decision = LLMTradeDecision(
        action="BUY",
        confidence=0.81,
        reason="trend and momentum aligned",
        prompt_version="btc_eth_v1",
        provider="ollama",
        model="llama3.1:8b",
    )
    client = StubDecisionClient(decision=decision)
    strategy = LLMDecisionEntryStrategy(
        params=LLMDecisionEntryParams(position_size=0.25, confidence_threshold=0.6),
        client=client,
    )
    ctx = _ctx()

    strategy.prepare_entry_decision(ctx, _history(ctx.timestamp))
    signal = strategy.check_entry(ctx)

    assert client.sync_calls == 1
    assert signal is not None
    assert signal.side == "buy"
    assert signal.quantity == 0.25
    assert "LLMDirection entry: BUY" in signal.reason


@pytest.mark.asyncio
async def test_async_prepare_and_check_entry_emits_buy_signal():
    decision = LLMTradeDecision(
        action="BUY",
        confidence=0.72,
        reason="breakout with supportive regime",
        prompt_version="btc_eth_v1",
        provider="ollama",
        model="llama3.1:8b",
    )
    client = StubDecisionClient(decision=decision)
    strategy = LLMDecisionEntryStrategy(client=client)
    ctx = _ctx(symbol="ETH", close=2500.0, ema_120=2450.0, ema_200=2400.0)

    await strategy.prepare_entry_decision_async(ctx, _history(ctx.timestamp))
    signal = strategy.check_entry(ctx)

    assert client.async_calls == 1
    assert signal is not None
    assert signal.symbol == "ETH"


def test_preflight_block_sets_hold_reason_without_calling_provider():
    client = StubDecisionClient(
        decision=LLMTradeDecision(
            action="BUY",
            confidence=0.95,
            reason="should never be used",
        )
    )
    strategy = LLMDecisionEntryStrategy(
        params=LLMDecisionEntryParams(require_close_above_ema120=True),
        client=client,
    )
    ctx = _ctx(close=95000.0, ema_120=98000.0)

    strategy.prepare_entry_decision(ctx, _history(ctx.timestamp))
    signal = strategy.check_entry(ctx)

    assert client.sync_calls == 0
    assert signal is None
    assert "below EMA120" in (strategy.get_last_rejection_reason("BTC") or "")


@pytest.mark.asyncio
async def test_provider_failure_falls_back_to_hold():
    strategy = LLMDecisionEntryStrategy(
        client=StubDecisionClient(exc=RuntimeError("provider down")),
    )
    ctx = _ctx()

    await strategy.prepare_entry_decision_async(ctx, _history(ctx.timestamp))
    signal = strategy.check_entry(ctx)

    assert signal is None
    assert "provider error" in (strategy.get_last_rejection_reason("BTC") or "").lower()


def test_invalid_provider_raises_value_error():
    with pytest.raises(ValueError):
        create_llm_decision_client(
            config=type("Cfg", (), {
                "provider": "invalid",
                "model": "x",
                "api_base_url": "http://localhost",
                "api_key_env": "OPENAI_API_KEY",
                "timeout_seconds": 1.0,
                "max_retries": 0,
                "temperature": 0.0,
                "max_output_tokens": 32,
            })()
        )
