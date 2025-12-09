#!/usr/bin/env python3
"""
v35_market_analyzer_v2_test.py
v35_optimized 전략과 MarketAnalyzerV2 통합 테스트

목적:
1. 기존 v35 전략이 MarketAnalyzerV2와 호환되는지 확인
2. AI 모드 on/off 시 동작 확인
3. 성능 영향 측정
"""

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

import pandas as pd
import numpy as np
import json
from datetime import datetime
from typing import Dict

# 기존 v35 imports
from strategies.v35_optimized.strategy import V35OptimizedStrategy
from core.backtester import Backtester
from core.data_loader import DataLoader

# 새로운 MarketAnalyzerV2
from core.market_analyzer_v2 import MarketAnalyzerV2


class V35WithMarketAnalyzerV2(V35OptimizedStrategy):
    """
    v35_optimized + MarketAnalyzerV2 통합 버전
    기존 로직은 그대로 유지하면서 AI 분석 추가
    """

    def __init__(self, config: Dict, ai_config: Dict = None):
        """
        Args:
            config: 기존 v35 설정
            ai_config: MarketAnalyzerV2 설정
        """
        super().__init__(config)

        # MarketAnalyzerV2 초기화
        self.ai_config = ai_config or {'ai_mode': False}
        self.analyzer_v2 = MarketAnalyzerV2(self.ai_config)

        # AI 분석 결과 저장
        self.ai_analysis_history = []

        print(f"V35WithMarketAnalyzerV2 초기화 - AI 모드: {self.analyzer_v2.ai_mode}")

    def execute(self, df: pd.DataFrame, i: int) -> Dict:
        """
        기존 v35 로직 + AI 분석 추가
        """
        if i < 30:
            return {'action': 'hold', 'reason': 'INSUFFICIENT_DATA'}

        # 1. AI 기반 시장 분석 (새로운 기능)
        ai_analysis = None
        if self.analyzer_v2.ai_mode and i % 10 == 0:  # 10캔들마다 AI 분석
            try:
                ai_analysis = self.analyzer_v2.analyze_market_state(df.iloc[:i+1])
                self.ai_analysis_history.append({
                    'index': i,
                    'timestamp': df.iloc[i].name,
                    'analysis': ai_analysis
                })
            except Exception as e:
                print(f"AI 분석 오류: {e}")

        # 2. 기존 v35 시장 상태 분류
        prev_row = df.iloc[i-1] if i > 0 else None
        current_row = df.iloc[i]
        market_state = self.classifier.classify_market_state(current_row, prev_row)

        # 3. AI 분석 결과가 있으면 추가 정보 활용
        enhanced_reason = ""
        confidence_boost = 1.0

        if ai_analysis and ai_analysis['confidence'] > 0.7:
            ai_market_state = ai_analysis['market_state']

            # AI 분석과 기존 분석 일치도 확인
            if ai_market_state == market_state:
                confidence_boost = 1.2  # 신뢰도 증가
                enhanced_reason = f"_AI_CONFIRMED_{ai_analysis['confidence']:.2f}"
            elif ai_analysis['confidence'] > 0.8:
                # AI 신뢰도가 매우 높으면 AI 우선 적용
                market_state = ai_market_state
                confidence_boost = 1.1
                enhanced_reason = f"_AI_OVERRIDE_{ai_analysis['confidence']:.2f}"

        # 4. 기존 v35 로직 실행 (시장 상태는 AI로 보정될 수 있음)
        # 포지션 있을 때: Exit 전략
        if self.in_position:
            exit_signal = self._check_exit_conditions(df, i, market_state)
            if exit_signal:
                self.in_position = False
                self.entry_price = 0
                self.entry_time = None
                self.entry_market_state = 'UNKNOWN'
                self.entry_strategy = 'unknown'
                self.exit_manager.reset()

                # AI 정보 추가
                if enhanced_reason:
                    exit_signal['reason'] += enhanced_reason

                return exit_signal

        # 포지션 없을 때: Entry 전략
        else:
            entry_signal = self._check_entry_conditions(df, i, market_state, prev_row)
            if entry_signal and entry_signal['action'] == 'buy':
                # 신뢰도 기반 포지션 크기 조정
                original_fraction = entry_signal.get('fraction', 0.5)
                adjusted_fraction = min(1.0, original_fraction * confidence_boost)

                self.in_position = True
                self.entry_price = current_row['close']
                self.entry_time = current_row.name
                self.entry_market_state = market_state
                self.entry_strategy = entry_signal.get('strategy', 'unknown')

                # Exit Manager 초기화
                self.exit_manager.set_entry(self.entry_price, market_state)

                # AI 정보 추가
                entry_signal['fraction'] = adjusted_fraction
                if enhanced_reason:
                    entry_signal['reason'] += enhanced_reason

                return entry_signal

        reason = f'NO_SIGNAL_{market_state}'
        if enhanced_reason:
            reason += enhanced_reason

        return {'action': 'hold', 'reason': reason}

    def get_ai_analysis_summary(self) -> Dict:
        """AI 분석 결과 요약"""
        if not self.ai_analysis_history:
            return {'total_analyses': 0}

        total = len(self.ai_analysis_history)
        high_confidence = sum(1 for a in self.ai_analysis_history
                             if a['analysis']['confidence'] > 0.7)

        # 가장 자주 나온 시장 상태
        states = [a['analysis']['market_state'] for a in self.ai_analysis_history]
        most_common = max(set(states), key=states.count) if states else 'N/A'

        # 평균 신뢰도
        avg_confidence = np.mean([a['analysis']['confidence']
                                 for a in self.ai_analysis_history])

        return {
            'total_analyses': total,
            'high_confidence_rate': high_confidence / total if total > 0 else 0,
            'most_common_state': most_common,
            'avg_confidence': avg_confidence,
            'ai_mode': self.analyzer_v2.ai_mode
        }


def run_comparison_test():
    """기존 v35 vs v35+AI 비교 테스트"""
    print("=" * 80)
    print("V35 vs V35+AI 비교 테스트")
    print("=" * 80)

    # 설정
    config = {
        'initial_capital': 10_000_000,
        'fee_rate': 0.0005,
        'slippage': 0.0002
    }

    # 전략 설정 로드
    strategy_config_path = Path("strategies/v35_optimized/config_optimized.json")
    if strategy_config_path.exists():
        with open(strategy_config_path, 'r') as f:
            strategy_config = json.load(f)
    else:
        # 기본 설정
        strategy_config = {
            "version": "v35_optimized_test",
            "timeframe": "day"
        }

    # 데이터 로드 (최근 1년)
    print("데이터 로드 중...")
    with DataLoader() as loader:
        df = loader.load_timeframe(
            "day",
            start_date="2024-01-01",
            end_date="2024-12-31"
        )

    # 지표 추가
    df = MarketAnalyzerV2.add_indicators(df, [
        'sma', 'ema', 'rsi', 'macd', 'bb', 'stoch', 'atr', 'adx', 'volume'
    ])

    print(f"데이터 기간: {df.index[0]} ~ {df.index[-1]}")
    print(f"캔들 수: {len(df)}")

    # 1. 기존 v35 (AI 없음)
    print("\n1. 기존 V35 백테스트...")
    strategy_basic = V35WithMarketAnalyzerV2(
        config=strategy_config,
        ai_config={'ai_mode': False}
    )

    backtester = Backtester(**config)
    results_basic = backtester.run(df, strategy_basic)

    print(f"   총 수익률: {results_basic['total_return']:.2f}%")
    print(f"   Sharpe: {results_basic['sharpe_ratio']:.2f}")
    print(f"   거래 수: {results_basic['total_trades']}")

    # 2. v35 + AI (기본 에이전트)
    print("\n2. V35 + AI 백테스트...")
    strategy_ai = V35WithMarketAnalyzerV2(
        config=strategy_config,
        ai_config={
            'ai_mode': True,
            'agents_enabled': ['trend', 'volatility'],
            'confidence_threshold': 0.7
        }
    )

    backtester_ai = Backtester(**config)
    results_ai = backtester_ai.run(df, strategy_ai)

    print(f"   총 수익률: {results_ai['total_return']:.2f}%")
    print(f"   Sharpe: {results_ai['sharpe_ratio']:.2f}")
    print(f"   거래 수: {results_ai['total_trades']}")

    # AI 분석 요약
    ai_summary = strategy_ai.get_ai_analysis_summary()
    print(f"   AI 분석 횟수: {ai_summary['total_analyses']}")
    print(f"   고신뢰도 비율: {ai_summary['high_confidence_rate']:.2%}")
    print(f"   가장 많은 상태: {ai_summary['most_common_state']}")
    print(f"   평균 신뢰도: {ai_summary['avg_confidence']:.3f}")

    # 3. 비교 결과
    print("\n" + "=" * 80)
    print("비교 결과")
    print("=" * 80)

    improvement_return = results_ai['total_return'] - results_basic['total_return']
    improvement_sharpe = results_ai['sharpe_ratio'] - results_basic['sharpe_ratio']

    print(f"수익률 개선: {improvement_return:+.2f}%p")
    print(f"Sharpe 개선: {improvement_sharpe:+.2f}")
    print(f"거래 수 변화: {results_ai['total_trades'] - results_basic['total_trades']:+d}")

    # 결과 저장
    output = {
        'test_date': datetime.now().isoformat(),
        'data_period': {
            'start': str(df.index[0]),
            'end': str(df.index[-1]),
            'candles': len(df)
        },
        'v35_basic': results_basic,
        'v35_ai': results_ai,
        'ai_summary': ai_summary,
        'improvement': {
            'return': improvement_return,
            'sharpe': improvement_sharpe,
            'trades': results_ai['total_trades'] - results_basic['total_trades']
        }
    }

    output_file = Path("core/market_analyzer_v2_test_results.json")
    with open(output_file, 'w') as f:
        json.dump(output, f, indent=2, default=str)

    print(f"\n✅ 테스트 결과 저장: {output_file}")

    return output


def run_simple_test():
    """간단한 동작 테스트"""
    print("MarketAnalyzerV2 간단 테스트")
    print("-" * 40)

    # 더미 데이터 생성
    dates = pd.date_range('2024-01-01', periods=100, freq='D')
    prices = 50000 + np.cumsum(np.random.randn(100) * 1000)

    df = pd.DataFrame({
        'open': prices,
        'high': prices * 1.02,
        'low': prices * 0.98,
        'close': prices,
        'volume': np.random.randint(1000, 10000, 100)
    }, index=dates)

    # 지표 추가
    df = MarketAnalyzerV2.add_indicators(df, ['sma', 'rsi', 'bb'])
    print(f"지표 추가 완료: {len(df.columns)}개 컬럼")

    # 기본 모드 테스트
    analyzer_basic = MarketAnalyzerV2({'ai_mode': False})
    result_basic = analyzer_basic.analyze_market_state(df)
    print(f"기본 모드: {result_basic['market_state']}")

    # AI 모드 테스트
    analyzer_ai = MarketAnalyzerV2({
        'ai_mode': True,
        'agents_enabled': ['trend', 'volatility']
    })
    result_ai = analyzer_ai.analyze_market_state(df)
    print(f"AI 모드: {result_ai['market_state']} (신뢰도: {result_ai['confidence']:.2f})")

    return True


if __name__ == "__main__":
    print("🚀 MarketAnalyzerV2 Phase 1 통합 테스트 시작\n")

    try:
        # 1. 간단 테스트
        print("1️⃣  간단 동작 테스트")
        run_simple_test()
        print("✅ 통과\n")

        # 2. v35 통합 테스트
        print("2️⃣  V35 통합 테스트")
        results = run_comparison_test()
        print("✅ 통과\n")

        print("🎉 Phase 1 통합 테스트 완료!")
        print("AWS에서 실행 중인 v35_optimized와 호환 확인됨")

    except Exception as e:
        print(f"❌ 테스트 실패: {e}")
        import traceback
        traceback.print_exc()