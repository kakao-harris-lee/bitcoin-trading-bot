#!/usr/bin/env python3
"""
Bitcoin Trading Bot - Entry Point
비트코인 트레이딩 봇 진입점

Usage:
    python run.py --trend paper  # Paper trading (default)
    python run.py --trend live   # Live trading
    python run.py --help         # Help

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


def format_info_message(engine, trend_mode: str = "live") -> str:
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

    # Build message - New format
    lines = [
        f"📊 *Trading Bot Status*",
        f"{running} | Uptime: {uptime_str}",
        f"",
        f"*Mode*",
        f"  • Trend: *{trend_mode.upper()}*",
    ]

    # === UPBIT ACCOUNT ===
    lines.append("")
    account_label = "LIVE" if trend_mode == "live" else "PAPER"
    lines.append(f"💰 *[{account_label}] Upbit Account*")

    try:
        from trading.adapters.upbit import UpbitTrader
        upbit = UpbitTrader()
        krw_balance, _ = upbit.get_balance()

        # Get all Upbit balances
        all_balances = upbit.upbit.get_balances()
        upbit_positions = {}
        upbit_total = krw_balance

        for bal in all_balances:
            currency = bal.get("currency", "")
            balance = float(bal.get("balance", 0))
            avg_buy_price = float(bal.get("avg_buy_price", 0))

            if currency == "KRW":
                continue

            if balance > 0.0001:
                # Get current price for this asset
                current_price = 0
                if currency in assets:
                    current_price = assets[currency].get("upbit_krw", 0)
                elif currency == "BTC" and "BTC" in assets:
                    current_price = assets["BTC"].get("upbit_krw", 0)

                if current_price > 0:
                    value_krw = balance * current_price
                    upbit_total += value_krw
                    pnl_pct = ((current_price - avg_buy_price) / avg_buy_price * 100) if avg_buy_price > 0 else 0
                    pnl_krw = (current_price - avg_buy_price) * balance if avg_buy_price > 0 else 0
                    upbit_positions[currency] = {
                        "balance": balance,
                        "current_price": current_price,
                        "avg_buy_price": avg_buy_price,
                        "pnl_pct": pnl_pct,
                        "pnl_krw": pnl_krw,
                        "value_krw": value_krw,
                    }

        # Calculate total P&L
        total_pnl_krw = sum(p["pnl_krw"] for p in upbit_positions.values())
        pnl_emoji = "📈" if total_pnl_krw >= 0 else "📉"

        lines.append(f"  Balance: ₩{krw_balance:,.0f}")
        if upbit_positions:
            lines.append(f"  {pnl_emoji} P&L: ₩{total_pnl_krw:+,.0f}")
        lines.append(f"  Total: ₩{upbit_total:,.0f}")

        # Upbit Positions
        if upbit_positions:
            lines.append(f"  *Positions:*")
            for currency, pos in upbit_positions.items():
                pnl_emoji = "📈" if pos["pnl_pct"] >= 0 else "📉"
                lines.append(f"    • {currency}: ₩{pos['current_price']:,.0f} ← ₩{pos['avg_buy_price']:,.0f} [LONG]")
                lines.append(f"      {pnl_emoji} {pos['pnl_pct']:+.2f}% (₩{pos['pnl_krw']:+,.0f})")
        else:
            lines.append(f"  *Positions:* None")

    except Exception as e:
        lines.append(f"  ⚠️ Failed to fetch: {str(e)[:30]}")

    # === BINANCE ACCOUNT ===
    lines.append("")
    lines.append(f"💰 *[{account_label}] Binance Futures*")

    try:
        from trading.adapters.binance import BinanceFuturesTrader
        binance = BinanceFuturesTrader()
        account = binance.get_account_info()
        total_usdt = account.get("total_balance", 0)
        available_usdt = account.get("available_balance", 0)
        unrealized_pnl = account.get("unrealized_pnl", 0)

        pnl_emoji = "📈" if unrealized_pnl >= 0 else "📉"
        lines.append(f"  Balance: ${available_usdt:,.2f}")
        lines.append(f"  {pnl_emoji} Unrealized P&L: ${unrealized_pnl:+,.2f}")
        lines.append(f"  Total: ${total_usdt:,.2f}")

        # Fetch Binance positions
        positions = binance.client.futures_position_information()
        active_positions = []
        for pos in positions:
            pos_amt = float(pos.get("positionAmt", 0))
            if abs(pos_amt) > 0.0001:
                symbol = pos.get("symbol", "")
                entry_price = float(pos.get("entryPrice", 0))
                mark_price = float(pos.get("markPrice", 0))
                unrealized = float(pos.get("unRealizedProfit", 0))
                side = "LONG" if pos_amt > 0 else "SHORT"
                pnl_pct = ((mark_price - entry_price) / entry_price * 100) if entry_price > 0 else 0
                if side == "SHORT":
                    pnl_pct = -pnl_pct
                active_positions.append({
                    "symbol": symbol.replace("USDT", ""),
                    "side": side,
                    "qty": abs(pos_amt),
                    "entry_price": entry_price,
                    "mark_price": mark_price,
                    "pnl_pct": pnl_pct,
                    "pnl_usd": unrealized,
                })

        if active_positions:
            lines.append(f"  *Positions:*")
            for pos in active_positions:
                pnl_emoji = "📈" if pos["pnl_pct"] >= 0 else "📉"
                lines.append(f"    • {pos['symbol']}: ${pos['mark_price']:,.2f} ← ${pos['entry_price']:,.2f} [{pos['side']}]")
                lines.append(f"      {pnl_emoji} {pos['pnl_pct']:+.2f}% (${pos['pnl_usd']:+,.2f})")
        else:
            lines.append(f"  *Positions:* None")

    except Exception as e:
        lines.append(f"  ⚠️ Failed to fetch: {str(e)[:30]}")

    # === MARKET INFORMATION ===
    lines.append("")
    lines.append("📈 *Market Information*")

    # Regime for each asset
    lines.append(f"  *Regime:*")
    for symbol in assets:
        regime = regimes.get(symbol, "UNKNOWN")
        lines.append(f"    {symbol}: {regime}")

    # FX Rate
    lines.append(f"  *FX Rate:*")
    lines.append(f"    USD/KRW: ₩{fx_rate:,.2f}")

    # Prices
    lines.append(f"  *Prices:*")
    for symbol in assets:
        data = assets.get(symbol, {})
        upbit_krw = data.get("upbit_krw", 0)
        binance_usd = data.get("binance_usd", 0)

        if upbit_krw >= 1_000_000:
            upbit_str = f"₩{upbit_krw/1_000_000:.2f}M"
        else:
            upbit_str = f"₩{upbit_krw:,.0f}"

        lines.append(f"    {symbol}: {upbit_str} | ${binance_usd:,.2f}")

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

            def handle_info(cmd_args: str):
                msg = format_info_message(engine, trend_mode)
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
  python run.py --trend paper  # Paper trading (default)
  python run.py --trend live   # Live trading
  python run.py --no-telegram  # Without telegram notifications

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

    print(f"Starting MultiAssetTradingEngine (Mode={args.trend.upper()})...")
    print(f"  Assets from config/strategies/allocation.json")

    asyncio.run(main(args))


if __name__ == "__main__":
    run()
