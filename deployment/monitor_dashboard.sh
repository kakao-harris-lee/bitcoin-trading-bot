#!/bin/bash
# EC2 트레이딩 봇 모니터링 대시보드

SSH_KEY="$HOME/Development/private/aws/chihunlee_aws_key.pem"
EC2_HOST="ubuntu@13.218.242.96"

# 색상 정의
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
MAGENTA='\033[0;35m'
NC='\033[0m' # No Color

clear

echo -e "${BLUE}╔════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║       비트코인 트레이딩 봇 모니터링 대시보드              ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════════════════════════╝${NC}"
echo ""

# 1. 서비스 상태
echo -e "${CYAN}📊 서비스 상태${NC}"
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
ssh -i "$SSH_KEY" "$EC2_HOST" "sudo systemctl status bitcoin-trading-bot --no-pager | head -10"
echo ""

# 2. 시스템 리소스
echo -e "${CYAN}💻 시스템 리소스${NC}"
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
ssh -i "$SSH_KEY" "$EC2_HOST" "free -h | grep Mem && df -h | grep -E 'Filesystem|/$' && uptime"
echo ""

# 3. 최근 신호 체크 (최근 5개)
echo -e "${CYAN}🔍 최근 신호 체크${NC}"
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
ssh -i "$SSH_KEY" "$EC2_HOST" "sudo journalctl -u bitcoin-trading-bot --no-pager | grep '🔍 신호 체크' | tail -5"
echo ""

# 4. Paper Trading 요약
echo -e "${CYAN}💰 Paper Trading 현황${NC}"
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
ssh -i "$SSH_KEY" "$EC2_HOST" "if [ -f bitcoin-trading-bot/live_trading/paper_trading_history.json ]; then
    cat bitcoin-trading-bot/live_trading/paper_trading_history.json | python3 -c '
import json, sys
data = json.load(sys.stdin)
print(f\"초기 자본: {data.get(\\\"initial_capital\\\", 0):,.0f} KRW\")
print(f\"현재 잔고: {data.get(\\\"cash\\\", 0):,.0f} KRW\")
print(f\"BTC 보유: {data.get(\\\"btc_balance\\\", 0):.8f} BTC\")
print(f\"총 거래: {len(data.get(\\\"trades\\\", []))}건\")
print(f\"마지막 업데이트: {data.get(\\\"last_updated\\\", \\\"N/A\\\")}\")
    '
else
    echo '거래 이력 없음'
fi"
echo ""

# 5. 최근 에러 (있는 경우)
echo -e "${CYAN}⚠️  최근 에러 (최근 3개)${NC}"
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
ERROR_COUNT=$(ssh -i "$SSH_KEY" "$EC2_HOST" "sudo journalctl -u bitcoin-trading-bot --since '1 hour ago' --no-pager | grep -c -E '❌|ERROR|error' || echo 0")

if [ "$ERROR_COUNT" -gt 0 ]; then
    echo -e "${RED}최근 1시간 에러 수: $ERROR_COUNT${NC}"
    ssh -i "$SSH_KEY" "$EC2_HOST" "sudo journalctl -u bitcoin-trading-bot --since '1 hour ago' --no-pager | grep -E '❌|ERROR|error' | tail -3"
else
    echo -e "${GREEN}✅ 최근 1시간 에러 없음${NC}"
fi
echo ""

# 6. 명령어 안내
echo -e "${BLUE}╔════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║  유용한 명령어                                             ║${NC}"
echo -e "${BLUE}╠════════════════════════════════════════════════════════════╣${NC}"
echo -e "${BLUE}║  실시간 로그: ./check_logs.sh 선택 1                       ║${NC}"
echo -e "${BLUE}║  거래 이력:   ./check_logs.sh 선택 9                       ║${NC}"
echo -e "${BLUE}║  재시작:      ssh ... 'sudo systemctl restart ...'         ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════════════════════════╝${NC}"
