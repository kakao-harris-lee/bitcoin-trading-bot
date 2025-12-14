#!/usr/bin/env python3
"""
Dual Exchange Paper Trading Engine
Upbit(v35 or SideWays_v2) + Binance(SHORT_V1) Paper Trading
"""

import sys
import os
import json
from pathlib import Path
from typing import Any, Dict, Optional
from datetime import datetime, timedelta
import time

# 프로젝트 루트 추가
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from paper_trading_engine import PaperTradingAccount
from telegram_notifier import TelegramNotifier
from core.data_loader import DataLoader

from live_trading.regime_router import RegimeRouter, RegimeDecision


def _load_candidate_from_json(path: str, index: int = 0) -> Dict[str, Any]:
    p = Path(path)
    with p.open("r", encoding="utf-8") as f:
        data = json.load(f)

    if isinstance(data, dict) and "candidate" in data:
        return dict(data["candidate"])

    results = data.get("results") if isinstance(data, dict) else None
    if not isinstance(results, list) or not results:
        raise ValueError(f"Invalid candidate JSON format: {path}")

    idx = int(index)
    if idx < 0:
        idx = len(results) + idx
    idx = max(0, min(len(results) - 1, idx))

    entry = results[idx]
    if not isinstance(entry, dict) or "candidate" not in entry:
        raise ValueError(f"Invalid results[{idx}] format in {path}")
    return dict(entry["candidate"])


class DualPaperTradingEngine:
    """듀얼 거래소 Paper Trading 엔진"""

    def __init__(
        self,
        upbit_capital: float = 10_000_000,  # 10M KRW
        binance_capital: float = 10_000,    # 10K USDT
        telegram_enabled: bool = True,
        candidate_json: Optional[str] = None,
        candidate_index: int = 0,
    ):
        """
        Args:
            upbit_capital: Upbit 초기 자본 (KRW)
            binance_capital: Binance 초기 자본 (USDT)
            telegram_enabled: 텔레그램 알림 활성화
        """
        print("=" * 70)
        print("  Dual Exchange Paper Trading Engine")
        print("=" * 70)
        print(f"  Upbit Capital: {upbit_capital:,.0f} KRW")
        print(f"  Binance Capital: {binance_capital:,.2f} USDT")
        print("=" * 70)

        # Paper Trading 계좌
        self.upbit_account = PaperTradingAccount(upbit_capital, 'upbit')
        self.binance_account = PaperTradingAccount(binance_capital, 'binance')

        # Candidate (tuned operational config)
        self._candidate: Optional[Dict[str, Any]] = None
        self.v35_fraction_mult = 1.0
        self.sideways_fraction_mult = 1.0
        self.binance_fraction_mult = 1.0
        self.bull_hold_fraction = 1.0
        self.sideways_v2_strategy_config: Dict[str, Any] = {}

        if candidate_json:
            self._candidate = _load_candidate_from_json(candidate_json, candidate_index)
            self._apply_candidate(self._candidate)

        # 전략 로드
        self.v35_strategy = self._load_v35_strategy()
        self.short_v1_strategy = self._load_short_v1_strategy()
        self.sideways_v2_strategy = self._init_sideways_v2_strategy(strategy_config=self.sideways_v2_strategy_config)

        # 운영형 라우팅 (레짐 기반)
        self.router = self._build_router()
        self._last_regime_decision: Optional[RegimeDecision] = None
        self._last_regime_check_at: Optional[datetime] = None

        # 텔레그램
        self.telegram = TelegramNotifier() if telegram_enabled else None

        # 상태
        self.upbit_position = False
        self.binance_position = False
        self.upbit_active_strategy: Optional[str] = None
        self.binance_active_strategy: Optional[str] = None
        self.last_upbit_signal = None
        self.last_binance_signal = None
        self.iteration_count = 0  # 반복 횟수

        print("✅ 초기화 완료\n")

        # 시작 알림 전송
        self._send_startup_notification(upbit_capital, binance_capital)

    def _send_startup_notification(self, upbit_capital: float, binance_capital: float):
        """시작 알림 전송"""
        if not self.telegram:
            return

        msg = "🚀 Dual Exchange Paper Trading 시작\n"
        msg += "=" * 30 + "\n\n"
        msg += "📊 전략 구성:\n"
        msg += f"  • Upbit: v35 ↔ SideWays_v2 (레짐 라우팅)\n"
        msg += f"  • Binance: SHORT_V1 (BEAR 레짐에서만)\n\n"
        msg += "💰 초기 자본:\n"
        msg += f"  • Upbit: {upbit_capital:,.0f} KRW\n"
        msg += f"  • Binance: ${binance_capital:,.2f} USDT\n\n"
        msg += f"✅ V35 전략: {'로드 성공' if self.v35_strategy else '❌ 로드 실패'}\n"
        msg += f"✅ SHORT_V1 전략: {'로드 성공' if self.short_v1_strategy else '❌ 로드 실패'}\n\n"
        msg += f"✅ SideWays_v2 전략: {'로드 성공' if self.sideways_v2_strategy else '❌ 로드 실패'}\n\n"
        msg += "⏰ 신호 체크: 60분마다 (레짐은 day 기반)"

        if self._candidate:
            msg += "\n\n🧪 Candidate 적용됨: router/policy/mults"

        try:
            self.telegram.send_message(msg)
        except Exception as e:
            print(f"⚠️  시작 알림 전송 실패: {e}")

    def _apply_candidate(self, candidate: Dict[str, Any]) -> None:
        self.v35_fraction_mult = float(candidate.get("v35_fraction_mult", 1.0))
        self.sideways_fraction_mult = float(candidate.get("sideways_fraction_mult", 1.0))
        self.binance_fraction_mult = float(candidate.get("binance_fraction_mult", 1.0))
        self.bull_hold_fraction = float(candidate.get("bull_hold_fraction", 1.0))
        self.sideways_v2_strategy_config = dict(candidate.get("sideways_v2_config") or {})

    def _build_router(self) -> RegimeRouter:
        if not self._candidate:
            return RegimeRouter(lookback_days=180)

        cand = self._candidate
        rcfg = dict(cand.get("router_config") or {})
        return RegimeRouter(
            lookback_days=int(rcfg.get("lookback_days", 180)),
            mfi_period=int(rcfg.get("mfi_period", 14)),
            adx_period=int(rcfg.get("adx_period", 14)),
            mfi_bull=float(rcfg.get("mfi_bull", 52.0)),
            mfi_bear=float(rcfg.get("mfi_bear", 48.0)),
            adx_strong=float(rcfg.get("adx_strong", 25.0)),
            adx_trend=float(rcfg.get("adx_trend", 20.0)),
            adx_weak=float(rcfg.get("adx_weak", 15.0)),
            bull_policy=str(cand.get("bull_policy", "v35")),
            sideways_policy=str(cand.get("sideways_policy", "sideways_v2")),
            sideways_bear_policy=cand.get("sideways_bear_policy"),
            bear_moderate_policy=cand.get("bear_moderate_policy"),
            bear_strong_policy=cand.get("bear_strong_policy"),
            binance_gate_mode=str(cand.get("binance_gate_mode", "bear_only")),
        )

    def _send_status_notification(self, prices: Dict[str, float]):
        """주기적 상태 알림 (6시간마다)"""
        if not self.telegram:
            return

        # 6시간마다 (6회 반복마다)
        if self.iteration_count % 6 != 0:
            return

        upbit_cash, upbit_btc = self.upbit_account.get_balance()
        upbit_total = upbit_cash + (upbit_btc * prices['upbit'])
        upbit_stats = self.upbit_account.get_statistics()

        binance_cash, _ = self.binance_account.get_balance()
        binance_position = self.binance_account.get_position()
        binance_stats = self.binance_account.get_statistics()

        msg = "📊 Dual Paper Trading 상태 보고\n"
        msg += "=" * 30 + "\n\n"
        msg += f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"

        msg += "📈 [Upbit]\n"
        msg += f"  포지션: {'🟢 있음' if self.upbit_position else '⚪ 없음'}\n"
        msg += f"  총 가치: {upbit_total:,.0f}원\n"
        msg += f"  수익률: {upbit_stats['return_pct']:+.2f}%\n\n"

        msg += "📉 [Binance]\n"
        msg += f"  포지션: {'🔻 숏' if self.binance_position else '⚪ 없음'}\n"
        if binance_position:
            msg += f"  진입가: ${binance_position['entry_price']:,.2f}\n"
        msg += f"  현금: ${binance_cash:,.2f}\n"
        msg += f"  수익률: {binance_stats['return_pct']:+.2f}%\n\n"

        # 합계
        total_krw = upbit_total + (binance_cash * 1300)
        initial_total = self.upbit_account.initial_capital + (self.binance_account.initial_capital * 1300)
        total_return_pct = ((total_krw - initial_total) / initial_total) * 100

        msg += f"💰 총 자산: {total_krw:,.0f}원\n"
        msg += f"📊 총 수익률: {total_return_pct:+.2f}%"

        try:
            self.telegram.send_message(msg)
        except Exception as e:
            print(f"⚠️  상태 알림 전송 실패: {e}")

    def _load_v35_strategy(self):
        """v35 전략 로드"""
        try:
            import importlib.util
            import json

            # 절대 경로로 모듈 로드
            strategy_path = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                                         'strategies/v35_optimized/strategy.py')
            spec = importlib.util.spec_from_file_location("v35_strategy", strategy_path)
            v35_module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(v35_module)

            config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                                       'strategies/v35_optimized/config_optimized.json')
            with open(config_path, 'r') as f:
                config = json.load(f)

            strategy = v35_module.V35OptimizedStrategy(config)
            print("✅ V35 전략 로드 완료")
            return strategy

        except Exception as e:
            print(f"❌ V35 전략 로드 실패: {e}")
            import traceback
            traceback.print_exc()
            return None

    def _load_short_v1_strategy(self):
        """SHORT_V1 전략 로드"""
        try:
            import importlib.util
            import json

            # 절대 경로로 모듈 로드
            strategy_path = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                                         'strategies/SHORT_V1/strategy.py')
            spec = importlib.util.spec_from_file_location("short_v1_strategy", strategy_path)
            short_module = importlib.util.module_from_spec(spec)

            # SHORT_V1 indicators 모듈도 로드해야 함
            indicators_path = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                                           'strategies/SHORT_V1/indicators.py')
            ind_spec = importlib.util.spec_from_file_location("indicators", indicators_path)
            ind_module = importlib.util.module_from_spec(ind_spec)
            sys.modules['indicators'] = ind_module
            ind_spec.loader.exec_module(ind_module)

            spec.loader.exec_module(short_module)

            config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                                       'strategies/SHORT_V1/config_optimized.json')
            with open(config_path, 'r') as f:
                config = json.load(f)

            strategy = short_module.ShortV1Strategy(config)
            print("✅ SHORT_V1 전략 로드 완료")
            return strategy

        except Exception as e:
            print(f"❌ SHORT_V1 전략 로드 실패: {e}")
            import traceback
            traceback.print_exc()
            return None

    def _init_sideways_v2_strategy(self, strategy_config: Optional[Dict[str, Any]] = None):
        """Trading Engine V2 SideWays_v2 전략 인스턴스 생성 (paper/live에서 직접 사용)."""
        try:
            from trading_engine_v2.modules.sideways_v2_strategy import SideWaysV2Strategy

            strategy = SideWaysV2Strategy(config=None, strategy_config=(strategy_config or None))
            print("✅ SideWays_v2 전략 초기화 완료")
            return strategy
        except Exception as e:
            print(f"⚠️  SideWays_v2 전략 초기화 실패: {e}")
            return None

    def get_current_prices(self) -> Dict[str, float]:
        """현재 가격 조회 (실제 시장 데이터)"""
        try:
            import pyupbit
            import requests

            # Upbit BTC/KRW
            upbit_price = pyupbit.get_current_price("KRW-BTC")

            # Binance BTC/USDT
            binance_url = "https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT"
            response = requests.get(binance_url)
            binance_price = float(response.json()['price'])

            return {
                'upbit': upbit_price,
                'binance': binance_price
            }

        except Exception as e:
            print(f"⚠️  가격 조회 실패: {e}")
            return {'upbit': 100_000_000, 'binance': 100_000}  # 임시값

    def _maybe_update_regime_decision(self) -> Optional[RegimeDecision]:
        """레짐 결정을 갱신 (day 캔들 기반)."""
        now = datetime.now()
        if self._last_regime_check_at and (now - self._last_regime_check_at) < timedelta(minutes=55):
            return self._last_regime_decision

        try:
            df_day = self.router.get_recent_daily_df(end_dt=now)
            decision = self.router.recommend(df_day)
            self._last_regime_check_at = now
            self._last_regime_decision = decision
            return decision
        except Exception as e:
            print(f"⚠️  레짐 판단 실패: {e}")
            return self._last_regime_decision

    def execute_upbit_strategy(self, current_price: float, strategy_name: Optional[str], decision: Optional[RegimeDecision] = None):
        """Upbit 전략 실행 (v35 또는 SideWays_v2)."""
        if not strategy_name:
            if self.upbit_position:
                strategy_name = self.upbit_active_strategy or "v35"
            else:
                print("⚪ [Upbit] 레짐상 진입 스킵")
                return

        # Special: bull_hold
        if strategy_name == "bull_hold":
            if not self.upbit_position:
                cash, _ = self.upbit_account.get_balance()
                frac = max(0.0, min(1.0, float(self.bull_hold_fraction)))
                buy_amount = cash * frac
                if buy_amount >= 5000:
                    result = self.upbit_account.buy(buy_amount, current_price)
                    if result.get("success"):
                        self.upbit_position = True
                        self.upbit_active_strategy = "bull_hold"
                        msg = f"🟢 [Upbit Paper] BULL_HOLD 매수\n━━━━━━━━━━━━━━━━━━━━\n💰 가격: {current_price:,.0f}원\n📊 수량: {result['executed_volume']:.8f} BTC\n📝 사유: BULL_HOLD_ENTRY"
                        print(msg)
                        if self.telegram:
                            self.telegram.send_message(msg)
                else:
                    print("⚪ [Upbit:bull_hold] 최소 주문 미달 - 진입 스킵")
            else:
                # exit when leaving BULL
                if decision is not None and decision.regime != "BULL":
                    cash, btc = self.upbit_account.get_balance()
                    if btc > 0:
                        result = self.upbit_account.sell(btc, current_price)
                        if result.get("success"):
                            self.upbit_position = False
                            self.upbit_active_strategy = None
                            msg = f"🔴 [Upbit Paper] BULL_HOLD 청산\n━━━━━━━━━━━━━━━━━━━━\n💰 가격: {current_price:,.0f}원\n📊 수량: {result['executed_volume']:.8f} BTC\n💵 손익: {result['pnl']:+,.0f}원\n📝 사유: BULL_HOLD_EXIT_{decision.regime}"
                            print(msg)
                            if self.telegram:
                                self.telegram.send_message(msg)
                else:
                    if self.iteration_count == 1:
                        print("⚪ [Upbit:bull_hold] 보유 유지")
            return

        if strategy_name == "sideways_v2" and not self.sideways_v2_strategy:
            print("⚠️  SideWays_v2 전략 미로드 - Upbit 거래 스킵")
            return

        if strategy_name == "v35" and not self.v35_strategy:
            print("⚠️  V35 전략 미로드 - Upbit 거래 스킵")
            return

        try:
            if strategy_name == "v35":
                with DataLoader() as loader:
                    df = loader.load_timeframe('day', start_date='2024-01-01')
                signal = self.v35_strategy.execute(df, len(df) - 1)
            elif strategy_name == "sideways_v2":
                with DataLoader() as loader:
                    df = loader.load_timeframe('minute240', start_date='2024-01-01')
                df = df.tail(500).reset_index(drop=True)
                df = self.sideways_v2_strategy.add_indicators(df)
                signal = self.sideways_v2_strategy.generate_signal(df, len(df) - 1) or {
                    "action": "hold",
                    "reason": "SIDEWAYS_V2_NO_SIGNAL",
                }
            else:
                print(f"⚠️  알 수 없는 Upbit 전략: {strategy_name}")
                return

            # 신호 로그 출력
            print(f"[Upbit:{strategy_name}] 신호: {signal['action']} | 사유: {signal.get('reason', 'N/A')}")

            # Apply multipliers (mirror backtest scaling behavior)
            if signal.get("action") in {"buy", "sell"}:
                base_fraction = float(signal.get("fraction", 1.0))
                mult = 1.0
                if strategy_name == "v35":
                    mult = self.v35_fraction_mult
                elif strategy_name == "sideways_v2":
                    mult = self.sideways_fraction_mult
                signal["fraction"] = max(0.0, min(1.0, base_fraction * float(mult)))

            if signal['action'] == 'buy' and not self.upbit_position:
                # 매수
                cash, btc = self.upbit_account.get_balance()
                buy_amount = cash * float(signal.get('fraction', 0.5))

                if buy_amount >= 5000:
                    result = self.upbit_account.buy(buy_amount, current_price)

                    if result['success']:
                        self.upbit_position = True
                        self.upbit_active_strategy = strategy_name
                        self.last_upbit_signal = signal

                        msg = f"🟢 [Upbit Paper] 매수\n"
                        msg += f"━━━━━━━━━━━━━━━━━━━━\n"
                        msg += f"💰 가격: {current_price:,.0f}원\n"
                        msg += f"📊 수량: {result['executed_volume']:.8f} BTC\n"
                        msg += f"📝 사유: {signal.get('reason', 'N/A')}"

                        print(msg)
                        if self.telegram:
                            self.telegram.send_message(msg)
                    else:
                        if strategy_name == "sideways_v2" and self.sideways_v2_strategy:
                            self.sideways_v2_strategy.clear_position()
                            self.sideways_v2_strategy.hold_bars = 0
                            self.sideways_v2_strategy.entry_method = None
                            self.sideways_v2_strategy.partial_exits = 0
                else:
                    if strategy_name == "sideways_v2" and self.sideways_v2_strategy:
                        # 전략은 진입 처리했는데 주문을 못 넣으면 상태 복구
                        self.sideways_v2_strategy.clear_position()
                        self.sideways_v2_strategy.hold_bars = 0
                        self.sideways_v2_strategy.entry_method = None
                        self.sideways_v2_strategy.partial_exits = 0

            elif signal['action'] == 'sell' and self.upbit_position:
                # 매도
                cash, btc = self.upbit_account.get_balance()

                if btc > 0:
                    frac = float(signal.get("fraction", 1.0))
                    frac = max(0.0, min(1.0, frac))
                    sell_btc = btc if frac >= 1.0 else btc * frac

                    if sell_btc * current_price < 5000:
                        return

                    result = self.upbit_account.sell(sell_btc, current_price)

                    if result['success']:
                        # determine remaining position
                        _, btc_after = self.upbit_account.get_balance()
                        fully_exited = (btc_after <= 1e-12) or (frac >= 1.0)
                        self.upbit_position = not fully_exited
                        if fully_exited:
                            self.upbit_active_strategy = None
                        self.last_upbit_signal = signal

                        if fully_exited and strategy_name == "sideways_v2" and self.sideways_v2_strategy:
                            # paper 엔진 상태와 전략 상태 싱크
                            self.sideways_v2_strategy.clear_position()
                            self.sideways_v2_strategy.hold_bars = 0
                            self.sideways_v2_strategy.entry_method = None
                            self.sideways_v2_strategy.partial_exits = 0

                        msg = f"🔴 [Upbit Paper] 매도\n"
                        msg += f"━━━━━━━━━━━━━━━━━━━━\n"
                        msg += f"💰 가격: {current_price:,.0f}원\n"
                        msg += f"📊 수량: {result['executed_volume']:.8f} BTC\n"
                        msg += f"💵 손익: {result['pnl']:+,.0f}원\n"
                        msg += f"📝 사유: {signal.get('reason', 'N/A')}"

                        print(msg)
                        if self.telegram:
                            self.telegram.send_message(msg)

            elif signal['action'] == 'hold':
                # 대기 상태 (첫 번째 반복에서만 알림)
                if self.iteration_count == 1:
                    print(f"⚪ [Upbit:{strategy_name}] 대기 중 - {signal.get('reason', 'N/A')}")

        except Exception as e:
            print(f"❌ Upbit 전략 실행 오류: {e}")
            import traceback
            traceback.print_exc()
            if self.telegram:
                self.telegram.send_message(f"❌ [Upbit] 전략 실행 오류: {e}")

    def execute_binance_strategy(self, current_price: float, strategy_name: Optional[str]):
        """Binance 전략 실행 (현재는 SHORT_V1만)."""
        if not strategy_name:
            if self.binance_position:
                strategy_name = self.binance_active_strategy or "short_v1"
            else:
                print("⚪ [Binance] 레짐상 진입 스킵")
                return

        if strategy_name != "short_v1":
            print(f"⚠️  알 수 없는 Binance 전략: {strategy_name}")
            return

        if not self.short_v1_strategy:
            print("⚠️  SHORT_V1 전략 미로드 - Binance 거래 스킵")
            return

        try:
            # 4시간봉 데이터 필요 (Binance API 또는 로컬 CSV)
            import pandas as pd

            # 로컬 CSV 로드 (data_collector로 미리 수집)
            csv_path = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                                    'strategies/SHORT_V1/results/btcusdt_4h_with_funding_2022-01-01_2024-12-31.csv')

            if os.path.exists(csv_path):
                df = pd.read_csv(csv_path)
                df['timestamp'] = pd.to_datetime(df['timestamp'])
                df = df.tail(300)  # 최근 300개 (워밍업 포함)
                df = df.reset_index(drop=True)

                # 지표 계산
                df = self.short_v1_strategy.prepare_data(df)

                # 현재 자본
                cash, _ = self.binance_account.get_balance()

                # 전략 실행 (execute 메서드 사용)
                signal = self.short_v1_strategy.execute(df, len(df) - 1, cash)

                # 신호 로그 출력
                print(f"[Binance] 신호: {signal['action']} | 사유: {signal.get('reason', 'N/A')}")

                if signal['action'] == 'open_short' and not self.binance_position:
                    # 숏 진입
                    base_fraction = float(signal.get("fraction", 0.5))
                    base_fraction = max(0.0, min(1.0, base_fraction))
                    position_size = cash * base_fraction * float(self.binance_fraction_mult)
                    leverage = signal.get('leverage', 2)

                    if position_size >= 10:  # 최소 10 USDT
                        result = self.binance_account.open_short(
                            position_size,
                            current_price,
                            leverage
                        )

                        if result['success']:
                            self.binance_position = True
                            self.binance_active_strategy = strategy_name
                            self.last_binance_signal = signal

                            msg = f"🔻 [Binance Paper] 숏 진입\n"
                            msg += f"━━━━━━━━━━━━━━━━━━━━\n"
                            msg += f"💰 가격: ${current_price:,.2f}\n"
                            msg += f"📊 수량: {result['executed_qty']:.6f} BTC\n"
                            msg += f"⚡ 레버리지: {leverage}x\n"
                            msg += f"📝 사유: {signal.get('reason', 'N/A')}"

                            print(msg)
                            if self.telegram:
                                self.telegram.send_message(msg)

                elif signal['action'] == 'close_short' and self.binance_position:
                    # 숏 청산
                    result = self.binance_account.close_short(current_price)

                    if result['success']:
                        self.binance_position = False
                        self.binance_active_strategy = None
                        self.last_binance_signal = signal

                        msg = f"🔺 [Binance Paper] 숏 청산\n"
                        msg += f"━━━━━━━━━━━━━━━━━━━━\n"
                        msg += f"💰 가격: ${current_price:,.2f}\n"
                        msg += f"💵 손익: ${result['realized_pnl']:+,.2f}\n"
                        msg += f"📝 사유: {signal.get('reason', 'N/A')}"

                        print(msg)
                        if self.telegram:
                            self.telegram.send_message(msg)

                elif signal['action'] == 'hold':
                    # 대기 상태 (첫 번째 반복에서만 알림)
                    if self.iteration_count == 1:
                        print(f"⚪ [Binance] 대기 중 - {signal.get('reason', 'N/A')}")
            else:
                print(f"⚠️  SHORT_V1 데이터 파일 없음: {csv_path}")
                if self.telegram and self.iteration_count == 1:
                    self.telegram.send_message(f"⚠️ [Binance] SHORT_V1 데이터 파일 없음\n실시간 데이터 수집 필요")

        except Exception as e:
            print(f"❌ Binance 전략 실행 오류: {e}")
            import traceback
            traceback.print_exc()
            if self.telegram:
                self.telegram.send_message(f"❌ [Binance] 전략 실행 오류: {e}")

    def run_iteration(self):
        """1회 반복 실행"""
        self.iteration_count += 1

        print(f"\n{'='*70}")
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Paper Trading 실행 (#{self.iteration_count})")
        print(f"{'='*70}")

        # 현재 가격
        prices = self.get_current_prices()
        print(f"Upbit: {prices['upbit']:,.0f}원 | Binance: ${prices['binance']:,.2f}")

        decision = self._maybe_update_regime_decision()
        if decision:
            # stickiness: 포지션 보유 중에는 기존 전략 유지
            if self.upbit_position and self.upbit_active_strategy == "bull_hold" and decision.regime != "BULL":
                upbit_target = "bull_hold"
            else:
                upbit_target = self.upbit_active_strategy if self.upbit_position else decision.upbit_strategy
            binance_target = self.binance_active_strategy if self.binance_position else decision.binance_strategy
            print(f"[Router] state={decision.market_state} regime={decision.regime} | upbit={upbit_target or 'NONE'} | binance={binance_target or 'NONE'}")
        else:
            upbit_target = self.upbit_active_strategy if self.upbit_position else "v35"
            binance_target = self.binance_active_strategy if self.binance_position else None
            print(f"[Router] 결정 없음 - 기본값 사용 (upbit={upbit_target}, binance={binance_target})")

        # 전략 실행
        self.execute_upbit_strategy(prices['upbit'], upbit_target, decision=decision)
        self.execute_binance_strategy(prices['binance'], binance_target)

        # 상태 출력
        self.print_status(prices)

        # 주기적 상태 알림 (6시간마다)
        self._send_status_notification(prices)

    def print_status(self, prices: Dict[str, float]):
        """현재 상태 출력"""
        print(f"\n{'─'*70}")
        print("  현재 상태")
        print(f"{'─'*70}")

        # Upbit
        upbit_cash, upbit_btc = self.upbit_account.get_balance()
        upbit_total = self.upbit_account.get_total_value(prices['upbit'])
        upbit_stats = self.upbit_account.get_statistics()

        print(f"\n[Upbit]")
        print(f"  포지션: {'🟢 있음' if self.upbit_position else '⚪ 없음'}")
        print(f"  현금: {upbit_cash:,.0f}원")
        print(f"  BTC: {upbit_btc:.8f} BTC")
        print(f"  총 가치: {upbit_total:,.0f}원")
        print(f"  수익률: {upbit_stats['return_pct']:+.2f}%")

        # Binance
        binance_cash, _ = self.binance_account.get_balance()
        binance_position = self.binance_account.get_position()
        binance_stats = self.binance_account.get_statistics()

        print(f"\n[Binance]")
        print(f"  포지션: {'🔻 숏' if self.binance_position else '⚪ 없음'}")
        if binance_position:
            print(f"  진입가: ${binance_position['entry_price']:,.2f}")
            print(f"  수량: {binance_position['size']:.6f} BTC")
            print(f"  레버리지: {binance_position['leverage']}x")
        print(f"  현금: ${binance_cash:,.2f}")
        print(f"  수익률: {binance_stats['return_pct']:+.2f}%")

        # 합계
        total_krw = upbit_total + (binance_cash * 1300)  # 간단히 1300 고정
        initial_total = self.upbit_account.initial_capital + (self.binance_account.initial_capital * 1300)
        total_return_pct = ((total_krw - initial_total) / initial_total) * 100

        print(f"\n[합계]")
        print(f"  총 자산: {total_krw:,.0f}원")
        print(f"  총 수익률: {total_return_pct:+.2f}%")
        print(f"{'─'*70}\n")

    def run_forever(self, interval_minutes: int = 60):
        """무한 루프 실행"""
        print(f"\n🚀 Paper Trading 시작 (간격: {interval_minutes}분)\n")

        # 로그 디렉토리 (절대 경로)
        log_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'logs')
        os.makedirs(log_dir, exist_ok=True)

        try:
            while True:
                self.run_iteration()

                # 로그 저장 (절대 경로 사용)
                try:
                    self.upbit_account.save_log(os.path.join(log_dir, 'paper_trading_upbit.json'))
                    self.binance_account.save_log(os.path.join(log_dir, 'paper_trading_binance.json'))
                except Exception as e:
                    print(f"⚠️  로그 저장 실패: {e}")

                # 대기
                print(f"\n⏱️  다음 실행까지 {interval_minutes}분 대기...\n")
                time.sleep(interval_minutes * 60)

        except KeyboardInterrupt:
            print(f"\n\n{'='*70}")
            print("  Paper Trading 중지")
            print(f"{'='*70}\n")

            # 최종 통계
            self.print_final_statistics()

    def print_final_statistics(self):
        """최종 통계 출력"""
        upbit_stats = self.upbit_account.get_statistics()
        binance_stats = self.binance_account.get_statistics()

        print("\n📊 최종 통계")
        print(f"{'='*70}")

        print(f"\n[Upbit]")
        print(f"  초기 자본: {upbit_stats['initial_capital']:,.0f}원")
        print(f"  최종 자본: {upbit_stats['current_cash']:,.0f}원")
        print(f"  총 거래: {upbit_stats['total_trades']}회")
        print(f"  승률: {upbit_stats['win_rate']*100:.1f}%")
        print(f"  순손익: {upbit_stats['net_pnl']:+,.0f}원")
        print(f"  수익률: {upbit_stats['return_pct']:+.2f}%")

        print(f"\n[Binance]")
        print(f"  초기 자본: ${binance_stats['initial_capital']:,.2f}")
        print(f"  최종 자본: ${binance_stats['current_cash']:,.2f}")
        print(f"  총 거래: {binance_stats['total_trades']}회")
        print(f"  승률: {binance_stats['win_rate']*100:.1f}%")
        print(f"  순손익: ${binance_stats['net_pnl']:+,.2f}")
        print(f"  수익률: {binance_stats['return_pct']:+.2f}%")

        print(f"\n{'='*70}\n")


if __name__ == '__main__':
    """실행"""
    import argparse

    parser = argparse.ArgumentParser(description='Dual Exchange Paper Trading')
    parser.add_argument('--upbit-capital', type=float, default=10_000_000,
                        help='Upbit 초기 자본 (KRW, 기본: 10M)')
    parser.add_argument('--binance-capital', type=float, default=10_000,
                        help='Binance 초기 자본 (USDT, 기본: 10K)')
    parser.add_argument('--interval', type=int, default=60,
                        help='실행 간격 (분, 기본: 60)')
    parser.add_argument('--no-telegram', action='store_true',
                        help='텔레그램 알림 비활성화')
    parser.add_argument('--candidate-json', type=str, default=None,
                        help='tune_operational_router 결과 JSON 경로 (results[...].candidate 로드)')
    parser.add_argument('--candidate-index', type=int, default=0,
                        help='candidate index (기본: 0)')

    args = parser.parse_args()

    engine = DualPaperTradingEngine(
        upbit_capital=args.upbit_capital,
        binance_capital=args.binance_capital,
        telegram_enabled=not args.no_telegram,
        candidate_json=args.candidate_json,
        candidate_index=args.candidate_index,
    )

    engine.run_forever(interval_minutes=args.interval)
