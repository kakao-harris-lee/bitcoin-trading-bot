"""
테스트용: 일(day) 단위만 수집하여 빠르게 테스트
"""

from upbit_bitcoin_collector import UpbitBitcoinCollector

def test_single_timeframe():
    """한 시간단위만 테스트"""
    collector = UpbitBitcoinCollector("upbit_bitcoin.db")

    try:
        # 일 단위만 수집 (데이터가 적어서 빠름)
        print("테스트: 일(day) 단위 데이터 수집")
        collector.collect_all_data('day')

        print("\n테스트 완료! 검증 시작...")

        # 통계 출력
        collector.print_statistics()

    except KeyboardInterrupt:
        print("\n\n⚠️ 사용자에 의해 중단됨")
    except Exception as e:
        print(f"\n✗ 오류 발생: {e}")
        import traceback
        traceback.print_exc()
    finally:
        collector.close()

if __name__ == "__main__":
    test_single_timeframe()
