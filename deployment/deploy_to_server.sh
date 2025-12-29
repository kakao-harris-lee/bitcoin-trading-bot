#!/bin/bash

################################################################################
# Bitcoin Trading Bot - 서버 배포 스크립트
# 새로운 서버: chsvr.duckdns.org
# 배포 방식: git push/pull (rsync/scp 금지)
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
SERVER_HOST="chsvr.duckdns.org"
SERVER_PATH="/home/deploy/bitcoin-trading-bot"
SSH_CONN="${SERVER_USER}@${SERVER_HOST}"
BRANCH="main"
MODE="paper"

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
echo "방식: git push/pull (rsync/scp 금지)"
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

# 2. 로컬 git 상태 확인
print_info "로컬 git 상태 확인 중..."
if [[ -n $(git status --porcelain) ]]; then
    print_warning "커밋되지 않은 변경사항이 있습니다:"
    git status --short
    echo ""
    read -p "커밋 없이 계속하시겠습니까? (y/N) " -n 1 -r
    echo ""
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        print_error "배포 중단. 먼저 변경사항을 커밋하세요."
        exit 1
    fi
fi
print_step "git 상태 확인 완료"

# 3. git push
print_info "origin/${BRANCH}로 push 중..."
git push origin "${BRANCH}"
print_step "git push 완료"

# 4. 서버에서 git pull 및 재시작
print_info "서버에서 git pull 및 재시작 중..."

ssh ${SSH_CONN} << EOF
set -e
cd ${SERVER_PATH}

echo ""
echo "========================================="
echo "git pull 실행 중..."
echo "========================================="
git fetch origin
git reset --hard origin/${BRANCH}

echo ""
echo "========================================="
echo ".env 확인..."
echo "========================================="
if [ -f .env ]; then
    echo ".env 파일 존재"
else
    echo "경고: .env 파일이 없습니다"
    echo "필수 시크릿을 포함한 .env 파일을 생성하세요"
fi

echo ""
echo "========================================="
echo "pip install 실행 중..."
echo "========================================="
source .venv/bin/activate 2>/dev/null || (python3 -m venv .venv && source .venv/bin/activate)
pip install -q -r requirements.txt

echo ""
echo "========================================="
echo "봇 재시작 중 (mode: ${MODE})..."
echo "========================================="
./bot.sh stop 2>/dev/null || true
sleep 2
./bot.sh start ${MODE}

echo ""
echo "========================================="
echo "상태 확인:"
echo "========================================="
./bot.sh status

EOF

print_step "배포 완료!"

echo ""
print_header "배포 완료 안내"
echo ""
echo "서버 접속: ssh ${SSH_CONN}"
echo "작업 디렉토리: cd ${SERVER_PATH}"
echo ""
echo "유용한 명령어:"
echo "  - 로그 확인: ./bot.sh logs"
echo "  - 봇 재시작: ./bot.sh restart"
echo "  - 봇 종료: ./bot.sh stop"
echo "  - 상태 확인: ./bot.sh status"
echo ""
