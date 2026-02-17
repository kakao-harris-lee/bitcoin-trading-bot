#!/usr/bin/env python3
"""
Backtest strategy with Risk-Based Position Sizing.

This script demonstrates the new risk-based sizing approach:
- 1% is the maximum LOSS per trade, not the position size
- Position size scales inversely with stop distance
- Generates comparison charts vs buy & hold

Usage:
    python scripts/backtest_risk_based_sizing.py
    python scripts/backtest_risk_based_sizing.py --start 2023-01-01 --end 2026-01-01
"""
import sys
import json
import argparse
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional

import pandas as pd
import numpy as np

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent))

# Force non-interactive matplotlib backend before any imports
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

from core.data_loader import DataLoader
from core.component_adapter import ComponentStrategyAdapter
from core.metrics import (
    calculate_benchmark,
    calculate_sharpe_ratio,
    calculate_max_drawdown,
    calculate_cagr,
    calculate_sortino_ratio,
    calculate_calmar_ratio,
)
from trading.strategies.components import StrategyFactory
from trading.indicators import add_all_indicators
from trading.risk.position_sizer import (
    PositionSizer,
    RiskSizingConfig,
    calculate_stop_price,
    calculate_quantity,
)


class RiskBasedBacktester:
    """Backtester with risk-based position sizing support.

    Key difference from standard backtester:
    - Position size is calculated based on stop distance
    - Risk per trade is fixed (default 1% of equity)
    - This means: tight stop = larger position, wide stop = smaller position
    """

    def __init__(
        self,
        initial_capital: float = 10000.0,
        fee_rate: float = None,  # Auto-detect from market if None
        slippage: float = 0.0002,
        risk_per_trade: float = 0.01,  # 1% risk per trade
        market: str = "spot",
    ):
        self.initial_capital = initial_capital
        self.market = market

        # Auto-detect fee rate based on market
        if fee_rate is None:
            self.fee_rate = 0.001 if market == "spot" else 0.0005
        else:
            self.fee_rate = fee_rate

        self.slippage = slippage
        self.risk_per_trade = risk_per_trade

        # Spot has no leverage
        self.leverage = 1 if market == "spot" else 3

        # State
        self.cash = initial_capital
        self.position = 0.0
        self.position_entry_price = 0.0
        self.position_stop_price = 0.0
        self.trades = []
        self.equity_curve = []

    def reset(self):
        """Reset state for new run."""
        self.cash = self.initial_capital
        self.position = 0.0
        self.position_entry_price = 0.0
        self.position_stop_price = 0.0
        self.trades = []
        self.equity_curve = []
        # Core+Overlay state
        self.core_position = 0.0
        self.core_entry_price = 0.0
        self.core_cash = 0.0
        self.overlay_cash = 0.0

    def run(
        self,
        df: pd.DataFrame,
        adapter: ComponentStrategyAdapter,
        symbol: str = "BTC",
    ) -> Dict[str, Any]:
        """Run backtest with risk-based sizing.

        Args:
            df: DataFrame with OHLCV and indicators
            adapter: ComponentStrategyAdapter for strategy logic
            symbol: Trading symbol

        Returns:
            Results dictionary with metrics and equity curve
        """
        self.reset()
        adapter.symbol = symbol

        # Risk sizer config from adapter's config
        config = adapter.config
        risk_config = RiskSizingConfig(
            risk_per_trade_pct=config.get('risk_per_trade_pct', self.risk_per_trade),
            atr_multiplier=config.get('atr_stop_multiplier', 3.5),
            min_stop_pct=config.get('atr_stop_min_pct', 3.0) / 100,
            max_stop_pct=config.get('atr_stop_max_pct', 5.0) / 100,
            fee_pct=self.fee_rate,
        )
        position_sizer = PositionSizer(risk_config)

        # Get leverage from config
        leverage = config.get('leverage', 3)

        # Core+Overlay setup
        core_hold_pct = config.get('core_hold_pct', 0.0)
        is_core_overlay = core_hold_pct > 0
        core_exit_on_ema200 = config.get('core_exit_on_ema200', False)
        core_reentry_on_ema200 = config.get('core_reentry_on_ema200', True)
        core_drawdown_exit_pct = config.get('core_drawdown_exit_pct', 20.0) / 100
        core_drawdown_reentry_pct = config.get('core_drawdown_reentry_pct', 10.0) / 100
        core_high_water_mark = 0.0
        core_exited_for_drawdown = False
        # Use confirmation period to avoid whipsaws (24 hours = 1 day confirmation)
        core_ema_confirm_hours = 24
        core_below_ema_count = 0
        core_above_ema_count = 0

        if is_core_overlay:
            # Allocate capital: core gets core_hold_pct, overlay gets rest
            first_price = float(df.iloc[0]['close'])
            self.core_cash = self.initial_capital * core_hold_pct
            self.overlay_cash = self.initial_capital * (1 - core_hold_pct)
            self.cash = self.overlay_cash  # Overlay cash for strategy trading

            # Buy core position at start (with fees)
            core_cost = self.core_cash * (1 - self.fee_rate)  # Subtract fees
            self.core_position = core_cost / first_price
            self.core_entry_price = first_price
            core_high_water_mark = first_price
            self.core_cash = 0  # All invested in core

            print(f"\n  Core+Overlay Mode: {core_hold_pct*100:.0f}% core, {(1-core_hold_pct)*100:.0f}% overlay")
            print(f"  Core: {self.core_position:.6f} BTC @ ${first_price:,.0f}")
            print(f"  Overlay capital: ${self.overlay_cash:,.2f}")
            if core_exit_on_ema200:
                print(f"  Core EMA200 filter: ENABLED (exit below, re-enter above)")

        for i in range(len(df)):
            row = df.iloc[i]
            timestamp = row['timestamp']
            price = float(row['close'])
            atr = float(row.get('atr', 0)) or price * 0.02  # Default 2% ATR if missing

            # Current equity (overlay position only)
            if self.position > 0:
                overlay_position_value = self.position * price
            else:
                overlay_position_value = 0.0
            overlay_equity = self.cash + overlay_position_value

            # Core position management (EMA200 filter + drawdown protection)
            if is_core_overlay:
                ema_200 = float(row.get('ema_200', 0))

                # Update core high water mark
                if self.core_position > 0 and price > core_high_water_mark:
                    core_high_water_mark = price

                # Check core drawdown exit
                if self.core_position > 0 and core_high_water_mark > 0:
                    core_drawdown = (core_high_water_mark - price) / core_high_water_mark
                    if core_drawdown >= core_drawdown_exit_pct and not core_exited_for_drawdown:
                        # Exit core position for drawdown protection
                        core_proceeds = self.core_position * price * (1 - self.fee_rate)
                        self.core_cash += core_proceeds
                        self.core_position = 0
                        core_exited_for_drawdown = True

                # Check EMA200 filter for core position (with confirmation to avoid whipsaws)
                if core_exit_on_ema200 and ema_200 > 0:
                    # Track consecutive hours below/above EMA200
                    if price < ema_200:
                        core_below_ema_count += 1
                        core_above_ema_count = 0
                    else:
                        core_above_ema_count += 1
                        core_below_ema_count = 0

                    # Exit core only after confirmed below EMA200 for N hours
                    if self.core_position > 0 and core_below_ema_count >= core_ema_confirm_hours:
                        core_proceeds = self.core_position * price * (1 - self.fee_rate)
                        self.core_cash += core_proceeds
                        self.core_position = 0

                    # Re-enter core only after confirmed above EMA200 for N hours
                    elif self.core_position == 0 and self.core_cash > 0 and core_above_ema_count >= core_ema_confirm_hours:
                        if core_reentry_on_ema200:
                            # Check drawdown recovery
                            if core_exited_for_drawdown:
                                recovery = (price - core_high_water_mark * (1 - core_drawdown_exit_pct)) / (core_high_water_mark * core_drawdown_exit_pct)
                                if recovery >= (core_drawdown_reentry_pct / core_drawdown_exit_pct):
                                    core_exited_for_drawdown = False  # Allow re-entry

                            if not core_exited_for_drawdown:
                                core_buy_cost = self.core_cash * (1 - self.fee_rate)
                                self.core_position = core_buy_cost / price
                                self.core_entry_price = price
                                core_high_water_mark = price  # Reset HWM
                                self.core_cash = 0

            # Core position value (if core+overlay mode)
            core_value = self.core_position * price if is_core_overlay else 0.0
            core_cash_value = self.core_cash if is_core_overlay else 0.0

            # Total equity (for reporting)
            current_equity = overlay_equity + core_value + core_cash_value

            # Update adapter's equity tracking for drawdown protection (overlay only)
            adapter.update_equity(overlay_equity)

            # Get strategy signal
            signal = adapter(df, i, {})
            action = signal.get('action', 'hold')
            reason = signal.get('reason', '')

            if action == 'buy' and self.position == 0:
                # Calculate position size using risk-based sizing
                stop_price = calculate_stop_price(
                    entry_price=price,
                    atr=atr,
                    atr_multiplier=risk_config.atr_multiplier,
                    min_stop_pct=risk_config.min_stop_pct,
                    max_stop_pct=risk_config.max_stop_pct,
                    direction='long',
                )

                sizing_result = calculate_quantity(
                    equity=current_equity,
                    entry_price=price,
                    stop_price=stop_price,
                    symbol=symbol,
                    risk_pct=risk_config.risk_per_trade_pct,
                    leverage=leverage,
                    fee_pct=risk_config.fee_pct,
                )

                if sizing_result.quantity > 0:
                    # Apply slippage
                    exec_price = price * (1 + self.slippage)
                    qty = sizing_result.quantity
                    cost = qty * exec_price * (1 + self.fee_rate)

                    if cost <= self.cash:
                        self.cash -= cost
                        self.position = qty
                        self.position_entry_price = exec_price
                        self.position_stop_price = stop_price

                        self.trades.append({
                            'entry_time': timestamp,
                            'entry_price': exec_price,
                            'stop_price': stop_price,
                            'quantity': qty,
                            'risk_amount': sizing_result.risk_amount,
                            'stop_distance_pct': sizing_result.stop_distance_pct,
                            'reason': reason,
                        })

            elif action == 'sell' and self.position > 0:
                # Exit position
                fraction = signal.get('fraction', 1.0)
                sell_qty = self.position * fraction

                # Apply slippage
                exec_price = price * (1 - self.slippage)
                proceeds = sell_qty * exec_price * (1 - self.fee_rate)

                self.cash += proceeds

                # Update trade record
                if self.trades:
                    trade = self.trades[-1]
                    if 'exit_time' not in trade:
                        trade['exit_time'] = timestamp
                        trade['exit_price'] = exec_price
                        trade['exit_qty'] = sell_qty
                        pnl = (exec_price - trade['entry_price']) * sell_qty
                        pnl_pct = ((exec_price - trade['entry_price']) / trade['entry_price']) * 100
                        trade['pnl'] = pnl
                        trade['pnl_pct'] = pnl_pct
                        trade['exit_reason'] = reason

                if fraction >= 1.0:
                    self.position = 0
                    self.position_entry_price = 0
                    self.position_stop_price = 0
                else:
                    self.position -= sell_qty

            elif action == 'open_short':
                # Short position (if supported)
                pass  # Skip shorts for this long-only strategy

            elif action == 'close_short':
                pass  # Skip

            # Record equity curve (including core position for core+overlay mode)
            overlay_pos_value = self.position * price if self.position > 0 else 0.0
            core_pos_value = self.core_position * price if is_core_overlay else 0.0
            core_cash_val = self.core_cash if is_core_overlay else 0.0
            total_equity = self.cash + overlay_pos_value + core_pos_value + core_cash_val

            self.equity_curve.append({
                'timestamp': timestamp,
                'cash': self.cash,
                'position_value': overlay_pos_value + core_pos_value,
                'total_equity': total_equity,
                'position': self.position,
                'core_position': self.core_position if is_core_overlay else 0.0,
                'core_value': core_pos_value,
                'core_cash': core_cash_val,
                'overlay_value': overlay_pos_value,
                'price': price,
            })

        # Close any remaining position at final price
        if self.position > 0:
            last_row = df.iloc[-1]
            last_price = float(last_row['close'])
            exec_price = last_price * (1 - self.slippage)
            proceeds = self.position * exec_price * (1 - self.fee_rate)
            self.cash += proceeds

            if self.trades:
                trade = self.trades[-1]
                if 'exit_time' not in trade:
                    trade['exit_time'] = last_row['timestamp']
                    trade['exit_price'] = exec_price
                    trade['exit_qty'] = self.position
                    pnl = (exec_price - trade['entry_price']) * self.position
                    pnl_pct = ((exec_price - trade['entry_price']) / trade['entry_price']) * 100
                    trade['pnl'] = pnl
                    trade['pnl_pct'] = pnl_pct
                    trade['exit_reason'] = 'END_OF_DATA'

            self.position = 0

        return self._generate_results(df)

    def _generate_results(self, df: pd.DataFrame) -> Dict[str, Any]:
        """Generate results dictionary."""
        # Final equity includes core position value (sold at final price) and core cash
        final_price = float(df.iloc[-1]['close'])
        core_final_value = self.core_position * final_price if self.core_position > 0 else 0.0
        final_equity = self.cash + core_final_value + self.core_cash
        total_return = ((final_equity - self.initial_capital) / self.initial_capital) * 100

        equity_df = pd.DataFrame(self.equity_curve)

        # Calculate risk metrics
        sharpe = calculate_sharpe_ratio(equity_df) if not equity_df.empty else 0.0
        mdd = calculate_max_drawdown(equity_df) if not equity_df.empty else 0.0

        # Trade statistics
        closed_trades = [t for t in self.trades if 'exit_time' in t]

        if not closed_trades:
            return {
                'initial_capital': self.initial_capital,
                'final_capital': final_equity,
                'total_return': total_return,
                'total_trades': 0,
                'winning_trades': 0,
                'losing_trades': 0,
                'win_rate': 0.0,
                'sharpe_ratio': sharpe,
                'max_drawdown_pct': mdd,
                'profit_factor': 0.0,
                'avg_risk_per_trade': 0.0,
                'equity_curve': equity_df,
                'trades': closed_trades,
            }

        winning_trades = [t for t in closed_trades if t.get('pnl', 0) > 0]
        losing_trades = [t for t in closed_trades if t.get('pnl', 0) <= 0]

        win_rate = len(winning_trades) / len(closed_trades) if closed_trades else 0

        gross_profit = sum(t['pnl'] for t in winning_trades) if winning_trades else 0
        gross_loss = abs(sum(t['pnl'] for t in losing_trades)) if losing_trades else 0
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0

        avg_risk = np.mean([t.get('risk_amount', 0) for t in closed_trades]) if closed_trades else 0
        avg_stop_dist = np.mean([t.get('stop_distance_pct', 0) for t in closed_trades]) if closed_trades else 0

        return {
            'initial_capital': self.initial_capital,
            'final_capital': final_equity,
            'total_return': total_return,
            'total_trades': len(closed_trades),
            'winning_trades': len(winning_trades),
            'losing_trades': len(losing_trades),
            'win_rate': win_rate,
            'sharpe_ratio': sharpe,
            'max_drawdown_pct': mdd,
            'profit_factor': profit_factor,
            'avg_risk_per_trade': avg_risk,
            'avg_stop_distance_pct': avg_stop_dist,
            'equity_curve': equity_df,
            'trades': closed_trades,
        }


def create_comparison_chart(
    results: Dict[str, Any],
    df: pd.DataFrame,
    initial_capital: float,
    output_path: str,
    title: str = "Risk-Based Sizing vs Buy & Hold",
) -> str:
    """Create dual-axis comparison chart.

    Args:
        results: Backtest results
        df: Original price DataFrame
        initial_capital: Initial capital
        output_path: Output file path
        title: Chart title

    Returns:
        Path to saved chart
    """
    fig, ax1 = plt.subplots(figsize=(14, 8))

    equity_df = results['equity_curve']

    # Strategy equity (left axis)
    timestamps = pd.to_datetime(equity_df['timestamp'])
    equity_values = equity_df['total_equity']

    strategy_return = results['total_return']
    line1 = ax1.plot(
        timestamps,
        equity_values,
        color='#2563eb',  # Blue
        linewidth=1.5,
        label=f"Strategy ({strategy_return:+.1f}%)",
    )
    ax1.set_xlabel('Date')
    ax1.set_ylabel('Strategy Equity ($)', color='#2563eb')
    ax1.tick_params(axis='y', labelcolor='#2563eb')

    # Buy & Hold equity (right axis)
    ax2 = ax1.twinx()

    # Calculate benchmark
    benchmark_curve, benchmark_return = calculate_benchmark(df, initial_capital, 'close')

    # Align timestamps
    bench_timestamps = pd.to_datetime(df['timestamp'])

    line2 = ax2.plot(
        bench_timestamps,
        benchmark_curve.values,
        color='#dc2626',  # Red
        linewidth=1.5,
        linestyle='--',
        label=f"Buy & Hold ({benchmark_return:+.1f}%)",
    )
    ax2.set_ylabel('Benchmark Equity ($)', color='#dc2626')
    ax2.tick_params(axis='y', labelcolor='#dc2626')

    # Format x-axis
    ax1.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
    ax1.xaxis.set_major_locator(mdates.MonthLocator(interval=3))
    plt.xticks(rotation=45)

    # Grid
    ax1.grid(True, alpha=0.3)

    # Combined legend
    lines = line1 + line2
    labels = [l.get_label() for l in lines]
    ax1.legend(lines, labels, loc='upper left')

    # Title with metrics
    mdd = results['max_drawdown_pct']
    sharpe = results['sharpe_ratio']
    trades = results['total_trades']
    win_rate = results['win_rate'] * 100

    title_with_metrics = (
        f"{title}\n"
        f"MDD: {mdd:.1f}% | Sharpe: {sharpe:.2f} | "
        f"Trades: {trades} | Win Rate: {win_rate:.1f}%"
    )
    plt.title(title_with_metrics, fontsize=12)

    fig.tight_layout()

    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    plt.close(fig)

    return output_path


def create_drawdown_chart(
    results: Dict[str, Any],
    output_path: str,
) -> str:
    """Create drawdown chart.

    Args:
        results: Backtest results
        output_path: Output file path

    Returns:
        Path to saved chart
    """
    fig, ax = plt.subplots(figsize=(14, 5))

    equity_df = results['equity_curve']
    timestamps = pd.to_datetime(equity_df['timestamp'])
    equity = equity_df['total_equity'].values

    # Calculate running drawdown
    peak = np.maximum.accumulate(equity)
    drawdown = (peak - equity) / peak * 100

    ax.fill_between(timestamps, 0, -drawdown, color='#dc2626', alpha=0.3)
    ax.plot(timestamps, -drawdown, color='#dc2626', linewidth=1)

    ax.set_xlabel('Date')
    ax.set_ylabel('Drawdown (%)')
    ax.set_title(f"Drawdown (Max: {results['max_drawdown_pct']:.1f}%)")

    ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=3))
    plt.xticks(rotation=45)

    ax.grid(True, alpha=0.3)
    ax.axhline(y=-10, color='orange', linestyle='--', alpha=0.5, label='10% DD')
    ax.axhline(y=-20, color='red', linestyle='--', alpha=0.5, label='20% DD')
    ax.legend()

    fig.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    plt.close(fig)

    return output_path


def create_judgment_chart(
    results: Dict[str, Any],
    df: pd.DataFrame,
    initial_capital: float,
    output_path: str,
) -> str:
    """Create 4-panel judgment chart.

    Panels:
    1. Equity curve vs Buy & Hold benchmark
    2. Drawdown comparison
    3. Trade distribution histogram
    4. Summary statistics

    Args:
        results: Backtest results
        df: Original price DataFrame
        initial_capital: Initial capital
        output_path: Output file path

    Returns:
        Path to saved chart
    """
    fig, axes = plt.subplots(2, 2, figsize=(16, 12))

    equity_df = results['equity_curve']
    timestamps = pd.to_datetime(equity_df['timestamp'])

    # Panel 1: Equity vs Benchmark
    ax1 = axes[0, 0]
    benchmark_curve, benchmark_return = calculate_benchmark(df, initial_capital, 'close')
    bench_timestamps = pd.to_datetime(df['timestamp'])

    ax1.plot(timestamps, equity_df['total_equity'], label='Strategy', color='#2563eb', linewidth=1.5)
    ax1.plot(bench_timestamps, benchmark_curve.values, label='Buy & Hold', color='#dc2626', alpha=0.7, linewidth=1.5, linestyle='--')
    ax1.set_title('Equity Curve vs Benchmark')
    ax1.legend()
    ax1.set_ylabel('Equity ($)')
    ax1.grid(True, alpha=0.3)
    ax1.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
    ax1.xaxis.set_major_locator(mdates.MonthLocator(interval=3))
    plt.setp(ax1.xaxis.get_majorticklabels(), rotation=45)

    # Panel 2: Drawdown comparison
    ax2 = axes[0, 1]
    equity = equity_df['total_equity'].values
    peak = np.maximum.accumulate(equity)
    drawdown = (peak - equity) / peak * 100

    ax2.fill_between(timestamps, 0, -drawdown, alpha=0.5, color='#dc2626', label='Strategy DD')
    ax2.set_title('Drawdown Analysis')
    ax2.set_ylabel('Drawdown (%)')
    ax2.legend()
    ax2.grid(True, alpha=0.3)
    ax2.axhline(y=-10, color='orange', linestyle='--', alpha=0.5)
    ax2.axhline(y=-20, color='red', linestyle='--', alpha=0.5)
    ax2.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
    ax2.xaxis.set_major_locator(mdates.MonthLocator(interval=3))
    plt.setp(ax2.xaxis.get_majorticklabels(), rotation=45)

    # Panel 3: Trade distribution
    ax3 = axes[1, 0]
    if results['trades']:
        pnl_values = [t.get('pnl_pct', 0) for t in results['trades']]
        ax3.hist(pnl_values, bins=30, edgecolor='black', alpha=0.7, color='#2563eb')
        ax3.axvline(x=0, color='red', linestyle='--', linewidth=2)
    ax3.set_title('Trade P&L Distribution')
    ax3.set_xlabel('P&L (%)')
    ax3.set_ylabel('Frequency')
    ax3.grid(True, alpha=0.3)

    # Panel 4: Summary stats
    ax4 = axes[1, 1]
    ax4.axis('off')

    stats_text = f"""
    Total Return:       {results['total_return']:.2f}%
    Benchmark (B&H):    {benchmark_return:.2f}%
    Alpha:              {results['total_return'] - benchmark_return:.2f}%

    Max Drawdown:       {results['max_drawdown_pct']:.2f}%
    Win Rate:           {results['win_rate']*100:.1f}%
    Total Trades:       {results['total_trades']}

    Sharpe Ratio:       {results.get('sharpe_ratio', 0):.2f}
    Profit Factor:      {results.get('profit_factor', 0):.2f}
    """

    ax4.text(0.1, 0.5, stats_text, fontsize=14, family='monospace',
             verticalalignment='center')
    ax4.set_title('Summary Statistics', fontsize=14, fontweight='bold')

    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    plt.close(fig)

    return output_path


def print_judgment_summary(results: Dict[str, Any], benchmark_return: float):
    """Print detailed judgment metrics."""
    print("\n" + "="*60)
    print("              JUDGMENT METRICS SUMMARY")
    print("="*60)
    print(f"Strategy Return:     {results['total_return']:.2f}%")
    print(f"Benchmark (B&H):     {benchmark_return:.2f}%")
    print(f"Outperformance:      {results['total_return'] - benchmark_return:.2f}%")
    print("-"*60)
    print(f"Max Drawdown:        {results['max_drawdown_pct']:.2f}%")
    print(f"Win Rate:            {results['win_rate']*100:.1f}%")
    print(f"Sharpe Ratio:        {results.get('sharpe_ratio', 0):.2f}")
    print(f"Profit Factor:       {results.get('profit_factor', 0):.2f}")
    print("="*60)


def print_results(results: Dict[str, Any], strategy_name: str):
    """Print formatted results."""
    print("\n" + "="*60)
    print(f"BACKTEST RESULTS: {strategy_name}")
    print("="*60)
    print(f"Initial Capital:    ${results['initial_capital']:,.2f}")
    print(f"Final Capital:      ${results['final_capital']:,.2f}")
    print(f"Total Return:       {results['total_return']:+.2f}%")
    print("-"*60)
    print(f"Total Trades:       {results['total_trades']}")
    print(f"Winning Trades:     {results['winning_trades']}")
    print(f"Losing Trades:      {results['losing_trades']}")
    print(f"Win Rate:           {results['win_rate']*100:.1f}%")
    print("-"*60)
    print(f"Sharpe Ratio:       {results['sharpe_ratio']:.2f}")
    print(f"Max Drawdown:       {results['max_drawdown_pct']:.2f}%")
    print(f"Profit Factor:      {results['profit_factor']:.2f}")
    print("-"*60)
    print(f"Avg Risk/Trade:     ${results['avg_risk_per_trade']:.2f}")
    print(f"Avg Stop Distance:  {results.get('avg_stop_distance_pct', 0):.2f}%")
    print("="*60)


def main():
    parser = argparse.ArgumentParser(description='Backtest strategy with risk-based sizing')
    parser.add_argument('--start', type=str, default='2023-01-01', help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end', type=str, default=None, help='End date (YYYY-MM-DD)')
    parser.add_argument('--symbol', type=str, default='BTC', help='Symbol to backtest')
    parser.add_argument('--capital', type=float, default=10000.0, help='Initial capital')
    parser.add_argument('--output', type=str, default='outputs', help='Output directory')
    parser.add_argument('--strategy', type=str, default='mlp_direction_btc', help='Strategy name from allocation.json')
    args = parser.parse_args()

    # Create output directory
    output_dir = Path(args.output)
    output_dir.mkdir(exist_ok=True)

    # Load data
    print(f"Loading {args.symbol} data from {args.start}...")
    loader = DataLoader()

    if not loader.db_path.exists():
        print(f"ERROR: Database not found at {loader.db_path}")
        return

    df = loader.load_timeframe(
        timeframe='minute60',
        start_date=args.start,
        end_date=args.end,
    )

    if df.empty:
        print("No data found!")
        return

    print(f"Loaded {len(df)} rows ({df['timestamp'].min()} to {df['timestamp'].max()})")

    # Add indicators
    print("Calculating indicators...")
    df = add_all_indicators(df)

    # Drop rows with NaN indicators
    original_len = len(df)
    df = df.dropna(subset=['mfi', 'adx', 'atr', 'ema_200']).reset_index(drop=True)
    print(f"After dropping NaN: {len(df)} rows (dropped {original_len - len(df)})")

    # Load strategy config
    strategy_name = args.strategy

    print(f"\nLoading {strategy_name} config...")
    config_path = Path(__file__).parent.parent / "config" / "strategies" / "allocation.json"
    with open(config_path) as f:
        allocation = json.load(f)

    config = allocation['strategies'].get(strategy_name, {})

    # Get market from config
    market = config.get("market", "spot")
    print(f"  market: {market}")

    # Override with risk-based sizing parameters for testing
    config['risk_based_sizing'] = True
    config['risk_per_trade_pct'] = 0.01
    config['atr_stop_multiplier'] = config.get('atr_stop_multiplier', 4.0)
    config['atr_stop_min_pct'] = config.get('atr_stop_min_pct', 6.0)
    config['atr_stop_max_pct'] = config.get('atr_stop_max_pct', 15.0)
    # Keep filters as configured in growth config (relaxed)
    # use_breakout_filter: false is already set in growth config
    print(f"  risk_per_trade_pct: {config.get('risk_per_trade_pct', 0.01)}")
    print(f"  atr_stop_multiplier: {config.get('atr_stop_multiplier', 3.5)}")
    print(f"  atr_stop_min_pct: {config.get('atr_stop_min_pct', 3.0)}%")
    print(f"  atr_stop_max_pct: {config.get('atr_stop_max_pct', 5.0)}%")

    # Create strategy adapter
    print("\nInitializing strategy...")
    factory = StrategyFactory(redis=None)

    # Use the requested strategy with allocation.json config
    adapter = ComponentStrategyAdapter(factory, strategy_name, config)

    # Pre-compute RF predictions if enabled
    # NOTE: Now optimized with vectorized scaling (~2.5 min for 3 years)
    # Run backtest
    print("\nRunning backtest with risk-based sizing...")
    backtester = RiskBasedBacktester(
        initial_capital=args.capital,
        fee_rate=0.001 if market == "spot" else 0.0005,
        slippage=0.0002,  # 0.02%
        risk_per_trade=config.get('risk_per_trade_pct', 0.01),
        market=market,
    )

    results = backtester.run(df, adapter, symbol=args.symbol)

    # Print results
    print_results(results, f'{strategy_name} (Risk-Based Sizing)')

    # Calculate and print benchmark
    benchmark_curve, benchmark_return = calculate_benchmark(df, args.capital, 'close')

    # Print judgment summary
    print_judgment_summary(results, benchmark_return)

    # Generate charts
    print("\nGenerating charts...")

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

    # Main comparison chart
    chart_path = output_dir / f"backtest_{strategy_name}_risk_sizing_{timestamp}.png"
    create_comparison_chart(
        results,
        df,
        args.capital,
        str(chart_path),
        title=f"{strategy_name} Risk-Based Sizing ({args.symbol})",
    )
    print(f"  Main chart: {chart_path}")

    # Drawdown chart
    dd_chart_path = output_dir / f"backtest_{strategy_name}_drawdown_{timestamp}.png"
    create_drawdown_chart(results, str(dd_chart_path))
    print(f"  Drawdown chart: {dd_chart_path}")

    # 4-panel judgment chart
    judgment_chart_path = output_dir / f"backtest_{strategy_name}_judgment_{timestamp}.png"
    create_judgment_chart(results, df, args.capital, str(judgment_chart_path))
    print(f"  Judgment chart: {judgment_chart_path}")

    # Print sample trades
    if results['trades']:
        print("\nSample Trades (last 5):")
        print("-" * 80)
        for trade in results['trades'][-5:]:
            entry_time = trade['entry_time']
            if hasattr(entry_time, 'strftime'):
                entry_time = entry_time.strftime('%Y-%m-%d')
            exit_time = trade.get('exit_time', 'OPEN')
            if hasattr(exit_time, 'strftime'):
                exit_time = exit_time.strftime('%Y-%m-%d')

            print(
                f"  {entry_time} -> {exit_time}: "
                f"Entry=${trade['entry_price']:.2f}, "
                f"Stop=${trade['stop_price']:.2f} ({trade['stop_distance_pct']:.1f}%), "
                f"Risk=${trade['risk_amount']:.2f}, "
                f"PnL={trade.get('pnl_pct', 0):+.1f}%"
            )

    print("\nDone!")


if __name__ == "__main__":
    main()
