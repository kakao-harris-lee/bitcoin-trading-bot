#!/usr/bin/env python3
"""
Short V1 Strategy 파라미터 최적화
목표: 거래 빈도 증가 + 수익성 유지

현재 문제:
- 연간 2~7회 거래 (너무 적음)
- 현금 보유 기간이 길어 자본 효율성 낮음
- Death Cross + ADX 조건이 너무 엄격

최적화 방향:
1. EMA 기간 단축 (더 빠른 반응)
2. ADX 임계값 완화
3. 추가 진입 신호 도입 (RSI 과매수, BB 이탈 등)
"""

import sys
from pathlib import Path
from itertools import product
import pandas as pd
import numpy as np
from typing import Dict, Tuple, Optional
from dataclasses import dataclass
import warnings
warnings.filterwarnings('ignore')

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


@dataclass
class BacktestResult:
    """백테스트 결과"""
    params: Dict
    total_return: float
    total_trades: int
    win_rate: float
    sharpe_ratio: float
    max_drawdown: float
    profit_factor: float
    avg_trades_per_year: float


class ShortV1StrategyOptimized:
    """최적화된 Short V1 전략"""

    def __init__(self, config: Dict):
        self.config = config
        self.in_position = False
        self.entry_price = 0.0
        self.entry_time = None
        self._cached_df = None
        self._cache_key = None

    def add_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """기술적 지표 추가"""
        df = df.copy()

        # EMA (빠른/느린)
        ema_fast = self.config.get('ema_fast', 20)
        ema_slow = self.config.get('ema_slow', 50)
        df['ema_fast'] = df['close'].ewm(span=ema_fast, adjust=False).mean()
        df['ema_slow'] = df['close'].ewm(span=ema_slow, adjust=False).mean()

        # 크로스 감지
        df['death_cross'] = (df['ema_fast'] < df['ema_slow']) & (df['ema_fast'].shift(1) >= df['ema_slow'].shift(1))
        df['golden_cross'] = (df['ema_fast'] > df['ema_slow']) & (df['ema_fast'].shift(1) <= df['ema_slow'].shift(1))

        # 추세 방향 (EMA 기울기)
        df['ema_slope'] = (df['ema_fast'] - df['ema_fast'].shift(5)) / df['ema_fast'].shift(5) * 100

        # RSI
        rsi_period = self.config.get('rsi_period', 14)
        delta = df['close'].diff()
        gain = delta.where(delta > 0, 0).rolling(rsi_period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(rsi_period).mean()
        rs = gain / loss
        df['rsi'] = 100 - (100 / (1 + rs))

        # Bollinger Bands
        bb_period = self.config.get('bb_period', 20)
        bb_std = self.config.get('bb_std', 2.0)
        df['bb_middle'] = df['close'].rolling(bb_period).mean()
        df['bb_std'] = df['close'].rolling(bb_period).std()
        df['bb_upper'] = df['bb_middle'] + bb_std * df['bb_std']
        df['bb_lower'] = df['bb_middle'] - bb_std * df['bb_std']
        df['bb_pct'] = (df['close'] - df['bb_lower']) / (df['bb_upper'] - df['bb_lower'])

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

        # 가격 모멘텀
        df['momentum'] = (df['close'] - df['close'].shift(10)) / df['close'].shift(10) * 100

        # 거래량 이상치
        df['volume_sma'] = df['volume'].rolling(20).mean()
        df['volume_ratio'] = df['volume'] / df['volume_sma']

        return df

    def check_entry_signal(self, row: pd.Series) -> Tuple[bool, str]:
        """진입 신호 확인 (다중 조건)"""
        signals = []
        entry_mode = self.config.get('entry_mode', 'multi')

        # 1. Death Cross 신호
        if self.config.get('use_death_cross', True):
            if row.get('death_cross', False):
                adx = row.get('adx', 0)
                adx_threshold = self.config.get('adx_threshold', 20)
                if adx >= adx_threshold:
                    signals.append('DEATH_CROSS')

        # 2. RSI 과매수 신호
        if self.config.get('use_rsi_overbought', True):
            rsi = row.get('rsi', 50)
            rsi_overbought = self.config.get('rsi_overbought', 70)
            if rsi >= rsi_overbought:
                # 추가 조건: 하락 추세
                ema_slope = row.get('ema_slope', 0)
                if ema_slope < 0:
                    signals.append('RSI_OVERBOUGHT')

        # 3. Bollinger Band 상단 이탈 후 복귀
        if self.config.get('use_bb_rejection', True):
            bb_pct = row.get('bb_pct', 0.5)
            bb_upper_threshold = self.config.get('bb_upper_threshold', 0.95)
            if bb_pct >= bb_upper_threshold:
                momentum = row.get('momentum', 0)
                if momentum < 0:  # 모멘텀 하락 중
                    signals.append('BB_REJECTION')

        # 4. EMA 아래에서 지속적 하락 (추세 추종)
        if self.config.get('use_trend_follow', True):
            if row.get('ema_fast', 0) < row.get('ema_slow', 0):
                ema_slope = row.get('ema_slope', 0)
                slope_threshold = self.config.get('slope_threshold', -0.5)
                minus_di = row.get('minus_di', 0)
                plus_di = row.get('plus_di', 0)
                if ema_slope < slope_threshold and minus_di > plus_di:
                    signals.append('TREND_FOLLOW')

        if entry_mode == 'any' and signals:
            return True, signals[0]
        elif entry_mode == 'multi' and len(signals) >= self.config.get('min_signals', 1):
            return True, '+'.join(signals[:2])

        return False, ''

    def execute(self, df: pd.DataFrame, i: int) -> Dict:
        """전략 실행"""
        warmup = max(self.config.get('ema_slow', 50), 50)
        if i < warmup:
            return {'action': 'hold', 'reason': 'WARMUP'}

        # 지표 계산 (캐싱)
        cache_key = (id(df), len(df))
        if self._cached_df is None or self._cache_key != cache_key:
            self._cached_df = self.add_indicators(df)
            self._cache_key = cache_key

        row = self._cached_df.iloc[i]

        # 포지션 있을 때
        if self.in_position:
            pnl_pct = (self.entry_price - row['close']) / self.entry_price * 100

            # 스탑로스
            stop_loss = self.config.get('stop_loss_pct', 2.0)
            if pnl_pct <= -stop_loss:
                self.in_position = False
                return {'action': 'close_short', 'fraction': 1.0, 'reason': f'STOP_LOSS:{pnl_pct:+.1f}%', 'pnl_pct': pnl_pct}

            # 테이크프로핏
            take_profit = self.config.get('take_profit_pct', 4.0)
            if pnl_pct >= take_profit:
                self.in_position = False
                return {'action': 'close_short', 'fraction': 1.0, 'reason': f'TAKE_PROFIT:{pnl_pct:+.1f}%', 'pnl_pct': pnl_pct}

            # 골든크로스
            if row.get('golden_cross', False):
                self.in_position = False
                return {'action': 'close_short', 'fraction': 1.0, 'reason': f'GOLDEN_CROSS:{pnl_pct:+.1f}%', 'pnl_pct': pnl_pct}

            # RSI 과매도 (청산)
            rsi = row.get('rsi', 50)
            if rsi <= self.config.get('rsi_oversold', 30):
                self.in_position = False
                return {'action': 'close_short', 'fraction': 1.0, 'reason': f'RSI_OVERSOLD:{pnl_pct:+.1f}%', 'pnl_pct': pnl_pct}

            # 시간 기반 청산
            if self.entry_time is not None:
                max_hold = self.config.get('max_hold_bars', 100)
                bars_held = i - self.entry_time
                if bars_held >= max_hold:
                    self.in_position = False
                    return {'action': 'close_short', 'fraction': 1.0, 'reason': f'TIME_EXIT:{pnl_pct:+.1f}%', 'pnl_pct': pnl_pct}

            return {'action': 'hold', 'reason': 'IN_POSITION'}

        # 포지션 없을 때: 진입 조건 확인
        should_enter, reason = self.check_entry_signal(row)
        if should_enter:
            self.in_position = True
            self.entry_price = row['close']
            self.entry_time = i
            return {
                'action': 'open_short',
                'fraction': self.config.get('position_size', 0.3),
                'reason': reason
            }

        return {'action': 'hold', 'reason': 'NO_SIGNAL'}


class QuickBacktester:
    """빠른 백테스터"""

    def __init__(self, initial_capital: float = 10_000_000, fee_rate: float = 0.0004,
                 slippage: float = 0.0002, leverage: int = 3):
        self.initial_capital = initial_capital
        self.fee_rate = fee_rate
        self.slippage = slippage
        self.leverage = leverage

    def run(self, df: pd.DataFrame, strategy) -> Dict:
        capital = self.initial_capital
        position_size = 0.0
        entry_price = 0.0
        trades = []
        equity_curve = []

        for i in range(len(df)):
            signal = strategy.execute(df, i)
            row = df.iloc[i]
            action = signal.get('action', 'hold')

            if action == 'open_short' and position_size == 0:
                fraction = signal.get('fraction', 0.3)
                margin = capital * fraction
                position_size = margin * self.leverage
                entry_price = row['close'] * (1 - self.slippage)
                fee = position_size * self.fee_rate
                capital -= margin + fee
                trades.append({'type': 'open', 'price': entry_price})

            elif action == 'close_short' and position_size > 0:
                exit_price = row['close'] * (1 + self.slippage)
                pnl_ratio = (entry_price - exit_price) / entry_price
                pnl = position_size * pnl_ratio
                fee = position_size * self.fee_rate
                margin_return = position_size / self.leverage
                capital += margin_return + pnl - fee
                trades.append({'type': 'close', 'pnl': pnl, 'pnl_pct': pnl_ratio * 100 * self.leverage})
                position_size = 0.0

            # Equity
            if position_size > 0:
                unrealized = position_size * (entry_price - row['close']) / entry_price
                equity_curve.append(capital + (position_size / self.leverage) + unrealized)
            else:
                equity_curve.append(capital)

        # 미청산 정리
        if position_size > 0:
            last_price = df.iloc[-1]['close']
            pnl = position_size * (entry_price - last_price) / entry_price
            capital += (position_size / self.leverage) + pnl

        # 메트릭 계산
        close_trades = [t for t in trades if t['type'] == 'close']
        total_return = (capital - self.initial_capital) / self.initial_capital * 100

        if not close_trades:
            return {'total_return': total_return, 'total_trades': 0, 'win_rate': 0,
                    'sharpe_ratio': 0, 'max_drawdown': 0, 'profit_factor': 0}

        profits = [t['pnl'] for t in close_trades]
        wins = [p for p in profits if p > 0]
        losses = [p for p in profits if p <= 0]
        win_rate = len(wins) / len(close_trades) * 100

        # Sharpe
        eq = pd.Series(equity_curve)
        rets = eq.pct_change().dropna()
        sharpe = rets.mean() / rets.std() * np.sqrt(252) if rets.std() > 0 else 0

        # MDD
        peak = eq.cummax()
        dd = (eq - peak) / peak * 100
        mdd = dd.min()

        # Profit Factor
        pf = sum(wins) / abs(sum(losses)) if losses and sum(losses) != 0 else 0

        return {
            'total_return': total_return,
            'total_trades': len(close_trades),
            'win_rate': win_rate,
            'sharpe_ratio': sharpe,
            'max_drawdown': mdd,
            'profit_factor': pf
        }


def load_data(start_date: str = '2020-01-01', end_date: str = '2024-12-31') -> pd.DataFrame:
    """데이터 로드 (Binance)"""
    from core.data_loader import DataLoader
    db_path = PROJECT_ROOT / 'data' / 'binance_bitcoin.db'
    loader = DataLoader(str(db_path))
    df = loader.load_binance('minute240', start_date, end_date)
    loader.conn.close()
    return df


def _normalize_config(config: Dict) -> Dict:
    """중복 제거를 위한 canonical config 생성 (사용하지 않는 파라미터 무시)."""
    normalized = dict(config)

    if not normalized.get('use_rsi_overbought', False):
        normalized.pop('rsi_overbought', None)
        normalized.pop('rsi_period', None)

    if not normalized.get('use_bb_rejection', False):
        normalized.pop('bb_upper_threshold', None)
        normalized.pop('bb_period', None)
        normalized.pop('bb_std', None)

    if not normalized.get('use_trend_follow', False):
        normalized.pop('slope_threshold', None)

    # 안정성을 위해 정렬된 키로 표현
    return normalized


def _score_result(r: BacktestResult, *, target_min_trades: float, target_max_trades: float) -> float:
    """복합 점수: 수익률 + 샤프 + 거래빈도 + MDD(페널티)."""
    trade_score: float
    if r.avg_trades_per_year < target_min_trades:
        trade_score = r.avg_trades_per_year / max(target_min_trades, 1e-9)
    elif r.avg_trades_per_year > target_max_trades:
        # 과도한 매매는 슬리피지/수수료 민감도↑라 페널티
        trade_score = max(0.0, 1.0 - (r.avg_trades_per_year - target_max_trades) / target_max_trades)
    else:
        trade_score = 1.0

    # MDD는 음수(%). -20%면 20 페널티
    mdd_penalty = abs(min(0.0, r.max_drawdown))

    # Profit factor가 1 미만이면 페널티
    pf_penalty = 0.0
    if r.profit_factor and r.profit_factor < 1.0:
        pf_penalty = (1.0 - r.profit_factor) * 10.0

    return (
        r.total_return * 0.25 +
        r.sharpe_ratio * 25.0 +
        trade_score * 15.0 -
        mdd_penalty * 0.8 -
        pf_penalty
    )


def test_single_config(args) -> BacktestResult:
    """단일 설정 테스트"""
    config, df = args
    strategy = ShortV1StrategyOptimized(config)
    backtester = QuickBacktester(leverage=config.get('leverage', 3))
    result = backtester.run(df, strategy)

    years = len(df) / (365 * 6)  # 4시간봉 기준
    avg_trades = result['total_trades'] / years if years > 0 else 0

    return BacktestResult(
        params=config,
        total_return=result['total_return'],
        total_trades=result['total_trades'],
        win_rate=result['win_rate'],
        sharpe_ratio=result['sharpe_ratio'],
        max_drawdown=result['max_drawdown'],
        profit_factor=result['profit_factor'],
        avg_trades_per_year=avg_trades
    )


def run_grid_search(
    *,
    train_start: str = '2020-01-01',
    train_end: str = '2024-12-31',
    oos_start: str = '2025-01-01',
    oos_end: str = '2025-12-11',
    leverage: int = 3,
    min_trades_per_year: float = 12.0,
    max_trades_per_year: float = 90.0,
    max_mdd: float = -25.0,
    min_sharpe: float = 0.0,
    top_n_oos: int = 15,
):
    """그리드 서치 최적화"""
    print("=" * 80)
    print("🔍 Short V1 파라미터 최적화 (Grid Search)")
    print("=" * 80)

    # 데이터 로드 (Train)
    print("\n📥 데이터 로드 중...")
    df = load_data(train_start, train_end)
    print(f"   ✅ Train: {train_start}~{train_end} | {len(df):,}개 캔들")

    # 파라미터 그리드
    param_grid = {
        'ema_fast': [10, 20, 30],
        'ema_slow': [50, 100],
        'adx_threshold': [15, 20, 25],
        'stop_loss_pct': [1.5, 2.0, 2.5],
        'take_profit_pct': [3.0, 4.0, 5.0],

        # 엔트리 시그널 토글
        'entry_mode': ['any'],
        'min_signals': [1],
        'use_death_cross': [True],
        'use_rsi_overbought': [False, True],
        'use_bb_rejection': [True, False],
        'use_trend_follow': [True],

        # RSI/BB 파라미터 (사용 시에만 의미)
        'rsi_overbought': [70, 75],
        'rsi_oversold': [25, 30],
        'bb_upper_threshold': [0.93, 0.95],

        # 실행
        'position_size': [0.3],
        'leverage': [leverage],
        'max_hold_bars': [50, 100],
        'slope_threshold': [-0.5],
    }

    # 모든 조합 생성
    keys = list(param_grid.keys())
    values = list(param_grid.values())
    all_configs = [dict(zip(keys, v)) for v in product(*values)]

    # 필터: 최소 하나의 진입 신호는 활성화
    valid_configs = []
    for c in all_configs:
        active_signals = sum([
            c.get('use_death_cross', False),
            c.get('use_rsi_overbought', False),
            c.get('use_bb_rejection', False),
            c.get('use_trend_follow', False)
        ])
        if active_signals >= 1:
            valid_configs.append(c)

    # normalize로 실질 중복 제거
    dedup: Dict[Tuple[Tuple[str, object], ...], Dict] = {}
    for c in valid_configs:
        nc = _normalize_config(c)
        sig = tuple(sorted(nc.items()))
        dedup[sig] = nc
    configs = list(dedup.values())

    print(f"\n🧪 테스트할 조합: {len(valid_configs):,}개 → 중복 제거 후 {len(configs):,}개")
    print(f"   제약: 연평균 거래 {min_trades_per_year:.0f}~{max_trades_per_year:.0f}회 | Sharpe≥{min_sharpe:.2f} | MDD≥{max_mdd:.1f}%")

    # 테스트 실행
    results = []
    total = len(configs)

    print("\n⏳ 최적화 진행 중...")
    for idx, config in enumerate(configs):
        if idx % 100 == 0:
            print(f"   진행: {idx}/{total} ({idx/total*100:.1f}%)")

        result = test_single_config((config, df))

        # hard constraints
        if result.avg_trades_per_year < min_trades_per_year:
            continue
        if result.avg_trades_per_year > max_trades_per_year:
            continue
        if result.sharpe_ratio < min_sharpe:
            continue
        if result.max_drawdown < max_mdd:  # 더 큰 하락(더 음수)면 제외
            continue

        results.append(result)

    if not results:
        print("\n❌ 제약 조건을 만족하는 조합이 없습니다. 제약을 완화해 주세요.")
        return None

    results.sort(
        key=lambda r: _score_result(r, target_min_trades=min_trades_per_year, target_max_trades=max_trades_per_year),
        reverse=True,
    )

    # 결과 중 실질 중복 제거 (출력/후속검증용)
    unique_results: list[BacktestResult] = []
    seen: set[Tuple[Tuple[str, object], ...]] = set()
    for r in results:
        sig = tuple(sorted(_normalize_config(r.params).items()))
        if sig in seen:
            continue
        seen.add(sig)
        unique_results.append(r)

    # Top 20 출력
    print("\n" + "=" * 100)
    print("🏆 Top 20 파라미터 조합")
    print("=" * 100)
    print(f"{'순위':>4} {'수익률':>10} {'거래/년':>10} {'승률':>8} {'Sharpe':>8} {'MDD':>10} {'PF':>8} | 주요 파라미터")
    print("-" * 100)

    for i, r in enumerate(unique_results[:20]):
        params_str = (
            f"EMA({r.params['ema_fast']}/{r.params['ema_slow']}) "
            f"ADX>{r.params['adx_threshold']} "
            f"SL{r.params['stop_loss_pct']}% TP{r.params['take_profit_pct']}% "
            f"BBthr={r.params.get('bb_upper_threshold', 'NA')} "
            f"RSIob={r.params.get('rsi_overbought', 'NA')} "
            f"Signals:DC={r.params.get('use_death_cross')} "
            f"RSI={r.params.get('use_rsi_overbought')} "
            f"BB={r.params.get('use_bb_rejection')} "
            f"TREND={r.params.get('use_trend_follow')}"
        )

        print(
            f"{i+1:>4} {r.total_return:>+9.2f}% {r.avg_trades_per_year:>9.1f}회 "
            f"{r.win_rate:>7.1f}% {r.sharpe_ratio:>7.2f} {r.max_drawdown:>9.2f}% "
            f"{r.profit_factor:>7.2f} | {params_str}"
        )

    # 최적 파라미터 저장
    best = unique_results[0]
    print("\n" + "=" * 80)
    print("🥇 최적 파라미터")
    print("=" * 80)
    for k, v in best.params.items():
        print(f"   {k}: {v}")

    print(f"\n📊 성과:")
    print(f"   수익률: {best.total_return:+.2f}%")
    print(f"   연평균 거래: {best.avg_trades_per_year:.1f}회")
    print(f"   승률: {best.win_rate:.1f}%")
    print(f"   Sharpe: {best.sharpe_ratio:.2f}")
    print(f"   MDD: {best.max_drawdown:.2f}%")

    # 상위 N개 OOS(2025) 포함 연도별 검증
    print("\n" + "=" * 80)
    print(f"📅 Top {top_n_oos} 후보 연도별 검증 (Train 2020-2024 + OOS 2025)")
    print("=" * 80)

    years = ['2020', '2021', '2022', '2023', '2024']
    oos_label = f"2025(OOS:{oos_start}~{oos_end})"

    candidates = unique_results[:top_n_oos]
    year_dfs = {y: load_data(f'{y}-01-01', f'{y}-12-31') for y in years}
    oos_df = load_data(oos_start, oos_end)

    backtester = QuickBacktester(leverage=leverage)

    def summarize_candidate(rank: int, r: BacktestResult) -> None:
        cfg = r.params
        strategy = ShortV1StrategyOptimized(cfg)
        train_summary = f"Train {r.total_return:+.1f}% | {r.avg_trades_per_year:.0f}/y | Sharpe {r.sharpe_ratio:.2f} | MDD {r.max_drawdown:.1f}%"

        per_year = []
        for y in years:
            res = backtester.run(year_dfs[y], strategy)
            per_year.append((y, res['total_return'], res['total_trades']))
        oos_res = backtester.run(oos_df, strategy)

        worst_year = min(per_year, key=lambda x: x[1])
        print(f"\n#{rank} {train_summary}")
        print(f"   OOS {oos_label}: {oos_res['total_return']:+.2f}% | 거래 {oos_res['total_trades']}회 | Sharpe {oos_res['sharpe_ratio']:.2f} | MDD {oos_res['max_drawdown']:.2f}%")
        print(f"   Worst year: {worst_year[0]} {worst_year[1]:+.2f}% (trades {worst_year[2]})")
        print(f"   Params: EMA({cfg.get('ema_fast')}/{cfg.get('ema_slow')}) ADX>{cfg.get('adx_threshold')} SL{cfg.get('stop_loss_pct')}% TP{cfg.get('take_profit_pct')}% "
              f"Signals: DC={cfg.get('use_death_cross')} RSI={cfg.get('use_rsi_overbought')} BB={cfg.get('use_bb_rejection')} TREND={cfg.get('use_trend_follow')}")

    for idx, r in enumerate(candidates, start=1):
        summarize_candidate(idx, r)

    return best


def compare_strategies():
    """기존 vs 최적화 전략 비교"""
    print("\n" + "=" * 80)
    print("📊 기존 vs 최적화 전략 비교")
    print("=" * 80)

    df = load_data('2020-01-01', '2024-12-31')

    # 기존 전략
    old_config = {
        'ema_fast': 50,
        'ema_slow': 200,
        'adx_threshold': 25,
        'stop_loss_pct': 2.0,
        'take_profit_pct': 5.0,
        'use_death_cross': True,
        'use_rsi_overbought': False,
        'use_bb_rejection': False,
        'use_trend_follow': False,
        'entry_mode': 'any',
        'min_signals': 1,
        'position_size': 0.3,
        'leverage': 3,
        'max_hold_bars': 100,
        'rsi_overbought': 70,
        'rsi_oversold': 30,
    }

    # 최적화 전략 (사전 테스트 결과 기반)
    new_config = {
        'ema_fast': 20,
        'ema_slow': 50,
        'adx_threshold': 15,
        'stop_loss_pct': 2.0,
        'take_profit_pct': 4.0,
        'use_death_cross': True,
        'use_rsi_overbought': True,
        'use_bb_rejection': True,
        'use_trend_follow': True,
        'entry_mode': 'any',
        'min_signals': 1,
        'position_size': 0.3,
        'leverage': 3,
        'max_hold_bars': 50,
        'rsi_overbought': 70,
        'rsi_oversold': 30,
        'bb_upper_threshold': 0.95,
        'slope_threshold': -0.5,
    }

    print(f"\n{'항목':<20} {'기존 전략':>15} {'최적화 전략':>15}")
    print("-" * 50)
    print(f"{'EMA Fast':<20} {old_config['ema_fast']:>15} {new_config['ema_fast']:>15}")
    print(f"{'EMA Slow':<20} {old_config['ema_slow']:>15} {new_config['ema_slow']:>15}")
    print(f"{'ADX Threshold':<20} {old_config['adx_threshold']:>15} {new_config['adx_threshold']:>15}")
    print(f"{'RSI 과매수':<20} {'❌':>15} {'✅':>15}")
    print(f"{'BB Rejection':<20} {'❌':>15} {'✅':>15}")
    print(f"{'Trend Follow':<20} {'❌':>15} {'✅':>15}")

    # 백테스트
    backtester = QuickBacktester(leverage=3)

    old_strategy = ShortV1StrategyOptimized(old_config)
    old_result = backtester.run(df, old_strategy)

    new_strategy = ShortV1StrategyOptimized(new_config)
    new_result = backtester.run(df, new_strategy)

    years = len(df) / (365 * 6)

    print(f"\n{'성과 비교':<20} {'기존':>15} {'최적화':>15} {'개선':>15}")
    print("-" * 65)
    print(f"{'수익률':<20} {old_result['total_return']:>+14.2f}% {new_result['total_return']:>+14.2f}% "
          f"{new_result['total_return'] - old_result['total_return']:>+14.2f}%p")
    print(f"{'총 거래':<20} {old_result['total_trades']:>14}회 {new_result['total_trades']:>14}회 "
          f"{new_result['total_trades'] - old_result['total_trades']:>+14}회")
    print(f"{'연평균 거래':<20} {old_result['total_trades']/years:>13.1f}회 {new_result['total_trades']/years:>13.1f}회")
    print(f"{'승률':<20} {old_result['win_rate']:>14.1f}% {new_result['win_rate']:>14.1f}%")
    print(f"{'Sharpe':<20} {old_result['sharpe_ratio']:>15.2f} {new_result['sharpe_ratio']:>15.2f}")
    print(f"{'MDD':<20} {old_result['max_drawdown']:>14.2f}% {new_result['max_drawdown']:>14.2f}%")

    return new_config


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument('--mode', choices=['grid', 'compare'], default='compare')
    parser.add_argument('--min-trades-per-year', type=float, default=12.0)
    parser.add_argument('--max-trades-per-year', type=float, default=90.0)
    parser.add_argument('--max-mdd', type=float, default=-25.0, help='예: -25 (=-25% 이내만 통과)')
    parser.add_argument('--min-sharpe', type=float, default=0.0)
    parser.add_argument('--leverage', type=int, default=3)
    parser.add_argument('--train-start', default='2020-01-01')
    parser.add_argument('--train-end', default='2024-12-31')
    parser.add_argument('--oos-start', default='2025-01-01')
    parser.add_argument('--oos-end', default='2025-12-11')
    parser.add_argument('--top-n-oos', type=int, default=10)
    args = parser.parse_args()

    if args.mode == 'grid':
        run_grid_search(
            train_start=args.train_start,
            train_end=args.train_end,
            oos_start=args.oos_start,
            oos_end=args.oos_end,
            leverage=args.leverage,
            min_trades_per_year=args.min_trades_per_year,
            max_trades_per_year=args.max_trades_per_year,
            max_mdd=args.max_mdd,
            min_sharpe=args.min_sharpe,
            top_n_oos=args.top_n_oos,
        )
    else:
        compare_strategies()
