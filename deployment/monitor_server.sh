#!/bin/bash

################################################################################
# 서버 모니터링 스크립트
# 사용법: ./monitor_server.sh
################################################################################

SERVER_USER="deploy"
SERVER_HOST="49.247.171.64"
SERVER_PATH="/home/deploy/bitcoin-trading-bot"
SSH_CONN="${SERVER_USER}@${SERVER_HOST}"

# 색상 정의
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m'

print_header() {
    echo ""
    echo "========================================="
    echo "  $1"
    echo "========================================="
}

while true; do
    clear
    print_header "Bitcoin Trading Bot - 서버 모니터링"
    echo "서버: ${SERVER_HOST}"
    echo "시간: $(date '+%Y-%m-%d %H:%M:%S')"
    echo ""

    echo "1. 실시간 로그"
    echo "2. 컨테이너 상태"
    echo "3. 시스템 리소스"
    echo "4. 최근 에러 로그"
    echo "5. 컨테이너 재시작"
    echo "6. 컨테이너 중지"
    echo "7. 컨테이너 시작"
    echo "8. 서버 SSH 접속"
    echo "9. 종료"
    echo ""

    read -p "선택 (1-9): " choice

    case $choice in
        1)
            echo ""
            echo "실시간 로그 (Ctrl+C로 중단):"
            echo "========================================="
            ssh ${SSH_CONN} "cd ${SERVER_PATH} && docker compose logs -f --tail=100"
            ;;
        2)
            echo ""
            echo "컨테이너 상태:"
            echo "========================================="
            ssh ${SSH_CONN} "cd ${SERVER_PATH} && docker compose ps"
            echo ""
            read -p "계속하려면 Enter를 누르세요..."
            ;;
        3)
            echo ""
            echo "시스템 리소스:"
            echo "========================================="
            ssh ${SSH_CONN} "
                echo '--- CPU 사용률 ---'
                top -bn1 | grep 'Cpu(s)' | awk '{print \"CPU: \" \$2 + \$4 \"%\"}'
                echo ''
                echo '--- 메모리 사용 ---'
                free -h
                echo ''
                echo '--- 디스크 사용 ---'
                df -h | grep -E '^/dev/'
                echo ''
                echo '--- Docker 리소스 ---'
                cd ${SERVER_PATH} && docker compose stats --no-stream
            "
            echo ""
            read -p "계속하려면 Enter를 누르세요..."
            ;;
        4)
            echo ""
            echo "최근 에러 로그 (최근 50줄):"
            echo "========================================="
            ssh ${SSH_CONN} "cd ${SERVER_PATH} && docker compose logs --tail=50 | grep -i error || echo '에러 없음'"
            echo ""
            read -p "계속하려면 Enter를 누르세요..."
            ;;
        5)
            echo ""
            echo "컨테이너 재시작 중..."
            ssh ${SSH_CONN} "cd ${SERVER_PATH} && docker compose restart"
            echo "재시작 완료!"
            sleep 2
            ;;
        6)
            echo ""
            read -p "정말 중지하시겠습니까? (y/n): " confirm
            if [ "$confirm" = "y" ]; then
                ssh ${SSH_CONN} "cd ${SERVER_PATH} && docker compose down"
                echo "컨테이너 중지 완료"
            fi
            sleep 2
            ;;
        7)
            echo ""
            echo "컨테이너 시작 중..."
            ssh ${SSH_CONN} "cd ${SERVER_PATH} && docker compose up -d"
            echo "시작 완료!"
            sleep 2
            ;;
        8)
            echo ""
            echo "서버 SSH 접속..."
            ssh ${SSH_CONN} "cd ${SERVER_PATH} && bash"
            ;;
        9)
            echo ""
            echo "모니터링을 종료합니다."
            exit 0
            ;;
        *)
            echo ""
            echo "잘못된 선택입니다."
            sleep 1
            ;;
    esac
done
