#!/usr/bin/env python3
"""
타임프레임별 백테스팅 결과 비교 및 리포트 생성

multi_timeframe_summary.json을 읽어서 전략별 최적 타임프레임을 분석하고
상세한 비교 리포트를 생성합니다.
"""

import json
from pathlib import Path
from typing import Dict, List
from datetime import datetime


class TimeframeComparator:
    """타임프레임 결과 비교 분석기"""

    def __init__(self, strategies_dir: str = "strategies"):
        self.strategies_dir = Path(strategies_dir)
        self.summary_path = self.strategies_dir / 'multi_timeframe_summary.json'
        self.summary_data = None

    def load_summary(self) -> bool:
        """요약 파일 로드"""
        if not self.summary_path.exists():
            print(f"✗ 요약 파일 없음: {self.summary_path}")
            print("  먼저 run_multi_timeframe_backtest.py를 실행하세요.")
            return False

        with open(self.summary_path, 'r', encoding='utf-8') as f:
            self.summary_data = json.load(f)

        return True

    def find_best_timeframe(self, timeframes_data: Dict) -> Dict:
        """최적 타임프레임 찾기 (수익률 기준)"""
        best = {
            'timeframe': None,
            'total_return': float('-inf'),
            'sharpe_ratio': 0,
            'max_drawdown': 0,
            'win_rate': 0
        }

        for timeframe, data in timeframes_data.items():
            if data and data.get('total_return', float('-inf')) > best['total_return']:
                best['timeframe'] = timeframe
                best['total_return'] = data.get('total_return', 0)
                best['sharpe_ratio'] = data.get('sharpe_ratio', 0)
                best['max_drawdown'] = data.get('max_drawdown', 0)
                best['win_rate'] = data.get('win_rate', 0)

        return best

    def generate_strategy_report(self, strategy_data: Dict) -> str:
        """전략별 상세 리포트 생성"""
        strategy_name = strategy_data['strategy_name']
        timeframes_data = strategy_data['timeframes']

        # 최적 타임프레임 찾기
        best = self.find_best_timeframe(timeframes_data)

        # 마크다운 리포트 생성
        report = f"""# {strategy_name} 타임프레임 비교 분석

## 📊 전체 결과 비교

| 타임프레임 | 수익률 | Sharpe | MDD | 승률 | 거래횟수 | Profit Factor |
|-----------|--------|--------|-----|------|----------|---------------|
"""

        for timeframe in ['minute5', 'minute15', 'minute30', 'minute60', 'minute240', 'day']:
            data = timeframes_data.get(timeframe)
            if data:
                mark = "⭐" if timeframe == best['timeframe'] else ""
                report += f"| {timeframe} {mark} | "
                report += f"{data.get('total_return', 0):>7.2f}% | "
                report += f"{data.get('sharpe_ratio', 0):>6.3f} | "
                report += f"{data.get('max_drawdown', 0):>6.2f}% | "
                report += f"{data.get('win_rate', 0)*100:>5.1f}% | "
                report += f"{data.get('total_trades', 0):>8} | "
                report += f"{data.get('profit_factor', 0):>6.2f} |\n"
            else:
                report += f"| {timeframe} | - | - | - | - | - | - |\n"

        report += f"""
## 🏆 최적 타임프레임: {best['timeframe']}

### 성과 지표
- **수익률**: {best['total_return']:.2f}%
- **Sharpe Ratio**: {best['sharpe_ratio']:.3f}
- **Max Drawdown**: {best['max_drawdown']:.2f}%
- **승률**: {best['win_rate']*100:.1f}%

### 권장사항
"""

        # 권장사항 생성
        if best['sharpe_ratio'] >= 1.0 and best['total_return'] >= 10:
            report += "✅ 우수한 성과. 이 타임프레임 사용 권장\n"
        elif best['total_return'] > 0:
            report += "⚠️  수익은 있으나 개선 필요. 전략 파라미터 최적화 고려\n"
        else:
            report += "❌ 손실 발생. 전략 재설계 필요\n"

        # 타임프레임별 특징
        report += "\n### 타임프레임별 특징\n\n"

        for timeframe in ['minute5', 'minute15', 'minute30', 'minute60', 'minute240', 'day']:
            data = timeframes_data.get(timeframe)
            if data:
                if data.get('total_return', 0) > 0:
                    report += f"- **{timeframe}**: "
                    if data.get('sharpe_ratio', 0) > best['sharpe_ratio'] * 0.8:
                        report += "안정적인 수익 (대안 가능)\n"
                    else:
                        report += f"수익 {data.get('total_return', 0):.2f}% (변동성 높음)\n"

        report += f"\n---\n생성 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"

        return report

    def generate_comprehensive_report(self) -> str:
        """전체 전략 통합 비교 리포트"""
        report = f"""# 전체 전략 타임프레임 비교 분석

**분석 기간**: {self.summary_data['period']['start']} ~ {self.summary_data['period']['end']}
**타임프레임**: {', '.join(self.summary_data['timeframes'])}
**생성 시간**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

---

## 📈 전략별 최적 타임프레임 요약

| 전략 | 최적 타임프레임 | 수익률 | Sharpe | MDD | 승률 |
|------|----------------|--------|--------|-----|------|
"""

        best_overall = {'strategy': None, 'timeframe': None, 'total_return': float('-inf')}

        for strategy_data in self.summary_data['strategies']:
            strategy_name = strategy_data['strategy_name']
            best = self.find_best_timeframe(strategy_data['timeframes'])

            if best['timeframe']:
                report += f"| {strategy_name} | {best['timeframe']} | "
                report += f"{best['total_return']:>7.2f}% | "
                report += f"{best['sharpe_ratio']:>6.3f} | "
                report += f"{best['max_drawdown']:>6.2f}% | "
                report += f"{best['win_rate']*100:>5.1f}% |\n"

                # 전체 최고 전략 추적
                if best['total_return'] > best_overall['total_return']:
                    best_overall['strategy'] = strategy_name
                    best_overall['timeframe'] = best['timeframe']
                    best_overall['total_return'] = best['total_return']
                    best_overall['sharpe_ratio'] = best['sharpe_ratio']
                    best_overall['max_drawdown'] = best['max_drawdown']

        report += f"\n## 🏆 전체 최고 성과\n\n"
        if best_overall['strategy']:
            report += f"- **전략**: {best_overall['strategy']}\n"
            report += f"- **타임프레임**: {best_overall['timeframe']}\n"
            report += f"- **수익률**: {best_overall['total_return']:.2f}%\n"
            report += f"- **Sharpe Ratio**: {best_overall['sharpe_ratio']:.3f}\n"
            report += f"- **Max Drawdown**: {best_overall['max_drawdown']:.2f}%\n"
        else:
            report += "결과 없음\n"

        report += "\n## 📋 타임프레임별 전략 성과 히트맵\n\n"

        # 히트맵 (수익률 기준)
        report += "| 전략 | min5 | min15 | min30 | min60 | min240 | day |\n"
        report += "|------|------|-------|-------|-------|--------|-----|\n"

        for strategy_data in self.summary_data['strategies']:
            strategy_name = strategy_data['strategy_name']
            report += f"| {strategy_name} | "

            for tf in ['minute5', 'minute15', 'minute30', 'minute60', 'minute240', 'day']:
                data = strategy_data['timeframes'].get(tf)
                if data:
                    ret = data.get('total_return', 0)
                    if ret >= 20:
                        report += f"🟢 {ret:.1f}% | "
                    elif ret >= 10:
                        report += f"🟡 {ret:.1f}% | "
                    elif ret > 0:
                        report += f"🟠 {ret:.1f}% | "
                    else:
                        report += f"🔴 {ret:.1f}% | "
                else:
                    report += "⚫ - | "

            report += "\n"

        report += "\n**범례**: 🟢 >= 20% | 🟡 >= 10% | 🟠 > 0% | 🔴 <= 0% | ⚫ 실패\n"

        report += "\n## 💡 인사이트\n\n"

        # 타임프레임 선호도 분석
        timeframe_wins = {}
        for strategy_data in self.summary_data['strategies']:
            best = self.find_best_timeframe(strategy_data['timeframes'])
            if best['timeframe']:
                timeframe_wins[best['timeframe']] = timeframe_wins.get(best['timeframe'], 0) + 1

        if timeframe_wins:
            report += "### 타임프레임별 최적 전략 수\n\n"
            for tf, count in sorted(timeframe_wins.items(), key=lambda x: x[1], reverse=True):
                report += f"- **{tf}**: {count}개 전략\n"

        report += "\n### 권장사항\n\n"
        report += "1. 각 전략별 상세 리포트(`timeframe_comparison.md`)를 참고하여 최적 타임프레임 선택\n"
        report += "2. 수익률뿐 아니라 Sharpe Ratio와 MDD도 함께 고려\n"
        report += "3. 승률이 낮은 경우 리스크 관리 파라미터 조정 검토\n"
        report += "4. 여러 타임프레임에서 안정적인 성과를 내는 전략 우선 고려\n"

        return report

    def save_reports(self):
        """모든 리포트 저장"""
        if not self.summary_data:
            print("✗ 데이터가 로드되지 않았습니다.")
            return

        # 전략별 개별 리포트
        for strategy_data in self.summary_data['strategies']:
            strategy_name = strategy_data['strategy_name']
            strategy_path = Path(strategy_data['strategy_path'])

            report = self.generate_strategy_report(strategy_data)

            report_path = strategy_path / 'timeframe_comparison.md'
            with open(report_path, 'w', encoding='utf-8') as f:
                f.write(report)

            print(f"✓ {strategy_name} 리포트 생성: {report_path}")

        # 통합 리포트
        comprehensive_report = self.generate_comprehensive_report()
        comprehensive_path = self.strategies_dir / 'comprehensive_timeframe_analysis.md'

        with open(comprehensive_path, 'w', encoding='utf-8') as f:
            f.write(comprehensive_report)

        print(f"\n✓ 통합 리포트 생성: {comprehensive_path}")

    def run(self):
        """전체 비교 분석 실행"""
        print("="*70)
        print("📊 타임프레임 결과 비교 분석")
        print("="*70)

        if not self.load_summary():
            return

        print(f"\n분석 대상: {len(self.summary_data['strategies'])}개 전략")
        print(f"타임프레임: {', '.join(self.summary_data['timeframes'])}")

        self.save_reports()

        print("\n" + "="*70)
        print("✅ 모든 리포트 생성 완료")
        print("="*70)
        print("\n다음 단계:")
        print("  1. strategies/comprehensive_timeframe_analysis.md 확인")
        print("  2. 각 전략 폴더의 timeframe_comparison.md 확인")
        print("  3. 최적 타임프레임으로 전략 설정 업데이트")


def main():
    """메인 실행"""
    comparator = TimeframeComparator()
    comparator.run()


if __name__ == '__main__':
    main()
