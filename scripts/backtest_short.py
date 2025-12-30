#!/usr/bin/env python3
"""
Short V1 Strategy Backtester
숏 전략 백테스팅 (Upbit 데이터 시뮬레이션 + Binance Futures 데이터)

사용법:
    python backtest_short_v1.py [--source upbit|binance] [--year 2024] [--preset NAME]
"""

import sys
import os
from pathlib import Path
from datetime import datetime
import pandas as pd
import numpy as np
from typing import Dict, Any, Optional, List

PROJECT_ROOT = Path(__file__).parent.parent.parent
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

    # Grid Search 추천(2020-2024 train + 2025 OOS 확인)
    # optimize_short_v1.py 결과 기반: EMA(30/100), ADX>20, SL2.5, TP5.0
    "opt_v1": {
        "strategy_impl": "optimized",
        "ema_fast": 30,
        "ema_slow": 100,
        "adx_threshold": 20,
        "stop_loss_pct": 2.5,
        "take_profit_pct": 5.0,
        "position_size": 0.3,
        "leverage": 3,
        "entry_mode": "any",
        "min_signals": 1,
        "use_death_cross": True,
        "use_rsi_overbought": False,
        "use_bb_rejection": True,
        "use_trend_follow": True,
        "rsi_oversold": 25,
        "bb_upper_threshold": 0.93,
        "slope_threshold": -0.5,
        "max_hold_bars": 100,
    },
}


def get_preset(name: str) -> Dict[str, Any]:
    if name not in PRESETS:
        available = ", ".join(sorted(PRESETS.keys()))
        raise ValueError(f"Unknown preset '{name}'. Available: {available}")
    return dict(PRESETS[name])


class ShortV1Strategy:
    """Short V1 전략 - EMA 데드크로스 기반 숏"""

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
            'stop_loss_pct': 2.0,   # +2% (숏이므로 가격 상승이 손실)
            'take_profit_pct': 5.0,  # -5% (숏이므로 가격 하락이 이익)
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

        # 추세 방향
        df['trend'] = np.where(df['ema_fast'] > df['ema_slow'], 'UP', 'DOWN')

        return df

    def execute(self, df: pd.DataFrame, i: int) -> Dict:
        """전략 실행"""
        if i < 200:  # EMA 200 워밍업
            return {'action': 'hold', 'reason': 'WARMUP'}

        # 지표 계산 (캐싱)
        if self._cached_df is None or len(df) != len(self._cached_df):
            self._cached_df = self.add_indicators(df)

        row = self._cached_df.iloc[i]

        # 포지션 있을 때: 청산 조건 확인
        if self.in_position:
            # 숏 PnL: (entry - current) / entry
            pnl_pct = (self.entry_price - row['close']) / self.entry_price * 100

            # 스탑로스 (가격 상승)
            if pnl_pct <= -self.config['stop_loss_pct']:
                self.in_position = False
                return {
                    'action': 'close_short',
                    'fraction': 1.0,
                    'reason': f'STOP_LOSS: {pnl_pct:+.2f}%',
                    'pnl_pct': pnl_pct
                }

            # 테이크프로핏 (가격 하락)
            if pnl_pct >= self.config['take_profit_pct']:
                self.in_position = False
                return {
                    'action': 'close_short',
                    'fraction': 1.0,
                    'reason': f'TAKE_PROFIT: {pnl_pct:+.2f}%',
                    'pnl_pct': pnl_pct
                }

            # 골든크로스 시 청산 (추세 반전)
            if row.get('golden_cross', False):
                self.in_position = False
                return {
                    'action': 'close_short',
                    'fraction': 1.0,
                    'reason': f'GOLDEN_CROSS: {pnl_pct:+.2f}%',
                    'pnl_pct': pnl_pct
                }

            return {'action': 'hold', 'reason': 'IN_POSITION'}

        # 포지션 없을 때: 진입 조건 확인
        # 데드크로스 + ADX 강세 + -DI > +DI
        if row.get('death_cross', False):
            adx = row.get('adx', 0)
            plus_di = row.get('plus_di', 0)
            minus_di = row.get('minus_di', 0)

            if adx >= self.config['adx_threshold'] and minus_di > plus_di:
                self.in_position = True
                self.entry_price = row['close']
                self.entry_time = row.get('timestamp', row.name)
                return {
                    'action': 'open_short',
                    'fraction': float(self.config.get('position_size', 0.3)),
                    'reason': f'DEATH_CROSS: ADX={adx:.1f}, -DI={minus_di:.1f} > +DI={plus_di:.1f}'
                }

        return {'action': 'hold', 'reason': 'NO_SIGNAL'}


class ShortBacktester:
    """숏 전략 백테스터"""

    def __init__(
        self,
        initial_capital: float = 10_000_000,
        fee_rate: float = 0.0004,  # Binance Futures 수수료
        slippage: float = 0.0002,
        leverage: int = 3
    ):
        self.initial_capital = initial_capital
        self.fee_rate = fee_rate
        self.slippage = slippage
        self.leverage = leverage

        # 상태
        self.capital = initial_capital
        self.position_size = 0.0  # USDT 기준 포지션 크기
        self.entry_price = 0.0
        self.trades: List[Dict] = []
        self.equity_curve: List[float] = []

    def run(self, df: pd.DataFrame, strategy: ShortV1Strategy) -> Dict:
        """백테스팅 실행"""
        self.capital = self.initial_capital
        self.position_size = 0.0
        self.entry_price = 0.0
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
                self.position_size = margin * self.leverage  # 레버리지 적용
                self.entry_price = row['close'] * (1 - self.slippage)  # 숏 진입 시 유리하게
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

            # Close Short
            elif action == 'close_short' and self.position_size > 0:
                exit_price = row['close'] * (1 + self.slippage)  # 숏 청산 시 불리하게

                # 숏 PnL: (entry - exit) / entry * position_size
                pnl_ratio = (self.entry_price - exit_price) / self.entry_price
                pnl = self.position_size * pnl_ratio
                fee = self.position_size * self.fee_rate

                # 마진 회수 + PnL
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

            # Equity 계산
            if self.position_size > 0:
                unrealized_pnl_ratio = (self.entry_price - row['close']) / self.entry_price
                unrealized_pnl = self.position_size * unrealized_pnl_ratio
                current_equity = self.capital + (self.position_size / self.leverage) + unrealized_pnl
            else:
                current_equity = self.capital

            self.equity_curve.append(current_equity)

        # 미청산 포지션 정리
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

        # 거래 분석
        close_trades = [t for t in self.trades if t['type'] == 'close_short']

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

        # Sharpe Ratio
        equity_series = pd.Series(self.equity_curve)
        returns = equity_series.pct_change().dropna()
        sharpe = returns.mean() / returns.std() * np.sqrt(252) if len(returns) > 0 and returns.std() > 0 else 0

        # MDD
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


def load_upbit_data(timeframe: str, start_date: str, end_date: str) -> pd.DataFrame:
    """Upbit 데이터 로드"""
    from core.data_loader import DataLoader

    db_path = PROJECT_ROOT / 'data' / 'upbit_bitcoin.db'
    loader = DataLoader(str(db_path))
    df = loader.load_timeframe(timeframe, start_date, end_date)
    loader.conn.close()
    return df


def load_binance_futures_data(timeframe: str, start_date: str, end_date: str) -> pd.DataFrame:
    """Binance Futures 데이터 로드"""
    import ccxt
    from datetime import datetime

    exchange = ccxt.binance({
        'options': {'defaultType': 'future'}
    })

    # 타임프레임 매핑
    tf_map = {
        'minute240': '4h',
        'minute60': '1h',
        'day': '1d',
    }
    ccxt_tf = tf_map.get(timeframe, '4h')

    # 날짜 변환
    since = int(datetime.strptime(start_date, '%Y-%m-%d').timestamp() * 1000)
    end_ts = int(datetime.strptime(end_date, '%Y-%m-%d').timestamp() * 1000)

    all_data = []
    current_since = since

    print(f"📥 Binance Futures 데이터 수집 중...")

    while current_since < end_ts:
        ohlcv = exchange.fetch_ohlcv('BTC/USDT', ccxt_tf, since=current_since, limit=1000)
        if not ohlcv:
            break

        all_data.extend(ohlcv)
        current_since = ohlcv[-1][0] + 1

        if len(all_data) % 5000 == 0:
            print(f"   수집: {len(all_data):,}개...")

    print(f"✅ 총 {len(all_data):,}개 캔들 수집")

    # DataFrame 변환
    df = pd.DataFrame(all_data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    df = df[df['timestamp'] <= end_date]

    return df


def run_backtest(
    source: str = 'upbit',
    timeframe: str = 'minute240',
    start_date: str = '2020-01-01',
    end_date: str = '2024-12-31',
    leverage: int = 3,
    preset: str = 'baseline',
) -> Dict:
    """백테스팅 실행"""
    print(f"\n{'='*60}")
    print(f"📊 Short V1 백테스팅")
    print(f"   소스: {source.upper()}")
    print(f"   프리셋: {preset}")
    print(f"   타임프레임: {timeframe}")
    print(f"   기간: {start_date} ~ {end_date}")
    print(f"   레버리지: {leverage}x")
    print(f"{'='*60}")

    # 데이터 로드
    if source == 'upbit':
        df = load_upbit_data(timeframe, start_date, end_date)
    else:
        df = load_binance_futures_data(timeframe, start_date, end_date)

    print(f"✅ 데이터 로드: {len(df):,}개 캔들")

    preset_cfg = get_preset(preset)
    preset_cfg['leverage'] = leverage

    # 전략 초기화
    if preset_cfg.get('strategy_impl') == 'optimized':
        from scripts.optimize import ShortV1StrategyOptimized  # type: ignore
        strategy = ShortV1StrategyOptimized(preset_cfg)
    else:
        strategy = ShortV1Strategy(preset_cfg)

    # 백테스팅 실행
    backtester = ShortBacktester(
        initial_capital=10_000_000,
        fee_rate=0.0004,  # Binance Futures
        slippage=0.0002,
        leverage=leverage
    )

    results = backtester.run(df, strategy)

    # 결과 출력
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

    # Buy & Hold 비교 (숏이므로 부호 반대)
    bh_return = (df.iloc[0]['close'] - df.iloc[-1]['close']) / df.iloc[0]['close'] * 100 * leverage
    print(f"\n📊 Short Buy & Hold (x{leverage}): {bh_return:+.2f}%")
    print(f"   Alpha: {results['total_return'] - bh_return:+.2f}%p")

    results['short_bh_return'] = bh_return

    return results


def run_full_analysis():
    """전체 분석"""
    print("\n" + "="*80)
    print("🔻 Short V1 Strategy - 백테스팅 분석")
    print("="*80)

    results = {}

    # Upbit 데이터 기반 (4시간봉)
    print("\n" + "-"*40)
    print("📌 Upbit 데이터 기반 시뮬레이션")
    print("-"*40)

    for year in ['2020', '2021', '2022', '2023', '2024', '2025']:
        end_date = '2025-12-11' if year == '2025' else f'{year}-12-31'
        key = f'upbit_{year}'
        try:
            results[key] = run_backtest(
                source='upbit',
                timeframe='minute240',
                start_date=f'{year}-01-01',
                end_date=end_date,
                leverage=3,
                preset='baseline'
            )
        except Exception as e:
            print(f"   ❌ {year}년 오류: {e}")
            results[key] = {'total_return': 0, 'total_trades': 0}

    # 요약 테이블
    print(f"\n{'='*80}")
    print("📊 연도별 Short V1 성과 요약 (Upbit 시뮬레이션, 3x 레버리지)")
    print("="*80)
    print(f"{'연도':<8} {'수익률':>10} {'거래':>8} {'승률':>8} {'Sharpe':>8} {'MDD':>10}")
    print("-"*80)

    for year in ['2020', '2021', '2022', '2023', '2024', '2025']:
        key = f'upbit_{year}'
        res = results.get(key, {})
        print(f"{year:<8} {res.get('total_return', 0):>+9.2f}% {res.get('total_trades', 0):>7}회 "
              f"{res.get('win_rate', 0):>7.1f}% {res.get('sharpe_ratio', 0):>7.2f} "
              f"{res.get('max_drawdown', 0):>9.2f}%")

    print("="*80)

    # 핵심 인사이트
    print("\n💡 핵심 인사이트:")
    print("   - 숏 전략은 하락장(2022년)에서 수익 기대")
    print("   - 상승장에서는 손실 발생 가능")
    print("   - 롱 전략(V35)과 함께 헤지 포트폴리오 구성 권장")

    return results


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Short V1 백테스팅')
    parser.add_argument('--source', choices=['upbit', 'binance'], default='upbit')
    parser.add_argument('--year', default='all')
    parser.add_argument('--timeframe', default='minute240')
    parser.add_argument('--leverage', type=int, default=3)
    parser.add_argument('--preset', default='baseline', help=f"Presets: {', '.join(sorted(PRESETS.keys()))}")

    args = parser.parse_args()

    if args.year == 'all':
        run_full_analysis()
    else:
        end_date = '2025-12-11' if args.year == '2025' else f'{args.year}-12-31'
        run_backtest(
            source=args.source,
            timeframe=args.timeframe,
            start_date=f'{args.year}-01-01',
            end_date=end_date,
            leverage=args.leverage,
            preset=args.preset,
        )
