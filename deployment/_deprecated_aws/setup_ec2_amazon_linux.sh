#!/bin/bash

# Amazon Linux 2023용 EC2 환경 설정 스크립트
# 사용자: ec2-user

set -e

# 색상 정의
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

print_step() {
    echo -e "${GREEN}[SETUP]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

print_step "Amazon Linux EC2 환경 설정 시작"

# 1. 시스템 업데이트
print_step "시스템 패키지 업데이트 중..."
sudo yum update -y

# 2. 필수 패키지 설치
print_step "필수 패키지 설치 중..."
sudo yum install -y \
    git \
    wget \
    gcc \
    gcc-c++ \
    make \
    automake \
    autoconf \
    libtool \
    python3 \
    python3-pip \
    python3-devel \
    sqlite

# 3. TA-Lib 설치
print_step "TA-Lib 빌드 및 설치 중... (5-10분 소요)"
cd /tmp
wget http://prdownloads.sourceforge.net/ta-lib/ta-lib-0.4.0-src.tar.gz
tar -xzf ta-lib-0.4.0-src.tar.gz
cd ta-lib/
./configure --prefix=/usr
make
sudo make install
sudo ldconfig

print_step "✅ TA-Lib 설치 완료"

# 4. Python 가상환경 생성
print_step "Python 가상환경 생성 중..."
cd ~/bitcoin-trading-bot
python3 -m venv venv
source venv/bin/activate

# 5. Python 패키지 설치
print_step "Python 패키지 설치 중... (5-10분 소요)"
pip install --upgrade pip
pip install -r requirements.txt

print_step "✅ Python 패키지 설치 완료"

# 6. 로그 디렉토리 생성
print_step "로그 디렉토리 생성 중..."
mkdir -p ~/bitcoin-trading-bot/logs

# 7. 스왑 파일 생성 (메모리 부족 방지)
print_step "스왑 파일 생성 중..."
if [ ! -f /swapfile ]; then
    sudo dd if=/dev/zero of=/swapfile bs=1M count=2048
    sudo chmod 600 /swapfile
    sudo mkswap /swapfile
    sudo swapon /swapfile
    echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
    print_step "✅ 2GB 스왑 파일 생성 완료"
else
    print_step "스왑 파일이 이미 존재합니다"
fi

# 8. 방화벽 설정 (필요시)
print_step "방화벽 설정 확인 중..."
# Amazon Linux는 기본적으로 방화벽이 비활성화되어 있음
# EC2 보안 그룹에서 관리

# 9. logrotate 설정
print_step "로그 로테이션 설정 중..."
sudo cp ~/bitcoin-trading-bot/deployment/logrotate.conf /etc/logrotate.d/bitcoin-trading-bot

# 10. systemd 서비스 파일 수정 (ec2-user 사용)
print_step "systemd 서비스 파일 준비 중..."
sed 's/ubuntu/ec2-user/g' ~/bitcoin-trading-bot/deployment/bitcoin-trading-bot.service > /tmp/bitcoin-trading-bot.service
sed -i 's|/home/ubuntu|/home/ec2-user|g' /tmp/bitcoin-trading-bot.service

# 11. 환경 정보 출력
print_step "환경 설정 완료!"
echo ""
echo "========================================"
echo "설치된 버전 정보:"
echo "========================================"
echo "Python: $(python3 --version)"
echo "pip: $(pip --version)"
echo "TA-Lib: $(python3 -c 'import talib; print(talib.__version__)' 2>/dev/null || echo '설치 확인 필요')"
echo ""
echo "========================================"
echo "다음 단계:"
echo "========================================"
echo "1. .env 파일 생성:"
echo "   nano ~/bitcoin-trading-bot/.env"
echo ""
echo "2. systemd 서비스 설정:"
echo "   sudo cp /tmp/bitcoin-trading-bot.service /etc/systemd/system/"
echo "   sudo systemctl daemon-reload"
echo "   sudo systemctl enable bitcoin-trading-bot"
echo "   sudo systemctl start bitcoin-trading-bot"
echo ""
echo "3. 서비스 상태 확인:"
echo "   sudo systemctl status bitcoin-trading-bot"
echo "========================================"
