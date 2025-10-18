#!/usr/bin/env python3
"""
Trading Environment for Reinforcement Learning (Gymnasium)

v10 RL Hybrid Strategy Environment
- State: Price, EMA, MACD, RSI, ADX, Position Info
- Action: buy(fraction), sell(fraction), hold
- Reward: Profit-based + Risk Penalty
"""

import sys
sys.path.append('../..')

import numpy as np
import pandas as pd
import gymnasium as gym
from gymnasium import spaces
from typing import Dict, Tuple, Optional


class TradingEnv(gym.Env):
    """
    Cryptocurrency Trading Environment

    Observation Space (14 features):
        - close_norm: 현재가 정규화 (0~1)
        - ema12_norm: EMA12 정규화
        - ema26_norm: EMA26 정규화
        - macd_norm: MACD 정규화
        - macd_signal_norm: MACD Signal 정규화
        - rsi_norm: RSI (0~100 → 0~1)
        - adx_norm: ADX (0~100 → 0~1)
        - momentum_norm: 30일 Momentum 정규화 (-1~1)
        - volatility_norm: 30일 변동성 정규화 (0~1)
        - position: 포지션 보유 여부 (0 or 1)
        - position_fraction: 현재 보유 비율 (0~1)
        - profit_pct: 현재 수익률 (-1~1)
        - holding_days: 보유 기간 (일수, 0~30)
        - cash_fraction: 현금 비율 (0~1)

    Action Space (1 continuous):
        - action: -1 (sell all) ~ 0 (hold) ~ +1 (buy all)
        - -1.0: 100% 매도
        - -0.5: 50% 매도
        - 0.0: 홀드
        - +0.5: 50% 매수
        - +1.0: 100% 매수

    Reward:
        - 수익 증가: +profit_pct
        - MDD 증가: -drawdown_pct
        - 거래 수수료: -0.05%
        - 보유 기간 페널티: -0.01% per day (30일 이상)
        - 승리 보너스: +1.0 (10% 이상 수익 청산)
    """

    metadata = {'render.modes': ['human']}

    def __init__(
        self,
        df: pd.DataFrame,
        initial_capital: float = 10_000_000,
        fee_rate: float = 0.0005,
        slippage: float = 0.0002,
        max_holding_days: int = 30
    ):
        super(TradingEnv, self).__init__()

        self.df = df.reset_index(drop=True)
        self.initial_capital = initial_capital
        self.fee_rate = fee_rate
        self.slippage = slippage
        self.max_holding_days = max_holding_days

        # Observation: 14 features (continuous)
        self.observation_space = spaces.Box(
            low=0.0,
            high=1.0,
            shape=(14,),
            dtype=np.float32
        )

        # Action: 1 continuous value [-1, 1]
        self.action_space = spaces.Box(
            low=-1.0,
            high=1.0,
            shape=(1,),
            dtype=np.float32
        )

        # State variables
        self.current_step = 0
        self.cash = initial_capital
        self.btc_balance = 0.0
        self.position_entry_price = 0.0
        self.position_entry_step = 0
        self.highest_equity = initial_capital
        self.total_trades = 0
        self.winning_trades = 0

        # Normalization params (calculated from df)
        self._calculate_normalization_params()

    def _calculate_normalization_params(self):
        """정규화 파라미터 계산"""
        self.price_min = self.df['close'].min()
        self.price_max = self.df['close'].max()

        if 'ema12' in self.df.columns:
            self.ema_min = min(self.df['ema12'].min(), self.df['ema26'].min())
            self.ema_max = max(self.df['ema12'].max(), self.df['ema26'].max())
        else:
            self.ema_min, self.ema_max = self.price_min, self.price_max

        if 'macd' in self.df.columns:
            self.macd_min = min(self.df['macd'].min(), self.df['macd_signal'].min())
            self.macd_max = max(self.df['macd'].max(), self.df['macd_signal'].max())
        else:
            self.macd_min, self.macd_max = -1.0, 1.0

        if 'momentum' in self.df.columns:
            self.momentum_min = self.df['momentum'].min()
            self.momentum_max = self.df['momentum'].max()
        else:
            self.momentum_min, self.momentum_max = -0.5, 0.5

        if 'volatility' in self.df.columns:
            self.volatility_min = self.df['volatility'].min()
            self.volatility_max = self.df['volatility'].max()
        else:
            self.volatility_min, self.volatility_max = 0.0, 0.1

    def reset(self, seed=None, options=None) -> Tuple[np.ndarray, Dict]:
        """환경 초기화"""
        super().reset(seed=seed)

        self.current_step = 30  # 최소 30일 지표 확보
        self.cash = self.initial_capital
        self.btc_balance = 0.0
        self.position_entry_price = 0.0
        self.position_entry_step = 0
        self.highest_equity = self.initial_capital
        self.total_trades = 0
        self.winning_trades = 0

        obs = self._get_observation()
        info = {}

        return obs, info

    def _get_observation(self) -> np.ndarray:
        """현재 관측값 반환"""
        row = self.df.iloc[self.current_step]

        # Price features (normalized)
        close_norm = (row['close'] - self.price_min) / (self.price_max - self.price_min + 1e-8)

        ema12_norm = (row.get('ema12', row['close']) - self.ema_min) / (self.ema_max - self.ema_min + 1e-8)
        ema26_norm = (row.get('ema26', row['close']) - self.ema_min) / (self.ema_max - self.ema_min + 1e-8)

        macd_norm = (row.get('macd', 0) - self.macd_min) / (self.macd_max - self.macd_min + 1e-8)
        macd_signal_norm = (row.get('macd_signal', 0) - self.macd_min) / (self.macd_max - self.macd_min + 1e-8)

        rsi_norm = row.get('rsi', 50) / 100.0
        adx_norm = row.get('adx', 25) / 100.0

        momentum_norm = (row.get('momentum', 0) - self.momentum_min) / (self.momentum_max - self.momentum_min + 1e-8)
        volatility_norm = (row.get('volatility', 0.02) - self.volatility_min) / (self.volatility_max - self.volatility_min + 1e-8)

        # Position features
        position = 1.0 if self.btc_balance > 0 else 0.0
        position_fraction = (self.btc_balance * row['close']) / (self.cash + self.btc_balance * row['close'])

        # Profit
        if self.btc_balance > 0 and self.position_entry_price > 0:
            profit_pct = (row['close'] - self.position_entry_price) / self.position_entry_price
            profit_pct = np.clip(profit_pct, -1.0, 1.0)
        else:
            profit_pct = 0.0

        # Holding days
        holding_days = (self.current_step - self.position_entry_step) if self.btc_balance > 0 else 0
        holding_days_norm = min(holding_days / self.max_holding_days, 1.0)

        # Cash fraction
        total_value = self.cash + self.btc_balance * row['close']
        cash_fraction = self.cash / (total_value + 1e-8)

        obs = np.array([
            close_norm,
            ema12_norm,
            ema26_norm,
            macd_norm,
            macd_signal_norm,
            rsi_norm,
            adx_norm,
            momentum_norm,
            volatility_norm,
            position,
            position_fraction,
            (profit_pct + 1.0) / 2.0,  # -1~1 → 0~1
            holding_days_norm,
            cash_fraction
        ], dtype=np.float32)

        return obs

    def step(self, action: np.ndarray) -> Tuple[np.ndarray, float, bool, bool, Dict]:
        """
        환경 진행

        Args:
            action: [-1, 1] 범위의 연속 값
                -1: 100% 매도
                0: 홀드
                +1: 100% 매수

        Returns:
            observation, reward, terminated, truncated, info
        """
        action_value = float(action[0])
        row = self.df.iloc[self.current_step]
        current_price = row['close']

        reward = 0.0
        trade_executed = False

        # Current equity
        current_equity = self.cash + self.btc_balance * current_price

        # Action 실행
        if action_value > 0.1:  # Buy
            buy_fraction = action_value  # 0.1~1.0
            buy_amount = self.cash * buy_fraction

            if buy_amount > 0:
                # Slippage + Fee
                effective_price = current_price * (1 + self.slippage)
                btc_bought = buy_amount / effective_price
                fee = buy_amount * self.fee_rate

                self.btc_balance += btc_bought
                self.cash -= (buy_amount + fee)

                # Entry price update (weighted average)
                if self.position_entry_price == 0:
                    self.position_entry_price = effective_price
                    self.position_entry_step = self.current_step
                else:
                    total_btc = self.btc_balance
                    self.position_entry_price = (self.position_entry_price * (total_btc - btc_bought) + effective_price * btc_bought) / total_btc

                trade_executed = True
                reward -= self.fee_rate  # 수수료 페널티

        elif action_value < -0.1:  # Sell
            sell_fraction = abs(action_value)  # 0.1~1.0
            btc_to_sell = self.btc_balance * sell_fraction

            if btc_to_sell > 0:
                # Slippage + Fee
                effective_price = current_price * (1 - self.slippage)
                sell_amount = btc_to_sell * effective_price
                fee = sell_amount * self.fee_rate

                # Profit calculation
                if self.position_entry_price > 0:
                    profit_pct = (effective_price - self.position_entry_price) / self.position_entry_price

                    # Reward for profit
                    reward += profit_pct

                    # Winning trade bonus
                    if profit_pct > 0.10:
                        reward += 1.0

                    # Update stats
                    self.total_trades += 1
                    if profit_pct > 0:
                        self.winning_trades += 1

                self.cash += (sell_amount - fee)
                self.btc_balance -= btc_to_sell

                # Reset position if fully sold
                if self.btc_balance < 1e-8:
                    self.btc_balance = 0.0
                    self.position_entry_price = 0.0
                    self.position_entry_step = 0

                trade_executed = True
                reward -= self.fee_rate  # 수수료 페널티

        # Holding penalty (30일 이상)
        if self.btc_balance > 0:
            holding_days = self.current_step - self.position_entry_step
            if holding_days > self.max_holding_days:
                reward -= 0.01 * (holding_days - self.max_holding_days)

        # MDD penalty
        new_equity = self.cash + self.btc_balance * current_price
        if new_equity > self.highest_equity:
            self.highest_equity = new_equity
        else:
            drawdown = (self.highest_equity - new_equity) / self.highest_equity
            reward -= drawdown

        # Next step
        self.current_step += 1
        terminated = (self.current_step >= len(self.df) - 1)
        truncated = False

        obs = self._get_observation() if not terminated else np.zeros(14, dtype=np.float32)

        info = {
            'equity': new_equity,
            'position': self.btc_balance,
            'cash': self.cash,
            'total_trades': self.total_trades,
            'win_rate': self.winning_trades / max(self.total_trades, 1)
        }

        return obs, reward, terminated, truncated, info

    def render(self, mode='human'):
        """렌더링 (옵션)"""
        row = self.df.iloc[self.current_step]
        current_price = row['close']
        equity = self.cash + self.btc_balance * current_price

        print(f"Step {self.current_step}: Price {current_price:,.0f}, Equity {equity:,.0f}, "
              f"BTC {self.btc_balance:.6f}, Cash {self.cash:,.0f}")


if __name__ == '__main__':
    """환경 테스트"""
    from core.data_loader import DataLoader
    from core.market_analyzer import MarketAnalyzer

    print("=" * 80)
    print("Trading Environment Test")
    print("=" * 80)

    # 데이터 로드
    print("\n[1/3] 데이터 로드...")
    with DataLoader('../../upbit_bitcoin.db') as loader:
        df = loader.load_timeframe('day', start_date='2024-01-01', end_date='2024-12-30')

    # 지표 추가
    print("\n[2/3] 지표 추가...")
    df = MarketAnalyzer.add_indicators(df, indicators=['ema', 'macd', 'rsi', 'adx'])
    df = df.rename(columns={'ema_12': 'ema12', 'ema_26': 'ema26'})

    # Momentum, Volatility 추가
    df['momentum'] = df['close'].pct_change(30)
    df['volatility'] = df['close'].pct_change().rolling(window=30).std()

    print(f"  ✅ {len(df)}개 캔들, {df.columns.tolist()}")

    # 환경 생성
    print("\n[3/3] 환경 테스트...")
    env = TradingEnv(df)

    print(f"\n  Observation Space: {env.observation_space}")
    print(f"  Action Space: {env.action_space}")

    # Reset
    obs, info = env.reset()
    print(f"\n  Initial Observation Shape: {obs.shape}")
    print(f"  Initial Observation: {obs}")

    # Random action test
    print("\n  Random Actions Test (10 steps):")
    for i in range(10):
        action = env.action_space.sample()
        obs, reward, terminated, truncated, info = env.step(action)

        print(f"    Step {i+1}: Action {action[0]:+.2f}, Reward {reward:+.4f}, "
              f"Equity {info['equity']:,.0f}, Trades {info['total_trades']}")

        if terminated or truncated:
            break

    print("\n" + "=" * 80)
    print("✅ 환경 테스트 완료")
    print("=" * 80)
