# Architecture Review: Bitcoin Trading Bot

**Date:** 2026-01-18
**Reviewer:** Claude (Architecture Expert)
**Version:** 1.1 (Updated for Component Architecture)

---

## Executive Summary

This document provides an architecture review of the Bitcoin Trading Bot project. The system has evolved into a robust **Component-based Architecture**, utilizing the Factory pattern to dynamically assemble strategies from modular entry and exit components.

**Overall Rating: A** (Modern, modular, and highly testable)

---

## System Overview

The trading bot consists of modular systems coordinated by `MultiAssetTradingEngine`:

1. **Strategy Factory** - Dynamically assembles strategies
2. **Composite Tasks** - Validates persistent state and runs component logic
3. **RegimeRouter** - Market state oracle (read-only reference)
4. **MultiAssetTradingEngine** - Orchestrates feeds, strategies, and execution

---

## Architecture Diagram

```
                          ┌─────────────────────┐
                          │    RegimeRouter     │
                          │      (Oracle)       │
                          └──────────┬──────────┘
                                     │
                    publishes regime │ (BULL/SIDEWAYS/BEAR)
                                     │
              ┌──────────────────────┼──────────────────────┐
              │                      │                      │
              ▼                      ▼                      ▼
   ┌──────────────────────────────────────────────────────────────────┐
   │                    CompositeStrategyTask                         │
   │  (Manages State, Persistence, Redis I/O, Error Handling)         │
   │                                                                  │
   │    ┌───────────────┐                 ┌───────────────┐           │
   │    │ IEntryStrategy│                 │ IExitStrategy │           │
   │    │ (Stateless)   │                 │ (Stateful)    │           │
   │    └───────┬───────┘                 └───────┬───────┘           │
   │            │                                 │                   │
   │      Checks Entry                      Checks Exit               │
   │            │                                 │                   │
   └────────────┼─────────────────────────────────┼───────────────────┘
                │                                 │
                ▼                                 ▼
        ┌──────────────────────┐       ┌──────────────────────┐
        │ strategy_factory.py  │       │     Redis State      │
        │ (Assembly Logic)     │       │ (positions/stops)    │
        └──────────────────────┘       └──────────────────────┘
```

---

## Component Analysis

### 1. Strategy Factory & Components

**Location:** `trading/strategies/components/`

**Role:** Replaces monolithic strategy classes with composable parts.

- **Factory (`StrategyFactory`)**: Reads `allocation.json` and assembles `CompositeStrategyTask` instances.
- **Entry Components**: Pure logic, return signals (e.g., `V35EntryStrategy`).
- **Exit Components**: Manage position state, trailing stops (e.g., `V35TrailingExitStrategy`, `ExperimentalExitStrategy`).

**Key Characteristics:**

- **Mix & Match**: Can combine `V35Entry` with `ExperimentalExit`.
- **Persistence**: Handled generically by `CompositeStrategyTask` via `StateManager`.
- **Testability**: Components are smaller and easier to unit test.

**Design Rating: A+**

- Excellent separation of concerns (Signal Generation vs. Position Management).
- Eliminates code duplication.

### 2. RegimeRouter (Market State Oracle)

**Location:** `trading/strategy/regime_router.py`

**Role:** Classifies market state using MFI and ADX indicators. Provides read-only reference information to strategies.

**Design Rating: A**

- Correctly positioned as an oracle, not a controller.

---

### 3. MultiAssetTradingEngine

**Location:** `trading/engine.py`

**Role:** Lightweight orchestrator. Now delegates strategy creation to `StrategyFactory`.

**Design Rating: A**

- Simplified by removing hardcoded strategy instantiation.

---

## Implementation Roadmap (Next Steps)

1. **Backtesting Unification**: Update `core/backtester.py` to use `StrategyFactory` logic, ensuring backtests match live execution 1:1.
2. **Observability**: Enhance `MetricsService` to track component-specific events (e.g., "Entry triggered by V35, Exit triggered by Experimental").
3. **Circuit Breakers**: Implement error recovery for connection failures.

---

## Appendix: Key File Locations

| Purpose | File |
|---------|------|
| Factory | `trading/strategies/components/strategy_factory.py` |
| Composite Task | `trading/strategies/components/composite_strategy_task.py` |
| V35 Entry | `trading/strategies/components/v35_entry.py` |
| V35 Exit | `trading/strategies/components/v35_trailing_exit.py` |
| Experimental Exit | `trading/strategies/components/experimental_exit.py` |
| Engine | `trading/engine.py` |
| Config | `config/strategies/allocation.json` |
