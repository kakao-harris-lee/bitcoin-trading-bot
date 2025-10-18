#!/usr/bin/env python3
"""
strategy.py
v02c 전략: v02b + 변동성 조정

개선점:
- 동적 Kelly (최소 15%)
- 분할 매도
- 변동성 기반 Kelly 조정 (ATR)
"""

import sys
sys.path.append('../..')

from adaptive_threshold import AdaptiveThreshold
from market_classifier import MarketClassifier
from ml_model import MLSignalValidator
from core.kelly_calculator import KellyCalculator


class VolatilityAdjustedStrategy:
    """v02c: Dynamic Kelly + Split Exit + Volatility Adjustment"""

    def __init__(self, config: dict, ml_model: MLSignalValidator):
        self.config = config
        
        # 시장 분류기
        self.market_classifier = MarketClassifier(
            window=config['rolling_window'],
            adx_period=config['adx_period'],
            adx_threshold=config['adx_threshold']
        )
        
        # 적응형 임계값 계산기
        self.adaptive_threshold = AdaptiveThreshold(
            window=config['rolling_window'],
            base_oversold=config['adaptive_rsi']['base_oversold'],
            base_overbought=config['adaptive_rsi']['base_overbought'],
            adjustment_range=config['adaptive_rsi']['adjustment_range'],
            volatility_threshold_high=config['volatility_threshold']['high'],
            volatility_threshold_low=config['volatility_threshold']['low']
        )
        
        # ML 검증기
        self.ml_validator = ml_model
        
        # Kelly 설정
        self.kelly_settings = config['kelly_settings']
        self.current_kelly = self.kelly_settings['initial_fraction']
        
        # 거래 기록 (Kelly 계산용)
        self.trade_history = []  # {'profit_loss_pct': float}
        
        # 상태 추적
        self.position = None
        self.entry_price = 0.0
        self.entry_timestamp = None

    def generate_signal(self, df, i: int) -> dict:
        """신호 생성"""
        if i < self.config['rolling_window']:
            return {'action': 'hold', 'fraction': 0.0, 'reason': 'insufficient_data'}
        
        # 1. 시장 상태 분류
        market = self.market_classifier.classify(df, i)
        
        # 2. 적응형 RSI 임계값
        thresholds = self.adaptive_threshold.calculate_thresholds(df, i)
        
        # 3. 현재 RSI
        rsi = df.iloc[i]['rsi']
        
        # 4. 신호 생성
        raw_signal = None
        reason = ""
        
        # 매수 신호
        if rsi < thresholds['oversold']:
            raw_signal = 'buy'
            reason = f"RSI({rsi:.1f}) < {thresholds['oversold']:.1f}"
        
        # 매도 신호
        elif rsi > thresholds['overbought']:
            raw_signal = 'sell'
            reason = f"RSI({rsi:.1f}) > {thresholds['overbought']:.1f}"
        
        # 보유 중 손익 체크 (분할 매도)
        elif self.position == 'long':
            current_price = df.iloc[i]['close']
            pnl_ratio = (current_price - self.entry_price) / self.entry_price

            # 익절 3단계 (20%)
            if pnl_ratio >= self.config['risk_management']['take_profit_3']:
                raw_signal = 'sell'
                sell_fraction = self.config['split_exit']['tp3_fraction']
                reason = f"take_profit_3 ({pnl_ratio:.2%}) - sell {sell_fraction*100:.0f}%"
                return {'action': 'sell', 'fraction': sell_fraction, 'reason': reason}

            # 익절 2단계 (10%)
            elif pnl_ratio >= self.config['risk_management']['take_profit_2']:
                raw_signal = 'sell'
                sell_fraction = self.config['split_exit']['tp2_fraction']
                reason = f"take_profit_2 ({pnl_ratio:.2%}) - sell {sell_fraction*100:.0f}%"
                return {'action': 'sell', 'fraction': sell_fraction, 'reason': reason}

            # 익절 1단계 (5%)
            elif pnl_ratio >= self.config['risk_management']['take_profit_1']:
                raw_signal = 'sell'
                sell_fraction = self.config['split_exit']['tp1_fraction']
                reason = f"take_profit_1 ({pnl_ratio:.2%}) - sell {sell_fraction*100:.0f}%"
                return {'action': 'sell', 'fraction': sell_fraction, 'reason': reason}

            # 손절 (-3%)
            elif pnl_ratio <= self.config['risk_management']['stop_loss']:
                raw_signal = 'sell'
                sell_fraction = self.config['split_exit']['sl_fraction']
                reason = f"stop_loss ({pnl_ratio:.2%}) - sell {sell_fraction*100:.0f}%"
                return {'action': 'sell', 'fraction': sell_fraction, 'reason': reason}
        
        # 5. ML 검증
        if raw_signal in ['buy', 'sell']:
            ml_result = self.ml_validator.predict(df, i)
            if not ml_result['approved']:
                return {'action': 'hold', 'fraction': 0.0, 
                        'reason': f"ML rejected: {raw_signal}"}
            reason += f" [ML: {ml_result['confidence']:.2%}]"
        
        # 6. 최종 신호 (변동성 조정 Kelly)
        if raw_signal == 'buy' and self.position is None:
            # ATR 기반 변동성 조정
            adjusted_kelly = self._adjust_kelly_for_volatility(df, i)

            return {
                'action': 'buy',
                'fraction': adjusted_kelly,
                'reason': reason + f" [Kelly: {adjusted_kelly:.2%}]"
            }
        
        elif raw_signal == 'sell' and self.position == 'long':
            # 매도 시 거래 기록 저장 (다음 캔들에서 계산)
            return {'action': 'sell', 'fraction': 1.0, 'reason': reason}
        
        return {'action': 'hold', 'fraction': 0.0, 'reason': 'no_signal'}

    def on_buy(self, timestamp, price: float):
        """매수 체결"""
        self.position = 'long'
        self.entry_price = price
        self.entry_timestamp = timestamp

    def on_sell(self, timestamp, price: float):
        """매도 체결"""
        if self.entry_price > 0:
            # 수익률 계산
            pnl_pct = ((price - self.entry_price) / self.entry_price) * 100
            self.trade_history.append({'profit_loss_pct': pnl_pct})
            
            # Kelly 재계산 (50회 이후)
            if len(self.trade_history) >= self.kelly_settings['min_trades_for_dynamic']:
                self._update_kelly()
        
        self.position = None
        self.entry_price = 0.0
        self.entry_timestamp = None

    def _update_kelly(self):
        """Kelly Criterion 동적 업데이트"""
        kelly_full, stats = KellyCalculator.from_trades(self.trade_history)

        # Quarter Kelly 적용
        kelly_quarter = kelly_full * self.kelly_settings['kelly_multiplier']

        # 최대/최소 제한 (최소 15%로 상향)
        min_frac = self.kelly_settings.get('min_fraction', 0.15)
        kelly_quarter = max(min_frac, min(kelly_quarter, self.kelly_settings['max_fraction']))

        self.current_kelly = kelly_quarter

    def _adjust_kelly_for_volatility(self, df, idx: int) -> float:
        """변동성 기반 Kelly 조정"""
        if 'atr' not in df.columns:
            return self.current_kelly

        close = df.iloc[idx]['close']
        atr = df.iloc[idx]['atr']
        atr_ratio = atr / close if close > 0 else 0

        kelly = self.current_kelly
        vol_adj = self.config.get('volatility_adjustment', {})

        # 높은 변동성: Kelly 감소
        if atr_ratio > self.config['volatility_threshold']['high']:
            kelly *= vol_adj.get('high_vol_multiplier', 0.8)

        # 낮은 변동성: Kelly 증가
        elif atr_ratio < self.config['volatility_threshold']['low']:
            kelly *= vol_adj.get('low_vol_multiplier', 1.1)

        # 최종 제한
        min_frac = self.kelly_settings.get('min_fraction', 0.15)
        kelly = max(min_frac, min(kelly, self.kelly_settings['max_fraction']))

        return kelly

    def get_kelly_history(self) -> list:
        """Kelly 변화 이력"""
        history = []
        for i in range(0, len(self.trade_history), 10):
            if i >= self.kelly_settings['min_trades_for_dynamic']:
                kelly, stats = KellyCalculator.from_trades(self.trade_history[:i])
                history.append({
                    'trade_count': i,
                    'kelly_full': kelly,
                    'kelly_quarter': kelly * 0.25,
                    'win_rate': stats['win_rate']
                })
        return history


def v02c_strategy_wrapper(df, i, params):
    """Backtester 호환 래퍼"""
    strategy = params['strategy_instance']
    signal = strategy.generate_signal(df, i)

    timestamp = df.iloc[i]['timestamp']
    price = df.iloc[i]['close']

    if signal['action'] == 'buy':
        strategy.on_buy(timestamp, price)
    elif signal['action'] == 'sell':
        strategy.on_sell(timestamp, price)

    return signal
