"""Period return comparison helpers for strategy vs buy-and-hold."""
from __future__ import annotations

from typing import Literal

import pandas as pd

PeriodFreq = Literal["M", "Q"]


def normalize_period_freq(value: str) -> PeriodFreq:
    """Normalize user input frequency to month/quarter aliases."""
    raw = (value or "").strip().upper()
    if raw in {"M", "ME", "MONTH", "MONTHLY"}:
        return "M"
    if raw in {"Q", "QE", "QUARTER", "QUARTERLY"}:
        return "Q"
    raise ValueError(f"Unsupported period frequency: {value}")


def _resample_freq(normalized: PeriodFreq) -> str:
    # Pandas deprecates M/Q aliases for resample; use explicit month/quarter-end.
    return "ME" if normalized == "M" else "QE"


def compute_period_returns_from_equity(
    equity_curve: pd.DataFrame | None,
    freq: str,
) -> pd.Series:
    """Convert equity curve into period returns."""
    if equity_curve is None or equity_curve.empty:
        return pd.Series(dtype=float, name="strategy_return")

    normalized = normalize_period_freq(freq)
    df = equity_curve.copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
    df = df.dropna(subset=["timestamp", "total_equity"]).sort_values("timestamp")
    if df.empty:
        return pd.Series(dtype=float, name="strategy_return")

    initial_equity = float(df["total_equity"].iloc[0])
    closes = (
        df.set_index("timestamp")["total_equity"]
        .resample(_resample_freq(normalized))
        .last()
        .dropna()
    )
    if closes.empty:
        return pd.Series(dtype=float, name="strategy_return")

    returns = closes.pct_change()
    returns.iloc[0] = (float(closes.iloc[0]) / initial_equity) - 1.0
    returns.name = "strategy_return"
    return returns.dropna()


def compute_period_returns_from_prices(
    price_df: pd.DataFrame | None,
    freq: str,
    price_column: str = "close",
) -> pd.Series:
    """Convert price series into buy-and-hold period returns."""
    if price_df is None or price_df.empty:
        return pd.Series(dtype=float, name="bnh_return")

    normalized = normalize_period_freq(freq)
    df = price_df.copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
    df = df.dropna(subset=["timestamp", price_column]).sort_values("timestamp")
    if df.empty:
        return pd.Series(dtype=float, name="bnh_return")

    initial_price = float(df[price_column].iloc[0])
    closes = (
        df.set_index("timestamp")[price_column]
        .resample(_resample_freq(normalized))
        .last()
        .dropna()
    )
    if closes.empty:
        return pd.Series(dtype=float, name="bnh_return")

    returns = closes.pct_change()
    returns.iloc[0] = (float(closes.iloc[0]) / initial_price) - 1.0
    returns.name = "bnh_return"
    return returns.dropna()


def build_period_comparison(
    *,
    strategy_returns: pd.Series,
    benchmark_returns: pd.Series,
    symbol: str,
    freq: str,
) -> pd.DataFrame:
    """Build aligned period comparison table."""
    normalized = normalize_period_freq(freq)
    joined = pd.concat([strategy_returns, benchmark_returns], axis=1, join="inner").dropna()
    if joined.empty:
        return pd.DataFrame(
            columns=["period_end", "period", "freq", "symbol", "strategy_return", "bnh_return", "alpha"]
        )

    df = joined.reset_index().rename(columns={"index": "period_end"})
    if "timestamp" in df.columns:
        df = df.rename(columns={"timestamp": "period_end"})
    df["period_end"] = pd.to_datetime(df["period_end"])
    if normalized == "M":
        df["period"] = df["period_end"].dt.to_period("M").astype(str)
    else:
        df["period"] = df["period_end"].dt.to_period("Q").astype(str)
    df["freq"] = normalized
    df["symbol"] = symbol.upper()
    df["alpha"] = df["strategy_return"] - df["bnh_return"]
    return df[
        ["period_end", "period", "freq", "symbol", "strategy_return", "bnh_return", "alpha"]
    ].sort_values("period_end")


def build_portfolio_comparison(per_symbol: pd.DataFrame) -> pd.DataFrame:
    """Aggregate symbol-level period returns into equal-weight portfolio returns."""
    if per_symbol.empty:
        return pd.DataFrame(
            columns=["period_end", "period", "freq", "symbol", "strategy_return", "bnh_return", "alpha"]
        )

    grouped = (
        per_symbol.groupby(["period_end", "period", "freq"], as_index=False)[
            ["strategy_return", "bnh_return"]
        ]
        .mean()
        .sort_values("period_end")
    )
    grouped["alpha"] = grouped["strategy_return"] - grouped["bnh_return"]
    grouped["symbol"] = "PORTFOLIO"
    return grouped[
        ["period_end", "period", "freq", "symbol", "strategy_return", "bnh_return", "alpha"]
    ]


def compound_return(period_returns: pd.Series) -> float:
    """Compound periodic returns into total return."""
    if period_returns is None or period_returns.empty:
        return 0.0
    return float((1.0 + period_returns).prod() - 1.0)


def alpha_by_market_direction(portfolio_periods: pd.DataFrame) -> dict[str, float]:
    """Average alpha split by benchmark direction."""
    if portfolio_periods.empty:
        return {"up_mean_alpha": 0.0, "down_mean_alpha": 0.0}

    up = portfolio_periods[portfolio_periods["bnh_return"] > 0]
    down = portfolio_periods[portfolio_periods["bnh_return"] < 0]
    return {
        "up_mean_alpha": float(up["alpha"].mean()) if not up.empty else 0.0,
        "down_mean_alpha": float(down["alpha"].mean()) if not down.empty else 0.0,
    }
