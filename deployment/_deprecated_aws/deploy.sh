#!/bin/bash

# 로컬에서 EC2로 배포하는 스크립트
# 사용법: ./deploy.sh <EC2_IP> <KEY_FILE>

set -e

# 색상 정의
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

print_step() {
    echo -e "${GREEN}[DEPLOY]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

# 인자 체크
if [ $# -lt 2 ]; then
    print_error "사용법: ./deploy.sh <EC2_IP> <KEY_FILE>"
    echo "예시: ./deploy.sh 13.125.123.456 ~/Downloads/bitcoin-trading-bot-key.pem"
    exit 1
fi

EC2_IP=$1
KEY_FILE=$2
EC2_USER="ubuntu"
EC2_HOST="${EC2_USER}@${EC2_IP}"

# 키 파일 존재 확인
if [ ! -f "$KEY_FILE" ]; then
    print_error "키 파일을 찾을 수 없습니다: $KEY_FILE"
    exit 1
fi

# 키 파일 권한 확인
if [ "$(stat -f %A "$KEY_FILE")" != "400" ]; then
    print_warning "키 파일 권한을 400으로 변경합니다"
    chmod 400 "$KEY_FILE"
fi

print_step "EC2 배포 시작: $EC2_IP"

# 1. 연결 테스트
print_step "EC2 연결 테스트 중..."
if ! ssh -i "$KEY_FILE" -o ConnectTimeout=10 "$EC2_HOST" "echo 'Connected'" > /dev/null 2>&1; then
    print_error "EC2 연결 실패. IP와 키 파일을 확인하세요."
    exit 1
fi
print_step "✅ 연결 성공"

# 2. 프로젝트 디렉토리 생성
print_step "프로젝트 디렉토리 생성 중..."
ssh -i "$KEY_FILE" "$EC2_HOST" "mkdir -p ~/bitcoin-trading-bot"

# 3. 파일 전송 (제외: .env, venv, .git, __pycache__, *.db)
print_step "프로젝트 파일 전송 중..."
rsync -avz --progress \
    --exclude '.env' \
    --exclude 'venv/' \
    --exclude '.git/' \
    --exclude '__pycache__/' \
    --exclude '*.pyc' \
    --exclude '*.db' \
    --exclude '.history/' \
    --exclude '.github/' \
    --exclude 'logs/' \
    -e "ssh -i $KEY_FILE" \
    ../ "$EC2_HOST":~/bitcoin-trading-bot/

print_step "✅ 파일 전송 완료"

# 4. DB 파일 전송 (선택)
print_warning "DB 파일을 전송하시겠습니까? (y/n)"
read -r answer
if [ "$answer" = "y" ]; then
    if [ -f "../upbit_bitcoin.db" ]; then
        print_step "DB 파일 전송 중..."
        scp -i "$KEY_FILE" ../upbit_bitcoin.db "$EC2_HOST":~/bitcoin-trading-bot/
        print_step "✅ DB 파일 전송 완료"
    else
        print_warning "DB 파일을 찾을 수 없습니다: ../upbit_bitcoin.db"
    fi
fi

# 5. 환경 설정 스크립트 실행
print_step "EC2 환경 설정 중... (시간이 걸릴 수 있습니다)"
ssh -i "$KEY_FILE" "$EC2_HOST" "cd ~/bitcoin-trading-bot/deployment && chmod +x setup_ec2.sh && ./setup_ec2.sh"

# 6. .env 파일 확인
print_warning ".env 파일을 수동으로 생성해야 합니다."
print_warning "다음 명령어를 실행하세요:"
echo ""
echo "  ssh -i $KEY_FILE $EC2_HOST"
echo "  nano ~/bitcoin-trading-bot/.env"
echo ""
echo "내용:"
echo "  UPBIT_ACCESS_KEY=..."
echo "  UPBIT_SECRET_KEY=..."
echo "  TELEGRAM_BOT_TOKEN=..."
echo "  TELEGRAM_CHAT_ID=..."
echo "  AUTO_TRADE=False"
echo ""

print_warning ".env 파일 생성을 완료했나요? (y/n)"
read -r env_answer
if [ "$env_answer" != "y" ]; then
    print_warning "배포를 중단합니다. .env 파일 생성 후 다시 실행하세요."
    exit 0
fi

# 7. systemd 서비스 설정
print_step "systemd 서비스 설정 중..."
ssh -i "$KEY_FILE" "$EC2_HOST" << 'EOF'
    sudo cp ~/bitcoin-trading-bot/deployment/bitcoin-trading-bot.service /etc/systemd/system/
    sudo systemctl daemon-reload
    sudo systemctl enable bitcoin-trading-bot
    sudo systemctl start bitcoin-trading-bot
EOF

print_step "✅ 서비스 시작 완료"

# 8. 서비스 상태 확인
print_step "서비스 상태 확인 중..."
ssh -i "$KEY_FILE" "$EC2_HOST" "sudo systemctl status bitcoin-trading-bot --no-pager"

# 9. 배포 완료
echo ""
echo "======================================"
echo -e "${GREEN}✅ 배포 완료!${NC}"
echo "======================================"
echo ""
echo "다음 명령어로 확인하세요:"
echo ""
echo "1. 서비스 상태:"
echo "   ssh -i $KEY_FILE $EC2_HOST \"sudo systemctl status bitcoin-trading-bot\""
echo ""
echo "2. 실시간 로그:"
echo "   ssh -i $KEY_FILE $EC2_HOST \"tail -f ~/bitcoin-trading-bot/logs/trading.log\""
echo ""
echo "3. 에러 로그:"
echo "   ssh -i $KEY_FILE $EC2_HOST \"tail -f ~/bitcoin-trading-bot/logs/error.log\""
echo ""
echo "4. 서비스 재시작:"
echo "   ssh -i $KEY_FILE $EC2_HOST \"sudo systemctl restart bitcoin-trading-bot\""
echo ""
