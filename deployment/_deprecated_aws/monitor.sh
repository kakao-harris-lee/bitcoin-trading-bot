#!/bin/bash

# EC2 모니터링 스크립트
# 사용법: ./monitor.sh <EC2_IP> <KEY_FILE>

set -e

# 색상 정의
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

print_header() {
    echo -e "${BLUE}======================================"
    echo -e "$1"
    echo -e "======================================${NC}"
}

print_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

# 인자 체크
if [ $# -lt 2 ]; then
    echo "사용법: ./monitor.sh <EC2_IP> <KEY_FILE>"
    exit 1
fi

EC2_IP=$1
KEY_FILE=$2
EC2_USER="ubuntu"
EC2_HOST="${EC2_USER}@${EC2_IP}"

# 메뉴 출력
show_menu() {
    clear
    print_header "Bitcoin Trading Bot - 모니터링"
    echo ""
    echo "1. 서비스 상태 확인"
    echo "2. 실시간 로그 보기"
    echo "3. 에러 로그 보기"
    echo "4. 시스템 리소스 확인"
    echo "5. 로그 파일 다운로드"
    echo "6. 서비스 재시작"
    echo "7. 서비스 중지"
    echo "8. 서비스 시작"
    echo "0. 종료"
    echo ""
    echo -n "선택: "
}

# 1. 서비스 상태
check_status() {
    print_header "서비스 상태"
    ssh -i "$KEY_FILE" "$EC2_HOST" "sudo systemctl status bitcoin-trading-bot --no-pager"
    echo ""
    read -p "계속하려면 Enter를 누르세요..."
}

# 2. 실시간 로그
view_log() {
    print_header "실시간 로그 (Ctrl+C로 종료)"
    ssh -i "$KEY_FILE" "$EC2_HOST" "tail -f ~/bitcoin-trading-bot/logs/trading.log"
}

# 3. 에러 로그
view_error_log() {
    print_header "에러 로그 (최근 50줄)"
    ssh -i "$KEY_FILE" "$EC2_HOST" "tail -n 50 ~/bitcoin-trading-bot/logs/error.log"
    echo ""
    read -p "계속하려면 Enter를 누르세요..."
}

# 4. 시스템 리소스
check_resources() {
    print_header "시스템 리소스"

    echo ""
    print_info "CPU 및 메모리 사용량:"
    ssh -i "$KEY_FILE" "$EC2_HOST" "top -bn1 | head -n 20"

    echo ""
    print_info "디스크 사용량:"
    ssh -i "$KEY_FILE" "$EC2_HOST" "df -h"

    echo ""
    print_info "메모리 상세:"
    ssh -i "$KEY_FILE" "$EC2_HOST" "free -h"

    echo ""
    read -p "계속하려면 Enter를 누르세요..."
}

# 5. 로그 다운로드
download_logs() {
    print_header "로그 파일 다운로드"

    LOCAL_LOG_DIR="./logs_$(date +%Y%m%d_%H%M%S)"
    mkdir -p "$LOCAL_LOG_DIR"

    print_info "다운로드 위치: $LOCAL_LOG_DIR"

    scp -i "$KEY_FILE" "$EC2_HOST":~/bitcoin-trading-bot/logs/trading.log "$LOCAL_LOG_DIR/"
    scp -i "$KEY_FILE" "$EC2_HOST":~/bitcoin-trading-bot/logs/error.log "$LOCAL_LOG_DIR/"

    print_info "✅ 다운로드 완료"
    echo ""
    read -p "계속하려면 Enter를 누르세요..."
}

# 6. 서비스 재시작
restart_service() {
    print_header "서비스 재시작"

    echo -n "정말 재시작하시겠습니까? (y/n): "
    read -r confirm

    if [ "$confirm" = "y" ]; then
        ssh -i "$KEY_FILE" "$EC2_HOST" "sudo systemctl restart bitcoin-trading-bot"
        print_info "✅ 재시작 완료"
        sleep 2
        ssh -i "$KEY_FILE" "$EC2_HOST" "sudo systemctl status bitcoin-trading-bot --no-pager"
    else
        print_info "취소됨"
    fi

    echo ""
    read -p "계속하려면 Enter를 누르세요..."
}

# 7. 서비스 중지
stop_service() {
    print_header "서비스 중지"

    echo -n "정말 중지하시겠습니까? (y/n): "
    read -r confirm

    if [ "$confirm" = "y" ]; then
        ssh -i "$KEY_FILE" "$EC2_HOST" "sudo systemctl stop bitcoin-trading-bot"
        print_info "✅ 중지 완료"
        sleep 1
        ssh -i "$KEY_FILE" "$EC2_HOST" "sudo systemctl status bitcoin-trading-bot --no-pager"
    else
        print_info "취소됨"
    fi

    echo ""
    read -p "계속하려면 Enter를 누르세요..."
}

# 8. 서비스 시작
start_service() {
    print_header "서비스 시작"

    ssh -i "$KEY_FILE" "$EC2_HOST" "sudo systemctl start bitcoin-trading-bot"
    print_info "✅ 시작 완료"
    sleep 2
    ssh -i "$KEY_FILE" "$EC2_HOST" "sudo systemctl status bitcoin-trading-bot --no-pager"

    echo ""
    read -p "계속하려면 Enter를 누르세요..."
}

# 메인 루프
while true; do
    show_menu
    read choice

    case $choice in
        1) check_status ;;
        2) view_log ;;
        3) view_error_log ;;
        4) check_resources ;;
        5) download_logs ;;
        6) restart_service ;;
        7) stop_service ;;
        8) start_service ;;
        0)
            echo "종료합니다."
            exit 0
            ;;
        *)
            echo "잘못된 선택입니다."
            sleep 1
            ;;
    esac
done
