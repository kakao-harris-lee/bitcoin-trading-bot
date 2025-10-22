#!/usr/bin/env python3
"""
v43 버그 검증 스크립트
- 버그 있는 원본: position = capital / buy_cost
- 수정 버전: btc_amount = (capital - fee) / price
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../strategies/v42_ultimate_scalping/core'))

from standard_compound_engine import StandardCompoundEngine
from data_loader import MultiTimeframeDataLoader
from score_engine import UnifiedScoreEngine
import json
import pandas as pd
from datetime import datetime


def load_v43_config():
    """v43 config 로드"""
    config_path = '../strategies/v43_supreme_scalping/config/v41_replica_config.json'
    with open(config_path) as f:
        return json.load(f)


def load_v42_config():
    """v42 config 로드 (score_engine용)"""
    config_path = '../strategies/v42_ultimate_scalping/config/base_config.json'
    with open(config_path) as f:
        return json.load(f)


def run_corrected_v43_backtest(year=2024, timeframe='day', min_score=25):
    """
    v43 수정 버전 백테스트

    Args:
        year: 백테스트 연도
        timeframe: 타임프레임
        min_score: 최소 점수

    Returns:
        결과 딕셔너리
    """

    print(f"\n{'='*80}")
    print(f"v43 수정 버전 백테스트: {year}년 {timeframe} (Score >= {min_score})")
    print(f"{'='*80}\n")

    # 설정 로드
    v43_config = load_v43_config()
    v42_config = load_v42_config()

    # 데이터 로더 & 점수 엔진
    data_loader = MultiTimeframeDataLoader()
    score_engine = UnifiedScoreEngine(v42_config)

    # 데이터 로드
    start_date = f"{year}-01-01"
    end_date = f"{year}-12-31"

    data = data_loader.load_all_timeframes(start_date, end_date)
    scored_data = score_engine.score_all_timeframes(data)

    # 타임프레임 데이터
    df = scored_data.get(timeframe)
    if df is None or len(df) == 0:
        print(f"[{timeframe}] 데이터 없음")
        return None

    # S-Tier, Score >= min_score 필터링
    signals = df[(df['tier'] == 'S') & (df['score'] >= min_score)].copy()

    print(f"S-Tier 시그널: {len(signals)}개 (Score >= {min_score})\n")

    if len(signals) == 0:
        print("시그널 없음")
        return None

    # ✅ 표준 복리 엔진 사용
    engine = StandardCompoundEngine(
        initial_capital=v43_config['backtest']['initial_capital'],
        fee_rate=v43_config['backtest']['fee_rate'],
        slippage=v43_config['backtest']['slippage']
    )

    # Exit 조건
    take_profit = v43_config['exit_conditions']['take_profit']
    stop_loss = v43_config['exit_conditions']['stop_loss']
    max_hold_hours = v43_config['exit_conditions']['max_hold_hours']

    # 백테스팅
    for idx, signal_row in signals.iterrows():
        signal_time = signal_row['timestamp']

        # 매수
        if engine.position_btc == 0:
            buy_price = signal_row['close']
            buy_idx = df[df['timestamp'] == signal_time].index[0]

            # 매수 실행
            engine.buy(str(signal_time), buy_price, fraction=1.0)

            # 청산 시점 찾기
            sell_idx = find_exit(df, buy_idx, buy_price, take_profit, stop_loss, max_hold_hours)

            if sell_idx >= 0:
                sell_row = df.iloc[sell_idx]
                sell_price = sell_row['close']
                sell_time = sell_row['timestamp']

                # 매도 실행
                engine.sell(str(sell_time), sell_price, reason='Exit Signal')

    # 미청산 포지션 처리
    if engine.position_btc > 0:
        final_row = df.iloc[-1]
        engine.sell(str(final_row['timestamp']), final_row['close'], reason='End of Period')

    # 통계 계산
    stats = engine.calculate_stats()

    # 거래 로그 출력 (최근 10개)
    engine.print_trade_log(limit=10)

    # 통계 출력
    print(f"\n{'='*80}")
    print("백테스트 결과")
    print(f"{'='*80}")
    print(f"초기 자본: {stats['initial_capital']:,.0f}원")
    print(f"최종 자본: {stats['final_capital']:,.0f}원")
    print(f"총 수익률: {stats['total_return_pct']:.2f}%")
    print(f"\n총 거래: {stats['total_trades']}회")
    print(f"승률: {stats['win_rate']:.1%}")
    print(f"Sharpe Ratio: {stats['sharpe_ratio']:.2f}")
    print(f"Max Drawdown: {stats['max_drawdown']:.2f}%")
    print(f"Profit Factor: {stats['profit_factor']:.2f}")

    return stats


def find_exit(df, buy_idx, buy_price, take_profit, stop_loss, max_hold_hours):
    """청산 시점 찾기"""
    max_idx = min(buy_idx + max_hold_hours, len(df) - 1)

    for i in range(buy_idx + 1, max_idx + 1):
        current_price = df.iloc[i]['close']
        current_return = (current_price - buy_price) / buy_price

        # 익절
        if current_return >= take_profit:
            return i

        # 손절
        if current_return <= stop_loss:
            return i

    # 시간 초과
    return max_idx


def compare_buggy_vs_corrected():
    """버그 버전 vs 수정 버전 비교"""

    print("\n" + "="*100)
    print("v43 버그 버전 vs 수정 버전 비교 (2024년)")
    print("="*100)

    # 원본 결과 로드
    original_file = '../strategies/v43_supreme_scalping/results/v43_day_score40_all_years.json'

    try:
        with open(original_file) as f:
            original_results = json.load(f)
            original_2024 = original_results.get('2024', {})
            original_return = original_2024.get('total_return_pct', 0)

        print(f"\n❌ 원본 (버그 있음): {original_return:.2f}%")
    except:
        print(f"\n⚠️  원본 결과 파일 없음: {original_file}")
        original_return = None

    # 수정 버전 실행
    print(f"\n✅ 수정 버전 실행 중...\n")
    corrected_stats = run_corrected_v43_backtest(year=2024, timeframe='day', min_score=40)

    if corrected_stats:
        corrected_return = corrected_stats['total_return_pct']

        print(f"\n{'='*100}")
        print("비교 결과")
        print(f"{'='*100}")

        if original_return:
            print(f"❌ 원본 (버그): {original_return:.2f}%")
            print(f"✅ 수정 버전: {corrected_return:.2f}%")
            print(f"차이: {original_return - corrected_return:.2f}%p")
            print(f"\n💡 원본 결과는 버그로 인해 {original_return / corrected_return:.1f}배 과대평가되었습니다.")
        else:
            print(f"✅ 수정 버전: {corrected_return:.2f}%")

        print(f"\n버그 원인:")
        print(f"  position = capital / buy_cost  # ❌ 항상 ~0.9993 BTC")
        print(f"  → btc_amount = (capital * (1 - fee)) / price  # ✅ 올바름")

        return {
            'original': original_return,
            'corrected': corrected_return,
            'corrected_stats': corrected_stats
        }

    return None


if __name__ == '__main__':
    # v43 버그 검증
    result = compare_buggy_vs_corrected()

    # 결과 저장
    if result:
        output_file = '../strategies/251020-2200_V43_BUG_VERIFICATION.json'

        save_data = {
            'verification_date': datetime.now().isoformat(),
            'strategy': 'v43_supreme_scalping',
            'bug_description': 'position = capital / buy_cost (고정 0.9993 BTC)',
            'correction': 'btc_amount = (capital * (1 - fee)) / price (동적 복리)',
            'year': 2024,
            'timeframe': 'day',
            'min_score': 40,
            'original_return_pct': result.get('original'),
            'corrected_return_pct': result.get('corrected'),
            'corrected_stats': result.get('corrected_stats')
        }

        with open(output_file, 'w') as f:
            json.dump(save_data, f, indent=2, ensure_ascii=False)

        print(f"\n✅ 검증 결과 저장: {output_file}")
