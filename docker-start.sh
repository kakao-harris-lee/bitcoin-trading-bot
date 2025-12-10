#!/bin/bash
################################################################################
# Docker Compose 실행 스크립트
# 듀얼 트레이딩 봇 + 웹 대시보드
################################################################################

set -e

# 색상 정의
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

print_header() {
    echo ""
    echo "======================================================================"
    echo "  $1"
    echo "======================================================================"
}

print_step() {
    echo -e "${GREEN}[✓]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[!]${NC} $1"
}

print_error() {
    echo -e "${RED}[✗]${NC} $1"
}

print_header "Bitcoin Trading Bot - Docker Compose 시작"

# 1. .env 파일 확인
if [ ! -f .env ]; then
    print_error ".env 파일이 없습니다!"
    echo "다음 내용으로 .env 파일을 생성하세요:"
    echo ""
    echo "UPBIT_ACCESS_KEY=your_key"
    echo "UPBIT_SECRET_KEY=your_secret"
    echo "BINANCE_API_KEY=your_key"
    echo "BINANCE_API_SECRET=your_secret"
    echo "TELEGRAM_BOT_TOKEN=your_token"
    echo "TELEGRAM_CHAT_ID=your_chat_id"
    exit 1
fi
print_step ".env 파일 확인 완료"

# 2. DB 파일 확인 및 생성
if [ ! -f trading_results.db ]; then
    print_warning "trading_results.db가 없습니다. 생성 중..."
    python3 setup_dashboard_db.py
    print_step "DB 생성 완료"
else
    print_step "trading_results.db 확인 완료"
fi

# 3. 로그 디렉토리 생성
mkdir -p logs
print_step "로그 디렉토리 준비 완료"

# 4. Docker Compose 실행
print_header "Docker Compose 시작"

# 기존 컨테이너 중지 및 제거
if docker-compose ps | grep -q "Up"; then
    print_warning "기존 컨테이너 중지 중..."
    docker-compose down
fi

# 빌드 및 시작
print_step "Docker 이미지 빌드 및 컨테이너 시작..."
docker-compose up -d --build

# 5. 상태 확인
sleep 5
print_header "서비스 상태 확인"
docker-compose ps

# 6. 로그 확인 안내
print_header "실행 완료!"
echo ""
echo "📊 웹 대시보드: http://localhost:8000"
echo ""
echo "🔍 유용한 명령어:"
echo ""
echo "  # 전체 로그 확인"
echo "  docker-compose logs -f"
echo ""
echo "  # 트레이딩 봇 로그만"
echo "  docker-compose logs -f trading-bot"
echo ""
echo "  # 대시보드 로그만"
echo "  docker-compose logs -f dashboard"
echo ""
echo "  # 서비스 중지"
echo "  docker-compose down"
echo ""
echo "  # 서비스 재시작"
echo "  docker-compose restart"
echo ""
echo "  # 컨테이너 상태 확인"
echo "  docker-compose ps"
echo ""
