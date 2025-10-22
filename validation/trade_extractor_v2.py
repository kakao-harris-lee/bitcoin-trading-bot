#!/usr/bin/env python3
"""
TradeExtractor v2 - 완벽한 거래 내역 추출
===========================================

개선사항:
1. 타임프레임 자동 추출 (config.json 또는 backtest.py 분석)
2. 포지션 누적 100% 상한선 정규화
3. 동적 익절/손절 파라미터 추출
4. Multi-timeframe 지원
5. 검증된 복리 계산 엔진 사용

Input:
  strategies/v{NN}_{name}/backtest_results.json
  strategies/v{NN}_{name}/config.json (타임프레임 확인)

Output:
  validation/signals_v2/v{NN}_{timeframe}_{year}_signals.json
"""

import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from datetime import datetime
import pandas as pd


class TradeExtractorV2:
    """개선된 거래 내역 추출기"""

    def __init__(self, project_root: Optional[Path] = None):
        if project_root is None:
            self.root = Path(__file__).parent.parent
        else:
            self.root = Path(project_root)

        self.output_dir = self.root / "validation" / "signals_v2"
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def extract_timeframe(self, strategy_path: Path) -> str:
        """
        전략의 타임프레임 추출

        우선순위:
        1. config.json의 'timeframe' 필드
        2. backtest_results.json의 'timeframe' 필드
        3. 기본값: 'day'
        """
        # 1. config.json 확인
        config_file = strategy_path / "config.json"
        if config_file.exists():
            try:
                with open(config_file, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    if 'timeframe' in config:
                        return config['timeframe']
            except:
                pass

        # 2. backtest_results.json 확인
        result_file = strategy_path / "backtest_results.json"
        if result_file.exists():
            try:
                with open(result_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if 'timeframe' in data:
                        return data['timeframe']
            except:
                pass

        # 3. 기본값
        return 'day'

    def normalize_position_fractions(self, trades: List[Tuple[Dict, Dict]]) -> List[Tuple[Dict, Dict]]:
        """
        포지션 누적을 100% 상한선으로 정규화

        예시:
        입력: [20%, 20%, 50%, 50%] = 140% (누적)
        출력: [20%, 20%, 50%, 10%] = 100% (정규화)

        Args:
            trades: [(buy_signal, sell_signal), ...] 리스트

        Returns:
            정규화된 trades
        """
        if not trades:
            return []

        normalized = []
        cumulative = 0.0

        for buy_sig, sell_sig in trades:
            original_fraction = buy_sig.get('position_size', 1.0)

            # 남은 여유분 계산
            remaining = 1.0 - cumulative

            # 실제 투자 가능 비율 (최대 남은 여유분)
            actual_fraction = min(original_fraction, remaining)

            # 누적 업데이트
            cumulative += actual_fraction

            # 정규화된 시그널 생성
            norm_buy = buy_sig.copy()
            norm_buy['position_size'] = actual_fraction
            norm_buy['original_position_size'] = original_fraction
            norm_buy['cumulative_after'] = cumulative

            normalized.append((norm_buy, sell_sig))

            # 100% 도달 시 중단
            if cumulative >= 0.9999:
                break

        return normalized

    def extract_exit_parameters(self, trade_str: str) -> Dict:
        """
        Trade 문자열에서 익절/손절 파라미터 추출

        Returns:
            {
                'take_profit_pct': 0.05,  # 5%
                'stop_loss_pct': -0.02,   # -2%
                'trailing_stop_pct': -0.01,
                'max_hold_hours': 72,
                'exit_reason': 'Take Profit'
            }
        """
        params = {}

        # reason 필드에서 추출
        reason_match = re.search(r"reason='([^']+)'", trade_str)
        if reason_match:
            reason = reason_match.group(1)
            params['exit_reason'] = reason

            # 익절/손절 패턴 (예: "TP 5.0%" or "SL -2.0%")
            tp_match = re.search(r'TP ([0-9.]+)%', reason)
            if tp_match:
                params['take_profit_pct'] = float(tp_match.group(1)) / 100.0

            sl_match = re.search(r'SL -?([0-9.]+)%', reason)
            if sl_match:
                params['stop_loss_pct'] = -abs(float(sl_match.group(1)) / 100.0)

            # Trailing Stop (예: "Trailing -1.0%")
            trail_match = re.search(r'Trailing -?([0-9.]+)%', reason)
            if trail_match:
                params['trailing_stop_pct'] = -abs(float(trail_match.group(1)) / 100.0)

            # Timeout (예: "Timeout 72h")
            timeout_match = re.search(r'Timeout ([0-9]+)h', reason)
            if timeout_match:
                params['max_hold_hours'] = int(timeout_match.group(1))

        return params

    def parse_trade_string(self, trade_str: str) -> Optional[Dict]:
        """
        Trade 문자열 완벽 파싱 (v2)

        개선사항:
        - 동적 익절/손절 파라미터 추출
        - 보유 시간 계산
        - reason 상세 분석
        """
        try:
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

            # position_fraction 추출 (Buy X% of cash)
            if 'reason' in parsed:
                reason = parsed['reason']
                buy_match = re.search(r'Buy ([0-9.]+)%', reason)
                if buy_match:
                    parsed['position_fraction'] = float(buy_match.group(1)) / 100.0
                else:
                    parsed['position_fraction'] = 1.0

            # 익절/손절 파라미터 추출
            exit_params = self.extract_exit_parameters(trade_str)
            parsed.update(exit_params)

            # 보유 시간 계산
            if 'entry_time' in parsed and 'exit_time' in parsed:
                entry = pd.to_datetime(parsed['entry_time'])
                exit = pd.to_datetime(parsed['exit_time'])
                hold_hours = (exit - entry).total_seconds() / 3600
                parsed['hold_hours'] = round(hold_hours, 2)

            # 필수 필드 검증
            required = ['entry_time', 'entry_price', 'exit_time', 'exit_price']
            if all(k in parsed for k in required):
                return parsed
            else:
                return None

        except Exception as e:
            print(f"⚠️  Trade 파싱 실패: {e}")
            return None

    def extract_year_signals_v2(self, year: str, year_data: Dict,
                                version: str, timeframe: str) -> Optional[Dict]:
        """
        개선된 연도별 시그널 추출 (v2)

        개선사항:
        - 포지션 누적 정규화
        - 익절/손절 파라미터 포함
        - 타임프레임 명시
        """
        trades = year_data.get('trades', [])
        if not trades:
            return None

        # 1. Trade 파싱
        parsed_trades = []
        for trade_str in trades:
            parsed = self.parse_trade_string(trade_str)
            if parsed:
                parsed_trades.append(parsed)

        if not parsed_trades:
            return None

        # 2. Buy/Sell 시그널 생성 (정규화 전)
        raw_buy_sell = []
        for i, parsed in enumerate(parsed_trades):
            buy_signal = {
                'timestamp': parsed['entry_time'],
                'price': parsed['entry_price'],
                'position_size': parsed.get('position_fraction', 1.0),
                'buy_index': i
            }

            sell_signal = {
                'timestamp': parsed['exit_time'],
                'price': parsed['exit_price'],
                'reason': parsed.get('exit_reason', 'Exit'),
                'buy_index': i,
                'original_profit_pct': parsed.get('profit_loss_pct', 0.0),
                'hold_hours': parsed.get('hold_hours', 0.0)
            }

            # 익절/손절 파라미터 추가
            if 'take_profit_pct' in parsed:
                sell_signal['take_profit_pct'] = parsed['take_profit_pct']
            if 'stop_loss_pct' in parsed:
                sell_signal['stop_loss_pct'] = parsed['stop_loss_pct']
            if 'trailing_stop_pct' in parsed:
                sell_signal['trailing_stop_pct'] = parsed['trailing_stop_pct']
            if 'max_hold_hours' in parsed:
                sell_signal['max_hold_hours'] = parsed['max_hold_hours']

            raw_buy_sell.append((buy_signal, sell_signal))

        # 3. 포지션 누적 정규화 (100% 상한선)
        normalized_trades = self.normalize_position_fractions(raw_buy_sell)

        # 4. Buy/Sell 시그널 분리
        buy_signals = [buy for buy, sell in normalized_trades]
        sell_signals = [sell for buy, sell in normalized_trades]

        # 5. 누적 포지션 통계
        total_original = sum(t[0].get('original_position_size', 1.0) for t in raw_buy_sell)
        total_normalized = sum(s['position_size'] for s in buy_signals)

        return {
            'version': version,
            'year': int(year),
            'timeframe': timeframe,
            'buy_signals': buy_signals,
            'sell_signals': sell_signals,
            'signal_count': len(buy_signals),

            # 원본 백테스트 결과
            'original_total_return': year_data.get('total_return', 0.0),
            'original_sharpe': year_data.get('sharpe_ratio', 0.0),
            'original_max_drawdown': year_data.get('max_drawdown', 0.0),
            'original_win_rate': year_data.get('win_rate', 0.0),
            'original_total_trades': year_data.get('total_trades', 0),

            # 포지션 정규화 정보
            'position_normalization': {
                'original_total': round(total_original, 4),
                'normalized_total': round(total_normalized, 4),
                'was_normalized': total_original > 1.0001,
                'reduction_pct': round((total_original - total_normalized) / total_original * 100, 2) if total_original > 0 else 0
            }
        }

    def extract_from_backtest_result_v2(self, result_path: Path,
                                       strategy_path: Path) -> Dict:
        """
        개선된 백테스트 결과 추출 (v2)

        Args:
            result_path: backtest_results.json 경로
            strategy_path: 전략 폴더 경로 (타임프레임 추출용)
        """
        with open(result_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        version = data.get('version', 'unknown')
        strategy_name = data.get('strategy_name', 'unknown')

        # 타임프레임 추출
        timeframe = data.get('timeframe') or self.extract_timeframe(strategy_path)

        results_by_year = data.get('results', {})

        extracted = {
            'version': version,
            'strategy_name': strategy_name,
            'timeframe': timeframe,
            'years': {}
        }

        for year, year_data in results_by_year.items():
            signals = self.extract_year_signals_v2(year, year_data, version, timeframe)
            if signals:
                extracted['years'][year] = signals

        return extracted

    def save_signals_v2(self, extracted: Dict, output_prefix: str = "signals"):
        """
        개선된 시그널 저장 (타임프레임 포함)

        Output 예시:
            validation/signals_v2/v38_day_2020_signals.json
            validation/signals_v2/v38_minute60_2021_signals.json
        """
        version = extracted['version']
        timeframe = extracted['timeframe']

        saved_files = []
        for year, signals in extracted['years'].items():
            # 타임프레임 포함 파일명
            output_file = self.output_dir / f"{version}_{timeframe}_{year}_signals.json"

            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(signals, f, indent=2, ensure_ascii=False)

            saved_files.append(output_file)

            # 정규화 정보 출력
            norm = signals.get('position_normalization', {})
            norm_info = ""
            if norm.get('was_normalized'):
                norm_info = f" (정규화: {norm['original_total']:.1%} → {norm['normalized_total']:.1%})"

            print(f"✅ {output_file.name}: {signals['signal_count']}개 거래{norm_info}")

        return saved_files

    def extract_strategy_v2(self, strategy_path: Path) -> Optional[Dict]:
        """
        개선된 전략 추출 (v2)

        Args:
            strategy_path: 전략 폴더 (e.g., strategies/v38_ensemble)
        """
        result_file = strategy_path / "backtest_results.json"

        if not result_file.exists():
            print(f"❌ {strategy_path.name}: backtest_results.json 없음")
            return None

        try:
            extracted = self.extract_from_backtest_result_v2(result_file, strategy_path)

            # 타임프레임 표시
            tf_info = f"[{extracted['timeframe']}]"
            print(f"📦 {strategy_path.name} {tf_info}: {len(extracted['years'])}개 연도 추출")

            return extracted

        except Exception as e:
            print(f"❌ {strategy_path.name}: 추출 실패 - {e}")
            import traceback
            traceback.print_exc()
            return None

    def extract_all_strategies_v2(self, strategy_list: Optional[List[str]] = None) -> Dict:
        """
        모든 전략 추출 (v2)

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
        print(f"  전략별 거래 내역 추출 v2 ({total_strategies}개)")
        print(f"{'='*70}\n")

        for i, path in enumerate(strategy_paths, 1):
            if not path.is_dir():
                continue

            print(f"[{i}/{total_strategies}] {path.name}")
            extracted = self.extract_strategy_v2(path)

            if extracted:
                results[path.name] = extracted
                self.save_signals_v2(extracted)

            print()

        print(f"{'='*70}")
        print(f"  완료: {len(results)}/{total_strategies}개 전략 추출")
        print(f"{'='*70}\n")

        return results


if __name__ == '__main__':
    """테스트 실행"""

    extractor = TradeExtractorV2()

    # 단일 전략 테스트 (v38_ensemble)
    print("=== TradeExtractor v2 테스트: v38_ensemble ===\n")

    v38_path = extractor.root / "strategies" / "v38_ensemble"
    extracted = extractor.extract_strategy_v2(v38_path)

    if extracted:
        print(f"\n추출 결과:")
        print(f"  버전: {extracted['version']}")
        print(f"  전략명: {extracted['strategy_name']}")
        print(f"  타임프레임: {extracted['timeframe']}")
        print(f"  연도 수: {len(extracted['years'])}")

        # 2020년 상세 정보
        if '2020' in extracted['years']:
            signals_2020 = extracted['years']['2020']
            print(f"\n  2020년 상세:")
            print(f"    거래 수: {signals_2020['signal_count']}")
            print(f"    원본 수익률: {signals_2020['original_total_return']:.2f}%")

            norm = signals_2020['position_normalization']
            print(f"\n    포지션 정규화:")
            print(f"      원본 누적: {norm['original_total']:.1%}")
            print(f"      정규화 후: {norm['normalized_total']:.1%}")
            print(f"      정규화 여부: {'예' if norm['was_normalized'] else '아니오'}")
            if norm['was_normalized']:
                print(f"      감소율: {norm['reduction_pct']:.1f}%")

            # 첫 3개 거래 표시
            print(f"\n    첫 3개 거래:")
            for i in range(min(3, len(signals_2020['buy_signals']))):
                buy = signals_2020['buy_signals'][i]
                sell = signals_2020['sell_signals'][i]
                print(f"      [{i+1}] {buy['timestamp']}: {buy['position_size']:.1%} "
                      f"(원본 {buy.get('original_position_size', 1.0):.1%}) @ {buy['price']:,.0f}원")
                print(f"          → {sell['timestamp']}: {sell['reason']} @ {sell['price']:,.0f}원 "
                      f"({sell['original_profit_pct']:+.2f}%)")

        # 파일 저장
        print(f"\n저장 중...")
        saved = extractor.save_signals_v2(extracted)
        print(f"\n저장 완료: {len(saved)}개 파일")
