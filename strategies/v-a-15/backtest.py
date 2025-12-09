#!/usr/bin/env python3
"""
v-a-15 Enhanced Backtesting
ATR Dynamic Exit + Strategy-Specific Logic
"""

import sys
from pathlib import Path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

import pandas as pd
import json
import numpy as np
import importlib.util
from core.data_loader import DataLoader
from core.market_analyzer import MarketAnalyzer

va15_dir = Path(__file__).parent

# ATR Exit Manager
spec = importlib.util.spec_from_file_location("atr", va15_dir / "core" / "atr_exit_manager.py")
atr_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(atr_module)
ATRExitManager = atr_module.ATRExitManager

# Market Classifier
spec = importlib.util.spec_from_file_location("mc", va15_dir / "core" / "market_classifier.py")
mc_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mc_module)
MarketClassifierV37 = mc_module.MarketClassifierV37


class EnhancedBacktester:
    """ATR 기반 동적 청산 + 전략별 로직"""

    def __init__(self, config: dict, initial_capital=10_000_000, fee_rate=0.0005):
        self.config = config
        self.initial_capital = initial_capital
        self.fee_rate = fee_rate

        # ATR Exit Manager
        self.atr_manager = ATRExitManager(config.get('atr_exit', {}))

        # Market Classifier
        self.classifier = MarketClassifierV37()

        self.reset()

    def reset(self):
        self.cash = self.initial_capital
        self.btc = 0
        self.trades = []
        self.position = None
        self.atr_manager.reset()

    def backtest(self, df: pd.DataFrame, signals_df: pd.DataFrame):
        """
        메인 백테스팅 루프

        개선사항:
        1. ATR 기반 동적 TP/SL
        2. Trailing Stop
        3. 시장 상태 변화 청산
        4. 전략별 청산 로직
        """
        self.reset()

        for i, row in df.iterrows():
            current_price = row['close']

            # 매수 시그널 확인
            if self.position is None:
                signal = signals_df[signals_df['timestamp'] == row['timestamp']]
                if len(signal) > 0:
                    signal_row = signal.iloc[0]

                    # 진입
                    fraction = signal_row['fraction']
                    buy_amount = self.cash * fraction
                    fee = buy_amount * self.fee_rate
                    btc_bought = (buy_amount - fee) / current_price

                    if btc_bought > 0:
                        self.btc += btc_bought
                        self.cash -= buy_amount

                        # 포지션 정보
                        self.position = {
                            'entry_price': current_price,
                            'entry_time': row['timestamp'],
                            'entry_index': i,
                            'strategy': signal_row['strategy'],
                            'market_state': signal_row.get('market_state', ''),
                            'confidence': signal_row.get('confidence', 0),
                            'entry_atr': row.get('atr', current_price * 0.02),  # 기본 2%
                            'entry_macd': row.get('macd', 0),
                            'entry_macd_signal': row.get('macd_signal', 0),
                            'entry_adx': row.get('adx', 20),
                            'entry_rsi': row.get('rsi', 50)
                        }

                        # ATR Exit Manager 설정
                        self.atr_manager.set_entry(
                            entry_price=current_price,
                            entry_atr=self.position['entry_atr'],
                            market_state=self.position['market_state']
                        )

            # 청산 조건 확인
            elif self.position:
                # 현재 시장 상태
                prev_row = df.iloc[i-1] if i > 0 else None
                df_recent = df.iloc[max(0, i-60):i+1]
                current_market_state = self.classifier.classify_market_state(row, prev_row, df_recent)

                # Trailing Stop 업데이트
                self.atr_manager.update_trailing_stop(current_price)

                # 청산 시그널 확인
                should_exit = False
                exit_reason = ''

                # 1. ATR 기반 청산
                atr_exit = self.atr_manager.check_exit(current_price, current_market_state)
                if atr_exit:
                    should_exit = True
                    exit_reason = atr_exit['reason']

                # 2. 전략별 청산 로직
                if not should_exit:
                    strategy_exit = self._check_strategy_exit(row, df, i)
                    if strategy_exit:
                        should_exit = True
                        exit_reason = strategy_exit['reason']

                # 3. 최대 보유 기간
                if not should_exit:
                    hold_days = (row['timestamp'] - self.position['entry_time']).days
                    max_hold = self._get_max_hold_days()
                    if hold_days >= max_hold:
                        should_exit = True
                        exit_reason = f'MAX_HOLD_{max_hold}D'

                # 청산 실행
                if should_exit:
                    sell_amount = self.btc * current_price
                    fee = sell_amount * self.fee_rate
                    self.cash += (sell_amount - fee)

                    profit_pct = (current_price - self.position['entry_price']) / self.position['entry_price']
                    profit = sell_amount - (self.position['entry_price'] * self.btc)

                    hold_days = (row['timestamp'] - self.position['entry_time']).days

                    self.trades.append({
                        'entry_time': self.position['entry_time'],
                        'exit_time': row['timestamp'],
                        'entry_price': self.position['entry_price'],
                        'exit_price': current_price,
                        'profit': profit,
                        'profit_pct': profit_pct * 100,
                        'strategy': self.position['strategy'],
                        'exit_reason': exit_reason,
                        'hold_days': hold_days,
                        'entry_market_state': self.position['market_state'],
                        'exit_market_state': current_market_state,
                        'confidence': self.position['confidence']
                    })

                    self.btc = 0
                    self.position = None
                    self.atr_manager.reset()

        # 미청산 포지션 강제 청산
        if self.position and self.btc > 0:
            final_price = df.iloc[-1]['close']
            sell_amount = self.btc * final_price
            fee = sell_amount * self.fee_rate
            self.cash += (sell_amount - fee)

            profit_pct = (final_price - self.position['entry_price']) / self.position['entry_price']
            profit = sell_amount - (self.position['entry_price'] * self.btc)
            hold_days = (df.iloc[-1]['timestamp'] - self.position['entry_time']).days

            self.trades.append({
                'entry_time': self.position['entry_time'],
                'exit_time': df.iloc[-1]['timestamp'],
                'entry_price': self.position['entry_price'],
                'exit_price': final_price,
                'profit': profit,
                'profit_pct': profit_pct * 100,
                'strategy': self.position['strategy'],
                'exit_reason': 'FORCED_END',
                'hold_days': hold_days,
                'entry_market_state': self.position['market_state'],
                'exit_market_state': '',
                'confidence': self.position['confidence']
            })

        # 최종 평가
        final_value = self.cash
        total_return = (final_value - self.initial_capital) / self.initial_capital * 100

        return self._generate_report(final_value, total_return)

    def _check_strategy_exit(self, row, df, current_idx):
        """전략별 청산 로직"""
        strategy = self.position['strategy']

        # Trend Enhanced: MACD Dead Cross
        if strategy == 'trend_enhanced':
            macd = row.get('macd', 0)
            macd_signal = row.get('macd_signal', 0)

            # MACD가 Signal 아래로 떨어지면 청산
            if macd < macd_signal:
                return {'reason': 'MACD_DEAD_CROSS'}

        # SIDEWAYS (stoch, rsi_bb): RSI 과매수
        elif strategy in ['stoch', 'rsi_bb']:
            rsi = row.get('rsi', 50)
            rsi_overbought = self.config.get('sideways_hybrid', {}).get('rsi_bb_overbought', 70)

            if rsi >= rsi_overbought:
                return {'reason': 'RSI_OVERBOUGHT'}

        return None

    def _get_max_hold_days(self):
        """전략별 최대 보유 기간"""
        strategy = self.position['strategy']

        if strategy == 'trend_enhanced':
            return self.config.get('trend_following_enhanced', {}).get('max_hold_days', 90)
        else:
            return self.config.get('sideways_hybrid', {}).get('max_hold_days', 20)

    def _generate_report(self, final_value, total_return):
        """상세 리포트 생성"""
        if not self.trades:
            return {
                'final_value': final_value,
                'total_return': total_return,
                'total_trades': 0,
                'winning_trades': 0,
                'win_rate': 0,
                'trades': []
            }

        winning = [t for t in self.trades if t['profit'] > 0]
        losing = [t for t in self.trades if t['profit'] <= 0]

        avg_win = np.mean([t['profit_pct'] for t in winning]) if winning else 0
        avg_loss = np.mean([t['profit_pct'] for t in losing]) if losing else 0

        return {
            'final_value': final_value,
            'total_return': total_return,
            'total_trades': len(self.trades),
            'winning_trades': len(winning),
            'losing_trades': len(losing),
            'win_rate': len(winning) / len(self.trades) * 100,
            'avg_win': avg_win,
            'avg_loss': avg_loss,
            'avg_hold_days': np.mean([t['hold_days'] for t in self.trades]),
            'max_win': max([t['profit_pct'] for t in self.trades]),
            'max_loss': min([t['profit_pct'] for t in self.trades]),
            'trades': self.trades
        }


def main():
    print("="*70)
    print("  v-a-15 Enhanced Backtesting (2024)")
    print("  ATR Dynamic Exit + Strategy Logic")
    print("="*70)

    # Config 로드
    config_path = Path(__file__).parent / 'config.json'
    with open(config_path, 'r') as f:
        config = json.load(f)

    # 데이터 로드
    db_path = Path(__file__).parent.parent.parent / 'upbit_bitcoin.db'

    with DataLoader(str(db_path)) as loader:
        df = loader.load_timeframe('day', '2024-01-01', '2024-12-31')

    if df is None:
        print("❌ 데이터 로드 실패")
        return

    # 지표 추가 (MACD, ADX, RSI 필요)
    df = MarketAnalyzer.add_indicators(df, ['rsi', 'macd', 'adx', 'atr', 'bb', 'stoch'])

    print(f"데이터: {len(df)}개 캔들")

    # 시그널 로드
    signals_file = Path(__file__).parent / 'signals' / 'day_2024_signals.json'

    if not signals_file.exists():
        print(f"\n❌ 시그널 파일 없음. 먼저 실행:")
        print(f"  python strategies/v-a-15/generate_signals.py")
        return

    with open(signals_file, 'r') as f:
        signals_data = json.load(f)

    signals_list = signals_data.get('signals', [])
    signals_df = pd.DataFrame(signals_list)

    if len(signals_df) > 0:
        signals_df['timestamp'] = pd.to_datetime(signals_df['timestamp'])

    print(f"시그널: {len(signals_df)}개")

    if len(signals_df) == 0:
        print("❌ 시그널 없음, 백테스트 중단")
        return

    # Enhanced Backtester
    backtester = EnhancedBacktester(config)
    result = backtester.backtest(df, signals_df)

    # 결과 출력
    print(f"\n{'='*70}")
    print(f"  백테스트 결과 (Enhanced)")
    print(f"{'='*70}")
    print(f"  최종 자본: {result['final_value']:,.0f} KRW")
    print(f"  총 수익률: {result['total_return']:+.2f}%")
    print(f"  총 거래: {result['total_trades']}회")
    print(f"  승리: {result['winning_trades']}회")
    print(f"  패배: {result['losing_trades']}회")
    print(f"  승률: {result['win_rate']:.1f}%")

    if result['total_trades'] > 0:
        print(f"\n{'='*70}")
        print(f"  거래 통계")
        print(f"{'='*70}")
        print(f"  평균 승리: {result['avg_win']:+.2f}%")
        print(f"  평균 손실: {result['avg_loss']:+.2f}%")
        print(f"  최대 승리: {result['max_win']:+.2f}%")
        print(f"  최대 손실: {result['max_loss']:+.2f}%")
        print(f"  평균 보유: {result['avg_hold_days']:.1f}일")

        # 청산 사유 분석
        exit_reasons = {}
        for t in result['trades']:
            reason = t['exit_reason']
            exit_reasons[reason] = exit_reasons.get(reason, 0) + 1

        print(f"\n{'='*70}")
        print(f"  청산 사유")
        print(f"{'='*70}")
        for reason, count in sorted(exit_reasons.items(), key=lambda x: -x[1]):
            print(f"  {reason}: {count}회")

        # 전략별 성과
        trend_trades = [t for t in result['trades'] if t['strategy'] == 'trend_enhanced']
        stoch_trades = [t for t in result['trades'] if t['strategy'] == 'stoch']

        print(f"\n{'='*70}")
        print(f"  전략별 성과")
        print(f"{'='*70}")

        if trend_trades:
            trend_wins = len([t for t in trend_trades if t['profit'] > 0])
            trend_win_rate = trend_wins / len(trend_trades) * 100
            trend_avg = np.mean([t['profit_pct'] for t in trend_trades])
            print(f"  Trend Enhanced: {len(trend_trades)}회 (승률 {trend_win_rate:.1f}%, 평균 {trend_avg:+.2f}%)")

        if stoch_trades:
            stoch_wins = len([t for t in stoch_trades if t['profit'] > 0])
            stoch_win_rate = stoch_wins / len(stoch_trades) * 100
            stoch_avg = np.mean([t['profit_pct'] for t in stoch_trades])
            print(f"  SIDEWAYS Stoch: {len(stoch_trades)}회 (승률 {stoch_win_rate:.1f}%, 평균 {stoch_avg:+.2f}%)")

    # 목표 달성 확인
    print(f"\n{'='*70}")
    print(f"  목표 달성 확인")
    print(f"{'='*70}")
    target_return = config.get('target_performance', {}).get('annual_return_2025', 0.43) * 100
    achieved = result['total_return'] >= target_return
    print(f"  2024 목표: >= +{target_return:.1f}% {'✅ 달성' if achieved else '❌ 미달성'}")
    print(f"  실제 수익률: {result['total_return']:+.2f}%")

    if not achieved:
        gap = target_return - result['total_return']
        print(f"  부족분: {gap:.2f}%p")

    # 결과 저장
    results_dir = Path(__file__).parent / 'results'
    results_dir.mkdir(exist_ok=True)

    result_file = results_dir / 'backtest_2024_enhanced.json'

    # Convert timestamps
    for t in result['trades']:
        if hasattr(t['entry_time'], 'isoformat'):
            t['entry_time'] = t['entry_time'].isoformat()
        if hasattr(t['exit_time'], 'isoformat'):
            t['exit_time'] = t['exit_time'].isoformat()

    with open(result_file, 'w') as f:
        json.dump(result, f, indent=2)

    print(f"\n  ✅ 결과 저장: {result_file}")

    # 비교 (이전 결과가 있으면)
    old_result_file = results_dir / 'backtest_2024.json'
    if old_result_file.exists():
        with open(old_result_file, 'r') as f:
            old_result = json.load(f)

        print(f"\n{'='*70}")
        print(f"  성능 비교 (Simple vs Enhanced)")
        print(f"{'='*70}")
        print(f"  수익률: {old_result['total_return']:+.2f}% → {result['total_return']:+.2f}% ({result['total_return'] - old_result['total_return']:+.2f}%p)")
        print(f"  승률: {old_result['win_rate']:.1f}% → {result['win_rate']:.1f}% ({result['win_rate'] - old_result['win_rate']:+.1f}%p)")

if __name__ == '__main__':
    main()
