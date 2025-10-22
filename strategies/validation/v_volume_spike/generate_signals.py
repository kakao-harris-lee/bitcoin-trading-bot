#!/usr/bin/env python3
"""
v_volume_spike: 거래량 폭증 전략
================================
시그널 조건: Volume ratio > 3.0
타임프레임: minute240
목적: Timeout Exit 플러그인 검증
"""

import sqlite3
import json
from datetime import datetime
from pathlib import Path
import pandas as pd


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
        FROM bitcoin_minute240
        WHERE strftime('%Y', timestamp) = '{year}'
        ORDER BY timestamp ASC
    """

    df = pd.read_sql_query(query, conn)
    conn.close()

    df['timestamp'] = pd.to_datetime(df['timestamp'])

    # Volume ratio 계산
    df['volume_ma20'] = df['volume'].rolling(window=20).mean()
    df['volume_ratio'] = df['volume'] / df['volume_ma20']

    signals = []

    for idx, row in df.iterrows():
        if pd.notna(row['volume_ratio']) and row['volume_ratio'] > 3.0:
            signal = {
                "timestamp": row['timestamp'].strftime('%Y-%m-%d %H:%M:%S'),
                "action": "BUY",
                "price": int(row['close']),
                "score": round(row['volume_ratio'] * 10, 2),
                "confidence": min(round(row['volume_ratio'] / 5, 2), 1.0),
                "metadata": {
                    "volume_ratio": round(row['volume_ratio'], 2),
                    "indicator": "VOLUME_SPIKE"
                }
            }
            signals.append(signal)

    return signals


def main():
    """메인 함수"""

    print("=" * 60)
    print("v_volume_spike: 거래량 폭증 시그널 생성")
    print("=" * 60)

    output_dir = Path('strategies/validation/v_volume_spike/signals')
    output_dir.mkdir(parents=True, exist_ok=True)

    year = 2024
    print(f"\n[{year}] 시그널 생성 중...")

    signals = generate_signals_for_year(year)

    output = {
        "metadata": {
            "strategy": "v_volume_spike",
            "version": "1.0",
            "timeframe": "minute240",
            "generated_at": datetime.now().isoformat(),
            "description": "Volume spike strategy (volume ratio > 3.0)",
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

    print("\n✅ 완료!")


if __name__ == '__main__':
    main()
