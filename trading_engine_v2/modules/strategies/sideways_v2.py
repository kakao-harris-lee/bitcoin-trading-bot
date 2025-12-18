"""
Trading Engine V2 - SideWays_v2 Strategy

v-a-09 SidewaysEntryChecker를 기반으로 한 횡보장 전담 롱 전략.

핵심 차별점 (v-a-09):
- OBV 하락 추세 감지(필터)로 하락 방향성 구간 진입 거부

나머지 Entry/Exit 구조는 SideWays_v1과 동일(3종 진입, TP/SL/Max hold).
"""

from __future__ import annotations

import logging
from typing import Dict, Optional

import numpy as np
import pandas as pd

from trading_engine_v2.modules.base_strategy import BaseStrategy
from trading_engine_v2.core.config import Config
from trading_engine_v2.core.message_types import Exchange, Direction

logger = logging.getLogger(__name__)


class SideWaysV2Strategy(BaseStrategy):
    """횡보장 전담 전략 - SideWays_v2 (v-a-09)"""

    DEFAULT_CONFIG: Dict = {
        # Feature toggles
        "use_rsi_bb": True,
        "use_stoch": True,
        "use_volume_breakout": True,

        # Entry thresholds (v-a-09 config.json의 sideways 섹션 기반)
        "rsi_bb_oversold": 24,
        "rsi_bb_overbought": 72,
        "stoch_oversold": 20,
        "stoch_overbought": 80,
        "volume_breakout_mult": 1.6834605851235325,

        # Position sizing
        "position_size": 0.4,

        # Exit thresholds
        "take_profit_1": 0.011254856376113564,
        "take_profit_2": 0.033274603915100426,
        "take_profit_3": 0.05519108455392487,
        "stop_loss": -0.010789744612422282,
        "max_hold_bars": 20,
        "min_hold_bars_for_tp1": 5,

        # v-a-09 filter
        "obv_ma_window": 14,
        "obv_slope_lookback": 7,
        "obv_downtrend_threshold": -0.04,  # tuned: less negative = stricter filter

        # Shared
        "bb_position_entry_max": 0.2,
        "stoch_entry_buffer": 10,

        # Buffer
        "buffer_size": 300,
    }

    def __init__(
        self,
        config: Optional[Config] = None,
        strategy_config: Optional[Dict] = None,
    ):
        merged_config = {**self.DEFAULT_CONFIG, **(strategy_config or {})}

        super().__init__(
            strategy_name="sideways-v2",
            exchange=Exchange.UPBIT,
            direction=Direction.LONG,
            symbol="KRW-BTC",
            config=config,
            strategy_config=merged_config,
        )

        self.hold_bars = 0
        self.entry_method: Optional[str] = None
        self.partial_exits = 0

    def _min_buffer_size(self) -> int:
        return 30

    def add_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()

        # RSI
        delta = df["close"].diff()
        gain = delta.where(delta > 0, 0).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss.replace(0, np.nan)
        df["rsi"] = 100 - (100 / (1 + rs))

        # Bollinger Bands
        bb_middle = df["close"].rolling(window=20).mean()
        bb_std = df["close"].rolling(window=20).std()
        df["bb_middle"] = bb_middle
        df["bb_upper"] = bb_middle + 2 * bb_std
        df["bb_lower"] = bb_middle - 2 * bb_std
        bb_range = (df["bb_upper"] - df["bb_lower"]).replace(0, np.nan)
        df["bb_position"] = (df["close"] - df["bb_lower"]) / bb_range

        # Stochastic
        low_14 = df["low"].rolling(window=14).min()
        high_14 = df["high"].rolling(window=14).max()
        df["stoch_k"] = 100 * (df["close"] - low_14) / (high_14 - low_14).replace(0, np.nan)
        df["stoch_d"] = df["stoch_k"].rolling(window=3).mean()

        # Avg volume for breakout
        df["avg_volume_20"] = df["volume"].rolling(window=20).mean()

        # OBV and slope (v-a-09 filter)
        price_diff = df["close"].diff()
        direction = np.sign(price_diff).fillna(0)
        obv = (direction * df["volume"]).fillna(0).cumsum()
        df["obv"] = obv

        ma_window = int(self.strategy_config.get("obv_ma_window", 14))
        slope_lookback = int(self.strategy_config.get("obv_slope_lookback", 7))
        obv_ma = df["obv"].rolling(ma_window).mean()
        df["obv_ma"] = obv_ma
        denom = obv_ma.shift(slope_lookback).replace(0, np.nan).abs()
        df["obv_slope"] = (obv_ma - obv_ma.shift(slope_lookback)) / denom

        return df

    def generate_signal(self, df: pd.DataFrame, i: int) -> Optional[Dict]:
        if i < self._min_buffer_size():
            return None

        row = df.iloc[i]
        prev_row = df.iloc[i - 1] if i > 0 else None

        # Exit
        if self.in_position:
            self.hold_bars += 1
            exit_signal = self._check_exit(row, prev_row)
            if exit_signal:
                fraction = float(exit_signal.get("fraction", 1.0))
                if fraction >= 1.0:
                    self.clear_position()
                    self.hold_bars = 0
                    self.entry_method = None
                    self.partial_exits = 0
                else:
                    self.partial_exits += 1
                return exit_signal

        # Entry
        if not self.in_position:
            if self._is_filtered_out(row):
                return None

            entry_signal = self._check_entry(row, prev_row)
            if entry_signal:
                self.set_position(float(row["close"]), entry_signal.get("reason", ""))
                self.hold_bars = 0
                self.entry_method = entry_signal.get("strategy")
                self.partial_exits = 0
                return entry_signal

        return None

    def _is_filtered_out(self, row: pd.Series) -> bool:
        """v-a-09: OBV 하락 추세 감지 시 진입 거부"""
        obv_slope = row.get("obv_slope", np.nan)
        threshold = float(self.strategy_config.get("obv_downtrend_threshold", -0.05))
        if pd.notna(obv_slope) and obv_slope < threshold:
            return True
        return False

    def _check_entry(self, row: pd.Series, prev_row: Optional[pd.Series]) -> Optional[Dict]:
        pos_size = float(self.strategy_config.get("position_size", 0.4))

        # 1) RSI + BB
        if self.strategy_config.get("use_rsi_bb", True):
            rsi = row.get("rsi", 50)
            bb_pos = row.get("bb_position", np.nan)
            if (
                pd.notna(bb_pos)
                and rsi < float(self.strategy_config.get("rsi_bb_oversold", 24))
                and bb_pos < float(self.strategy_config.get("bb_position_entry_max", 0.2))
            ):
                return {
                    "action": "buy",
                    "fraction": pos_size,
                    "reason": f"SIDEWAYS_V2_RSI_BB (RSI={rsi:.1f}, BB={bb_pos:.2f})",
                    "confidence": 0.8,
                    "strategy": "rsi_bb",
                }

        # 2) Stochastic (GC)
        if self.strategy_config.get("use_stoch", True) and prev_row is not None:
            stoch_k = row.get("stoch_k", 50)
            stoch_d = row.get("stoch_d", 50)
            prev_k = prev_row.get("stoch_k", 50)
            prev_d = prev_row.get("stoch_d", 50)
            golden_cross = (prev_k <= prev_d) and (stoch_k > stoch_d)
            oversold = float(self.strategy_config.get("stoch_oversold", 20))
            buffer = float(self.strategy_config.get("stoch_entry_buffer", 10))
            if golden_cross and stoch_k < oversold + buffer:
                return {
                    "action": "buy",
                    "fraction": pos_size,
                    "reason": f"SIDEWAYS_V2_STOCH_GC (K={stoch_k:.1f}, D={stoch_d:.1f})",
                    "confidence": 0.75,
                    "strategy": "stoch",
                }

        # 3) Volume Breakout
        if self.strategy_config.get("use_volume_breakout", True):
            volume = row.get("volume", 0)
            avg_vol = row.get("avg_volume_20", np.nan)
            mult = float(self.strategy_config.get("volume_breakout_mult", 1.68))
            if pd.notna(avg_vol) and avg_vol > 0 and volume >= avg_vol * mult:
                return {
                    "action": "buy",
                    "fraction": pos_size,
                    "reason": f"SIDEWAYS_V2_VOLUME_BREAKOUT (Vol={volume/avg_vol:.1f}x)",
                    "confidence": 0.7,
                    "strategy": "volume_breakout",
                }

        return None

    def _check_exit(self, row: pd.Series, prev_row: Optional[pd.Series]) -> Optional[Dict]:
        current_price = float(row["close"])
        profit = (current_price - self.entry_price) / self.entry_price if self.entry_price > 0 else 0.0

        tp1 = float(self.strategy_config.get("take_profit_1", 0.011))
        tp2 = float(self.strategy_config.get("take_profit_2", 0.033))
        tp3 = float(self.strategy_config.get("take_profit_3", 0.055))
        stop_loss = float(self.strategy_config.get("stop_loss", -0.011))
        max_hold = int(self.strategy_config.get("max_hold_bars", 20))
        min_hold_tp1 = int(self.strategy_config.get("min_hold_bars_for_tp1", 5))

        if self.partial_exits <= 0 and profit >= tp1 and self.hold_bars >= min_hold_tp1:
            return {
                "action": "sell",
                "fraction": 0.3,
                "reason": f"SIDEWAYS_V2_TP1_PARTIAL ({profit:.2%})",
                "confidence": 0.8,
                "metadata": {"entry_method": self.entry_method},
            }

        if self.partial_exits <= 1 and profit >= tp2:
            return {
                "action": "sell",
                "fraction": 0.5,
                "reason": f"SIDEWAYS_V2_TP2_PARTIAL ({profit:.2%})",
                "confidence": 0.85,
                "metadata": {"entry_method": self.entry_method},
            }

        if profit >= tp3:
            return {
                "action": "sell",
                "fraction": 1.0,
                "reason": f"SIDEWAYS_V2_TP3 ({profit:.2%})",
                "confidence": 0.9,
                "metadata": {"entry_method": self.entry_method},
            }

        if profit <= stop_loss:
            return {
                "action": "sell",
                "fraction": 1.0,
                "reason": f"SIDEWAYS_V2_STOP_LOSS ({profit:.2%})",
                "confidence": 0.95,
                "metadata": {"entry_method": self.entry_method},
            }

        if self.hold_bars >= max_hold:
            return {
                "action": "sell",
                "fraction": 1.0,
                "reason": f"SIDEWAYS_V2_MAX_HOLD ({profit:.2%}, {max_hold} bars)",
                "confidence": 0.7,
                "metadata": {"entry_method": self.entry_method},
            }

        return None
