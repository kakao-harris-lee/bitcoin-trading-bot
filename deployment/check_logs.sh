#!/bin/bash
# EC2 로그 확인 스크립트

SSH_KEY="$HOME/Development/private/aws/chihunlee_aws_key.pem"
EC2_HOST="ubuntu@13.218.242.96"

# 색상 정의
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}  비트코인 트레이딩 봇 로그 확인${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""
echo "1) 실시간 로그 (Ctrl+C로 종료)"
echo "2) 최근 50줄"
echo "3) 최근 100줄"
echo "4) 오늘 로그"
echo "5) 최근 1시간"
echo "6) 신호 체크만 보기"
echo "7) 에러만 보기"
echo "8) 서비스 상태"
echo "9) Paper Trading 거래 이력"
echo ""
read -p "선택하세요 (1-9): " choice

case $choice in
    1)
        echo -e "\n${GREEN}📊 실시간 로그 확인 중... (Ctrl+C로 종료)${NC}\n"
        ssh -i "$SSH_KEY" "$EC2_HOST" "sudo journalctl -u bitcoin-trading-bot -f"
        ;;
    2)
        echo -e "\n${GREEN}📊 최근 50줄 로그${NC}\n"
        ssh -i "$SSH_KEY" "$EC2_HOST" "sudo journalctl -u bitcoin-trading-bot -n 50 --no-pager"
        ;;
    3)
        echo -e "\n${GREEN}📊 최근 100줄 로그${NC}\n"
        ssh -i "$SSH_KEY" "$EC2_HOST" "sudo journalctl -u bitcoin-trading-bot -n 100 --no-pager"
        ;;
    4)
        echo -e "\n${GREEN}📊 오늘 로그${NC}\n"
        ssh -i "$SSH_KEY" "$EC2_HOST" "sudo journalctl -u bitcoin-trading-bot --since today --no-pager"
        ;;
    5)
        echo -e "\n${GREEN}📊 최근 1시간 로그${NC}\n"
        ssh -i "$SSH_KEY" "$EC2_HOST" "sudo journalctl -u bitcoin-trading-bot --since '1 hour ago' --no-pager"
        ;;
    6)
        echo -e "\n${GREEN}📊 신호 체크 로그만${NC}\n"
        ssh -i "$SSH_KEY" "$EC2_HOST" "sudo journalctl -u bitcoin-trading-bot --no-pager | grep -E '🔍|신호|BUY|SELL|매수|매도' | tail -50"
        ;;
    7)
        echo -e "\n${RED}❌ 에러 로그만${NC}\n"
        ssh -i "$SSH_KEY" "$EC2_HOST" "sudo journalctl -u bitcoin-trading-bot --no-pager | grep -E '❌|ERROR|Error|error|실패|Failed' | tail -50"
        ;;
    8)
        echo -e "\n${GREEN}📊 서비스 상태${NC}\n"
        ssh -i "$SSH_KEY" "$EC2_HOST" "sudo systemctl status bitcoin-trading-bot"
        ;;
    9)
        echo -e "\n${GREEN}📊 Paper Trading 거래 이력${NC}\n"
        ssh -i "$SSH_KEY" "$EC2_HOST" "cat bitcoin-trading-bot/live_trading/paper_trading_history.json"
        ;;
    *)
        echo -e "\n${RED}잘못된 선택입니다.${NC}"
        exit 1
        ;;
esac
