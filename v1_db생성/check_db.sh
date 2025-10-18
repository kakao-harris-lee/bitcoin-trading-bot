#!/bin/bash

# 빠른 DB 확인 스크립트

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

DB_FILE="upbit_bitcoin.db"

if [ ! -f "$DB_FILE" ]; then
    echo "✗ DB 파일을 찾을 수 없습니다: $DB_FILE"
    exit 1
fi

echo "============================================================"
echo "📊 업비트 비트코인 DB 빠른 확인"
echo "============================================================"
echo ""

# DB 파일 정보
DB_SIZE=$(ls -lh "$DB_FILE" | awk '{print $5}')
echo "📦 DB 파일 크기: $DB_SIZE"
echo ""

# SQLite로 통계 조회
sqlite3 "$DB_FILE" << 'EOF'
.mode column
.headers on

SELECT '전체 통계' as '===';

SELECT
    '총 레코드 수' as 항목,
    (SELECT COUNT(*) FROM bitcoin_minute1) +
    (SELECT COUNT(*) FROM bitcoin_minute3) +
    (SELECT COUNT(*) FROM bitcoin_minute5) +
    (SELECT COUNT(*) FROM bitcoin_minute10) +
    (SELECT COUNT(*) FROM bitcoin_minute15) +
    (SELECT COUNT(*) FROM bitcoin_minute30) +
    (SELECT COUNT(*) FROM bitcoin_minute60) +
    (SELECT COUNT(*) FROM bitcoin_minute240) +
    (SELECT COUNT(*) FROM bitcoin_day) +
    (SELECT COUNT(*) FROM bitcoin_week) +
    (SELECT COUNT(*) FROM bitcoin_month) as 값;

SELECT '' as '';
SELECT '시간단위별 데이터 수' as '===';
SELECT '' as '';

SELECT 'minute1' as 시간단위, COUNT(*) as 개수, MIN(timestamp) as 최고, MAX(timestamp) as 최신
FROM bitcoin_minute1;

SELECT 'minute3' as 시간단위, COUNT(*) as 개수, MIN(timestamp) as 최고, MAX(timestamp) as 최신
FROM bitcoin_minute3 WHERE (SELECT COUNT(*) FROM bitcoin_minute3) > 0;

SELECT 'minute5' as 시간단위, COUNT(*) as 개수, MIN(timestamp) as 최고, MAX(timestamp) as 최신
FROM bitcoin_minute5 WHERE (SELECT COUNT(*) FROM bitcoin_minute5) > 0;

SELECT 'minute10' as 시간단위, COUNT(*) as 개수, MIN(timestamp) as 최고, MAX(timestamp) as 최신
FROM bitcoin_minute10 WHERE (SELECT COUNT(*) FROM bitcoin_minute10) > 0;

SELECT 'minute15' as 시간단위, COUNT(*) as 개수, MIN(timestamp) as 최고, MAX(timestamp) as 최신
FROM bitcoin_minute15 WHERE (SELECT COUNT(*) FROM bitcoin_minute15) > 0;

SELECT 'minute30' as 시간단위, COUNT(*) as 개수, MIN(timestamp) as 최고, MAX(timestamp) as 최신
FROM bitcoin_minute30 WHERE (SELECT COUNT(*) FROM bitcoin_minute30) > 0;

SELECT 'minute60' as 시간단위, COUNT(*) as 개수, MIN(timestamp) as 최고, MAX(timestamp) as 최신
FROM bitcoin_minute60 WHERE (SELECT COUNT(*) FROM bitcoin_minute60) > 0;

SELECT 'minute240' as 시간단위, COUNT(*) as 개수, MIN(timestamp) as 최고, MAX(timestamp) as 최신
FROM bitcoin_minute240 WHERE (SELECT COUNT(*) FROM bitcoin_minute240) > 0;

SELECT 'day' as 시간단위, COUNT(*) as 개수, MIN(timestamp) as 최고, MAX(timestamp) as 최신
FROM bitcoin_day WHERE (SELECT COUNT(*) FROM bitcoin_day) > 0;

SELECT 'week' as 시간단위, COUNT(*) as 개수, MIN(timestamp) as 최고, MAX(timestamp) as 최신
FROM bitcoin_week WHERE (SELECT COUNT(*) FROM bitcoin_week) > 0;

SELECT 'month' as 시간단위, COUNT(*) as 개수, MIN(timestamp) as 최고, MAX(timestamp) as 최신
FROM bitcoin_month WHERE (SELECT COUNT(*) FROM bitcoin_month) > 0;

EOF

echo ""
echo "============================================================"
echo ""
echo "💡 상세 확인을 원하시면:"
echo "   python db_cli.py"
echo ""
