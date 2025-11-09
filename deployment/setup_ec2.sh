#!/bin/bash

# EC2 환경 설정 스크립트
# Ubuntu 22.04 LTS 기준

set -e  # 에러 발생 시 중단

echo "======================================"
echo "Bitcoin Trading Bot - EC2 Setup"
echo "======================================"

# 색상 정의
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 진행 상황 출력 함수
print_step() {
    echo -e "${GREEN}[STEP]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

# 1. 시스템 업데이트
print_step "시스템 업데이트 중..."
sudo apt update
sudo apt upgrade -y

# 2. 필수 패키지 설치
print_step "필수 패키지 설치 중..."
sudo apt install -y \
    build-essential \
    git \
    wget \
    curl \
    vim \
    htop \
    tmux \
    python3.10 \
    python3.10-venv \
    python3-pip \
    gcc \
    g++ \
    make

# 3. TA-Lib 설치
print_step "TA-Lib 설치 중..."
cd /tmp
wget http://prdownloads.sourceforge.net/ta-lib/ta-lib-0.4.0-src.tar.gz
tar -xzf ta-lib-0.4.0-src.tar.gz
cd ta-lib/
./configure --prefix=/usr
make
sudo make install
sudo ldconfig

# TA-Lib 설치 확인
if [ -f "/usr/lib/libta_lib.so" ]; then
    print_step "✅ TA-Lib 설치 완료"
else
    print_error "❌ TA-Lib 설치 실패"
    exit 1
fi

# 4. Python 가상환경 생성
print_step "Python 가상환경 생성 중..."
cd ~
if [ -d "bitcoin-trading-bot" ]; then
    cd bitcoin-trading-bot
    python3 -m venv venv
    source venv/bin/activate

    # pip 업그레이드
    pip install --upgrade pip

    # 라이브러리 설치
    print_step "Python 라이브러리 설치 중... (시간이 걸릴 수 있습니다)"
    pip install -r requirements.txt

    # TA-Lib Python 래퍼 설치
    pip install TA-Lib

    print_step "✅ Python 환경 설정 완료"
else
    print_error "프로젝트 디렉토리를 찾을 수 없습니다: ~/bitcoin-trading-bot"
    print_warning "먼저 프로젝트를 clone하거나 업로드하세요."
    exit 1
fi

# 5. 로그 디렉토리 생성
print_step "로그 디렉토리 생성 중..."
mkdir -p ~/bitcoin-trading-bot/logs

# 6. .env 파일 확인
if [ ! -f "~/bitcoin-trading-bot/.env" ]; then
    print_warning ".env 파일이 없습니다. 수동으로 생성하세요:"
    echo "  nano ~/bitcoin-trading-bot/.env"
else
    # .env 파일 권한 설정
    chmod 600 ~/.env
    print_step "✅ .env 파일 권한 설정 완료"
fi

# 7. 방화벽 설정
print_step "방화벽 설정 중..."
sudo ufw --force enable
sudo ufw allow 22/tcp
print_step "✅ 방화벽 설정 완료 (SSH 허용)"

# 8. Fail2Ban 설치
print_step "Fail2Ban 설치 중..."
sudo apt install -y fail2ban
sudo systemctl start fail2ban
sudo systemctl enable fail2ban
print_step "✅ Fail2Ban 설치 완료"

# 9. 자동 업데이트 설정
print_step "자동 업데이트 설정 중..."
sudo apt install -y unattended-upgrades
sudo dpkg-reconfigure --priority=low unattended-upgrades
print_step "✅ 자동 업데이트 설정 완료"

# 10. 스왑 파일 생성 (메모리 보강)
if [ ! -f "/swapfile" ]; then
    print_step "스왑 파일 생성 중 (2GB)..."
    sudo fallocate -l 2G /swapfile
    sudo chmod 600 /swapfile
    sudo mkswap /swapfile
    sudo swapon /swapfile
    echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
    print_step "✅ 스왑 파일 생성 완료"
else
    print_step "스왑 파일이 이미 존재합니다"
fi

# 11. 연결 테스트
print_step "연결 테스트 실행 중..."
cd ~/bitcoin-trading-bot/live_trading
source ../venv/bin/activate

if python test_connection.py; then
    print_step "✅ 연결 테스트 성공"
else
    print_error "❌ 연결 테스트 실패"
    print_warning ".env 파일을 확인하세요"
fi

# 완료 메시지
echo ""
echo "======================================"
echo -e "${GREEN}✅ EC2 환경 설정 완료!${NC}"
echo "======================================"
echo ""
echo "다음 단계:"
echo "1. .env 파일 생성/확인:"
echo "   nano ~/bitcoin-trading-bot/.env"
echo ""
echo "2. systemd 서비스 설정:"
echo "   sudo cp ~/bitcoin-trading-bot/deployment/bitcoin-trading-bot.service /etc/systemd/system/"
echo "   sudo systemctl daemon-reload"
echo "   sudo systemctl enable bitcoin-trading-bot"
echo "   sudo systemctl start bitcoin-trading-bot"
echo ""
echo "3. 서비스 상태 확인:"
echo "   sudo systemctl status bitcoin-trading-bot"
echo ""
echo "4. 로그 확인:"
echo "   tail -f ~/bitcoin-trading-bot/logs/trading.log"
echo ""
