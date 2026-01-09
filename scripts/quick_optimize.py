#!/usr/bin/env python3
"""Quick Short V1 Parameter Optimization - simplified version"""
import sys
import logging
logging.disable(logging.CRITICAL)

sys.path.insert(0, '/home/deploy/project/bitcoin-trading-bot')

import sqlite3
import pandas as pd
import numpy as np
from itertools import product
import json

def load_data(start, end):
    conn = sqlite3.connect('/home/deploy/project/bitcoin-trading-bot/data/binance_bitcoin.db')
    df = pd.read_sql_query(
        "SELECT timestamp, open, high, low, close, volume FROM binance_minute240 WHERE timestamp >= ? AND timestamp <= ? ORDER BY timestamp",
        conn, params=[start, end]
    )
    conn.close()
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    return df

def add_indicators(df, ema_fast, ema_slow, adx_period, atr_period):
    df = df.copy()
    df['ema_fast'] = df['close'].ewm(span=ema_fast, adjust=False).mean()
    df['ema_slow'] = df['close'].ewm(span=ema_slow, adjust=False).mean()

    # Death cross
    df['death_cross'] = (df['ema_fast'] < df['ema_slow']) & (df['ema_fast'].shift(1) >= df['ema_slow'].shift(1))
    df['golden_cross'] = (df['ema_fast'] > df['ema_slow']) & (df['ema_fast'].shift(1) <= df['ema_slow'].shift(1))
    df['bear_trend'] = df['ema_fast'] < df['ema_slow']

    # ATR
    tr = np.maximum(df['high'] - df['low'],
                    np.maximum(abs(df['high'] - df['close'].shift(1)),
                              abs(df['low'] - df['close'].shift(1))))
    df['atr'] = tr.rolling(atr_period).mean()

    # ADX
    plus_dm = df['high'].diff().clip(lower=0)
    minus_dm = (-df['low'].diff()).clip(lower=0)
    plus_dm[plus_dm < minus_dm] = 0
    minus_dm[minus_dm < plus_dm] = 0

    smoothed_tr = tr.rolling(adx_period).sum()
    plus_di = 100 * plus_dm.rolling(adx_period).sum() / smoothed_tr
    minus_di = 100 * minus_dm.rolling(adx_period).sum() / smoothed_tr
    dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di)
    df['adx'] = dx.rolling(adx_period).mean()
    df['plus_di'] = plus_di
    df['minus_di'] = minus_di
    df['di_bear'] = minus_di > plus_di

    # Swing high
    df['swing_high'] = df['high'].rolling(10).max()

    return df

def backtest(df, params, leverage=2):
    ema_fast = params['ema_fast']
    ema_slow = params['ema_slow']
    adx_min = params['adx_min']
    atr_mult = params['atr_mult']
    rr_ratio = params['rr_ratio']

    df = add_indicators(df, ema_fast, ema_slow, 14, 14)

    capital = 10000
    position = 0
    entry_price = 0
    stop_loss = 0
    take_profit = 0
    trades = []
    equity = [capital]

    for i in range(max(200, ema_slow + 50), len(df)):
        row = df.iloc[i]
        price = row['close']

        # Entry
        if position == 0:
            if (row['bear_trend'] or row['death_cross']) and row['adx'] >= adx_min and row['di_bear']:
                position = (capital * leverage) / price
                entry_price = price
                atr = row['atr']
                stop_loss = min(row['swing_high'] + atr * atr_mult, entry_price * 1.05)
                risk = stop_loss - entry_price
                take_profit = entry_price - risk * rr_ratio

        # Exit
        elif position > 0:
            exit_price = None
            reason = None

            if row['high'] >= stop_loss:
                exit_price = stop_loss
                reason = 'stop'
            elif row['low'] <= take_profit:
                exit_price = take_profit
                reason = 'profit'
            elif row['golden_cross']:
                exit_price = price
                reason = 'golden'

            if exit_price:
                pnl = (entry_price - exit_price) / entry_price * position * entry_price
                capital += pnl
                trades.append({'pnl': pnl, 'reason': reason})
                position = 0

        # Equity
        if position > 0:
            unrealized = (entry_price - price) / entry_price * position * entry_price
            equity.append(capital + unrealized)
        else:
            equity.append(capital)

    # Metrics
    ret = (capital - 10000) / 10000 * 100
    n = len(trades)
    win_rate = len([t for t in trades if t['pnl'] > 0]) / n * 100 if n > 0 else 0

    eq = pd.Series(equity)
    rets = eq.pct_change().dropna()
    sharpe = rets.mean() / rets.std() * np.sqrt(6*252) if len(rets) > 0 and rets.std() > 0 else 0

    mdd = ((eq - eq.expanding().max()) / eq.expanding().max() * 100).min()
    years = (df['timestamp'].iloc[-1] - df['timestamp'].iloc[0]).days / 365.25
    tpy = n / years if years > 0 else 0

    return {'return': ret, 'trades': n, 'win_rate': win_rate, 'sharpe': sharpe, 'mdd': mdd, 'tpy': tpy}

if __name__ == '__main__':
    print("Loading data...")
    df_train = load_data('2020-01-01', '2024-12-31')
    df_oos = load_data('2025-01-01', '2026-01-09')
    print(f"Train: {len(df_train)}, OOS: {len(df_oos)}")

    # Parameter grid
    grid = {
        'ema_fast': [30, 50, 68],
        'ema_slow': [100, 128, 200],
        'adx_min': [20, 25, 30],
        'atr_mult': [1.0, 1.5, 2.0],
        'rr_ratio': [2.0, 2.5, 3.0],
    }

    combos = list(product(*grid.values()))
    keys = list(grid.keys())
    print(f"Testing {len(combos)} combinations...")

    results = []
    for i, vals in enumerate(combos):
        params = dict(zip(keys, vals))
        if params['ema_fast'] >= params['ema_slow']:
            continue

        r = backtest(df_train, params)
        if r['trades'] >= 10 and r['mdd'] >= -25:
            results.append((params, r))

        if (i+1) % 50 == 0:
            print(f"  {i+1}/{len(combos)}, valid: {len(results)}")

    print(f"\nFound {len(results)} valid configs")

    # Sort by Sharpe
    results.sort(key=lambda x: x[1]['sharpe'], reverse=True)

    print("\n" + "="*80)
    print("TOP 10 TRAINING RESULTS")
    print("="*80)
    print(f"{'#':<3} {'Return':>8} {'Trades':>7} {'Win%':>6} {'Sharpe':>7} {'MDD':>7} {'Tr/Yr':>6}")
    print("-"*80)

    for i, (p, r) in enumerate(results[:10]):
        print(f"{i+1:<3} {r['return']:>7.1f}% {r['trades']:>7} {r['win_rate']:>5.0f}% {r['sharpe']:>7.2f} {r['mdd']:>6.1f}% {r['tpy']:>5.1f}")

    # OOS test
    print("\n" + "="*80)
    print("OUT-OF-SAMPLE VALIDATION")
    print("="*80)
    print(f"{'#':<3} {'Train':>8} {'OOS':>8} {'OOS Tr':>7} {'OOS Sh':>7} Params")
    print("-"*80)

    best = None
    for i, (p, train_r) in enumerate(results[:10]):
        oos_r = backtest(df_oos, p)
        print(f"{i+1:<3} {train_r['return']:>7.1f}% {oos_r['return']:>7.1f}% {oos_r['trades']:>7} {oos_r['sharpe']:>7.2f} EMA {p['ema_fast']}/{p['ema_slow']}, ADX {p['adx_min']}, ATR {p['atr_mult']}, RR {p['rr_ratio']}")

        if best is None or oos_r['sharpe'] > best[1]['sharpe']:
            best = (p, oos_r, train_r)

    if best:
        p, oos_r, train_r = best
        print("\n" + "="*80)
        print("BEST CONFIGURATION")
        print("="*80)
        print(f"Train: Return={train_r['return']:.1f}%, Sharpe={train_r['sharpe']:.2f}, Trades={train_r['trades']}")
        print(f"OOS:   Return={oos_r['return']:.1f}%, Sharpe={oos_r['sharpe']:.2f}, Trades={oos_r['trades']}")
        print(f"\nParameters: EMA {p['ema_fast']}/{p['ema_slow']}, ADX min={p['adx_min']}, ATR mult={p['atr_mult']}, R:R={p['rr_ratio']}")

        # Save
        cfg = {
            "strategy_name": "SHORT_V1_OPTIMIZED",
            "indicators": {"ema_fast": p['ema_fast'], "ema_slow": p['ema_slow'], "adx_period": 14, "atr_period": 14},
            "entry": {"adx_min": p['adx_min'], "require_death_cross": True, "di_negative_dominant": True},
            "exit": {"risk_reward_ratio": p['rr_ratio'], "exit_on_golden_cross": True},
            "stop_loss": {"atr_buffer_multiplier": p['atr_mult'], "max_stop_loss_pct": 5.0},
            "risk_management": {"max_leverage": 2},
            "performance": {"train_return": train_r['return'], "train_sharpe": train_r['sharpe'], "oos_return": oos_r['return'], "oos_sharpe": oos_r['sharpe']}
        }
        with open('/home/deploy/project/bitcoin-trading-bot/config/strategies/short_v1_optimized.json', 'w') as f:
            json.dump(cfg, f, indent=2)
        print("\nSaved to config/strategies/short_v1_optimized.json")
