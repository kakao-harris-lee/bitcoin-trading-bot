#!/bin/bash

################################################################################
# 데이터베이스 준비 스크립트
# Upbit 데이터 + Binance 데이터 수집
################################################################################

set -e

# 색상
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

print_step() {
    echo -e "${GREEN}[✓]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[!]${NC} $1"
}

print_error() {
    echo -e "${RED}[✗]${NC} $1"
}

echo "======================================"
echo "  데이터베이스 준비"
echo "======================================"

# 1. upbit_bitcoin.db 확인
if [ -f "data/upbit_bitcoin.db" ]; then
    SIZE=$(ls -lh data/upbit_bitcoin.db | awk '{print $5}')
    print_step "upbit_bitcoin.db 존재 (크기: $SIZE)"
else
    print_warning "upbit_bitcoin.db 없음 - 데이터 수집 시작"

    # Python 스크립트로 데이터 수집
    print_step "Upbit 데이터 수집 중..."
    python scripts/collect_data.py

    print_step "upbit_bitcoin.db 생성 완료"
fi

# 2. Binance 데이터 수집
print_step "Binance 데이터 수집 중..."

cd strategies/SHORT_V1

# Python 환경 확인
if ! python -c "import pandas" 2>/dev/null; then
    print_warning "pandas 설치 필요"
    pip install pandas requests
fi

# 데이터 수집 실행
python data_collector.py

print_step "Binance 데이터 수집 완료"
cd ../..

# 3. 데이터 검증
echo ""
echo "======================================"
echo "  데이터 검증"
echo "======================================"

# Upbit DB
if [ -f "data/upbit_bitcoin.db" ]; then
    COUNT=$(sqlite3 data/upbit_bitcoin.db "SELECT COUNT(*) FROM bitcoin_day" 2>/dev/null || echo "0")
    print_step "Upbit 일봉 데이터: $COUNT개"
fi

# Binance CSV
BINANCE_CSV="strategies/SHORT_V1/results/btcusdt_4h_with_funding_2022-01-01_2024-12-31.csv"
if [ -f "$BINANCE_CSV" ]; then
    COUNT=$(wc -l < "$BINANCE_CSV")
    print_step "Binance 4시간봉 데이터: $COUNT줄"
else
    print_warning "Binance CSV 없음: $BINANCE_CSV"
fi

echo ""
print_step "데이터 준비 완료!"
echo ""
echo "다음 명령으로 배포:"
echo "  cd deployment"
echo "  ./deploy_to_server.sh"
echo ""
