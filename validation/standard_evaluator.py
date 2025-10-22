"""
표준 평가 엔진
시그널 기반으로 표준 복리 계산을 수행하여 전략 성과를 평가
"""

from pathlib import Path
import sys
import json
from typing import Dict, List, Optional
import pandas as pd
import numpy as np
from datetime import datetime

# StandardCompoundEngine import
sys.path.insert(0, str(Path(__file__).parent))
from standard_compound_engine import StandardCompoundEngine


class StandardEvaluator:
    """표준 복리 계산 기반 평가 엔진"""

    def __init__(self,
                 initial_capital: float = 10_000_000,
                 fee_rate: float = 0.0005,
                 slippage: float = 0.0002):
        """
        Args:
            initial_capital: 초기 자본 (기본 1000만원)
            fee_rate: 거래 수수료 (기본 0.05%)
            slippage: 슬리피지 (기본 0.02%)
        """
        self.initial_capital = initial_capital
        self.fee_rate = fee_rate
        self.slippage = slippage

    def evaluate_signals(self, signals_data: Dict) -> Dict:
        """시그널 기반 평가

        Args:
            signals_data: BaseSignalExtractor.extract_all()의 반환값
                {
                    'version': 'v31',
                    'strategy_name': 'scalping',
                    'year': 2020,
                    'timeframe': 'day',
                    'buy_signals': [...],
                    'sell_signals': [...],
                    'signal_count': 10
                }

        Returns:
            {
                'version': 'v31',
                'year': 2020,
                'timeframe': 'day',
                'total_return_pct': 105.5,
                'final_capital': 20550000,
                'sharpe_ratio': 1.8,
                'max_drawdown_pct': -12.3,
                'total_trades': 10,
                'winning_trades': 6,
                'losing_trades': 4,
                'win_rate': 0.6,
                'avg_profit_pct': 5.2,
                'avg_loss_pct': -2.1,
                'profit_factor': 2.5,
                'trades': [...],  # 상세 거래 내역
                'equity_curve': [...],  # 자본 곡선
                'evaluation_date': '2025-10-21...'
            }
        """
        version = signals_data.get('version', 'unknown')
        year = signals_data.get('year', 0)
        timeframe = signals_data.get('timeframe', 'day')
        buy_signals = signals_data.get('buy_signals', [])
        sell_signals = signals_data.get('sell_signals', [])

        print(f"[StandardEvaluator] {version} {year} {timeframe} 평가 시작...")
        print(f"  시그널 개수: 매수 {len(buy_signals)}, 매도 {len(sell_signals)}")

        # 시그널 개수 검증
        if len(buy_signals) != len(sell_signals):
            return {
                'version': version,
                'year': year,
                'timeframe': timeframe,
                'error': f'Signal mismatch: buy={len(buy_signals)}, sell={len(sell_signals)}',
                'evaluation_date': datetime.now().isoformat()
            }

        if len(buy_signals) == 0:
            # 거래 없음
            return self._create_empty_result(version, year, timeframe)

        # StandardCompoundEngine 생성
        engine = StandardCompoundEngine(
            initial_capital=self.initial_capital,
            fee_rate=self.fee_rate,
            slippage=self.slippage
        )

        # 시그널 기반 거래 시뮬레이션
        for i, (buy_sig, sell_sig) in enumerate(zip(buy_signals, sell_signals)):
            # 매수
            buy_timestamp = buy_sig['timestamp']
            buy_price = buy_sig['price']
            position_size = buy_sig.get('position_size', 1.0)  # 기본 100%

            engine.buy(
                timestamp=buy_timestamp,
                price=buy_price,
                fraction=position_size
            )

            # 매도
            sell_timestamp = sell_sig['timestamp']
            sell_price = sell_sig['price']
            sell_reason = sell_sig.get('reason', 'Exit')

            engine.sell(
                timestamp=sell_timestamp,
                price=sell_price,
                reason=sell_reason
            )

        # 통계 계산
        stats = engine.calculate_stats()

        # 결과 생성
        result = {
            'version': version,
            'strategy_name': signals_data.get('strategy_name', ''),
            'year': year,
            'timeframe': timeframe,
            'initial_capital': stats['initial_capital'],
            'final_capital': stats['final_capital'],
            'total_return_pct': stats['total_return_pct'],
            'sharpe_ratio': stats['sharpe_ratio'],
            'max_drawdown_pct': stats['max_drawdown'],
            'total_trades': stats['total_trades'],
            'winning_trades': stats['wins'],
            'losing_trades': stats['losses'],
            'win_rate': stats['win_rate'],
            'avg_profit_pct': stats['avg_profit_pct'],
            'avg_loss_pct': stats['avg_loss_pct'],
            'profit_factor': stats['profit_factor'],
            'trades': engine.trades,
            'equity_curve': engine.equity_curve,
            'evaluation_date': datetime.now().isoformat()
        }

        print(f"[StandardEvaluator] {version} {year} {timeframe} 평가 완료")
        print(f"  수익률: {result['total_return_pct']:.2f}%")
        print(f"  Sharpe: {result['sharpe_ratio']:.2f}")
        print(f"  MDD: {result['max_drawdown_pct']:.2f}%")
        print(f"  거래: {result['total_trades']}회 (승률 {result['win_rate']*100:.1f}%)")

        return result

    def _create_empty_result(self, version: str, year: int, timeframe: str) -> Dict:
        """거래 없음 결과 생성"""
        return {
            'version': version,
            'year': year,
            'timeframe': timeframe,
            'initial_capital': self.initial_capital,
            'final_capital': self.initial_capital,
            'total_return_pct': 0.0,
            'sharpe_ratio': 0.0,
            'max_drawdown_pct': 0.0,
            'total_trades': 0,
            'winning_trades': 0,
            'losing_trades': 0,
            'win_rate': 0.0,
            'avg_profit_pct': 0.0,
            'avg_loss_pct': 0.0,
            'profit_factor': 0.0,
            'trades': [],
            'equity_curve': [],
            'evaluation_date': datetime.now().isoformat(),
            'note': 'No trades'
        }

    def save_evaluation(self, evaluation: Dict, output_dir: Optional[Path] = None):
        """평가 결과 저장

        Args:
            evaluation: evaluate_signals()의 반환값
            output_dir: 저장 디렉토리 (기본: validation/results/)
        """
        if output_dir is None:
            output_dir = Path(__file__).parent / "results"

        output_dir.mkdir(parents=True, exist_ok=True)

        # 파일명: v31_evaluation_2020_day.json
        filename = f"{evaluation['version']}_evaluation_{evaluation['year']}_{evaluation['timeframe']}.json"
        filepath = output_dir / filename

        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(evaluation, f, indent=2, ensure_ascii=False)

        print(f"[StandardEvaluator] 평가 결과 저장: {filepath}")

    def evaluate_all_years(self,
                          version: str,
                          strategy_name: str,
                          years: List[int],
                          timeframe: str = 'day',
                          signals_dir: Optional[Path] = None) -> Dict:
        """전체 연도 평가

        Args:
            version: 버전 (예: 'v31')
            strategy_name: 전략 이름
            years: 연도 리스트 [2020, 2021, ...]
            timeframe: 타임프레임
            signals_dir: 시그널 디렉토리

        Returns:
            {
                '2020': {...},
                '2021': {...},
                ...
                'summary': {
                    'avg_return': 45.5,
                    'avg_sharpe': 1.5,
                    'total_trades': 50,
                    ...
                }
            }
        """
        if signals_dir is None:
            signals_dir = Path(__file__).parent / "signals"

        results = {}

        for year in years:
            # 시그널 파일 로드
            signal_file = signals_dir / f"{version}_signals_{year}_{timeframe}.json"

            if not signal_file.exists():
                print(f"[StandardEvaluator] 시그널 파일 없음: {signal_file}")
                results[str(year)] = {
                    'error': 'Signal file not found',
                    'year': year
                }
                continue

            with open(signal_file, 'r', encoding='utf-8') as f:
                signals_data = json.load(f)

            # 평가
            evaluation = self.evaluate_signals(signals_data)
            results[str(year)] = evaluation

            # 저장
            self.save_evaluation(evaluation)

        # 요약 통계
        summary = self._calculate_summary(results)
        results['summary'] = summary

        return results

    def _calculate_summary(self, year_results: Dict) -> Dict:
        """연도별 결과 요약 통계"""
        valid_years = [r for r in year_results.values()
                      if isinstance(r, dict) and 'error' not in r]

        if not valid_years:
            return {'error': 'No valid results'}

        returns = [r['total_return_pct'] for r in valid_years]
        sharpes = [r['sharpe_ratio'] for r in valid_years]
        mdds = [r['max_drawdown_pct'] for r in valid_years]
        trades = [r['total_trades'] for r in valid_years]
        win_rates = [r['win_rate'] for r in valid_years]

        return {
            'years_evaluated': len(valid_years),
            'avg_return_pct': np.mean(returns),
            'median_return_pct': np.median(returns),
            'std_return_pct': np.std(returns),
            'min_return_pct': np.min(returns),
            'max_return_pct': np.max(returns),
            'avg_sharpe': np.mean(sharpes),
            'avg_mdd_pct': np.mean(mdds),
            'total_trades': sum(trades),
            'avg_win_rate': np.mean(win_rates),
            'cagr': self._calculate_cagr(returns, len(valid_years))
        }

    def _calculate_cagr(self, returns: List[float], years: int) -> float:
        """연평균 성장률 (CAGR) 계산"""
        if years == 0:
            return 0.0

        # 복리 계산: (1+r1) * (1+r2) * ... * (1+rn)
        compound = 1.0
        for r in returns:
            compound *= (1 + r / 100)

        # CAGR = (최종값 / 초기값)^(1/기간) - 1
        cagr = (compound ** (1 / years) - 1) * 100
        return cagr


if __name__ == "__main__":
    # 테스트
    evaluator = StandardEvaluator()

    # 간단한 테스트 시그널
    test_signals = {
        'version': 'test',
        'strategy_name': 'test_strategy',
        'year': 2020,
        'timeframe': 'day',
        'buy_signals': [
            {
                'timestamp': '2020-03-22 09:00:00',
                'price': 7367473.2,
                'position_size': 1.0
            }
        ],
        'sell_signals': [
            {
                'buy_index': 0,
                'timestamp': '2020-12-30 09:00:00',
                'price': 31884621.8,
                'reason': 'Test Exit'
            }
        ],
        'signal_count': 1
    }

    result = evaluator.evaluate_signals(test_signals)
    print("\n테스트 결과:")
    print(json.dumps(result, indent=2, ensure_ascii=False))
