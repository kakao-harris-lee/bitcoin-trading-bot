#!/usr/bin/env python3
"""
v-a-05: Ultimate Quality Signal Generator
==========================================
v-a-04 개선:
1. Sideways: 4조건 강화 (RSI 20, BB 0.1, Volume 1.2x, MACD 상승)
2. Trend: ADX 12, MACD strength 50k
3. Swing: RSI 40/35 활성화

목표: 240개 → 120-150개 (품질 중심)
"""

import sys
from pathlib import Path

# 프로젝트 루트를 sys.path 최상단에 추가
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

import pandas as pd
import json
from datetime import datetime
import importlib.util

# Core 모듈
from core.data_loader import DataLoader
from core.market_analyzer import MarketAnalyzer

# v-a-05 로컬 모듈
va05_dir = Path(__file__).parent

# MarketClassifier
spec = importlib.util.spec_from_file_location(
    "market_classifier_v37",
    va05_dir / "core" / "market_classifier.py"
)
mc_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mc_module)
MarketClassifierV37 = mc_module.MarketClassifierV37

# DynamicThresholds
spec = importlib.util.spec_from_file_location(
    "dynamic_thresholds",
    va05_dir / "core" / "dynamic_thresholds.py"
)
dt_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dt_module)
DynamicThresholds = dt_module.DynamicThresholds

# Signal Extractors v05 (품질 향상)
spec = importlib.util.spec_from_file_location(
    "signal_extractors_v05",
    va05_dir / "signal_extractors_v05.py"
)
se_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(se_module)
TrendFollowingEntryCheckerV05 = se_module.TrendFollowingEntryCheckerV05
SwingTradingEntryCheckerV05 = se_module.SwingTradingEntryCheckerV05
SidewaysEntryCheckerV05 = se_module.SidewaysEntryCheckerV05
DefensiveEntryCheckerV05 = se_module.DefensiveEntryCheckerV05


class V05SignalGenerator:
    """v-a-05 시그널 생성기 (품질 중심)"""

    def __init__(self, config: dict):
        """
        Args:
            config: v37 config.json
        """
        self.config = config

        # 시장 분류기
        self.classifier = MarketClassifierV37()
        self.dynamic_thresholds = DynamicThresholds(config)

        # 4종 무상태 Entry Checker v05
        self.trend_checker = TrendFollowingEntryCheckerV05(config)
        self.swing_checker = SwingTradingEntryCheckerV05(config)
        self.sideways_checker = SidewaysEntryCheckerV05(config)
        self.defensive_checker = DefensiveEntryCheckerV05(config)

        # 전략 매핑
        self.strategy_map = {
            'BULL_STRONG': ('trend_following', self.trend_checker.check_entry),
            'BULL_MODERATE': ('swing_trading', self.swing_checker.check_entry),
            'SIDEWAYS': ('sideways', self.sideways_checker.check_entry),
            'BEAR_MODERATE': ('defensive', self.defensive_checker.check_entry),
            'BEAR_STRONG': ('defensive', self.defensive_checker.check_entry),
            'UNKNOWN': ('sideways', self.sideways_checker.check_entry)
        }

    def generate_signals(self, df: pd.DataFrame, year: int) -> pd.DataFrame:
        """
        v-a-05 방식 시그널 생성 (품질 중심)

        Args:
            df: 지표 포함 시장 데이터
            year: 연도 (통계용)

        Returns:
            시그널 DataFrame
        """
        signals = []
        market_states = []

        for i in range(30, len(df)):
            row = df.iloc[i]
            prev_row = df.iloc[i-1] if i > 0 else None
            df_recent = df.iloc[max(0, i-60):i+1]

            # 1. 시장 분류
            market_state = self.classifier.classify_market_state(
                current_row=row,
                prev_row=prev_row,
                df_recent=df_recent
            )

            market_states.append({
                'timestamp': row['timestamp'],
                'market_state': market_state
            })

            # 2. 모든 전략 Entry 조건 체크 (우선순위 순서)
            # 핵심: MACD 골든크로스는 BULL_STRONG 전환 전에 발생하므로,
            #       시장 분류와 무관하게 모든 Entry 조건을 체크해야 함

            signal = None

            # Trend Following (MACD GC + ADX >= 16) - 최우선
            trend_signal = self.trend_checker.check_entry(row, prev_row)
            if trend_signal:
                signal = trend_signal
                signal['market_state'] = market_state

            # Swing Trading (RSI < 33 + MACD GC)
            if signal is None:
                swing_signal = self.swing_checker.check_entry(row, prev_row)
                if swing_signal:
                    signal = swing_signal
                    signal['market_state'] = market_state

            # Sideways (RSI+BB, Stoch, Volume)
            if signal is None:
                sideways_signal = self.sideways_checker.check_entry(row, prev_row, df_recent)
                if sideways_signal:
                    signal = sideways_signal
                    signal['market_state'] = market_state

            # Defensive (극단 RSI) - 최후
            if signal is None:
                defensive_signal = self.defensive_checker.check_entry(row, market_state)
                if defensive_signal:
                    signal = defensive_signal
                    signal['market_state'] = market_state

            # 3. BUY 시그널 저장
            if signal is not None:
                signals.append({
                    'timestamp': row['timestamp'],
                    'entry_price': row['close'],
                    'market_state': signal.get('market_state', market_state),
                    'strategy': signal.get('strategy', 'unknown'),
                    'reason': signal.get('reason', ''),
                    'fraction': signal.get('fraction', 0.5),
                    'rsi': row.get('rsi', 50),
                    'macd': row.get('macd', 0),
                    'macd_signal': row.get('macd_signal', 0),
                    'adx': row.get('adx', 0),
                    'bb_position': row.get('bb_position', 0.5),
                    'stoch_k': row.get('stoch_k', 50),
                    'volume_ratio': row.get('volume') / df_recent['volume'].mean() if len(df_recent) > 0 else 1.0
                })

        return pd.DataFrame(signals), pd.DataFrame(market_states)


def main():
    """메인 실행"""

    # v-a-04 config 로드 (v37 복사본)
    config_path = Path(__file__).parent / 'config.json'
    with open(config_path, 'r', encoding='utf-8') as f:
        config = json.load(f)

    # 타임프레임/연도 설정
    TIMEFRAME = config.get('timeframe', 'day')
    YEARS = [2020, 2021, 2022, 2023, 2024, 2025]

    print("="*70)
    print("  v-a-05: Ultimate Quality Signal Generator")
    print("="*70)
    print(f"  Timeframe: {TIMEFRAME}")
    print(f"  Years: {YEARS}")
    print()

    # 데이터 로드
    db_path = Path(__file__).parent.parent.parent / 'upbit_bitcoin.db'

    # 연도별 시그널 생성
    all_results = {}

    for year in YEARS:
        print(f"\n{'='*70}")
        print(f"  {year}년 시그널 생성")
        print(f"{'='*70}")

        start_date = f"{year}-01-01"
        end_date = f"{year}-12-31"

        # 데이터 로드
        with DataLoader(str(db_path)) as loader:
            df = loader.load_timeframe(
                timeframe=TIMEFRAME,
                start_date=start_date,
                end_date=end_date
            )

        if df is None or len(df) == 0:
            print(f"  ❌ {year}년 데이터 없음")
            continue

        # 지표 추가
        df = MarketAnalyzer.add_indicators(
            df,
            indicators=['rsi', 'macd', 'adx', 'atr', 'bb', 'stoch', 'mfi']
        )

        print(f"  기간: {df.iloc[0]['timestamp']} ~ {df.iloc[-1]['timestamp']}")
        print(f"  캔들: {len(df)}개")

        # 시그널 생성
        generator = V05SignalGenerator(config)
        signals_df, market_states_df = generator.generate_signals(df, year)

        print(f"\n  생성된 시그널: {len(signals_df)}개")

        if len(signals_df) > 0:
            # 전략별 분포
            strategy_dist = signals_df['strategy'].value_counts().to_dict()
            print(f"\n  전략별 분포:")
            for strategy, count in strategy_dist.items():
                print(f"    {strategy}: {count}개")

            # 시장 상태별 분포
            market_dist = signals_df['market_state'].value_counts().to_dict()
            print(f"\n  시장 상태별 분포:")
            for state, count in market_dist.items():
                print(f"    {state}: {count}개")

        # 시그널 저장 (JSON)
        output_dir = Path(__file__).parent / 'signals'
        output_dir.mkdir(exist_ok=True)

        output_file = output_dir / f'{TIMEFRAME}_{year}_signals.json'

        # JSON 형식
        signals_json = {
            'strategy': 'v-a-05',
            'version': '1.0',
            'description': 'Ultimate Quality Signal Generator',
            'timeframe': TIMEFRAME,
            'year': year,
            'total_signals': len(signals_df),
            'market_distribution': market_dist if len(signals_df) > 0 else {},
            'signals': []
        }

        for _, row in signals_df.iterrows():
            signals_json['signals'].append({
                'timestamp': row['timestamp'].isoformat(),
                'entry_price': float(row['entry_price']),
                'market_state': row['market_state'],
                'strategy': row['strategy'],
                'reason': row['reason'],
                'fraction': float(row['fraction']),
                'rsi': float(row['rsi']),
                'macd': float(row['macd']),
                'macd_signal': float(row['macd_signal']),
                'adx': float(row['adx']),
                'bb_position': float(row['bb_position']),
                'stoch_k': float(row['stoch_k']),
                'volume_ratio': float(row['volume_ratio'])
            })

        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(signals_json, f, indent=2, ensure_ascii=False)

        print(f"\n  ✅ 저장: {output_file}")

        # 시장 상태 저장 (분석용)
        market_csv = output_dir / f'{TIMEFRAME}_{year}_market_states.csv'
        market_states_df.to_csv(market_csv, index=False, encoding='utf-8')
        print(f"  ✅ 시장 상태: {market_csv}")

        all_results[year] = {
            'signals': len(signals_df),
            'strategy_dist': strategy_dist if len(signals_df) > 0 else {},
            'market_dist': market_dist if len(signals_df) > 0 else {}
        }

    # 종합 요약
    print(f"\n{'='*70}")
    print(f"  시그널 생성 완료!")
    print(f"{'='*70}\n")

    print("[연도별 요약]")
    print(f"{'연도':>6s} | {'시그널':>8s} | {'Trend':>7s} | {'Swing':>7s} | {'Sideways':>9s} | {'Defensive':>10s}")
    print("-"*70)

    for year, result in all_results.items():
        dist = result['strategy_dist']
        print(f"{year:>6d} | {result['signals']:>7d}개 | "
              f"{dist.get('trend_following', 0):>6d}개 | "
              f"{dist.get('swing_trading', 0):>6d}개 | "
              f"{dist.get('sideways', 0):>8d}개 | "
              f"{dist.get('defensive', 0):>9d}개")

    print(f"\n다음 단계:")
    print(f"  1. python strategies/v-a-04/backtest.py (백테스팅)")
    print(f"  2. v37 결과와 비교")
    print(f"  3. 개선 방향 도출")
    print()


if __name__ == '__main__':
    main()
