#!/usr/bin/env python3
"""
v_simple_rsi: RSI 과매도 전략
============================
시그널 조건: RSI < 30 (과매도 구간)
타임프레임: day
목적: Fixed Exit + Fixed Position 플러그인 검증
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


def generate_signals_for_year(year: int):
    """연도별 시그널 생성"""

    # DB에서 데이터 로드
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

    # RSI 계산
    df['rsi'] = calculate_rsi(df, period=14)

    # 시그널 생성: RSI < 30
    signals = []

    for idx, row in df.iterrows():
        if pd.notna(row['rsi']) and row['rsi'] < 30:
            signal = {
                "timestamp": row['timestamp'].strftime('%Y-%m-%d %H:%M:%S'),
                "action": "BUY",
                "price": int(row['close']),
                "score": round(30 - row['rsi'], 2),  # RSI가 낮을수록 높은 점수
                "confidence": round((30 - row['rsi']) / 30, 2),
                "metadata": {
                    "rsi": round(row['rsi'], 2),
                    "indicator": "RSI_OVERSOLD"
                }
            }
            signals.append(signal)

    return signals


def main():
    """메인 함수"""

    print("=" * 60)
    print("v_simple_rsi: RSI 과매도 시그널 생성")
    print("=" * 60)

    output_dir = Path('strategies/validation/v_simple_rsi/signals')
    output_dir.mkdir(parents=True, exist_ok=True)

    # 2024년 시그널 생성
    year = 2024
    print(f"\n[{year}] 시그널 생성 중...")

    signals = generate_signals_for_year(year)

    # JSON 저장
    output = {
        "metadata": {
            "strategy": "v_simple_rsi",
            "version": "1.0",
            "timeframe": "day",
            "generated_at": datetime.now().isoformat(),
            "description": "Simple RSI oversold strategy (RSI < 30)",
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

    # 통계 출력
    if signals:
        scores = [s['score'] for s in signals]
        print(f"\n[통계]")
        print(f"  평균 점수: {sum(scores)/len(scores):.2f}")
        print(f"  최대 점수: {max(scores):.2f}")
        print(f"  최소 점수: {min(scores):.2f}")

    print("\n✅ 완료!")


if __name__ == '__main__':
    main()
