#!/usr/bin/env python3
"""
v_voting: v41 S-Tier 시그널 재사용
==================================
시그널: v41 S-Tier 2024년 결과 사용
타임프레임: day
목적: Score-based Position + Dynamic Exit 검증
"""

import json
from datetime import datetime
from pathlib import Path
import pandas as pd


def main():
    """메인 함수"""

    print("=" * 60)
    print("v_voting: v41 S-Tier 시그널 복사")
    print("=" * 60)

    # v41 S-Tier 데이터 로드
    v41_file = Path('strategies/v41_scalping_voting/analysis/tier_backtest/day_SA_tier_2025.csv')

    if not v41_file.exists():
        # 2024 파일 시도
        v41_file = Path('strategies/v41_scalping_voting/analysis/tier_backtest/day_SA_tier.csv')

    if not v41_file.exists():
        print("❌ v41 S-Tier 파일을 찾을 수 없습니다.")
        return

    df = pd.read_csv(v41_file)
    df['timestamp'] = pd.to_datetime(df['timestamp'])

    # 2024년만 필터링
    df_2024 = df[df['timestamp'].dt.year == 2024]

    # S-Tier만 필터링
    df_s = df_2024[df_2024['tier'] == 'S']

    print(f"  로드된 S-Tier 시그널: {len(df_s)}개")

    # 시그널 변환
    signals = []
    for _, row in df_s.iterrows():
        signal = {
            "timestamp": row['timestamp'].strftime('%Y-%m-%d %H:%M:%S'),
            "action": "BUY",
            "price": int(row['close']),
            "score": float(row.get('score', 25)),  # S-Tier 기본 점수 25
            "confidence": 0.85,  # S-Tier 높은 신뢰도
            "metadata": {
                "tier": "S",
                "source": "v41_scalping_voting",
                "indicator": "VOTING_ENSEMBLE"
            }
        }
        signals.append(signal)

    # JSON 저장
    output_dir = Path('strategies/validation/v_voting/signals')
    output_dir.mkdir(parents=True, exist_ok=True)

    output = {
        "metadata": {
            "strategy": "v_voting",
            "version": "1.0",
            "timeframe": "day",
            "generated_at": datetime.now().isoformat(),
            "description": "v41 S-Tier signals reused for validation",
            "statistics": {
                "total_signals": len(signals),
                "period_start": "2024-01-01",
                "period_end": "2024-12-31",
                "avg_score": round(sum(s['score'] for s in signals) / len(signals), 2) if signals else 0
            }
        },
        "signals": signals
    }

    output_file = output_dir / '2024_signals.json'
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"  ✓ {len(signals)}개 시그널 저장")
    print(f"  ✓ 저장: {output_file}")
    print("\n✅ 완료!")


if __name__ == '__main__':
    main()
