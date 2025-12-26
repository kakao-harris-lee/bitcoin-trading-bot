#!/usr/bin/env python3
"""Trading Engine V2 - Strategy Recommender

최근 장세(레짐)를 분류해서 어떤 전략을 구동할지 추천한다.

- BULL: v35 (long)
- SIDEWAYS: sideways_v2 (long)
- BEAR: short_v1 (short)

주의: 이 스크립트는 "추천"만 한다. 실제 실행/라우팅은 운영 환경에서
프로세스/모듈 구동 방식에 맞게 연결해야 한다.

사용 예:
    .venv/bin/python trading/scripts/recommend_strategy.py --timeframe day --lookback-days 180
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional, Dict

import pandas as pd

# Path bootstrap (same pattern as backtest_v2_strategies.py)
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.data_loader import DataLoader
from trading.scripts.backtest_v2_strategies import (
    V35StrategyAdapter,
    _market_state_to_regime,
)


def _recommend_for_regime(regime: str) -> Dict[str, str]:
    """Return recommended strategy + suggested timeframe.

    NOTE: This repo's current strategy set is effectively multi-timeframe:
    - v35: day (Upbit spot long)
    - sideways_v2: minute240 (Upbit spot long)
    - short_v1: minute240 (Binance futures short)
    """
    if regime == "BULL":
        return {"strategy": "v35", "suggested_timeframe": "day"}
    if regime == "SIDEWAYS":
        return {"strategy": "sideways_v2", "suggested_timeframe": "minute240"}
    if regime == "BEAR":
        return {"strategy": "short_v1", "suggested_timeframe": "minute240"}
    return {"strategy": "unknown", "suggested_timeframe": "unknown"}


def recommend_strategy(
    timeframe: str,
    lookback_days: int,
    db_path: Optional[str] = None,
) -> Dict[str, str]:
    if db_path is None:
        db_path = str(PROJECT_ROOT / "upbit_history_db" / "upbit_bitcoin.db")

    end_ts = pd.Timestamp.utcnow().normalize()  # date boundary
    start_ts = end_ts - pd.Timedelta(days=int(lookback_days))

    loader = DataLoader(db_path)
    df = loader.load_timeframe(timeframe, start_ts.strftime("%Y-%m-%d"), end_ts.strftime("%Y-%m-%d"))

    if df.empty:
        loader.conn.close()
        raise ValueError("No data loaded. Check db_path/timeframe/lookback-days")

    v35 = V35StrategyAdapter()
    df_ind = v35.add_indicators(df)

    # last row classification
    row = df_ind.iloc[-1]
    market_state = v35.classify_market(row)
    regime = _market_state_to_regime(market_state)
    rec = _recommend_for_regime(regime)

    loader.conn.close()

    return {
        "timeframe": timeframe,
        "start": str(df["timestamp"].iloc[0]),
        "end": str(df["timestamp"].iloc[-1]),
        "market_state": market_state,
        "regime": regime,
        "recommended_strategy": rec["strategy"],
        "suggested_timeframe": rec["suggested_timeframe"],
    }


def main():
    import argparse

    parser = argparse.ArgumentParser(description="최근 레짐 기반 전략 추천")
    parser.add_argument("--timeframe", default="day", help="레짐 분류에 사용할 타임프레임")
    parser.add_argument("--lookback-days", type=int, default=180)
    parser.add_argument("--db-path", default=None)
    args = parser.parse_args()

    rec = recommend_strategy(args.timeframe, args.lookback_days, args.db_path)

    print("=" * 80)
    print("🧭 Regime-based Strategy Recommendation")
    print("=" * 80)
    print(f"timeframe: {rec['timeframe']}")
    print(f"range:     {rec['start']} ~ {rec['end']}")
    print(f"state:     {rec['market_state']}  (regime={rec['regime']})")
    print(f"recommend: {rec['recommended_strategy']}  (tf={rec['suggested_timeframe']})")
    print("=" * 80)


if __name__ == "__main__":
    main()
