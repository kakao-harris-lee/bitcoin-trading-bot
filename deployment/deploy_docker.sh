#!/bin/bash

################################################################################
# Bitcoin Trading Bot - Docker Compose 배포 스크립트
#
# 사용법: ./deploy_docker.sh [command]
#
# Commands:
#   start   - 컨테이너 시작 (기본값)
#   stop    - 컨테이너 중지
#   restart - 컨테이너 재시작
#   logs    - 실시간 로그 보기
#   status  - 컨테이너 상태 확인
#   build   - 이미지 재빌드
#   clean   - 모든 컨테이너 및 이미지 삭제
################################################################################

set -e

# 색상 정의
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

print_step() {
    echo -e "${GREEN}[DOCKER]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

# 프로젝트 루트로 이동
cd "$(dirname "$0")/.."

# 명령어 파싱
COMMAND=${1:-start}

echo ""
echo "========================================"
echo "  Bitcoin Trading Bot - Docker"
echo "========================================"
echo "  버전: v35 Optimized (Optuna Trial 99)"
echo "  명령: $COMMAND"
echo "========================================"
echo ""

# Docker 설치 확인
if ! command -v docker &> /dev/null; then
    print_error "Docker가 설치되지 않았습니다"
    echo "설치: https://docs.docker.com/get-docker/"
    exit 1
fi

if ! command -v docker-compose &> /dev/null && ! docker compose version &> /dev/null 2>&1; then
    print_error "Docker Compose가 설치되지 않았습니다"
    echo "설치: https://docs.docker.com/compose/install/"
    exit 1
fi

# Docker Compose 명령어 감지
if docker compose version &> /dev/null 2>&1; then
    DC="docker compose"
else
    DC="docker-compose"
fi

# .env 파일 확인
if [ ! -f ".env" ]; then
    print_error ".env 파일이 없습니다!"
    echo ""
    echo "다음 내용으로 .env 파일을 생성하세요:"
    echo ""
    echo "UPBIT_ACCESS_KEY=your_access_key"
    echo "UPBIT_SECRET_KEY=your_secret_key"
    echo "TELEGRAM_BOT_TOKEN=your_bot_token"
    echo "TELEGRAM_CHAT_ID=your_chat_id"
    echo "BINANCE_API_KEY=your_binance_key (선택)"
    echo "BINANCE_API_SECRET=your_binance_secret (선택)"
    echo "AUTO_TRADE=False"
    echo ""
    exit 1
fi

# DB 파일 확인
if [ ! -f "upbit_bitcoin.db" ]; then
    print_warning "upbit_bitcoin.db 파일이 없습니다"
    print_info "컨테이너 시작 후 데이터 수집이 필요합니다"
fi

# 명령 실행
case $COMMAND in
    start)
        print_step "[1/3] 컨테이너 시작 중..."
        $DC up -d

        print_step "[2/3] 컨테이너 상태 확인 중..."
        sleep 3
        $DC ps

        print_step "[3/3] 로그 확인 (최근 20줄)..."
        $DC logs --tail=20 trading-bot

        echo ""
        print_step "✅ 배포 완료!"
        echo ""
        echo "유용한 명령어:"
        echo "  로그 보기:     $0 logs"
        echo "  상태 확인:     $0 status"
        echo "  재시작:        $0 restart"
        echo "  중지:          $0 stop"
        ;;

    stop)
        print_step "컨테이너 중지 중..."
        $DC down
        print_step "✅ 중지 완료"
        ;;

    restart)
        print_step "컨테이너 재시작 중..."
        $DC restart
        sleep 3
        $DC logs --tail=20 trading-bot
        print_step "✅ 재시작 완료"
        ;;

    logs)
        print_step "실시간 로그 (Ctrl+C로 종료)..."
        $DC logs -f trading-bot
        ;;

    status)
        print_step "컨테이너 상태:"
        $DC ps
        echo ""
        print_step "리소스 사용량:"
        docker stats --no-stream bitcoin-trading-bot-v35-optimized 2>/dev/null || echo "컨테이너가 실행 중이지 않습니다"
        ;;

    build)
        print_step "[1/2] 이미지 재빌드 중..."
        $DC build --no-cache

        print_step "[2/2] 컨테이너 재시작 중..."
        $DC up -d

        print_step "✅ 빌드 및 배포 완료"
        ;;

    clean)
        print_warning "모든 컨테이너와 이미지를 삭제합니다"
        read -p "계속하시겠습니까? (yes 입력): " confirm
        if [ "$confirm" = "yes" ]; then
            print_step "컨테이너 중지 및 삭제 중..."
            $DC down -v

            print_step "이미지 삭제 중..."
            docker rmi $(docker images | grep bitcoin-trading-bot | awk '{print $3}') 2>/dev/null || true

            print_step "✅ 정리 완료"
        else
            print_info "취소됨"
        fi
        ;;

    *)
        print_error "알 수 없는 명령: $COMMAND"
        echo ""
        echo "사용 가능한 명령:"
        echo "  start   - 컨테이너 시작 (기본값)"
        echo "  stop    - 컨테이너 중지"
        echo "  restart - 컨테이너 재시작"
        echo "  logs    - 실시간 로그 보기"
        echo "  status  - 컨테이너 상태 확인"
        echo "  build   - 이미지 재빌드"
        echo "  clean   - 모든 컨테이너 및 이미지 삭제"
        exit 1
        ;;
esac
