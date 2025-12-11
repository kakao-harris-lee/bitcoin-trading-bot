"""
1분 단위 일부 데이터 수집 테스트 (중복 체크 확인)
"""

from upbit_bitcoin_collector import UpbitBitcoinCollector

def test_minute1_short():
    """1분 단위 일부만 수집하여 중복 체크 테스트"""
    collector = UpbitBitcoinCollector("upbit_bitcoin.db")

    try:
        print("테스트: 1분(minute1) 단위 데이터 수집 (최신 600개)")
        collector.collect_all_data('minute1')

        # 통계 출력
        print("\n검증...")
        collector.print_statistics()

    except Exception as e:
        print(f"\n✗ 오류 발생: {e}")
        import traceback
        traceback.print_exc()
    finally:
        collector.close()

if __name__ == "__main__":
    test_minute1_short()
