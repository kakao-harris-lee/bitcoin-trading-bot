#!/usr/bin/env python3
"""
업비트 비트코인 DB 확인 CLI
간단한 대화형 인터페이스로 DB 내용 확인
"""

import sqlite3
import sys
from datetime import datetime


class BitcoinDBCLI:
    """비트코인 DB CLI"""

    TIMEFRAMES = [
        'minute1', 'minute3', 'minute5', 'minute10', 'minute15',
        'minute30', 'minute60', 'minute240', 'day', 'week', 'month'
    ]

    def __init__(self, db_path="upbit_bitcoin.db"):
        try:
            self.conn = sqlite3.connect(db_path)
            self.cursor = self.conn.cursor()
            print(f"✓ DB 연결 성공: {db_path}\n")
        except Exception as e:
            print(f"✗ DB 연결 실패: {e}")
            sys.exit(1)

    def show_menu(self):
        """메인 메뉴 표시"""
        print("\n" + "="*60)
        print("📊 업비트 비트코인 DB 확인 CLI")
        print("="*60)
        print("\n메뉴:")
        print("  1. 전체 통계")
        print("  2. 특정 시간단위 상세 정보")
        print("  3. 최신 데이터 조회")
        print("  4. 날짜별 데이터 조회")
        print("  5. 보간 데이터 통계")
        print("  6. DB 파일 정보")
        print("  0. 종료")
        print("-"*60)

    def show_all_stats(self):
        """전체 통계 표시"""
        print("\n" + "="*60)
        print("📈 전체 데이터 통계")
        print("="*60)

        total_records = 0
        for tf in self.TIMEFRAMES:
            try:
                self.cursor.execute(f"""
                    SELECT
                        COUNT(*) as total,
                        SUM(CASE WHEN is_interpolated = 0 THEN 1 ELSE 0 END) as original,
                        SUM(CASE WHEN is_interpolated = 1 THEN 1 ELSE 0 END) as interpolated,
                        MIN(timestamp) as oldest,
                        MAX(timestamp) as newest
                    FROM bitcoin_{tf}
                """)

                stats = self.cursor.fetchone()
                total, original, interpolated, oldest, newest = stats

                if total > 0:
                    total_records += total
                    print(f"\n{tf}:")
                    print(f"  전체: {total:,}개")
                    print(f"  원본: {original or 0:,}개")
                    print(f"  보간: {interpolated or 0:,}개")
                    if oldest and newest:
                        print(f"  기간: {oldest} ~ {newest}")
            except Exception as e:
                continue

        print(f"\n총 레코드 수: {total_records:,}개")
        print("="*60)

    def show_timeframe_detail(self):
        """특정 시간단위 상세 정보"""
        print("\n사용 가능한 시간단위:")
        for i, tf in enumerate(self.TIMEFRAMES, 1):
            print(f"  {i}. {tf}")

        try:
            choice = int(input("\n번호 선택 (1-11): "))
            if 1 <= choice <= len(self.TIMEFRAMES):
                tf = self.TIMEFRAMES[choice - 1]
                self._show_detail(tf)
            else:
                print("✗ 잘못된 번호입니다.")
        except ValueError:
            print("✗ 숫자를 입력하세요.")

    def _show_detail(self, tf):
        """시간단위 상세 정보 표시"""
        print(f"\n" + "="*60)
        print(f"📊 {tf} 상세 정보")
        print("="*60)

        # 기본 통계
        self.cursor.execute(f"""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN is_interpolated = 0 THEN 1 ELSE 0 END) as original,
                SUM(CASE WHEN is_interpolated = 1 THEN 1 ELSE 0 END) as interpolated,
                MIN(timestamp) as oldest,
                MAX(timestamp) as newest,
                MIN(trade_price) as min_price,
                MAX(trade_price) as max_price,
                AVG(trade_price) as avg_price
            FROM bitcoin_{tf}
        """)

        stats = self.cursor.fetchone()
        total, original, interpolated, oldest, newest, min_price, max_price, avg_price = stats

        if total == 0:
            print("데이터 없음")
            return

        print(f"\n📈 기본 통계:")
        print(f"  전체 데이터: {total:,}개")
        print(f"  원본 데이터: {original or 0:,}개")
        print(f"  보간 데이터: {interpolated or 0:,}개")
        print(f"  보간 비율: {(interpolated or 0)/total*100:.2f}%")

        print(f"\n📅 기간:")
        print(f"  최고: {oldest}")
        print(f"  최신: {newest}")

        print(f"\n💰 가격 정보:")
        print(f"  최저가: {min_price:,.0f}원")
        print(f"  최고가: {max_price:,.0f}원")
        print(f"  평균가: {avg_price:,.0f}원")

        # 최근 데이터 샘플
        print(f"\n💾 최신 5개 데이터:")
        self.cursor.execute(f"""
            SELECT timestamp, opening_price, high_price, low_price, trade_price, is_interpolated
            FROM bitcoin_{tf}
            ORDER BY timestamp DESC
            LIMIT 5
        """)

        print(f"  {'시간':<20} {'시가':>15} {'고가':>15} {'저가':>15} {'종가':>15} 보간")
        print(f"  {'-'*95}")

        for row in self.cursor.fetchall():
            timestamp, open_p, high_p, low_p, close_p, interp = row
            interp_mark = "✓" if interp == 1 else ""
            print(f"  {timestamp:<20} {open_p:>15,.0f} {high_p:>15,.0f} {low_p:>15,.0f} {close_p:>15,.0f} {interp_mark}")

    def show_latest_data(self):
        """최신 데이터 조회"""
        print("\n" + "="*60)
        print("🔍 최신 데이터 조회")
        print("="*60)

        count = input("\n각 시간단위별 최신 데이터 개수 (기본: 3): ").strip()
        count = int(count) if count.isdigit() else 3

        for tf in self.TIMEFRAMES:
            try:
                self.cursor.execute(f"""
                    SELECT timestamp, trade_price, is_interpolated
                    FROM bitcoin_{tf}
                    ORDER BY timestamp DESC
                    LIMIT {count}
                """)

                rows = self.cursor.fetchall()
                if rows:
                    print(f"\n{tf}:")
                    for row in rows:
                        timestamp, price, interp = row
                        interp_mark = "[보간]" if interp == 1 else ""
                        print(f"  {timestamp}: {price:,.0f}원 {interp_mark}")
            except Exception:
                continue

    def show_date_query(self):
        """날짜별 데이터 조회"""
        print("\n" + "="*60)
        print("📅 날짜별 데이터 조회")
        print("="*60)

        date = input("\n날짜 입력 (YYYY-MM-DD, 예: 2025-10-16): ").strip()

        if not date:
            print("✗ 날짜를 입력하세요.")
            return

        print(f"\n{date} 데이터:")
        for tf in self.TIMEFRAMES:
            try:
                self.cursor.execute(f"""
                    SELECT COUNT(*) FROM bitcoin_{tf}
                    WHERE timestamp LIKE '{date}%'
                """)

                count = self.cursor.fetchone()[0]
                if count > 0:
                    self.cursor.execute(f"""
                        SELECT MIN(trade_price), MAX(trade_price), AVG(trade_price)
                        FROM bitcoin_{tf}
                        WHERE timestamp LIKE '{date}%'
                    """)

                    min_p, max_p, avg_p = self.cursor.fetchone()
                    print(f"  {tf}: {count}개 | 최저 {min_p:,.0f}원 | 최고 {max_p:,.0f}원 | 평균 {avg_p:,.0f}원")
            except Exception:
                continue

    def show_interpolation_stats(self):
        """보간 데이터 통계"""
        print("\n" + "="*60)
        print("🔧 보간 데이터 통계")
        print("="*60)

        total_interpolated = 0
        for tf in self.TIMEFRAMES:
            try:
                self.cursor.execute(f"""
                    SELECT
                        COUNT(*) as total,
                        SUM(CASE WHEN is_interpolated = 1 THEN 1 ELSE 0 END) as interpolated
                    FROM bitcoin_{tf}
                """)

                total, interpolated = self.cursor.fetchone()
                if total > 0 and interpolated > 0:
                    total_interpolated += interpolated
                    ratio = interpolated / total * 100
                    print(f"  {tf}: {interpolated:,}개 ({ratio:.2f}%)")
            except Exception:
                continue

        print(f"\n총 보간 데이터: {total_interpolated:,}개")

    def show_db_info(self):
        """DB 파일 정보"""
        import os

        print("\n" + "="*60)
        print("📦 DB 파일 정보")
        print("="*60)

        db_path = "upbit_bitcoin.db"
        if os.path.exists(db_path):
            size = os.path.getsize(db_path)
            size_mb = size / (1024 * 1024)

            print(f"\n파일 경로: {os.path.abspath(db_path)}")
            print(f"파일 크기: {size_mb:.2f} MB")

            # 테이블 정보
            self.cursor.execute("""
                SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'bitcoin_%'
            """)

            tables = [row[0] for row in self.cursor.fetchall()]
            print(f"테이블 수: {len(tables)}개")
            print(f"테이블 목록: {', '.join(tables)}")

            # 전체 레코드 수
            total_records = 0
            for table in tables:
                self.cursor.execute(f"SELECT COUNT(*) FROM {table}")
                total_records += self.cursor.fetchone()[0]

            print(f"총 레코드 수: {total_records:,}개")
        else:
            print("✗ DB 파일을 찾을 수 없습니다.")

    def run(self):
        """CLI 실행"""
        while True:
            self.show_menu()
            choice = input("\n선택: ").strip()

            if choice == '0':
                print("\n👋 종료합니다.")
                break
            elif choice == '1':
                self.show_all_stats()
            elif choice == '2':
                self.show_timeframe_detail()
            elif choice == '3':
                self.show_latest_data()
            elif choice == '4':
                self.show_date_query()
            elif choice == '5':
                self.show_interpolation_stats()
            elif choice == '6':
                self.show_db_info()
            else:
                print("✗ 잘못된 선택입니다.")

            input("\nEnter를 눌러 계속...")

    def close(self):
        """DB 연결 종료"""
        self.conn.close()


def main():
    """메인 함수"""
    cli = BitcoinDBCLI()
    try:
        cli.run()
    except KeyboardInterrupt:
        print("\n\n✗ 사용자에 의해 중단됨")
    finally:
        cli.close()


if __name__ == "__main__":
    main()
