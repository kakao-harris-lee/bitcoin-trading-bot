#!/bin/bash

###############################################################################
# Paper Trading 모니터링 스크립트
# Paper Trading 성과 실시간 모니터링
###############################################################################

set -e

# 색상 정의
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# 사용법
if [ "$#" -lt 2 ]; then
    echo "사용법: $0 <EC2_IP> <KEY_FILE>"
    echo "예시: $0 13.218.242.96 ~/Downloads/bitcoin-trading-bot-key.pem"
    exit 1
fi

EC2_IP=$1
KEY_FILE=$2

# SSH 명령 기본값
SSH_CMD="ssh -i $KEY_FILE ubuntu@$EC2_IP"

###############################################################################
# 함수 정의
###############################################################################

# Paper Trading 이력 조회
show_trading_history() {
    echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${CYAN}📊 Paper Trading 이력${NC}"
    echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

    $SSH_CMD "cat ~/bitcoin-trading-bot/live_trading/paper_trading_history.json 2>/dev/null" | python3 -m json.tool || echo "이력 파일 없음"

    echo ""
    read -p "계속하려면 Enter..."
}

# 성과 요약
show_performance_summary() {
    echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${CYAN}💰 Paper Trading 성과 요약${NC}"
    echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

    $SSH_CMD "cd ~/bitcoin-trading-bot/live_trading && python3 << 'EOF'
import json
import os

history_file = 'paper_trading_history.json'

if not os.path.exists(history_file):
    print('❌ Paper Trading 이력 없음')
    exit()

with open(history_file, 'r') as f:
    data = json.load(f)

initial = data.get('initial_capital', 0)
cash = data.get('cash', 0)
btc = data.get('btc_balance', 0)
trades = data.get('trades', [])

# 거래 통계
sell_trades = [t for t in trades if t['type'] == 'SELL']
total_trades = len(sell_trades)
winning = len([t for t in sell_trades if t.get('profit', 0) > 0])
losing = len([t for t in sell_trades if t.get('profit', 0) <= 0])
win_rate = (winning / total_trades * 100) if total_trades > 0 else 0

# 총 수익
total_profit = sum([t.get('profit', 0) for t in sell_trades])
total_return = (total_profit / initial * 100) if initial > 0 else 0

# 평균 수익률
avg_profit_pct = sum([t.get('profit_pct', 0) for t in sell_trades]) / total_trades if total_trades > 0 else 0

# 현재 포지션
has_position = data.get('position') is not None
position_info = '보유 중' if has_position else '없음'

print(f\"\"\"
💰 초기 자본: {initial:,.0f} KRW
💵 현재 잔고: {cash:,.0f} KRW
📊 BTC 잔고: {btc:.8f} BTC
💎 현재 포지션: {position_info}

📈 총 거래: {total_trades}회
✅ 승리: {winning}회
❌ 손실: {losing}회
🎯 승률: {win_rate:.1f}%

💰 총 수익: {total_profit:+,.0f} KRW
📊 총 수익률: {total_return:+.2f}%
📉 평균 수익률: {avg_profit_pct:+.2f}%
\"\"\")

# 최근 거래
if sell_trades:
    print('\\n📋 최근 거래 (최대 5개):')
    print('-' * 60)
    for trade in sell_trades[-5:]:
        profit = trade.get('profit', 0)
        profit_pct = trade.get('profit_pct', 0)
        time = trade.get('time', 'N/A')
        price = trade.get('price', 0)
        reason = trade.get('exit_reason', 'N/A')

        profit_symbol = '✅' if profit > 0 else '❌'
        print(f\"{profit_symbol} {time} | {price:,.0f} KRW | {profit:+,.0f} ({profit_pct:+.2f}%) | {reason}\")

EOF
"

    echo ""
    read -p "계속하려면 Enter..."
}

# 실시간 로그
show_live_logs() {
    echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${CYAN}📜 실시간 로그 (Ctrl+C로 종료)${NC}"
    echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

    $SSH_CMD "tail -f ~/bitcoin-trading-bot/logs/trading.log"
}

# 에러 로그
show_error_logs() {
    echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${CYAN}❌ 에러 로그 (최근 50줄)${NC}"
    echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

    $SSH_CMD "tail -50 ~/bitcoin-trading-bot/logs/error.log 2>/dev/null || echo '에러 로그 없음'"

    echo ""
    read -p "계속하려면 Enter..."
}

# 서비스 상태
show_service_status() {
    echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${CYAN}🔧 서비스 상태${NC}"
    echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

    $SSH_CMD "sudo systemctl status bitcoin-trading-bot --no-pager" || true

    echo ""
    echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

    read -p "계속하려면 Enter..."
}

# 일일 리포트 생성
generate_daily_report() {
    echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${CYAN}📊 일일 리포트 생성 중...${NC}"
    echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

    REPORT_FILE="paper_trading_report_$(date +%Y%m%d).txt"

    {
        echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        echo "📊 Paper Trading 일일 리포트"
        echo "생성일시: $(date '+%Y-%m-%d %H:%M:%S')"
        echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        echo ""

        # 성과 요약
        $SSH_CMD "cd ~/bitcoin-trading-bot/live_trading && python3 << 'EOF'
import json
import os
from datetime import datetime, timedelta

history_file = 'paper_trading_history.json'

if not os.path.exists(history_file):
    print('❌ Paper Trading 이력 없음')
    exit()

with open(history_file, 'r') as f:
    data = json.load(f)

initial = data.get('initial_capital', 0)
cash = data.get('cash', 0)
trades = data.get('trades', [])

sell_trades = [t for t in trades if t['type'] == 'SELL']
total_trades = len(sell_trades)
winning = len([t for t in sell_trades if t.get('profit', 0) > 0])
losing = len([t for t in sell_trades if t.get('profit', 0) <= 0])
win_rate = (winning / total_trades * 100) if total_trades > 0 else 0

total_profit = sum([t.get('profit', 0) for t in sell_trades])
total_return = (total_profit / initial * 100) if initial > 0 else 0

# 오늘 거래
today = datetime.now().strftime('%Y-%m-%d')
today_trades = [t for t in sell_trades if t.get('time', '').startswith(today)]
today_profit = sum([t.get('profit', 0) for t in today_trades])

print(f\"\"\"
💰 초기 자본: {initial:,.0f} KRW
💵 현재 잔고: {cash:,.0f} KRW

📈 총 거래: {total_trades}회 (오늘: {len(today_trades)}회)
✅ 승리: {winning}회
❌ 손실: {losing}회
🎯 승률: {win_rate:.1f}%

💰 총 수익: {total_profit:+,.0f} KRW
📊 총 수익률: {total_return:+.2f}%
💵 오늘 수익: {today_profit:+,.0f} KRW
\"\"\")
EOF
"

        echo ""
        echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

    } | tee "$REPORT_FILE"

    echo -e "${GREEN}✅ 리포트 저장: $REPORT_FILE${NC}"
    echo ""
    read -p "계속하려면 Enter..."
}

# 서비스 재시작
restart_service() {
    echo -e "${YELLOW}⚠️  서비스를 재시작하시겠습니까? (y/N)${NC}"
    read -p "> " confirm

    if [ "$confirm" = "y" ] || [ "$confirm" = "Y" ]; then
        echo -e "${CYAN}🔄 서비스 재시작 중...${NC}"
        $SSH_CMD "sudo systemctl restart bitcoin-trading-bot"
        sleep 2
        echo -e "${GREEN}✅ 재시작 완료${NC}"
        show_service_status
    else
        echo "취소됨"
        sleep 1
    fi
}

# 이력 초기화
reset_history() {
    echo -e "${RED}⚠️  경고: Paper Trading 이력을 완전히 삭제합니다!${NC}"
    echo -e "${RED}⚠️  이 작업은 되돌릴 수 없습니다!${NC}"
    echo ""
    echo -e "${YELLOW}정말 초기화하시겠습니까? (yes 입력 필요)${NC}"
    read -p "> " confirm

    if [ "$confirm" = "yes" ]; then
        echo -e "${CYAN}🔄 이력 초기화 중...${NC}"
        $SSH_CMD "rm -f ~/bitcoin-trading-bot/live_trading/paper_trading_history.json"
        $SSH_CMD "sudo systemctl restart bitcoin-trading-bot"
        sleep 2
        echo -e "${GREEN}✅ 초기화 완료${NC}"
    else
        echo "취소됨"
    fi

    sleep 2
}

###############################################################################
# 메인 메뉴
###############################################################################

show_menu() {
    clear
    echo -e "${CYAN}"
    cat << "EOF"
╔═══════════════════════════════════════════════════════════════╗
║                                                               ║
║        📊 Paper Trading 모니터링 대시보드                      ║
║        Multi-Strategy Trading System                         ║
║                                                               ║
╚═══════════════════════════════════════════════════════════════╝
EOF
    echo -e "${NC}"

    echo -e "${GREEN}EC2:${NC} $EC2_IP"
    echo ""

    echo "1. 📊 성과 요약"
    echo "2. 📋 거래 이력"
    echo "3. 📜 실시간 로그"
    echo "4. ❌ 에러 로그"
    echo "5. 🔧 서비스 상태"
    echo "6. 📄 일일 리포트 생성"
    echo "7. 🔄 서비스 재시작"
    echo "8. 🗑️  이력 초기화"
    echo "0. 종료"
    echo ""
    echo -n "선택: "
}

# 메인 루프
while true; do
    show_menu
    read choice

    case $choice in
        1) show_performance_summary ;;
        2) show_trading_history ;;
        3) show_live_logs ;;
        4) show_error_logs ;;
        5) show_service_status ;;
        6) generate_daily_report ;;
        7) restart_service ;;
        8) reset_history ;;
        0)
            echo -e "${GREEN}👋 종료합니다${NC}"
            exit 0
            ;;
        *)
            echo -e "${RED}잘못된 선택입니다${NC}"
            sleep 1
            ;;
    esac
done
