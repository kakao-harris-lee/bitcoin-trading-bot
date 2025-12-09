#!/usr/bin/env python3
"""
v35_with_ai_test.py
v35_optimized + AI Analyzer v2 통합 테스트

목적:
1. 기존 v35 로직이 정상 작동하는지 확인
2. AI 모드 on/off 테스트
3. AI 분석이 거래에 미치는 영향 측정
"""

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent.parent))

import json
import pandas as pd
from core.data_loader import DataLoader
from core.market_analyzer_v2 import MarketAnalyzerV2
from strategies.v35_optimized.strategy import V35OptimizedStrategy
from strategies.v35_optimized.backtest import V35Backtester


def run_test(ai_enabled=False, ai_test_mode=True):
    """v35 + AI 테스트 실행"""
    
    print(f"\n{'='*80}")
    print(f"V35 + AI 테스트 (AI enabled={ai_enabled}, test_mode={ai_test_mode})")
    print(f"{'='*80}")
    
    # 설정 로드
    config_path = Path("strategies/v35_optimized/config_optimized.json")
    with open(config_path, 'r') as f:
        config = json.load(f)
    
    # AI 설정 오버라이드
    config['ai_analyzer'] = {
        'enabled': ai_enabled,
        'test_mode': ai_test_mode,
        'agents': ['trend'],
        'confidence_threshold': 0.8
    }
    
    # 데이터 로드 (2024년 전체)
    print("\n데이터 로드 중...")
    with DataLoader() as loader:
        df = loader.load_timeframe("day", start_date="2024-01-01", end_date="2024-12-31")
    
    # 지표 추가
    df = MarketAnalyzerV2.add_indicators(df, [
        'sma', 'ema', 'rsi', 'macd', 'bb', 'stoch', 'atr', 'adx', 'volume'
    ])
    
    print(f"데이터 기간: {df.index[0]} ~ {df.index[-1]}")
    print(f"캔들 수: {len(df)}")
    
    # 전략 초기화
    strategy = V35OptimizedStrategy(config)
    
    # 백테스트 실행
    print("\n백테스트 실행 중...")
    backtester = V35Backtester(
        initial_capital=10_000_000,
        fee_rate=0.0005,
        slippage=0.0002
    )
    
    results = backtester.run(df, strategy)
    
    # 결과 출력
    print(f"\n{'='*60}")
    print("백테스트 결과")
    print(f"{'='*60}")
    print(f"총 수익률: {results['total_return']:.2f}%")
    print(f"Sharpe Ratio: {results['sharpe_ratio']:.2f}")
    print(f"Max Drawdown: {results['max_drawdown']:.2f}%")
    print(f"총 거래 수: {results['total_trades']}")
    print(f"승률: {results['win_rate']:.1%}")
    
    # AI 분석 요약
    if ai_enabled:
        ai_summary = strategy.get_ai_analysis_summary()
        print(f"\n{'='*60}")
        print("AI 분석 요약")
        print(f"{'='*60}")
        print(f"AI 모드: {ai_summary['ai_enabled']}")
        print(f"테스트 모드: {ai_summary['ai_test_mode']}")
        print(f"총 AI 분석: {ai_summary['total_analyses']}회")
        print(f"V34-AI 일치율: {ai_summary['v34_ai_match_rate']:.1%}")
        print(f"고신뢰도 분석 비율: {ai_summary['high_confidence_rate']:.1%}")
        print(f"평균 신뢰도: {ai_summary['avg_confidence']:.3f}")
        print(f"신뢰도 임계값: {ai_summary['confidence_threshold']}")
        print(f"\n시장 상태 분포 (AI):")
        for state, count in sorted(ai_summary['state_distribution'].items()):
            print(f"  {state}: {count}회")
    
    return results, strategy


def main():
    """메인 테스트"""
    print("🚀 V35 + AI Analyzer v2 통합 테스트 시작")
    
    # 1. 기존 v35 (AI 비활성화)
    print("\n" + "="*80)
    print("1️⃣  기존 V35 (AI 비활성화)")
    print("="*80)
    results_baseline, strategy_baseline = run_test(ai_enabled=False, ai_test_mode=False)
    
    # 2. v35 + AI (테스트 모드 - 로그만 기록)
    print("\n" + "="*80)
    print("2️⃣  V35 + AI (테스트 모드 - 로그만)")
    print("="*80)
    results_ai_test, strategy_ai_test = run_test(ai_enabled=True, ai_test_mode=True)
    
    # 3. v35 + AI (활성 모드 - 실제 적용)
    print("\n" + "="*80)
    print("3️⃣  V35 + AI (활성 모드 - 실제 적용)")
    print("="*80)
    results_ai_active, strategy_ai_active = run_test(ai_enabled=True, ai_test_mode=False)
    
    # 비교 결과
    print("\n" + "="*80)
    print("📊 종합 비교")
    print("="*80)
    
    comparison = pd.DataFrame({
        'Baseline (AI OFF)': {
            '수익률': results_baseline['total_return'],
            'Sharpe': results_baseline['sharpe_ratio'],
            'MDD': results_baseline['max_drawdown'],
            '거래수': results_baseline['total_trades'],
            '승률': results_baseline['win_rate']
        },
        'AI Test Mode': {
            '수익률': results_ai_test['total_return'],
            'Sharpe': results_ai_test['sharpe_ratio'],
            'MDD': results_ai_test['max_drawdown'],
            '거래수': results_ai_test['total_trades'],
            '승률': results_ai_test['win_rate']
        },
        'AI Active': {
            '수익률': results_ai_active['total_return'],
            'Sharpe': results_ai_active['sharpe_ratio'],
            'MDD': results_ai_active['max_drawdown'],
            '거래수': results_ai_active['total_trades'],
            '승률': results_ai_active['win_rate']
        }
    })
    
    print("\n" + comparison.to_string())
    
    # 개선도 계산
    print(f"\n{'='*80}")
    print("개선도")
    print(f"{'='*80}")
    print(f"AI Active vs Baseline:")
    print(f"  수익률: {results_ai_active['total_return'] - results_baseline['total_return']:+.2f}%p")
    print(f"  Sharpe: {results_ai_active['sharpe_ratio'] - results_baseline['sharpe_ratio']:+.2f}")
    print(f"  거래수: {results_ai_active['total_trades'] - results_baseline['total_trades']:+d}")
    
    # 결과 저장
    output = {
        'test_date': pd.Timestamp.now().isoformat(),
        'baseline': results_baseline,
        'ai_test_mode': results_ai_test,
        'ai_active': results_ai_active,
        'ai_summary_test': strategy_ai_test.get_ai_analysis_summary(),
        'ai_summary_active': strategy_ai_active.get_ai_analysis_summary(),
        'improvement': {
            'return': results_ai_active['total_return'] - results_baseline['total_return'],
            'sharpe': results_ai_active['sharpe_ratio'] - results_baseline['sharpe_ratio'],
            'trades': results_ai_active['total_trades'] - results_baseline['total_trades']
        }
    }
    
    output_file = Path("strategies/v35_optimized/ai_integration_test_results.json")
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, ensure_ascii=False, default=str)
    
    print(f"\n✅ 테스트 결과 저장: {output_file}")
    print("\n🎉 AI 통합 테스트 완료!")
    print("\n다음 단계:")
    print("1. test_mode로 AWS 배포하여 로그 수집")
    print("2. 1주일 모니터링 후 AI 신뢰도 검증")
    print("3. 검증 완료 후 ai_analyzer.enabled = true로 전환")


if __name__ == "__main__":
    main()
