#!/usr/bin/env python3
"""v-a-14 BULL Trend 전략 분석"""

import json
from pathlib import Path

def analyze_bull_trend_performance():
    """BULL Trend 전략만 분리 분석"""

    result_file = Path(__file__).parent / 'results' / 'backtest_v37_style.json'

    with open(result_file, 'r') as f:
        data = json.load(f)

    print("="*70)
    print("  v-a-14 BULL Trend 전략 분석")
    print("="*70)

    results = data.get('results', {})

    for year, year_data in sorted(results.items()):
        trades = year_data.get('trades', [])

        # BULL Trend 거래만 필터
        bull_trades = [t for t in trades if t['strategy'] == 'bull_trend']

        if not bull_trades:
            continue

        # 통계 계산
        total = len(bull_trades)
        wins = [t for t in bull_trades if t['profit_pct'] > 0]
        losses = [t for t in bull_trades if t['profit_pct'] <= 0]

        win_rate = len(wins) / total if total > 0 else 0
        avg_profit = sum(t['profit_pct'] for t in bull_trades) / total if total > 0 else 0
        avg_win = sum(t['profit_pct'] for t in wins) / len(wins) if wins else 0
        avg_loss = sum(t['profit_pct'] for t in losses) / len(losses) if losses else 0

        # 청산 사유 분석
        exit_reasons = {}
        for t in bull_trades:
            reason = t['exit_reason']
            exit_reasons[reason] = exit_reasons.get(reason, 0) + 1

        print(f"\n[{year}년] BULL Trend 거래: {total}개")
        print(f"  승률: {win_rate*100:.1f}% ({len(wins)}승/{len(losses)}패)")
        print(f"  평균 수익: {avg_profit:.2f}%")
        print(f"  평균 익절: {avg_win:.2f}%")
        print(f"  평균 손절: {avg_loss:.2f}%")
        print(f"  청산 사유:")
        for reason, count in sorted(exit_reasons.items(), key=lambda x: -x[1]):
            pct = count / total * 100
            print(f"    {reason}: {count}회 ({pct:.1f}%)")

    # 전체 BULL Trend 통계
    print("\n" + "="*70)
    print("  전체 BULL Trend 통계 (2020-2025)")
    print("="*70)

    all_bull_trades = []
    for year, year_data in results.items():
        trades = year_data.get('trades', [])
        all_bull_trades.extend([t for t in trades if t['strategy'] == 'bull_trend'])

    total = len(all_bull_trades)
    wins = [t for t in all_bull_trades if t['profit_pct'] > 0]
    losses = [t for t in all_bull_trades if t['profit_pct'] <= 0]

    print(f"\n총 거래: {total}개")
    print(f"승률: {len(wins)/total*100:.1f}% ({len(wins)}승/{len(losses)}패)")
    print(f"평균 수익: {sum(t['profit_pct'] for t in all_bull_trades)/total:.2f}%")
    print(f"평균 익절: {sum(t['profit_pct'] for t in wins)/len(wins):.2f}%")
    print(f"평균 손절: {sum(t['profit_pct'] for t in losses)/len(losses):.2f}%")

    # TP 도달률
    tp1_count = sum(1 for t in all_bull_trades if 'TP1' in t['exit_reason'])
    tp2_count = sum(1 for t in all_bull_trades if 'TP2' in t['exit_reason'])
    tp3_count = sum(1 for t in all_bull_trades if 'TP3' in t['exit_reason'])
    sl_count = sum(1 for t in all_bull_trades if 'STOP_LOSS' in t['exit_reason'])
    trailing_count = sum(1 for t in all_bull_trades if 'TRAILING' in t['exit_reason'])
    timeout_count = sum(1 for t in all_bull_trades if 'TIMEOUT' in t['exit_reason'])

    print(f"\n청산 사유 분포:")
    print(f"  TP1 (8%): {tp1_count}회 ({tp1_count/total*100:.1f}%)")
    print(f"  TP2 (15%): {tp2_count}회 ({tp2_count/total*100:.1f}%)")
    print(f"  TP3 (25%): {tp3_count}회 ({tp3_count/total*100:.1f}%)")
    print(f"  Stop Loss (-5%): {sl_count}회 ({sl_count/total*100:.1f}%)")
    print(f"  Trailing Stop: {trailing_count}회 ({trailing_count/total*100:.1f}%)")
    print(f"  Timeout (40일): {timeout_count}회 ({timeout_count/total*100:.1f}%)")

    # 최적화 제안
    print("\n" + "="*70)
    print("  최적화 제안")
    print("="*70)

    if tp1_count > tp2_count + tp3_count:
        print("\n⚠️ TP1(8%)에서 대부분 청산")
        print("  → TP1을 낮추거나 (6-7%), Trailing Stop 강화 필요")

    if sl_count > total * 0.3:
        print("\n⚠️ Stop Loss 과다 (30% 이상)")
        print("  → Entry 조건 강화 or SL 완화 필요")

    if timeout_count > total * 0.2:
        print("\n⚠️ Timeout 과다 (20% 이상)")
        print("  → 보유 기간 단축 or Trailing 강화 필요")

if __name__ == '__main__':
    analyze_bull_trend_performance()
