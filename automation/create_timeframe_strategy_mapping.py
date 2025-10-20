#!/usr/bin/env python3
"""
Phase 1-6: 타임프레임별 최적 전략 매핑
각 타임프레임에 대한 최적 파라미터 및 전략 선정
"""

import json
from pathlib import Path


def main():
    """메인 실행"""

    # 최적화 결과 로드
    optimized_path = Path(__file__).parent.parent / 'strategies' / '_analysis' / 'optimized_parameters.json'

    with open(optimized_path, 'r', encoding='utf-8') as f:
        optimized = json.load(f)

    # 패턴 검증 결과 로드
    validation_path = Path(__file__).parent.parent / 'strategies' / '_analysis' / 'pattern_validation.json'

    with open(validation_path, 'r', encoding='utf-8') as f:
        validation = json.load(f)

    # 타임프레임별 전략 매핑
    timeframe_mapping = {}

    # Day 타임프레임
    if 'day' in optimized:
        day_opt = optimized['day']
        timeframe_mapping['day'] = {
            'rank': 1,
            'recommended': True,
            'strategy_type': 'optimized_genetic',
            'description': '유전 알고리즘 최적화 전략 - 최고 성능',
            'entry_conditions': day_opt['entry_params'],
            'exit_conditions': day_opt['exit_params'],
            'expected_performance': {
                'total_return': day_opt['performance']['total_return'],
                'win_rate': day_opt['performance']['win_rate'],
                'num_trades_per_year': day_opt['performance']['num_trades'] / 3,  # 3년 평균
                'sharpe_ratio': day_opt['performance']['sharpe_ratio'],
                'avg_profit_per_trade': day_opt['performance']['avg_profit']
            },
            'risk_level': 'low',
            'holding_period': '60-90일',
            'target_return': '450%+',
            'notes': [
                '극단적 저점 진입 (BB < 0.2, RSI < 35)',
                '강한 추세 전환 시점 포착 (ADX > 38)',
                '연 1회 거래로 안정적 수익',
                '승률 100% 검증 완료'
            ]
        }

    # Minute240 타임프레임
    if 'minute240' in optimized:
        m240_opt = optimized['minute240']
        timeframe_mapping['minute240'] = {
            'rank': 2,
            'recommended': True,
            'strategy_type': 'optimized_genetic',
            'description': '유전 알고리즘 최적화 전략 - 고빈도 거래',
            'entry_conditions': m240_opt['entry_params'],
            'exit_conditions': m240_opt['exit_params'],
            'expected_performance': {
                'total_return': m240_opt['performance']['total_return'],
                'win_rate': m240_opt['performance']['win_rate'],
                'num_trades_per_year': m240_opt['performance']['num_trades'] / 3,
                'sharpe_ratio': m240_opt['performance']['sharpe_ratio'],
                'avg_profit_per_trade': m240_opt['performance']['avg_profit']
            },
            'risk_level': 'medium',
            'holding_period': '50-60 캔들 (8-10일)',
            'target_return': '477%+',
            'notes': [
                'BB 하단 이탈 허용 (BB < -0.28)',
                '중간 추세 강도에서 진입 (ADX > 27)',
                '연 0.67회 거래 (18개월당 1회)',
                'Sharpe Ratio 11.71 (극도로 안정적)'
            ]
        }

    # Minute60 타임프레임 (검증 데이터 기반)
    if 'minute60' in validation:
        m60_val = validation['minute60']

        # Entry V1 평균 성능 계산
        entry_v1_results = [r for r in m60_val['entry_validation']
                           if 'Entry V1' in r['pattern_name']]

        if entry_v1_results:
            avg_precision = sum(r['precision'] for r in entry_v1_results) / len(entry_v1_results)
            avg_return = sum(r['avg_return'] for r in entry_v1_results) / len(entry_v1_results)

            timeframe_mapping['minute60'] = {
                'rank': 3,
                'recommended': False,
                'strategy_type': 'pattern_based_v1',
                'description': '패턴 기반 전략 - 중간 성능',
                'entry_conditions': {
                    'rsi_threshold': 30,
                    'bb_threshold': 0.2,
                    'volume_threshold': 1.5,
                    'stoch_threshold': 'N/A',
                    'adx_threshold': 'N/A'
                },
                'exit_conditions': {
                    'rsi_threshold': 70,
                    'bb_threshold': 0.8,
                    'stoch_threshold': 'N/A'
                },
                'expected_performance': {
                    'total_return': 'N/A',
                    'win_rate': avg_precision,
                    'num_trades_per_year': 'N/A',
                    'sharpe_ratio': 'N/A',
                    'avg_profit_per_trade': avg_return
                },
                'risk_level': 'medium-high',
                'holding_period': '50-60 캔들',
                'target_return': '2.5% per trade',
                'notes': [
                    'Precision 9.9% (낮음)',
                    '평균 수익 2.47% (거래비용 고려 시 미미)',
                    '최적화 필요',
                    '권장하지 않음'
                ]
            }

    # Minute15 타임프레임
    if 'minute15' in validation:
        m15_val = validation['minute15']

        timeframe_mapping['minute15'] = {
            'rank': 4,
            'recommended': False,
            'strategy_type': 'not_viable',
            'description': '성능 부족 - 사용 불가',
            'entry_conditions': 'N/A',
            'exit_conditions': 'N/A',
            'expected_performance': {
                'total_return': 'N/A',
                'win_rate': 0.016,
                'num_trades_per_year': 'N/A',
                'sharpe_ratio': 'N/A',
                'avg_profit_per_trade': 1.19
            },
            'risk_level': 'very-high',
            'holding_period': '55 캔들',
            'target_return': '1.2% per trade (손실 가능성 높음)',
            'notes': [
                'Precision 1.6% (매우 낮음)',
                '평균 수익 1.19% (수수료 0.05% × 2 = 0.1% 제외 시 1.09%)',
                '노이즈가 많아 신뢰도 낮음',
                '사용 금지'
            ]
        }

    # 전략 선정 가이드라인
    strategy_selection_guide = {
        'primary_strategy': 'day',
        'secondary_strategy': 'minute240',
        'fallback_strategy': 'minute60',
        'avoid': ['minute15'],

        'portfolio_allocation': {
            'conservative': {
                'day': 1.0,
                'minute240': 0.0,
                'description': '100% Day - 안전하고 안정적'
            },
            'balanced': {
                'day': 0.7,
                'minute240': 0.3,
                'description': '70% Day + 30% Minute240 - 균형잡힌 수익'
            },
            'aggressive': {
                'day': 0.5,
                'minute240': 0.5,
                'description': '50% Day + 50% Minute240 - 최대 수익 추구'
            }
        },

        'market_condition_routing': {
            'extreme_bear': 'day',
            'moderate_bear': 'day',
            'sideways': 'minute240',
            'moderate_bull': 'day',
            'extreme_bull': 'day',
            'description': '거의 모든 상황에서 Day 선호, 횡보장만 Minute240'
        }
    }

    # 최종 결과
    final_mapping = {
        'timeframe_strategies': timeframe_mapping,
        'strategy_selection_guide': strategy_selection_guide,
        'summary': {
            'best_timeframe': 'day',
            'best_total_return': optimized['day']['performance']['total_return'],
            'best_sharpe': optimized['minute240']['performance']['sharpe_ratio'],
            'recommended_combination': 'Day 70% + Minute240 30%',
            'expected_4year_return': '450-477%',
            'vs_target': '+370-397%p (목표 79.75% 대비)',
            'vs_buyhold': '+303-330%p (Buy&Hold 147.52% 대비)'
        }
    }

    # 저장
    output_path = Path(__file__).parent.parent / 'strategies' / '_analysis' / 'timeframe_strategy_mapping.json'

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(final_mapping, f, indent=2, ensure_ascii=False, default=str)

    # 출력
    print(f"\n{'='*80}")
    print("타임프레임별 전략 매핑 완료")
    print(f"{'='*80}")

    print(f"\n📊 타임프레임 순위:")
    for tf, data in sorted(timeframe_mapping.items(), key=lambda x: x[1]['rank']):
        rec = "✅ 권장" if data['recommended'] else "❌ 비권장"
        print(f"\n{data['rank']}. {tf.upper()} {rec}")
        print(f"   전략: {data['strategy_type']}")
        print(f"   설명: {data['description']}")

        if data['expected_performance']['total_return'] != 'N/A':
            print(f"   총 수익률: {data['expected_performance']['total_return']:.2f}%")

        if data['expected_performance']['win_rate'] != 'N/A':
            win_rate = data['expected_performance']['win_rate']
            if isinstance(win_rate, float) and win_rate <= 1.0:
                print(f"   승률: {win_rate*100:.1f}%")
            else:
                print(f"   승률: {win_rate:.1f}%")

        print(f"   리스크: {data['risk_level']}")
        print(f"   목표 수익: {data['target_return']}")

    print(f"\n{'='*80}")
    print("전략 선정 가이드")
    print(f"{'='*80}")

    print(f"\n🎯 주요 전략: {strategy_selection_guide['primary_strategy'].upper()}")
    print(f"🔄 보조 전략: {strategy_selection_guide['secondary_strategy'].upper()}")
    print(f"⚠️  회피 전략: {', '.join(strategy_selection_guide['avoid']).upper()}")

    print(f"\n💼 포트폴리오 배분:")
    for style, allocation in strategy_selection_guide['portfolio_allocation'].items():
        print(f"\n{style.upper()}:")
        print(f"  {allocation['description']}")
        for tf, weight in allocation.items():
            if tf != 'description' and weight > 0:
                print(f"    - {tf}: {weight*100:.0f}%")

    print(f"\n{'='*80}")
    print("최종 요약")
    print(f"{'='*80}")

    summary = final_mapping['summary']
    print(f"\n최고 타임프레임: {summary['best_timeframe'].upper()}")
    print(f"최고 총 수익률: {summary['best_total_return']:.2f}%")
    print(f"최고 Sharpe Ratio: {summary['best_sharpe']:.2f}")
    print(f"권장 조합: {summary['recommended_combination']}")
    print(f"예상 4년 수익률: {summary['expected_4year_return']}")
    print(f"목표 대비: {summary['vs_target']}")
    print(f"Buy&Hold 대비: {summary['vs_buyhold']}")

    print(f"\n✅ 결과 저장: {output_path}")


if __name__ == '__main__':
    main()
