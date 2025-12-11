"""
5분 단위 데이터 수집 및 보간 테스트
"""

from upbit_bitcoin_collector import UpbitBitcoinCollector

def test_minute5():
    """5분 단위 테스트 (보간 확인용)"""
    collector = UpbitBitcoinCollector("upbit_bitcoin.db")

    try:
        print("테스트: 5분(minute5) 단위 데이터 수집 (일부만 수집)")
        # 일부 데이터만 수집하여 빠르게 테스트
        print("\n============================================================")
        print("📊 minute5 데이터 수집 시작 (최신 1000개)")
        print("============================================================")

        candles = []
        to_timestamp = None

        for i in range(5):  # 5번만 반복 (1000개 데이터)
            fetched = collector.fetch_candles('minute5', to_timestamp)
            if not fetched:
                break

            candles.extend(fetched)
            to_timestamp = fetched[-1]['candle_date_time_kst']
            print(f"  반복 {i+1}: {len(fetched)}개 수집 (총 {len(candles)}개)")

        # DB에 저장
        collector.save_candles('minute5', candles)
        print(f"\n✓ 총 {len(candles)}개 캔들 저장 완료")

        # 결측값 보간
        collector.interpolate_missing_data('minute5')

        # 통계 출력
        print("\n검증 시작...")
        collector.print_statistics()

    except Exception as e:
        print(f"\n✗ 오류 발생: {e}")
        import traceback
        traceback.print_exc()
    finally:
        collector.close()

if __name__ == "__main__":
    test_minute5()
