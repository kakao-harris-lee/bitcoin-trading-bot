#!/bin/bash

# 비트코인 트레이딩 봇 웹 대시보드 실행 스크립트

set -e

# 색상 정의
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${BLUE}======================================"
echo "🤖 Bitcoin Trading Bot Dashboard"
echo -e "======================================${NC}"
echo ""

# 현재 디렉토리 확인
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

# DB 파일 확인
if [ ! -f "../trading_results.db" ]; then
    echo -e "${YELLOW}⚠️  DB 파일이 없습니다. 생성 중...${NC}"
    sqlite3 ../trading_results.db < init_db.sql
    sqlite3 ../trading_results.db < insert_test_data.sql
    echo -e "${GREEN}✅ DB 생성 완료${NC}"
    echo ""
fi

# 의존성 확인
if ! python -c "import fastapi, uvicorn" 2>/dev/null; then
    echo -e "${YELLOW}⚠️  FastAPI가 설치되어 있지 않습니다.${NC}"
    echo "설치 중..."
    pip install fastapi uvicorn[standard] jinja2
    echo -e "${GREEN}✅ 설치 완료${NC}"
    echo ""
fi

# 포트 8000 사용 중인지 확인
if lsof -Pi :8000 -sTCP:LISTEN -t >/dev/null 2>&1 ; then
    echo -e "${YELLOW}⚠️  포트 8000이 이미 사용 중입니다.${NC}"
    echo "기존 프로세스를 종료하시겠습니까? (y/n)"
    read -r answer
    if [ "$answer" = "y" ]; then
        PID=$(lsof -Pi :8000 -sTCP:LISTEN -t)
        kill -9 $PID
        echo -e "${GREEN}✅ 기존 프로세스 종료${NC}"
        sleep 1
    else
        echo "다른 포트를 사용하려면 --port 옵션을 사용하세요."
        exit 0
    fi
fi

# 서버 시작
echo -e "${GREEN}🚀 웹 서버 시작 중...${NC}"
echo ""
echo -e "${BLUE}접속 URL:${NC}"
echo "  http://localhost:8000"
echo ""
echo -e "${BLUE}API 엔드포인트:${NC}"
echo "  http://localhost:8000/api/strategies"
echo ""
echo -e "${YELLOW}종료: Ctrl+C${NC}"
echo ""
echo -e "${BLUE}======================================${NC}"
echo ""

# uvicorn 실행
python -m uvicorn app:app --host 0.0.0.0 --port 8000 --reload
