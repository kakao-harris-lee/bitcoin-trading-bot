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


def format_info_message(engine) -> str:
    """Format engine stats for /info command."""
    stats = engine.get_stats()

    # Basic info
    mode = stats.get("execution_mode", "unknown").upper()
    running = "Running" if stats.get("running") else "Stopped"
    iterations = stats.get("iteration_count", 0)
    signals = stats.get("signal_count", 0)

    # Price info
    price_hub = stats.get("price_hub", {})
    prices = price_hub.get("prices", {})

    # Portfolio info
    portfolio = stats.get("portfolio", {})
    positions = portfolio.get("positions", {})

    # Regime info
    regimes = stats.get("regimes", {})

    # Build message
    lines = [
        f"📊 *Trading Bot Status*",
        f"",
        f"*Mode:* {mode} | *Status:* {running}",
        f"*Iterations:* {iterations} | *Signals:* {signals}",
        f"",
        f"💰 *Current Prices:*",
    ]

    # Add prices
    for symbol, data in prices.items():
        if isinstance(data, dict) and "upbit" in data:
            upbit_price = data.get("upbit", 0)
            binance_price = data.get("binance", 0)
            premium = data.get("premium_pct", 0)
            lines.append(f"  {symbol}: ₩{upbit_price:,.0f} | ${binance_price:,.2f} (김프 {premium:.1f}%)")

    lines.append("")
    lines.append("📈 *Market Regimes:*")
    for symbol, regime in regimes.items():
        lines.append(f"  {symbol}: {regime}")

    lines.append("")
    lines.append("💼 *Positions:*")
    if positions:
        for symbol, pos in positions.items():
            if pos.get("quantity", 0) > 0:
                qty = pos.get("quantity", 0)
                entry = pos.get("entry_price", 0)
                pnl = pos.get("unrealized_pnl_pct", 0)
                lines.append(f"  {symbol}: {qty:.6f} @ ₩{entry:,.0f} ({pnl:+.2f}%)")
    else:
        lines.append("  No open positions")

    # Alpha stats
    alpha = stats.get("alpha", {})
    if alpha:
        total_trades = alpha.get("total_trades", 0)
        win_rate = alpha.get("win_rate", 0)
        total_pnl = alpha.get("total_pnl_pct", 0)
        lines.append("")
        lines.append("📉 *Alpha Performance:*")
        lines.append(f"  Trades: {total_trades} | Win Rate: {win_rate:.1f}% | P&L: {total_pnl:+.2f}%")

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

    config = MultiAssetEngineConfig(
        execution_mode=execution_mode,
        total_capital_krw=float(args.paper_upbit_capital),
        hedge_capital_usdt=float(args.paper_binance_capital),
        telegram_enabled=not bool(args.no_telegram),
    )

    engine = MultiAssetTradingEngine(config, allocation_config)

    # Setup telegram command handler if enabled
    cmd_handler = None
    if args.telegram_commands and not args.no_telegram:
        try:
            from trading.notification.telegram_commands import TelegramCommandHandler

            cmd_handler = TelegramCommandHandler(engine._telegram)

            # Register /info command
            def handle_info(cmd_args: str):
                msg = format_info_message(engine)
                engine._telegram.send_message(msg)

            cmd_handler.register_command("info", handle_info)

            # Start polling
            cmd_handler.start_polling()
            print("✅ Telegram commands enabled: /info")

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
