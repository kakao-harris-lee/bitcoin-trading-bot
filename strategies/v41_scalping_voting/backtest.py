#!/usr/bin/env python3
"""
v41 Scalping Voting Backtest Engine
타임프레임별 백테스팅 실행
"""

import sys
sys.path.append('../..')

import json
import pandas as pd
import numpy as np
from typing import Dict, List
from datetime import datetime
import talib

from core import DataLoader
from voting_ensemble import VotingEnsemble


class ScalpingBacktester:
    """v41 스캘핑 투표 시스템 백테스터"""

    def __init__(self, timeframe: str, config: Dict, db_path: str = '../../upbit_bitcoin.db'):
        """
        Args:
            timeframe: 'minute1', 'minute5', 'minute15', 'minute60', 'minute240'
            config: v41 config.json 전체
            db_path: upbit_bitcoin.db 경로
        """
        self.timeframe = timeframe
        self.config = config
        self.db_path = db_path

        # 타임프레임별 설정
        self.tf_config = config['timeframes'][timeframe]
        self.entry_config = config['entry_conditions'][timeframe]
        self.exit_config = config['exit_conditions'][timeframe]
        self.position_config = config['position_sizing'][timeframe]
        self.risk_config = config['risk_management']['per_timeframe'][timeframe]

        # 백테스팅 설정
        bt_config = config['backtesting']
        self.initial_capital = bt_config['initial_capital'] * self.tf_config['capital_allocation']
        self.fee_rate = bt_config['fee_rate']
        self.slippage = bt_config['slippage']

        # VotingEnsemble 초기화
        print(f"\n[Backtest] VotingEnsemble 초기화 중...")
        self.ensemble = VotingEnsemble(timeframe, config, db_path)

        # 백테스팅 상태
        self.capital = self.initial_capital
        self.position = None  # {'entry_price', 'entry_time', 'size', 'votes', 'candles_held'}
        self.trades = []
        self.equity_curve = []

        # 리스크 관리
        self.daily_loss = 0.0
        self.last_trade_date = None
        self.consecutive_losses = 0

    def load_data(self, start_date: str, end_date: str) -> pd.DataFrame:
        """
        데이터 로드 및 지표 계산

        Args:
            start_date: YYYY-MM-DD
            end_date: YYYY-MM-DD

        Returns:
            DataFrame with OHLCV + indicators
        """
        print(f"\n[Backtest] {self.timeframe} 데이터 로드 중...")
        with DataLoader(self.db_path) as loader:
            df = loader.load_timeframe(self.timeframe, start_date=start_date, end_date=end_date)

        print(f"[Backtest] 로드 완료: {len(df)} 캔들")
        print(f"[Backtest] 지표 계산 중...")

        # 타임프레임별 지표 설정
        ind_config = self.config['indicators'][self.timeframe]

        # RSI
        df['rsi'] = talib.RSI(df['close'], timeperiod=ind_config['rsi_period'])

        # Volume SMA
        df['volume_sma'] = talib.SMA(df['volume'], timeperiod=ind_config['volume_sma'])

        # MACD
        macd, macd_signal, macd_hist = talib.MACD(
            df['close'],
            fastperiod=ind_config['macd_fast'],
            slowperiod=ind_config['macd_slow'],
            signalperiod=ind_config['macd_signal']
        )
        df['macd'] = macd
        df['macd_signal'] = macd_signal
        df['macd_hist'] = macd_hist

        # EMA
        df['ema_fast'] = talib.EMA(df['close'], timeperiod=ind_config['ema_fast'])
        df['ema_slow'] = talib.EMA(df['close'], timeperiod=ind_config['ema_slow'])
        if 'ema_mid' in ind_config:
            df['ema_mid'] = talib.EMA(df['close'], timeperiod=ind_config['ema_mid'])

        # Bollinger Bands
        bb_upper, bb_middle, bb_lower = talib.BBANDS(
            df['close'],
            timeperiod=ind_config['bb_period'],
            nbdevup=ind_config['bb_std'],
            nbdevdn=ind_config['bb_std']
        )
        df['bb_upper'] = bb_upper
        df['bb_middle'] = bb_middle
        df['bb_lower'] = bb_lower

        # ADX + DI (일부 타임프레임만)
        if 'adx_period' in ind_config:
            df['adx'] = talib.ADX(df['high'], df['low'], df['close'], timeperiod=ind_config['adx_period'])
            df['plus_di'] = talib.PLUS_DI(df['high'], df['low'], df['close'], timeperiod=ind_config['adx_period'])
            df['minus_di'] = talib.MINUS_DI(df['high'], df['low'], df['close'], timeperiod=ind_config['adx_period'])

        # MFI (일부 타임프레임만)
        if 'mfi_period' in ind_config:
            df['mfi'] = talib.MFI(
                df['high'], df['low'], df['close'], df['volume'],
                timeperiod=ind_config['mfi_period']
            )

        # NaN 제거
        df = df.dropna().reset_index(drop=True)
        print(f"[Backtest] 지표 계산 완료: {len(df)} 캔들 (NaN 제거 후)\n")

        return df

    def calculate_position_size(self, votes: int) -> float:
        """
        투표 수 기반 포지션 크기 계산

        Args:
            votes: 총 매수 투표 수 (4~7)

        Returns:
            포지션 비율 (0.0 ~ 1.0)
        """
        vote_mapping = self.position_config['vote_mapping']
        votes_str = str(votes)

        if votes_str in vote_mapping:
            return vote_mapping[votes_str]
        else:
            # 기본값
            return self.position_config['base_size']

    def check_entry(self, df: pd.DataFrame, idx: int) -> bool:
        """진입 가능 여부 확인 (리스크 관리)"""
        # 포지션 이미 있음
        if self.position is not None:
            return False

        # 일일 손실 한도 초과
        if self.daily_loss >= self.risk_config['max_daily_loss']:
            return False

        # 연속 손실 한도 초과
        global_risk = self.config['risk_management']['global']
        if self.consecutive_losses >= global_risk['consecutive_loss_limit']:
            return False

        return True

    def check_exit(self, df: pd.DataFrame, idx: int, signal: str) -> tuple:
        """
        청산 조건 확인

        Returns:
            (should_exit, exit_reason)
        """
        if self.position is None:
            return False, None

        current = df.iloc[idx]
        entry_price = self.position['entry_price']
        current_price = current['close']
        candles_held = self.position['candles_held']

        pnl_pct = (current_price - entry_price) / entry_price

        # 1. 투표 신호 매도
        if signal == 'sell':
            return True, 'voting_signal'

        # 2. 익절
        if pnl_pct >= self.exit_config['take_profit']:
            return True, 'take_profit'

        # 3. 손절
        if pnl_pct <= -self.exit_config['stop_loss']:
            return True, 'stop_loss'

        # 4. 타임스탑 (보유 캔들 수 초과)
        if candles_held >= self.exit_config['time_stop_candles']:
            return True, 'time_stop'

        # 5. 최대 보유 캔들 (일부 타임프레임만)
        if 'max_hold_candles' in self.exit_config:
            if candles_held >= self.exit_config['max_hold_candles']:
                return True, 'max_hold'

        # 6. Trailing Stop (일부 타임프레임만)
        if 'trailing_trigger' in self.exit_config and self.exit_config['trailing_stop'] is not None:
            if pnl_pct >= self.exit_config['trailing_trigger']:
                # 최고점 추적
                if 'max_pnl' not in self.position:
                    self.position['max_pnl'] = pnl_pct

                if pnl_pct > self.position['max_pnl']:
                    self.position['max_pnl'] = pnl_pct

                # Trailing stop 발동
                drawdown_from_peak = self.position['max_pnl'] - pnl_pct
                if drawdown_from_peak >= self.exit_config['trailing_stop']:
                    return True, 'trailing_stop'

        return False, None

    def execute_trade(self, df: pd.DataFrame, idx: int, action: str, reason: str, votes_detail: Dict = None):
        """거래 실행"""
        current = df.iloc[idx]
        timestamp = current['timestamp']
        price = current['close']

        if action == 'buy':
            # 포지션 진입
            total_votes = votes_detail['total_buy_votes']
            position_size = self.calculate_position_size(total_votes)

            # Turn-of-Candle 부스트 (minute15)
            if self.timeframe == 'minute15' and 'turn_of_candle_boost' in self.position_config:
                if votes_detail.get('turn_of_candle', False):
                    position_size *= self.position_config['turn_of_candle_boost']

            # 최대 1.0 제한
            position_size = min(position_size, 1.0)

            # 진입 금액
            entry_amount = self.capital * position_size

            # 수수료 + 슬리피지
            entry_cost = entry_amount * (1 + self.fee_rate + self.slippage)

            self.position = {
                'entry_price': price,
                'entry_time': timestamp,
                'size': position_size,
                'amount': entry_amount,
                'cost': entry_cost,
                'votes': total_votes,
                'candles_held': 0
            }

            print(f"  [BUY] {timestamp} @ ₩{price:,.0f} | Size: {position_size:.2%} | Votes: {total_votes}/7")

        elif action == 'sell':
            # 포지션 청산
            exit_amount = self.position['amount'] * (price / self.position['entry_price'])

            # 수수료 + 슬리피지
            exit_proceeds = exit_amount * (1 - self.fee_rate - self.slippage)

            # PnL 계산
            pnl_krw = exit_proceeds - self.position['cost']
            pnl_pct = pnl_krw / self.position['cost']

            # 자본 업데이트
            self.capital += pnl_krw

            # 거래 기록
            trade = {
                'entry_time': self.position['entry_time'],
                'exit_time': timestamp,
                'entry_price': self.position['entry_price'],
                'exit_price': price,
                'size': self.position['size'],
                'votes': self.position['votes'],
                'candles_held': self.position['candles_held'],
                'pnl_krw': pnl_krw,
                'pnl_pct': pnl_pct,
                'exit_reason': reason
            }
            self.trades.append(trade)

            # 일일 손실 추적
            current_date = pd.to_datetime(timestamp).date()
            if self.last_trade_date != current_date:
                self.daily_loss = 0.0
                self.last_trade_date = current_date

            if pnl_pct < 0:
                self.daily_loss += abs(pnl_pct)
                self.consecutive_losses += 1
            else:
                self.consecutive_losses = 0

            print(f"  [SELL] {timestamp} @ ₩{price:,.0f} | PnL: {pnl_pct:+.2%} | Reason: {reason}")

            # 포지션 초기화
            self.position = None

    def run(self, start_date: str, end_date: str) -> Dict:
        """
        백테스팅 실행

        Args:
            start_date: YYYY-MM-DD
            end_date: YYYY-MM-DD

        Returns:
            백테스팅 결과 딕셔너리
        """
        print(f"\n{'='*70}")
        print(f"v41 Scalping Voting Backtest - {self.timeframe}")
        print(f"{'='*70}")
        print(f"기간: {start_date} ~ {end_date}")
        print(f"초기 자본: ₩{self.initial_capital:,.0f} (전체의 {self.tf_config['capital_allocation']:.0%})")
        print(f"{'='*70}\n")

        # 데이터 로드
        df = self.load_data(start_date, end_date)

        # 백테스팅 루프
        print(f"[Backtest] 백테스팅 시작... ({len(df)} 캔들)\n")

        for i in range(len(df)):
            # 현재 포지션 상태
            position_state = 'long' if self.position is not None else 'none'

            # 투표 신호 얻기
            signal, votes_detail = self.ensemble.get_signal(df, i, position_state)

            # 포지션 보유 기간 업데이트
            if self.position is not None:
                self.position['candles_held'] += 1

            # 청산 체크 (우선)
            if position_state == 'long':
                should_exit, exit_reason = self.check_exit(df, i, signal)
                if should_exit:
                    self.execute_trade(df, i, 'sell', exit_reason)

            # 진입 체크
            elif signal == 'buy' and self.check_entry(df, i):
                self.execute_trade(df, i, 'buy', 'voting_signal', votes_detail)

            # Equity 기록 (매 캔들)
            current_equity = self.capital
            if self.position is not None:
                current_price = df.iloc[i]['close']
                unrealized_pnl = self.position['amount'] * (current_price / self.position['entry_price']) - self.position['cost']
                current_equity += unrealized_pnl

            self.equity_curve.append({
                'timestamp': df.iloc[i]['timestamp'],
                'equity': current_equity
            })

        # 결과 집계
        return self.calculate_metrics(df)

    def calculate_metrics(self, df: pd.DataFrame) -> Dict:
        """성과 지표 계산"""
        print(f"\n{'='*70}")
        print(f"백테스팅 완료")
        print(f"{'='*70}\n")

        # 기본 통계
        final_capital = self.capital
        total_return = (final_capital - self.initial_capital) / self.initial_capital
        num_trades = len(self.trades)

        # 거래 통계
        if num_trades > 0:
            wins = [t for t in self.trades if t['pnl_pct'] > 0]
            losses = [t for t in self.trades if t['pnl_pct'] <= 0]

            win_rate = len(wins) / num_trades if num_trades > 0 else 0
            avg_win = np.mean([t['pnl_pct'] for t in wins]) if wins else 0
            avg_loss = np.mean([t['pnl_pct'] for t in losses]) if losses else 0

            total_profit = sum([t['pnl_krw'] for t in wins]) if wins else 0
            total_loss = abs(sum([t['pnl_krw'] for t in losses])) if losses else 0
            profit_factor = total_profit / total_loss if total_loss > 0 else 0

            # Sharpe Ratio (일간 수익률 기준)
            equity_df = pd.DataFrame(self.equity_curve)
            equity_df['returns'] = equity_df['equity'].pct_change()
            daily_returns = equity_df['returns'].dropna()

            if len(daily_returns) > 0 and daily_returns.std() > 0:
                sharpe_ratio = (daily_returns.mean() / daily_returns.std()) * np.sqrt(252 * 24)  # 연환산
            else:
                sharpe_ratio = 0

            # Max Drawdown
            equity_series = equity_df['equity']
            cummax = equity_series.cummax()
            drawdown = (equity_series - cummax) / cummax
            max_drawdown = abs(drawdown.min())

        else:
            win_rate = 0
            avg_win = 0
            avg_loss = 0
            profit_factor = 0
            sharpe_ratio = 0
            max_drawdown = 0

        # 결과 출력
        print(f"=== 수익 성과 ===")
        print(f"초기 자본: ₩{self.initial_capital:,.0f}")
        print(f"최종 자본: ₩{final_capital:,.0f}")
        print(f"총 수익률: {total_return:+.2%}\n")

        print(f"=== 거래 통계 ===")
        print(f"총 거래: {num_trades}회")
        print(f"승률: {win_rate:.1%}")
        print(f"평균 수익: {avg_win:+.2%}")
        print(f"평균 손실: {avg_loss:+.2%}")
        print(f"Profit Factor: {profit_factor:.2f}\n")

        print(f"=== 리스크 지표 ===")
        print(f"Sharpe Ratio: {sharpe_ratio:.2f}")
        print(f"Max Drawdown: {max_drawdown:.2%}\n")

        # 목표 대비 평가
        target = self.config['target_performance'][self.timeframe]
        print(f"=== 목표 대비 평가 ===")
        print(f"수익률: {total_return:.2%} / 목표 {target['annual_return']:.2%} {'✅' if total_return >= target['annual_return'] else '❌'}")
        print(f"Sharpe: {sharpe_ratio:.2f} / 목표 {target['sharpe_ratio']:.2f} {'✅' if sharpe_ratio >= target['sharpe_ratio'] else '❌'}")
        print(f"MDD: {max_drawdown:.2%} / 목표 <{target['max_drawdown']:.2%} {'✅' if max_drawdown <= target['max_drawdown'] else '❌'}")
        print(f"승률: {win_rate:.1%} / 목표 {target['win_rate']:.1%} {'✅' if win_rate >= target['win_rate'] else '❌'}")

        return {
            'timeframe': self.timeframe,
            'initial_capital': self.initial_capital,
            'final_capital': final_capital,
            'total_return': total_return,
            'num_trades': num_trades,
            'win_rate': win_rate,
            'avg_win': avg_win,
            'avg_loss': avg_loss,
            'profit_factor': profit_factor,
            'sharpe_ratio': sharpe_ratio,
            'max_drawdown': max_drawdown,
            'trades': self.trades,
            'equity_curve': self.equity_curve
        }


if __name__ == "__main__":
    """단일 타임프레임 백테스트 실행"""

    # Config 로드
    with open('config.json') as f:
        config = json.load(f)

    # 타임프레임 선택 (인자로 받거나 기본값)
    import sys
    if len(sys.argv) > 1:
        timeframe = sys.argv[1]
    else:
        timeframe = 'minute15'  # 기본값

    # 백테스트 기간 (2024년 전체)
    start_date = '2024-01-01'
    end_date = '2024-12-31'

    # 백테스터 생성 및 실행
    backtester = ScalpingBacktester(timeframe, config)
    results = backtester.run(start_date, end_date)

    # 결과 저장
    output_file = f'results_{timeframe}.json'
    with open(output_file, 'w') as f:
        # equity_curve는 너무 커서 제외
        save_results = {k: v for k, v in results.items() if k != 'equity_curve'}
        json.dump(save_results, f, indent=2, default=str)

    print(f"\n결과 저장: {output_file}")
    print(f"{'='*70}\n")
