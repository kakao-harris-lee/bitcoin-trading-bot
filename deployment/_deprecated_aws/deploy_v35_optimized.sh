#!/bin/bash

################################################################################
# v35 Optuna 최적화 버전 AWS EC2 배포 스크립트
#
# 사용법: ./deploy_v35_optimized.sh <EC2_IP> <KEY_FILE>
# 예시: ./deploy_v35_optimized.sh 13.125.123.456 ~/Downloads/bitcoin-trading-bot-key.pem
################################################################################

set -e

# 색상 정의
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
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

print_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

# 인자 체크
if [ $# -lt 2 ]; then
    print_error "사용법: ./deploy_v35_optimized.sh <EC2_IP> <KEY_FILE>"
    echo "예시: ./deploy_v35_optimized.sh 13.125.123.456 ~/Downloads/bitcoin-trading-bot-key.pem"
    exit 1
fi

EC2_IP=$1
KEY_FILE=$2
EC2_USER="ubuntu"
EC2_HOST="${EC2_USER}@${EC2_IP}"

echo ""
echo "======================================"
echo "  v35 Optuna 최적화 버전 배포"
echo "======================================"
echo "  EC2 IP: $EC2_IP"
echo "  버전: v35 Optimized (Trial 99)"
echo "  예상 2025 수익률: +23.16%"
echo "======================================"
echo ""

# 키 파일 존재 확인
if [ ! -f "$KEY_FILE" ]; then
    print_error "키 파일을 찾을 수 없습니다: $KEY_FILE"
    exit 1
fi

# 키 파일 권한 확인
if [ "$(stat -f %A "$KEY_FILE" 2>/dev/null || stat -c %a "$KEY_FILE")" != "400" ]; then
    print_warning "키 파일 권한을 400으로 변경합니다"
    chmod 400 "$KEY_FILE"
fi

# 1. 연결 테스트
print_step "[1/10] EC2 연결 테스트 중..."
if ! ssh -i "$KEY_FILE" -o ConnectTimeout=10 "$EC2_HOST" "echo 'Connected'" > /dev/null 2>&1; then
    print_error "EC2 연결 실패. IP와 키 파일을 확인하세요."
    exit 1
fi
print_step "✅ 연결 성공"

# 2. 기존 서비스 중지
print_step "[2/10] 기존 서비스 중지 중..."
ssh -i "$KEY_FILE" "$EC2_HOST" << 'EOF'
    # 모든 bitcoin-trading-bot 서비스 중지
    if systemctl list-units --full --all | grep -q "bitcoin-trading-bot"; then
        echo "기존 서비스 중지 중..."
        sudo systemctl stop bitcoin-trading-bot 2>/dev/null || true
        sudo systemctl stop bitcoin-trading-bot-paper 2>/dev/null || true
        sudo systemctl disable bitcoin-trading-bot 2>/dev/null || true
        sudo systemctl disable bitcoin-trading-bot-paper 2>/dev/null || true
        echo "✅ 기존 서비스 중지 완료"
    else
        echo "기존 서비스 없음"
    fi
EOF

print_step "✅ 기존 서비스 중지 완료"

# 3. 백업 생성
print_step "[3/10] 기존 배포 백업 중..."
BACKUP_DATE=$(date +"%Y%m%d_%H%M%S")
ssh -i "$KEY_FILE" "$EC2_HOST" << EOF
    if [ -d ~/bitcoin-trading-bot ]; then
        echo "기존 디렉토리 백업 중..."
        mv ~/bitcoin-trading-bot ~/bitcoin-trading-bot.backup.$BACKUP_DATE
        echo "✅ 백업 완료: ~/bitcoin-trading-bot.backup.$BACKUP_DATE"
    else
        echo "기존 배포 없음"
    fi
EOF

print_step "✅ 백업 완료"

# 4. 프로젝트 디렉토리 생성
print_step "[4/10] 프로젝트 디렉토리 생성 중..."
ssh -i "$KEY_FILE" "$EC2_HOST" "mkdir -p ~/bitcoin-trading-bot"

# 5. 파일 전송
print_step "[5/10] 프로젝트 파일 전송 중..."
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
    --exclude 'strategies/*/signals/' \
    --exclude 'strategies/*/results/' \
    -e "ssh -i $KEY_FILE" \
    ../ "$EC2_HOST":~/bitcoin-trading-bot/

print_step "✅ 파일 전송 완료"

# 6. config_optimized.json 존재 확인
print_step "[6/10] 최적화 설정 파일 확인 중..."
if ! ssh -i "$KEY_FILE" "$EC2_HOST" "[ -f ~/bitcoin-trading-bot/strategies/v35_optimized/config_optimized.json ]"; then
    print_error "config_optimized.json 파일이 없습니다!"
    exit 1
fi
print_step "✅ config_optimized.json 확인 완료"

# 7. DB 파일 전송 (선택)
print_warning "[7/10] DB 파일을 전송하시겠습니까? (y/n)"
read -r answer
if [ "$answer" = "y" ]; then
    if [ -f "../upbit_bitcoin.db" ]; then
        print_step "DB 파일 전송 중..."
        scp -i "$KEY_FILE" ../upbit_bitcoin.db "$EC2_HOST":~/bitcoin-trading-bot/
        print_step "✅ DB 파일 전송 완료"
    else
        print_warning "DB 파일을 찾을 수 없습니다: ../upbit_bitcoin.db"
    fi
else
    print_info "DB 파일 전송 스킵"
fi

# 8. 환경 설정
print_step "[8/10] EC2 환경 설정 중..."
ssh -i "$KEY_FILE" "$EC2_HOST" "cd ~/bitcoin-trading-bot/deployment && chmod +x setup_ec2.sh && ./setup_ec2.sh"
print_step "✅ 환경 설정 완료"

# 9. .env 파일 확인
print_warning "[9/10] .env 파일을 확인합니다..."
if ssh -i "$KEY_FILE" "$EC2_HOST" "[ -f ~/bitcoin-trading-bot/.env ]"; then
    print_info ".env 파일이 이미 존재합니다."
    print_warning ".env 파일을 업데이트하시겠습니까? (y/n)"
    read -r env_update
    if [ "$env_update" = "y" ]; then
        print_warning "SSH로 접속하여 .env 파일을 편집하세요:"
        echo ""
        echo "  ssh -i $KEY_FILE $EC2_HOST"
        echo "  nano ~/bitcoin-trading-bot/.env"
        echo ""
        echo "필수 내용:"
        echo "  UPBIT_ACCESS_KEY=..."
        echo "  UPBIT_SECRET_KEY=..."
        echo "  TELEGRAM_BOT_TOKEN=..."
        echo "  TELEGRAM_CHAT_ID=..."
        echo ""
        echo "선택 (바이낸스 헤지 사용 시):"
        echo "  BINANCE_API_KEY=..."
        echo "  BINANCE_API_SECRET=..."
        echo ""
        print_warning ".env 파일 업데이트를 완료했나요? (y/n)"
        read -r env_done
        if [ "$env_done" != "y" ]; then
            print_warning "배포를 중단합니다."
            exit 0
        fi
    fi
else
    print_error ".env 파일이 없습니다!"
    print_warning "SSH로 접속하여 .env 파일을 생성하세요:"
    echo ""
    echo "  ssh -i $KEY_FILE $EC2_HOST"
    echo "  nano ~/bitcoin-trading-bot/.env"
    echo ""
    print_warning ".env 파일 생성을 완료했나요? (y/n)"
    read -r env_create
    if [ "$env_create" != "y" ]; then
        print_warning "배포를 중단합니다."
        exit 0
    fi
fi

# 10. systemd 서비스 업데이트 및 시작
print_step "[10/10] systemd 서비스 설정 중..."

# 새 서비스 파일 생성
ssh -i "$KEY_FILE" "$EC2_HOST" << 'EOF'
cat > ~/bitcoin-trading-bot/deployment/bitcoin-trading-bot-v35-optimized.service << 'SERVICE'
[Unit]
Description=Bitcoin Trading Bot v35 Optimized (Optuna Trial 99)
After=network.target
Wants=network-online.target

[Service]
Type=simple
User=ubuntu
Group=ubuntu
WorkingDirectory=/home/ubuntu/bitcoin-trading-bot/live_trading
Environment="PATH=/home/ubuntu/bitcoin-trading-bot/venv/bin:/usr/local/bin:/usr/bin:/bin"
Environment="PYTHONUNBUFFERED=1"
ExecStart=/home/ubuntu/bitcoin-trading-bot/venv/bin/python main.py --auto
Restart=always
RestartSec=10
StandardOutput=append:/home/ubuntu/bitcoin-trading-bot/logs/trading.log
StandardError=append:/home/ubuntu/bitcoin-trading-bot/logs/error.log

# 보안 설정
NoNewPrivileges=true
PrivateTmp=true

# 리소스 제한
LimitNOFILE=65536
CPUQuota=80%
MemoryLimit=1G

[Install]
WantedBy=multi-user.target
SERVICE

sudo cp ~/bitcoin-trading-bot/deployment/bitcoin-trading-bot-v35-optimized.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable bitcoin-trading-bot-v35-optimized
sudo systemctl start bitcoin-trading-bot-v35-optimized
EOF

print_step "✅ 서비스 시작 완료"

# 서비스 상태 확인
echo ""
print_step "서비스 상태 확인 중..."
sleep 3
ssh -i "$KEY_FILE" "$EC2_HOST" "sudo systemctl status bitcoin-trading-bot-v35-optimized --no-pager -l"

# 배포 완료
echo ""
echo "======================================"
echo -e "${GREEN}✅ v35 Optuna 배포 완료!${NC}"
echo "======================================"
echo ""
echo "📊 배포 정보:"
echo "  - 버전: v35 Optimized (Trial 99)"
echo "  - 설정: config_optimized.json"
echo "  - 예상 2025 수익률: +23.16%"
echo "  - Sharpe Ratio: 2.62"
echo "  - MDD: -2.39%"
echo ""
echo "🔧 유용한 명령어:"
echo ""
echo "1. 서비스 상태:"
echo "   ssh -i $KEY_FILE $EC2_HOST \"sudo systemctl status bitcoin-trading-bot-v35-optimized\""
echo ""
echo "2. 실시간 로그:"
echo "   ssh -i $KEY_FILE $EC2_HOST \"tail -f ~/bitcoin-trading-bot/logs/trading.log\""
echo ""
echo "3. 에러 로그:"
echo "   ssh -i $KEY_FILE $EC2_HOST \"tail -f ~/bitcoin-trading-bot/logs/error.log\""
echo ""
echo "4. 서비스 재시작:"
echo "   ssh -i $KEY_FILE $EC2_HOST \"sudo systemctl restart bitcoin-trading-bot-v35-optimized\""
echo ""
echo "5. 서비스 중지:"
echo "   ssh -i $KEY_FILE $EC2_HOST \"sudo systemctl stop bitcoin-trading-bot-v35-optimized\""
echo ""
echo "6. 로그 실시간 모니터링:"
echo "   ssh -i $KEY_FILE $EC2_HOST"
echo "   cd ~/bitcoin-trading-bot/deployment"
echo "   ./monitor.sh"
echo ""
echo "⚠️  주의사항:"
echo "  - Paper Trading 모드에서 테스트 후 실거래로 전환하세요"
echo "  - .env 파일의 AUTO_TRADE=True 설정 확인"
echo "  - 텔레그램 알림 설정 확인"
echo ""
