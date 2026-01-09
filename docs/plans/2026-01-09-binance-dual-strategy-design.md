# Binance Dual Strategy Integration

## Overview

Add Binance long/short strategies alongside existing Upbit strategies, displayed as separate cards in the dashboard.

## Requirements

1. Each asset can have both Upbit and Binance strategies running independently
2. Binance supports both long (BULL) and short (BEAR) strategies
3. Dashboard shows separate cards per exchange (e.g., "BTC Upbit", "BTC Binance")
4. Independent capital pools for each exchange
5. Per-asset enable/disable for each exchange

## Config Structure

```json
{
  "capital": {
    "upbit_krw": 10000000,
    "binance_usdt": 5000
  },
  "assets": {
    "BTC": {
      "upbit_enabled": true,
      "binance_enabled": true,
      "alpha_ratio": 0.4,
      "upbit_symbol": "KRW-BTC",
      "binance_symbol": "BTCUSDT",
      "db_path": "data/upbit_bitcoin.db",
      "upbit_strategies": {
        "BULL": "v35",
        "SIDEWAYS": "sideways_v2",
        "BEAR": null
      },
      "binance_strategies": {
        "BULL": "v35",
        "SIDEWAYS": null,
        "BEAR": "short_v1"
      },
      "binance_leverage": 3
    }
  }
}
```

## Implementation

### 1. Config Changes (`config/strategies/allocation.json`)

- Add `capital` section with `upbit_krw` and `binance_usdt`
- Rename `strategies` to `upbit_strategies`
- Add `binance_strategies` per asset
- Add `upbit_enabled` and `binance_enabled` flags
- Add `binance_leverage` per asset

### 2. MultiAssetAlphaManager Changes

Modify to support `(symbol, exchange)` composite keys:

```python
# Current: accounts[symbol]
# New: accounts[(symbol, "upbit")], accounts[(symbol, "binance")]

def set_account(self, symbol: str, exchange: str, account):
    self._accounts[(symbol, exchange)] = account

def set_strategy(self, symbol: str, exchange: str, strategy):
    self._strategies[(symbol, exchange)] = strategy
```

### 3. MultiAssetTradingEngine Changes

Dual account and strategy setup:

```python
def _setup_strategies_and_accounts(self):
    for symbol in self._symbols:
        asset_cfg = self.allocation_config["assets"][symbol]

        # Upbit setup
        if asset_cfg.get("upbit_enabled", False):
            upbit_capital = self.config.total_capital_krw * asset_cfg["alpha_ratio"]
            upbit_account = PaperTradingAccount(upbit_capital, "upbit")
            self.alpha_manager.set_account(symbol, "upbit", upbit_account)

            upbit_strategy = self._load_strategy_for_exchange(
                symbol, asset_cfg, "upbit"
            )
            if upbit_strategy:
                self.alpha_manager.set_strategy(symbol, "upbit", upbit_strategy)

        # Binance setup
        if asset_cfg.get("binance_enabled", False):
            binance_capital = self.config.binance_capital_usdt * asset_cfg["alpha_ratio"]
            binance_account = PaperTradingAccount(binance_capital, "binance")
            self.alpha_manager.set_account(symbol, "binance", binance_account)

            binance_strategy = self._load_strategy_for_exchange(
                symbol, asset_cfg, "binance"
            )
            if binance_strategy:
                self.alpha_manager.set_strategy(symbol, "binance", binance_strategy)
```

### 4. Dashboard API Changes (`web/app.py`)

Return separate entries per exchange:

```python
assets = {}
for symbol, data in assets_data.items():
    asset_config = allocation.get('assets', {}).get(symbol, {})

    if asset_config.get('upbit_enabled'):
        assets[f"{symbol}_upbit"] = {
            'symbol': symbol,
            'exchange': 'upbit',
            'strategies': asset_config.get('upbit_strategies', {}),
            'price': data.get('upbit_price', 0),
            'position_active': data.get('upbit_position_active', False),
            'position_qty': data.get('upbit_position_qty', 0),
            ...
        }

    if asset_config.get('binance_enabled'):
        assets[f"{symbol}_binance"] = {
            'symbol': symbol,
            'exchange': 'binance',
            'strategies': asset_config.get('binance_strategies', {}),
            'price': data.get('binance_price', 0),
            'position_active': data.get('binance_position_active', False),
            'position_qty': data.get('binance_position_qty', 0),
            ...
        }
```

### 5. Dashboard JS Changes (`web/static/js/dashboard.js`)

Render exchange-aware cards:

```javascript
function renderAssetCards(assets) {
    let html = '';
    for (const [key, data] of Object.entries(assets)) {
        const exchangeClass = `exchange-${data.exchange}`;
        const regimeClass = getRegimeClass(data.regime);

        let activeStrategy = '-';
        if (data.strategies) {
            const regimeKey = data.regime?.split('_')[0] || 'BULL';
            activeStrategy = data.strategies[regimeKey] || '-';
        }

        html += `
            <div class="asset-card ${regimeClass} ${exchangeClass}">
                <div class="asset-header">
                    <span class="asset-symbol">${data.symbol}</span>
                    <span class="asset-exchange">${data.exchange.toUpperCase()}</span>
                    <span class="asset-regime ${regimeClass}">${getRegimeLabel(data.regime)}</span>
                </div>
                <div class="asset-prices">
                    <div class="price-row">
                        <span class="label">Price</span>
                        <span class="value">${formatPrice(data.price, data.exchange === 'upbit')}</span>
                    </div>
                </div>
                <div class="asset-position">
                    <div class="info-row">
                        <span class="label">Strategy</span>
                        <span class="value">${activeStrategy}</span>
                    </div>
                    <div class="info-row">
                        <span class="label">Position</span>
                        <span class="value">${data.position_active ? 'Active' : 'None'}</span>
                    </div>
                </div>
            </div>
        `;
    }
    container.innerHTML = html;
}
```

### 6. CSS Changes (`web/static/css/style.css`)

```css
.exchange-upbit {
    border-left: 4px solid #0066cc;
}

.exchange-binance {
    border-left: 4px solid #f0b90b;
}

.asset-exchange {
    font-size: 0.7em;
    padding: 2px 6px;
    border-radius: 3px;
    background: rgba(255,255,255,0.1);
}
```

## Files to Modify

1. `config/strategies/allocation.json` - New config structure
2. `trading/execution/multi_asset_alpha_manager.py` - Exchange dimension support
3. `trading/multi_asset_engine.py` - Dual setup and status
4. `web/app.py` - API response with exchange entries
5. `web/static/js/dashboard.js` - Exchange-aware rendering
6. `web/static/css/style.css` - Visual distinction

## Out of Scope

- Live trading execution for Binance (paper only)
- Binance-optimized long strategy (using v35 for now)
- Cross-exchange hedging logic
- Dynamic rebalancing between exchanges
