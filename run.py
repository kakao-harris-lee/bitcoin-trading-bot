#!/usr/bin/env python3
"""
Bitcoin Trading Bot - Entry Point
비트코인 트레이딩 봇 진입점

Usage:
    python run.py --trend paper --premium paper  # Both paper (default)
    python run.py --trend live --premium paper   # Trend live, premium paper
    python run.py --trend live --premium live    # Both live
    python run.py --help                         # Help

Coins are controlled via config/strategies/allocation.json
"""

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

# 프로젝트 루트를 path에 추가
PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    stream=sys.stdout,
)


def format_info_message(engine, trend_mode: str = "live", premium_mode: str = "paper") -> str:
    """Format engine stats for /info command with live exchange balances."""
    from datetime import datetime

    stats = engine.get_stats()

    # Status
    running = "🟢 Running" if stats.get("running") else "🔴 Stopped"

    # Uptime
    started_at = stats.get("started_at")
    if started_at:
        start = datetime.fromisoformat(started_at)
        uptime = datetime.now() - start
        hours, remainder = divmod(int(uptime.total_seconds()), 3600)
        minutes, _ = divmod(remainder, 60)
        uptime_str = f"{hours}h {minutes}m"
    else:
        uptime_str = "N/A"

    # Price info from price_hub.assets
    price_hub = stats.get("price_hub", {})
    assets = price_hub.get("assets", {})
    fx_rate = price_hub.get("fx_rate", 1450)

    # Regime info
    regimes = stats.get("regimes", {})

    # Build message
    trend_emoji = "🔴" if trend_mode == "live" else "⚪"
    premium_emoji = "🔴" if premium_mode == "live" else "⚪"

    lines = [
        f"📊 *Trading Bot Status*",
        f"",
        f"{running} | Uptime: {uptime_str}",
        f"",
        f"*Mode:*",
        f"  {trend_emoji} Trend: {trend_mode.upper()}",
        f"  {premium_emoji} Premium: {premium_mode.upper()}",
    ]

    # === LIVE EXCHANGE BALANCES ===
    lines.append("")
    lines.append("💰 *Live Balances:*")

    # Get BTC price for total value calculation
    btc_price = 0
    if "BTC" in assets:
        btc_price = assets["BTC"].get("upbit_krw", 0)

    # Fetch real Upbit balance
    try:
        from trading.adapters.upbit import UpbitTrader
        upbit = UpbitTrader()
        krw_balance, btc_balance = upbit.get_balance()

        upbit_total = krw_balance + (btc_balance * btc_price)
        lines.append(f"  *Upbit:*")
        lines.append(f"    KRW: ₩{krw_balance:,.0f}")
        if btc_balance > 0.0001:
            lines.append(f"    BTC: {btc_balance:.6f} (₩{btc_balance * btc_price:,.0f})")
        lines.append(f"    Total: ₩{upbit_total:,.0f}")
    except Exception as e:
        lines.append(f"  *Upbit:* ⚠️ 조회 실패")

    # Fetch real Binance balance
    try:
        from trading.adapters.binance import BinanceFuturesTrader
        binance = BinanceFuturesTrader()
        account = binance.get_account_info()
        total_usdt = account.get("total_balance", 0)
        available_usdt = account.get("available_balance", 0)
        unrealized_pnl = account.get("unrealized_pnl", 0)

        lines.append(f"  *Binance Futures:*")
        lines.append(f"    Total: ${total_usdt:,.2f}")
        lines.append(f"    Available: ${available_usdt:,.2f}")
        if abs(unrealized_pnl) > 0.01:
            pnl_emoji = "📈" if unrealized_pnl >= 0 else "📉"
            lines.append(f"    {pnl_emoji} Unrealized: ${unrealized_pnl:+,.2f}")
    except Exception as e:
        lines.append(f"  *Binance:* ⚠️ 조회 실패")

    # === PRICES & REGIMES ===
    lines.append("")
    lines.append(f"📈 *Market (FX ₩{fx_rate:,.0f}):*")

    for symbol in assets:
        data = assets.get(symbol, {})
        upbit_krw = data.get("upbit_krw", 0)
        binance_usd = data.get("binance_usd", 0)
        premium = data.get("premium_pct", 0)
        regime = regimes.get(symbol, "UNKNOWN")

        # Format price based on magnitude
        if upbit_krw >= 1_000_000:
            upbit_str = f"₩{upbit_krw/1_000_000:.1f}M"
        else:
            upbit_str = f"₩{upbit_krw:,.0f}"

        lines.append(f"  *{symbol}* {upbit_str} | ${binance_usd:,.0f}")
        lines.append(f"    김프 {premium:+.2f}% | {regime}")

    # === PAPER TRADING POSITIONS ===
    lines.append("")
    lines.append("💼 *Paper Positions:*")

    has_position = False
    for symbol in assets:
        state = engine.alpha_manager.get_state(symbol)
        if state and state.active and state.quantity > 0:
            has_position = True
            pnl_pct = ((state.current_price - state.entry_price) / state.entry_price * 100) if state.entry_price > 0 else 0
            pnl_emoji = "📈" if pnl_pct >= 0 else "📉"
            lines.append(f"  *{symbol}* {state.quantity:.6f}")
            lines.append(f"    ₩{state.entry_price:,.0f} → ₩{state.current_price:,.0f}")
            lines.append(f"    {pnl_emoji} {pnl_pct:+.2f}%")

    if not has_position:
        lines.append("  포지션 없음")

    # Paper trading stats
    alpha = stats.get("alpha", {})
    if alpha and alpha.get("total_trades", 0) > 0:
        total_trades = alpha.get("total_trades", 0)
        win_rate = alpha.get("win_rate", 0)
        total_pnl = alpha.get("total_pnl_krw", 0)
        lines.append("")
        lines.append("📉 *Paper Stats:*")
        lines.append(f"  거래: {total_trades}회 | 승률: {win_rate:.0f}%")
        lines.append(f"  P&L: ₩{total_pnl:+,.0f}")

    return "\n".join(lines)


async def main(args):
    """MultiAssetTradingEngine 실행."""
    from trading.multi_asset_engine import MultiAssetTradingEngine, MultiAssetEngineConfig

    # Load allocation config
    config_path = PROJECT_ROOT / "config" / "strategies" / "allocation.json"
    with open(config_path) as f:
        allocation_config = json.load(f)

    # Map mode to execution_mode
    execution_mode = "live" if args.trend == "live" else "paper"

    # Determine capital - fetch live balances in live mode
    if execution_mode == "live":
        # Fetch Upbit balance
        try:
            from trading.adapters.upbit import UpbitTrader
            upbit = UpbitTrader()
            krw_balance, _ = upbit.get_balance()
            total_capital_krw = krw_balance
            print(f"Live Upbit balance: ₩{krw_balance:,.0f}")
        except Exception as e:
            print(f"Warning: Failed to fetch Upbit balance: {e}")
            total_capital_krw = float(args.paper_upbit_capital)

        # Fetch Binance balance separately
        try:
            from trading.adapters.binance import BinanceFuturesTrader
            binance = BinanceFuturesTrader()
            account_info = binance.get_account_info()
            usdt_balance = account_info.get('total_balance', 0)
            hedge_capital_usdt = usdt_balance
            print(f"Live Binance balance: ${usdt_balance:,.2f}")
        except Exception as e:
            print(f"Warning: Failed to fetch Binance balance: {e}")
            hedge_capital_usdt = float(args.paper_binance_capital)
    else:
        total_capital_krw = float(args.paper_upbit_capital)
        hedge_capital_usdt = float(args.paper_binance_capital)

    config = MultiAssetEngineConfig(
        execution_mode=execution_mode,
        total_capital_krw=total_capital_krw,
        hedge_capital_usdt=hedge_capital_usdt,
        telegram_enabled=not bool(args.no_telegram),
    )

    engine = MultiAssetTradingEngine(config, allocation_config)

    # Setup telegram command handler if enabled
    cmd_handler = None
    if args.telegram_commands and not args.no_telegram:
        try:
            from trading.notification.telegram_commands import TelegramCommandHandler

            cmd_handler = TelegramCommandHandler(engine._telegram)

            # Register /info command (capture args for mode info)
            trend_mode = args.trend
            premium_mode = args.premium

            def handle_info(cmd_args: str):
                msg = format_info_message(engine, trend_mode, premium_mode)
                engine._telegram.send_message(msg)

            cmd_handler.register_command("info", handle_info)

            # Register /dashboard command
            def handle_dashboard(cmd_args: str):
                import os
                try:
                    import pyotp
                except ImportError:
                    engine._telegram.send_message("pyotp not installed. Run: pip install pyotp")
                    return

                totp_secret = os.getenv("DASHBOARD_TOTP_SECRET")
                if not totp_secret:
                    engine._telegram.send_message("DASHBOARD_TOTP_SECRET not configured in .env")
                    return

                totp = pyotp.TOTP(totp_secret, interval=30)
                current_code = totp.now()

                msg = f"""*Dashboard Access*

URL: `/btc-dashboard`
TOTP Code: `{current_code}`
Valid for: ~30 seconds

_Code expired? Run /dashboard again._"""
                engine._telegram.send_message(msg)

            cmd_handler.register_command("dashboard", handle_dashboard)

            # Start polling
            cmd_handler.start_polling()
            print("✅ Telegram commands enabled: /info /dashboard")

        except Exception as e:
            print(f"⚠️  Telegram commands setup failed: {e}")

    try:
        await engine.start()
    except KeyboardInterrupt:
        print("\nShutting down...")
    finally:
        if cmd_handler:
            cmd_handler.stop_polling()
        await engine.stop()


def run():
    """메인 함수"""
    parser = argparse.ArgumentParser(
        description='Bitcoin Trading Bot (MultiAssetEngine)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python run.py --trend paper --premium paper  # Both paper (default)
  python run.py --trend live --premium paper   # Trend live, premium paper
  python run.py --trend live --premium live    # Both live
  python run.py --no-telegram                  # Without telegram notifications

Coins are controlled via config/strategies/allocation.json
        """
    )

    # 실행 모드 (Dual mode)
    parser.add_argument(
        '--trend',
        choices=['paper', 'live'],
        default='paper',
        help='Trend/directional trading mode (default: paper)'
    )

    parser.add_argument(
        '--premium',
        choices=['paper', 'live'],
        default='paper',
        help='Kimchi premium hedge mode (default: paper)'
    )

    # Legacy --mode argument (maps to --trend)
    parser.add_argument(
        '--mode',
        choices=['paper', 'live'],
        default=None,
        help=argparse.SUPPRESS  # Hidden, for backward compatibility
    )

    # Paper Trading 자본금 설정 (Live 모드에서는 무시됨 - 실제 잔고 조회)
    parser.add_argument(
        '--paper-upbit-capital',
        type=float,
        default=10_000_000,
        help='[Paper only] Upbit simulation capital in KRW (default: 10,000,000)'
    )

    parser.add_argument(
        '--paper-binance-capital',
        type=float,
        default=10_000,
        help='[Paper only] Binance simulation capital in USDT (default: 10,000)'
    )

    # 텔레그램 설정
    parser.add_argument(
        '--no-telegram',
        action='store_true',
        help='Disable telegram notifications'
    )

    parser.add_argument(
        '--telegram-commands',
        action='store_true',
        help='Enable telegram command polling'
    )

    # Legacy compatibility (ignored)
    parser.add_argument('--engine', default='async', help=argparse.SUPPRESS)
    parser.add_argument('--interval', type=int, default=60, help=argparse.SUPPRESS)
    parser.add_argument('--once', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--candidate-json', type=str, default=None, help=argparse.SUPPRESS)
    parser.add_argument('--candidate-index', type=int, default=0, help=argparse.SUPPRESS)
    parser.add_argument('--sideways-policy', type=str, default='sideways_v2', help=argparse.SUPPRESS)
    parser.add_argument('--binance-policy', type=str, default='short_v1', help=argparse.SUPPRESS)
    parser.add_argument('--binance-gate', type=str, default='bear_only', help=argparse.SUPPRESS)

    args = parser.parse_args()

    # Handle legacy --mode argument
    if args.mode is not None:
        args.trend = args.mode
        print(f"Warning: --mode is deprecated. Use --trend instead.")

    print(f"Starting MultiAssetTradingEngine (Trend={args.trend.upper()}, Premium={args.premium.upper()})...")
    print(f"  Assets from config/strategies/allocation.json")

    asyncio.run(main(args))


if __name__ == "__main__":
    run()
