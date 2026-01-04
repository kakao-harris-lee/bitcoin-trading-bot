"""
Trading Engine V2 - V35 Long Strategy
Upbit Long 전략 (v35_optimized 이식)
"""

import logging
from typing import Optional, Dict, Any
import pandas as pd
import numpy as np

from .base import BaseStrategy
from ..indicators import add_all_indicators
from ..core.config import Config
from core.types import Exchange, Direction, MarketState

logger = logging.getLogger(__name__)


# ========== 시장 상태 분류기 (v34 기반) ==========

class MarketClassifier:
    """시장 상태 분류기 (7레벨)

    Thresholds aligned with RegimeRouter (selected_candidate.json):
    - Router mfi_bull=54, mfi_bear=49, adx_strong=25, adx_trend=18
    """

    def __init__(self, config: Dict):
        self.config = config

        # MFI 임계값 (aligned with RegimeRouter)
        self.mfi_bull_strong = config.get('mfi_bull_strong', 54)
        self.mfi_bull_moderate = config.get('mfi_bull_moderate', 54)
        self.mfi_sideways_up = config.get('mfi_sideways_up', 49)
        self.mfi_bear_moderate = config.get('mfi_bear_moderate', 41)
        self.mfi_bear_strong = config.get('mfi_bear_strong', 34)

        # ADX 임계값 (aligned with RegimeRouter)
        self.adx_strong_trend = config.get('adx_strong_trend', 25)
        self.adx_moderate_trend = config.get('adx_moderate_trend', 18)

    def classify(self, row: pd.Series, prev_row: Optional[pd.Series] = None) -> str:
        """
        시장 상태 분류

        Returns:
            BULL_STRONG, BULL_MODERATE, SIDEWAYS_UP, SIDEWAYS_FLAT,
            SIDEWAYS_DOWN, BEAR_MODERATE, BEAR_STRONG
        """
        mfi = row.get('mfi', 50)
        adx = row.get('adx', 20)

        # ADX로 추세 강도 판단
        is_strong_trend = adx >= self.adx_strong_trend
        is_moderate_trend = adx >= self.adx_moderate_trend

        # MFI로 방향 판단
        if mfi >= self.mfi_bull_strong and is_strong_trend:
            return 'BULL_STRONG'
        elif mfi >= self.mfi_bull_moderate and is_moderate_trend:
            return 'BULL_MODERATE'
        elif mfi >= self.mfi_sideways_up:
            return 'SIDEWAYS_UP'
        elif mfi >= self.mfi_bear_moderate:
            return 'SIDEWAYS_FLAT'
        elif mfi >= self.mfi_bear_strong:
            return 'SIDEWAYS_DOWN'
        elif is_strong_trend:
            return 'BEAR_STRONG'
        else:
            return 'BEAR_MODERATE'


# ========== 동적 Exit 관리자 ==========

class DynamicExitManager:
    """동적 익절/손절 관리"""

    def __init__(self, config: Dict):
        self.config = config
        self.entry_price = 0.0
        self.market_state = 'UNKNOWN'
        self.partial_exits = 0

    def set_entry(self, price: float, market_state: str):
        """진입 설정"""
        self.entry_price = price
        self.market_state = market_state
        self.partial_exits = 0

    def reset(self):
        """리셋"""
        self.entry_price = 0.0
        self.market_state = 'UNKNOWN'
        self.partial_exits = 0

    def check_exit(
        self,
        current_price: float,
        current_market_state: str,
        macd: float = 0,
        macd_signal: float = 0
    ) -> Optional[Dict]:
        """
        Exit 조건 확인

        Returns:
            Exit 신호 또는 None
        """
        if self.entry_price <= 0:
            return None

        pnl_pct = (current_price - self.entry_price) / self.entry_price

        # 손절
        stop_loss = self.config.get('stop_loss', -0.015)
        if pnl_pct <= stop_loss:
            return {
                'action': 'sell',
                'fraction': 1.0,
                'reason': f'STOP_LOSS_{pnl_pct*100:.2f}%'
            }

        # 시장 상태별 익절
        tp_levels = self._get_tp_levels()

        # 분할 익절
        if self.partial_exits < 3:
            for level, (tp_pct, fraction) in enumerate(tp_levels):
                if level == self.partial_exits and pnl_pct >= tp_pct:
                    self.partial_exits += 1
                    return {
                        'action': 'sell',
                        'fraction': fraction,
                        'reason': f'TP_LEVEL_{level+1}_{pnl_pct*100:.2f}%'
                    }

        # MACD 데드크로스
        if macd < macd_signal and pnl_pct > 0:
            return {
                'action': 'sell',
                'fraction': 1.0,
                'reason': f'MACD_DEAD_CROSS_{pnl_pct*100:.2f}%'
            }

        return None

    def _get_tp_levels(self):
        """시장 상태별 TP 레벨 반환"""
        if self.market_state in ['BULL_STRONG']:
            return [
                (self.config.get('tp_bull_strong_1', 0.05), 0.4),
                (self.config.get('tp_bull_strong_2', 0.10), 0.3),
                (self.config.get('tp_bull_strong_3', 0.20), 0.3),
            ]
        elif self.market_state in ['BULL_MODERATE']:
            return [
                (self.config.get('tp_bull_moderate_1', 0.03), 0.4),
                (self.config.get('tp_bull_moderate_2', 0.07), 0.3),
                (self.config.get('tp_bull_moderate_3', 0.12), 0.3),
            ]
        else:  # SIDEWAYS
            return [
                (self.config.get('tp_sideways_1', 0.02), 0.5),
                (self.config.get('tp_sideways_2', 0.04), 0.3),
                (self.config.get('tp_sideways_3', 0.06), 0.2),
            ]


# ========== V35 Long Strategy ==========

class V35LongStrategy(BaseStrategy):
    """
    V35 Long Strategy (Upbit)

    v35_optimized 전략을 이벤트 기반으로 이식
    - 시장 상태별 Entry/Exit
    - 동적 익절 시스템
    - SIDEWAYS 강화 전략
    """

    # 기본 설정 (aligned with RegimeRouter thresholds from selected_candidate.json)
    DEFAULT_CONFIG = {
        # 시장 분류 - aligned with router: mfi_bull=54, mfi_bear=49, adx_strong=25, adx_trend=18
        'mfi_bull_strong': 54,
        'mfi_bull_moderate': 54,
        'mfi_sideways_up': 49,
        'mfi_bear_moderate': 41,
        'mfi_bear_strong': 34,
        'adx_strong_trend': 25,
        'adx_moderate_trend': 18,

        # Entry
        'momentum_rsi_bull_strong': 52,
        'momentum_rsi_bull_moderate': 55,
        'breakout_threshold': 0.005,
        'breakout_volume_mult': 1.3,
        'range_support_zone': 0.15,
        'range_rsi_oversold': 40,

        # Exit
        'stop_loss': -0.015,
        'tp_bull_strong_1': 0.05,
        'tp_bull_strong_2': 0.10,
        'tp_bull_strong_3': 0.20,
        'tp_bull_moderate_1': 0.03,
        'tp_bull_moderate_2': 0.07,
        'tp_bull_moderate_3': 0.12,
        'tp_sideways_1': 0.02,
        'tp_sideways_2': 0.04,
        'tp_sideways_3': 0.06,

        # Position
        'position_size': 0.5,
        'buffer_size': 300,
    }

    def __init__(
        self,
        config: Optional[Config] = None,
        strategy_config: Optional[Dict] = None,
    ):
        # 설정 병합
        merged_config = {**self.DEFAULT_CONFIG, **(strategy_config or {})}

        super().__init__(
            strategy_name="v35-long",
            exchange=Exchange.UPBIT,
            direction=Direction.LONG,
            symbol="KRW-BTC",
            config=config,
            strategy_config=merged_config,
        )

        # 컴포넌트 초기화
        self.classifier = MarketClassifier(merged_config)
        self.exit_manager = DynamicExitManager(merged_config)

        # 진입 전략
        self.entry_strategy = ""
        self.entry_market_state = ""

    def _min_buffer_size(self) -> int:
        """최소 30개 캔들 필요"""
        return 30

    def add_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """기술적 지표 추가 (using shared indicator library)"""
        # Use shared indicator library
        if len(df) >= 200:
            add_all_indicators(df)
        else:
            # Fallback for small DataFrames (library requires 200+ rows)
            self._add_indicators_legacy(df)
        return df

    def _add_indicators_legacy(self, df: pd.DataFrame) -> pd.DataFrame:
        """Legacy indicator calculation for small DataFrames (<200 rows)"""
        # RSI
        delta = df['close'].diff()
        gain = delta.where(delta > 0, 0).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss.replace(0, np.nan)
        df['rsi'] = 100 - (100 / (1 + rs))

        # MACD
        ema12 = df['close'].ewm(span=12, adjust=False).mean()
        ema26 = df['close'].ewm(span=26, adjust=False).mean()
        df['macd'] = ema12 - ema26
        df['macd_signal'] = df['macd'].ewm(span=9, adjust=False).mean()

        # MFI
        typical_price = (df['high'] + df['low'] + df['close']) / 3
        raw_money_flow = typical_price * df['volume']
        positive_flow = raw_money_flow.where(typical_price > typical_price.shift(1), 0)
        negative_flow = raw_money_flow.where(typical_price < typical_price.shift(1), 0)
        positive_mf = positive_flow.rolling(window=14).sum()
        negative_mf = negative_flow.rolling(window=14).sum()
        mfi_ratio = positive_mf / negative_mf.replace(0, np.nan)
        df['mfi'] = 100 - (100 / (1 + mfi_ratio))

        # ADX
        df['adx'] = self._calculate_adx(df)

        # Bollinger Bands
        df['bb_middle'] = df['close'].rolling(window=20).mean()
        bb_std = df['close'].rolling(window=20).std()
        df['bb_upper'] = df['bb_middle'] + 2 * bb_std
        df['bb_lower'] = df['bb_middle'] - 2 * bb_std

        # Stochastic
        low_14 = df['low'].rolling(window=14).min()
        high_14 = df['high'].rolling(window=14).max()
        df['stoch_k'] = 100 * (df['close'] - low_14) / (high_14 - low_14).replace(0, np.nan)
        df['stoch_d'] = df['stoch_k'].rolling(window=3).mean()

        return df

    def _calculate_adx(self, df: pd.DataFrame, period: int = 14) -> pd.Series:
        """ADX 계산"""
        high = df['high']
        low = df['low']
        close = df['close']

        tr1 = high - low
        tr2 = abs(high - close.shift(1))
        tr3 = abs(low - close.shift(1))
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

        up_move = high - high.shift(1)
        down_move = low.shift(1) - low

        plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0)
        minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0)

        plus_dm = pd.Series(plus_dm, index=df.index)
        minus_dm = pd.Series(minus_dm, index=df.index)

        atr = tr.ewm(alpha=1/period, adjust=False).mean()
        smooth_plus = plus_dm.ewm(alpha=1/period, adjust=False).mean()
        smooth_minus = minus_dm.ewm(alpha=1/period, adjust=False).mean()

        plus_di = 100 * smooth_plus / atr.replace(0, np.nan)
        minus_di = 100 * smooth_minus / atr.replace(0, np.nan)

        dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di).replace(0, np.nan)
        adx = dx.ewm(alpha=1/period, adjust=False).mean()

        return adx

    def generate_signal(self, df: pd.DataFrame, i: int) -> Optional[Dict]:
        """
        신호 생성

        Returns:
            {'action': 'buy'/'sell', 'fraction': float, 'reason': str} or None
        """
        row = df.iloc[i]
        prev_row = df.iloc[i-1] if i > 0 else None

        # 시장 상태 분류
        market_state = self.classifier.classify(row, prev_row)

        # BEAR_PROTECTION disabled - analysis showed it was cutting profitable trades short
        # (278 trades forced exit at 14% win rate, -87% total loss)
        # Trades perform better when allowed to run to TP or MACD exit
        # if self.in_position and market_state in ['BEAR_MODERATE', 'BEAR_STRONG']:
        #     if self.entry_strategy != 'conservative':
        #         self.clear_position()
        #         self.exit_manager.reset()
        #         return {
        #             'action': 'sell',
        #             'fraction': 1.0,
        #             'reason': f'BEAR_PROTECTION_{market_state}',
        #             'confidence': 0.95,
        #             'metadata': {'market_state': market_state}
        #         }

        # 포지션 있을 때: Exit 조건
        if self.in_position:
            exit_signal = self.exit_manager.check_exit(
                current_price=row['close'],
                current_market_state=market_state,
                macd=row.get('macd', 0),
                macd_signal=row.get('macd_signal', 0)
            )

            if exit_signal:
                self.clear_position()
                self.exit_manager.reset()
                exit_signal['metadata'] = {'market_state': market_state}
                return exit_signal

        # 포지션 없을 때: Entry 조건
        else:
            entry_signal = self._check_entry(df, i, market_state, prev_row)
            if entry_signal:
                self.set_position(row['close'], entry_signal['reason'])
                self.entry_market_state = market_state
                self.entry_strategy = entry_signal.get('strategy', 'unknown')
                self.exit_manager.set_entry(row['close'], market_state)

                entry_signal['metadata'] = {
                    'market_state': market_state,
                    'rsi': row.get('rsi', 0),
                    'adx': row.get('adx', 0),
                }
                return entry_signal

        return None

    def _check_entry(
        self,
        df: pd.DataFrame,
        i: int,
        market_state: str,
        prev_row: Optional[pd.Series]
    ) -> Optional[Dict]:
        """Entry 조건 확인

        Single Source of Truth: V35 generates signals for ALL market states.
        RegimeRouter controls whether V35 runs at all.
        Internal classification only affects position sizing and exits.
        """
        row = df.iloc[i]

        # BULL_STRONG: Aggressive momentum
        if market_state == 'BULL_STRONG':
            return self._momentum_entry(row, aggressive=True)

        # BULL_MODERATE: Moderate momentum
        elif market_state == 'BULL_MODERATE':
            return self._momentum_entry(row, aggressive=False)

        # SIDEWAYS_UP: Breakout
        elif market_state == 'SIDEWAYS_UP':
            return self._breakout_entry(df, i)

        # SIDEWAYS_FLAT/SIDEWAYS_DOWN: Conservative range
        elif market_state in ['SIDEWAYS_FLAT', 'SIDEWAYS_DOWN']:
            return self._range_entry(df, i)

        # BEAR states: Very conservative range entry (if conditions met)
        # Note: RegimeRouter typically blocks V35 in BEAR, this is a fallback
        elif market_state in ['BEAR_MODERATE', 'BEAR_STRONG']:
            return self._conservative_entry(df, i)

        return None

    def _momentum_entry(self, row: pd.Series, aggressive: bool) -> Optional[Dict]:
        """Momentum Entry"""
        macd = row.get('macd', 0)
        macd_signal = row.get('macd_signal', 0)
        rsi = row.get('rsi', 50)

        threshold = (
            self.strategy_config['momentum_rsi_bull_strong']
            if aggressive else
            self.strategy_config['momentum_rsi_bull_moderate']
        )

        if macd > macd_signal and rsi > threshold:
            return {
                'action': 'buy',
                'fraction': self.strategy_config['position_size'],
                'reason': f'MOMENTUM_{"STRONG" if aggressive else "MODERATE"}',
                'confidence': 0.85 if aggressive else 0.75,
                'strategy': 'momentum',
            }

        return None

    def _breakout_entry(self, df: pd.DataFrame, i: int) -> Optional[Dict]:
        """Breakout Entry"""
        if i < 20:
            return None

        row = df.iloc[i]
        prev_20 = df.iloc[i-20:i]

        resistance = prev_20['high'].max()
        threshold = self.strategy_config['breakout_threshold']

        if row['close'] > resistance * (1 + threshold):
            avg_volume = prev_20['volume'].mean()
            volume_mult = self.strategy_config['breakout_volume_mult']

            if row['volume'] > avg_volume * volume_mult:
                return {
                    'action': 'buy',
                    'fraction': self.strategy_config['position_size'],
                    'reason': 'BREAKOUT_SIDEWAYS_UP',
                    'confidence': 0.7,
                    'strategy': 'breakout',
                }

        return None

    def _range_entry(self, df: pd.DataFrame, i: int) -> Optional[Dict]:
        """Range Entry"""
        if i < 20:
            return None

        row = df.iloc[i]
        prev_20 = df.iloc[i-20:i]

        support = prev_20['low'].min()
        resistance = prev_20['high'].max()
        range_height = resistance - support
        support_zone = self.strategy_config['range_support_zone']

        if row['close'] < support + range_height * support_zone:
            rsi_threshold = self.strategy_config['range_rsi_oversold']
            if row.get('rsi', 50) < rsi_threshold:
                return {
                    'action': 'buy',
                    'fraction': self.strategy_config['position_size'],
                    'reason': 'RANGE_SUPPORT',
                    'confidence': 0.65,
                    'strategy': 'range',
                }

        return None

    def _conservative_entry(self, df: pd.DataFrame, i: int) -> Optional[Dict]:
        """Conservative Entry for BEAR states.

        Very strict conditions - only enter on extreme oversold with support.
        Uses smaller position size for risk management.
        """
        if i < 20:
            return None

        row = df.iloc[i]
        prev_20 = df.iloc[i-20:i]

        rsi = row.get('rsi', 50)
        stoch_k = row.get('stoch_k', 50)

        # Very strict oversold conditions
        if rsi > 30:  # RSI must be < 30 (very oversold)
            return None

        if stoch_k > 20:  # Stochastic must be < 20
            return None

        # Must be near support
        support = prev_20['low'].min()
        resistance = prev_20['high'].max()
        range_height = resistance - support

        if range_height == 0:
            return None

        # Price must be in bottom 10% of range
        if row['close'] > support + range_height * 0.10:
            return None

        # All conditions met - conservative entry
        return {
            'action': 'buy',
            'fraction': self.strategy_config['position_size'] * 0.5,  # Half size
            'reason': 'CONSERVATIVE_BEAR_ENTRY',
            'confidence': 0.55,
            'strategy': 'conservative',
        }
