#!/usr/bin/env python3
"""
TradeExtractor - 기존 백테스트 결과에서 거래 내역 추출
=====================================================

목적:
  전략별 backtest_results.json에서 trades를 추출하여
  StandardEvaluator로 재평가할 수 있는 signals 형식으로 변환

Input:
  strategies/v{NN}_{name}/backtest_results.json

Output:
  validation/signals/v{NN}_{name}_{year}_signals.json
  {
    "version": "v38",
    "year": 2024,
    "timeframe": "day",
    "buy_signals": [...],
    "sell_signals": [...],
    "signal_count": N
  }
"""

import json
import re
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime
import pandas as pd


class TradeExtractor:
    """백테스트 결과에서 거래 내역 추출"""

    def __init__(self, project_root: Optional[Path] = None):
        """
        Args:
            project_root: 프로젝트 루트 디렉터리 (기본값: 현재 파일 기준 상위 3단계)
        """
        if project_root is None:
            self.root = Path(__file__).parent.parent
        else:
            self.root = Path(project_root)

        self.output_dir = self.root / "validation" / "signals"
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def extract_from_backtest_result(self, result_path: Path) -> Dict:
        """
        backtest_results.json에서 모든 연도의 거래 내역 추출

        Args:
            result_path: backtest_results.json 경로

        Returns:
            {
                'version': 'v38',
                'strategy_name': 'ensemble',
                'timeframe': 'day',
                'years': {
                    '2020': {'buy_signals': [...], 'sell_signals': [...], ...},
                    '2021': {...},
                    ...
                }
            }
        """
        with open(result_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        version = data.get('version', 'unknown')
        strategy_name = data.get('strategy_name', 'unknown')
        timeframe = data.get('timeframe', 'day')
        results_by_year = data.get('results', {})

        extracted = {
            'version': version,
            'strategy_name': strategy_name,
            'timeframe': timeframe,
            'years': {}
        }

        for year, year_data in results_by_year.items():
            signals = self._extract_year_signals(year, year_data, version, timeframe)
            if signals:
                extracted['years'][year] = signals

        return extracted

    def _extract_year_signals(self, year: str, year_data: Dict, version: str, timeframe: str) -> Optional[Dict]:
        """
        단일 연도의 거래 내역 추출

        Args:
            year: 연도 (문자열, e.g., "2024")
            year_data: 해당 연도의 백테스트 결과 딕셔너리
            version: 전략 버전
            timeframe: 타임프레임

        Returns:
            {
                'year': 2024,
                'timeframe': 'day',
                'buy_signals': [...],
                'sell_signals': [...],
                'signal_count': N,
                'original_total_return': X.XX,
                'original_sharpe': Y.YY
            }
        """
        trades = year_data.get('trades', [])

        if not trades:
            return None

        # Trade 객체 파싱
        buy_signals = []
        sell_signals = []

        for i, trade_str in enumerate(trades):
            parsed = self._parse_trade_string(trade_str)
            if not parsed:
                continue

            buy_signal = {
                'timestamp': parsed['entry_time'],
                'price': parsed['entry_price'],
                'position_size': parsed.get('position_fraction', 1.0),
                'buy_index': i
            }
            buy_signals.append(buy_signal)

            sell_signal = {
                'timestamp': parsed['exit_time'],
                'price': parsed['exit_price'],
                'reason': parsed.get('reason', 'Exit'),
                'buy_index': i,
                'original_profit_pct': parsed.get('profit_loss_pct', 0.0)
            }
            sell_signals.append(sell_signal)

        return {
            'version': version,
            'year': int(year),
            'timeframe': timeframe,
            'buy_signals': buy_signals,
            'sell_signals': sell_signals,
            'signal_count': len(buy_signals),
            'original_total_return': year_data.get('total_return', 0.0),
            'original_sharpe': year_data.get('sharpe_ratio', 0.0),
            'original_max_drawdown': year_data.get('max_drawdown', 0.0),
            'original_win_rate': year_data.get('win_rate', 0.0),
            'original_total_trades': year_data.get('total_trades', 0)
        }

    def _parse_trade_string(self, trade_str: str) -> Optional[Dict]:
        """
        Trade 문자열 파싱

        Input 예시:
            "Trade(entry_time=Timestamp('2024-06-24 09:00:00'), entry_price=np.float64(85513099.2),
             quantity=np.float64(0.023376541353913708), side='buy',
             exit_time=Timestamp('2024-07-05 09:00:00'), exit_price=np.float64(81101776.4),
             profit_loss=np.float64(-103121.46985966233), profit_loss_pct=np.float64(-5.158651529729608),
             reason='Buy 20.0% of cash -> Sell 100.0%')"

        Returns:
            {
                'entry_time': '2024-06-24 09:00:00',
                'entry_price': 85513099.2,
                'exit_time': '2024-07-05 09:00:00',
                'exit_price': 81101776.4,
                'profit_loss_pct': -5.158651529729608,
                'reason': 'Buy 20.0% of cash -> Sell 100.0%',
                'position_fraction': 0.2  # reason에서 추출
            }
        """
        try:
            # 정규식 패턴
            patterns = {
                'entry_time': r"entry_time=Timestamp\('([^']+)'\)",
                'entry_price': r"entry_price=(?:np\.float64\()?([0-9.]+)",
                'exit_time': r"exit_time=Timestamp\('([^']+)'\)",
                'exit_price': r"exit_price=(?:np\.float64\()?([0-9.]+)",
                'profit_loss_pct': r"profit_loss_pct=(?:np\.float64\()?([-0-9.]+)",
                'reason': r"reason='([^']+)'"
            }

            parsed = {}
            for key, pattern in patterns.items():
                match = re.search(pattern, trade_str)
                if match:
                    value = match.group(1)
                    if key in ['entry_price', 'exit_price', 'profit_loss_pct']:
                        parsed[key] = float(value)
                    else:
                        parsed[key] = value

            # reason에서 position_fraction 추출 (Buy X% of cash)
            if 'reason' in parsed:
                reason = parsed['reason']
                buy_match = re.search(r'Buy ([0-9.]+)%', reason)
                if buy_match:
                    parsed['position_fraction'] = float(buy_match.group(1)) / 100.0
                else:
                    parsed['position_fraction'] = 1.0  # 기본값: 전액

            # 필수 필드 검증
            required = ['entry_time', 'entry_price', 'exit_time', 'exit_price']
            if all(k in parsed for k in required):
                return parsed
            else:
                return None

        except Exception as e:
            print(f"⚠️  Trade 파싱 실패: {e}")
            print(f"   Trade string: {trade_str[:100]}...")
            return None

    def save_signals(self, extracted: Dict, output_prefix: str = "signals"):
        """
        추출한 시그널을 파일로 저장

        Args:
            extracted: extract_from_backtest_result() 결과
            output_prefix: 출력 파일명 prefix (기본값: "signals")

        Output:
            validation/signals/{version}_{year}_signals.json (각 연도별)
        """
        version = extracted['version']

        saved_files = []
        for year, signals in extracted['years'].items():
            output_file = self.output_dir / f"{version}_{year}_signals.json"

            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(signals, f, indent=2, ensure_ascii=False)

            saved_files.append(output_file)
            print(f"✅ {output_file.name}: {signals['signal_count']}개 거래")

        return saved_files

    def extract_strategy(self, strategy_path: Path) -> Optional[Dict]:
        """
        전략 폴더에서 backtest_results.json 찾아서 추출

        Args:
            strategy_path: 전략 폴더 (e.g., strategies/v38_ensemble)

        Returns:
            extract_from_backtest_result() 결과 또는 None
        """
        result_file = strategy_path / "backtest_results.json"

        if not result_file.exists():
            print(f"❌ {strategy_path.name}: backtest_results.json 없음")
            return None

        try:
            extracted = self.extract_from_backtest_result(result_file)
            print(f"📦 {strategy_path.name}: {len(extracted['years'])}개 연도 추출")
            return extracted

        except Exception as e:
            print(f"❌ {strategy_path.name}: 추출 실패 - {e}")
            return None

    def extract_all_strategies(self, strategy_list: Optional[List[str]] = None) -> Dict:
        """
        모든 전략에서 거래 내역 추출

        Args:
            strategy_list: 추출할 전략 리스트 (기본값: None, 모든 전략)

        Returns:
            {
                'v38_ensemble': {...},
                'v37_supreme': {...},
                ...
            }
        """
        strategies_dir = self.root / "strategies"

        if strategy_list:
            strategy_paths = [strategies_dir / name for name in strategy_list]
        else:
            strategy_paths = sorted(strategies_dir.glob("v*"))

        results = {}
        total_strategies = len(strategy_paths)

        print(f"{'='*70}")
        print(f"  전략별 거래 내역 추출 ({total_strategies}개)")
        print(f"{'='*70}\n")

        for i, path in enumerate(strategy_paths, 1):
            if not path.is_dir():
                continue

            print(f"[{i}/{total_strategies}] {path.name}")
            extracted = self.extract_strategy(path)

            if extracted:
                results[path.name] = extracted
                self.save_signals(extracted)

            print()

        print(f"{'='*70}")
        print(f"  완료: {len(results)}/{total_strategies}개 전략 추출")
        print(f"{'='*70}\n")

        return results


if __name__ == '__main__':
    """테스트 실행"""

    extractor = TradeExtractor()

    # 단일 전략 테스트 (v38_ensemble)
    print("=== 단일 전략 테스트: v38_ensemble ===\n")

    v38_path = extractor.root / "strategies" / "v38_ensemble"
    extracted = extractor.extract_strategy(v38_path)

    if extracted:
        print(f"\n추출 결과:")
        print(f"  버전: {extracted['version']}")
        print(f"  전략명: {extracted['strategy_name']}")
        print(f"  타임프레임: {extracted['timeframe']}")
        print(f"  연도 수: {len(extracted['years'])}")

        for year, signals in extracted['years'].items():
            print(f"\n  {year}년:")
            print(f"    거래 수: {signals['signal_count']}")
            print(f"    원본 수익률: {signals['original_total_return']:.2f}%")
            print(f"    원본 Sharpe: {signals['original_sharpe']:.2f}")

            if signals['buy_signals']:
                first_buy = signals['buy_signals'][0]
                print(f"    첫 거래: {first_buy['timestamp']} @ {first_buy['price']:,.0f}원")

        # 파일 저장
        print(f"\n저장 중...")
        saved = extractor.save_signals(extracted)
        print(f"저장 완료: {len(saved)}개 파일")
