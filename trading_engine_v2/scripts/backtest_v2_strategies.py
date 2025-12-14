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
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.data_loader import DataLoader
from core.backtester import Backtester


# =============================================================================
# V35 Long Strategy Adapter
# =============================================================================

class V35StrategyAdapter:
    """V35 Long 전략 어댑터 (기존 Backtester와 호환)"""

    def __init__(self, config: Dict = None):
        self.config = config or self._default_config()
        self.in_position = False
        self.entry_price = 0.0
        self.entry_time = None
        self.market_state = 'UNKNOWN'
        self.partial_exits = 0

        # 캐시된 지표
        self._cached_df = None
        self._cached_indicators = None

    def _default_config(self) -> Dict:
        """기본 설정"""
        return {
            # MarketClassifier
            'mfi_bull_strong': 52,
            'mfi_bull_moderate': 45,
            'mfi_sideways_up': 42,
            'mfi_bear_moderate': 38,
            'mfi_bear_strong': 35,
            'adx_strong_trend': 20,
            'adx_moderate_trend': 15,
            # Entry
            'rsi_oversold': 35,
            'rsi_overbought': 70,
            'bb_lower_mult': 2.0,
            # Exit
            'stop_loss': -0.015,  # -1.5%
            'tp_bull_strong': [0.05, 0.10, 0.20],
            'tp_bull_moderate': [0.03, 0.07, 0.12],
            'tp_sideways': [0.02, 0.04, 0.06],
        }

    def add_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """기술적 지표 추가"""
        df = df.copy()

        # RSI
        delta = df['close'].diff()
        gain = delta.where(delta > 0, 0).rolling(window=14).mean()
        loss = -delta.where(delta < 0, 0).rolling(window=14).mean()
        rs = gain / loss
        df['rsi'] = 100 - (100 / (1 + rs))

        # MACD
        ema12 = df['close'].ewm(span=12, adjust=False).mean()
        ema26 = df['close'].ewm(span=26, adjust=False).mean()
        df['macd'] = ema12 - ema26
        df['macd_signal'] = df['macd'].ewm(span=9, adjust=False).mean()
        df['macd_hist'] = df['macd'] - df['macd_signal']

        # Bollinger Bands
        sma20 = df['close'].rolling(window=20).mean()
        std20 = df['close'].rolling(window=20).std()
        df['bb_upper'] = sma20 + (std20 * 2)
        df['bb_middle'] = sma20
        df['bb_lower'] = sma20 - (std20 * 2)

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

        # MFI (Money Flow Index)
        typical_price = (df['high'] + df['low'] + df['close']) / 3
        raw_mf = typical_price * df['volume']
        mf_positive = raw_mf.where(typical_price > typical_price.shift(1), 0)
        mf_negative = raw_mf.where(typical_price < typical_price.shift(1), 0)
        mf_ratio = mf_positive.rolling(14).sum() / mf_negative.rolling(14).sum()
        df['mfi'] = 100 - (100 / (1 + mf_ratio))

        return df

    def classify_market(self, row: pd.Series) -> str:
        """시장 상태 분류"""
        mfi = row.get('mfi', 50)
        adx = row.get('adx', 15)

        cfg = self.config

        if mfi >= cfg['mfi_bull_strong'] and adx >= cfg['adx_strong_trend']:
            return 'BULL_STRONG'
        elif mfi >= cfg['mfi_bull_moderate'] and adx >= cfg['adx_moderate_trend']:
            return 'BULL_MODERATE'
        elif mfi >= cfg['mfi_sideways_up']:
            return 'SIDEWAYS_UP'
        elif mfi >= cfg['mfi_bear_moderate']:
            return 'SIDEWAYS_FLAT'
        elif mfi >= cfg['mfi_bear_strong']:
            return 'SIDEWAYS_DOWN'
        elif adx >= cfg['adx_strong_trend']:
            return 'BEAR_STRONG'
        else:
            return 'BEAR_MODERATE'

    def check_entry(self, row: pd.Series) -> Optional[Dict]:
        """진입 조건 확인"""
        if self.in_position:
            return None

        rsi = row.get('rsi', 50)
        close = row['close']
        bb_lower = row.get('bb_lower', close)
        macd = row.get('macd', 0)
        macd_signal = row.get('macd_signal', 0)

        # BULL 상태에서만 진입
        if self.market_state not in ['BULL_STRONG', 'BULL_MODERATE']:
            return None

        # 진입 조건: RSI 과매도 + BB 하단 근처 + MACD 골든크로스
        if rsi < self.config['rsi_oversold'] and close <= bb_lower * 1.02:
            if macd > macd_signal:  # MACD 골든크로스
                return {
                    'action': 'buy',
                    'fraction': 0.5 if self.market_state == 'BULL_STRONG' else 0.3,
                    'reason': f'ENTRY: RSI={rsi:.1f}, BB_LOWER_TOUCH, {self.market_state}'
                }

        return None

    def check_exit(self, row: pd.Series) -> Optional[Dict]:
        """청산 조건 확인"""
        if not self.in_position:
            return None

        close = row['close']
        pnl_pct = (close - self.entry_price) / self.entry_price

        # 스탑로스
        if pnl_pct <= self.config['stop_loss']:
            return {
                'action': 'sell',
                'fraction': 1.0,
                'reason': f'STOP_LOSS: {pnl_pct*100:.2f}%'
            }

        # 테이크프로핏 (시장 상태별)
        if self.market_state == 'BULL_STRONG':
            tp_levels = self.config['tp_bull_strong']
        elif self.market_state == 'BULL_MODERATE':
            tp_levels = self.config['tp_bull_moderate']
        else:
            tp_levels = self.config['tp_sideways']

        # 부분 청산
        if self.partial_exits < len(tp_levels):
            if pnl_pct >= tp_levels[self.partial_exits]:
                fraction = 0.4 if self.partial_exits == 0 else 0.3
                return {
                    'action': 'sell',
                    'fraction': fraction,
                    'reason': f'TP_LEVEL_{self.partial_exits + 1}: {pnl_pct*100:.2f}%'
                }

        # MACD 데드크로스
        macd = row.get('macd', 0)
        macd_signal = row.get('macd_signal', 0)
        if macd < macd_signal and pnl_pct > 0:
            return {
                'action': 'sell',
                'fraction': 1.0,
                'reason': f'MACD_DEAD_CROSS: {pnl_pct*100:.2f}%'
            }

        return None

    def __call__(self, df: pd.DataFrame, i: int, params: Dict) -> Dict:
        """Backtester 호환 인터페이스"""
        if i < 30:  # 워밍업
            return {'action': 'hold'}

        # 지표 계산 (캐싱)
        if self._cached_df is None or len(df) != len(self._cached_df):
            self._cached_df = self.add_indicators(df)

        row = self._cached_df.iloc[i]

        # 시장 상태 분류
        self.market_state = self.classify_market(row)

        # 청산 확인
        exit_signal = self.check_exit(row)
        if exit_signal:
            if exit_signal['fraction'] >= 1.0:
                self.in_position = False
                self.entry_price = 0
                self.partial_exits = 0
            else:
                self.partial_exits += 1
            return exit_signal

        # 진입 확인
        entry_signal = self.check_entry(row)
        if entry_signal:
            self.in_position = True
            self.entry_price = row['close']
            self.entry_time = row['timestamp']
            self.partial_exits = 0
            return entry_signal

        return {'action': 'hold'}


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
# Backtest Runner
# =============================================================================

def run_backtest(
    strategy_name: str,
    timeframe: str = 'day',
    start_date: str = '2020-01-01',
    end_date: str = '2024-12-31',
    initial_capital: float = 10_000_000,
    db_path: str = None
) -> Dict:
    """백테스팅 실행"""

    # DB 경로
    if db_path is None:
        db_path = PROJECT_ROOT / 'upbit_history_db' / 'upbit_bitcoin.db'

    print(f"\n{'='*60}")
    print(f"📊 백테스팅: {strategy_name.upper()}")
    print(f"   타임프레임: {timeframe}")
    print(f"   기간: {start_date} ~ {end_date}")
    print(f"   초기자본: {initial_capital:,.0f}원")
    print(f"{'='*60}")

    # 데이터 로드
    loader = DataLoader(str(db_path))
    df = loader.load_timeframe(timeframe, start_date, end_date)
    print(f"✅ 데이터 로드: {len(df):,}개 캔들")

    # 전략 선택
    if strategy_name == 'v35':
        strategy = V35StrategyAdapter()
    elif strategy_name == 'short_v1':
        strategy = ShortV1StrategyAdapter()
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
    print(f"\n📈 결과:")
    print(f"   초기 자본: {results['initial_capital']:,.0f}원")
    print(f"   최종 자본: {results['final_capital']:,.0f}원")
    print(f"   총 수익률: {results['total_return']:.2f}%")
    print(f"   총 거래: {results['total_trades']}회")

    if results['total_trades'] > 0:
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
            print(f"   CAGR: {cagr:.2f}%")

        # 최대 낙폭 (MDD)
        peak = equity_df['total_equity'].cummax()
        drawdown = (equity_df['total_equity'] - peak) / peak * 100
        mdd = drawdown.min()
        print(f"   MDD: {mdd:.2f}%")

        # Sharpe Ratio (일간 수익률 기반)
        daily_returns = equity_df['total_equity'].pct_change().dropna()
        if len(daily_returns) > 0:
            sharpe = (daily_returns.mean() / daily_returns.std()) * np.sqrt(252)
            print(f"   Sharpe Ratio: {sharpe:.2f}")

        results['cagr'] = cagr if years > 0 else 0
        results['mdd'] = mdd
        results['sharpe'] = sharpe if len(daily_returns) > 0 else 0

    # Buy & Hold 비교
    bh_return = (df['close'].iloc[-1] - df['close'].iloc[0]) / df['close'].iloc[0] * 100
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
    parser.add_argument('--strategy', choices=['v35', 'short_v1', 'both'], default='both')
    parser.add_argument('--period', choices=['train', 'test', 'all'], default='all')
    parser.add_argument('--timeframe', default='day')

    args = parser.parse_args()

    if args.strategy == 'both' and args.period == 'all':
        run_full_analysis()
    else:
        periods = {
            'train': ('2020-01-01', '2024-12-31'),
            'test': ('2025-01-01', '2025-12-11'),
            'all': ('2020-01-01', '2025-12-11')
        }
        start, end = periods[args.period]

        if args.strategy in ['v35', 'both']:
            run_backtest('v35', args.timeframe, start, end)

        if args.strategy in ['short_v1', 'both']:
            tf = 'minute240' if args.timeframe == 'day' else args.timeframe
            run_backtest('short_v1', tf, start, end)
