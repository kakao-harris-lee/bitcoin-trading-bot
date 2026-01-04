#!/usr/bin/env python3
"""
Trading Engine V2 - Backtest Runner
V2 전략의 백테스팅 실행

사용법:
    python backtest_v2_strategies.py [--strategy v35|short_v1|both] [--period train|test|all]
"""

import sys
import os
from pathlib import Path
from datetime import datetime
import pandas as pd
import numpy as np
from typing import Dict, Any, Optional

# 경로 설정
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.data_loader import DataLoader
from core.backtester import Backtester

from trading.strategy.v35_long import V35LongStrategy
from trading.strategy.sideways_v1 import SideWaysV1Strategy
from trading.strategy.sideways_v2 import SideWaysV2Strategy

from trading.strategy.regime_router import RegimeRouter as LiveRegimeRouter
from trading.strategy.regime_router import _calc_adx as _live_calc_adx
from trading.strategy.regime_router import _calc_mfi as _live_calc_mfi


def _market_state_to_regime(market_state: str) -> str:
    """Map V35-style market_state to coarse regime labels."""
    if market_state in {"BULL_STRONG", "BULL_MODERATE"}:
        return "BULL"
    if market_state in {"SIDEWAYS_UP", "SIDEWAYS_FLAT", "SIDEWAYS_DOWN"}:
        return "SIDEWAYS"
    if market_state in {"BEAR_MODERATE", "BEAR_STRONG"}:
        return "BEAR"
    return "UNKNOWN"


def _live_market_state_to_regime(market_state: str) -> str:
    """Map live RegimeRouter's market_state to coarse regime labels."""
    if market_state.startswith("BULL"):
        return "BULL"
    if market_state.startswith("SIDEWAYS"):
        return "SIDEWAYS"
    if market_state.startswith("BEAR"):
        return "BEAR"
    return "UNKNOWN"


def _bars_per_day(timeframe: str) -> int:
    """Convert timeframe string to approximate bars-per-day."""
    if timeframe == "day":
        return 1
    if timeframe.startswith("minute"):
        minutes = int(timeframe.replace("minute", ""))
        if minutes <= 0:
            return 1
        return int(round(24 * 60 / minutes))
    return 1


def _scale_sideways_config_for_timeframe(config: Dict, timeframe: str) -> Dict:
    """Scale day-based hold settings to bar counts for intraday data."""
    scaled = dict(config or {})
    bpd = _bars_per_day(timeframe)
    if bpd <= 1:
        return scaled

    # If users override these values, assume they were specified in 'day' units.
    if "max_hold_bars" in scaled:
        scaled["max_hold_bars"] = int(round(float(scaled["max_hold_bars"]) * bpd))
    if "min_hold_bars_for_tp1" in scaled:
        scaled["min_hold_bars_for_tp1"] = int(round(float(scaled["min_hold_bars_for_tp1"]) * bpd))

    return scaled


# =============================================================================
# V35 Long Strategy Adapter (using actual V35LongStrategy)
# =============================================================================

class V35StrategyAdapter:
    """V35 Long 전략 어댑터 - wraps actual V35LongStrategy for backtester compatibility."""

    def __init__(self, config: Dict = None):
        self.strategy = V35LongStrategy(strategy_config=config)
        self._cached_df: Optional[pd.DataFrame] = None

    @property
    def in_position(self) -> bool:
        return self.strategy.in_position

    def __call__(self, df: pd.DataFrame, i: int, params: Dict) -> Dict:
        if i < 200:  # V35 needs 200 bars for EMA warmup
            return {'action': 'hold'}

        if self._cached_df is None or len(df) != len(self._cached_df):
            self._cached_df = self.strategy.add_indicators(df)

        signal = self.strategy.generate_signal(self._cached_df, i)
        return signal or {'action': 'hold'}


# =============================================================================
# Short V1 Strategy Adapter
# =============================================================================

class ShortV1StrategyAdapter:
    """Short V1 전략 어댑터 (기존 Backtester와 호환)"""

    def __init__(self, config: Dict = None):
        self.config = config or self._default_config()
        self.in_position = False
        self.entry_price = 0.0
        self.entry_time = None

        self._cached_df = None

    def _default_config(self) -> Dict:
        return {
            'ema_fast': 50,
            'ema_slow': 200,
            'adx_threshold': 25,
            'stop_loss': 0.02,  # +2% (Short이므로 가격 상승이 손실)
            'take_profit': 0.05,  # -5% (Short이므로 가격 하락이 이익)
        }

    def add_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """EMA 및 ADX 지표 추가"""
        df = df.copy()

        # EMA
        df['ema_fast'] = df['close'].ewm(span=self.config['ema_fast'], adjust=False).mean()
        df['ema_slow'] = df['close'].ewm(span=self.config['ema_slow'], adjust=False).mean()

        # 크로스 감지
        df['death_cross'] = (df['ema_fast'] < df['ema_slow']) & (df['ema_fast'].shift(1) >= df['ema_slow'].shift(1))
        df['golden_cross'] = (df['ema_fast'] > df['ema_slow']) & (df['ema_fast'].shift(1) <= df['ema_slow'].shift(1))

        # ADX
        df['tr'] = np.maximum(
            df['high'] - df['low'],
            np.maximum(
                abs(df['high'] - df['close'].shift(1)),
                abs(df['low'] - df['close'].shift(1))
            )
        )
        df['atr'] = df['tr'].rolling(window=14).mean()

        plus_dm = df['high'].diff()
        minus_dm = -df['low'].diff()
        plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0)
        minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0)

        plus_di = 100 * (plus_dm.rolling(14).mean() / df['atr'])
        minus_di = 100 * (minus_dm.rolling(14).mean() / df['atr'])
        dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di)
        df['adx'] = dx.rolling(14).mean()
        df['plus_di'] = plus_di
        df['minus_di'] = minus_di

        # 추세 방향
        df['trend'] = np.where(df['ema_fast'] > df['ema_slow'], 'UP', 'DOWN')

        return df

    def __call__(self, df: pd.DataFrame, i: int, params: Dict) -> Dict:
        """Backtester 호환 인터페이스"""
        if i < 200:  # EMA 200 워밍업
            return {'action': 'hold'}

        # 지표 계산 (캐싱)
        if self._cached_df is None or len(df) != len(self._cached_df):
            self._cached_df = self.add_indicators(df)

        row = self._cached_df.iloc[i]

        # 포지션 있을 때: 청산 조건 확인
        if self.in_position:
            pnl_pct = (self.entry_price - row['close']) / self.entry_price  # Short

            # 스탑로스 (가격 상승)
            if pnl_pct <= -self.config['stop_loss']:
                self.in_position = False
                return {
                    'action': 'sell',  # Short 청산
                    'fraction': 1.0,
                    'reason': f'SHORT_SL: {pnl_pct*100:.2f}%'
                }

            # 테이크프로핏 (가격 하락)
            if pnl_pct >= self.config['take_profit']:
                self.in_position = False
                return {
                    'action': 'sell',
                    'fraction': 1.0,
                    'reason': f'SHORT_TP: {pnl_pct*100:.2f}%'
                }

            # 골든크로스 시 청산
            if row.get('golden_cross', False):
                self.in_position = False
                return {
                    'action': 'sell',
                    'fraction': 1.0,
                    'reason': f'GOLDEN_CROSS: {pnl_pct*100:.2f}%'
                }

            return {'action': 'hold'}

        # 포지션 없을 때: 진입 조건 확인
        # 데드크로스 + ADX 강세 + -DI > +DI
        if row.get('death_cross', False):
            adx = row.get('adx', 0)
            plus_di = row.get('plus_di', 0)
            minus_di = row.get('minus_di', 0)

            if adx >= self.config['adx_threshold'] and minus_di > plus_di:
                self.in_position = True
                self.entry_price = row['close']
                self.entry_time = row['timestamp']
                return {
                    'action': 'buy',  # Short 진입 (Backtester 관점 매수)
                    'fraction': 0.3,
                    'reason': f'SHORT_ENTRY: DEATH_CROSS, ADX={adx:.1f}'
                }

        return {'action': 'hold'}


# =============================================================================
# SideWays Strategies Adapters
# =============================================================================


class SideWaysV1StrategyAdapter:
    """SideWays_v1 (v-a-08) 어댑터"""

    def __init__(self, config: Dict = None, timeframe: str = "day"):
        cfg = _scale_sideways_config_for_timeframe(config or {}, timeframe)
        self.strategy = SideWaysV1Strategy(strategy_config=cfg)
        self._cached_df = None

    def __call__(self, df: pd.DataFrame, i: int, params: Dict) -> Dict:
        if i < 30:
            return {'action': 'hold'}

        if self._cached_df is None or len(df) != len(self._cached_df):
            self._cached_df = self.strategy.add_indicators(df)

        signal = self.strategy.generate_signal(self._cached_df, i)
        return signal or {'action': 'hold'}


class SideWaysV2StrategyAdapter:
    """SideWays_v2 (v-a-09) 어댑터"""

    def __init__(self, config: Dict = None, timeframe: str = "day"):
        cfg = _scale_sideways_config_for_timeframe(config or {}, timeframe)
        self.strategy = SideWaysV2Strategy(strategy_config=cfg)
        self._cached_df = None

    def __call__(self, df: pd.DataFrame, i: int, params: Dict) -> Dict:
        if i < 30:
            return {'action': 'hold'}

        if self._cached_df is None or len(df) != len(self._cached_df):
            self._cached_df = self.strategy.add_indicators(df)

        signal = self.strategy.generate_signal(self._cached_df, i)
        return signal or {'action': 'hold'}


# =============================================================================
# Regime Router Adapter (V35 vs SideWays_v2)
# =============================================================================


class RegimeRouterV1Adapter:
    """시장 레짐에 따라 전략을 라우팅하는 어댑터.

    - BULL: v35
    - SIDEWAYS: sideways_v2
    - BEAR: (Backtester가 Long-only이므로) hold

    포지션 진입 후에는 레짐이 바뀌더라도 "완전 청산"까지 동일 전략에 고정한다.
    """

    def __init__(self, timeframe: str = "day"):
        self.timeframe = timeframe

        self.v35 = V35StrategyAdapter()
        self.sideways_v2 = SideWaysV2StrategyAdapter(timeframe=timeframe)
        self.router = LiveRegimeRouter()  # Use live router for classification

        self._active_strategy: Optional[str] = None  # 'v35' | 'sideways_v2' | None
        self._cached_df: Optional[pd.DataFrame] = None

    def _classify_market_state(self, df: pd.DataFrame, i: int) -> str:
        """Use live router for market state classification."""
        if self._cached_df is None or len(df) != len(self._cached_df):
            cached = df.copy()
            cached["mfi"] = _live_calc_mfi(cached, period=self.router.mfi_period)
            cached["adx"] = _live_calc_adx(cached, period=self.router.adx_period)
            self._cached_df = cached
        row = self._cached_df.iloc[i]
        return self.router.classify_from_values(
            mfi=float(row.get("mfi", np.nan)),
            adx=float(row.get("adx", np.nan))
        )

    def _pick_strategy_for_regime(self, regime: str) -> Optional[str]:
        if regime == "BULL":
            return "v35"
        if regime == "SIDEWAYS":
            return "sideways_v2"
        return None  # BEAR/UNKNOWN -> no-trade for Backtester

    def _delegate(self, strategy_key: str, df: pd.DataFrame, i: int, params: Dict) -> Dict:
        if strategy_key == "v35":
            return self.v35(df, i, params)
        if strategy_key == "sideways_v2":
            return self.sideways_v2(df, i, params)
        return {"action": "hold"}

    def __call__(self, df: pd.DataFrame, i: int, params: Dict) -> Dict:
        if i < 30:
            return {"action": "hold"}

        # 포지션 보유 중이면 기존 전략을 계속 사용
        if self._active_strategy is not None:
            signal = self._delegate(self._active_strategy, df, i, params)
            if signal.get("action") == "sell" and float(signal.get("fraction", 0.0)) >= 1.0:
                self._active_strategy = None
            return signal

        # 포지션 없으면 레짐 판단 후 전략 선택
        market_state = self._classify_market_state(df, i)
        regime = _market_state_to_regime(market_state)
        picked = self._pick_strategy_for_regime(regime)

        if picked is None:
            return {"action": "hold", "reason": f"ROUTER_NO_TRADE_{regime}"}

        signal = self._delegate(picked, df, i, params)
        if signal.get("action") == "buy":
            self._active_strategy = picked
            signal.setdefault("metadata", {})
            signal["metadata"].update({"router_regime": regime, "router_market_state": market_state, "router_picked": picked})
        return signal


class RegimeRouterLiveAdapter:
    """운영형 RegimeRouter( live_trading/regime_router.py ) 로직을 그대로 사용하는 백테스트 어댑터.

    - 레짐 분류: live RegimeRouter (MFI/ADX 임계값)
    - 라우팅 정책(Upbit 기준):
      - BULL -> v35
      - SIDEWAYS -> sideways_v2
      - BEAR -> hold (Backtester 단일 타임프레임/단일 자산 가정)

    포지션 진입 후에는 "완전 청산"까지 동일 전략에 고정(stickiness).
    """

    def __init__(
        self,
        timeframe: str = "day",
        router_config: Optional[Dict[str, float]] = None,
        bull_policy: str = "v35",
        bull_hold_fraction: float = 1.0,
        sideways_policy: str = "sideways_v2",
        sideways_bear_policy: Optional[str] = None,
        bear_moderate_policy: Optional[str] = None,
        bear_strong_policy: Optional[str] = None,
        v35_fraction_mult: float = 1.0,
        sideways_fraction_mult: float = 1.0,
        sideways_v2_config: Optional[Dict] = None,
    ):
        self.timeframe = timeframe

        # Operational router config (thresholds)
        cfg = dict(router_config or {})
        self.router = LiveRegimeRouter(
            lookback_days=int(cfg.get("lookback_days", 180)),
            mfi_period=int(cfg.get("mfi_period", 14)),
            adx_period=int(cfg.get("adx_period", 14)),
            mfi_bull=float(cfg.get("mfi_bull", 52.0)),
            mfi_bear=float(cfg.get("mfi_bear", 48.0)),
            adx_strong=float(cfg.get("adx_strong", 25.0)),
            adx_trend=float(cfg.get("adx_trend", 20.0)),
            adx_weak=float(cfg.get("adx_weak", 15.0)),
        )
        self.v35 = V35StrategyAdapter()
        self.sideways_v2 = SideWaysV2StrategyAdapter(config=(sideways_v2_config or {}), timeframe=timeframe)

        # BULL routing policy for Upbit
        # - 'v35' (default)
        # - 'hold_long' (enter long when BULL and exit when leaving BULL)
        self.bull_policy = bull_policy
        self.bull_hold_fraction = float(bull_hold_fraction)

        # SIDEWAYS routing policy for Upbit (operational tuning lever)
        # - 'sideways_v2' (default)
        # - 'v35'
        # - 'hold'
        self.sideways_policy = sideways_policy
        self.sideways_bear_policy = sideways_bear_policy

        # BEAR routing policy override (Upbit). Defaults to live policy (hold) when None.
        # Allowed values when set: 'sideways_v2' | 'v35' | 'hold'
        self.bear_moderate_policy = bear_moderate_policy
        self.bear_strong_policy = bear_strong_policy

        self.v35_fraction_mult = float(v35_fraction_mult)
        self.sideways_fraction_mult = float(sideways_fraction_mult)

        self._active_strategy: Optional[str] = None
        self._cached_df: Optional[pd.DataFrame] = None

    def _ensure_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        if self._cached_df is None or len(df) != len(self._cached_df):
            cached = df.copy()
            cached["mfi"] = _live_calc_mfi(cached, period=self.router.mfi_period)
            cached["adx"] = _live_calc_adx(cached, period=self.router.adx_period)
            self._cached_df = cached
        return self._cached_df

    def _pick_strategy(self, market_state: str) -> Optional[str]:
        decision = self.router.decide_from_market_state(market_state)  # default Upbit policy embedded

        if market_state.startswith("BULL"):
            if self.bull_policy == "hold_long":
                return "bull_hold"
            return "v35"

        # Override only SIDEWAYS behavior when requested
        if market_state.startswith("SIDEWAYS"):
            policy = self.sideways_policy
            if market_state == "SIDEWAYS_BEAR" and self.sideways_bear_policy is not None:
                policy = self.sideways_bear_policy

            if policy == "sideways_v2":
                return "sideways_v2"
            if policy == "v35":
                return "v35"
            if policy == "hold":
                return None

        # Override BEAR behavior when requested (lets tuner decide whether to trade in BEAR)
        if market_state.startswith("BEAR"):
            policy: Optional[str] = None
            if market_state == "BEAR_STRONG":
                policy = self.bear_strong_policy
            elif market_state == "BEAR_MODERATE":
                policy = self.bear_moderate_policy

            if policy == "sideways_v2":
                return "sideways_v2"
            if policy == "v35":
                return "v35"
            if policy == "hold":
                return None
        return decision.upbit_strategy

    def _delegate(self, strategy_key: str, df: pd.DataFrame, i: int, params: Dict) -> Dict:
        if strategy_key == "v35":
            sig = self.v35(df, i, params)
            if sig.get("action") in {"buy", "sell"}:
                sig["fraction"] = float(sig.get("fraction", 1.0)) * self.v35_fraction_mult
                sig["fraction"] = max(0.0, min(1.0, float(sig["fraction"])))
            return sig
        if strategy_key == "sideways_v2":
            sig = self.sideways_v2(df, i, params)
            if sig.get("action") in {"buy", "sell"}:
                sig["fraction"] = float(sig.get("fraction", 1.0)) * self.sideways_fraction_mult
                sig["fraction"] = max(0.0, min(1.0, float(sig["fraction"])))
            return sig
        return {"action": "hold"}

    def __call__(self, df: pd.DataFrame, i: int, params: Dict) -> Dict:
        if i < 30:
            return {"action": "hold"}

        # stickiness
        if self._active_strategy is not None:
            # Special handling for bull_hold: hold while BULL, exit fully when leaving BULL.
            if self._active_strategy == "bull_hold":
                cached = self._ensure_indicators(df)
                row = cached.iloc[i]
                market_state = self.router.classify_from_values(mfi=float(row.get("mfi", np.nan)), adx=float(row.get("adx", np.nan)))
                regime = _live_market_state_to_regime(market_state)

                if regime != "BULL":
                    self._active_strategy = None
                    return {
                        "action": "sell",
                        "fraction": 1.0,
                        "reason": f"BULL_HOLD_EXIT_{regime}",
                        "metadata": {
                            "router_type": "live",
                            "router_regime": regime,
                            "router_market_state": market_state,
                            "router_picked": "bull_hold",
                        },
                    }
                return {"action": "hold", "reason": "BULL_HOLD_IN_POSITION"}

            signal = self._delegate(self._active_strategy, df, i, params)
            if signal.get("action") == "sell" and float(signal.get("fraction", 0.0)) >= 1.0:
                self._active_strategy = None
            return signal

        cached = self._ensure_indicators(df)
        row = cached.iloc[i]
        market_state = self.router.classify_from_values(mfi=float(row.get("mfi", np.nan)), adx=float(row.get("adx", np.nan)))
        regime = _live_market_state_to_regime(market_state)
        picked = self._pick_strategy(market_state)

        if picked is None:
            return {"action": "hold", "reason": f"ROUTER_LIVE_NO_TRADE_{regime}"}

        if picked == "bull_hold":
            signal = {
                "action": "buy",
                "fraction": max(0.0, min(1.0, float(self.bull_hold_fraction))),
                "reason": "BULL_HOLD_ENTRY",
            }
        else:
            signal = self._delegate(picked, df, i, params)
        if signal.get("action") == "buy":
            self._active_strategy = picked
            signal.setdefault("metadata", {})
            signal["metadata"].update({
                "router_type": "live",
                "router_regime": regime,
                "router_market_state": market_state,
                "router_picked": picked,
            })
        return signal


# =============================================================================
# Backtest Runner
# =============================================================================

def run_backtest(
    strategy_name: str,
    timeframe: str = 'day',
    start_date: str = '2020-01-01',
    end_date: str = '2024-12-31',
    initial_capital: float = 10_000_000,
    db_path: str = None,
    verbose: bool = True,
) -> Dict:
    """백테스팅 실행"""

    # DB 경로
    if db_path is None:
        db_path = PROJECT_ROOT / 'data' / 'upbit_bitcoin.db'

    if verbose:
        print(f"\n{'='*60}")
        print(f"📊 백테스팅: {strategy_name.upper()}")
        print(f"   타임프레임: {timeframe}")
        print(f"   기간: {start_date} ~ {end_date}")
        print(f"   초기자본: {initial_capital:,.0f}원")
        print(f"{'='*60}")

    # 데이터 로드
    loader = DataLoader(str(db_path))
    df = loader.load_timeframe(timeframe, start_date, end_date)
    if verbose:
        print(f"✅ 데이터 로드: {len(df):,}개 캔들")

    # 전략 선택
    if strategy_name == 'v35':
        strategy = V35StrategyAdapter()
    elif strategy_name == 'short_v1':
        strategy = ShortV1StrategyAdapter()
    elif strategy_name == 'sideways_v1':
        strategy = SideWaysV1StrategyAdapter(timeframe=timeframe)
    elif strategy_name == 'sideways_v2':
        strategy = SideWaysV2StrategyAdapter(timeframe=timeframe)
    elif strategy_name == 'router_v1':
        strategy = RegimeRouterV1Adapter(timeframe=timeframe)
    elif strategy_name == 'router_live':
        strategy = RegimeRouterLiveAdapter(timeframe=timeframe)
    else:
        raise ValueError(f"Unknown strategy: {strategy_name}")

    # 백테스팅 실행
    backtester = Backtester(
        initial_capital=initial_capital,
        fee_rate=0.0005,
        slippage=0.0002
    )

    results = backtester.run(df, strategy, {})

    # 결과 출력
    if verbose:
        print(f"\n📈 결과:")
        print(f"   초기 자본: {results['initial_capital']:,.0f}원")
        print(f"   최종 자본: {results['final_capital']:,.0f}원")
        print(f"   총 수익률: {results['total_return']:.2f}%")
        print(f"   총 거래: {results['total_trades']}회")

    if verbose and results['total_trades'] > 0:
        print(f"   승률: {results['win_rate']*100:.1f}%")
        print(f"   평균 이익: {results['avg_profit']:,.0f}원")
        print(f"   평균 손실: {results['avg_loss']:,.0f}원")
        print(f"   Profit Factor: {results['profit_factor']:.2f}")

    # 추가 분석
    if not results['equity_curve'].empty:
        equity_df = results['equity_curve']

        # 연환산 수익률 (CAGR)
        days = (df['timestamp'].iloc[-1] - df['timestamp'].iloc[0]).days
        years = days / 365.25
        if years > 0:
            cagr = ((results['final_capital'] / results['initial_capital']) ** (1/years) - 1) * 100
            if verbose:
                print(f"   CAGR: {cagr:.2f}%")

        # 최대 낙폭 (MDD)
        peak = equity_df['total_equity'].cummax()
        drawdown = (equity_df['total_equity'] - peak) / peak * 100
        mdd = drawdown.min()
        if verbose:
            print(f"   MDD: {mdd:.2f}%")

        # Sharpe Ratio (일간 수익률 기반)
        daily_returns = equity_df['total_equity'].pct_change().dropna()
        if len(daily_returns) > 0:
            sharpe = (daily_returns.mean() / daily_returns.std()) * np.sqrt(252)
            if verbose:
                print(f"   Sharpe Ratio: {sharpe:.2f}")

        results['cagr'] = cagr if years > 0 else 0
        results['mdd'] = mdd
        results['sharpe'] = sharpe if len(daily_returns) > 0 else 0

    # Buy & Hold 비교
    bh_return = (df['close'].iloc[-1] - df['close'].iloc[0]) / df['close'].iloc[0] * 100
    if verbose:
        print(f"\n📊 Buy & Hold: {bh_return:.2f}%")
        print(f"   Alpha: {results['total_return'] - bh_return:.2f}%p")

    results['buy_hold_return'] = bh_return
    results['alpha'] = results['total_return'] - bh_return

    loader.conn.close()

    return results


def run_full_analysis():
    """전체 분석 실행"""
    print("\n" + "="*80)
    print("🚀 Trading Engine V2 - 전략 백테스팅")
    print("="*80)

    results = {}

    # 1. V35 Long (일봉) - 학습 기간
    print("\n" + "-"*40)
    print("📌 V35 Long Strategy - 학습 기간 (2020-2024)")
    print("-"*40)
    results['v35_train'] = run_backtest(
        'v35', 'day', '2020-01-01', '2024-12-31'
    )

    # 2. V35 Long (일봉) - 검증 기간
    print("\n" + "-"*40)
    print("📌 V35 Long Strategy - 검증 기간 (2025)")
    print("-"*40)
    results['v35_test'] = run_backtest(
        'v35', 'day', '2025-01-01', '2025-12-11'
    )

    # 3. Short V1 (4시간봉) - 학습 기간
    print("\n" + "-"*40)
    print("📌 Short V1 Strategy - 학습 기간 (2020-2024)")
    print("-"*40)
    results['short_train'] = run_backtest(
        'short_v1', 'minute240', '2020-01-01', '2024-12-31'
    )

    # 4. Short V1 (4시간봉) - 검증 기간
    print("\n" + "-"*40)
    print("📌 Short V1 Strategy - 검증 기간 (2025)")
    print("-"*40)
    results['short_test'] = run_backtest(
        'short_v1', 'minute240', '2025-01-01', '2025-12-11'
    )

    # 요약 테이블
    print("\n" + "="*80)
    print("📊 백테스팅 결과 요약")
    print("="*80)
    print(f"{'전략':<20} {'기간':<12} {'수익률':>10} {'CAGR':>10} {'MDD':>10} {'Sharpe':>8} {'Alpha':>10}")
    print("-"*80)

    for key, res in results.items():
        name = key.replace('_train', ' (Train)').replace('_test', ' (Test)')
        name = name.replace('v35', 'V35 Long').replace('short', 'Short V1')
        period = '2020-2024' if 'train' in key else '2025'
        print(f"{name:<20} {period:<12} {res['total_return']:>9.2f}% {res.get('cagr', 0):>9.2f}% {res.get('mdd', 0):>9.2f}% {res.get('sharpe', 0):>7.2f} {res.get('alpha', 0):>+9.2f}%p")

    print("="*80)

    return results


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Trading Engine V2 백테스팅')
    parser.add_argument(
        '--strategy',
        choices=['v35', 'short_v1', 'sideways_v1', 'sideways_v2', 'router_v1', 'router_live', 'both'],
        default='both',
    )
    parser.add_argument('--period', choices=['train', 'test', 'all'], default='all')
    parser.add_argument('--timeframe', default='day')
    parser.add_argument('--start-date', default=None)
    parser.add_argument('--end-date', default=None)
    parser.add_argument('--by-year', action='store_true', help='기간을 연도별로 나눠 요약 테이블 출력')

    args = parser.parse_args()

    # 날짜 범위 결정 (기본: period 매핑)
    periods = {
        'train': ('2020-01-01', '2024-12-31'),
        'test': ('2025-01-01', '2025-12-11'),
        'all': ('2020-01-01', '2025-12-11')
    }
    start, end = periods[args.period]
    if args.start_date:
        start = args.start_date
    if args.end_date:
        end = args.end_date

    if args.by_year:
        start_year = int(start[:4])
        end_year = int(end[:4])
        print("\n" + "=" * 80)
        print(f"📅 연도별 백테스트 요약: strategy={args.strategy}, timeframe={args.timeframe}")
        print(f"   range: {start} ~ {end}")
        print("=" * 80)

        results_by_year = []
        for year in range(start_year, end_year + 1):
            year_start = f"{year}-01-01"
            year_end = f"{year}-12-31"

            # clip to requested range
            if year == start_year:
                year_start = start
            if year == end_year:
                year_end = end

            strategy_key = args.strategy
            tf = args.timeframe
            if strategy_key == 'short_v1' and tf == 'day':
                tf = 'minute240'

            res = run_backtest(strategy_key, tf, year_start, year_end, verbose=False)
            results_by_year.append({
                'year': year,
                'return_pct': res.get('total_return', 0.0),
                'trades': res.get('total_trades', 0),
                'win_rate': res.get('win_rate', 0.0) * 100 if res.get('total_trades', 0) else 0.0,
                'mdd': res.get('mdd', 0.0),
                'sharpe': res.get('sharpe', 0.0),
                'alpha': res.get('alpha', 0.0),
            })

        print(f"{'YEAR':<6} {'RET%':>8} {'TRADES':>8} {'WIN%':>7} {'MDD%':>8} {'SHARPE':>8} {'ALPHA%P':>10}")
        print("-" * 80)
        for r in results_by_year:
            print(
                f"{r['year']:<6} {r['return_pct']:>8.2f} {r['trades']:>8} {r['win_rate']:>7.1f} "
                f"{r['mdd']:>8.2f} {r['sharpe']:>8.2f} {r['alpha']:>10.2f}"
            )
        print("=" * 80)
        raise SystemExit(0)

    if args.strategy == 'both' and args.period == 'all':
        run_full_analysis()
    else:
        if args.strategy in ['v35', 'both']:
            run_backtest('v35', args.timeframe, start, end)

        if args.strategy in ['short_v1', 'both']:
            tf = 'minute240' if args.timeframe == 'day' else args.timeframe
            run_backtest('short_v1', tf, start, end)

        if args.strategy == 'sideways_v1':
            run_backtest('sideways_v1', args.timeframe, start, end)

        if args.strategy == 'sideways_v2':
            run_backtest('sideways_v2', args.timeframe, start, end)

        if args.strategy == 'router_v1':
            run_backtest('router_v1', args.timeframe, start, end)

        if args.strategy == 'router_live':
            run_backtest('router_live', args.timeframe, start, end)
