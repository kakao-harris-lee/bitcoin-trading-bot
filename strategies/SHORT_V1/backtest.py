#!/usr/bin/env python3
"""
SHORT_V1 - 백테스트 시뮬레이터
선물 거래 시뮬레이션 (레버리지, 수수료, 슬리피지, 펀딩비 반영)
"""

import json
import sys
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import pandas as pd
import numpy as np

# 로컬 모듈 import
sys.path.insert(0, str(Path(__file__).parent))
from strategy import ShortV1Strategy
from indicators import TechnicalIndicators


class FuturesBacktester:
    """선물 백테스트 엔진"""

    def __init__(self, config: Dict):
        """
        초기화

        Args:
            config: 전략 설정
        """
        self.config = config

        # 백테스트 설정
        bt_config = config.get('backtest', {})
        self.initial_capital = bt_config.get('initial_capital', 10000)
        self.fee_rate = bt_config.get('fee_rate', 0.0004)  # 0.04%
        self.slippage = bt_config.get('slippage', 0.0005)  # 0.05%
        self.funding_rate_avg = bt_config.get('funding_rate_avg', -0.0001)  # 8시간마다

        # 상태
        self.capital = self.initial_capital
        self.peak_capital = self.initial_capital
        self.equity_curve: List[Dict] = []
        self.trades: List[Dict] = []
        self.max_drawdown = 0

    def run(self, df: pd.DataFrame, verbose: bool = True) -> Dict:
        """
        백테스트 실행

        Args:
            df: OHLCV 데이터프레임
            verbose: 상세 출력 여부

        Returns:
            백테스트 결과 딕셔너리
        """
        strategy = ShortV1Strategy(self.config)

        # 지표 추가
        df = strategy.prepare_data(df)

        self.capital = self.initial_capital
        self.peak_capital = self.initial_capital
        self.equity_curve = []
        self.trades = []
        self.max_drawdown = 0

        # 펀딩비 누적 (포지션 보유 중)
        funding_accumulated = 0
        position_start_idx = None

        if verbose:
            print(f"\n{'='*70}")
            print(f"  SHORT_V1 백테스트 시작")
            print(f"  기간: {df.index.min()} ~ {df.index.max()}")
            print(f"  초기 자본: ${self.initial_capital:,.0f}")
            print(f"{'='*70}\n")

        for i in range(len(df)):
            row = df.iloc[i]
            timestamp = df.index[i]

            # 전략 실행
            signal = strategy.execute(df, i, self.capital)

            # 숏 포지션 오픈
            if signal['action'] == 'open_short':
                entry_price = signal['entry_price'] * (1 - self.slippage)  # 슬리피지
                fee = signal['position_size'] * self.fee_rate

                strategy.open_position(
                    entry_price=entry_price,
                    entry_time=timestamp,
                    size=signal['position_size'],
                    leverage=signal['leverage'],
                    stop_loss=signal['stop_loss'],
                    take_profit=signal['take_profit'],
                    reason=signal['reason']
                )

                self.capital -= fee  # 진입 수수료
                position_start_idx = i
                funding_accumulated = 0

                if verbose:
                    print(f"[{timestamp}] SHORT OPEN @ ${entry_price:,.2f}")
                    print(f"    Size: ${signal['position_size']:,.0f}, Lev: {signal['leverage']}x")
                    print(f"    SL: ${signal['stop_loss']:,.2f}, TP: ${signal['take_profit']:,.2f}")
                    print(f"    Reason: {signal['reason']}")

            # 숏 포지션 청산
            elif signal['action'] == 'close_short' and strategy.position is not None:
                exit_price = signal['exit_price'] * (1 + self.slippage)  # 슬리피지
                fee = strategy.position.size * self.fee_rate

                # 펀딩비 계산 (보유 기간 동안)
                if position_start_idx is not None and 'funding_rate' in df.columns:
                    funding_candles = df.iloc[position_start_idx:i+1]
                    funding_accumulated = funding_candles['funding_rate'].sum() * strategy.position.size

                trade = strategy.close_position(
                    exit_price=exit_price,
                    exit_time=timestamp,
                    exit_reason=signal['reason'],
                    funding_paid=funding_accumulated
                )

                self.capital += trade.pnl - fee  # PnL - 청산 수수료

                self.trades.append({
                    'entry_time': trade.entry_time,
                    'exit_time': trade.exit_time,
                    'entry_price': trade.entry_price,
                    'exit_price': trade.exit_price,
                    'size': trade.size,
                    'leverage': trade.leverage,
                    'pnl': trade.pnl,
                    'pnl_pct': trade.pnl_pct,
                    'exit_reason': trade.exit_reason,
                    'funding_paid': trade.funding_paid
                })

                if verbose:
                    pnl_emoji = "✅" if trade.pnl > 0 else "❌"
                    print(f"[{timestamp}] SHORT CLOSE @ ${exit_price:,.2f} {pnl_emoji}")
                    print(f"    PnL: ${trade.pnl:,.2f} ({trade.pnl_pct:+.2f}%)")
                    print(f"    Reason: {signal['reason']}")
                    print(f"    Capital: ${self.capital:,.0f}")

                position_start_idx = None

            # Equity 기록
            unrealized_pnl = 0
            if strategy.position is not None:
                # 미실현 손익 계산
                current_price = row['close']
                pnl_pct = (strategy.position.entry_price - current_price) / strategy.position.entry_price
                pnl_pct *= strategy.position.leverage
                unrealized_pnl = strategy.position.size * pnl_pct

            equity = self.capital + unrealized_pnl
            self.equity_curve.append({
                'timestamp': timestamp,
                'equity': equity,
                'capital': self.capital,
                'unrealized_pnl': unrealized_pnl
            })

            # Max Drawdown 업데이트
            if equity > self.peak_capital:
                self.peak_capital = equity
            drawdown = (self.peak_capital - equity) / self.peak_capital * 100
            if drawdown > self.max_drawdown:
                self.max_drawdown = drawdown

        # 마지막 포지션 강제 청산
        if strategy.position is not None:
            last_row = df.iloc[-1]
            trade = strategy.close_position(
                exit_price=last_row['close'],
                exit_time=df.index[-1],
                exit_reason='BACKTEST_END',
                funding_paid=0
            )
            self.capital += trade.pnl

            if verbose:
                print(f"\n[백테스트 종료] 포지션 강제 청산")
                print(f"    PnL: ${trade.pnl:,.2f} ({trade.pnl_pct:+.2f}%)")

        return self._calculate_metrics(df, strategy)

    def _calculate_metrics(self, df: pd.DataFrame, strategy: ShortV1Strategy) -> Dict:
        """성과 지표 계산"""
        final_capital = self.capital
        total_return = (final_capital - self.initial_capital) / self.initial_capital * 100

        # Buy&Hold (숏 전략이므로 비교용)
        start_price = df.iloc[200]['close']  # 워밍업 이후 시작
        end_price = df.iloc[-1]['close']
        buy_hold_return = (end_price - start_price) / start_price * 100

        # Equity curve
        equity_series = pd.Series([e['equity'] for e in self.equity_curve])
        returns = equity_series.pct_change().dropna()

        # Sharpe Ratio (4시간봉 기준)
        periods_per_year = 365 * 6  # 4시간봉 → 1년에 약 2190개
        sharpe = returns.mean() / returns.std() * np.sqrt(periods_per_year) if returns.std() > 0 else 0

        # 거래 통계
        stats = strategy.get_stats()

        # CAGR 계산
        days = (df.index[-1] - df.index[200]).days
        years = days / 365
        cagr = ((final_capital / self.initial_capital) ** (1 / years) - 1) * 100 if years > 0 else 0

        return {
            'initial_capital': self.initial_capital,
            'final_capital': final_capital,
            'total_return': total_return,
            'cagr': cagr,
            'buy_hold_return': buy_hold_return,
            'excess_return': -buy_hold_return - total_return,  # 숏 전략은 BH 하락이 유리
            'sharpe_ratio': sharpe,
            'max_drawdown': self.max_drawdown,
            **stats,
            'trades': self.trades,
            'equity_curve': self.equity_curve
        }


def run_backtest(
    data_path: Optional[str] = None,
    start_date: str = '2022-01-01',
    end_date: str = '2024-12-31',
    verbose: bool = True
) -> Dict:
    """
    백테스트 실행 편의 함수

    Args:
        data_path: 데이터 파일 경로 (없으면 데이터 수집)
        start_date: 시작일
        end_date: 종료일
        verbose: 상세 출력

    Returns:
        백테스트 결과
    """
    # 설정 로드
    config_path = Path(__file__).parent / 'config.json'
    with open(config_path) as f:
        config = json.load(f)

    # 데이터 로드 또는 수집
    if data_path and Path(data_path).exists():
        df = pd.read_csv(data_path, index_col=0, parse_dates=True)
        print(f"데이터 로드: {data_path}")
    else:
        # 데이터 수집
        from data_collector import collect_all_data
        df = collect_all_data(start_date, end_date, timeframe='4h')

    # 백테스트 실행
    backtester = FuturesBacktester(config)
    results = backtester.run(df, verbose=verbose)

    return results


def print_results(results: Dict):
    """결과 출력"""
    print(f"\n{'='*70}")
    print(f"  SHORT_V1 백테스트 결과")
    print(f"{'='*70}")

    print(f"\n📊 수익 성과:")
    print(f"  초기 자본: ${results['initial_capital']:,.0f}")
    print(f"  최종 자본: ${results['final_capital']:,.0f}")
    print(f"  총 수익률: {results['total_return']:+.2f}%")
    print(f"  CAGR: {results['cagr']:+.2f}%")
    print(f"  Buy&Hold: {results['buy_hold_return']:+.2f}%")

    print(f"\n📈 리스크 지표:")
    print(f"  Sharpe Ratio: {results['sharpe_ratio']:.2f}")
    print(f"  Max Drawdown: {results['max_drawdown']:.2f}%")
    print(f"  Profit Factor: {results.get('profit_factor', 0):.2f}")

    print(f"\n🎯 거래 통계:")
    print(f"  총 거래: {results['total_trades']}회")
    print(f"  승률: {results.get('win_rate', 0):.1f}%")
    print(f"  평균 PnL: {results.get('avg_pnl_pct', 0):+.2f}%")
    print(f"  R:R Ratio: {results.get('rr_ratio', 0):.2f}")
    print(f"  Expectancy: {results.get('expectancy', 0):.2f}")

    print(f"\n🔧 청산 유형:")
    print(f"  Stop Loss: {results.get('sl_exits', 0)}회")
    print(f"  Take Profit: {results.get('tp_exits', 0)}회")
    print(f"  Reversal: {results.get('reversal_exits', 0)}회")

    print(f"\n💰 비용:")
    print(f"  펀딩비 합계: ${results.get('total_funding_paid', 0):,.2f}")

    # KPI 달성 여부
    print(f"\n{'='*70}")
    print(f"  KPI 달성 여부")
    print(f"{'='*70}")

    kpi_checks = [
        ('Profit Factor >= 1.5', results.get('profit_factor', 0) >= 1.5),
        ('Expectancy >= 0.2', results.get('expectancy', 0) >= 0.2),
        ('Sharpe Ratio >= 1.0', results['sharpe_ratio'] >= 1.0),
        ('MDD <= 20%', results['max_drawdown'] <= 20),
        ('R:R Ratio >= 2.0', results.get('rr_ratio', 0) >= 2.0),
    ]

    for kpi_name, achieved in kpi_checks:
        status = "✅" if achieved else "❌"
        print(f"  {status} {kpi_name}")

    achieved_count = sum(1 for _, achieved in kpi_checks if achieved)
    print(f"\n  달성: {achieved_count}/{len(kpi_checks)}")


def save_results(results: Dict, output_path: str):
    """결과 저장"""
    # 거래 리스트에서 datetime 객체 변환
    trades_serializable = []
    for trade in results.get('trades', []):
        trade_copy = trade.copy()
        trade_copy['entry_time'] = str(trade_copy['entry_time'])
        trade_copy['exit_time'] = str(trade_copy['exit_time'])
        trades_serializable.append(trade_copy)

    # Equity curve 변환
    equity_serializable = []
    for eq in results.get('equity_curve', []):
        eq_copy = eq.copy()
        eq_copy['timestamp'] = str(eq_copy['timestamp'])
        equity_serializable.append(eq_copy)

    output = {
        'summary': {k: v for k, v in results.items() if k not in ['trades', 'equity_curve']},
        'trades': trades_serializable,
        'equity_curve': equity_serializable
    }

    with open(output_path, 'w') as f:
        json.dump(output, f, indent=2)

    print(f"\n결과 저장: {output_path}")


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='SHORT_V1 백테스트')
    parser.add_argument('--data', type=str, help='데이터 파일 경로')
    parser.add_argument('--start', type=str, default='2022-01-01', help='시작일')
    parser.add_argument('--end', type=str, default='2024-12-31', help='종료일')
    parser.add_argument('--quiet', action='store_true', help='상세 출력 비활성화')
    parser.add_argument('--save', type=str, help='결과 저장 경로')

    args = parser.parse_args()

    # 백테스트 실행
    results = run_backtest(
        data_path=args.data,
        start_date=args.start,
        end_date=args.end,
        verbose=not args.quiet
    )

    # 결과 출력
    print_results(results)

    # 결과 저장
    if args.save:
        save_results(results, args.save)
    else:
        # 기본 저장 경로
        output_path = Path(__file__).parent / 'results' / f'backtest_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json'
        save_results(results, str(output_path))
