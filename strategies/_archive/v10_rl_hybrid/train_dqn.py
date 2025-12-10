#!/usr/bin/env python3
"""
DQN Agent Training Script

Conservative strategy:
- Focus on loss avoidance
- Lower position sizing
- Quick stop-loss
"""

import sys
sys.path.append('../..')

import json
import numpy as np
import pandas as pd
from datetime import datetime

from stable_baselines3 import DQN
from stable_baselines3.common.callbacks import CheckpointCallback, EvalCallback
from stable_baselines3.common.vec_env import DummyVecEnv
from stable_baselines3.common.monitor import Monitor

from core.data_loader import DataLoader
from core.market_analyzer import MarketAnalyzer
from trading_env import TradingEnv


def prepare_data(start_date='2018-09-04', end_date='2023-12-31'):
    """데이터 준비"""
    print(f"\n데이터 로드: {start_date} ~ {end_date}")

    with DataLoader('../../upbit_bitcoin.db') as loader:
        df = loader.load_timeframe('day', start_date=start_date, end_date=end_date)

    print(f"  {len(df)}개 캔들 로드")

    # 지표 추가
    print("\n지표 추가...")
    df = MarketAnalyzer.add_indicators(df, indicators=['ema', 'macd', 'rsi', 'adx'])
    df = df.rename(columns={'ema_12': 'ema12', 'ema_26': 'ema26'})

    # Momentum, Volatility
    df['momentum'] = df['close'].pct_change(30)
    df['volatility'] = df['close'].pct_change().rolling(window=30).std()

    # NaN 제거
    df = df.dropna().reset_index(drop=True)

    print(f"  {len(df)}개 캔들 (NaN 제거 후)")

    return df


def make_env(df):
    """환경 생성 함수"""
    env = TradingEnv(df, initial_capital=10_000_000, fee_rate=0.0005, slippage=0.0002)
    env = Monitor(env)
    return env


def train_dqn(
    train_df: pd.DataFrame,
    val_df: pd.DataFrame = None,
    total_timesteps: int = 50_000,
    learning_rate: float = 0.0001,
    buffer_size: int = 50_000,
    batch_size: int = 64,
    gamma: float = 0.95,
    exploration_fraction: float = 0.3,
    exploration_final_eps: float = 0.05,
    save_path: str = './models/dqn_conservative'
):
    """
    DQN Agent 학습

    Args:
        train_df: 학습 데이터
        val_df: 검증 데이터 (optional)
        total_timesteps: 총 학습 스텝
        learning_rate: 학습률
        buffer_size: Replay Buffer 크기
        batch_size: 배치 크기
        gamma: 할인율 (미래 보상 가중치)
        exploration_fraction: 탐험 비율 (초기)
        exploration_final_eps: 탐험 비율 (최종)
        save_path: 모델 저장 경로
    """
    print("\n" + "=" * 80)
    print("DQN Conservative Agent Training")
    print("=" * 80)

    # 환경 생성
    print("\n[1/3] 환경 생성...")
    train_env = DummyVecEnv([lambda: make_env(train_df)])

    if val_df is not None:
        eval_env = DummyVecEnv([lambda: make_env(val_df)])
    else:
        eval_env = None

    print(f"  Train Env: {len(train_df)} 캔들")
    if val_df is not None:
        print(f"  Eval Env: {len(val_df)} 캔들")

    # DQN 모델 생성
    print("\n[2/3] DQN 모델 생성...")
    model = DQN(
        policy="MlpPolicy",
        env=train_env,
        learning_rate=learning_rate,
        buffer_size=buffer_size,
        learning_starts=1000,
        batch_size=batch_size,
        tau=1.0,
        gamma=gamma,
        train_freq=4,
        gradient_steps=1,
        target_update_interval=1000,
        exploration_fraction=exploration_fraction,
        exploration_initial_eps=1.0,
        exploration_final_eps=exploration_final_eps,
        verbose=1,
        tensorboard_log="./logs/dqn_conservative"
    )

    print(f"  Policy: MlpPolicy")
    print(f"  Learning Rate: {learning_rate}")
    print(f"  Gamma: {gamma}")
    print(f"  Buffer Size: {buffer_size}")
    print(f"  Exploration: {exploration_fraction} → {exploration_final_eps}")

    # Callbacks
    callbacks = []

    # Checkpoint: 매 10k 스텝마다 저장
    checkpoint_callback = CheckpointCallback(
        save_freq=10_000,
        save_path=save_path,
        name_prefix='dqn_checkpoint'
    )
    callbacks.append(checkpoint_callback)

    # Evaluation: 검증 환경에서 평가
    if eval_env is not None:
        eval_callback = EvalCallback(
            eval_env,
            best_model_save_path=save_path,
            log_path='./logs/dqn_eval',
            eval_freq=10_000,
            deterministic=True,
            render=False
        )
        callbacks.append(eval_callback)

    # 학습
    print("\n[3/3] 학습 시작...")
    print(f"  Total Timesteps: {total_timesteps:,}")
    print(f"  Estimated Time: ~{total_timesteps // 1000} minutes")

    model.learn(
        total_timesteps=total_timesteps,
        callback=callbacks,
        progress_bar=True
    )

    # 최종 모델 저장
    final_path = f"{save_path}/dqn_final"
    model.save(final_path)

    print("\n" + "=" * 80)
    print(f"✅ 학습 완료")
    print(f"  모델 저장: {final_path}.zip")
    print("=" * 80)

    return model


def evaluate_agent(model, df: pd.DataFrame, title: str = "Evaluation"):
    """에이전트 평가"""
    print("\n" + "=" * 80)
    print(title)
    print("=" * 80)

    env = make_env(df)
    obs, info = env.reset()

    total_reward = 0.0
    done = False
    step = 0

    while not done:
        action, _states = model.predict(obs, deterministic=True)
        obs, reward, terminated, truncated, info = env.step(action)
        total_reward += reward
        step += 1
        done = terminated or truncated

    final_equity = info['equity']
    initial_capital = 10_000_000
    total_return = ((final_equity - initial_capital) / initial_capital) * 100

    print(f"\n초기 자본: {initial_capital:,.0f}원")
    print(f"최종 자본: {final_equity:,.0f}원")
    print(f"수익률: {total_return:+.2f}%")
    print(f"총 Reward: {total_reward:+.2f}")
    print(f"총 거래: {info['total_trades']}회")
    print(f"승률: {info['win_rate']:.1%}")
    print("=" * 80)

    return {
        'final_equity': final_equity,
        'total_return': total_return,
        'total_reward': total_reward,
        'total_trades': info['total_trades'],
        'win_rate': info['win_rate']
    }


if __name__ == '__main__':
    """
    DQN 학습 메인
    """
    # 데이터 준비
    print("=" * 80)
    print("Data Preparation")
    print("=" * 80)

    train_df = prepare_data('2018-09-04', '2023-12-31')  # 5.3년 학습
    val_df = prepare_data('2024-01-01', '2024-12-30')    # 2024 검증
    test_df = prepare_data('2025-01-01', '2025-10-17')   # 2025 테스트

    # 학습
    model = train_dqn(
        train_df=train_df,
        val_df=val_df,
        total_timesteps=50_000,
        learning_rate=0.0001,
        buffer_size=50_000,
        batch_size=64,
        gamma=0.95,
        exploration_fraction=0.3,
        exploration_final_eps=0.05,
        save_path='./models/dqn_conservative'
    )

    # 평가
    train_results = evaluate_agent(model, train_df, title="Train Set Evaluation (2018-2023)")
    val_results = evaluate_agent(model, val_df, title="Validation Set Evaluation (2024)")
    test_results = evaluate_agent(model, test_df, title="Test Set Evaluation (2025)")

    # 결과 저장
    results = {
        'agent': 'DQN (Conservative)',
        'timestamp': datetime.now().isoformat(),
        'train': {
            'period': '2018-09-04 ~ 2023-12-31',
            'return': train_results['total_return'],
            'trades': train_results['total_trades'],
            'win_rate': train_results['win_rate']
        },
        'validation_2024': {
            'period': '2024-01-01 ~ 2024-12-30',
            'return': val_results['total_return'],
            'trades': val_results['total_trades'],
            'win_rate': val_results['win_rate']
        },
        'test_2025': {
            'period': '2025-01-01 ~ 2025-10-17',
            'return': test_results['total_return'],
            'trades': test_results['total_trades'],
            'win_rate': test_results['win_rate']
        }
    }

    with open('dqn_results.json', 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    print("\n결과 저장: dqn_results.json")
