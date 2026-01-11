# Binance Futures-Only Refactor Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Remove all Upbit code and consolidate to Binance Futures-only trading with separate capital pools for V35 Long and Short_V1 strategies.

**Architecture:** Two strategies (V35 Long + Short_V1) share price feeds but trade independently with 50/50 capital pools. Global risk manager kills all positions if portfolio MDD exceeds 20%.

**Tech Stack:** Python 3.10+, Redis Streams, Binance Futures API, pytest

---

## Phase 1: Delete Upbit-Only Files

### Task 1.1: Delete Upbit Collector

**Files:**
- Delete: `scripts/collectors/upbit_collector.py`

**Step 1: Delete the file**

```bash
rm scripts/collectors/upbit_collector.py
```

**Step 2: Verify deletion**

```bash
ls scripts/collectors/upbit_collector.py 2>&1 | grep "No such file"
```

Expected: "No such file or directory"

**Step 3: Commit**

```bash
git add -A && git commit -m "chore: delete upbit_collector.py"
```

---

### Task 1.2: Delete Upbit-Only Strategies

**Files:**
- Delete: `trading/strategy/sideways_v1.py`
- Delete: `trading/strategy/sideways_v2.py`
- Delete: `trading/strategy/va02_long.py`

**Step 1: Delete the files**

```bash
rm trading/strategy/sideways_v1.py
rm trading/strategy/sideways_v2.py
rm trading/strategy/va02_long.py
```

**Step 2: Verify deletion**

```bash
ls trading/strategy/sideways_v1.py trading/strategy/sideways_v2.py trading/strategy/va02_long.py 2>&1 | grep -c "No such file"
```

Expected: 3

**Step 3: Commit**

```bash
git add -A && git commit -m "chore: delete Upbit-only strategies (sideways_v1, sideways_v2, va02_long)"
```

---

### Task 1.3: Delete Upbit-Only Strategy Runners

**Files:**
- Delete: `trading/strategy_runners/sideways_v2.py`
- Delete: `trading/strategy_runners/h4.py`

**Step 1: Delete the files**

```bash
rm trading/strategy_runners/sideways_v2.py
rm trading/strategy_runners/h4.py
```

**Step 2: Verify deletion**

```bash
ls trading/strategy_runners/*.py | wc -l
```

Expected: Fewer files than before (check remaining are v35.py, short_v1.py, base.py)

**Step 3: Commit**

```bash
git add -A && git commit -m "chore: delete Upbit-only strategy runners (sideways_v2, h4)"
```

---

### Task 1.4: Delete Upbit Connection Test

**Files:**
- Delete: `tests/test_upbit_connection.py`

**Step 1: Delete the file**

```bash
rm tests/test_upbit_connection.py
```

**Step 2: Commit**

```bash
git add -A && git commit -m "chore: delete test_upbit_connection.py"
```

---

## Phase 2: Remove Exchange.UPBIT from Core Types

### Task 2.1: Update Exchange Enum

**Files:**
- Modify: `core/types.py:12-15`

**Step 1: Read current enum**

```bash
grep -A5 "class Exchange" core/types.py
```

**Step 2: Edit to remove UPBIT**

Change from:
```python
class Exchange(str, Enum):
    """거래소"""
    UPBIT = "upbit"
    BINANCE = "binance"
```

To:
```python
class Exchange(str, Enum):
    """거래소"""
    BINANCE = "binance"
```

**Step 3: Remove upbit_symbol field (line ~220)**

Find and remove:
```python
    upbit_symbol: str = Field(description="Upbit trading pair (e.g., KRW-BTC)")
```

**Step 4: Run tests to find breakages**

```bash
pytest tests/ --ignore=tests/test_web_api.py --ignore=tests/web/ -x 2>&1 | head -50
```

**Step 5: Commit**

```bash
git add core/types.py && git commit -m "refactor: remove Exchange.UPBIT enum and upbit_symbol field"
```

---

## Phase 3: Update Strategy Files

### Task 3.1: Update V35 Long Strategy

**Files:**
- Modify: `trading/strategy/v35_long.py:266`

**Step 1: Find UPBIT reference**

```bash
grep -n "UPBIT" trading/strategy/v35_long.py
```

**Step 2: Change Exchange.UPBIT to Exchange.BINANCE**

Change from:
```python
exchange=Exchange.UPBIT,
```

To:
```python
exchange=Exchange.BINANCE,
```

**Step 3: Update docstrings (remove "Upbit" references)**

Search and update any docstrings mentioning "Upbit" to say "Binance Futures".

**Step 4: Run strategy tests**

```bash
pytest tests/trading/ -k "v35" -v
```

**Step 5: Commit**

```bash
git add trading/strategy/v35_long.py && git commit -m "refactor: update v35_long to use Exchange.BINANCE"
```

---

### Task 3.2: Update V35 Strategy Runner

**Files:**
- Modify: `trading/strategy_runners/v35.py:62,66`

**Step 1: Change exchange property**

Change from:
```python
def exchange(self) -> str:
    return "upbit"
```

To:
```python
def exchange(self) -> str:
    return "binance"
```

**Step 2: Change required_streams**

Change from:
```python
def required_streams(self) -> list:
    return ["market:upbit:prices", "market:regime"]
```

To:
```python
def required_streams(self) -> list:
    return ["market:binance:prices"]
```

**Step 3: Run tests**

```bash
pytest tests/trading/strategy_runners/test_v35.py -v
```

**Step 4: Commit**

```bash
git add trading/strategy_runners/v35.py && git commit -m "refactor: update v35 runner to use binance exchange"
```

---

### Task 3.3: Update Strategy Runner Base

**Files:**
- Modify: `trading/strategy_runners/base.py`

**Step 1: Find Upbit references**

```bash
grep -n "upbit" trading/strategy_runners/base.py
```

**Step 2: Update comments/docstrings**

Change any "upbit or binance" to just "binance".

**Step 3: Commit**

```bash
git add trading/strategy_runners/base.py && git commit -m "docs: remove Upbit references from strategy runner base"
```

---

## Phase 4: Update Infrastructure Files

### Task 4.1: Update Feed Publisher

**Files:**
- Modify: `trading/publishers/feed_publisher.py`

**Step 1: Find Upbit references**

```bash
grep -n "upbit\|UPBIT" trading/publishers/feed_publisher.py
```

**Step 2: Remove Upbit stream references from comments/code**

Update docstrings and any stream name references.

**Step 3: Commit**

```bash
git add trading/publishers/feed_publisher.py && git commit -m "refactor: remove Upbit references from feed_publisher"
```

---

### Task 4.2: Update Data Cache

**Files:**
- Modify: `trading/core/data_cache.py:60`

**Step 1: Find Upbit reference**

```bash
grep -n "upbit" trading/core/data_cache.py
```

**Step 2: Update Literal type**

Change from:
```python
exchange: Literal["upbit", "binance"] = "binance",
```

To:
```python
exchange: Literal["binance"] = "binance",
```

**Step 3: Commit**

```bash
git add trading/core/data_cache.py && git commit -m "refactor: remove upbit option from data_cache"
```

---

### Task 4.3: Update bot.sh

**Files:**
- Modify: `bot.sh:157-158`

**Step 1: Find Upbit references**

```bash
grep -n "upbit\|Upbit" bot.sh
```

**Step 2: Remove Upbit price display section**

Remove lines like:
```bash
if d['prices'].get('upbit', {}).get('price'):
    print(f"   BTC (Upbit):  ₩{d['prices']['upbit']['price']:,.0f}")
```

**Step 3: Test bot.sh status**

```bash
./bot.sh status 2>&1 | head -20
```

**Step 4: Commit**

```bash
git add bot.sh && git commit -m "refactor: remove Upbit price display from bot.sh"
```

---

### Task 4.4: Update .env.example

**Files:**
- Modify: `.env.example`

**Step 1: Find Upbit references**

```bash
grep -n "UPBIT\|upbit" .env.example
```

**Step 2: Remove Upbit API key lines**

Remove:
```bash
# 발급: https://upbit.com/mypage/open_api_management

UPBIT_ACCESS_KEY=your_access_key_here
UPBIT_SECRET_KEY=your_secret_key_here
```

**Step 3: Commit**

```bash
git add .env.example && git commit -m "chore: remove Upbit API keys from .env.example"
```

---

## Phase 5: Fix Remaining Test Files

### Task 5.1: Update test_message_types.py

**Files:**
- Modify: `tests/trading/test_message_types.py`

**Step 1: Find Upbit references**

```bash
grep -n "UPBIT\|upbit" tests/trading/test_message_types.py
```

**Step 2: Change all Exchange.UPBIT to Exchange.BINANCE**

**Step 3: Update expected values in assertions**

Change `"upbit"` to `"binance"` in expected values.

**Step 4: Run tests**

```bash
pytest tests/trading/test_message_types.py -v
```

**Step 5: Commit**

```bash
git add tests/trading/test_message_types.py && git commit -m "test: update test_message_types for Binance-only"
```

---

### Task 5.2: Update Strategy Runner Tests

**Files:**
- Modify: `tests/trading/strategy_runners/test_v35.py`
- Modify: `tests/trading/strategy_runners/test_base.py`

**Step 1: Find Upbit references**

```bash
grep -rn "upbit" tests/trading/strategy_runners/
```

**Step 2: Update all references to binance**

**Step 3: Run tests**

```bash
pytest tests/trading/strategy_runners/ -v
```

**Step 4: Commit**

```bash
git add tests/trading/strategy_runners/ && git commit -m "test: update strategy runner tests for Binance-only"
```

---

### Task 5.3: Update Remaining Test Files

**Files:**
- Modify: `tests/trading/test_metrics.py`
- Modify: `tests/trading/test_phase3_strategies.py`

**Step 1: Find all Upbit references**

```bash
grep -rn "upbit\|UPBIT" tests/trading/test_metrics.py tests/trading/test_phase3_strategies.py
```

**Step 2: Update or delete tests as appropriate**

**Step 3: Run all tests**

```bash
pytest tests/ --ignore=tests/test_web_api.py --ignore=tests/web/ -v
```

**Step 4: Commit**

```bash
git add tests/ && git commit -m "test: update remaining tests for Binance-only"
```

---

## Phase 6: Final Verification

### Task 6.1: Verify No Upbit References Remain

**Step 1: Search entire codebase**

```bash
grep -ri "upbit" --include="*.py" trading/ core/ tests/ | grep -v __pycache__ | wc -l
```

Expected: 0

**Step 2: Search config files**

```bash
grep -ri "upbit" bot.sh .env.example config/ | wc -l
```

Expected: 0

**Step 3: If any remain, fix them**

---

### Task 6.2: Run Full Test Suite

**Step 1: Run all tests**

```bash
pytest tests/ --ignore=tests/test_web_api.py --ignore=tests/web/ -v 2>&1 | tail -20
```

Expected: All tests pass

**Step 2: Document test count**

Record: X passed, Y skipped, 0 failed

---

### Task 6.3: Final Commit and Summary

**Step 1: Create summary commit if needed**

```bash
git status
```

If any uncommitted changes:
```bash
git add -A && git commit -m "chore: final cleanup for Binance-only refactor"
```

**Step 2: Push branch**

```bash
git push -u origin feature/binance-futures-only
```

**Step 3: Verify branch**

```bash
git log --oneline -10
```

---

## Summary

| Phase | Tasks | Description |
|-------|-------|-------------|
| 1 | 1.1-1.4 | Delete Upbit-only files (4 deletes) |
| 2 | 2.1 | Remove Exchange.UPBIT from core/types.py |
| 3 | 3.1-3.3 | Update strategy files to use BINANCE |
| 4 | 4.1-4.4 | Update infrastructure files |
| 5 | 5.1-5.3 | Fix test files |
| 6 | 6.1-6.3 | Final verification |

**Total Tasks:** 14
**Estimated Commits:** 14-16
**Estimated Lines Removed:** ~2,000+
