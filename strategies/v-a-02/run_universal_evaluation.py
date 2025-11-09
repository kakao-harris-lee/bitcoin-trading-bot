#!/usr/bin/env python3
"""
v-a-02 Universal Evaluation 실행
"""
import sys
import argparse
from pathlib import Path

# 프로젝트 루트를 sys.path에 추가
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from validation.universal_evaluation_engine import UniversalEvaluationEngine
import json

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--tier', type=str, required=True, help='S, A, or B')
    args = parser.parse_args()

    tier = args.tier.upper()

    print("=" * 70)
    print(f"v-a-02-{tier}-Tier Universal Evaluation Engine 실행")
    print("=" * 70)
    print()

    # 경로 설정
    v_a_02_dir = Path(__file__).parent
    signals_dir = v_a_02_dir / 'signals'
    config_file = v_a_02_dir / f'evaluation_config_{tier}.json'
    output_dir = v_a_02_dir / 'results' / f'{tier}-Tier'

    # 시그널 파일 복사 (2024_signals.json으로)
    src_signal = signals_dir / f'day_2024_{tier}tier_signals.json'
    dst_signal = signals_dir / '2024_signals.json'

    import shutil
    shutil.copy(src_signal, dst_signal)
    print(f"📋 Signal file: {src_signal.name} → 2024_signals.json")

    # 설정 로드
    print(f"📋 Loading config: {config_file}")
    with open(config_file, 'r') as f:
        evaluation_config = json.load(f)
    print(f"   Strategy: {evaluation_config['strategy']}")
    print(f"   Timeframe: {evaluation_config['timeframe']}")
    print(f"   Years: {evaluation_config['years']}")
    print(f"   Holding periods: {len(evaluation_config['holding_periods'])} periods")
    print()

    # 엔진 생성
    print("🔧 Creating Universal Evaluation Engine...")
    engine = UniversalEvaluationEngine(
        initial_capital=10_000_000,
        fee_rate=0.0005,
        slippage=0.0002
    )
    print()

    # 평가 실행
    print("🚀 Running evaluation...")
    print(f"   Signals dir: {signals_dir}")
    print(f"   Output dir: {output_dir}")
    print()

    try:
        report = engine.evaluate_all_combinations(
            signals_dir=signals_dir,
            evaluation_config=evaluation_config,
            parallel=False  # 디버깅을 위해 직렬 실행
        )

        # 결과 저장
        output_dir.mkdir(parents=True, exist_ok=True)

        result_file = output_dir / 'evaluation_report.json'
        with open(result_file, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2, ensure_ascii=False)

        print()
        print("=" * 70)
        print(f"✅ {tier}-Tier Evaluation Complete!")
        print("=" * 70)
        print()
        print(f"📊 Results Summary:")
        print(f"   Total combinations: {report['evaluated_combinations']}")
        print(f"   Best period: {report['optimization']['best_period']}")
        print(f"   Training avg return: {report['optimization']['training_avg']['avg_return_pct']:.2f}%")
        print(f"   Training avg Sharpe: {report['optimization']['training_avg']['avg_sharpe']:.2f}")
        print()
        print(f"   Validation year: {report['validation']['year']}")
        if report['validation']['result']:
            print(f"   Validation return: {report['validation']['result']['total_return_pct']:.2f}%")
            print(f"   Validation Sharpe: {report['validation']['result']['sharpe_ratio']:.2f}")
            print(f"   Win Rate: {report['validation']['result']['win_rate']:.1f}%")
            print(f"   Trades: {report['validation']['result']['total_trades']}")
        print()
        print(f"💡 Recommendation: {report['recommendation']}")
        print()
        print(f"📁 Full report saved: {result_file}")
        print()

        return report

    except Exception as e:
        print(f"❌ Error during evaluation: {e}")
        import traceback
        traceback.print_exc()
        return None

if __name__ == '__main__':
    main()
