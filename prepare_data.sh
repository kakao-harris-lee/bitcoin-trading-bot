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
if [ -f "upbit_bitcoin.db" ]; then
    SIZE=$(ls -lh upbit_bitcoin.db | awk '{print $5}')
    print_step "upbit_bitcoin.db 존재 (크기: $SIZE)"
else
    print_warning "upbit_bitcoin.db 없음 - 데이터 수집 시작"

    # v1_db생성 디렉토리로 이동
    if [ -d "v1_db생성" ]; then
        cd v1_db생성

        # 가상환경 활성화
        if [ -d "venv" ]; then
            source venv/bin/activate
        else
            print_error "가상환경 없음. python -m venv venv 실행 필요"
            exit 1
        fi

        # 데이터 수집 (최근 1년)
        print_step "Upbit 데이터 수집 중 (1년)..."
        python collect_upbit_data.py --days 365

        cd ..
        print_step "upbit_bitcoin.db 생성 완료"
    else
        print_error "v1_db생성 디렉토리 없음"
        exit 1
    fi
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
if [ -f "upbit_bitcoin.db" ]; then
    COUNT=$(sqlite3 upbit_bitcoin.db "SELECT COUNT(*) FROM bitcoin_day" 2>/dev/null || echo "0")
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
