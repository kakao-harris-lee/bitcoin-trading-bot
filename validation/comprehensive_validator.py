#!/usr/bin/env python3
"""
v37~v45 전략 포괄적 검증 시스템

기능:
1. 원본 백테스트 결과에서 매매 기록 추출
2. StandardCompoundEngine으로 재계산
3. 모든 매수/매도 기록 및 자산 변화 추적
4. 원본 vs 재계산 비교 보고서 생성
"""

import json
import re
from pathlib import Path
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass, asdict
from datetime import datetime
import sys

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from validation.standard_compound_engine_v2 import StandardCompoundEngineV2


@dataclass
class TradeRecord:
    """매매 기록"""
    timestamp: str
    action: str  # 'BUY' or 'SELL'
    price: float
    quantity: float  # BTC amount
    fraction: float  # Position size (0-1)
    capital_before: float
    btc_before: float
    capital_after: float
    btc_after: float
    total_value_before: float
    total_value_after: float
    profit_loss: Optional[float] = None
    profit_loss_pct: Optional[float] = None
    reason: Optional[str] = None
    trade_id: Optional[int] = None


@dataclass
class AssetSnapshot:
    """자산 스냅샷"""
    timestamp: str
    capital: float
    btc_amount: float
    btc_value: float  # BTC × current price
    total_value: float
    total_return_pct: float
    trade_id: Optional[int] = None
    event: Optional[str] = None  # 'BUY', 'SELL', or None


class ComprehensiveValidator:
    """포괄적 검증 시스템"""

    def __init__(self, initial_capital: float = 10_000_000):
        self.initial_capital = initial_capital
        self.engine = StandardCompoundEngineV2(
            initial_capital=initial_capital,
            fee_rate=0.0005,
            slippage=0.0002
        )

    def parse_trade_string(self, trade_str: str) -> Dict:
        """Trade 객체 문자열 파싱"""
        patterns = {
            'entry_time': r"entry_time=Timestamp\('([^']+)'\)",
            'entry_price': r"entry_price=(?:np\.float64\()?([0-9.]+)\)?",
            'quantity': r"quantity=(?:np\.float64\()?([0-9.]+)\)?",
            'exit_time': r"exit_time=Timestamp\('([^']+)'\)",
            'exit_price': r"exit_price=(?:np\.float64\()?([0-9.]+)\)?",
            'profit_loss': r"profit_loss=(?:np\.float64\()?(-?[0-9.]+)\)?",
            'profit_loss_pct': r"profit_loss_pct=(?:np\.float64\()?(-?[0-9.]+)\)?",
            'reason': r"reason='([^']+)'"
        }

        result = {}
        for key, pattern in patterns.items():
            match = re.search(pattern, trade_str)
            if match:
                value = match.group(1)
                if key in ['entry_price', 'exit_price', 'quantity', 'profit_loss', 'profit_loss_pct']:
                    result[key] = float(value)
                else:
                    result[key] = value

        # Extract position fraction from reason
        if 'reason' in result:
            frac_match = re.search(r'Buy ([0-9.]+)%', result['reason'])
            if frac_match:
                result['fraction'] = float(frac_match.group(1)) / 100.0
            else:
                result['fraction'] = 1.0

        return result

    def extract_trades_from_backtest_result(self, result_path: Path) -> Dict:
        """backtest_results.json에서 거래 추출"""
        with open(result_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        version = data.get('version', 'unknown')
        results_by_year = data.get('results', {})

        all_trades = {}

        for year, year_data in results_by_year.items():
            trades_raw = year_data.get('trades', [])

            trade_pairs = []
            for trade_str in trades_raw:
                if isinstance(trade_str, str):
                    parsed = self.parse_trade_string(trade_str)
                    if parsed:
                        trade_pairs.append(parsed)

            all_trades[year] = {
                'trades': trade_pairs,
                'original_return': year_data.get('total_return', 0),
                'original_sharpe': year_data.get('sharpe_ratio', 0),
                'original_total_trades': year_data.get('total_trades', 0),
                'original_win_rate': year_data.get('win_rate', 0)
            }

        return {
            'version': version,
            'years': all_trades
        }

    def validate_year(self, version: str, year: str, trades: List[Dict],
                     price_data: Optional[Dict] = None) -> Dict:
        """연도별 거래 검증"""
        self.engine.reset()

        trade_records = []
        asset_snapshots = []
        trade_id = 0

        # Initial snapshot
        asset_snapshots.append(AssetSnapshot(
            timestamp=f"{year}-01-01 09:00:00",
            capital=self.engine.capital,
            btc_amount=self.engine.btc_amount,
            btc_value=0,
            total_value=self.engine.capital,
            total_return_pct=0,
            event=None
        ))

        for trade in trades:
            entry_time = trade.get('entry_time')
            entry_price = trade.get('entry_price')
            quantity = trade.get('quantity')
            fraction = trade.get('fraction', 1.0)
            exit_time = trade.get('exit_time')
            exit_price = trade.get('exit_price')
            reason = trade.get('reason', '')

            # BUY
            capital_before = self.engine.capital
            btc_before = self.engine.btc_amount
            total_before = capital_before + (btc_before * entry_price)

            buy_success = self.engine.buy(entry_time, entry_price, fraction)

            if buy_success:
                capital_after = self.engine.capital
                btc_after = self.engine.btc_amount
                total_after = capital_after + (btc_after * entry_price)

                # Record BUY
                trade_records.append(TradeRecord(
                    timestamp=entry_time,
                    action='BUY',
                    price=entry_price,
                    quantity=btc_after - btc_before,
                    fraction=fraction,
                    capital_before=capital_before,
                    btc_before=btc_before,
                    capital_after=capital_after,
                    btc_after=btc_after,
                    total_value_before=total_before,
                    total_value_after=total_after,
                    reason=f"Buy {fraction*100:.1f}%",
                    trade_id=trade_id
                ))

                # Snapshot after BUY
                asset_snapshots.append(AssetSnapshot(
                    timestamp=entry_time,
                    capital=capital_after,
                    btc_amount=btc_after,
                    btc_value=btc_after * entry_price,
                    total_value=total_after,
                    total_return_pct=((total_after / self.initial_capital) - 1) * 100,
                    trade_id=trade_id,
                    event='BUY'
                ))

            # SELL
            capital_before = self.engine.capital
            btc_before = self.engine.btc_amount
            total_before = capital_before + (btc_before * exit_price)

            sell_success = self.engine.sell(exit_time, exit_price, fraction=1.0, reason=reason)

            if sell_success:
                capital_after = self.engine.capital
                btc_after = self.engine.btc_amount
                total_after = capital_after + (btc_after * exit_price)

                # Calculate profit/loss
                pl = capital_after - capital_before
                pl_pct = ((exit_price / entry_price) - 1) * 100 if entry_price > 0 else 0

                # Record SELL
                trade_records.append(TradeRecord(
                    timestamp=exit_time,
                    action='SELL',
                    price=exit_price,
                    quantity=btc_before - btc_after,
                    fraction=1.0,
                    capital_before=capital_before,
                    btc_before=btc_before,
                    capital_after=capital_after,
                    btc_after=btc_after,
                    total_value_before=total_before,
                    total_value_after=total_after,
                    profit_loss=pl,
                    profit_loss_pct=pl_pct,
                    reason=reason,
                    trade_id=trade_id
                ))

                # Snapshot after SELL
                asset_snapshots.append(AssetSnapshot(
                    timestamp=exit_time,
                    capital=capital_after,
                    btc_amount=btc_after,
                    btc_value=btc_after * exit_price,
                    total_value=total_after,
                    total_return_pct=((total_after / self.initial_capital) - 1) * 100,
                    trade_id=trade_id,
                    event='SELL'
                ))

                trade_id += 1

        # Final statistics
        stats = self.engine.calculate_stats()

        return {
            'version': version,
            'year': year,
            'initial_capital': self.initial_capital,
            'final_capital': self.engine.capital,
            'final_btc': self.engine.btc_amount,
            'total_return_pct': stats['total_return_pct'],
            'total_trades': len(trades),
            'trade_records': [asdict(tr) for tr in trade_records],
            'asset_snapshots': [asdict(snap) for snap in asset_snapshots],
            'statistics': stats
        }

    def validate_strategy(self, strategy_path: Path) -> Dict:
        """전략 전체 검증"""
        result_files = [
            strategy_path / 'backtest_results.json',
            strategy_path / 'results.json',
            strategy_path / 'results' / 'comprehensive_results.json',  # v43
            strategy_path / 'results' / 'multi_year_results.json',  # v44
            strategy_path / 'results' / 'result_2024.json'  # v44 single year
        ]

        result_path = None
        for rf in result_files:
            if rf.exists():
                result_path = rf
                break

        if not result_path:
            return {'error': f'No result file found in {strategy_path}'}

        # Extract trades
        extracted = self.extract_trades_from_backtest_result(result_path)
        version = extracted['version']

        # Validate each year
        validation_results = {}
        comparison = {}

        for year, year_data in extracted['years'].items():
            trades = year_data['trades']

            if not trades:
                continue

            # Validate
            validated = self.validate_year(version, year, trades)
            validation_results[year] = validated

            # Compare
            original_return = year_data['original_return']
            validated_return = validated['total_return_pct']
            diff = validated_return - original_return
            diff_pct = (diff / original_return * 100) if original_return != 0 else 0

            comparison[year] = {
                'original_return_pct': original_return,
                'validated_return_pct': validated_return,
                'difference_pct': diff,
                'difference_relative': diff_pct,
                'match': abs(diff_pct) < 1.0  # 1% tolerance
            }

        return {
            'strategy': version,
            'path': str(strategy_path),
            'validation_results': validation_results,
            'comparison': comparison,
            'summary': {
                'total_years': len(validation_results),
                'matching_years': sum(1 for c in comparison.values() if c['match']),
                'mismatching_years': sum(1 for c in comparison.values() if not c['match'])
            }
        }


def main():
    """메인 실행"""
    import argparse

    parser = argparse.ArgumentParser(description='v37~v45 전략 포괄적 검증')
    parser.add_argument('--strategies', nargs='+',
                       default=['v37', 'v38', 'v39', 'v40', 'v43', 'v45'],
                       help='검증할 전략 목록')
    parser.add_argument('--output', type=str,
                       default='validation/comprehensive_validation_results',
                       help='결과 저장 디렉터리')

    args = parser.parse_args()

    validator = ComprehensiveValidator()
    base_path = Path('strategies')
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    all_results = {}

    for strategy_name in args.strategies:
        # Find strategy directory
        strategy_dirs = list(base_path.glob(f'{strategy_name}_*'))

        if not strategy_dirs:
            print(f"⚠️  {strategy_name}: Directory not found")
            continue

        strategy_path = strategy_dirs[0]
        print(f"\n{'='*80}")
        print(f"🔍 Validating: {strategy_path.name}")
        print(f"{'='*80}")

        result = validator.validate_strategy(strategy_path)
        all_results[strategy_name] = result

        # Save individual result
        output_file = output_dir / f'{strategy_name}_validation.json'
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(result, f, indent=2, ensure_ascii=False)

        print(f"✅ Saved: {output_file}")

        # Print summary
        if 'summary' in result:
            summary = result['summary']
            print(f"\n📊 Summary:")
            print(f"   Total Years: {summary['total_years']}")
            print(f"   Matching: {summary['matching_years']}")
            print(f"   Mismatching: {summary['mismatching_years']}")

            if 'comparison' in result:
                print(f"\n📈 Comparison:")
                for year, comp in result['comparison'].items():
                    match_icon = "✅" if comp['match'] else "⚠️"
                    print(f"   {year}: {match_icon} Original {comp['original_return_pct']:.2f}% → "
                          f"Validated {comp['validated_return_pct']:.2f}% "
                          f"(Δ {comp['difference_pct']:.2f}%)")

    # Save combined results
    combined_file = output_dir / 'all_strategies_validation.json'
    with open(combined_file, 'w', encoding='utf-8') as f:
        json.dump(all_results, f, indent=2, ensure_ascii=False)

    print(f"\n{'='*80}")
    print(f"✅ All results saved to: {output_dir}")
    print(f"📄 Combined: {combined_file}")
    print(f"{'='*80}")


if __name__ == '__main__':
    main()
