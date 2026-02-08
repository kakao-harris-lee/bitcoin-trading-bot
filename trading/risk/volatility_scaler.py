"""Volatility-based position scaling.

Scales position size inversely with realized volatility using the standard CTA
volatility-targeting approach: position_scale = target_vol / realized_vol.

When volatility doubles, position size halves automatically. This preserves
capital during bear markets (high-vol) and deploys fully during calm bull
markets (low-vol).
"""


def compute_volatility_scale(
    atr: float,
    price: float,
    target_vol: float = 0.02,
    min_scale: float = 0.25,
    max_scale: float = 1.0,
) -> float:
    """Scale position size inversely with realized volatility.

    Formula: scale = target_vol / (atr / price), clamped to [min, max].

    Examples (target_vol=0.02):
        ATR/price = 1% -> scale = 2.0 -> clamped to max_scale (1.0)
        ATR/price = 2% -> scale = 1.0 (neutral)
        ATR/price = 4% -> scale = 0.5 (half position)
        ATR/price = 8% -> scale = 0.25 (quarter position)

    Args:
        atr: Average True Range value.
        price: Current asset price.
        target_vol: Target volatility as fraction (0.02 = 2%).
        min_scale: Minimum allowed scale factor.
        max_scale: Maximum allowed scale factor.

    Returns:
        Scale factor in [min_scale, max_scale].
    """
    if price <= 0 or atr <= 0:
        return 1.0
    realized_vol = atr / price
    if realized_vol <= 0:
        return 1.0
    scale = target_vol / realized_vol
    return max(min_scale, min(max_scale, scale))
