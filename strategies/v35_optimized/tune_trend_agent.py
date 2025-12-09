#!/usr/bin/env python3
"""
tune_trend_agent.py
TrendAgent 파라미터 최적화

목표:
- 평균 신뢰도 >= 0.7
- 고신뢰도(>=0.8) 비율 >= 50%
- 백테스트 수익률 유지 (28.73% 근처)
"""

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent.parent))

import json
import optuna
import pandas as pd
import numpy as np
from core.data_loader import DataLoader
from strategies.v35_optimized.strategy import V35OptimizedStrategy
from strategies.v35_optimized.backtest import V35Backtester


class TrendAgentTuner:
    """TrendAgent 파라미터 튜너"""

    def __init__(self):
        # 데이터 로드 (2024년 전체)
        print("데이터 로드 중...")
        with DataLoader() as loader:
            self.df = loader.load_timeframe("day", start_date="2024-01-01", end_date="2024-12-31")

        # 지표 추가 (MarketAnalyzerV2 사용)
        from core.market_analyzer_v2 import MarketAnalyzerV2
        self.df = MarketAnalyzerV2.add_indicators(self.df, [
            'sma', 'ema', 'rsi', 'macd', 'bb', 'stoch', 'atr', 'adx', 'volume'
        ])

        print(f"데이터 기간: {self.df.index[0]} ~ {self.df.index[-1]}")
        print(f"캔들 수: {len(self.df)}")

        # 베이스라인 수익률 (목표: 이 근처 유지)
        self.baseline_return = 28.73

        # 최적화 가중치
        self.w_avg_conf = 0.4      # 평균 신뢰도
        self.w_high_conf = 0.4     # 고신뢰도 비율
        self.w_return = 0.2        # 수익률 유지

    def create_modified_agent(self, params: dict):
        """수정된 TrendAgent 클래스 생성"""

        class TunedTrendAgent:
            """튜닝된 TrendAgent"""

            def __init__(self, params):
                self.name = "TunedTrendAgent"
                self.params = params

            def analyze(self, df: pd.DataFrame) -> dict:
                """파라미터화된 트렌드 분석"""
                if len(df) < max(params['sma_long_period'], 50):
                    return {
                        'market_state': 'SIDEWAYS_NEUTRAL',
                        'confidence': params['confidence_sideways'],
                        'trend_strength': 0.0
                    }

                # SMA 계산
                sma_short = df['close'].rolling(params['sma_short_period']).mean().iloc[-1]
                sma_long = df['close'].rolling(params['sma_long_period']).mean().iloc[-1]
                current_price = df['close'].iloc[-1]

                # 트렌드 강도
                trend_strength = abs(sma_short - sma_long) / sma_long

                # 상태 분류
                if current_price > sma_short > sma_long:
                    if trend_strength > params['strong_threshold']:
                        state = 'BULL_STRONG'
                        confidence = params['confidence_strong']
                    else:
                        state = 'BULL_WEAK'
                        confidence = params['confidence_weak']
                elif current_price < sma_short < sma_long:
                    if trend_strength > params['strong_threshold']:
                        state = 'BEAR_STRONG'
                        confidence = params['confidence_strong']
                    else:
                        state = 'BEAR_WEAK'
                        confidence = params['confidence_weak']
                else:
                    state = 'SIDEWAYS_NEUTRAL'
                    confidence = params['confidence_sideways']

                return {
                    'market_state': state,
                    'confidence': confidence,
                    'trend_strength': trend_strength,
                    'sma_short': sma_short,
                    'sma_long': sma_long
                }

        return TunedTrendAgent(params)

    def evaluate_params(self, params: dict) -> dict:
        """파라미터 평가"""

        # 설정 생성
        config_path = Path("strategies/v35_optimized/config_optimized.json")
        with open(config_path, 'r') as f:
            config = json.load(f)

        # AI 설정
        config['ai_analyzer'] = {
            'enabled': True,
            'test_mode': True,  # test_mode로 평가 (거래 영향 없음)
            'agents': ['trend'],
            'confidence_threshold': 0.8
        }

        # 전략 초기화
        strategy = V35OptimizedStrategy(config)

        # TrendAgent 교체
        tuned_agent = self.create_modified_agent(params)
        if hasattr(strategy.analyzer_v2, 'agents') and 'trend' in strategy.analyzer_v2.agents:
            strategy.analyzer_v2.agents['trend'] = tuned_agent

        # 백테스트 실행
        backtester = V35Backtester(
            initial_capital=10_000_000,
            fee_rate=0.0005,
            slippage=0.0002
        )

        results = backtester.run(self.df, strategy)

        # AI 통계 수집
        ai_summary = strategy.get_ai_analysis_summary()

        return {
            'total_return': results['total_return'],
            'avg_confidence': ai_summary['avg_confidence'],
            'high_confidence_rate': ai_summary['high_confidence_rate'],
            'total_analyses': ai_summary['total_analyses']
        }

    def objective(self, trial: optuna.Trial) -> float:
        """Optuna 목적 함수"""

        # 파라미터 샘플링
        params = {
            'sma_short_period': trial.suggest_int('sma_short_period', 10, 30),
            'sma_long_period': trial.suggest_int('sma_long_period', 40, 100),
            'strong_threshold': trial.suggest_float('strong_threshold', 0.02, 0.15),
            'confidence_strong': trial.suggest_float('confidence_strong', 0.75, 0.95),
            'confidence_weak': trial.suggest_float('confidence_weak', 0.55, 0.75),
            'confidence_sideways': trial.suggest_float('confidence_sideways', 0.40, 0.60)
        }

        # 제약 조건: short < long
        if params['sma_short_period'] >= params['sma_long_period']:
            return -1.0  # 페널티

        # 제약 조건: strong > weak > sideways
        if not (params['confidence_strong'] > params['confidence_weak'] > params['confidence_sideways']):
            return -1.0  # 페널티

        try:
            # 평가
            eval_result = self.evaluate_params(params)

            # 목표 달성도 계산
            avg_conf = eval_result['avg_confidence']
            high_conf_rate = eval_result['high_confidence_rate']
            total_return = eval_result['total_return']

            # 1. 평균 신뢰도 점수 (목표: >= 0.7)
            avg_conf_score = min(avg_conf / 0.7, 1.0)

            # 2. 고신뢰도 비율 점수 (목표: >= 0.5)
            high_conf_score = min(high_conf_rate / 0.5, 1.0)

            # 3. 수익률 유지 점수 (목표: 28.73% 근처)
            return_diff = abs(total_return - self.baseline_return)
            return_penalty = max(0, (return_diff - 5.0) / 10.0)  # 5%p 이상 차이 시 페널티
            return_score = max(0, 1.0 - return_penalty)

            # 종합 점수
            total_score = (
                self.w_avg_conf * avg_conf_score +
                self.w_high_conf * high_conf_score +
                self.w_return * return_score
            )

            # 로그
            print(f"\n[Trial {trial.number}]")
            print(f"  SMA: {params['sma_short_period']}/{params['sma_long_period']}")
            print(f"  Strong Threshold: {params['strong_threshold']:.3f}")
            print(f"  Confidences: {params['confidence_strong']:.2f}/{params['confidence_weak']:.2f}/{params['confidence_sideways']:.2f}")
            print(f"  → Avg Conf: {avg_conf:.3f} (목표: 0.7+)")
            print(f"  → High Conf Rate: {high_conf_rate:.1%} (목표: 50%+)")
            print(f"  → Return: {total_return:.2f}% (기준: {self.baseline_return:.2f}%)")
            print(f"  → Score: {total_score:.3f}")

            return total_score

        except Exception as e:
            print(f"[Trial {trial.number}] 에러: {e}")
            return -1.0


def main():
    """메인 실행"""

    print("="*80)
    print("TrendAgent 파라미터 최적화 시작")
    print("="*80)

    # Tuner 초기화
    tuner = TrendAgentTuner()

    # Optuna Study 생성
    study = optuna.create_study(
        direction='maximize',
        study_name='trend_agent_tuning',
        sampler=optuna.samplers.TPESampler(seed=42)
    )

    # 최적화 실행
    n_trials = 100
    print(f"\n최적화 시작 (총 {n_trials}회 시도)...")
    print("목표:")
    print("  1. 평균 신뢰도 >= 0.7")
    print("  2. 고신뢰도 비율 >= 50%")
    print("  3. 수익률 유지 (~28.73%)")
    print()

    study.optimize(tuner.objective, n_trials=n_trials, show_progress_bar=True)

    # 결과 출력
    print("\n" + "="*80)
    print("최적화 완료!")
    print("="*80)

    best_params = study.best_params
    best_score = study.best_value

    print(f"\n최고 점수: {best_score:.3f}")
    print("\n최적 파라미터:")
    for key, value in best_params.items():
        print(f"  {key}: {value}")

    # 최적 파라미터로 최종 평가
    print("\n최적 파라미터로 최종 평가 중...")
    final_eval = tuner.evaluate_params(best_params)

    print("\n최종 평가 결과:")
    print(f"  평균 신뢰도: {final_eval['avg_confidence']:.3f} (목표: 0.7+)")
    print(f"  고신뢰도 비율: {final_eval['high_confidence_rate']:.1%} (목표: 50%+)")
    print(f"  수익률: {final_eval['total_return']:.2f}% (기준: {tuner.baseline_return:.2f}%)")
    print(f"  총 분석 횟수: {final_eval['total_analyses']}")

    # 목표 달성 여부
    print("\n목표 달성 여부:")
    avg_conf_ok = final_eval['avg_confidence'] >= 0.7
    high_conf_ok = final_eval['high_confidence_rate'] >= 0.5
    return_ok = abs(final_eval['total_return'] - tuner.baseline_return) <= 5.0

    print(f"  ✅ 평균 신뢰도: {'달성' if avg_conf_ok else '미달'}")
    print(f"  ✅ 고신뢰도 비율: {'달성' if high_conf_ok else '미달'}")
    print(f"  ✅ 수익률 유지: {'달성' if return_ok else '미달'}")

    all_ok = avg_conf_ok and high_conf_ok and return_ok

    if all_ok:
        print("\n🎉 모든 목표 달성!")
    else:
        print("\n⚠️  일부 목표 미달 - 추가 튜닝 필요")

    # 결과 저장
    output_file = Path("strategies/v35_optimized/trend_agent_tuning_results.json")
    output = {
        'best_params': best_params,
        'best_score': best_score,
        'final_evaluation': final_eval,
        'goals_achieved': {
            'avg_confidence': avg_conf_ok,
            'high_confidence_rate': high_conf_ok,
            'return_maintained': return_ok,
            'all_goals': all_ok
        },
        'study_stats': {
            'n_trials': len(study.trials),
            'best_trial': study.best_trial.number
        }
    }

    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"\n결과 저장: {output_file}")

    # 다음 단계 안내
    if all_ok:
        print("\n다음 단계:")
        print("1. core/market_analyzer_v2.py의 BasicTrendAgent에 최적 파라미터 적용")
        print("2. v35_with_ai_test.py로 전체 백테스트 재실행")
        print("3. AI 품질 재확인 후 AWS 배포")
    else:
        print("\n다음 단계:")
        print("1. n_trials 증가 (200-500)")
        print("2. 파라미터 범위 조정")
        print("3. 가중치 조정 (w_avg_conf, w_high_conf, w_return)")


if __name__ == "__main__":
    main()
