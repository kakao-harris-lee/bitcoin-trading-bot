#!/usr/bin/env python3
"""
Server Health Check Script for Bitcoin Trading Bot
Verifies deployment integrity, Redis connectivity, and configuration.
Usage: python scripts/server_health_check.py
"""
import sys
import os
import json
import asyncio
import importlib
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# ANSI colors
RED = "\033[0;31m"
GREEN = "\033[0;32m"
YELLOW = "\033[1;33m"
NC = "\033[0m"

def print_pass(msg):
    print(f"{GREEN}[PASS] {msg}{NC}")

def print_fail(msg):
    print(f"{RED}[FAIL] {msg}{NC}")
    return False

def print_warn(msg):
    print(f"{YELLOW}[WARN] {msg}{NC}")
    return True

def check_python_version():
    v = sys.version_info
    if v.major < 3 or (v.major == 3 and v.minor < 9):
        return print_fail(f"Python version {v.major}.{v.minor} is too old. Required 3.9+")
    print_pass(f"Python version {v.major}.{v.minor} OK")
    return True

async def check_redis():
    try:
        from trading.streams.redis_streams import RedisStreams
        from dotenv import load_dotenv

        load_dotenv(PROJECT_ROOT / ".env")

        # Try to load config to get redis_url
        redis_url = "redis://localhost:6379"
        try:
             config_path = PROJECT_ROOT / "config/strategies/allocation.json"
             with open(config_path) as f:
                 cfg = json.load(f)
             if "redis_url" in cfg:
                 redis_url = cfg["redis_url"]
        except:
             pass

        print(f"Checking Redis connection to {redis_url}...")
        r = RedisStreams(url=redis_url)
        await r.connect()
        if r._client:
            await r._client.ping()
            await r.disconnect()
            print_pass(f"Redis connection OK")
            return True
        else:
            return print_fail("Redis client failed to initialize")

    except ImportError as e:
        return print_fail(f"redis/trading.streams module not found. Is venv active? Err: {e}")
    except Exception as e:
        return print_fail(f"Redis connection failed: {e}")

def check_imports():
    modules = [
        "trading.engine",
        "trading.strategies.components.strategy_factory",
        "trading.strategies.components.composite_task",
        "trading.strategies.components.state_manager"
    ]
    failed = False
    for mod in modules:
        try:
            importlib.import_module(mod)
            print_pass(f"Import {mod} OK")
        except Exception as e:
            print_fail(f"Import {mod} failed: {e}")
            failed = True
    return not failed

def check_config():
    path = PROJECT_ROOT / "config/strategies/allocation.json"
    if not path.exists():
        return print_fail(f"Config not found at {path}")

    try:
        with open(path) as f:
            data = json.load(f)

        print_pass(f"Config file loaded ({len(data.get('strategies', {}))} strategies configured)")

        if not data.get("use_component_strategies"):
            print_warn("'use_component_strategies' is false/missing. Engine will likely use LEGACY mode.")

        return True
    except json.JSONDecodeError as e:
        return print_fail(f"Config JSON invalid: {e}")

async def main():
    print("=== Bitcoin Trading Bot Server Health Check ===")
    print(f"Project Root: {PROJECT_ROOT}")

    checks = []
    checks.append(check_python_version())
    checks.append(check_config())
    checks.append(check_imports())
    checks.append(await check_redis())

    if all(checks):
        print(f"\n{GREEN}All systems operational. Ready for deployment.{NC}")
        sys.exit(0)
    else:
        print(f"\n{RED}System checks failed. Please resolve issues above.{NC}")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
