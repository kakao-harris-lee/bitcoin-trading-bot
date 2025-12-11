#!/bin/bash

################################################################################
# Bitcoin Trading Bot - 서버 배포 스크립트
# 새로운 서버: 49.247.171.64
# 사용법: ./deploy_to_server.sh [옵션]
################################################################################

set -e

# 색상 정의
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# 서버 정보
SERVER_USER="deploy"
SERVER_HOST="49.247.171.64"
SERVER_PATH="/home/deploy/bitcoin-trading-bot"
SSH_CONN="${SERVER_USER}@${SERVER_HOST}"

print_step() {
    echo -e "${GREEN}[✓]${NC} $1"
}

print_error() {
    echo -e "${RED}[✗]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[!]${NC} $1"
}

print_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_header() {
    echo ""
    echo "========================================="
    echo "  $1"
    echo "========================================="
}

# 프로젝트 루트로 이동
cd "$(dirname "$0")/.."

print_header "Bitcoin Trading Bot 서버 배포"
echo "서버: ${SERVER_HOST}"
echo "경로: ${SERVER_PATH}"
echo ""

# 1. SSH 연결 확인
print_info "서버 연결 확인 중..."
if ! ssh -o ConnectTimeout=5 ${SSH_CONN} "echo 'SSH 연결 성공'" &> /dev/null; then
    print_error "서버에 연결할 수 없습니다"
    echo ""
    echo "다음을 확인하세요:"
    echo "  1. SSH 키가 등록되어 있는지: ssh-copy-id ${SSH_CONN}"
    echo "  2. 서버가 실행 중인지"
    echo "  3. 방화벽 설정이 올바른지"
    echo ""
    echo "수동 연결 테스트: ssh ${SSH_CONN}"
    exit 1
fi
print_step "서버 연결 성공"

# 2. .env 파일 확인
if [ ! -f ".env" ]; then
    print_error ".env 파일이 없습니다!"
    echo ""
    echo "다음 내용으로 .env 파일을 생성하세요:"
    echo ""
    echo "UPBIT_ACCESS_KEY=your_access_key"
    echo "UPBIT_SECRET_KEY=your_secret_key"
    echo "TELEGRAM_BOT_TOKEN=your_bot_token"
    echo "TELEGRAM_CHAT_ID=your_chat_id"
    echo "AUTO_TRADE=False"
    echo ""
    exit 1
fi
print_step ".env 파일 확인"

# 3. upbit_bitcoin.db 확인
if [ ! -f "upbit_bitcoin.db" ]; then
    print_warning "upbit_bitcoin.db 파일이 없습니다"
    print_info "서버에서 데이터 수집이 필요합니다"
fi

# 4. 서버에 디렉토리 생성
print_info "서버 디렉토리 설정 중..."
ssh ${SSH_CONN} "mkdir -p ${SERVER_PATH}"
print_step "디렉토리 생성 완료"

# 5. 필수 파일 전송
print_info "파일 전송 중..."

# 핵심 파일들
rsync -avz --progress \
    --exclude='.git' \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='venv' \
    --exclude='v1_db생성' \
    --exclude='logs/*.log' \
    --exclude='*.backup' \
    --exclude='strategies/_archive' \
    --exclude='strategies/_deprecated' \
    --exclude='*.ipynb' \
    ./ ${SSH_CONN}:${SERVER_PATH}/

print_step "파일 전송 완료"

# 6. 서버에서 Docker Compose 실행
print_info "Docker Compose 시작 중..."

ssh ${SSH_CONN} << 'EOF'
cd /home/deploy/bitcoin-trading-bot

# Docker 및 Docker Compose 확인
if ! command -v docker &> /dev/null; then
    echo "Docker가 설치되어 있지 않습니다. 설치를 시작합니다..."
    curl -fsSL https://get.docker.com -o get-docker.sh
    sudo sh get-docker.sh
    sudo usermod -aG docker $USER
    rm get-docker.sh
    echo "Docker 설치 완료. 로그아웃 후 다시 로그인해주세요."
    exit 1
fi

# Docker Compose 버전 확인
if docker compose version &> /dev/null 2>&1; then
    DC="docker compose"
else
    DC="docker-compose"
fi

# 이전 컨테이너 중지
echo "이전 컨테이너 중지 중..."
$DC down 2>/dev/null || true

# 이미지 빌드 및 실행
echo "Docker 이미지 빌드 중..."
$DC build

echo "컨테이너 시작 중..."
$DC up -d

# 상태 확인
echo ""
echo "========================================="
echo "컨테이너 상태:"
echo "========================================="
$DC ps

echo ""
echo "로그 확인:"
echo "========================================="
$DC logs --tail=20

EOF

print_step "배포 완료!"

echo ""
print_header "배포 완료 안내"
echo ""
echo "서버 접속: ssh ${SSH_CONN}"
echo "작업 디렉토리: cd ${SERVER_PATH}"
echo ""
echo "유용한 명령어:"
echo "  - 로그 확인: docker compose logs -f"
echo "  - 컨테이너 재시작: docker compose restart"
echo "  - 컨테이너 중지: docker compose down"
echo "  - 컨테이너 상태: docker compose ps"
echo ""
print_info "원격 모니터링: ./deployment/monitor_server.sh"
echo ""
