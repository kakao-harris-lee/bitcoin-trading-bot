#!/usr/bin/env python3
"""
V35 Optimized Strategy - Real-time Trading with AI Analyzer v2
Test Mode: AI 분석만 로그, 거래 영향 없음
"""

import sys
import os
import json
import time
import logging
from datetime import datetime
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pyupbit
from core.data_loader import DataLoader
from strategies.v35_optimized.strategy import V35OptimizedStrategy

# Logging setup
log_dir = Path(__file__).parent.parent.parent / "logs"
log_dir.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(log_dir / 'trading.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class V35Trader:
    """V35 Optimized Strategy Real-time Trader"""
    
    def __init__(self, config_path: str, dry_run: bool = False):
        self.config_path = config_path
        self.dry_run = dry_run
        
        # Load configuration
        with open(config_path, 'r') as f:
            self.config = json.load(f)
        
        # Initialize strategy
        self.strategy = V35OptimizedStrategy(self.config)
        
        # Load API keys from environment
        self.access_key = os.getenv('UPBIT_ACCESS_KEY')
        self.secret_key = os.getenv('UPBIT_SECRET_KEY')
        
        if not self.access_key or not self.secret_key:
            logger.warning("⚠️  Upbit API keys not found - Running in simulation mode")
            self.upbit = None
        else:
            self.upbit = pyupbit.Upbit(self.access_key, self.secret_key)
        
        # Trading state
        self.ticker = "KRW-BTC"
        self.last_action_time = None
        self.min_action_interval = 60  # seconds
        
        # AI Analyzer status
        ai_config = self.config.get('ai_analyzer', {})
        self.ai_enabled = ai_config.get('enabled', False)
        self.ai_test_mode = ai_config.get('test_mode', True)
        
        logger.info("=" * 80)
        logger.info("V35 Optimized Strategy + AI Analyzer v2 Trader Started")
        logger.info("=" * 80)
        logger.info(f"Dry Run: {self.dry_run}")
        logger.info(f"AI Analyzer: {'Enabled' if self.ai_enabled else 'Disabled'}")
        if self.ai_enabled:
            logger.info(f"AI Mode: {'TEST MODE (로그만)' if self.ai_test_mode else 'ACTIVE (거래 영향)'}")
        logger.info("=" * 80)
    
    def get_current_data(self, count=200):
        """Get current market data"""
        try:
            df = pyupbit.get_ohlcv(self.ticker, interval="day", count=count)
            if df is None or df.empty:
                logger.error("Failed to fetch market data")
                return None
            
            df = df.reset_index()
            df.columns = ['timestamp', 'open', 'high', 'low', 'close', 'volume', 'value']
            return df
        except Exception as e:
            logger.error(f"Error fetching data: {e}")
            return None
    
    def get_current_balance(self):
        """Get current balance and position"""
        if not self.upbit:
            return None, 0
        
        try:
            krw = self.upbit.get_balance("KRW")
            btc = self.upbit.get_balance("BTC")
            return krw, btc
        except Exception as e:
            logger.error(f"Error getting balance: {e}")
            return None, 0
    
    def execute_buy(self, fraction: float, reason: str):
        """Execute buy order"""
        if self.dry_run:
            logger.info(f"[DRY RUN] BUY {fraction*100:.1f}% - {reason}")
            return
        
        krw, btc = self.get_current_balance()
        if krw is None:
            logger.error("Cannot execute buy - balance check failed")
            return
        
        buy_amount = krw * fraction
        min_order = 10000  # 10,000 KRW minimum
        
        if buy_amount < min_order:
            logger.warning(f"Buy amount {buy_amount:.0f} KRW < minimum {min_order} KRW")
            return
        
        try:
            result = self.upbit.buy_market_order(self.ticker, buy_amount * 0.9995)  # fee 제외
            logger.info(f"✅ BUY ORDER: {buy_amount:.0f} KRW - {reason}")
            logger.info(f"Order result: {result}")
            self.last_action_time = time.time()
        except Exception as e:
            logger.error(f"Buy order failed: {e}")
    
    def execute_sell(self, fraction: float, reason: str):
        """Execute sell order"""
        if self.dry_run:
            logger.info(f"[DRY RUN] SELL {fraction*100:.1f}% - {reason}")
            return
        
        krw, btc = self.get_current_balance()
        if btc == 0:
            logger.warning("No BTC to sell")
            return
        
        sell_amount = btc * fraction
        
        try:
            result = self.upbit.sell_market_order(self.ticker, sell_amount)
            logger.info(f"✅ SELL ORDER: {sell_amount:.8f} BTC - {reason}")
            logger.info(f"Order result: {result}")
            self.last_action_time = time.time()
        except Exception as e:
            logger.error(f"Sell order failed: {e}")
    
    def run_trading_cycle(self):
        """Execute one trading cycle"""
        # Get market data
        df = self.get_current_data()
        if df is None:
            return
        
        # Get current position
        krw, btc = self.get_current_balance()
        if krw is None:
            return
        
        current_price = df.iloc[-1]['close']
        total_value = krw + (btc * current_price if btc > 0 else 0)
        btc_ratio = (btc * current_price / total_value * 100) if total_value > 0 else 0
        
        logger.info(f"Portfolio: KRW {krw:,.0f} | BTC {btc:.8f} ({btc_ratio:.1f}%) | Total {total_value:,.0f} KRW")
        
        # Execute strategy
        i = len(df) - 1
        decision = self.strategy.execute(df, i)
        
        action = decision.get('action')
        fraction = decision.get('fraction', 0)
        reason = decision.get('reason', 'No reason')
        
        logger.info(f"Strategy Decision: {action.upper()} | Fraction: {fraction:.2%} | Reason: {reason}")
        
        # AI Analysis summary
        if self.ai_enabled:
            ai_summary = self.strategy.get_ai_analysis_summary()
            logger.info(f"AI Analysis: {ai_summary['total_analyses']} total | "
                       f"{ai_summary['high_confidence_count']} high confidence "
                       f"({ai_summary['high_confidence_rate']:.1%}) | "
                       f"avg confidence {ai_summary['avg_confidence']:.3f}")
        
        # Execute action
        if action == 'buy' and fraction > 0:
            # Check minimum interval
            if self.last_action_time and time.time() - self.last_action_time < self.min_action_interval:
                logger.info(f"⏸️  Skipping buy - minimum interval not met")
                return
            
            self.execute_buy(fraction, reason)
            
        elif action == 'sell' and fraction > 0:
            # Check minimum interval
            if self.last_action_time and time.time() - self.last_action_time < self.min_action_interval:
                logger.info(f"⏸️  Skipping sell - minimum interval not met")
                return
            
            self.execute_sell(fraction, reason)
        
        else:
            logger.info("💤 HOLD")
    
    def run(self, interval: int = 60):
        """Main trading loop"""
        logger.info(f"Starting trading loop (interval: {interval}s)")
        
        while True:
            try:
                self.run_trading_cycle()
                
                # Wait for next cycle
                time.sleep(interval)
                
            except KeyboardInterrupt:
                logger.info("Trading stopped by user")
                break
            except Exception as e:
                logger.error(f"Error in trading cycle: {e}", exc_info=True)
                time.sleep(interval)


def main():
    """Main entry point"""
    # Configuration
    config_path = Path(__file__).parent / "config_optimized.json"
    dry_run = os.getenv('DRY_RUN', 'false').lower() == 'true'
    
    # Create trader
    trader = V35Trader(str(config_path), dry_run=dry_run)
    
    # Run
    trader.run(interval=60)  # 1 minute intervals


if __name__ == "__main__":
    main()
