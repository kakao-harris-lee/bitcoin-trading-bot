#!/usr/bin/env python3
"""
PPO Agent Training Script

Balanced strategy:
- Balance between risk and reward
- Moderate position sizing
- Adaptive stop-loss
"""

import sys
sys.path.append('../..')

import json
import numpy as np
import pandas as pd
from datetime import datetime

from stable_baselines3 import PPO
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
    print("지표 추가...")
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


def train_ppo(
    train_df: pd.DataFrame,
    val_df: pd.DataFrame = None,
    total_timesteps: int = 100_000,
    learning_rate: float = 0.0003,
    n_steps: int = 2048,
    batch_size: int = 64,
    n_epochs: int = 10,
    gamma: float = 0.99,
    gae_lambda: float = 0.95,
    clip_range: float = 0.2,
    save_path: str = './models/ppo_balanced'
):
    """
    PPO Agent 학습

    Args:
        train_df: 학습 데이터
        val_df: 검증 데이터 (optional)
        total_timesteps: 총 학습 스텝
        learning_rate: 학습률
        n_steps: 에피소드 당 스텝
        batch_size: 배치 크기
        n_epochs: PPO 업데이트 에폭
        gamma: 할인율
        gae_lambda: GAE lambda
        clip_range: Clipping 범위
        save_path: 모델 저장 경로
    """
    print("\n" + "=" * 80)
    print("PPO Balanced Agent Training")
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

    # PPO 모델 생성
    print("\n[2/3] PPO 모델 생성...")
    model = PPO(
        policy="MlpPolicy",
        env=train_env,
        learning_rate=learning_rate,
        n_steps=n_steps,
        batch_size=batch_size,
        n_epochs=n_epochs,
        gamma=gamma,
        gae_lambda=gae_lambda,
        clip_range=clip_range,
        clip_range_vf=None,
        normalize_advantage=True,
        ent_coef=0.0,
        vf_coef=0.5,
        max_grad_norm=0.5,
        verbose=1,
        tensorboard_log="./logs/ppo_balanced"
    )

    print(f"  Policy: MlpPolicy")
    print(f"  Learning Rate: {learning_rate}")
    print(f"  Gamma: {gamma}")
    print(f"  n_steps: {n_steps}")
    print(f"  batch_size: {batch_size}")
    print(f"  n_epochs: {n_epochs}")
    print(f"  clip_range: {clip_range}")

    # Callbacks
    callbacks = []

    # Checkpoint: 매 20k 스텝마다 저장
    checkpoint_callback = CheckpointCallback(
        save_freq=20_000,
        save_path=save_path,
        name_prefix='ppo_checkpoint'
    )
    callbacks.append(checkpoint_callback)

    # Evaluation: 검증 환경에서 평가
    if eval_env is not None:
        eval_callback = EvalCallback(
            eval_env,
            best_model_save_path=save_path,
            log_path='./logs/ppo_eval',
            eval_freq=20_000,
            deterministic=True,
            render=False
        )
        callbacks.append(eval_callback)

    # 학습
    print("\n[3/3] 학습 시작...")
    print(f"  Total Timesteps: {total_timesteps:,}")
    print(f"  Estimated Time: ~{total_timesteps // 2000} minutes")

    model.learn(
        total_timesteps=total_timesteps,
        callback=callbacks,
        progress_bar=True
    )

    # 최종 모델 저장
    final_path = f"{save_path}/ppo_final"
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
    actions_taken = []

    while not done:
        action, _states = model.predict(obs, deterministic=True)
        actions_taken.append(float(action[0]))
        obs, reward, terminated, truncated, info = env.step(action)
        total_reward += reward
        step += 1
        done = terminated or truncated

    final_equity = info['equity']
    initial_capital = 10_000_000
    total_return = ((final_equity - initial_capital) / initial_capital) * 100

    # Action 분석
    actions_taken = np.array(actions_taken)
    buy_actions = (actions_taken > 0.1).sum()
    sell_actions = (actions_taken < -0.1).sum()
    hold_actions = ((actions_taken >= -0.1) & (actions_taken <= 0.1)).sum()

    print(f"\n초기 자본: {initial_capital:,.0f}원")
    print(f"최종 자본: {final_equity:,.0f}원")
    print(f"수익률: {total_return:+.2f}%")
    print(f"총 Reward: {total_reward:+.2f}")
    print(f"총 거래: {info['total_trades']}회")
    print(f"승률: {info['win_rate']:.1%}")
    print(f"\nAction 분포:")
    print(f"  Buy: {buy_actions}회 ({buy_actions/len(actions_taken)*100:.1f}%)")
    print(f"  Sell: {sell_actions}회 ({sell_actions/len(actions_taken)*100:.1f}%)")
    print(f"  Hold: {hold_actions}회 ({hold_actions/len(actions_taken)*100:.1f}%)")
    print("=" * 80)

    return {
        'final_equity': final_equity,
        'total_return': total_return,
        'total_reward': total_reward,
        'total_trades': info['total_trades'],
        'win_rate': info['win_rate'],
        'buy_actions': int(buy_actions),
        'sell_actions': int(sell_actions),
        'hold_actions': int(hold_actions)
    }


if __name__ == '__main__':
    """
    PPO 학습 메인
    """
    # numpy 다운그레이드 (NumPy 2.x → 1.x)
    import subprocess
    subprocess.run(['pip', 'install', 'numpy<2'], check=False)

    # 데이터 준비
    print("=" * 80)
    print("Data Preparation")
    print("=" * 80)

    train_df = prepare_data('2018-09-04', '2023-12-31')  # 5.3년 학습
    val_df = prepare_data('2024-01-01', '2024-12-30')    # 2024 검증
    test_df = prepare_data('2025-01-01', '2025-10-17')   # 2025 테스트

    # 학습
    model = train_ppo(
        train_df=train_df,
        val_df=val_df,
        total_timesteps=100_000,
        learning_rate=0.0003,
        n_steps=2048,
        batch_size=64,
        n_epochs=10,
        gamma=0.99,
        gae_lambda=0.95,
        clip_range=0.2,
        save_path='./models/ppo_balanced'
    )

    # 평가
    train_results = evaluate_agent(model, train_df, title="Train Set Evaluation (2018-2023)")
    val_results = evaluate_agent(model, val_df, title="Validation Set Evaluation (2024)")
    test_results = evaluate_agent(model, test_df, title="Test Set Evaluation (2025)")

    # 결과 저장
    results = {
        'agent': 'PPO (Balanced)',
        'timestamp': datetime.now().isoformat(),
        'train': {
            'period': '2018-09-04 ~ 2023-12-31',
            'return': train_results['total_return'],
            'trades': train_results['total_trades'],
            'win_rate': train_results['win_rate'],
            'actions': {
                'buy': train_results['buy_actions'],
                'sell': train_results['sell_actions'],
                'hold': train_results['hold_actions']
            }
        },
        'validation_2024': {
            'period': '2024-01-01 ~ 2024-12-30',
            'return': val_results['total_return'],
            'trades': val_results['total_trades'],
            'win_rate': val_results['win_rate'],
            'actions': {
                'buy': val_results['buy_actions'],
                'sell': val_results['sell_actions'],
                'hold': val_results['hold_actions']
            }
        },
        'test_2025': {
            'period': '2025-01-01 ~ 2025-10-17',
            'return': test_results['total_return'],
            'trades': test_results['total_trades'],
            'win_rate': test_results['win_rate'],
            'actions': {
                'buy': test_results['buy_actions'],
                'sell': test_results['sell_actions'],
                'hold': test_results['hold_actions']
            }
        }
    }

    with open('ppo_results.json', 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    print("\n✅ 결과 저장: ppo_results.json")
    print("\n" + "=" * 80)
    print("v10 RL Hybrid - PPO Training Complete")
    print("=" * 80)
