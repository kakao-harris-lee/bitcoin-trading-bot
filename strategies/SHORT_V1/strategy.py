#!/usr/bin/env python3
"""
SHORT_V1 - 숏 전략 메인 로직
EMA/ADX 추세 추종 기반 비트코인 선물 숏 전략
"""

import pandas as pd
import numpy as np
from typing import Dict, Optional, List
from dataclasses import dataclass, field
from datetime import datetime

from indicators import TechnicalIndicators, SignalGenerator


@dataclass
class Position:
    """포지션 정보"""
    entry_price: float
    entry_time: datetime
    size: float  # USDT 기준
    leverage: int
    stop_loss: float
    take_profit: float
    entry_reason: str
    # Trailing Stop 관련
    trailing_activated: bool = False
    highest_profit_pct: float = 0.0
    trailing_stop_price: float = 0.0


@dataclass
class Trade:
    """거래 기록"""
    entry_time: datetime
    exit_time: datetime
    entry_price: float
    exit_price: float
    size: float
    leverage: int
    pnl: float
    pnl_pct: float
    exit_reason: str
    funding_paid: float = 0.0


class ShortV1Strategy:
    """SHORT_V1 전략 클래스"""

    def __init__(self, config: Dict):
        """
        초기화

        Args:
            config: 전략 설정
        """
        self.config = config
        self.indicators = TechnicalIndicators(config)
        self.signal_gen = SignalGenerator(config)

        # 리스크 관리 설정
        risk_config = config.get('risk_management', {})
        self.max_leverage = risk_config.get('max_leverage', 3)
        self.position_risk_pct = risk_config.get('position_risk_pct', 1.0)
        self.max_drawdown_pct = risk_config.get('max_drawdown_pct', 20.0)

        # 청산 설정
        exit_config = config.get('exit', {})
        self.max_sl_pct = exit_config.get('max_stop_loss_pct', 5.0)
        self.rr_ratio = exit_config.get('risk_reward_ratio', 2.5)

        # Trailing Stop 설정
        ts_config = config.get('trailing_stop', {})
        self.trailing_enabled = ts_config.get('enabled', False)
        self.trailing_activation_pct = ts_config.get('activation_pct', 2.0)
        self.trailing_trail_pct = ts_config.get('trail_pct', 1.5)

        # 시장 필터 설정
        mf_config = config.get('market_filter', {})
        self.market_filter_enabled = mf_config.get('enabled', False)
        self.market_filter_ma_period = mf_config.get('ma_period', 100)
        self.market_filter_require_below = mf_config.get('require_below_ma', True)

        # 상태
        self.position: Optional[Position] = None
        self.trades: List[Trade] = []
        self.equity_curve: List[float] = []

    def prepare_data(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        데이터 전처리 및 지표 추가

        Args:
            df: OHLCV 데이터프레임

        Returns:
            지표가 추가된 데이터프레임
        """
        df = self.indicators.add_all_indicators(df)

        # 시장 필터용 MA 추가
        if self.market_filter_enabled:
            df['market_filter_ma'] = df['close'].rolling(
                window=self.market_filter_ma_period
            ).mean()

        return df

    def calculate_position_size(
        self,
        capital: float,
        entry_price: float,
        stop_loss: float,
        leverage: int
    ) -> float:
        """
        포지션 크기 계산 (리스크 기반)

        Args:
            capital: 현재 자본
            entry_price: 진입 가격
            stop_loss: 손절 가격
            leverage: 레버리지

        Returns:
            포지션 크기 (USDT)
        """
        # 리스크 금액 = 자본 × 리스크 비율
        risk_amount = capital * (self.position_risk_pct / 100)

        # 손절 비율
        sl_pct = abs(stop_loss - entry_price) / entry_price

        # 포지션 크기 = 리스크 금액 / 손절 비율 × 레버리지
        if sl_pct > 0:
            position_size = (risk_amount / sl_pct) * leverage
        else:
            position_size = capital * 0.5  # 기본값

        # 최대 포지션 = 자본 × 레버리지
        max_position = capital * leverage

        return min(position_size, max_position)

    def execute(self, df: pd.DataFrame, i: int, capital: float) -> Dict:
        """
        전략 실행 (단일 캔들)

        Args:
            df: 지표가 포함된 데이터프레임
            i: 현재 인덱스
            capital: 현재 자본

        Returns:
            {'action': 'open_short'/'close_short'/'hold', ...}
        """
        # 초기 워밍업 기간
        if i < 200:  # EMA 200 워밍업
            return {'action': 'hold', 'reason': 'WARMUP'}

        row = df.iloc[i]
        prev_row = df.iloc[i-1] if i > 0 else None

        # 포지션 있을 때: 청산 조건 확인
        if self.position is not None:
            current_price = row['close']

            # Trailing Stop 업데이트
            if self.trailing_enabled:
                trailing_result = self._update_trailing_stop(current_price)
                if trailing_result:
                    return trailing_result

            # 기존 청산 조건 확인 (Trailing Stop 가격 사용)
            effective_sl = self.position.trailing_stop_price if self.position.trailing_activated else self.position.stop_loss

            exit_signal = self.signal_gen.check_exit_signal(
                row=row,
                entry_price=self.position.entry_price,
                stop_loss_price=effective_sl,
                take_profit_price=self.position.take_profit
            )

            if exit_signal['signal']:
                exit_reason = exit_signal['reason']
                if self.position.trailing_activated and 'STOP_LOSS' in exit_reason:
                    exit_reason = f"TRAILING_STOP_{effective_sl:.2f}"
                return {
                    'action': 'close_short',
                    'reason': exit_reason,
                    'exit_type': exit_signal['type'],
                    'exit_price': exit_signal['exit_price']
                }

            return {'action': 'hold', 'reason': 'HOLDING_POSITION'}

        # 포지션 없을 때: 진입 조건 확인
        # 시장 필터 체크
        if self.market_filter_enabled:
            market_filter_ma = row.get('market_filter_ma', None)
            if market_filter_ma is not None and not np.isnan(market_filter_ma):
                if self.market_filter_require_below and row['close'] >= market_filter_ma:
                    return {'action': 'hold', 'reason': f'MARKET_FILTER_ABOVE_MA{self.market_filter_ma_period}'}

        entry_signal = self.signal_gen.check_entry_signal(row, prev_row)

        if entry_signal['signal']:
            # 스윙 하이 계산 (손절 기준)
            swing_high = self.indicators.get_swing_high(df.iloc[:i+1], lookback=10).iloc[-1]

            # 포지션 레벨 계산
            levels = self.signal_gen.calculate_position_levels(
                entry_price=row['close'],
                swing_high=swing_high,
                max_sl_pct=self.max_sl_pct,
                rr_ratio=self.rr_ratio
            )

            # 포지션 크기 계산
            position_size = self.calculate_position_size(
                capital=capital,
                entry_price=row['close'],
                stop_loss=levels['stop_loss'],
                leverage=self.max_leverage
            )

            return {
                'action': 'open_short',
                'reason': entry_signal['reason'],
                'strength': entry_signal['strength'],
                'entry_price': row['close'],
                'stop_loss': levels['stop_loss'],
                'take_profit': levels['take_profit'],
                'position_size': position_size,
                'risk_pct': levels['risk_pct'],
                'leverage': self.max_leverage
            }

        return {'action': 'hold', 'reason': entry_signal.get('reason', 'NO_SIGNAL')}

    def _update_trailing_stop(self, current_price: float) -> Optional[Dict]:
        """
        Trailing Stop 업데이트

        Args:
            current_price: 현재 가격

        Returns:
            청산 신호 또는 None
        """
        if self.position is None:
            return None

        # 숏 포지션의 수익률 계산 (가격 하락 시 수익)
        profit_pct = (self.position.entry_price - current_price) / self.position.entry_price * 100

        # Trailing Stop 활성화 체크
        if not self.position.trailing_activated:
            if profit_pct >= self.trailing_activation_pct:
                # Trailing Stop 활성화
                self.position.trailing_activated = True
                self.position.highest_profit_pct = profit_pct
                # 손익분기점 + 트레일 거리로 설정
                self.position.trailing_stop_price = self.position.entry_price * (1 - self.trailing_trail_pct / 100)
        else:
            # 이미 활성화된 경우: 최고 수익 갱신 시 Trailing Stop 조정
            if profit_pct > self.position.highest_profit_pct:
                self.position.highest_profit_pct = profit_pct
                # Trailing Stop을 현재 가격 + 트레일 거리로 조정
                self.position.trailing_stop_price = current_price * (1 + self.trailing_trail_pct / 100)

        return None

    def open_position(
        self,
        entry_price: float,
        entry_time: datetime,
        size: float,
        leverage: int,
        stop_loss: float,
        take_profit: float,
        reason: str
    ):
        """포지션 오픈"""
        self.position = Position(
            entry_price=entry_price,
            entry_time=entry_time,
            size=size,
            leverage=leverage,
            stop_loss=stop_loss,
            take_profit=take_profit,
            entry_reason=reason
        )

    def close_position(
        self,
        exit_price: float,
        exit_time: datetime,
        exit_reason: str,
        funding_paid: float = 0.0
    ) -> Trade:
        """포지션 청산 및 거래 기록 생성"""
        if self.position is None:
            raise ValueError("No position to close")

        # PnL 계산 (숏이므로 진입가 - 청산가)
        pnl_pct = (self.position.entry_price - exit_price) / self.position.entry_price * 100
        pnl_pct *= self.position.leverage  # 레버리지 적용
        pnl = self.position.size * (pnl_pct / 100)

        # 펀딩비 차감
        pnl -= funding_paid

        trade = Trade(
            entry_time=self.position.entry_time,
            exit_time=exit_time,
            entry_price=self.position.entry_price,
            exit_price=exit_price,
            size=self.position.size,
            leverage=self.position.leverage,
            pnl=pnl,
            pnl_pct=pnl_pct,
            exit_reason=exit_reason,
            funding_paid=funding_paid
        )

        self.trades.append(trade)
        self.position = None

        return trade

    def get_stats(self) -> Dict:
        """거래 통계 계산"""
        if not self.trades:
            return {'total_trades': 0}

        pnls = [t.pnl for t in self.trades]
        pnl_pcts = [t.pnl_pct for t in self.trades]

        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p < 0]

        total_pnl = sum(pnls)
        win_rate = len(wins) / len(pnls) * 100 if pnls else 0

        # Profit Factor
        gross_profit = sum(wins) if wins else 0
        gross_loss = abs(sum(losses)) if losses else 1
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0

        # 평균 승/패
        avg_win = np.mean(wins) if wins else 0
        avg_loss = np.mean(losses) if losses else 0

        # R:R 비율
        avg_win_pct = np.mean([t.pnl_pct for t in self.trades if t.pnl > 0]) if wins else 0
        avg_loss_pct = abs(np.mean([t.pnl_pct for t in self.trades if t.pnl < 0])) if losses else 1
        rr_ratio = avg_win_pct / avg_loss_pct if avg_loss_pct > 0 else 0

        # Expectancy (거래당 기대값)
        expectancy = (win_rate / 100 * avg_win_pct) - ((100 - win_rate) / 100 * avg_loss_pct)

        # Exit 유형별 통계
        sl_exits = [t for t in self.trades if t.exit_reason.startswith('STOP_LOSS')]
        trailing_exits = [t for t in self.trades if t.exit_reason.startswith('TRAILING_STOP')]
        tp_exits = [t for t in self.trades if t.exit_reason.startswith('TAKE_PROFIT')]
        reversal_exits = [t for t in self.trades if 'REVERSAL' in t.exit_reason]

        return {
            'total_trades': len(self.trades),
            'wins': len(wins),
            'losses': len(losses),
            'win_rate': win_rate,
            'total_pnl': total_pnl,
            'avg_pnl': np.mean(pnls),
            'avg_pnl_pct': np.mean(pnl_pcts),
            'avg_win': avg_win,
            'avg_loss': avg_loss,
            'profit_factor': profit_factor,
            'rr_ratio': rr_ratio,
            'expectancy': expectancy,
            'sl_exits': len(sl_exits),
            'trailing_exits': len(trailing_exits),
            'tp_exits': len(tp_exits),
            'reversal_exits': len(reversal_exits),
            'total_funding_paid': sum(t.funding_paid for t in self.trades)
        }


if __name__ == '__main__':
    import json
    from pathlib import Path

    # 설정 로드
    config_path = Path(__file__).parent / 'config.json'
    with open(config_path) as f:
        config = json.load(f)

    strategy = ShortV1Strategy(config)
    print(f"SHORT_V1 Strategy initialized")
    print(f"  - Max Leverage: {strategy.max_leverage}x")
    print(f"  - Position Risk: {strategy.position_risk_pct}%")
    print(f"  - Max SL: {strategy.max_sl_pct}%")
    print(f"  - R:R Ratio: {strategy.rr_ratio}")
