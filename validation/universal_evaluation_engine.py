#!/usr/bin/env python3
"""
Universal Evaluation Engine
============================
모든 전략의 시그널을 평가하는 범용 엔진

작성일: 2025-10-21
버전: 1.0

핵심 기능:
- 플러그인 기반 청산 전략 (fixed, dynamic, trailing, composite)
- 플러그인 기반 포지션 크기 (fixed, kelly, score_based)
- 6년(2020-2025) × 23개 보유 기간 = 138개 조합 평가
- 2020-2024 최적화, 2025 검증 (Out-of-Sample)
- 기존 51개 전략 패턴 모두 호환
"""

import json
import sqlite3
from pathlib import Path
from typing import Dict, List, Optional, Any, Callable
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict
import pandas as pd
import numpy as np
from concurrent.futures import ProcessPoolExecutor, as_completed
import logging

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


# ========================================
# 데이터 클래스
# ========================================

@dataclass
class Signal:
    """시그널 데이터 클래스"""
    timestamp: datetime
    action: str  # BUY, SELL
    price: float
    score: Optional[float] = None
    confidence: Optional[float] = None
    market_state: Optional[str] = None
    reason: Optional[str] = None
    metadata: Optional[Dict] = None


@dataclass
class Trade:
    """거래 기록"""
    entry_time: datetime
    entry_price: float
    exit_time: datetime
    exit_price: float
    return_pct: float
    holding_hours: float
    exit_reason: str
    btc_amount: float
    entry_capital: float
    exit_capital: float
    profit: float
    fee_total: float


@dataclass
class Position:
    """현재 포지션"""
    entry_time: datetime
    entry_price: float
    btc_amount: float
    capital_at_entry: float
    entry_fee: float
    peak_price: float
    signal_score: Optional[float] = None
    signal_metadata: Optional[Dict] = None


# ========================================
# 보유 기간 상수
# ========================================

HOLDING_PERIODS = {
    # 초단타 (분-시간)
    '30min': 0.5,
    '1h': 1,
    '2h': 2,
    '3h': 3,
    '4h': 4,
    '6h': 6,
    '8h': 8,
    '12h': 12,

    # 단타 (시간-일)
    '18h': 18,
    '1d': 24,
    '1.5d': 36,
    '2d': 48,
    '3d': 72,
    '4d': 96,
    '5d': 120,
    '6d': 144,
    '7d': 168,

    # 중단타 (일)
    '10d': 240,
    '14d': 336,
    '21d': 504,
    '30d': 720,

    # 참고용 (중기)
    '60d': 1440,
    '90d': 2160
}


# ========================================
# UniversalEvaluationEngine 클래스
# ========================================

class UniversalEvaluationEngine:
    """
    범용 전략 평가 엔진

    특징:
    - 플러그인 시스템으로 청산/포지션 전략 확장 가능
    - 모든 연도 × 모든 보유 기간 조합 평가
    - 병렬 처리 지원
    """

    def __init__(
        self,
        initial_capital: float = 10_000_000,
        fee_rate: float = 0.0005,
        slippage: float = 0.0002
    ):
        """
        Args:
            initial_capital: 초기 자본 (기본 1천만원)
            fee_rate: 거래 수수료율 (0.05% Upbit)
            slippage: 슬리피지 (0.02%)
        """
        self.initial_capital = initial_capital
        self.fee_rate = fee_rate
        self.slippage = slippage
        self.total_fee = fee_rate + slippage  # 0.0007 (0.07%)

        # 플러그인 레지스트리
        self.exit_strategies = {}
        self.position_strategies = {}

        # 기본 플러그인 등록
        self._register_default_plugins()

        logger.info(f"UniversalEvaluationEngine initialized (capital={initial_capital:,})")

    def _register_default_plugins(self):
        """기본 플러그인 등록"""
        import sys
        sys.path.insert(0, str(Path(__file__).parent))

        from exit_strategy_plugins import (
            FixedExitPlugin,
            DynamicExitPlugin,
            TrailingStopPlugin,
            TimeoutExitPlugin,
            CompositeExitPlugin
        )
        from position_sizing_plugins import (
            FixedPositionPlugin,
            KellyPositionPlugin,
            ScoreBasedPositionPlugin,
            ConfidenceBasedPositionPlugin,
            TierBasedPositionPlugin
        )

        # Exit 전략 플러그인
        self.exit_strategies['fixed'] = FixedExitPlugin()
        self.exit_strategies['dynamic'] = DynamicExitPlugin()
        self.exit_strategies['trailing'] = TrailingStopPlugin()
        self.exit_strategies['timeout'] = TimeoutExitPlugin()
        self.exit_strategies['composite'] = CompositeExitPlugin(self.exit_strategies)

        # Position 크기 플러그인
        self.position_strategies['fixed'] = FixedPositionPlugin()
        self.position_strategies['kelly'] = KellyPositionPlugin()
        self.position_strategies['score_based'] = ScoreBasedPositionPlugin()
        self.position_strategies['confidence_based'] = ConfidenceBasedPositionPlugin()
        self.position_strategies['tier_based'] = TierBasedPositionPlugin()

    def register_exit_strategy(self, name: str, plugin):
        """새로운 청산 전략 플러그인 등록"""
        self.exit_strategies[name] = plugin
        logger.info(f"Registered exit strategy: {name}")

    def register_position_strategy(self, name: str, plugin):
        """새로운 포지션 크기 플러그인 등록"""
        self.position_strategies[name] = plugin
        logger.info(f"Registered position strategy: {name}")

    # ========================================
    # 시그널 로드
    # ========================================

    def load_signals(self, signal_file: Path) -> List[Signal]:
        """
        시그널 JSON 파일 로드

        Args:
            signal_file: signals/2024_signals.json

        Returns:
            Signal 객체 리스트
        """
        with open(signal_file, 'r', encoding='utf-8') as f:
            data = json.load(f)

        signals = []
        for sig in data['signals']:
            signals.append(Signal(
                timestamp=pd.to_datetime(sig['timestamp']),
                action=sig['action'],
                price=float(sig['price']),
                score=sig.get('score'),
                confidence=sig.get('confidence'),
                market_state=sig.get('market_state'),
                reason=sig.get('reason'),
                metadata=sig.get('metadata')
            ))

        logger.info(f"Loaded {len(signals)} signals from {signal_file.name}")
        return signals

    def load_price_data(self, year: int, timeframe: str) -> pd.DataFrame:
        """
        가격 데이터 로드 (DB)

        Args:
            year: 연도 (2020-2025)
            timeframe: minute5, minute60, day 등

        Returns:
            DataFrame (timestamp, open, high, low, close, volume)
        """
        db_path = Path('upbit_bitcoin.db')
        table_name = f'bitcoin_{timeframe}'

        conn = sqlite3.connect(db_path)

        query = f"""
            SELECT timestamp,
                   opening_price as open,
                   high_price as high,
                   low_price as low,
                   trade_price as close,
                   candle_acc_trade_volume as volume
            FROM {table_name}
            WHERE strftime('%Y', timestamp) = '{year}'
            ORDER BY timestamp ASC
        """

        df = pd.read_sql_query(query, conn)
        conn.close()

        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df = df.set_index('timestamp')

        logger.info(f"Loaded {len(df)} {timeframe} candles for {year}")
        return df

    # ========================================
    # 백테스팅 엔진
    # ========================================

    def backtest_single_combination(
        self,
        signals: List[Signal],
        price_data: pd.DataFrame,
        holding_period_hours: float,
        exit_config: Dict,
        position_config: Dict,
        year: int,
        period_name: str
    ) -> Dict[str, Any]:
        """
        단일 조합 백테스팅 (1개 연도 × 1개 보유 기간 × 1개 청산 방식)

        Args:
            signals: 시그널 리스트
            price_data: 가격 데이터
            holding_period_hours: 보유 기간 (시간)
            exit_config: 청산 설정
            position_config: 포지션 크기 설정
            year: 연도
            period_name: 보유 기간 이름 (예: "3d")

        Returns:
            백테스팅 결과 딕셔너리
        """
        # 초기화
        capital = self.initial_capital
        position: Optional[Position] = None
        trades: List[Trade] = []
        capital_history = [(price_data.index[0], capital)]
        peak_capital = capital
        max_drawdown = 0.0

        # Exit 전략 플러그인 선택
        exit_type = exit_config.get('type', 'fixed')
        exit_plugin = self.exit_strategies.get(exit_type)

        if not exit_plugin:
            raise ValueError(f"Unknown exit strategy: {exit_type}")

        # Position 크기 플러그인 선택
        position_type = position_config.get('type', 'fixed')
        position_plugin = self.position_strategies.get(position_type)

        if not position_plugin:
            raise ValueError(f"Unknown position strategy: {position_type}")

        # 시그널 처리
        signal_idx = 0

        for timestamp, bar in price_data.iterrows():
            # 포지션 없음 → 시그널 체크
            if position is None:
                # 다음 시그널 시간 체크
                while signal_idx < len(signals):
                    signal = signals[signal_idx]

                    if signal.timestamp > timestamp:
                        break  # 미래 시그널, 대기

                    if signal.timestamp <= timestamp:
                        # 진입
                        fraction = position_plugin.calculate_position_size(
                            signal=signal,
                            capital=capital,
                            config=position_config
                        )

                        entry_amount = capital * fraction
                        entry_fee = entry_amount * self.total_fee
                        btc_amount = (entry_amount - entry_fee) / signal.price

                        position = Position(
                            entry_time=signal.timestamp,
                            entry_price=signal.price,
                            btc_amount=btc_amount,
                            capital_at_entry=entry_amount,  # 수정: 투입 금액 저장
                            entry_fee=entry_fee,
                            peak_price=signal.price,
                            signal_score=signal.score,
                            signal_metadata=signal.metadata
                        )

                        capital -= entry_amount
                        signal_idx += 1
                        break

            # 포지션 있음 → 청산 조건 체크
            else:
                # Peak 업데이트
                if bar['high'] > position.peak_price:
                    position.peak_price = bar['high']

                # Timeout 체크
                holding_hours = (timestamp - position.entry_time).total_seconds() / 3600

                if holding_hours >= holding_period_hours:
                    # Timeout 청산
                    exit_price = bar['close']
                    exit_reason = 'TIMEOUT'

                else:
                    # Exit 플러그인으로 청산 조건 체크
                    exit_result = exit_plugin.check_exit(
                        position=position,
                        current_bar=bar,
                        timestamp=timestamp,
                        config=exit_config
                    )

                    if not exit_result['should_exit']:
                        continue  # 유지

                    exit_price = exit_result['exit_price']
                    exit_reason = exit_result['reason']

                # 청산 실행
                sell_amount = position.btc_amount * exit_price
                sell_fee = sell_amount * self.total_fee
                sell_revenue = sell_amount - sell_fee

                capital += sell_revenue

                return_pct = (sell_revenue - position.capital_at_entry) / position.capital_at_entry * 100
                holding_hours_actual = (timestamp - position.entry_time).total_seconds() / 3600

                trade = Trade(
                    entry_time=position.entry_time,
                    entry_price=position.entry_price,
                    exit_time=timestamp,
                    exit_price=exit_price,
                    return_pct=return_pct,
                    holding_hours=holding_hours_actual,
                    exit_reason=exit_reason,
                    btc_amount=position.btc_amount,
                    entry_capital=position.capital_at_entry,
                    exit_capital=sell_revenue,
                    profit=sell_revenue - position.capital_at_entry,
                    fee_total=position.entry_fee + sell_fee
                )

                trades.append(trade)
                position = None

                # Capital history
                capital_history.append((timestamp, capital))

                # Peak & Drawdown
                if capital > peak_capital:
                    peak_capital = capital
                else:
                    drawdown = (capital - peak_capital) / peak_capital * 100
                    if drawdown < max_drawdown:
                        max_drawdown = drawdown

        # 미청산 포지션 강제 청산
        if position is not None:
            last_bar = price_data.iloc[-1]
            last_timestamp = price_data.index[-1]

            sell_amount = position.btc_amount * last_bar['close']
            sell_fee = sell_amount * self.total_fee
            sell_revenue = sell_amount - sell_fee
            capital += sell_revenue

            return_pct = (sell_revenue - position.capital_at_entry) / position.capital_at_entry * 100
            holding_hours_actual = (last_timestamp - position.entry_time).total_seconds() / 3600

            trade = Trade(
                entry_time=position.entry_time,
                entry_price=position.entry_price,
                exit_time=last_timestamp,
                exit_price=last_bar['close'],
                return_pct=return_pct,
                holding_hours=holding_hours_actual,
                exit_reason='END_OF_PERIOD',
                btc_amount=position.btc_amount,
                entry_capital=position.capital_at_entry,
                exit_capital=sell_revenue,
                profit=sell_revenue - position.capital_at_entry,
                fee_total=position.entry_fee + sell_fee
            )

            trades.append(trade)

        # 통계 계산
        stats = self._calculate_statistics(
            trades=trades,
            initial_capital=self.initial_capital,
            final_capital=capital,
            max_drawdown=max_drawdown,
            year=year,
            period_name=period_name
        )

        return stats

    def _calculate_statistics(
        self,
        trades: List[Trade],
        initial_capital: float,
        final_capital: float,
        max_drawdown: float,
        year: int,
        period_name: str
    ) -> Dict[str, Any]:
        """통계 계산"""
        if len(trades) == 0:
            return {
                'year': year,
                'period': period_name,
                'total_return_pct': 0.0,
                'total_trades': 0,
                'winning_trades': 0,
                'losing_trades': 0,
                'win_rate': 0.0,
                'avg_return': 0.0,
                'avg_winning_return': 0.0,
                'avg_losing_return': 0.0,
                'sharpe_ratio': 0.0,
                'max_drawdown': 0.0,
                'final_capital': initial_capital,
                'total_profit': 0.0,
                'avg_holding_hours': 0.0
            }

        total_return_pct = (final_capital - initial_capital) / initial_capital * 100

        winning_trades = [t for t in trades if t.return_pct > 0]
        losing_trades = [t for t in trades if t.return_pct <= 0]

        win_rate = len(winning_trades) / len(trades) * 100 if trades else 0

        returns = [t.return_pct for t in trades]
        avg_return = np.mean(returns)
        avg_winning = np.mean([t.return_pct for t in winning_trades]) if winning_trades else 0
        avg_losing = np.mean([t.return_pct for t in losing_trades]) if losing_trades else 0

        # Sharpe Ratio
        if len(returns) > 1:
            sharpe = (np.mean(returns) - 0) / np.std(returns) if np.std(returns) > 0 else 0
        else:
            sharpe = 0

        avg_holding_hours = np.mean([t.holding_hours for t in trades])

        return {
            'year': year,
            'period': period_name,
            'total_return_pct': round(total_return_pct, 2),
            'total_trades': len(trades),
            'winning_trades': len(winning_trades),
            'losing_trades': len(losing_trades),
            'win_rate': round(win_rate, 2),
            'avg_return': round(avg_return, 2),
            'avg_winning_return': round(avg_winning, 2),
            'avg_losing_return': round(avg_losing, 2),
            'sharpe_ratio': round(sharpe, 2),
            'max_drawdown': round(max_drawdown, 2),
            'final_capital': int(final_capital),
            'total_profit': int(final_capital - initial_capital),
            'avg_holding_hours': round(avg_holding_hours, 1)
        }

    # ========================================
    # 전체 평가 (6년 × 23개 보유 기간)
    # ========================================

    def evaluate_all_combinations(
        self,
        signals_dir: Path,
        evaluation_config: Dict,
        parallel: bool = True
    ) -> Dict[str, Any]:
        """
        모든 연도 × 보유 기간 조합 평가

        Args:
            signals_dir: signals/ 디렉토리
            evaluation_config: 평가 설정
            parallel: 병렬 처리 여부

        Returns:
            전체 평가 결과
        """
        years = evaluation_config.get('years', [2020, 2021, 2022, 2023, 2024, 2025])
        training_years = evaluation_config.get('training_years', [2020, 2021, 2022, 2023, 2024])
        validation_year = evaluation_config.get('validation_year', 2025)

        holding_periods = evaluation_config.get('holding_periods', HOLDING_PERIODS)
        timeframe = evaluation_config['timeframe']

        logger.info(f"Starting evaluation: {len(years)} years × {len(holding_periods)} periods = {len(years) * len(holding_periods)} combinations")

        all_results = {}
        total_combinations = len(years) * len(holding_periods)
        completed = 0

        for year in years:
            # 시그널 로드
            signal_file = signals_dir / f'{year}_signals.json'
            if not signal_file.exists():
                logger.warning(f"Signal file not found: {signal_file}")
                continue

            signals = self.load_signals(signal_file)

            # 가격 데이터 로드
            price_data = self.load_price_data(year, timeframe)

            for period_name, hold_hours in holding_periods.items():
                completed += 1
                logger.info(f"[{completed}/{total_combinations}] {year} × {period_name}...")

                result = self.backtest_single_combination(
                    signals=signals,
                    price_data=price_data,
                    holding_period_hours=hold_hours,
                    exit_config=evaluation_config['exit_strategy'],
                    position_config=evaluation_config['position_sizing'],
                    year=year,
                    period_name=period_name
                )

                key = f"{year}_{period_name}"
                all_results[key] = result

        # 최적화 (training_years 기준)
        logger.info("Optimizing: finding best holding period...")
        best_period = self._find_best_period(all_results, training_years, holding_periods.keys())

        # 검증 (validation_year)
        logger.info(f"Validating: {validation_year} performance...")
        validation_result = all_results.get(f"{validation_year}_{best_period}")

        # Training 평균 계산
        training_avg = self._calculate_training_average(all_results, training_years, best_period)

        # 최종 리포트
        report = {
            'strategy': evaluation_config.get('strategy', 'unknown'),
            'evaluation_date': datetime.now().isoformat(),
            'evaluated_combinations': len(all_results),

            'full_matrix': all_results,

            'optimization': {
                'best_period': best_period,
                'training_years': training_years,
                'training_avg': training_avg,
                'selection_metric': 'sharpe_ratio'
            },

            'validation': {
                'year': validation_year,
                'period': best_period,
                'result': validation_result,
                'degradation_pct': self._calculate_degradation(training_avg, validation_result)
            },

            'recommendation': self._generate_recommendation(best_period, training_avg, validation_result)
        }

        logger.info(f"✅ Evaluation complete! Best period: {best_period}")
        return report

    def _find_best_period(
        self,
        all_results: Dict,
        training_years: List[int],
        period_names: List[str]
    ) -> str:
        """최적 보유 기간 찾기 (Sharpe 기준)"""
        period_scores = {}

        for period in period_names:
            sharpes = []
            for year in training_years:
                key = f"{year}_{period}"
                if key in all_results:
                    sharpes.append(all_results[key]['sharpe_ratio'])

            if sharpes:
                period_scores[period] = np.mean(sharpes)
            else:
                period_scores[period] = -999

        best_period = max(period_scores, key=period_scores.get)
        return best_period

    def _calculate_training_average(
        self,
        all_results: Dict,
        training_years: List[int],
        period: str
    ) -> Dict:
        """Training 기간 평균 성과"""
        sharpes = []
        returns = []
        trades = []

        for year in training_years:
            key = f"{year}_{period}"
            if key in all_results:
                sharpes.append(all_results[key]['sharpe_ratio'])
                returns.append(all_results[key]['total_return_pct'])
                trades.append(all_results[key]['total_trades'])

        return {
            'avg_sharpe': round(np.mean(sharpes), 2) if sharpes else 0,
            'avg_return_pct': round(np.mean(returns), 2) if returns else 0,
            'avg_trades': int(np.mean(trades)) if trades else 0
        }

    def _calculate_degradation(self, training_avg: Dict, validation_result: Dict) -> float:
        """성능 저하율 계산 (Sharpe 기준)"""
        if not training_avg or not validation_result:
            return 0.0

        train_sharpe = training_avg.get('avg_sharpe', 0)
        val_sharpe = validation_result.get('sharpe_ratio', 0)

        if train_sharpe == 0:
            return 0.0

        degradation = (val_sharpe - train_sharpe) / abs(train_sharpe) * 100
        return round(degradation, 1)

    def _generate_recommendation(
        self,
        best_period: str,
        training_avg: Dict,
        validation_result: Dict
    ) -> str:
        """추천 메시지 생성"""
        degradation = self._calculate_degradation(training_avg, validation_result)

        if abs(degradation) < 20:
            status = "✅ Good"
        elif abs(degradation) < 40:
            status = "⚠️  Caution"
        else:
            status = "❌ Overfitting"

        return f"Use {best_period} holding period. Validation degradation: {degradation:+.1f}% ({status})"


# ========================================
# 메인 실행
# ========================================

if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Universal Evaluation Engine')
    parser.add_argument('--signals', type=str, required=True, help='Signals directory (e.g., strategies/v46/signals/)')
    parser.add_argument('--config', type=str, required=True, help='Evaluation config JSON')
    parser.add_argument('--output', type=str, required=True, help='Output directory')

    args = parser.parse_args()

    # 설정 로드
    with open(args.config, 'r') as f:
        evaluation_config = json.load(f)

    # 엔진 생성
    engine = UniversalEvaluationEngine()

    # 평가 실행
    report = engine.evaluate_all_combinations(
        signals_dir=Path(args.signals),
        evaluation_config=evaluation_config
    )

    # 결과 저장
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    with open(output_dir / 'full_matrix.json', 'w') as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    logger.info(f"Report saved: {output_dir / 'full_matrix.json'}")
