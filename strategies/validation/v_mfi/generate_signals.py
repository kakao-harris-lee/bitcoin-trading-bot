#!/usr/bin/env python3
"""
v_mfi: MFI 과매도 전략
======================
시그널 조건: MFI < 30
타임프레임: minute60
목적: Confidence-based Position 검증
"""

import sqlite3
import json
from datetime import datetime
from pathlib import Path
import pandas as pd


def calculate_mfi(df, period=14):
    """MFI 계산"""
    typical_price = (df['high'] + df['low'] + df['close']) / 3
    money_flow = typical_price * df['volume']

    delta = typical_price.diff()
    positive_flow = money_flow.where(delta > 0, 0).rolling(window=period).sum()
    negative_flow = money_flow.where(delta < 0, 0).rolling(window=period).sum()

    mfr = positive_flow / negative_flow
    mfi = 100 - (100 / (1 + mfr))
    return mfi


def generate_signals_for_year(year: int):
    """연도별 시그널 생성"""

    db_path = Path('upbit_bitcoin.db')
    conn = sqlite3.connect(db_path)

    query = f"""
        SELECT timestamp,
               opening_price as open,
               high_price as high,
               low_price as low,
               trade_price as close,
               candle_acc_trade_volume as volume
        FROM bitcoin_minute60
        WHERE strftime('%Y', timestamp) = '{year}'
        ORDER BY timestamp ASC
    """

    df = pd.read_sql_query(query, conn)
    conn.close()

    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df['mfi'] = calculate_mfi(df, period=14)

    signals = []

    for idx, row in df.iterrows():
        if pd.notna(row['mfi']) and row['mfi'] < 30:
            signal = {
                "timestamp": row['timestamp'].strftime('%Y-%m-%d %H:%M:%S'),
                "action": "BUY",
                "price": int(row['close']),
                "score": round(30 - row['mfi'], 2),
                "confidence": round((30 - row['mfi']) / 30 * 0.9, 2),  # 최대 0.9
                "metadata": {
                    "mfi": round(row['mfi'], 2),
                    "indicator": "MFI_OVERSOLD"
                }
            }
            signals.append(signal)

    return signals


def main():
    """메인 함수"""

    print("=" * 60)
    print("v_mfi: MFI 과매도 시그널 생성")
    print("=" * 60)

    output_dir = Path('strategies/validation/v_mfi/signals')
    output_dir.mkdir(parents=True, exist_ok=True)

    year = 2024
    print(f"\n[{year}] 시그널 생성 중...")

    signals = generate_signals_for_year(year)

    output = {
        "metadata": {
            "strategy": "v_mfi",
            "version": "1.0",
            "timeframe": "minute60",
            "generated_at": datetime.now().isoformat(),
            "description": "MFI oversold strategy (MFI < 30)",
            "statistics": {
                "total_signals": len(signals),
                "period_start": f"{year}-01-01",
                "period_end": f"{year}-12-31",
                "avg_score": round(sum(s['score'] for s in signals) / len(signals), 2) if signals else 0
            }
        },
        "signals": signals
    }

    output_file = output_dir / f'{year}_signals.json'
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"  ✓ {len(signals)}개 시그널 생성")
    print(f"  ✓ 저장: {output_file}")

    if signals:
        confidences = [s['confidence'] for s in signals]
        print(f"\n[통계]")
        print(f"  평균 신뢰도: {sum(confidences)/len(confidences):.2f}")

    print("\n✅ 완료!")


if __name__ == '__main__':
    main()
