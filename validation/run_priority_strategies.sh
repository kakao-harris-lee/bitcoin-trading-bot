#!/bin/bash
# 우선순위 전략 15개 × 6년 = 90 백테스트 실행
# Phase 4-6 핵심 전략

cd /Users/bongbong/SynologyDrive/vendor/sandbox/251015_봉봇

echo "=========================================="
echo "우선순위 전략 백테스팅 시작"
echo "전략: 15개 | 연도: 6년 | 총: 90 backtests"
echo "=========================================="

python validation/mass_backtest_runner.py --priority \
  2>&1 | tee validation/priority_backtest_output.log

echo ""
echo "=========================================="
echo "백테스팅 완료!"
echo "=========================================="
echo "결과 확인:"
echo "  - 로그: validation/mass_backtest_log.txt"
echo "  - 진행: validation/mass_backtest_progress.json"
echo "  - 결과: validation/results/"
echo "=========================================="
