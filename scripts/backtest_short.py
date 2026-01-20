#!/usr/bin/env python3
"""
Short V1 Strategy Backtester
숏 전략 백테스팅 (Binance Futures 데이터)

사용법:
    python backtest_short.py [--year 2024] [--preset NAME]

프리셋:
    - baseline: 기존 단순 전략 (EMA cross, fixed SL/TP)
    - enhanced: 향상된 전략 (2-tier exit, ATR-based SL, trailing stop)
"""

import sys
import os
from pathlib import Path
from datetime import datetime
import pandas as pd
import numpy as np
from typing import Dict, Any, Optional, List

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


PRESETS: Dict[str, Dict[str, Any]] = {
    # 기존(단순) 숏 전략
    "baseline": {
        "strategy_impl": "basic",
        "ema_fast": 50,
        "ema_slow": 200,
        "adx_threshold": 25,
        "stop_loss_pct": 2.0,
        "take_profit_pct": 5.0,
        "position_size": 0.3,
        "leverage": 3,
    },

    # 향상된 전략 (trading/strategy/short_v1.py와 동일)
    "enhanced": {
        "strategy_impl": "enhanced",
        "ema_fast": 50,
        "ema_slow": 200,
        "adx_period": 14,
        "adx_min": 25,
        "require_death_cross": True,
        "di_negative_dominant": True,
        "max_leverage": 3,
        "position_risk_pct": 1.0,
        "max_stop_loss_pct": 5.0,
        "risk_reward_ratio": 2.5,
        "exit_on_golden_cross": True,
        "two_tier_enabled": True,
        "first_tier_r_multiple": 1.0,
        "first_tier_pct": 0.5,
        "second_tier_r_multiple": 2.0,
        "atr_buffer_multiplier": 1.5,
        "trailing_stop_atr_multiplier": 1.5,
        "require_adx_not_declining": True,
        "halt_entries_on_extreme_vol": True,
        "extreme_volatility_threshold": 0.10,
        "leverage": 3,
    },
}


def get_preset(name: str) -> Dict[str, Any]:
    if name not in PRESETS:
        available = ", ".join(sorted(PRESETS.keys()))
        raise ValueError(f"Unknown preset '{name}'. Available: {available}")
    return dict(PRESETS[name])


class BasicShortStrategy:
    """Basic Short V1 전략 - EMA 데드크로스 기반 숏 (단순 버전)"""

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
            'stop_loss_pct': 2.0,
            'take_profit_pct': 5.0,
            'position_size': 0.3,
            'leverage': 3,
        }

    def add_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """기술적 지표 추가"""
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

        return df

    def execute(self, df: pd.DataFrame, i: int) -> Dict:
        """전략 실행"""
        if i < 200:
            return {'action': 'hold', 'reason': 'WARMUP'}

        if self._cached_df is None or len(df) != len(self._cached_df):
            self._cached_df = self.add_indicators(df)

        row = self._cached_df.iloc[i]

        if self.in_position:
            pnl_pct = (self.entry_price - row['close']) / self.entry_price * 100

            if pnl_pct <= -self.config['stop_loss_pct']:
                self.in_position = False
                return {'action': 'close_short', 'fraction': 1.0, 'reason': f'STOP_LOSS: {pnl_pct:+.2f}%', 'pnl_pct': pnl_pct}

            if pnl_pct >= self.config['take_profit_pct']:
                self.in_position = False
                return {'action': 'close_short', 'fraction': 1.0, 'reason': f'TAKE_PROFIT: {pnl_pct:+.2f}%', 'pnl_pct': pnl_pct}

            if row.get('golden_cross', False):
                self.in_position = False
                return {'action': 'close_short', 'fraction': 1.0, 'reason': f'GOLDEN_CROSS: {pnl_pct:+.2f}%', 'pnl_pct': pnl_pct}

            return {'action': 'hold', 'reason': 'IN_POSITION'}

        if row.get('death_cross', False):
            adx = row.get('adx', 0)
            plus_di = row.get('plus_di', 0)
            minus_di = row.get('minus_di', 0)

            if adx >= self.config['adx_threshold'] and minus_di > plus_di:
                self.in_position = True
                self.entry_price = row['close']
                return {'action': 'open_short', 'fraction': float(self.config.get('position_size', 0.3)), 'reason': f'DEATH_CROSS: ADX={adx:.1f}'}

        return {'action': 'hold', 'reason': 'NO_SIGNAL'}


from trading.strategies.components.strategy_factory import StrategyFactory
from core.component_adapter import ComponentStrategyAdapter
from trading.indicators import add_all_indicators, technical as ta

class EnhancedShortStrategyAdapter:
    """Adapter for Short Strategy using new Component System"""

    def __init__(self, config: Dict = None):
        self.config = config or {}
        # Initialize Factory and Component Adapter
        self.factory = StrategyFactory(redis_client=None)
        self.adapter = ComponentStrategyAdapter(self.factory, "short_v1", self.config)

        self._indicators_added = False
        self._cached_df = None

    def execute(self, df: pd.DataFrame, i: int) -> Dict:
        """Execute strategy and return signal compatible with backtester"""
        if i < 200:
            return {'action': 'hold', 'reason': 'WARMUP'}

        # Add indicators once (Idempotent check)
        if not self._indicators_added:
            # We must work on a copy to avoid SettingWithCopy warnings if df is a slice
            self._cached_df = df.copy()
            add_all_indicators(self._cached_df)

            # Calculate custom indicators needed for ShortV1
            close = self._cached_df['close']
            high = self._cached_df['high']
            low = self._cached_df['low']

            ema_fast = self.config.get('ema_fast', 68)
            ema_slow = self.config.get('ema_slow', 128)
            self._cached_df[f'ema_{ema_fast}'] = ta.ema(close, period=ema_fast)
            self._cached_df[f'ema_{ema_slow}'] = ta.ema(close, period=ema_slow)

            adx_period = self.config.get('adx_period', 14)
            if adx_period != 14:
                self._cached_df['adx'], self._cached_df['plus_di'], self._cached_df['minus_di'] = ta.adx(high, low, close, period=adx_period)

            self._cached_df['adx_slope'] = self._cached_df['adx'].diff()

            self._indicators_added = True

        # Delegate `execute` to the ComponentStrategyAdapter
        # ComponentStrategyAdapter takes (df, i) and returns dict with action/fraction/reason
        return self.adapter(self._cached_df, i)

        return {'action': 'hold', 'reason': 'NO_SIGNAL'}


class ShortBacktester:
    """숏 전략 백테스터 (Enhanced version with two-tier support)"""

    def __init__(
        self,
        initial_capital: float = 10_000_000,
        fee_rate: float = 0.0004,
        slippage: float = 0.0002,
        leverage: int = 3
    ):
        self.initial_capital = initial_capital
        self.fee_rate = fee_rate
        self.slippage = slippage
        self.leverage = leverage

        self.capital = initial_capital
        self.position_size = 0.0
        self.entry_price = 0.0
        self.initial_position_size = 0.0
        self.trades: List[Dict] = []
        self.equity_curve: List[float] = []

    def run(self, df: pd.DataFrame, strategy) -> Dict:
        """백테스팅 실행"""
        self.capital = self.initial_capital
        self.position_size = 0.0
        self.entry_price = 0.0
        self.initial_position_size = 0.0
        self.trades = []
        self.equity_curve = []

        for i in range(len(df)):
            signal = strategy.execute(df, i)
            row = df.iloc[i]
            action = signal.get('action', 'hold')

            # Open Short
            if action == 'open_short' and self.position_size == 0:
                fraction = signal.get('fraction', 0.3)
                margin = self.capital * fraction
                self.position_size = margin * self.leverage
                self.initial_position_size = self.position_size
                self.entry_price = row['close'] * (1 - self.slippage)
                fee = self.position_size * self.fee_rate

                self.capital -= margin + fee

                self.trades.append({
                    'type': 'open_short',
                    'time': row.get('timestamp', row.name),
                    'price': self.entry_price,
                    'size': self.position_size,
                    'margin': margin,
                    'fee': fee,
                    'reason': signal.get('reason', '')
                })

            # Partial Close (50% at 1R)
            elif action == 'partial_close' and self.position_size > 0:
                close_fraction = signal.get('fraction', 0.5)
                close_size = self.initial_position_size * close_fraction
                exit_price = row['close'] * (1 + self.slippage)

                pnl_ratio = (self.entry_price - exit_price) / self.entry_price
                pnl = close_size * pnl_ratio
                fee = close_size * self.fee_rate

                margin_return = close_size / self.leverage
                self.capital += margin_return + pnl - fee
                self.position_size -= close_size

                self.trades.append({
                    'type': 'partial_close',
                    'time': row.get('timestamp', row.name),
                    'entry_price': self.entry_price,
                    'exit_price': exit_price,
                    'size': close_size,
                    'pnl': pnl,
                    'pnl_pct': pnl_ratio * 100 * self.leverage,
                    'fee': fee,
                    'reason': signal.get('reason', ''),
                    'remaining_size': self.position_size,
                })

            # Close Short (full)
            elif action == 'close_short' and self.position_size > 0:
                exit_price = row['close'] * (1 + self.slippage)

                pnl_ratio = (self.entry_price - exit_price) / self.entry_price
                pnl = self.position_size * pnl_ratio
                fee = self.position_size * self.fee_rate

                margin_return = self.position_size / self.leverage
                self.capital += margin_return + pnl - fee

                self.trades.append({
                    'type': 'close_short',
                    'time': row.get('timestamp', row.name),
                    'entry_price': self.entry_price,
                    'exit_price': exit_price,
                    'size': self.position_size,
                    'pnl': pnl,
                    'pnl_pct': pnl_ratio * 100 * self.leverage,
                    'fee': fee,
                    'reason': signal.get('reason', '')
                })

                self.position_size = 0.0
                self.entry_price = 0.0
                self.initial_position_size = 0.0

            # Equity calculation
            if self.position_size > 0:
                unrealized_pnl_ratio = (self.entry_price - row['close']) / self.entry_price
                unrealized_pnl = self.position_size * unrealized_pnl_ratio
                current_equity = self.capital + (self.position_size / self.leverage) + unrealized_pnl
            else:
                current_equity = self.capital

            self.equity_curve.append(current_equity)

        # Close remaining position
        if self.position_size > 0:
            last_price = df.iloc[-1]['close']
            pnl_ratio = (self.entry_price - last_price) / self.entry_price
            pnl = self.position_size * pnl_ratio
            self.capital += (self.position_size / self.leverage) + pnl

        return self._calculate_metrics(df)

    def _calculate_metrics(self, df: pd.DataFrame) -> Dict:
        """성과 지표 계산"""
        final_capital = self.capital
        total_return = (final_capital - self.initial_capital) / self.initial_capital * 100

        close_trades = [t for t in self.trades if t['type'] in ('close_short', 'partial_close')]

        if not close_trades:
            return {
                'initial_capital': self.initial_capital,
                'final_capital': final_capital,
                'total_return': total_return,
                'total_trades': 0,
                'equity_curve': self.equity_curve
            }

        profits = [t['pnl'] for t in close_trades]
        wins = [p for p in profits if p > 0]
        losses = [p for p in profits if p <= 0]

        win_rate = len(wins) / len(close_trades) * 100 if close_trades else 0
        avg_win = np.mean(wins) if wins else 0
        avg_loss = abs(np.mean(losses)) if losses else 0
        profit_factor = sum(wins) / abs(sum(losses)) if losses and sum(losses) != 0 else 0

        equity_series = pd.Series(self.equity_curve)
        returns = equity_series.pct_change().dropna()
        sharpe = returns.mean() / returns.std() * np.sqrt(252) if len(returns) > 0 and returns.std() > 0 else 0

        peak = equity_series.cummax()
        drawdown = (equity_series - peak) / peak * 100
        mdd = drawdown.min()

        return {
            'initial_capital': self.initial_capital,
            'final_capital': final_capital,
            'total_return': total_return,
            'total_trades': len(close_trades),
            'winning_trades': len(wins),
            'losing_trades': len(losses),
            'win_rate': win_rate,
            'avg_win': avg_win,
            'avg_loss': avg_loss,
            'profit_factor': profit_factor,
            'sharpe_ratio': sharpe,
            'max_drawdown': mdd,
            'trades': self.trades,
            'equity_curve': self.equity_curve
        }


def load_binance_data(timeframe: str, start_date: str, end_date: str) -> pd.DataFrame:
    """Binance 데이터 로드"""
    from core.data_loader import DataLoader

    with DataLoader(exchange='binance') as loader:
        df = loader.load_timeframe(timeframe, start_date, end_date)
    return df


def run_backtest(
    timeframe: str = 'minute240',
    start_date: str = '2020-01-01',
    end_date: str = '2024-12-31',
    leverage: int = 3,
    preset: str = 'enhanced',
) -> Dict:
    """백테스팅 실행"""
    print(f"\n{'='*60}")
    print(f"📊 Short V1 백테스팅")
    print(f"   소스: BINANCE")
    print(f"   프리셋: {preset}")
    print(f"   타임프레임: {timeframe}")
    print(f"   기간: {start_date} ~ {end_date}")
    print(f"   레버리지: {leverage}x")
    print(f"{'='*60}")

    df = load_binance_data(timeframe, start_date, end_date)
    print(f"✅ 데이터 로드: {len(df):,}개 캔들")

    preset_cfg = get_preset(preset)
    preset_cfg['leverage'] = leverage

    # Select strategy implementation
    if preset_cfg.get('strategy_impl') == 'enhanced':
        print(f"   전략: Enhanced (2-tier exit, ATR SL, trailing stop)")
        strategy = EnhancedShortStrategyAdapter(preset_cfg)
    else:
        print(f"   전략: Basic (fixed SL/TP)")
        strategy = BasicShortStrategy(preset_cfg)

    backtester = ShortBacktester(
        initial_capital=10_000_000,
        fee_rate=0.0004,
        slippage=0.0002,
        leverage=leverage
    )

    results = backtester.run(df, strategy)

    print(f"\n📈 결과:")
    print(f"   초기 자본: {results['initial_capital']:,.0f}원")
    print(f"   최종 자본: {results['final_capital']:,.0f}원")
    print(f"   수익률: {results['total_return']:+.2f}%")
    print(f"   거래 횟수: {results['total_trades']}회")

    if results['total_trades'] > 0:
        print(f"   승률: {results['win_rate']:.1f}%")
        print(f"   평균 이익: {results['avg_win']:,.0f}원")
        print(f"   평균 손실: {results['avg_loss']:,.0f}원")
        print(f"   Profit Factor: {results['profit_factor']:.2f}")
        print(f"   Sharpe Ratio: {results['sharpe_ratio']:.2f}")
        print(f"   MDD: {results['max_drawdown']:.2f}%")

    bh_return = (df.iloc[0]['close'] - df.iloc[-1]['close']) / df.iloc[0]['close'] * 100 * leverage
    print(f"\n📊 Short Buy & Hold (x{leverage}): {bh_return:+.2f}%")
    print(f"   Alpha: {results['total_return'] - bh_return:+.2f}%p")

    results['short_bh_return'] = bh_return
    results['preset'] = preset

    return results


def run_full_analysis(preset: str = 'enhanced'):
    """전체 분석"""
    print("\n" + "="*80)
    print(f"🔻 Short V1 Strategy - 백테스팅 분석 (preset: {preset})")
    print("="*80)

    results = {}

    print("\n" + "-"*40)
    print("📌 Binance 데이터 기반")
    print("-"*40)

    for year in ['2020', '2021', '2022', '2023', '2024', '2025']:
        end_date = '2025-12-11' if year == '2025' else f'{year}-12-31'
        key = f'binance_{year}'
        try:
            results[key] = run_backtest(
                timeframe='minute240',
                start_date=f'{year}-01-01',
                end_date=end_date,
                leverage=3,
                preset=preset
            )
        except Exception as e:
            print(f"   ❌ {year}년 오류: {e}")
            import traceback
            traceback.print_exc()
            results[key] = {'total_return': 0, 'total_trades': 0}

    print(f"\n{'='*80}")
    print(f"📊 연도별 Short V1 성과 요약 (Binance Futures, 3x 레버리지, {preset})")
    print("="*80)
    print(f"{'연도':<8} {'수익률':>10} {'거래':>8} {'승률':>8} {'Sharpe':>8} {'MDD':>10}")
    print("-"*80)

    for year in ['2020', '2021', '2022', '2023', '2024', '2025']:
        key = f'binance_{year}'
        res = results.get(key, {})
        print(f"{year:<8} {res.get('total_return', 0):>+9.2f}% {res.get('total_trades', 0):>7}회 "
              f"{res.get('win_rate', 0):>7.1f}% {res.get('sharpe_ratio', 0):>7.2f} "
              f"{res.get('max_drawdown', 0):>9.2f}%")

    print("="*80)

    if preset == 'enhanced':
        print("\n💡 Enhanced 전략 특징:")
        print("   - 2-tier exit: 50% at 1R, 50% trailing stop")
        print("   - ATR-based dynamic stop loss")
        print("   - ADX declining filter (avoid weakening trends)")
        print("   - Extreme volatility filter (>10% daily range)")
    else:
        print("\n💡 Baseline 전략 특징:")
        print("   - Fixed stop loss: 2%")
        print("   - Fixed take profit: 5%")
        print("   - Simple EMA death cross entry")

    return results


def compare_presets():
    """Compare baseline vs enhanced presets"""
    print("\n" + "="*80)
    print("📊 전략 비교: Baseline vs Enhanced")
    print("="*80)

    baseline_results = run_full_analysis(preset='baseline')
    enhanced_results = run_full_analysis(preset='enhanced')

    print("\n" + "="*80)
    print("📊 비교 요약")
    print("="*80)
    print(f"{'연도':<8} {'Baseline':>12} {'Enhanced':>12} {'차이':>12}")
    print("-"*80)

    for year in ['2020', '2021', '2022', '2023', '2024', '2025']:
        key = f'binance_{year}'
        b_ret = baseline_results.get(key, {}).get('total_return', 0)
        e_ret = enhanced_results.get(key, {}).get('total_return', 0)
        diff = e_ret - b_ret
        print(f"{year:<8} {b_ret:>+11.2f}% {e_ret:>+11.2f}% {diff:>+11.2f}%p")

    print("="*80)


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Short V1 백테스팅 (Binance)')
    parser.add_argument('--year', default='all')
    parser.add_argument('--timeframe', default='minute240')
    parser.add_argument('--leverage', type=int, default=3)
    parser.add_argument('--preset', default='enhanced', help=f"Presets: {', '.join(sorted(PRESETS.keys()))}")
    parser.add_argument('--compare', action='store_true', help='Compare baseline vs enhanced')

    args = parser.parse_args()

    if args.compare:
        compare_presets()
    elif args.year == 'all':
        run_full_analysis(preset=args.preset)
    else:
        end_date = '2025-12-11' if args.year == '2025' else f'{args.year}-12-31'
        run_backtest(
            timeframe=args.timeframe,
            start_date=f'{args.year}-01-01',
            end_date=end_date,
            leverage=args.leverage,
            preset=args.preset,
        )
