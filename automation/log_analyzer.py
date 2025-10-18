#!/usr/bin/env python3
"""
log_analyzer.py
로그 분석기 - 기존 결과 분석 및 패턴 추출
"""

import sqlite3
from pathlib import Path
from typing import Dict, List

class LogAnalyzer:
    """로그 분석기"""

    def __init__(self, project_root: str = "."):
        self.project_root = Path(project_root)
        self.db_path = self.project_root / "trading_results.db"
        self.plans_dir = self.project_root / "strategies" / "_plans"
        self.results_dir = self.project_root / "strategies" / "_results"

    def analyze_all_versions(self) -> Dict:
        """모든 버전 분석"""
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()

        cursor.execute("""
            SELECT s.version, s.name, b.total_return, b.sharpe_ratio, b.max_drawdown, b.win_rate
            FROM strategies s
            LEFT JOIN backtest_results b ON s.strategy_id = b.strategy_id
            ORDER BY s.version
        """)

        results = cursor.fetchall()
        conn.close()

        if not results:
            return {
                'count': 0,
                'best_version': None,
                'patterns': []
            }

        # 최고 성과 버전
        best = max(results, key=lambda x: x[2] if x[2] else 0)

        return {
            'count': len(results),
            'best_version': best[0],
            'best_return': best[2],
            'all_versions': results,
            'patterns': self._extract_patterns(results)
        }

    def _extract_patterns(self, results: List) -> List[str]:
        """패턴 추출"""
        patterns = []
        # TODO: 실제 패턴 추출 로직
        patterns.append("Sample pattern: RSI가 효과적")
        return patterns

if __name__ == "__main__":
    analyzer = LogAnalyzer()
    analysis = analyzer.analyze_all_versions()
    print(f"분석된 버전: {analysis['count']}개")
    print(f"최고 성과: {analysis['best_version']}")
