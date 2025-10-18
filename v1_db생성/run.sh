#!/bin/bash

# 업비트 비트코인 데이터 수집기 실행 스크립트

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "============================================================"
echo "🚀 업비트 비트코인 데이터 수집기"
echo "============================================================"
echo ""

# 1. DB 초기화 확인
if [ -f "upbit_bitcoin.db" ]; then
    DB_SIZE=$(ls -lh upbit_bitcoin.db | awk '{print $5}')
    echo "⚠️  기존 DB 발견: $DB_SIZE"
    echo ""
    read -p "DB를 초기화하시겠습니까? (y/N): " -n 1 -r
    echo ""
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        # 백업 생성
        BACKUP_NAME="upbit_bitcoin_backup_$(date +%Y%m%d_%H%M%S).db"
        echo "📦 백업 생성: $BACKUP_NAME"
        cp upbit_bitcoin.db "$BACKUP_NAME"

        # DB 삭제
        rm -f upbit_bitcoin.db
        echo "✓ DB 초기화 완료"
    else
        echo "✓ 기존 DB 유지 (새 데이터만 추가됩니다)"
    fi
else
    echo "ℹ️  DB 파일 없음 (새로 생성됩니다)"
fi

echo ""
echo "------------------------------------------------------------"
echo "실행 방법 선택:"
echo "  1) Go 버전 (추천 - 빠르고 안정적)"
echo "  2) Python 버전 (순차 처리)"
echo "------------------------------------------------------------"
read -p "선택 (1 또는 2): " -n 1 -r
echo ""
echo ""

if [[ $REPLY == "1" ]]; then
    echo "============================================================"
    echo "📊 Go 버전 실행 (병렬 처리 + Rate Limiter)"
    echo "============================================================"
    echo ""

    # Go 설치 확인
    if ! command -v go &> /dev/null; then
        echo "✗ Go가 설치되지 않았습니다."
        echo "  설치 명령: brew install go"
        exit 1
    fi

    # 빌드
    echo "🔨 빌드 중..."
    go build -o upbit-collector main.go
    echo "✓ 빌드 완료"
    echo ""

    # 실행
    echo "🚀 실행 시작..."
    echo "   (Ctrl+C로 중단 가능)"
    echo ""
    ./upbit-collector

elif [[ $REPLY == "2" ]]; then
    echo "============================================================"
    echo "📊 Python 버전 실행 (순차 처리)"
    echo "============================================================"
    echo ""

    # 가상환경 확인
    if [ ! -d "venv" ]; then
        echo "✗ 가상환경이 없습니다."
        echo "  생성 명령:"
        echo "    python3 -m venv venv"
        echo "    source venv/bin/activate"
        echo "    pip install requests pandas"
        exit 1
    fi

    # 가상환경 활성화
    source venv/bin/activate

    # 실행
    echo "🚀 실행 시작..."
    echo "   (Ctrl+C로 중단 가능)"
    echo ""
    python upbit_bitcoin_collector.py

else
    echo "✗ 잘못된 선택입니다."
    exit 1
fi
