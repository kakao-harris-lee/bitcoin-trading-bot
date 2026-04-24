// Trading Terminal JavaScript
// Dark terminal-style dashboard with sparkline charts

class TradingTerminal {
    constructor() {
        this.priceHistory = {};  // Store price history per symbol
        this.maxPricePoints = 60;  // 60 data points for sparkline
        this.updateInterval = 10000;  // 10 seconds
        this.currentFilter = 'all';
        this.init();
    }

    init() {
        this.bindEvents();
        this.fetchData();
        this.startAutoRefresh();
        this.updateTimestamp();
    }

    bindEvents() {
        // Filter buttons
        document.querySelectorAll('.filter-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
                e.target.classList.add('active');
                this.currentFilter = e.target.dataset.filter;
                this.applyFilter();
            });
        });

        // Kill switch
        const killSwitch = document.getElementById('kill-switch');
        if (killSwitch) {
            killSwitch.addEventListener('click', () => this.toggleKillSwitch());
        }

        // Keyboard shortcuts
        document.addEventListener('keydown', (e) => {
            if (e.key === 'r' || e.key === 'R') {
                this.fetchData();
            }
        });
    }

    startAutoRefresh() {
        setInterval(() => {
            this.fetchData();
        }, this.updateInterval);
    }

    updateTimestamp() {
        const el = document.getElementById('last-update');
        if (el) {
            const now = new Date();
            el.textContent = now.toLocaleTimeString('en-US', { hour12: false });
        }
    }

    async fetchData() {
        try {
            // Fetch all data in parallel
            const [statusRes, balancesRes, tradesRes] = await Promise.all([
                fetch('/api/status'),
                fetch('/api/exchange_balances'),
                fetch('/api/recent_trades?limit=20')
            ]);

            const status = await statusRes.json();
            const balances = await balancesRes.json();
            const trades = await tradesRes.json();

            this.updateStatus(status);
            this.updateBalances(balances);
            this.updateAssets(balances);
            this.updateTrades(trades);
            this.updateConnectionStatus(true);
            this.updateTimestamp();

        } catch (error) {
            console.error('Failed to fetch data:', error);
            this.updateConnectionStatus(false);
        }
    }

    updateStatus(status) {
        // Engine status
        const engineStatus = document.getElementById('engine-status');
        if (engineStatus) {
            const isRunning = status.engine_status === 'running';
            engineStatus.className = `status-badge ${isRunning ? 'running' : 'stopped'}`;
            engineStatus.querySelector('.status-text').textContent = isRunning ? 'RUNNING' : 'STOPPED';
        }

        // Trading mode
        const modeEl = document.getElementById('trading-mode');
        if (modeEl) {
            const mode = status.trading_mode || 'PAPER';
            modeEl.textContent = mode.toUpperCase();
            modeEl.className = `value ${mode.toLowerCase()}`;
        }

        // Daily P&L
        const dailyPnl = document.getElementById('daily-pnl');
        if (dailyPnl && status.risk) {
            const pnl = parseFloat(status.risk.daily_pnl || 0);
            dailyPnl.textContent = this.formatCurrency(pnl, true);
            dailyPnl.className = `value ${pnl >= 0 ? 'profit' : 'loss'}`;
        }

        // Kill switch
        const killSwitch = document.getElementById('kill-switch');
        if (killSwitch && status.risk) {
            const isActive = status.risk.kill_switch === 'true';
            killSwitch.className = `kill-switch ${isActive ? 'active' : ''}`;
        }
    }

    updateBalances(balances) {
        // API returns { binance: { spot: {...}, total_equity: ... } }
        const binance = balances.binance || {};
        const spot = binance.spot || {};

        // Spot balances
        const spotUsdt = document.getElementById('spot-usdt');
        const spotPositionValue = document.getElementById('spot-position-value');
        const spotTotal = document.getElementById('spot-total');

        if (spotUsdt) spotUsdt.textContent = this.formatCurrency(spot.usdt_balance || 0);
        if (spotPositionValue) spotPositionValue.textContent = this.formatCurrency(spot.position_value || 0);
        if (spotTotal) spotTotal.textContent = this.formatCurrency(spot.total || 0);

        // Spot positions
        this.renderPositions('spot-positions', spot.positions || [], 'spot');

        // Total equity
        const totalEquity = document.getElementById('total-equity');
        if (totalEquity) {
            totalEquity.textContent = this.formatCurrency(binance.total_equity || 0);
        }
    }

    renderPositions(containerId, positions, market) {
        const container = document.getElementById(containerId);
        if (!container) return;

        if (!positions || positions.length === 0) {
            container.innerHTML = '<div class="no-positions">No positions</div>';
            return;
        }

        container.innerHTML = positions.map(pos => {
            const pnl = pos.unrealized_pnl || 0;
            const pnlClass = pnl >= 0 ? 'profit' : 'loss';
            return `
                <div class="position-row">
                    <span class="position-symbol">${pos.symbol}</span>
                    <span class="position-qty">${this.formatNumber(pos.quantity, 6)}</span>
                    <span class="position-value">${this.formatCurrency(pos.value || 0)}</span>
                    <span class="position-pnl ${pnlClass}">${this.formatCurrency(pnl, true)}</span>
                </div>
            `;
        }).join('');
    }

    updateAssets(balances) {
        const grid = document.getElementById('assets-grid');
        if (!grid) return;

        // API returns { binance: { spot: {...} } }
        const binance = balances.binance || {};
        const spot = binance.spot || {};

        // Collect all unique assets from spot positions
        const assets = new Map();

        // Add spot positions
        if (spot.positions) {
            spot.positions.forEach(pos => {
                const symbol = pos.asset || pos.symbol?.replace('USDT', '');
                if (!symbol) return;
                if (!assets.has(symbol)) {
                    assets.set(symbol, { symbol, spot: null });
                }
                assets.get(symbol).spot = {
                    symbol: symbol,
                    quantity: pos.quantity || 0,
                    value: pos.value || 0,
                    price: pos.price || 0,
                };
            });
        }

        // Default assets if none
        const defaultSymbols = ['BTC', 'ETH', 'SOL'];
        defaultSymbols.forEach(symbol => {
            if (!assets.has(symbol)) {
                assets.set(symbol, { symbol, spot: null });
            }
        });

        // Filter assets
        let filteredAssets = Array.from(assets.values());
        if (this.currentFilter === 'holding') {
            filteredAssets = filteredAssets.filter(a => a.spot);
        }

        if (filteredAssets.length === 0) {
            grid.innerHTML = '<div class="empty-state">No assets to display</div>';
            return;
        }

        // Render asset cards
        grid.innerHTML = filteredAssets.map(asset => this.renderAssetCard(asset)).join('');

        // Draw sparklines
        filteredAssets.forEach(asset => {
            this.drawSparkline(asset.symbol);
        });

        // Fetch prices for sparklines
        this.fetchPrices(filteredAssets.map(a => a.symbol));
    }

    renderAssetCard(asset) {
        const hasPosition = Boolean(asset.spot);

        // Get current price from history
        const history = this.priceHistory[asset.symbol] || [];
        const currentPrice = history.length > 0 ? history[history.length - 1] : 0;
        const prevPrice = history.length > 1 ? history[history.length - 2] : currentPrice;
        const priceChange = currentPrice && prevPrice ? ((currentPrice - prevPrice) / prevPrice * 100) : 0;

        return `
            <div class="asset-card ${hasPosition ? 'has-position' : ''}" data-symbol="${asset.symbol}">
                <div class="asset-header">
                    <div class="asset-symbol">
                        <span class="symbol-icon">${this.getSymbolIcon(asset.symbol)}</span>
                        <span class="symbol-name">${asset.symbol}</span>
                    </div>
                    <div class="asset-price">
                        <span class="price">${currentPrice ? this.formatCurrency(currentPrice) : '-'}</span>
                        <span class="change ${priceChange >= 0 ? 'up' : 'down'}">
                            ${priceChange >= 0 ? '+' : ''}${priceChange.toFixed(2)}%
                        </span>
                    </div>
                </div>

                <div class="asset-chart">
                    <canvas id="chart-${asset.symbol}" width="280" height="60"></canvas>
                </div>

                <div class="asset-holdings">
                    ${asset.spot ? `
                        <div class="holding-row spot">
                            <span class="holding-label">SPOT</span>
                            <span class="holding-qty">${this.formatNumber(asset.spot.quantity, 6)}</span>
                            <span class="holding-value">${this.formatCurrency(asset.spot.value || 0)}</span>
                        </div>
                    ` : ''}
                    ${!hasPosition ? `
                        <div class="no-holding">No position</div>
                    ` : ''}
                </div>
            </div>
        `;
    }

    async fetchPrices(symbols) {
        // Fetch current prices from status API
        try {
            const response = await fetch('/api/status');
            const status = await response.json();

            if (status.prices) {
                Object.entries(status.prices).forEach(([symbol, price]) => {
                    const cleanSymbol = symbol.replace('USDT', '');
                    if (!this.priceHistory[cleanSymbol]) {
                        this.priceHistory[cleanSymbol] = [];
                    }

                    this.priceHistory[cleanSymbol].push(parseFloat(price));

                    // Keep only last N points
                    if (this.priceHistory[cleanSymbol].length > this.maxPricePoints) {
                        this.priceHistory[cleanSymbol].shift();
                    }

                    this.drawSparkline(cleanSymbol);
                });
            }
        } catch (error) {
            console.error('Failed to fetch prices:', error);
        }
    }

    drawSparkline(symbol) {
        const canvas = document.getElementById(`chart-${symbol}`);
        if (!canvas) return;

        const ctx = canvas.getContext('2d');
        const data = this.priceHistory[symbol] || [];

        // Clear canvas
        ctx.clearRect(0, 0, canvas.width, canvas.height);

        if (data.length < 2) {
            // Not enough data
            ctx.fillStyle = 'rgba(255,255,255,0.1)';
            ctx.font = '10px JetBrains Mono';
            ctx.textAlign = 'center';
            ctx.fillText('Collecting data...', canvas.width / 2, canvas.height / 2);
            return;
        }

        const padding = 5;
        const width = canvas.width - padding * 2;
        const height = canvas.height - padding * 2;

        const min = Math.min(...data);
        const max = Math.max(...data);
        const range = max - min || 1;

        // Determine color based on trend
        const isUp = data[data.length - 1] >= data[0];
        const lineColor = isUp ? '#00ff88' : '#ff4444';
        const fillColor = isUp ? 'rgba(0, 255, 136, 0.1)' : 'rgba(255, 68, 68, 0.1)';

        // Draw gradient fill
        const gradient = ctx.createLinearGradient(0, padding, 0, height + padding);
        gradient.addColorStop(0, fillColor);
        gradient.addColorStop(1, 'transparent');

        ctx.beginPath();
        ctx.moveTo(padding, height + padding);

        data.forEach((price, i) => {
            const x = padding + (i / (data.length - 1)) * width;
            const y = padding + height - ((price - min) / range) * height;

            if (i === 0) {
                ctx.lineTo(x, y);
            } else {
                ctx.lineTo(x, y);
            }
        });

        ctx.lineTo(padding + width, height + padding);
        ctx.closePath();
        ctx.fillStyle = gradient;
        ctx.fill();

        // Draw line
        ctx.beginPath();
        data.forEach((price, i) => {
            const x = padding + (i / (data.length - 1)) * width;
            const y = padding + height - ((price - min) / range) * height;

            if (i === 0) {
                ctx.moveTo(x, y);
            } else {
                ctx.lineTo(x, y);
            }
        });

        ctx.strokeStyle = lineColor;
        ctx.lineWidth = 1.5;
        ctx.stroke();

        // Draw last point
        const lastX = padding + width;
        const lastY = padding + height - ((data[data.length - 1] - min) / range) * height;

        ctx.beginPath();
        ctx.arc(lastX, lastY, 3, 0, Math.PI * 2);
        ctx.fillStyle = lineColor;
        ctx.fill();
    }

    updateTrades(trades) {
        const container = document.getElementById('recent-trades');
        if (!container) return;

        if (!trades || trades.length === 0) {
            container.innerHTML = '<div class="empty-state">No recent trades</div>';
            return;
        }

        container.innerHTML = trades.map(trade => {
            const isBuy = trade.side === 'buy';
            const profit = trade.profit ? parseFloat(trade.profit) : null;

            return `
                <div class="trade-row ${isBuy ? 'buy' : 'sell'}">
                    <div class="trade-main">
                        <span class="trade-side ${isBuy ? 'buy' : 'sell'}">${isBuy ? 'BUY' : 'SELL'}</span>
                        <span class="trade-symbol">${trade.symbol}</span>
                        <span class="trade-market ${trade.market}">${trade.market?.toUpperCase()}</span>
                    </div>
                    <div class="trade-details">
                        <span class="trade-qty">${this.formatNumber(trade.quantity, 6)}</span>
                        <span class="trade-price">@ ${this.formatCurrency(trade.price)}</span>
                    </div>
                    <div class="trade-meta">
                        ${profit !== null ? `
                            <span class="trade-profit ${profit >= 0 ? 'profit' : 'loss'}">
                                ${this.formatCurrency(profit, true)}
                            </span>
                        ` : ''}
                        ${trade.reason ? `<span class="trade-reason">${trade.reason}</span>` : ''}
                        <span class="trade-time">${this.formatTime(trade.timestamp)}</span>
                    </div>
                </div>
            `;
        }).join('');
    }

    updateConnectionStatus(connected) {
        const status = document.getElementById('connection-status');
        if (status) {
            status.className = `connection-status ${connected ? 'connected' : 'disconnected'}`;
            status.innerHTML = `
                <span class="dot"></span>
                ${connected ? 'CONNECTED' : 'DISCONNECTED'}
            `;
        }
    }

    async toggleKillSwitch() {
        // Toggle kill switch via API (if available)
        console.log('Kill switch toggle requested');
    }

    applyFilter() {
        // Re-render assets with new filter
        this.fetchData();
    }

    // Utility functions
    formatCurrency(value, showSign = false) {
        const num = parseFloat(value) || 0;
        const sign = showSign && num > 0 ? '+' : '';
        return sign + '$' + num.toLocaleString('en-US', {
            minimumFractionDigits: 2,
            maximumFractionDigits: 2
        });
    }

    formatNumber(value, decimals = 2) {
        const num = parseFloat(value) || 0;
        return num.toLocaleString('en-US', {
            minimumFractionDigits: decimals,
            maximumFractionDigits: decimals
        });
    }

    formatTime(timestamp) {
        if (!timestamp) return '-';
        const date = new Date(parseInt(timestamp));
        return date.toLocaleTimeString('en-US', { hour12: false });
    }

    getSymbolIcon(symbol) {
        const icons = {
            'BTC': '₿',
            'ETH': 'Ξ',
            'SOL': '◎',
            'BNB': '♦',
            'XRP': '✕',
            'ADA': '₳',
            'DOGE': 'Ð',
            'DOT': '●',
            'MATIC': '⬡',
            'AVAX': '▲'
        };
        return icons[symbol] || '○';
    }
}

// Initialize terminal when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    window.terminal = new TradingTerminal();
});
