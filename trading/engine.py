#!/usr/bin/env python3
"""
Dual Exchange Engine (paper / live)
Upbit(v35 or SideWays_v2) + Binance(SHORT_V1)
"""

import sys
import os
import json
from pathlib import Path
from typing import Any, Dict, Optional
from datetime import datetime, timedelta
import time

# 프로젝트 루트 추가 (스크립트 실행 호환)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    # When imported as a package module
    from .execution.paper_account import PaperTradingAccount
    from .notification.telegram_notifier import TelegramNotifier
    from .strategy.regime_router import RegimeRouter, RegimeDecision
    from .risk.risk_controls import (
        RiskConfig,
        clamp_fraction,
        kill_switch_active,
        set_kill_switch,
        should_block_new_entries,
        today,
    )
    from .risk.premium_tracker import PremiumTracker
    from .risk.premium_controller import PremiumController
    from .execution.hedge_manager import HedgeManager
    from .execution.alpha_manager import AlphaManager
    from .execution.delta_rebalancer import DeltaRebalancer
    from .data.data_cache import DataCache, get_data_cache
except ImportError:  # pragma: no cover
    # When executed as a script
    from trading.execution.paper_account import PaperTradingAccount
    from trading.notification.telegram_notifier import TelegramNotifier
    from trading.strategy.regime_router import RegimeRouter, RegimeDecision
    from trading.risk.risk_controls import (
        RiskConfig,
        clamp_fraction,
        kill_switch_active,
        set_kill_switch,
        should_block_new_entries,
        today,
    )
    from trading.risk.premium_tracker import PremiumTracker
    from trading.risk.premium_controller import PremiumController
    from trading.execution.hedge_manager import HedgeManager
    from trading.execution.alpha_manager import AlphaManager
    from trading.execution.delta_rebalancer import DeltaRebalancer
    from trading.data.data_cache import DataCache, get_data_cache

from core.data_loader import DataLoader


def _load_allocation_config() -> Dict[str, Any]:
    """Load strategy allocation config."""
    config_path = Path(__file__).parent.parent / 'config' / 'strategies' / 'allocation.json'
    if config_path.exists():
        with open(config_path, 'r') as f:
            return json.load(f)
    # Default: v35 only
    return {
        "upbit": {
            "v35": {"ratio": 1.0, "enabled": True, "regimes": ["BULL"]},
            "va02": {"ratio": 0.0, "enabled": False, "regimes": ["BULL", "SIDEWAYS"]}
        }
    }


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
    """듀얼 거래소 엔진 (기본: paper, 옵션: live).

    NOTE: live 모드는 실제 주문을 실행합니다.
    안전장치로 환경변수 ENABLE_LIVE_TRADING=1 이 반드시 필요합니다.
    """

    def __init__(
        self,
        paper_upbit_capital: float = 10_000_000,  # 10M KRW (Paper 전용)
        paper_binance_capital: float = 10_000,    # 10K USDT (Paper 전용)
        telegram_enabled: bool = True,
        candidate_json: Optional[str] = None,
        candidate_index: int = 0,
        execution_mode: str = "paper",  # 'paper' | 'live'
        telegram_commands_enabled: bool = False,
        sideways_policy: str = "sideways_v2",  # 'sideways_v2' | 'h4_conservative' | 'v35' | 'hold'
        binance_policy: str = "short_v1",  # 'short_v1' | 'h4_short' | 'hold'
        binance_gate_mode: str = "bear_only",  # 'bear_only' | 'sideways_and_bear' | 'always'
    ):
        """
        Args:
            paper_upbit_capital: [Paper 전용] Upbit 시뮬레이션 자본 (KRW)
            paper_binance_capital: [Paper 전용] Binance 시뮬레이션 자본 (USDT)
            telegram_enabled: 텔레그램 알림 활성화
            sideways_policy: Sideways 레짐 Upbit 전략 (sideways_v2, h4_conservative, v35, hold)
            binance_policy: Bear 레짐 Binance 전략 (short_v1, h4_short, hold)
            binance_gate_mode: Binance 활성화 조건 (bear_only, sideways_and_bear, always)

        Note:
            Live 모드에서는 paper_*_capital 값이 무시되고 실제 거래소 잔고를 조회합니다.
        """
        if execution_mode not in {"paper", "live"}:
            raise ValueError(f"Invalid execution_mode: {execution_mode}")

        self.execution_mode = execution_mode

        # Risk controls (primarily for live mode)
        self.risk_config = RiskConfig()
        self._day_start_date = None
        self._day_start_total_krw: Optional[float] = None
        self._block_new_entries = False
        self._last_risk_alert_date = None

        # Live health monitoring
        self._consecutive_price_failures = 0
        self._consecutive_execution_errors = 0
        self._last_kill_recommend_at: Optional[datetime] = None

        # Simple v2 engine log files (for web dashboard)
        self._v2_trades: Dict[str, list] = {"upbit": [], "binance": []}
        self._signal_history: Dict[str, list] = {"upbit": [], "binance": []}
        self._v2_log_dir = Path(os.path.dirname(os.path.dirname(__file__))) / "logs"
        self._v2_log_dir.mkdir(parents=True, exist_ok=True)

        print("=" * 70)
        print(f"  Dual Exchange Engine [{execution_mode.upper()}]")
        print("=" * 70)
        if execution_mode == "paper":
            print(f"  [Paper] Upbit Capital: {paper_upbit_capital:,.0f} KRW")
            print(f"  [Paper] Binance Capital: {paper_binance_capital:,.2f} USDT")
        else:
            print("  [Live] 실제 거래소 잔고 조회...")
        print("=" * 70)

        # Accounts
        if execution_mode == "paper":
            self.upbit_account = PaperTradingAccount(paper_upbit_capital, 'upbit')
            self.binance_account = PaperTradingAccount(paper_binance_capital, 'binance')
        else:
            # Hard safety gate: require explicit opt-in.
            if os.getenv("ENABLE_LIVE_TRADING") != "1":
                raise ValueError(
                    "LIVE 모드 안전장치: ENABLE_LIVE_TRADING=1 환경변수가 필요합니다. "
                    "(실주문 실행 방지)"
                )

            from trading.adapters.upbit import UpbitTrader
            from trading.adapters.binance import BinanceFuturesTrader
            from trading.adapters.live_adapters import UpbitLiveAccount, BinanceLiveAccount

            upbit_trader = UpbitTrader()
            binance_trader = BinanceFuturesTrader()

            upbit_initial = float(upbit_trader.get_total_value())
            binance_initial = float((binance_trader.get_account_info() or {}).get("total_balance", 0.0))

            self.upbit_account = UpbitLiveAccount(trader=upbit_trader, initial_capital=upbit_initial)
            self.binance_account = BinanceLiveAccount(trader=binance_trader, initial_capital=binance_initial)

        # Candidate (tuned operational config)
        self._candidate: Optional[Dict[str, Any]] = None
        self.v35_fraction_mult = 1.0
        self.sideways_fraction_mult = 1.0
        self.binance_fraction_mult = 1.0
        self.bull_hold_fraction = 1.0
        self.sideways_v2_strategy_config: Dict[str, Any] = {}
        self._sideways_policy = sideways_policy  # CLI or default policy
        self._binance_policy = binance_policy    # CLI or default policy for Binance
        self._binance_gate_mode = binance_gate_mode  # Binance activation mode

        if candidate_json:
            self._candidate = _load_candidate_from_json(candidate_json, candidate_index)
            self._apply_candidate(self._candidate)

            # Optional risk overrides
            rc = dict(self._candidate.get("risk_config") or {}) if isinstance(self._candidate, dict) else {}
            if rc:
                self.risk_config = RiskConfig(
                    kill_switch_file=str(rc.get("kill_switch_file", self.risk_config.kill_switch_file)),
                    daily_max_loss_pct=float(rc.get("daily_max_loss_pct", self.risk_config.daily_max_loss_pct)),
                    max_upbit_entry_fraction=float(rc.get("max_upbit_entry_fraction", self.risk_config.max_upbit_entry_fraction)),
                    max_binance_entry_fraction=float(rc.get("max_binance_entry_fraction", self.risk_config.max_binance_entry_fraction)),
                    min_upbit_order_krw=float(rc.get("min_upbit_order_krw", self.risk_config.min_upbit_order_krw)),
                    min_binance_order_usdt=float(rc.get("min_binance_order_usdt", self.risk_config.min_binance_order_usdt)),
                    recommend_kill_on_daily_loss_pct=float(rc.get("recommend_kill_on_daily_loss_pct", self.risk_config.recommend_kill_on_daily_loss_pct)),
                    recommend_kill_on_price_failures=int(rc.get("recommend_kill_on_price_failures", self.risk_config.recommend_kill_on_price_failures)),
                    recommend_kill_on_consecutive_errors=int(rc.get("recommend_kill_on_consecutive_errors", self.risk_config.recommend_kill_on_consecutive_errors)),
                )

        # 전략 로드
        self.v35_strategy = self._load_v35_strategy()
        self.short_v1_strategy = self._load_short_v1_strategy()
        self.sideways_v2_strategy = self._init_sideways_v2_strategy(strategy_config=self.sideways_v2_strategy_config)
        self.h4_strategy = self._init_h4_strategy()
        self.h4_short_strategy = self._init_h4_short_strategy()
        self.va02_strategy = self._load_va02_strategy()

        # Multi-strategy allocation config
        self._allocation_config = _load_allocation_config()

        # 운영형 라우팅 (레짐 기반)
        self.router = self._build_router()
        self._last_regime_decision: Optional[RegimeDecision] = None
        self._last_regime_check_at: Optional[datetime] = None

        # 텔레그램
        self.telegram = TelegramNotifier() if telegram_enabled else None

        # Telegram commands (optional)
        self._telegram_commands_enabled = bool(telegram_commands_enabled)
        self._telegram_cmd = None
        if self.telegram and self._telegram_commands_enabled:
            try:
                from trading.notification.telegram_commands import TelegramCommandHandler
            except Exception:  # pragma: no cover
                TelegramCommandHandler = None

            if TelegramCommandHandler:
                self._telegram_cmd = TelegramCommandHandler(self.telegram)
                self._telegram_cmd.register_command("kill_on", lambda _: self._cmd_kill_switch(True))
                self._telegram_cmd.register_command("kill_off", lambda _: self._cmd_kill_switch(False))
                self._telegram_cmd.register_command("kill_status", lambda _: self._cmd_kill_status())
                self._telegram_cmd.start_polling()

        # 상태 (legacy - kept for binance compatibility)
        self.upbit_position = False  # Deprecated: use _upbit_positions
        self.binance_position = False
        self.upbit_active_strategy: Optional[str] = None  # Deprecated: use _upbit_positions
        self.binance_active_strategy: Optional[str] = None
        self.last_upbit_signal = None
        self.last_binance_signal = None
        self.iteration_count = 0  # 반복 횟수

        # Per-strategy position tracking for concurrent execution
        self._upbit_positions = self._init_upbit_positions()

        # Premium tracker for Kimchi Premium monitoring (legacy)
        premium_config = self._allocation_config.get("premium_tracking", {})
        self.premium_tracker = PremiumTracker(config=premium_config)
        self._last_premium_alert_at: Optional[datetime] = None

        # New Hedge Infrastructure (Phase 3)
        hedge_config = self._allocation_config.get("hedge", {})
        self._hedge_enabled = hedge_config.get("enabled", False)
        self.premium_controller: Optional[PremiumController] = None
        self.hedge_manager: Optional[HedgeManager] = None
        self.alpha_manager: Optional[AlphaManager] = None
        self.data_cache: Optional[DataCache] = None

        if self._hedge_enabled:
            self._init_hedge_infrastructure(hedge_config)

        print("✅ 초기화 완료\n")

        # 시작 알림 전송
        self._send_startup_notification()

    def _recommend_kill_switch(self, reason: str) -> None:
        """Notify operator that kill-switch is recommended (does not auto-enable)."""
        if not self.telegram:
            return
        now = datetime.now()
        # Basic rate limit: once per 30 minutes
        if self._last_kill_recommend_at and (now - self._last_kill_recommend_at).total_seconds() < 1800:
            return
        self._last_kill_recommend_at = now

        active = kill_switch_active(self.risk_config.kill_switch_file)
        state = "ON" if active else "OFF"
        msg = (
            "⚠️ Kill-Switch 권장\n"
            f"- reason: {reason}\n"
            f"- kill_switch: {state} ({self.risk_config.kill_switch_file})\n"
            f"- daily_block_new_entries: {self._block_new_entries}\n\n"
            "Telegram으로 제어: /kill_on /kill_off /kill_status"
        )
        try:
            self.telegram.send_message(msg)
        except Exception:
            pass

    def _cmd_kill_switch(self, active: bool) -> None:
        p = set_kill_switch(self.risk_config.kill_switch_file, bool(active))
        state = "ON" if active else "OFF"
        msg = f"⛔ Kill-Switch {state}: {str(p)}"
        print(msg)
        if self.telegram:
            self.telegram.send_message(msg)

    def _cmd_kill_status(self) -> None:
        active = kill_switch_active(self.risk_config.kill_switch_file)
        state = "ON" if active else "OFF"
        msg = f"⛔ Kill-Switch 상태: {state}\n- file: {self.risk_config.kill_switch_file}\n- daily_block_new_entries: {self._block_new_entries}"
        print(msg)
        if self.telegram:
            self.telegram.send_message(msg)

    def _init_hedge_infrastructure(self, hedge_config: Dict[str, Any]) -> None:
        """Initialize hedge infrastructure (PremiumController, HedgeManager, AlphaManager)."""
        try:
            # Initialize DataCache for in-memory data caching
            self.data_cache = get_data_cache()
            print("✅ DataCache 초기화 완료")

            # Initialize PremiumController for hedge signal generation
            history_file = str(self._v2_log_dir / "premium_history.json")
            premium_controller_config = {
                "history_file": history_file,
                "entry_threshold_pct": hedge_config.get("entry_threshold_pct", 1.5),
                "entry_sigma": hedge_config.get("entry_sigma", 2.0),
                "min_hold_minutes": hedge_config.get("min_hold_minutes", 30),
                "negative_funding_exit": hedge_config.get("negative_funding_exit", -0.05),
                "volatility_block_threshold": hedge_config.get("volatility_block_threshold", 2.0),
            }
            self.premium_controller = PremiumController(config=premium_controller_config)
            print("✅ PremiumController 초기화 완료")

            # Initialize HedgeManager for delta-neutral execution
            hedge_manager_config = {
                "capital_usdt": hedge_config.get("capital_usdt", 5000),
                "max_capital_usage_pct": hedge_config.get("max_capital_usage_pct", 0.8),
                "fee_pct": 0.04,
                "slippage_pct": 0.02,
            }
            self.hedge_manager = HedgeManager(
                binance_account=self.binance_account,
                premium_controller=self.premium_controller,
                config=hedge_manager_config,
                telegram_notifier=self.telegram,
                execution_mode=self.execution_mode,
            )
            print("✅ HedgeManager 초기화 완료")

            # Initialize DeltaRebalancer for automatic delta-neutral rebalancing
            rebalancer_config = {
                "calm_threshold_pct": hedge_config.get("calm_threshold_pct", 3.0),
                "normal_threshold_pct": hedge_config.get("normal_threshold_pct", 5.0),
                "volatile_threshold_pct": hedge_config.get("volatile_threshold_pct", 8.0),
                "volatility_calm": hedge_config.get("volatility_calm", 0.5),
                "volatility_high": hedge_config.get("volatility_high", 1.5),
                "min_rebalance_interval": hedge_config.get("min_rebalance_interval", 30),
            }
            self.delta_rebalancer = DeltaRebalancer(
                upbit_account=self.upbit_account,
                hedge_manager=self.hedge_manager,
                premium_controller=self.premium_controller,
                config=rebalancer_config,
            )
            print("✅ DeltaRebalancer 초기화 완료")

            # Initialize AlphaManager for directional strategies
            self.alpha_manager = AlphaManager(
                upbit_account=self.upbit_account,
                regime_router=self.router,
                allocation_config=self._allocation_config,
                strategies={
                    "v35": self.v35_strategy,
                    "va02": self.va02_strategy,
                    "sideways_v2": self.sideways_v2_strategy,
                    "h4_conservative": self.h4_strategy,
                },
                execution_mode=self.execution_mode,
                risk_config=self.risk_config,
                telegram_notifier=self.telegram,
                delta_rebalancer=self.delta_rebalancer,  # Pass rebalancer for trade notifications
            )
            print("✅ AlphaManager 초기화 완료")

            print(f"🔄 Hedge Infrastructure 활성화 (capital: ${hedge_config.get('capital_usdt', 5000):,.0f})")

        except Exception as e:
            print(f"⚠️  Hedge Infrastructure 초기화 실패: {e}")
            import traceback
            traceback.print_exc()
            self._hedge_enabled = False

    def _record_trade(self, exchange: str, trade: Dict[str, Any]) -> None:
        if exchange not in self._v2_trades:
            return
        self._v2_trades[exchange].append(trade)
        # keep last 200
        if len(self._v2_trades[exchange]) > 200:
            self._v2_trades[exchange] = self._v2_trades[exchange][-200:]

    def _record_signal(self, exchange: str, signal: Dict[str, Any], strategy: str,
                       indicators: Optional[Dict[str, Any]] = None) -> None:
        """Record strategy signal for dashboard display."""
        if exchange not in self._signal_history:
            return
        record = {
            "timestamp": datetime.now().isoformat(),
            "strategy": strategy,
            "action": signal.get("action", "hold"),
            "reason": signal.get("reason", ""),
            "regime": self._last_regime_decision.regime if self._last_regime_decision else None,
            "market_state": self._last_regime_decision.market_state if self._last_regime_decision else None,
            "indicators": indicators or {},
        }
        self._signal_history[exchange].append(record)
        # keep last 100
        if len(self._signal_history[exchange]) > 100:
            self._signal_history[exchange] = self._signal_history[exchange][-100:]

    def _extract_indicators(self, df, columns: list) -> Dict[str, Any]:
        """Extract indicator values from last row of dataframe."""
        if df is None or len(df) == 0:
            return {}
        last_row = df.iloc[-1]
        result = {}
        for col in columns:
            if col in df.columns:
                val = last_row[col]
                # Convert numpy types to Python types
                if hasattr(val, 'item'):
                    val = val.item()
                if isinstance(val, float):
                    result[col] = round(val, 2)
                else:
                    result[col] = val
        return result

    def _write_v2_engine_logs(self, prices: Dict[str, float]) -> None:
        """Write minimal engine logs for web dashboard consumption."""
        try:
            # Upbit
            upbit_cash, upbit_btc = self.upbit_account.get_balance()
            upbit_total = float(self.upbit_account.get_total_value(prices["upbit"]))
            upbit_stats = self.upbit_account.get_statistics() if hasattr(self.upbit_account, "get_statistics") else {}

            # Regime info from last decision
            regime_info = {
                "market_state": self._last_regime_decision.market_state if self._last_regime_decision else None,
                "regime": self._last_regime_decision.regime if self._last_regime_decision else None,
            }

            # Build per-strategy positions for concurrent execution
            strategy_positions = {}
            total_btc = 0.0
            total_cash = 0.0
            for strat_name, pos in self._upbit_positions.items():
                strategy_positions[strat_name] = {
                    "active": pos.get("active", False),
                    "btc": pos.get("btc", 0.0),
                    "entry_price": pos.get("entry_price", 0.0),
                    "cash": pos.get("cash", 0.0),
                    "initial_cash": pos.get("initial_cash", 0.0),
                    "ratio": pos.get("ratio", 0.0),
                    "value": pos.get("cash", 0.0) + pos.get("btc", 0.0) * prices["upbit"],
                }
                total_btc += pos.get("btc", 0.0)
                total_cash += pos.get("cash", 0.0)

            upbit_payload = {
                "exchange": "upbit",
                "mode": self.execution_mode,
                "initial_capital": getattr(self.upbit_account, "initial_capital", None),
                "current_cash": total_cash,
                "btc_balance": total_btc,
                "total_value": total_cash + total_btc * prices["upbit"],
                "strategy": self.upbit_active_strategy or "none",
                "regime": regime_info["regime"],
                "market_state": regime_info["market_state"],
                "trades": self._v2_trades["upbit"],
                "signals": self._signal_history["upbit"][-50:],
                "statistics": upbit_stats,
                "strategies": strategy_positions,  # Per-strategy data
                "generated_at": datetime.now().isoformat(),
            }

            # Binance
            binance_cash, _ = self.binance_account.get_balance()
            binance_stats = self.binance_account.get_statistics() if hasattr(self.binance_account, "get_statistics") else {}
            pos = self.binance_account.get_position() if hasattr(self.binance_account, "get_position") else None

            binance_payload = {
                "exchange": "binance",
                "mode": self.execution_mode,
                "initial_capital": getattr(self.binance_account, "initial_capital", None),
                "current_cash": float(binance_cash),
                "position_size": float(pos.get("size")) if pos else 0.0,
                "entry_price": float(pos.get("entry_price")) if pos else 0.0,
                "leverage": int(pos.get("leverage")) if pos else 1,
                "strategy": self.binance_active_strategy or "none",
                "regime": regime_info["regime"],
                "market_state": regime_info["market_state"],
                "trades": self._v2_trades["binance"],
                "signals": self._signal_history["binance"][-50:],
                "statistics": binance_stats,
                "generated_at": datetime.now().isoformat(),
            }

            # Calculate premium and hedge ratio for combined log
            premium_info = self.calculate_kimchi_premium(prices)
            hedge_info = self.calculate_hedge_ratio(prices)
            premium_stats = self.premium_tracker.get_stats()

            # Build hedge manager state (if enabled)
            hedge_manager_state = None
            if self._hedge_enabled and self.hedge_manager:
                hedge_manager_state = self.hedge_manager.to_dict()

            # Build premium controller stats (if enabled)
            premium_controller_stats = None
            if self._hedge_enabled and self.premium_controller:
                pc_stats = self.premium_controller.get_stats()
                premium_controller_stats = {
                    "current": pc_stats.current,
                    "mean_24h": pc_stats.mean_24h,
                    "std_24h": pc_stats.std_24h,
                    "min_24h": pc_stats.min_24h,
                    "max_24h": pc_stats.max_24h,
                    "volatility_state": pc_stats.volatility_state,
                    "trend": pc_stats.trend,
                    "readings_count": pc_stats.readings_count,
                    "entry_threshold": pc_stats.mean_24h + 2 * pc_stats.std_24h if pc_stats.std_24h > 0 else 0,
                }

            combined_payload = {
                "generated_at": datetime.now().isoformat(),
                "mode": self.execution_mode,
                "regime": regime_info["regime"],
                "market_state": regime_info["market_state"],
                "kimchi_premium": premium_info,
                "premium_stats": {
                    "current": premium_stats.current,
                    "mean_24h": premium_stats.mean_24h,
                    "std_24h": premium_stats.std_24h,
                    "min_24h": premium_stats.min_24h,
                    "max_24h": premium_stats.max_24h,
                    "volatility_state": premium_stats.volatility_state,
                    "trend": premium_stats.trend,
                    "readings_count": premium_stats.readings_count,
                },
                "hedge_ratio": hedge_info,
                "prices": {
                    "upbit_krw": prices.get("upbit", 0),
                    "binance_usd": prices.get("binance", 0),
                },
                # New hedge infrastructure state
                "hedge_enabled": self._hedge_enabled,
                "hedge_manager": hedge_manager_state,
                "premium_controller": premium_controller_stats,
            }

            (self._v2_log_dir / "v2_engine_upbit.json").write_text(json.dumps(upbit_payload, ensure_ascii=False, indent=2), encoding="utf-8")
            (self._v2_log_dir / "v2_engine_binance.json").write_text(json.dumps(binance_payload, ensure_ascii=False, indent=2), encoding="utf-8")
            (self._v2_log_dir / "v2_engine_combined.json").write_text(json.dumps(combined_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            print(f"⚠️  v2_engine 로그 저장 실패: {e}")

    def _send_startup_notification(self):
        """시작 알림 전송"""
        if not self.telegram:
            return

        mode_label = "LIVE" if self.execution_mode == "live" else "PAPER"
        sideways_label = self._sideways_policy
        binance_label = self._binance_policy
        msg = f"🚀 Dual Exchange {mode_label} 시작\n"
        msg += "=" * 30 + "\n\n"
        msg += "📊 전략 구성:\n"
        msg += f"  • Upbit BULL: v35\n"
        msg += f"  • Upbit SIDEWAYS: {sideways_label}\n"
        msg += f"  • Binance BEAR: {binance_label}\n\n"

        # 자본금 정보 (Paper: 시뮬레이션 자본, Live: 실제 잔고)
        upbit_capital = getattr(self.upbit_account, 'initial_capital', 0)
        binance_capital = getattr(self.binance_account, 'initial_capital', 0)
        capital_label = "시뮬레이션 자본" if self.execution_mode == "paper" else "실제 잔고"
        msg += f"💰 {capital_label}:\n"
        msg += f"  • Upbit: {upbit_capital:,.0f} KRW\n"
        msg += f"  • Binance: ${binance_capital:,.2f} USDT\n\n"
        msg += f"✅ V35 전략: {'로드 성공' if self.v35_strategy else '❌ 로드 실패'}\n"
        msg += f"✅ VA02 전략: {'로드 성공' if self.va02_strategy else '❌ 로드 실패'}\n"
        msg += f"✅ SHORT_V1 전략: {'로드 성공' if self.short_v1_strategy else '❌ 로드 실패'}\n"
        msg += f"✅ SideWays_v2 전략: {'로드 성공' if self.sideways_v2_strategy else '❌ 로드 실패'}\n"
        msg += f"✅ H4 Conservative: {'로드 성공 (50%)' if self.h4_strategy else '❌ 로드 실패'}\n"
        msg += f"✅ H4 Short: {'로드 성공 (50%)' if self.h4_short_strategy else '❌ 로드 실패'}\n\n"

        # Show allocation config
        upbit_alloc = self._allocation_config.get("upbit", {})
        if upbit_alloc.get("va02", {}).get("enabled"):
            v35_ratio = upbit_alloc.get("v35", {}).get("ratio", 0.5)
            va02_ratio = upbit_alloc.get("va02", {}).get("ratio", 0.5)
            msg += f"📊 Upbit 자본 배분:\n"
            msg += f"  • V35: {v35_ratio:.0%}\n"
            msg += f"  • VA02: {va02_ratio:.0%}\n\n"
        msg += "⏰ 신호 체크: 60분마다 (레짐은 day 기반)"

        if self._candidate:
            msg += "\n\n🧪 Candidate 적용됨: router/policy/mults"

        if self._telegram_commands_enabled and self.telegram:
            msg += "\n\n⌨️ Telegram commands: /kill_on /kill_off /kill_status"

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
        # CLI policy가 기본 policy로 사용됨
        default_sideways_policy = self._sideways_policy
        default_binance_policy = self._binance_policy
        default_binance_gate_mode = self._binance_gate_mode

        if not self._candidate:
            return RegimeRouter(
                lookback_days=180,
                sideways_policy=default_sideways_policy,
                binance_policy=default_binance_policy,
                binance_gate_mode=default_binance_gate_mode,
            )

        cand = self._candidate
        rcfg = dict(cand.get("router_config") or {})
        # candidate에 policy가 있으면 그걸 사용, 없으면 CLI 값 사용
        sideways_policy = str(cand.get("sideways_policy", default_sideways_policy))
        binance_policy = str(cand.get("binance_policy", default_binance_policy))
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
            sideways_policy=sideways_policy,
            sideways_bear_policy=cand.get("sideways_bear_policy"),
            bear_moderate_policy=cand.get("bear_moderate_policy"),
            bear_strong_policy=cand.get("bear_strong_policy"),
            binance_gate_mode=str(cand.get("binance_gate_mode", "bear_only")),
            binance_policy=binance_policy,
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

        # Regime info
        regime_str = "⏳ 확인 중"
        if self._last_regime_decision:
            rd = self._last_regime_decision
            regime_emoji = {"BULL": "🐂 상승장", "BEAR": "🐻 하락장", "SIDEWAYS": "↔️ 횡보장"}.get(rd.regime, rd.regime)
            regime_str = f"{regime_emoji} ({rd.market_state})"

        msg = "📊 Dual Trading 상태 보고\n"
        msg += "=" * 30 + "\n\n"
        msg += f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"
        msg += f"🌐 시장 상태: {regime_str}\n\n"

        msg += "📈 [Upbit]\n"
        msg += f"  전략: {self.upbit_active_strategy or 'none'}\n"
        msg += f"  포지션: {'🟢 있음' if self.upbit_position else '⚪ 없음'}\n"
        msg += f"  총 가치: {upbit_total:,.0f}원\n"
        msg += f"  수익률: {upbit_stats['return_pct']:+.2f}%\n\n"

        msg += "📉 [Binance]\n"
        msg += f"  전략: {self.binance_active_strategy or 'none'}\n"
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
            import json
            from trading.strategy.v35_long import V35LongStrategy

            config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                                       'config/strategies/v35_long.json')
            with open(config_path, 'r') as f:
                config = json.load(f)

            strategy = V35LongStrategy(config=config)
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
            import json
            from trading.strategy.short_v1 import ShortV1Strategy

            config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                                       'config/strategies/short_v1.json')
            with open(config_path, 'r') as f:
                config = json.load(f)

            strategy = ShortV1Strategy(config=config)
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
            from trading.strategy.sideways_v2 import SideWaysV2Strategy

            strategy = SideWaysV2Strategy(config=None, strategy_config=(strategy_config or None))
            print("✅ SideWays_v2 전략 초기화 완료")
            return strategy
        except Exception as e:
            print(f"⚠️  SideWays_v2 전략 초기화 실패: {e}")
            return None

    def _init_h4_strategy(self):
        """H4 Conservative 전략 초기화 (Sideways 레짐 대응, 4시간봉)."""
        try:
            from trading.strategy.h4_conservative import H4ConservativeStrategy

            config = {
                'position_fraction': 0.5,  # 50% 자본 배분
                'take_profit': 0.04,       # 4% 익절
                'stop_loss': -0.02,        # 2% 손절
            }
            strategy = H4ConservativeStrategy(config)
            print("✅ H4 Conservative 전략 초기화 완료 (50% 자본)")
            return strategy
        except Exception as e:
            print(f"⚠️  H4 Conservative 전략 초기화 실패: {e}")
            return None

    def _init_h4_short_strategy(self):
        """H4 Short 전략 초기화 (Binance 숏, 4시간봉).

        과매수 구간에서 숏 진입, H4 Conservative의 반대 로직
        백테스트: Train +7.97%, Validation +15.53% (88% 승률)
        """
        try:
            from trading.strategy.h4_short import H4ShortStrategy

            config = {
                'position_fraction': 0.5,  # 50% 자본 배분
                'take_profit': 0.05,       # 5% 익절
                'stop_loss': -0.02,        # 2% 손절
                'rsi_overbought': 72.0,    # RSI > 72 (과매수)
                'bb_position_min': 0.82,   # BB 상단
                'pct_rise_threshold': 6.0, # 저점 대비 6% 상승
            }
            strategy = H4ShortStrategy(config)
            print("✅ H4 Short 전략 초기화 완료 (Binance, 50% 자본)")
            return strategy
        except Exception as e:
            print(f"⚠️  H4 Short 전략 초기화 실패: {e}")
            return None

    def _load_va02_strategy(self):
        """VA02 Long 전략 로드"""
        try:
            from trading.strategy.va02_long import VA02LongStrategy

            strategy = VA02LongStrategy()
            print("✅ VA02 Long 전략 로드 완료")
            return strategy
        except Exception as e:
            print(f"⚠️  VA02 Long 전략 로드 실패: {e}")
            import traceback
            traceback.print_exc()
            return None

    def _is_strategy_allowed_in_regime(self, strategy_name: str, regime: str) -> bool:
        """Check if strategy is allowed to trade in current regime."""
        upbit_config = self._allocation_config.get("upbit", {})
        strategy_config = upbit_config.get(strategy_name, {})

        if not strategy_config.get("enabled", False):
            return False

        allowed_regimes = strategy_config.get("regimes", [])
        # Check if regime matches any allowed regime prefix
        for allowed in allowed_regimes:
            if regime.startswith(allowed):
                return True
        return False

    def _init_upbit_positions(self) -> Dict[str, Dict[str, Any]]:
        """Initialize per-strategy position tracking with split capital."""
        upbit_config = self._allocation_config.get("upbit", {})

        # Get total Upbit capital
        total_cash, _ = self.upbit_account.get_balance()

        positions = {}
        for strategy_name, config in upbit_config.items():
            if not config.get("enabled", False):
                continue

            ratio = config.get("ratio", 0.0)
            allocated_cash = float(total_cash) * ratio

            positions[strategy_name] = {
                "active": False,
                "btc": 0.0,
                "entry_price": 0.0,
                "cash": allocated_cash,
                "initial_cash": allocated_cash,
                "ratio": ratio,
                "regimes": config.get("regimes", []),
            }

            print(f"  📊 {strategy_name}: {ratio*100:.0f}% = {allocated_cash:,.0f} KRW")

        return positions

    def _get_upbit_strategy_position(self, strategy_name: str) -> Dict[str, Any]:
        """Get position info for a specific strategy."""
        return self._upbit_positions.get(strategy_name, {
            "active": False, "btc": 0.0, "entry_price": 0.0, "cash": 0.0
        })

    def _has_any_upbit_position(self) -> bool:
        """Check if any Upbit strategy has an active position."""
        return any(pos.get("active", False) for pos in self._upbit_positions.values())

    def _get_total_upbit_value(self, current_price: float) -> float:
        """Get total value across all Upbit strategies."""
        total = 0.0
        for pos in self._upbit_positions.values():
            total += pos.get("cash", 0.0)
            total += pos.get("btc", 0.0) * current_price
        return total

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

    def calculate_kimchi_premium(self, prices: Dict[str, float]) -> Dict[str, float]:
        """Calculate Kimchi Premium (Upbit vs Binance price differential).

        Returns:
            Dict with premium_pct, upbit_usd, binance_usd, usd_krw_rate
        """
        premium_config = self._allocation_config.get("premium_tracking", {})
        usd_krw_rate = premium_config.get("usd_krw_rate", 1450)

        upbit_krw = prices.get('upbit', 0)
        binance_usd = prices.get('binance', 0)

        if binance_usd <= 0:
            return {"premium_pct": 0.0, "upbit_usd": 0.0, "binance_usd": 0.0, "usd_krw_rate": usd_krw_rate}

        # Convert Upbit KRW to USD equivalent
        upbit_usd = upbit_krw / usd_krw_rate

        # Premium = (Upbit - Binance) / Binance * 100
        premium_pct = ((upbit_usd - binance_usd) / binance_usd) * 100

        return {
            "premium_pct": round(premium_pct, 2),
            "upbit_usd": round(upbit_usd, 2),
            "binance_usd": round(binance_usd, 2),
            "usd_krw_rate": usd_krw_rate,
        }

    def calculate_hedge_ratio(self, prices: Dict[str, float]) -> Dict[str, float]:
        """Calculate current hedge ratio (short exposure / long exposure).

        Returns:
            Dict with hedge_ratio, long_exposure, short_exposure, regime_target
        """
        # Calculate long exposure (Upbit positions)
        _, upbit_btc = self.upbit_account.get_balance()
        long_exposure = upbit_btc * prices.get('upbit', 0)

        # Calculate short exposure (Binance positions)
        binance_pos = self.binance_account.get_position() if hasattr(self.binance_account, 'get_position') else None
        if binance_pos and binance_pos.get('size', 0) > 0:
            # Convert to KRW equivalent for comparison
            usd_krw_rate = self._allocation_config.get("premium_tracking", {}).get("usd_krw_rate", 1450)
            short_exposure = binance_pos['size'] * prices.get('binance', 0) * usd_krw_rate
        else:
            short_exposure = 0.0

        # Calculate hedge ratio
        if long_exposure > 0:
            hedge_ratio = short_exposure / long_exposure
        else:
            hedge_ratio = 0.0

        # Get regime-based target
        current_regime = self._last_regime_decision.regime if self._last_regime_decision else "SIDEWAYS"
        hedge_targets = self._allocation_config.get("hedge_ratio_targets", {})
        regime_config = hedge_targets.get(current_regime, {"min": 0.3, "max": 0.7, "target": 0.5})
        base_target = regime_config.get("target", 0.5)

        # Apply dynamic premium-based adjustment
        premium_adjustment = self.premium_tracker.get_hedge_adjustment(
            base_target=base_target,
            regime=current_regime,
        )
        adjusted_target = premium_adjustment.get("adjusted_target", base_target)

        return {
            "hedge_ratio": round(hedge_ratio, 3),
            "long_exposure_krw": round(long_exposure, 0),
            "short_exposure_krw": round(short_exposure, 0),
            "regime": current_regime,
            "target_min": regime_config.get("min", 0.3),
            "target_max": regime_config.get("max", 0.7),
            "target": base_target,
            "adjusted_target": adjusted_target,
            "adjustment_reason": premium_adjustment.get("reason", "normal"),
        }

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

    def _execute_upbit_strategies_concurrent(self, current_price: float, regime: str, decision: Optional[RegimeDecision] = None):
        """Execute all enabled Upbit strategies concurrently."""
        executed = []

        for strategy_name, pos in self._upbit_positions.items():
            # Check if strategy is allowed in current regime
            if not self._is_strategy_allowed_in_regime(strategy_name, regime):
                if not pos.get("active", False):
                    # Skip if not in position and regime doesn't match
                    continue

            # Execute strategy with its own position tracking
            self._execute_upbit_strategy_with_position(current_price, strategy_name, pos, decision)
            executed.append(strategy_name)

        if executed:
            active_strats = [s for s, p in self._upbit_positions.items() if p.get("active")]
            print(f"  [Concurrent] executed={executed} active={active_strats}")

        # Update legacy flags for compatibility
        self.upbit_position = self._has_any_upbit_position()
        active = [s for s, p in self._upbit_positions.items() if p.get("active")]
        self.upbit_active_strategy = active[0] if len(active) == 1 else ",".join(active) if active else None

    def _execute_upbit_strategy_with_position(
        self,
        current_price: float,
        strategy_name: str,
        pos: Dict[str, Any],
        decision: Optional[RegimeDecision] = None
    ):
        """Execute a single Upbit strategy with its own position tracking."""
        # Get strategy object
        strategy = None
        if strategy_name == "v35":
            strategy = self.v35_strategy
        elif strategy_name == "va02":
            strategy = self.va02_strategy
        elif strategy_name == "sideways_v2":
            strategy = self.sideways_v2_strategy
        elif strategy_name == "h4_conservative":
            strategy = self.h4_strategy

        if not strategy:
            return

        try:
            # Load data and generate signal
            if strategy_name == "va02":
                with DataLoader() as loader:
                    df = loader.load_timeframe('day', start_date='2024-01-01')
                df = df.tail(500).reset_index(drop=True)
                df = strategy.add_indicators(df)
                signal = strategy.generate_signal(df, len(df) - 1) or {
                    "action": "hold", "reason": "VA02_NO_SIGNAL"
                }
                indicators = self._extract_indicators(df, ["rsi", "mfi", "adx", "close"])
                if "score" in signal:
                    indicators["score"] = signal.get("score", 0)
                    indicators["tier"] = signal.get("tier", "C")
            elif strategy_name == "v35":
                with DataLoader() as loader:
                    df = loader.load_timeframe('day', start_date='2024-01-01')
                df = df.tail(500).reset_index(drop=True)
                df = strategy.add_indicators(df)
                signal = strategy.generate_signal(df, len(df) - 1) or {
                    "action": "hold", "reason": "V35_NO_SIGNAL"
                }
                indicators = self._extract_indicators(df, ["rsi", "mfi", "adx", "close"])
            else:
                # For other strategies, skip concurrent execution for now
                return

            # Record signal
            self._record_signal("upbit", signal, strategy_name, indicators)

            # Execute based on signal
            if signal.get("action") == "buy" and not pos.get("active", False):
                self._execute_strategy_buy(current_price, strategy_name, pos, signal)
            elif signal.get("action") == "sell" and pos.get("active", False):
                self._execute_strategy_sell(current_price, strategy_name, pos, signal)

        except Exception as e:
            print(f"⚠️  [{strategy_name}] 전략 실행 오류: {e}")
            import traceback
            traceback.print_exc()

    def _execute_strategy_buy(
        self,
        current_price: float,
        strategy_name: str,
        pos: Dict[str, Any],
        signal: Dict[str, Any]
    ):
        """Execute buy for a specific strategy using its allocated capital."""
        if self.execution_mode == "live" and self._block_new_entries:
            print(f"⛔ [{strategy_name}] LIVE 신규 진입 차단 (daily loss guard)")
            return

        cash = pos.get("cash", 0.0)
        frac = float(signal.get("fraction", 0.5))
        frac = clamp_fraction(frac, self.risk_config.max_upbit_entry_fraction)
        buy_amount = cash * frac

        if buy_amount < float(self.risk_config.min_upbit_order_krw):
            print(f"⚪ [{strategy_name}] 매수 금액 부족: {buy_amount:,.0f} < {self.risk_config.min_upbit_order_krw:,.0f}")
            return

        tag = "Live" if self.execution_mode == "live" else "Paper"

        if self.execution_mode == "live":
            # LIVE MODE: Place actual order on exchange
            result = self.upbit_account.buy(buy_amount, current_price)
            if not result or not result.get("success"):
                print(f"❌ [{strategy_name}] 실제 주문 실패: {result}")
                return
            # Use executed values from exchange
            btc_amount = float(result.get("executed_volume", 0))
            actual_price = float(result.get("executed_price", current_price))
            # Refresh actual balance from exchange
            actual_cash, actual_btc = self.upbit_account.get_balance()
            pos["cash"] = actual_cash * pos.get("ratio", 0.5)  # Approximate strategy's share
        else:
            # PAPER MODE: Simulate trade
            fee_rate = 0.0005  # 0.05%
            btc_amount = (buy_amount * (1 - fee_rate)) / current_price
            actual_price = current_price
            pos["cash"] = cash - buy_amount

        # Update position
        pos["active"] = True
        pos["btc"] = btc_amount
        pos["entry_price"] = actual_price

        msg = f"🟢 [{strategy_name} {tag}] 매수\n"
        msg += f"━━━━━━━━━━━━━━━━━━━━\n"
        msg += f"💰 가격: {actual_price:,.0f}원\n"
        msg += f"📊 수량: {btc_amount:.8f} BTC\n"
        msg += f"💵 투자: {buy_amount:,.0f}원 ({frac*100:.0f}%)\n"
        msg += f"📝 사유: {signal.get('reason', 'N/A')}"
        print(msg)

        if self.telegram:
            self.telegram.send_message(msg)

        # Record trade
        self._v2_trades["upbit"].append({
            "timestamp": datetime.now().isoformat(),
            "strategy": strategy_name,
            "type": "buy",
            "price": actual_price,
            "amount": btc_amount,
            "value": buy_amount,
            "reason": signal.get("reason"),
        })

    def _execute_strategy_sell(
        self,
        current_price: float,
        strategy_name: str,
        pos: Dict[str, Any],
        signal: Dict[str, Any]
    ):
        """Execute sell for a specific strategy."""
        btc = pos.get("btc", 0.0)
        entry_price = pos.get("entry_price", current_price)
        frac = float(signal.get("fraction", 1.0))
        sell_btc = btc * frac

        tag = "Live" if self.execution_mode == "live" else "Paper"

        if self.execution_mode == "live":
            # LIVE MODE: Place actual order on exchange
            result = self.upbit_account.sell(sell_btc, current_price)
            if not result or not result.get("success"):
                print(f"❌ [{strategy_name}] 실제 매도 주문 실패: {result}")
                return
            # Use executed values from exchange
            executed_btc = float(result.get("executed_volume", sell_btc))
            actual_price = float(result.get("executed_price", current_price))
            sell_value = float(result.get("executed_amount", executed_btc * actual_price))
            # Refresh actual balance from exchange
            actual_cash, actual_btc = self.upbit_account.get_balance()
            pos["cash"] = actual_cash * pos.get("ratio", 0.5)  # Approximate strategy's share
        else:
            # PAPER MODE: Simulate trade
            fee_rate = 0.0005  # 0.05%
            sell_value = sell_btc * current_price * (1 - fee_rate)
            actual_price = current_price
            executed_btc = sell_btc
            pos["cash"] = pos.get("cash", 0.0) + sell_value

        # Calculate PnL
        cost_basis = executed_btc * entry_price
        pnl = sell_value - cost_basis
        pnl_pct = (actual_price - entry_price) / entry_price if entry_price > 0 else 0

        # Update position
        remaining_btc = btc - executed_btc
        if remaining_btc < 1e-8:
            pos["active"] = False
            pos["btc"] = 0.0
            pos["entry_price"] = 0.0
        else:
            pos["btc"] = remaining_btc

        pnl_emoji = "📈" if pnl >= 0 else "📉"
        msg = f"🔴 [{strategy_name} {tag}] 매도\n"
        msg += f"━━━━━━━━━━━━━━━━━━━━\n"
        msg += f"💰 가격: {actual_price:,.0f}원\n"
        msg += f"📊 수량: {executed_btc:.8f} BTC\n"
        msg += f"{pnl_emoji} 손익: {pnl:+,.0f}원 ({pnl_pct:+.2%})\n"
        msg += f"📝 사유: {signal.get('reason', 'N/A')}"
        print(msg)

        if self.telegram:
            self.telegram.send_message(msg)

        # Record trade
        self._v2_trades["upbit"].append({
            "timestamp": datetime.now().isoformat(),
            "strategy": strategy_name,
            "type": "sell",
            "price": actual_price,
            "amount": executed_btc,
            "value": sell_value,
            "pnl": pnl,
            "pnl_pct": pnl_pct,
            "reason": signal.get("reason"),
        })

    def execute_upbit_strategy(self, current_price: float, strategy_name: Optional[str], decision: Optional[RegimeDecision] = None):
        """Upbit 전략 실행 (v35 또는 SideWays_v2)."""
        if not strategy_name:
            if self.upbit_position:
                strategy_name = self.upbit_active_strategy or "v35"
            else:
                print("⚪ [Upbit] 레짐상 진입 스킵")
                return

        # Check if strategy is allowed in current regime (from allocation config)
        current_regime = decision.regime if decision else "UNKNOWN"
        if strategy_name not in ["bull_hold"] and not self.upbit_position:
            if not self._is_strategy_allowed_in_regime(strategy_name, current_regime):
                print(f"⚪ [{strategy_name}] 레짐 {current_regime}에서 비활성화됨 (allocation config)")
                return

        # Special: bull_hold
        if strategy_name == "bull_hold":
            if not self.upbit_position:
                if self.execution_mode == "live" and self._block_new_entries:
                    print("⛔ [Risk] LIVE 신규 진입 차단 (daily loss guard)")
                    return
                cash, _ = self.upbit_account.get_balance()
                frac = clamp_fraction(float(self.bull_hold_fraction), self.risk_config.max_upbit_entry_fraction)
                buy_amount = cash * frac
                if buy_amount >= float(self.risk_config.min_upbit_order_krw):
                    result = self.upbit_account.buy(buy_amount, current_price)
                    if result.get("success"):
                        self.upbit_position = True
                        self.upbit_active_strategy = "bull_hold"
                        tag = "Live" if self.execution_mode == "live" else "Paper"
                        msg = f"🟢 [Upbit {tag}] BULL_HOLD 매수\n━━━━━━━━━━━━━━━━━━━━\n💰 가격: {current_price:,.0f}원\n📊 수량: {result['executed_volume']:.8f} BTC\n📝 사유: BULL_HOLD_ENTRY"
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
                            tag = "Live" if self.execution_mode == "live" else "Paper"
                            pnl = result.get("pnl")
                            pnl_str = f"{float(pnl):+,.0f}원" if pnl is not None else "N/A"
                            msg = f"🔴 [Upbit {tag}] BULL_HOLD 청산\n━━━━━━━━━━━━━━━━━━━━\n💰 가격: {current_price:,.0f}원\n📊 수량: {result['executed_volume']:.8f} BTC\n💵 손익: {pnl_str}\n📝 사유: BULL_HOLD_EXIT_{decision.regime}"
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

        if strategy_name == "h4_conservative" and not self.h4_strategy:
            print("⚠️  H4 Conservative 전략 미로드 - Upbit 거래 스킵")
            return

        if strategy_name == "v35" and not self.v35_strategy:
            print("⚠️  V35 전략 미로드 - Upbit 거래 스킵")
            return

        if strategy_name == "va02" and not self.va02_strategy:
            print("⚠️  VA02 전략 미로드 - Upbit 거래 스킵")
            return

        try:
            if strategy_name == "va02":
                with DataLoader() as loader:
                    df = loader.load_timeframe('day', start_date='2024-01-01')
                df = df.tail(500).reset_index(drop=True)
                df = self.va02_strategy.add_indicators(df)
                signal = self.va02_strategy.generate_signal(df, len(df) - 1) or {
                    "action": "hold",
                    "reason": "VA02_NO_SIGNAL",
                }
                indicators = self._extract_indicators(df, ["rsi", "mfi", "adx", "close", "score"])
                if "score" in signal:
                    indicators["score"] = signal.get("score", 0)
                    indicators["tier"] = signal.get("tier", "C")
            elif strategy_name == "v35":
                with DataLoader() as loader:
                    df = loader.load_timeframe('day', start_date='2024-01-01')
                df = df.tail(500).reset_index(drop=True)
                df = self.v35_strategy.add_indicators(df)
                signal = self.v35_strategy.generate_signal(df, len(df) - 1) or {
                    "action": "hold",
                    "reason": "V35_NO_SIGNAL",
                }
                indicators = self._extract_indicators(df, ["rsi", "mfi", "adx", "close"])
            elif strategy_name == "sideways_v2":
                with DataLoader() as loader:
                    df = loader.load_timeframe('minute240', start_date='2024-01-01')
                df = df.tail(500).reset_index(drop=True)
                df = self.sideways_v2_strategy.add_indicators(df)
                signal = self.sideways_v2_strategy.generate_signal(df, len(df) - 1) or {
                    "action": "hold",
                    "reason": "SIDEWAYS_V2_NO_SIGNAL",
                }
                indicators = self._extract_indicators(df, ["rsi", "bb_upper", "bb_lower", "close"])
            elif strategy_name == "h4_conservative":
                with DataLoader() as loader:
                    df = loader.load_timeframe('minute240', start_date='2024-01-01')
                df = df.tail(500).reset_index(drop=True)
                df = self.h4_strategy.add_indicators(df)
                signal = self.h4_strategy.generate_signal(df, len(df) - 1) or {
                    "action": "hold",
                    "reason": "H4_NO_SIGNAL",
                }
                indicators = self._extract_indicators(df, ["rsi", "stoch_k", "stoch_d", "close"])
            else:
                print(f"⚠️  알 수 없는 Upbit 전략: {strategy_name}")
                return

            # 신호 로그 출력
            print(f"[Upbit:{strategy_name}] 신호: {signal['action']} | 사유: {signal.get('reason', 'N/A')}")

            # Record signal for dashboard
            self._record_signal("upbit", signal, strategy_name, indicators)

            # Apply multipliers (mirror backtest scaling behavior)
            if signal.get("action") in {"buy", "sell"}:
                base_fraction = float(signal.get("fraction", 1.0))
                mult = 1.0
                if strategy_name == "v35":
                    mult = self.v35_fraction_mult
                elif strategy_name == "va02":
                    mult = 1.0  # VA02 uses fraction from strategy config (default 0.5)
                elif strategy_name == "sideways_v2":
                    mult = self.sideways_fraction_mult
                elif strategy_name == "h4_conservative":
                    mult = 1.0  # H4 uses 50% from strategy config
                signal["fraction"] = max(0.0, min(1.0, base_fraction * float(mult)))

            if signal['action'] == 'buy' and not self.upbit_position:
                if self.execution_mode == "live" and self._block_new_entries:
                    print("⛔ [Risk] LIVE 신규 진입 차단 (daily loss guard)")
                    return
                # 매수
                cash, btc = self.upbit_account.get_balance()
                frac = clamp_fraction(float(signal.get('fraction', 0.5)), self.risk_config.max_upbit_entry_fraction)
                buy_amount = cash * frac

                if buy_amount >= float(self.risk_config.min_upbit_order_krw):
                    result = self.upbit_account.buy(buy_amount, current_price)

                    if result['success']:
                        self.upbit_position = True
                        self.upbit_active_strategy = strategy_name
                        self.last_upbit_signal = signal

                        tag = "Live" if self.execution_mode == "live" else "Paper"
                        msg = f"🟢 [Upbit {tag}] 매수\n"
                        msg += f"━━━━━━━━━━━━━━━━━━━━\n"
                        msg += f"💰 가격: {current_price:,.0f}원\n"
                        msg += f"📊 수량: {result['executed_volume']:.8f} BTC\n"
                        msg += f"📝 사유: {signal.get('reason', 'N/A')}"

                        print(msg)
                        if self.telegram:
                            self.telegram.send_message(msg)

                        self._record_trade(
                            "upbit",
                            {
                                "timestamp": datetime.now().isoformat(),
                                "type": "buy",
                                "price": float(current_price),
                                "amount": float(buy_amount),
                                "btc_qty": float(result.get("executed_volume", 0.0)),
                                "fee": float(result.get("fee", 0.0)),
                                "reason": signal.get("reason"),
                            },
                        )
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

                    if sell_btc * current_price < float(self.risk_config.min_upbit_order_krw):
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

                        tag = "Live" if self.execution_mode == "live" else "Paper"
                        msg = f"🔴 [Upbit {tag}] 매도\n"
                        msg += f"━━━━━━━━━━━━━━━━━━━━\n"
                        msg += f"💰 가격: {current_price:,.0f}원\n"
                        msg += f"📊 수량: {result['executed_volume']:.8f} BTC\n"
                        pnl = result.get('pnl')
                        pnl_str = f"{float(pnl):+,.0f}원" if pnl is not None else "N/A"
                        msg += f"💵 손익: {pnl_str}\n"
                        msg += f"📝 사유: {signal.get('reason', 'N/A')}"

                        print(msg)
                        if self.telegram:
                            self.telegram.send_message(msg)

                        self._record_trade(
                            "upbit",
                            {
                                "timestamp": datetime.now().isoformat(),
                                "type": "sell",
                                "price": float(current_price),
                                "btc_qty": float(result.get("executed_volume", 0.0)),
                                "amount": float(result.get("total_value", 0.0)),
                                "fee": float(result.get("fee", 0.0)),
                                "pnl": result.get("pnl"),
                                "reason": signal.get("reason"),
                            },
                        )

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
            if self.execution_mode == "live":
                self._consecutive_execution_errors += 1

    def execute_binance_strategy(self, current_price: float, strategy_name: Optional[str]):
        """Binance 전략 실행 (SHORT_V1 또는 H4_SHORT)."""
        if not strategy_name:
            if self.binance_position:
                strategy_name = self.binance_active_strategy or "short_v1"
            else:
                print("⚪ [Binance] 레짐상 진입 스킵")
                return

        if strategy_name not in ("short_v1", "h4_short"):
            print(f"⚠️  알 수 없는 Binance 전략: {strategy_name}")
            return

        # H4 Short 전략 분기
        if strategy_name == "h4_short":
            self._execute_h4_short_strategy(current_price)
            return

        if not self.short_v1_strategy:
            print("⚠️  SHORT_V1 전략 미로드 - Binance 거래 스킵")
            return

        try:
            # 4시간봉 데이터 로드 (Binance DataLoader 사용)
            with DataLoader(exchange="binance") as loader:
                df = loader.load_timeframe('minute240', start_date='2024-01-01')
            df = df.tail(300).reset_index(drop=True)

            if len(df) > 0:
                # 지표 계산
                df = self.short_v1_strategy.add_indicators(df)

                # 현재 자본
                cash, _ = self.binance_account.get_balance()

                # 전략 실행 (generate_signal 메서드 사용)
                signal = self.short_v1_strategy.generate_signal(df, len(df) - 1) or {
                    "action": "hold",
                    "reason": "SHORT_V1_NO_SIGNAL",
                }

                # 신호 로그 출력
                print(f"[Binance] 신호: {signal['action']} | 사유: {signal.get('reason', 'N/A')}")

                if signal['action'] == 'open_short' and not self.binance_position:
                    if self.execution_mode == "live" and self._block_new_entries:
                        print("⛔ [Risk] LIVE 신규 진입 차단 (daily loss guard)")
                        return
                    # 숏 진입
                    base_fraction = float(signal.get("fraction", 0.5))
                    base_fraction = max(0.0, min(1.0, base_fraction))
                    frac = clamp_fraction(base_fraction * float(self.binance_fraction_mult), self.risk_config.max_binance_entry_fraction)
                    position_size = cash * frac
                    leverage = signal.get('leverage', 2)

                    if position_size >= float(self.risk_config.min_binance_order_usdt):
                        result = self.binance_account.open_short(
                            position_size,
                            current_price,
                            leverage
                        )

                        if result['success']:
                            self.binance_position = True
                            self.binance_active_strategy = strategy_name
                            self.last_binance_signal = signal

                            tag = "Live" if self.execution_mode == "live" else "Paper"
                            msg = f"🔻 [Binance {tag}] 숏 진입\n"
                            msg += f"━━━━━━━━━━━━━━━━━━━━\n"
                            msg += f"💰 가격: ${current_price:,.2f}\n"
                            msg += f"📊 수량: {result['executed_qty']:.6f} BTC\n"
                            msg += f"⚡ 레버리지: {leverage}x\n"
                            msg += f"📝 사유: {signal.get('reason', 'N/A')}"

                            print(msg)
                            if self.telegram:
                                self.telegram.send_message(msg)

                            self._record_trade(
                                "binance",
                                {
                                    "timestamp": datetime.now().isoformat(),
                                    "type": "open_short",
                                    "price": float(current_price),
                                    "size": float(result.get("executed_qty", 0.0)),
                                    "margin": float(position_size),
                                    "leverage": int(leverage),
                                    "reason": signal.get("reason"),
                                },
                            )

                elif signal['action'] == 'close_short' and self.binance_position:
                    # 숏 청산
                    result = self.binance_account.close_short(current_price)

                    if result['success']:
                        self.binance_position = False
                        self.binance_active_strategy = None
                        self.last_binance_signal = signal

                        tag = "Live" if self.execution_mode == "live" else "Paper"
                        msg = f"🔺 [Binance {tag}] 숏 청산\n"
                        msg += f"━━━━━━━━━━━━━━━━━━━━\n"
                        msg += f"💰 가격: ${current_price:,.2f}\n"
                        msg += f"💵 손익: ${result['realized_pnl']:+,.2f}\n"
                        msg += f"📝 사유: {signal.get('reason', 'N/A')}"

                        print(msg)
                        if self.telegram:
                            self.telegram.send_message(msg)

                        self._record_trade(
                            "binance",
                            {
                                "timestamp": datetime.now().isoformat(),
                                "type": "close_short",
                                "price": float(current_price),
                                "realized_pnl": float(result.get("realized_pnl", 0.0)),
                                "reason": signal.get("reason"),
                            },
                        )

                elif signal['action'] == 'hold':
                    # 대기 상태 (첫 번째 반복에서만 알림)
                    if self.iteration_count == 1:
                        print(f"⚪ [Binance] 대기 중 - {signal.get('reason', 'N/A')}")
            else:
                print("⚠️  SHORT_V1 데이터 부족 - 전략 실행 스킵")
                if self.telegram and self.iteration_count == 1:
                    self.telegram.send_message("⚠️ [Binance] SHORT_V1 데이터 부족")

        except Exception as e:
            print(f"❌ Binance 전략 실행 오류: {e}")
            import traceback
            traceback.print_exc()
            if self.telegram:
                self.telegram.send_message(f"❌ [Binance] 전략 실행 오류: {e}")
            if self.execution_mode == "live":
                self._consecutive_execution_errors += 1

    def _execute_h4_short_strategy(self, current_price: float):
        """H4 Short 전략 실행 (Binance 숏, 4시간봉).

        과매수 구간에서 숏 진입하는 역발상 전략
        """
        if not self.h4_short_strategy:
            print("⚠️  H4 Short 전략 미로드 - Binance 거래 스킵")
            return

        try:
            import pandas as pd
            import requests

            # Binance 4시간봉 데이터 수집 (최근 500개)
            url = 'https://api.binance.com/api/v3/klines'
            params = {
                'symbol': 'BTCUSDT',
                'interval': '4h',
                'limit': 500
            }
            response = requests.get(url, params=params, timeout=10)
            data = response.json()

            df = pd.DataFrame(data, columns=[
                'timestamp', 'open', 'high', 'low', 'close', 'volume',
                'close_time', 'quote_volume', 'trades', 'taker_buy_base',
                'taker_buy_quote', 'ignore'
            ])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            df['open'] = df['open'].astype(float)
            df['high'] = df['high'].astype(float)
            df['low'] = df['low'].astype(float)
            df['close'] = df['close'].astype(float)
            df['volume'] = df['volume'].astype(float)
            df = df[['timestamp', 'open', 'high', 'low', 'close', 'volume']]

            # 지표 계산
            df = self.h4_short_strategy.add_indicators(df)

            # 신호 생성
            signal = self.h4_short_strategy.generate_signal(df, len(df) - 1) or {'action': 'hold'}

            print(f"[Binance H4] 신호: {signal['action']} | 사유: {signal.get('reason', 'N/A')}")

            # Record signal for dashboard
            indicators = self._extract_indicators(df, ["rsi", "stoch_k", "stoch_d", "close"])
            self._record_signal("binance", signal, "h4_short", indicators)

            cash, _ = self.binance_account.get_balance()

            if signal['action'] == 'short' and not self.binance_position:
                if self.execution_mode == "live" and self._block_new_entries:
                    print("⛔ [Risk] LIVE 신규 진입 차단 (daily loss guard)")
                    return

                # 숏 진입
                base_fraction = float(signal.get("fraction", 0.5))
                frac = clamp_fraction(base_fraction * float(self.binance_fraction_mult), self.risk_config.max_binance_entry_fraction)
                position_size = cash * frac
                leverage = 2  # H4 전략은 낮은 레버리지

                if position_size >= float(self.risk_config.min_binance_order_usdt):
                    result = self.binance_account.open_short(position_size, current_price, leverage)

                    if result['success']:
                        self.binance_position = True
                        self.binance_active_strategy = "h4_short"
                        self.last_binance_signal = signal

                        tag = "Live" if self.execution_mode == "live" else "Paper"
                        msg = f"🔻 [Binance {tag}] H4 숏 진입\n"
                        msg += f"━━━━━━━━━━━━━━━━━━━━\n"
                        msg += f"💰 가격: ${current_price:,.2f}\n"
                        msg += f"📊 수량: {result['executed_qty']:.6f} BTC\n"
                        msg += f"⚡ 레버리지: {leverage}x\n"
                        msg += f"📝 사유: {signal.get('reason', 'N/A')}"

                        print(msg)
                        if self.telegram:
                            self.telegram.send_message(msg)

                        self._record_trade("binance", {
                            "timestamp": datetime.now().isoformat(),
                            "type": "open_short",
                            "strategy": "h4_short",
                            "price": float(current_price),
                            "size": float(result.get("executed_qty", 0.0)),
                            "margin": float(position_size),
                            "leverage": leverage,
                            "reason": signal.get("reason"),
                        })

            elif signal['action'] == 'close_short' and self.binance_position:
                # 숏 청산
                result = self.binance_account.close_short(current_price)

                if result['success']:
                    self.binance_position = False
                    self.binance_active_strategy = None
                    self.last_binance_signal = signal

                    # H4 Short 전략 상태 초기화
                    self.h4_short_strategy._reset_position()

                    tag = "Live" if self.execution_mode == "live" else "Paper"
                    msg = f"🔺 [Binance {tag}] H4 숏 청산\n"
                    msg += f"━━━━━━━━━━━━━━━━━━━━\n"
                    msg += f"💰 가격: ${current_price:,.2f}\n"
                    msg += f"💵 손익: ${result['realized_pnl']:+,.2f}\n"
                    msg += f"📝 사유: {signal.get('reason', 'N/A')}"

                    print(msg)
                    if self.telegram:
                        self.telegram.send_message(msg)

                    self._record_trade("binance", {
                        "timestamp": datetime.now().isoformat(),
                        "type": "close_short",
                        "strategy": "h4_short",
                        "price": float(current_price),
                        "realized_pnl": float(result.get("realized_pnl", 0.0)),
                        "reason": signal.get("reason"),
                    })

        except Exception as e:
            print(f"❌ H4 Short 전략 실행 오류: {e}")
            import traceback
            traceback.print_exc()
            if self.telegram:
                self.telegram.send_message(f"❌ [Binance H4] 전략 실행 오류: {e}")
            if self.execution_mode == "live":
                self._consecutive_execution_errors += 1

    def _execute_hedge_strategy(self, prices: Dict[str, float], premium_info: Dict[str, float]) -> None:
        """Execute delta-neutral hedge strategy using HedgeManager.

        This runs separately from directional strategies (SHORT_V1) and uses
        independent capital allocation for Kimchi Premium mean-reversion.
        """
        if not self.hedge_manager or not self.premium_controller:
            return

        try:
            import asyncio

            # Record premium in PremiumController
            self.premium_controller.record(premium_info)

            # Get Upbit BTC balance for hedge size calculation
            _, upbit_btc = self.upbit_account.get_balance()

            # Evaluate hedge signal (sync wrapper for async method)
            try:
                loop = asyncio.get_event_loop()
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)

            signal = loop.run_until_complete(
                self.hedge_manager.evaluate(
                    upbit_btc_balance=upbit_btc,
                    binance_price=prices['binance'],
                    premium_info=premium_info,
                )
            )

            # Log hedge status
            if signal:
                exposure = self.hedge_manager.get_delta_exposure(upbit_btc)
                print(f"[Hedge] signal={signal.action} | reason={signal.reason}")
                print(f"[Hedge] delta: net={exposure['net_btc']:.6f} BTC | ratio={exposure['hedge_ratio']:.1%}")

                # Send telegram notification on action
                if signal.action in ("open", "close") and self.telegram:
                    emoji = "🔄" if signal.action == "open" else "✅"
                    msg = f"{emoji} [Hedge] {signal.action.upper()}\n"
                    msg += f"━━━━━━━━━━━━━━━━━━━━\n"
                    msg += f"📊 Premium: {premium_info['premium_pct']:+.2f}%\n"
                    msg += f"💰 BTC: {signal.target_btc_qty:.6f}\n"
                    msg += f"📝 사유: {signal.reason}"
                    self.telegram.send_message(msg)

        except Exception as e:
            print(f"⚠️  Hedge 전략 실행 오류: {e}")
            import traceback
            traceback.print_exc()

    def _flush_delta_rebalance(self, prices: Dict[str, float]) -> Optional[Dict[str, Any]]:
        """Flush pending delta rebalance after Alpha execution.

        Called after Alpha strategies execute to check if hedge position
        needs adjustment to maintain delta neutrality.

        Returns:
            Dict with rebalance result, or None if no rebalance needed
        """
        if not hasattr(self, 'delta_rebalancer') or not self.delta_rebalancer:
            return None

        try:
            import asyncio

            try:
                loop = asyncio.get_event_loop()
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)

            result = loop.run_until_complete(
                self.delta_rebalancer.flush_rebalance(prices['binance'])
            )

            return result

        except Exception as e:
            print(f"⚠️  Delta rebalance 오류: {e}")
            import traceback
            traceback.print_exc()
            return None

    def run_iteration(self):
        """1회 반복 실행"""
        if not hasattr(self, "iteration_count"):
            self.iteration_count = 0
        self.iteration_count += 1

        print(f"\n{'='*70}")
        mode_label = "LIVE" if self.execution_mode == "live" else "PAPER"
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {mode_label} 실행 (#{self.iteration_count})")
        print(f"{'='*70}")

        if self.execution_mode == "live":
            if kill_switch_active(self.risk_config.kill_switch_file):
                msg = f"⛔ LIVE 중지: kill-switch 활성화 ({self.risk_config.kill_switch_file})"
                print(msg)
                if self.telegram:
                    self.telegram.send_message(msg)
                return False

        # 현재 가격
        prices = self.get_current_prices()
        print(f"Upbit: {prices['upbit']:,.0f}원 | Binance: ${prices['binance']:,.2f}")

        # Track Kimchi Premium
        premium_info = self.calculate_kimchi_premium(prices)
        self.premium_tracker.record(premium_info)
        premium_stats = self.premium_tracker.get_stats()
        print(f"[Premium] {self.premium_tracker.format_status(premium_stats)}")

        # Check for premium alerts (rate-limited to 1 per hour)
        now = datetime.now()
        if self._last_premium_alert_at is None or (now - self._last_premium_alert_at).total_seconds() >= 3600:
            alert_msg = self.premium_tracker.should_alert(premium_stats)
            if alert_msg and self.telegram:
                self._last_premium_alert_at = now
                self.telegram.send_message(f"🔔 Premium Alert\n{alert_msg}")

        # Live: detect bad price feed (placeholders/zeros)
        if self.execution_mode == "live":
            up = float(prices.get("upbit", 0.0) or 0.0)
            bn = float(prices.get("binance", 0.0) or 0.0)
            looks_like_placeholder = (up >= 90_000_000 and bn >= 90_000)  # matches fallback values
            if up <= 0 or bn <= 0 or looks_like_placeholder:
                self._consecutive_price_failures += 1
                if self._consecutive_price_failures >= int(self.risk_config.recommend_kill_on_price_failures):
                    self._recommend_kill_switch(f"PRICE_FEED_UNRELIABLE (count={self._consecutive_price_failures})")
            else:
                self._consecutive_price_failures = 0

        # Live: recommend kill if repeated execution errors
        if self.execution_mode == "live" and self._consecutive_execution_errors >= int(self.risk_config.recommend_kill_on_consecutive_errors):
            self._recommend_kill_switch(f"CONSECUTIVE_ERRORS (count={self._consecutive_execution_errors})")

        if self.execution_mode == "live":
            d = today()
            if self._day_start_date != d:
                self._day_start_date = d
                upbit_total = float(self.upbit_account.get_total_value(prices['upbit']))
                binance_total_usdt = float(self.binance_account.get_total_value(prices['binance']))
                self._day_start_total_krw = upbit_total + (binance_total_usdt * 1300.0)
                self._block_new_entries = False

            upbit_total = float(self.upbit_account.get_total_value(prices['upbit']))
            binance_total_usdt = float(self.binance_account.get_total_value(prices['binance']))
            current_total_krw = upbit_total + (binance_total_usdt * 1300.0)

            blocked, daily_ret = should_block_new_entries(
                daily_max_loss_pct=self.risk_config.daily_max_loss_pct,
                day_start_total=float(self._day_start_total_krw or 0.0),
                current_total=current_total_krw,
            )
            self._block_new_entries = bool(blocked)
            if blocked and self._last_risk_alert_date != d:
                self._last_risk_alert_date = d
                msg = f"⛔ LIVE 신규 진입 차단: Daily loss guard ({daily_ret:+.2f}%)"
                print(msg)
                if self.telegram:
                    self.telegram.send_message(msg)

            # Recommend kill-switch at a more severe daily loss threshold
            if daily_ret is not None and daily_ret <= -abs(float(self.risk_config.recommend_kill_on_daily_loss_pct)):
                self._recommend_kill_switch(f"DAILY_LOSS_SEVERE ({daily_ret:+.2f}%)")

        decision = self._maybe_update_regime_decision()
        current_regime = decision.regime if decision else "UNKNOWN"

        if decision:
            binance_target = self.binance_active_strategy if self.binance_position else decision.binance_strategy
            print(f"[Router] state={decision.market_state} regime={decision.regime}")
        else:
            binance_target = self.binance_active_strategy if self.binance_position else None
            print(f"[Router] 결정 없음 - 기본값 사용")

        # Execute ALL enabled Upbit strategies concurrently
        self._execute_upbit_strategies_concurrent(prices['upbit'], current_regime, decision)

        # Flush delta rebalance after Alpha execution (if needed)
        if self._hedge_enabled and hasattr(self, 'delta_rebalancer') and self.delta_rebalancer:
            if self.hedge_manager and self.hedge_manager.hedge_position:
                rebalance_result = self._flush_delta_rebalance(prices)
                if rebalance_result and rebalance_result.get('success'):
                    print(f"🔄 Rebalance: {rebalance_result['direction']} {rebalance_result['qty_adjusted']:.4f} BTC")

        # Execute Hedge Strategy first (if enabled) - has priority over SHORT_V1
        if self._hedge_enabled and self.hedge_manager and self.premium_controller:
            self._execute_hedge_strategy(prices, premium_info)

        # Execute Binance strategy (SHORT_V1) only when hedge is NOT active
        # Design doc: "Execute SHORT_V1 only when hedge inactive"
        hedge_is_active = (
            self._hedge_enabled
            and self.hedge_manager
            and self.hedge_manager.hedge_position is not None
        )
        if not hedge_is_active:
            self.execute_binance_strategy(prices['binance'], binance_target)
        else:
            print("[Binance] SHORT_V1 skipped - hedge position active")

        # 상태 출력
        self.print_status(prices)

        # 주기적 상태 알림 (6시간마다)
        self._send_status_notification(prices)

        # Write v2 engine logs (paper + live)
        self._write_v2_engine_logs(prices)

        return True

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

        # Kimchi Premium & Hedge Ratio
        premium_info = self.calculate_kimchi_premium(prices)
        hedge_info = self.calculate_hedge_ratio(prices)

        print(f"\n[Kimchi Premium]")
        print(f"  프리미엄: {premium_info['premium_pct']:+.2f}%")
        print(f"  Upbit: ${premium_info['upbit_usd']:,.2f} | Binance: ${premium_info['binance_usd']:,.2f}")
        print(f"  환율: {premium_info['usd_krw_rate']:,.0f} KRW/USD")

        print(f"\n[Hedge Ratio]")
        adjusted = hedge_info.get('adjusted_target', hedge_info['target'])
        reason = hedge_info.get('adjustment_reason', 'normal')
        if adjusted != hedge_info['target']:
            print(f"  현재: {hedge_info['hedge_ratio']:.1%} (목표: {hedge_info['target']:.0%} → {adjusted:.0%})")
            print(f"  조정: {reason}")
        else:
            print(f"  현재: {hedge_info['hedge_ratio']:.1%} (목표: {hedge_info['target']:.0%})")
        print(f"  범위: {hedge_info['target_min']:.0%} ~ {hedge_info['target_max']:.0%} [{hedge_info['regime']}]")
        if hedge_info['long_exposure_krw'] > 0:
            print(f"  Long: {hedge_info['long_exposure_krw']:,.0f}원 | Short: {hedge_info['short_exposure_krw']:,.0f}원")

        # 합계
        usd_krw_rate = premium_info['usd_krw_rate']
        total_krw = upbit_total + (binance_cash * usd_krw_rate)
        initial_total = self.upbit_account.initial_capital + (self.binance_account.initial_capital * usd_krw_rate)
        total_return_pct = ((total_krw - initial_total) / initial_total) * 100

        print(f"\n[합계]")
        print(f"  총 자산: {total_krw:,.0f}원")
        print(f"  총 수익률: {total_return_pct:+.2f}%")
        print(f"{'─'*70}\n")

    def run_forever(self, interval_minutes: int = 60):
        """무한 루프 실행"""
        mode_label = "LIVE" if self.execution_mode == "live" else "PAPER"
        print(f"\n🚀 {mode_label} 시작 (간격: {interval_minutes}분)\n")

        # 로그 디렉토리 (절대 경로)
        log_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'logs')
        os.makedirs(log_dir, exist_ok=True)

        try:
            while True:
                cont = self.run_iteration()
                if cont is False:
                    break

                # 로그 저장 (절대 경로 사용)
                try:
                    if hasattr(self.upbit_account, "save_log"):
                        self.upbit_account.save_log(os.path.join(log_dir, 'paper_trading_upbit.json'))
                    if hasattr(self.binance_account, "save_log"):
                        self.binance_account.save_log(os.path.join(log_dir, 'paper_trading_binance.json'))
                except Exception as e:
                    print(f"⚠️  로그 저장 실패: {e}")

                # 대기
                print(f"\n⏱️  다음 실행까지 {interval_minutes}분 대기...\n")
                time.sleep(interval_minutes * 60)

        except KeyboardInterrupt:
            mode_label = "LIVE Trading" if self.execution_mode == "live" else "Paper Trading"
            print(f"\n\n{'='*70}")
            print(f"  {mode_label} 중지")
            print(f"{'='*70}\n")

            # 최종 통계
            self.print_final_statistics()

    def print_final_statistics(self):
        """최종 통계 출력"""
        try:
            upbit_stats = self.upbit_account.get_statistics()
            binance_stats = self.binance_account.get_statistics()

            print("\n📊 최종 통계")
            print(f"{'='*70}")

            # Helper for safe formatting
            def safe_pct(val):
                return (val or 0) * 100

            def safe_val(val, default=0):
                return val if val is not None else default

            print(f"\n[Upbit]")
            print(f"  초기 자본: {safe_val(upbit_stats.get('initial_capital'), 0):,.0f}원")
            print(f"  최종 자본: {safe_val(upbit_stats.get('current_cash'), 0):,.0f}원")
            print(f"  총 거래: {safe_val(upbit_stats.get('total_trades'), 0)}회")
            print(f"  승률: {safe_pct(upbit_stats.get('win_rate')):.1f}%")
            print(f"  순손익: {safe_val(upbit_stats.get('net_pnl'), 0):+,.0f}원")
            print(f"  수익률: {safe_val(upbit_stats.get('return_pct'), 0):+.2f}%")

            print(f"\n[Binance]")
            print(f"  초기 자본: ${safe_val(binance_stats.get('initial_capital'), 0):,.2f}")
            print(f"  최종 자본: ${safe_val(binance_stats.get('current_cash'), 0):,.2f}")
            print(f"  총 거래: {safe_val(binance_stats.get('total_trades'), 0)}회")
            print(f"  승률: {safe_pct(binance_stats.get('win_rate')):.1f}%")
            print(f"  순손익: ${safe_val(binance_stats.get('net_pnl'), 0):+,.2f}")
            print(f"  수익률: {safe_val(binance_stats.get('return_pct'), 0):+.2f}%")

            print(f"\n{'='*70}\n")
        except Exception as e:
            print(f"\n⚠️ 통계 출력 오류: {e}\n")


if __name__ == '__main__':
    """실행 - run.py 사용 권장"""
    import argparse

    parser = argparse.ArgumentParser(description='Dual Exchange Engine (paper/live)')
    parser.add_argument('--paper-upbit-capital', type=float, default=10_000_000,
                        help='[Paper 전용] Upbit 시뮬레이션 자본 (KRW, 기본: 10M)')
    parser.add_argument('--paper-binance-capital', type=float, default=10_000,
                        help='[Paper 전용] Binance 시뮬레이션 자본 (USDT, 기본: 10K)')
    parser.add_argument('--mode', choices=['paper', 'live'], default='paper',
                        help='실행 모드 (paper|live, 기본: paper)')
    parser.add_argument('--interval', type=int, default=60,
                        help='실행 간격 (분, 기본: 60)')
    parser.add_argument('--no-telegram', action='store_true',
                        help='텔레그램 알림 비활성화')
    parser.add_argument('--telegram-commands', action='store_true',
                        help='텔레그램 명령어 polling 활성화 (/kill_on 등)')
    parser.add_argument('--candidate-json', type=str, default=None,
                        help='tune_operational_router 결과 JSON 경로 (results[...].candidate 로드)')
    parser.add_argument('--candidate-index', type=int, default=0,
                        help='candidate index (기본: 0)')

    args = parser.parse_args()

    engine = DualPaperTradingEngine(
        paper_upbit_capital=args.paper_upbit_capital,
        paper_binance_capital=args.paper_binance_capital,
        telegram_enabled=not args.no_telegram,
        candidate_json=args.candidate_json,
        candidate_index=args.candidate_index,
        execution_mode=str(args.mode),
        telegram_commands_enabled=bool(args.telegram_commands),
    )

    engine.run_forever(interval_minutes=args.interval)
