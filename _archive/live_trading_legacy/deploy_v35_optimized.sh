#!/bin/bash

################################################################################
# v35 Optuna 최적화 버전 배포 스크립트
#
# 사용법:
#   ./deploy_v35_optimized.sh [mode]
#
# mode:
#   paper    - Paper Trading (모의 거래, 기본값)
#   live     - 실거래 (주의!)
################################################################################

set -e  # 에러 시 중단

# 색상 정의
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 모드 설정
MODE=${1:-paper}

echo -e "${BLUE}=================================${NC}"
echo -e "${BLUE}  v35 Optuna 최적화 버전 배포${NC}"
echo -e "${BLUE}=================================${NC}"
echo ""

# 1. 환경 확인
echo -e "${YELLOW}[1/6] 환경 확인${NC}"

# Python 확인
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}❌ Python3가 설치되지 않았습니다${NC}"
    exit 1
fi
echo -e "${GREEN}✅ Python3: $(python3 --version)${NC}"

# .env 파일 확인
if [ ! -f "../.env" ]; then
    echo -e "${RED}❌ .env 파일이 없습니다${NC}"
    echo -e "${YELLOW}다음 내용을 포함한 .env 파일을 생성하세요:${NC}"
    echo "  UPBIT_ACCESS_KEY=your_access_key"
    echo "  UPBIT_SECRET_KEY=your_secret_key"
    echo "  TELEGRAM_BOT_TOKEN=your_bot_token"
    echo "  TELEGRAM_CHAT_ID=your_chat_id"
    exit 1
fi
echo -e "${GREEN}✅ .env 파일 존재${NC}"

# config_optimized.json 확인
CONFIG_PATH="../strategies/v35_optimized/config_optimized.json"
if [ ! -f "$CONFIG_PATH" ]; then
    echo -e "${RED}❌ config_optimized.json 파일이 없습니다${NC}"
    exit 1
fi
echo -e "${GREEN}✅ config_optimized.json 존재${NC}"

# 2. 설정 확인
echo ""
echo -e "${YELLOW}[2/6] 설정 확인${NC}"

# config 내용 출력
echo -e "${BLUE}포지션 크기:${NC} $(grep -A 1 'position_sizing' $CONFIG_PATH | grep 'position_size' | awk -F: '{print $2}' | tr -d ' ,')"
echo -e "${BLUE}Stop Loss:${NC} $(grep 'stop_loss' $CONFIG_PATH | awk -F: '{print $2}' | tr -d ' ,')"

# 3. 모드 확인
echo ""
echo -e "${YELLOW}[3/6] 배포 모드 확인${NC}"

if [ "$MODE" = "paper" ]; then
    echo -e "${GREEN}📄 Paper Trading 모드 (모의 거래)${NC}"
    echo -e "${BLUE}   - 초기 자본: 1,000,000 KRW${NC}"
    echo -e "${BLUE}   - 실제 거래 없음${NC}"
    TRADING_MODE="--paper --capital 1000000"
elif [ "$MODE" = "live" ]; then
    echo -e "${RED}⚠️  실거래 모드${NC}"
    echo -e "${YELLOW}   실제 자금이 사용됩니다!${NC}"

    # 실거래 확인
    read -p "정말로 실거래를 시작하시겠습니까? (yes 입력): " confirm
    if [ "$confirm" != "yes" ]; then
        echo -e "${YELLOW}배포 취소됨${NC}"
        exit 0
    fi
    TRADING_MODE=""
else
    echo -e "${RED}❌ 잘못된 모드: $MODE${NC}"
    echo "사용 가능한 모드: paper, live"
    exit 1
fi

# 4. 백테스팅 결과 확인
echo ""
echo -e "${YELLOW}[4/6] 백테스팅 결과 확인${NC}"

BACKTEST_FILE="../strategies/v35_optimized/backtest_results_before_optuna.json"
if [ -f "$BACKTEST_FILE" ]; then
    RETURN_2025=$(grep -A 1 '"2025"' $BACKTEST_FILE | grep 'total_return' | head -1 | awk -F: '{print $2}' | tr -d ' ,')
    echo -e "${GREEN}✅ 2025년 백테스팅 수익률: ${RETURN_2025}%${NC}"
else
    echo -e "${YELLOW}⚠️  백테스팅 결과 없음${NC}"
fi

# 5. 연결 테스트
echo ""
echo -e "${YELLOW}[5/6] 연결 테스트${NC}"

if [ "$MODE" = "live" ]; then
    echo -e "${BLUE}Upbit API 연결 테스트 중...${NC}"
    python3 test_connection.py
    if [ $? -ne 0 ]; then
        echo -e "${RED}❌ Upbit 연결 실패${NC}"
        exit 1
    fi
    echo -e "${GREEN}✅ Upbit 연결 성공${NC}"
fi

# 6. 배포 실행
echo ""
echo -e "${YELLOW}[6/6] 트레이딩 봇 시작${NC}"

# 로그 디렉토리 생성
mkdir -p logs

# 현재 시각
NOW=$(date +"%Y%m%d_%H%M%S")
LOG_FILE="logs/trading_${MODE}_${NOW}.log"

echo -e "${BLUE}로그 파일: $LOG_FILE${NC}"
echo ""

# 트레이딩 봇 실행
echo -e "${GREEN}🚀 트레이딩 봇 시작!${NC}"
echo -e "${BLUE}중지하려면 Ctrl+C를 누르세요${NC}"
echo ""

# Python 실행
python3 main.py $TRADING_MODE 2>&1 | tee $LOG_FILE

# 종료 처리
echo ""
echo -e "${YELLOW}트레이딩 봇이 종료되었습니다${NC}"
echo -e "${BLUE}로그 파일: $LOG_FILE${NC}"
