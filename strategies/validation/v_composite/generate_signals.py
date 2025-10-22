#!/usr/bin/env python3
"""
v_composite: 복합 전략
======================
시그널 조건: RSI < 35 AND MFI > 50 (역발산)
타임프레임: day
목적: Composite Exit (Fixed + Trailing + Timeout) 검증
"""

import sqlite3
import json
from datetime import datetime
from pathlib import Path
import pandas as pd


def calculate_rsi(df, period=14):
    """RSI 계산"""
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    return rsi


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
        FROM bitcoin_day
        WHERE strftime('%Y', timestamp) = '{year}'
        ORDER BY timestamp ASC
    """

    df = pd.read_sql_query(query, conn)
    conn.close()

    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df['rsi'] = calculate_rsi(df, period=14)
    df['mfi'] = calculate_mfi(df, period=14)

    signals = []

    for idx, row in df.iterrows():
        # RSI < 35 AND MFI > 50 (역발산: 가격은 하락하지만 자금은 유입)
        if (pd.notna(row['rsi']) and pd.notna(row['mfi']) and
            row['rsi'] < 35 and row['mfi'] > 50):

            # Tier 분류 (RSI + MFI 조합)
            combined_score = (35 - row['rsi']) + (row['mfi'] - 50)

            if combined_score >= 30:
                tier = 'S'
            elif combined_score >= 20:
                tier = 'A'
            else:
                tier = 'B'

            signal = {
                "timestamp": row['timestamp'].strftime('%Y-%m-%d %H:%M:%S'),
                "action": "BUY",
                "price": int(row['close']),
                "score": round(combined_score, 2),
                "confidence": min(round(combined_score / 40, 2), 1.0),
                "metadata": {
                    "rsi": round(row['rsi'], 2),
                    "mfi": round(row['mfi'], 2),
                    "tier": tier,
                    "indicator": "RSI_MFI_DIVERGENCE"
                }
            }
            signals.append(signal)

    return signals


def main():
    """메인 함수"""

    print("=" * 60)
    print("v_composite: 복합 전략 시그널 생성")
    print("=" * 60)

    output_dir = Path('strategies/validation/v_composite/signals')
    output_dir.mkdir(parents=True, exist_ok=True)

    year = 2024
    print(f"\n[{year}] 시그널 생성 중...")

    signals = generate_signals_for_year(year)

    output = {
        "metadata": {
            "strategy": "v_composite",
            "version": "1.0",
            "timeframe": "day",
            "generated_at": datetime.now().isoformat(),
            "description": "Composite strategy (RSI < 35 AND MFI > 50 divergence)",
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
        tiers = [s['metadata']['tier'] for s in signals]
        print(f"\n[통계]")
        print(f"  S-Tier: {tiers.count('S')}개")
        print(f"  A-Tier: {tiers.count('A')}개")
        print(f"  B-Tier: {tiers.count('B')}개")

    print("\n✅ 완료!")


if __name__ == '__main__':
    main()
