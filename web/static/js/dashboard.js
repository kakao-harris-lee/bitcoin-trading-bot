/**
 * Multi-Asset Trading Bot Dashboard
 * Real-time status monitoring for Multi-Asset Engine
 */

const REFRESH_INTERVAL = 30000; // 30 seconds
const STALE_THRESHOLD = 60000; // 60 seconds - data considered stale
const MAX_RETRIES = 3;
const RETRY_DELAY = 2000; // 2 seconds

// Track last successful fetch times
let lastFetchTimes = {};

// Price history for sparklines (symbol -> array of prices)
const priceHistory = {};
const PRICE_HISTORY_LENGTH = 60; // Keep last 60 data points

// API Fetch Utility with Error Handling and Retry
async function apiFetch(endpoint, options = {}, retryCount = 0) {
    const defaultOptions = {
        credentials: 'include',
        headers: {
            'Content-Type': 'application/json',
        },
    };

    const mergedOptions = { ...defaultOptions, ...options };

    try {
        const response = await fetch(endpoint, mergedOptions);

        if (!response.ok) {
            const errorData = await response.json().catch(() => ({}));
            throw new Error(errorData.error || `HTTP ${response.status}: ${response.statusText}`);
        }

        // Track successful fetch time
        lastFetchTimes[endpoint] = Date.now();

        return await response.json();
    } catch (error) {
        console.error(`API fetch error (${endpoint}):`, error);

        // Retry for GET requests on network errors
        if (retryCount < MAX_RETRIES && !options.method) {
            console.log(`Retrying ${endpoint} (attempt ${retryCount + 1}/${MAX_RETRIES})...`);
            await sleep(RETRY_DELAY);
            return apiFetch(endpoint, options, retryCount + 1);
        }

        throw error;
    }
}

// Helper: sleep function
function sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
}

// Helper: HTML escape to prevent XSS
function escapeHtml(unsafe) {
    if (unsafe === null || unsafe === undefined) return '';
    return String(unsafe)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}

// Check if data is stale
function isDataStale(endpoint) {
    const lastFetch = lastFetchTimes[endpoint];
    if (!lastFetch) return true;
    return (Date.now() - lastFetch) > STALE_THRESHOLD;
}

// Update staleness indicator
function updateStalenessIndicator() {
    const lastUpdateEl = document.getElementById('last-update-time');
    if (!lastUpdateEl) return;

    const statusFetchTime = lastFetchTimes['/api/status'];
    if (!statusFetchTime) return;

    const age = Date.now() - statusFetchTime;
    if (age > STALE_THRESHOLD) {
        lastUpdateEl.parentElement.classList.add('stale');
        lastUpdateEl.title = 'Data may be outdated';
    } else {
        lastUpdateEl.parentElement.classList.remove('stale');
        lastUpdateEl.title = '';
    }
}

// Render loading state
function renderLoading(containerId) {
    const container = document.getElementById(containerId);
    if (container) {
        container.innerHTML = `
            <div class="loading-container">
                <div class="spinner"></div>
                <span>Loading...</span>
            </div>
        `;
    }
}

// Render error state
function renderError(containerId, message, retryFn = null) {
    const container = document.getElementById(containerId);
    if (container) {
        container.innerHTML = `
            <div class="error-state">
                <span class="error-icon">!</span>
                <span class="error-message">${message}</span>
                ${retryFn ? '<button class="retry-btn" onclick="' + retryFn + '()">Retry</button>' : ''}
            </div>
        `;
    }
}

// Render empty state
function renderEmpty(containerId, message = 'No data available') {
    const container = document.getElementById(containerId);
    if (container) {
        container.innerHTML = `
            <div class="empty-state">
                <span class="empty-icon">-</span>
                <span>${message}</span>
            </div>
        `;
    }
}

// Format numbers
function formatUSDT(value) {
    if (value === null || value === undefined) return '-';
    return new Intl.NumberFormat('en-US', {
        style: 'currency',
        currency: 'USD',
        minimumFractionDigits: 2,
        maximumFractionDigits: 2
    }).format(value).replace('$', '') + ' USDT';
}

function formatUSD(value) {
    if (value === null || value === undefined) return '-';
    return new Intl.NumberFormat('en-US', {
        style: 'currency',
        currency: 'USD',
        minimumFractionDigits: 2,
        maximumFractionDigits: 2
    }).format(value);
}

function formatPercent(value, decimals = 2) {
    if (value === null || value === undefined) return '-';
    const percent = value.toFixed(decimals);
    return `${value >= 0 ? '+' : ''}${percent}%`;
}

function formatTime(isoString) {
    if (!isoString) return '-';
    const date = new Date(isoString);
    return date.toLocaleTimeString('ko-KR', {
        hour: '2-digit',
        minute: '2-digit'
    });
}

function formatDateTime(isoString) {
    if (!isoString) return '-';
    const date = new Date(isoString);
    return date.toLocaleString('ko-KR', {
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit'
    });
}

function formatPrice(price, isUSD = true) {
    if (!price) return '-';
    return new Intl.NumberFormat('en-US', {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2
    }).format(price);
}

// Format date for display (YYYY-MM-DD)
function formatDate(dateStr) {
    if (!dateStr) return '-';
    const date = new Date(dateStr);
    return date.toLocaleDateString('ko-KR', {
        year: 'numeric',
        month: '2-digit',
        day: '2-digit'
    });
}

// Format number with commas
function formatNumber(value, decimals = 0) {
    if (value === null || value === undefined) return '-';
    return new Intl.NumberFormat('ko-KR', {
        minimumFractionDigits: decimals,
        maximumFractionDigits: decimals
    }).format(value);
}

// Format quantity (crypto amounts)
function formatQuantity(value, decimals = 6) {
    if (value === null || value === undefined) return '-';
    return Number(value).toFixed(decimals);
}

// Get CSS class for P&L value
function getPnLClass(value) {
    if (value === null || value === undefined) return '';
    return value >= 0 ? 'positive' : 'negative';
}

// Get regime class for styling
function getRegimeClass(regime) {
    if (!regime) return '';
    const regimeLower = regime.toLowerCase();
    if (regimeLower.includes('bull')) return 'regime-bull';
    if (regimeLower.includes('bear')) return 'regime-bear';
    if (regimeLower.includes('sideways')) return 'regime-sideways';
    return '';
}

// Get regime display label
function getRegimeLabel(regime) {
    if (!regime) return '?';
    const regimeLower = regime.toLowerCase();
    if (regimeLower.includes('bull')) return 'BULL';
    if (regimeLower.includes('bear')) return 'BEAR';
    if (regimeLower.includes('sideways')) return 'SIDE';
    return regime.substring(0, 4).toUpperCase();
}

// Update price history for sparklines
function updatePriceHistory(symbol, price) {
    if (!price || price <= 0) return;

    if (!priceHistory[symbol]) {
        priceHistory[symbol] = [];
    }

    priceHistory[symbol].push(price);

    // Keep only last N points
    if (priceHistory[symbol].length > PRICE_HISTORY_LENGTH) {
        priceHistory[symbol].shift();
    }
}

// Draw sparkline chart on canvas
function drawSparkline(canvasId, data, color = '#58a6ff') {
    const canvas = document.getElementById(canvasId);
    if (!canvas || !data || data.length < 2) return;

    const ctx = canvas.getContext('2d');
    const width = canvas.width;
    const height = canvas.height;
    const padding = 2;

    // Clear canvas
    ctx.clearRect(0, 0, width, height);

    // Find min/max for scaling
    const min = Math.min(...data);
    const max = Math.max(...data);
    const range = max - min || 1;

    // Calculate points
    const stepX = (width - padding * 2) / (data.length - 1);
    const points = data.map((val, i) => ({
        x: padding + i * stepX,
        y: height - padding - ((val - min) / range) * (height - padding * 2)
    }));

    // Determine line color based on trend
    const isUp = data[data.length - 1] >= data[0];
    const lineColor = isUp ? '#3fb950' : '#f85149';

    // Draw gradient fill
    const gradient = ctx.createLinearGradient(0, 0, 0, height);
    gradient.addColorStop(0, isUp ? 'rgba(63, 185, 80, 0.3)' : 'rgba(248, 81, 73, 0.3)');
    gradient.addColorStop(1, 'rgba(0, 0, 0, 0)');

    ctx.beginPath();
    ctx.moveTo(points[0].x, points[0].y);
    for (let i = 1; i < points.length; i++) {
        ctx.lineTo(points[i].x, points[i].y);
    }
    ctx.lineTo(points[points.length - 1].x, height);
    ctx.lineTo(points[0].x, height);
    ctx.closePath();
    ctx.fillStyle = gradient;
    ctx.fill();

    // Draw line
    ctx.beginPath();
    ctx.moveTo(points[0].x, points[0].y);
    for (let i = 1; i < points.length; i++) {
        ctx.lineTo(points[i].x, points[i].y);
    }
    ctx.strokeStyle = lineColor;
    ctx.lineWidth = 1.5;
    ctx.stroke();

    // Draw end dot
    const lastPoint = points[points.length - 1];
    ctx.beginPath();
    ctx.arc(lastPoint.x, lastPoint.y, 3, 0, Math.PI * 2);
    ctx.fillStyle = lineColor;
    ctx.fill();
}

// Draw all sparklines for assets
function drawAllSparklines() {
    for (const symbol of Object.keys(priceHistory)) {
        const canvasId = `sparkline-${symbol.toLowerCase()}`;
        drawSparkline(canvasId, priceHistory[symbol]);
    }
}

// Render asset cards (exchange-aware)
function renderAssetCards(assets) {
    const container = document.getElementById('assets-grid');
    if (!assets || Object.keys(assets).length === 0) {
        container.innerHTML = '<p class="no-data">No assets available</p>';
        return;
    }

    let html = '';
    for (const [key, data] of Object.entries(assets)) {
        const regimeClass = getRegimeClass(data.regime);
        const regimeLabel = getRegimeLabel(data.regime);
        const exchangeClass = `exchange-${data.exchange}`;

        // Update price history for sparkline
        updatePriceHistory(data.symbol, data.price);

        // Position status
        let positionStatus = 'None';
        let positionClass = '';
        if (data.position_active) {
            positionClass = 'has-position';
            positionStatus = data.direction === 'short' ? 'SHORT' : 'LONG';
        }

        // Get active strategy from strategies config
        let activeStrategy = data.strategy || '-';
        if (!activeStrategy || activeStrategy === '-') {
            if (data.strategies) {
                const regimeKey = data.regime?.split('_')[0] || 'BULL';
                activeStrategy = data.strategies[regimeKey] || '-';
            }
        }

        // Format price (USDT)
        const priceDisplay = `$${formatPrice(data.price, false)}`;

        // Direction indicator
        const directionClass = data.direction === 'short' ? 'direction-short' : 'direction-long';

        // Calculate price change percentage if we have history
        let priceChange = '';
        const history = priceHistory[data.symbol];
        if (history && history.length >= 2) {
            const firstPrice = history[0];
            const lastPrice = history[history.length - 1];
            const changePct = ((lastPrice - firstPrice) / firstPrice) * 100;
            const changeClass = changePct >= 0 ? 'positive' : 'negative';
            priceChange = `<span class="price-change ${changeClass}">${changePct >= 0 ? '+' : ''}${changePct.toFixed(2)}%</span>`;
        }

        // Sparkline canvas ID
        const sparklineId = `sparkline-${data.symbol.toLowerCase()}`;

        html += `
            <div class="asset-card ${regimeClass} ${positionClass} ${exchangeClass}">
                <div class="asset-header">
                    <span class="asset-symbol">${data.symbol}</span>
                    <span class="asset-exchange">${data.exchange.toUpperCase()}</span>
                </div>
                <div class="asset-chart">
                    <canvas id="${sparklineId}" width="180" height="50"></canvas>
                </div>
                <div class="asset-prices">
                    <div class="price-row">
                        <span class="label">Price</span>
                        <span class="value">${priceDisplay} ${priceChange}</span>
                    </div>
                    <div class="price-row">
                        <span class="label">Leverage</span>
                        <span class="value">${data.leverage || 1}x</span>
                    </div>
                </div>
                <div class="asset-position">
                    <div class="info-row">
                        <span class="label">Strategy</span>
                        <span class="value">${escapeHtml(activeStrategy)}</span>
                    </div>
                    <div class="info-row">
                        <span class="label">Position</span>
                        <span class="value ${positionClass} ${directionClass}">${positionStatus}</span>
                    </div>
                    ${data.position_active ? `
                    <div class="info-row">
                        <span class="label">Qty</span>
                        <span class="value">${data.position_qty.toFixed(6)}</span>
                    </div>
                    ` : ''}
                </div>
            </div>
        `;
    }
    container.innerHTML = html;

    // Draw sparklines after DOM update
    requestAnimationFrame(() => {
        drawAllSparklines();
    });
}

// Update portfolio summary
function updatePortfolio(portfolio) {
    if (!portfolio) return;

    document.getElementById('total-capital').textContent = formatUSDT(portfolio.total_capital_krw);
    document.getElementById('total-value').textContent = formatUSDT(portfolio.total_value_krw);
    document.getElementById('exposure-pct').textContent = `${(portfolio.exposure_pct || 0).toFixed(1)}%`;

    const pnlEl = document.getElementById('unrealized-pnl');
    const pnl = portfolio.unrealized_pnl || 0;
    pnlEl.textContent = formatUSDT(pnl);
    pnlEl.className = `value ${pnl >= 0 ? 'positive' : 'negative'}`;
}

// Update status display
function updateStatus(data) {
    if (data.error) {
        console.error('Status error:', data.error);
        return;
    }

    document.getElementById('last-update-time').textContent = formatTime(data.timestamp);
    document.getElementById('engine-mode').textContent = (data.mode || 'paper').toUpperCase();
    document.getElementById('iteration-count').textContent = data.iteration_count || 0;

    // Update portfolio
    updatePortfolio(data.portfolio);

    // Render asset cards
    renderAssetCards(data.assets);
}

// Update kill switch status
function updateKillSwitch(data) {
    const indicator = document.getElementById('kill-switch-indicator');
    const text = document.getElementById('kill-switch-text');

    if (data.active) {
        indicator.className = 'indicator on';
        text.textContent = 'KILL SWITCH ON';
        text.style.color = '#e74c3c';
    } else {
        indicator.className = 'indicator off';
        text.textContent = 'Trading Active';
        text.style.color = '#2ecc71';
    }
}

// Fetch and update status
async function fetchStatus() {
    try {
        const response = await fetch('/api/status', { credentials: 'include' });
        if (!response.ok) throw new Error('Status fetch failed');
        const data = await response.json();
        updateStatus(data);
    } catch (err) {
        console.error('Status fetch error:', err);
    }
}

// Fetch and update kill switch
async function fetchKillSwitch() {
    try {
        const response = await fetch('/api/kill_switch/status', { credentials: 'include' });
        if (!response.ok) throw new Error('Kill switch fetch failed');
        const data = await response.json();
        updateKillSwitch(data);
    } catch (err) {
        console.error('Kill switch fetch error:', err);
    }
}

// Update exchange balances display
function updateExchangeBalances(data) {
    if (!data.binance) {
        document.getElementById('spot-status').textContent = 'Error';
        document.getElementById('spot-status').className = 'exchange-status error';
        document.getElementById('futures-status').textContent = 'Error';
        document.getElementById('futures-status').className = 'exchange-status error';
        return;
    }

    const binance = data.binance;

    // ==================== SPOT SECTION ====================
    const spot = binance.spot || {};
    document.getElementById('spot-status').textContent = 'Connected';
    document.getElementById('spot-status').className = 'exchange-status connected';
    document.getElementById('spot-usdt').textContent = formatUSD(spot.usdt_balance || 0);
    document.getElementById('spot-position-value').textContent = formatUSD(spot.position_value || 0);
    document.getElementById('spot-total').textContent = formatUSD(spot.total || 0);

    // Spot positions
    const spotPositions = spot.positions || [];
    const spotPosList = document.getElementById('spot-positions-list');
    if (spotPositions.length > 0) {
        let html = '';
        for (const pos of spotPositions) {
            html += `
                <div class="position-item spot">
                    <div class="position-header">
                        <span class="position-symbol">${pos.asset}</span>
                        <span class="position-side long">HOLD</span>
                    </div>
                    <div class="position-details">
                        <div class="detail-row">
                            <span class="label">Qty</span>
                            <span class="value">${pos.quantity.toFixed(6)}</span>
                        </div>
                        <div class="detail-row">
                            <span class="label">Price</span>
                            <span class="value">$${formatPrice(pos.price, false)}</span>
                        </div>
                        <div class="detail-row">
                            <span class="label">Value</span>
                            <span class="value">${formatUSD(pos.value)}</span>
                        </div>
                    </div>
                </div>
            `;
        }
        spotPosList.innerHTML = html;
    } else {
        spotPosList.innerHTML = '<span class="no-positions">No spot positions</span>';
    }

    // ==================== FUTURES SECTION ====================
    const futures = binance.futures || {};
    document.getElementById('futures-status').textContent = 'Connected';
    document.getElementById('futures-status').className = 'exchange-status connected';
    document.getElementById('futures-usdt').textContent = formatUSD(futures.usdt_balance || 0);

    // Unrealized PnL with color
    const unrealizedPnlEl = document.getElementById('futures-unrealized-pnl');
    const unrealizedPnl = futures.unrealized_pnl || 0;
    unrealizedPnlEl.textContent = formatUSD(unrealizedPnl);
    unrealizedPnlEl.className = `value ${unrealizedPnl >= 0 ? 'positive' : 'negative'}`;

    document.getElementById('futures-total').textContent = formatUSD(futures.total || 0);

    // Hedge mode badge
    const hedgeBadge = document.getElementById('hedge-mode-badge');
    if (futures.hedge_mode) {
        hedgeBadge.style.display = 'inline-block';
    } else {
        hedgeBadge.style.display = 'none';
    }

    // Futures positions
    const futuresPositions = futures.positions || [];
    const futuresPosList = document.getElementById('futures-positions-list');
    if (futuresPositions.length > 0) {
        let html = '';
        for (const pos of futuresPositions) {
            const sideClass = pos.side === 'LONG' ? 'long' : 'short';
            const pnlClass = pos.unrealized_pnl >= 0 ? 'positive' : 'negative';
            html += `
                <div class="position-item futures ${sideClass}">
                    <div class="position-header">
                        <span class="position-symbol">${pos.symbol}</span>
                        <span class="position-side ${sideClass}">${pos.side}</span>
                        <span class="position-leverage">${pos.leverage}x</span>
                    </div>
                    <div class="position-details">
                        <div class="detail-row">
                            <span class="label">Size</span>
                            <span class="value">${Math.abs(pos.size).toFixed(4)}</span>
                        </div>
                        <div class="detail-row">
                            <span class="label">Entry</span>
                            <span class="value">$${formatPrice(pos.entry_price, false)}</span>
                        </div>
                        <div class="detail-row">
                            <span class="label">Mark</span>
                            <span class="value">$${formatPrice(pos.mark_price, false)}</span>
                        </div>
                        ${pos.liquidation_price > 0 ? `
                        <div class="detail-row liquidation">
                            <span class="label">Liq.</span>
                            <span class="value warning">$${formatPrice(pos.liquidation_price, false)}</span>
                        </div>
                        ` : ''}
                        <div class="detail-row pnl">
                            <span class="label">PnL</span>
                            <span class="value ${pnlClass}">${formatUSD(pos.unrealized_pnl)}</span>
                        </div>
                    </div>
                </div>
            `;
        }
        futuresPosList.innerHTML = html;
    } else {
        futuresPosList.innerHTML = '<span class="no-positions">No futures positions</span>';
    }

    // ==================== COMBINED TOTAL ====================
    document.getElementById('binance-total').textContent = formatUSD(binance.total_equity || 0);

    // Show errors if any
    if (data.errors && data.errors.length > 0) {
        console.warn('Exchange balance errors:', data.errors);
    }
}

// Fetch exchange balances
async function fetchExchangeBalances() {
    try {
        const response = await fetch('/api/exchange_balances', { credentials: 'include' });
        if (!response.ok) throw new Error('Exchange balances fetch failed');
        const data = await response.json();
        updateExchangeBalances(data);
    } catch (err) {
        console.error('Exchange balances fetch error:', err);
        document.getElementById('binance-status').textContent = 'Error';
        document.getElementById('binance-status').className = 'exchange-status error';
    }
}

// Fetch leverage state
async function fetchLeverageState() {
    try {
        const response = await fetch('/api/metrics/leverage', { credentials: 'include' });
        if (!response.ok) throw new Error('Leverage state fetch failed');
        const data = await response.json();
        renderLeverageState(data);
    } catch (err) {
        console.error('Leverage state fetch error:', err);
    }
}

// Render leverage state panel
function renderLeverageState(data) {
    const container = document.getElementById('leverage-state');
    if (!container) return;

    if (!data.enabled) {
        container.innerHTML = '<div class="leverage-disabled">LeverageManager not active</div>';
        return;
    }

    // Calculate drawdown bar width
    const drawdownPct = Math.min(data.drawdown_pct || 0, 25); // Cap at 25% for visual
    const drawdownBarWidth = (drawdownPct / 25) * 100;

    // Determine tier color
    let tierClass = 'tier-full';
    if (data.tier === 'reduced') tierClass = 'tier-reduced';
    else if (data.tier === 'cautious') tierClass = 'tier-cautious';
    else if (data.tier === 'minimal') tierClass = 'tier-minimal';
    else if (data.tier === 'halted') tierClass = 'tier-halted';

    // Build tier indicators
    let tiersHtml = '';
    if (data.tiers) {
        for (const tier of data.tiers) {
            const isActive = tier.name === data.tier;
            tiersHtml += `
                <div class="tier-indicator ${isActive ? 'active' : ''}">
                    <span class="tier-leverage">${tier.leverage}x</span>
                    <span class="tier-name">${tier.name}</span>
                    <span class="tier-dd">&lt;${tier.drawdown_max_pct}%</span>
                </div>
            `;
        }
    }

    container.innerHTML = `
        <div class="leverage-header">
            <h4>Risk-Adjusted Leverage</h4>
            <span class="leverage-badge ${tierClass}">${data.leverage}x</span>
        </div>
        <div class="leverage-metrics">
            <div class="leverage-metric">
                <span class="label">Peak Equity</span>
                <span class="value">${formatUSD(data.peak_equity)}</span>
            </div>
            <div class="leverage-metric">
                <span class="label">Current Equity</span>
                <span class="value">${formatUSD(data.current_equity)}</span>
            </div>
            <div class="leverage-metric highlight">
                <span class="label">Drawdown</span>
                <span class="value ${data.drawdown_pct > 10 ? 'negative' : ''}">${data.drawdown_pct.toFixed(1)}%</span>
            </div>
            <div class="leverage-metric">
                <span class="label">Tier</span>
                <span class="value ${tierClass}">${data.tier.toUpperCase()}</span>
            </div>
        </div>
        <div class="drawdown-bar-container">
            <div class="drawdown-bar" style="width: ${drawdownBarWidth}%"></div>
            <div class="drawdown-markers">
                <span class="marker" style="left: 20%">5%</span>
                <span class="marker" style="left: 40%">10%</span>
                <span class="marker" style="left: 60%">15%</span>
                <span class="marker" style="left: 80%">20%</span>
            </div>
        </div>
        <div class="tier-grid">
            ${tiersHtml}
        </div>
    `;
}

// Fetch all data
async function fetchAll() {
    await Promise.all([
        fetchStatus(),
        fetchKillSwitch(),
        fetchExchangeBalances(),
        fetchLeverageState(),
    ]);
}

// Initial load
document.addEventListener('DOMContentLoaded', () => {
    // Initialize tab navigation
    initTabNavigation();

    // Initialize keyboard shortcuts
    initKeyboardShortcuts();

    // Initialize history filters
    initHistoryFilters();

    // Initialize signals filters
    initSignalsFilters();

    // Initialize analytics period selector
    initAnalyticsPeriodSelector();

    // Initialize backtest
    initBacktest();

    // Fetch initial data
    fetchAll();

    // Load initial positions data (default tab)
    fetchPositions();

    // Auto refresh
    setInterval(() => {
        fetchAll();
        // Also refresh active tab data
        if (isTabActive('positions')) {
            fetchPositions();
        } else if (isTabActive('signals')) {
            fetchSignals();
        }
        // Update staleness indicator
        updateStalenessIndicator();
    }, REFRESH_INTERVAL);

    // Initial staleness check interval (more frequent)
    setInterval(updateStalenessIndicator, 10000);
});

// Keyboard Shortcuts
function initKeyboardShortcuts() {
    const TAB_KEYS = {
        '1': 'positions',
        '2': 'history',
        '3': 'signals',
        '4': 'analytics',
        '5': 'backtest'
    };

    document.addEventListener('keydown', (e) => {
        // Don't trigger shortcuts when typing in input fields
        if (e.target.tagName === 'INPUT' || e.target.tagName === 'SELECT' || e.target.tagName === 'TEXTAREA') {
            return;
        }

        // Tab navigation with number keys (1-5)
        if (TAB_KEYS[e.key]) {
            e.preventDefault();
            switchToTab(TAB_KEYS[e.key]);
            return;
        }

        // Refresh with 'r' key
        if (e.key === 'r' || e.key === 'R') {
            e.preventDefault();
            console.log('Manual refresh triggered');
            fetchAll();
            // Refresh current tab data
            const activeTab = getActiveTabId();
            if (activeTab) {
                onTabActivated(activeTab);
            }
            return;
        }
    });

    // Log keyboard shortcuts availability
    console.log('Keyboard shortcuts enabled: 1-5 for tabs, R for refresh');
}

// Switch to a specific tab programmatically
function switchToTab(tabId) {
    const tabBtn = document.querySelector(`.tab-btn[data-tab="${tabId}"]`);
    if (tabBtn) {
        tabBtn.click();
    }
}

// Get currently active tab ID
function getActiveTabId() {
    const activeTab = document.querySelector('.tab-content.active');
    return activeTab ? activeTab.id : null;
}

// Check if a tab is currently active
function isTabActive(tabId) {
    const tabContent = document.getElementById(tabId);
    return tabContent && tabContent.classList.contains('active');
}

// Tab Navigation
function initTabNavigation() {
    const tabButtons = document.querySelectorAll('.tab-btn');
    const tabContents = document.querySelectorAll('.tab-content');

    tabButtons.forEach(btn => {
        btn.addEventListener('click', () => {
            const tabId = btn.dataset.tab;

            // Remove active from all buttons and contents
            tabButtons.forEach(b => b.classList.remove('active'));
            tabContents.forEach(c => c.classList.remove('active'));

            // Activate clicked tab
            btn.classList.add('active');
            const tabContent = document.getElementById(tabId);
            if (tabContent) {
                tabContent.classList.add('active');
            }

            // Trigger tab-specific data loading
            onTabActivated(tabId);
        });
    });
}

// Handle tab activation - load data for specific tab
function onTabActivated(tabId) {
    console.log(`Tab activated: ${tabId}`);

    switch (tabId) {
        case 'positions':
            fetchPositions();
            break;
        case 'history':
            initHistoryDefaults();
            fetchTrades();
            break;
        case 'signals':
            fetchSignals();
            break;
        case 'decisions':
            fetchDecisions();
            break;
        case 'analytics':
            fetchAnalytics(analyticsState.period);
            break;
        case 'backtest':
            // Strategies are loaded on init, but refresh if empty
            if (backtestState.strategies.length === 0) {
                fetchStrategies();
            }
            break;
    }
}

// =====================
// Positions Tab (US1)
// =====================

let positionsData = null;

async function fetchPositions() {
    const containerId = 'positions-container';

    try {
        renderLoading(containerId);
        const data = await apiFetch('/api/positions');
        positionsData = data;
        renderPositions(data);
        updatePositionsSummary(data);
    } catch (error) {
        renderError(containerId, 'Failed to load positions', 'fetchPositions');
    }
}

function renderPositions(data) {
    const container = document.getElementById('positions-container');

    if (!data.positions || data.positions.length === 0) {
        renderEmpty('positions-container', 'No open positions');
        return;
    }

    let html = '';

    // Render all positions (Binance-only)
    for (const pos of data.positions) {
        const pnlClass = getPnLClass(pos.unrealized_pnl);
        const sideClass = pos.side.toLowerCase();

        html += `
            <div class="position-card ${pos.exchange}">
                <div class="card-header">
                    <div>
                        <span class="symbol">${pos.symbol}</span>
                        <span class="side-badge ${sideClass}">${pos.side}</span>
                    </div>
                    <span class="exchange-badge ${pos.exchange}">${pos.exchange}</span>
                </div>
                <div class="card-body">
                    <div class="stat-row">
                        <span class="label">Quantity</span>
                        <span class="value">${formatQuantity(pos.quantity, 4)}</span>
                    </div>
                    <div class="stat-row">
                        <span class="label">Entry Price</span>
                        <span class="value">$${formatPrice(pos.entry_price, false)}</span>
                    </div>
                    <div class="stat-row">
                        <span class="label">Current Price</span>
                        <span class="value">$${formatPrice(pos.current_price, false)}</span>
                    </div>
                    <div class="stat-row">
                        <span class="label">Value</span>
                        <span class="value">${formatUSD(pos.value)}</span>
                    </div>
                    ${pos.leverage ? `
                    <div class="stat-row">
                        <span class="label">Leverage</span>
                        <span class="value">${pos.leverage}x</span>
                    </div>
                    ` : ''}
                    ${pos.liquidation_price ? `
                    <div class="stat-row">
                        <span class="label">Liquidation</span>
                        <span class="value">$${formatPrice(pos.liquidation_price, false)}</span>
                    </div>
                    ` : ''}
                    <div class="stat-row pnl-row">
                        <span class="label">Unrealized P&L</span>
                        <span class="pnl-value ${pnlClass}">
                            ${formatUSD(pos.unrealized_pnl)}
                            (${formatPercent(pos.unrealized_pnl_pct)})
                        </span>
                    </div>
                </div>
            </div>
        `;
    }

    container.innerHTML = html;
}

function updatePositionsSummary(data) {
    const totalValueEl = document.getElementById('positions-total-value');
    const totalPnlEl = document.getElementById('positions-total-pnl');

    if (totalValueEl) {
        // Show as approximate
        totalValueEl.textContent = formatUSDT(data.total_value) + ' (approx)';
    }

    if (totalPnlEl) {
        totalPnlEl.textContent = formatUSDT(data.total_unrealized_pnl);
        totalPnlEl.className = `value ${getPnLClass(data.total_unrealized_pnl)}`;
    }
}

// =====================
// History Tab (US2)
// =====================

let historyState = {
    page: 1,
    limit: 50,
    startDate: '',
    endDate: '',
    totalCount: 0,
    initialized: false
};

function getDefaultHistoryDates() {
    const end = new Date();
    const start = new Date();
    start.setDate(start.getDate() - 7);
    return {
        startDate: start.toISOString().split('T')[0],
        endDate: end.toISOString().split('T')[0]
    };
}

function initHistoryFilters() {
    const applyBtn = document.getElementById('history-apply-filters');
    const clearBtn = document.getElementById('history-clear-filters');

    if (applyBtn) {
        applyBtn.addEventListener('click', () => {
            historyState.startDate = document.getElementById('history-start-date').value;
            historyState.endDate = document.getElementById('history-end-date').value;
            historyState.page = 1;
            fetchTrades();
        });
    }

    if (clearBtn) {
        clearBtn.addEventListener('click', () => {
            // Reset to default (last 1 week)
            const defaults = getDefaultHistoryDates();
            document.getElementById('history-start-date').value = defaults.startDate;
            document.getElementById('history-end-date').value = defaults.endDate;
            historyState.startDate = defaults.startDate;
            historyState.endDate = defaults.endDate;
            historyState.page = 1;
            fetchTrades();
        });
    }
}

function initHistoryDefaults() {
    if (!historyState.initialized) {
        const defaults = getDefaultHistoryDates();
        document.getElementById('history-start-date').value = defaults.startDate;
        document.getElementById('history-end-date').value = defaults.endDate;
        historyState.startDate = defaults.startDate;
        historyState.endDate = defaults.endDate;
        historyState.initialized = true;
    }
}

async function fetchTrades() {
    const containerId = 'history-container';

    try {
        renderLoading(containerId);

        // Build query string
        const params = new URLSearchParams({
            page: historyState.page,
            limit: historyState.limit
        });

        if (historyState.startDate) params.append('start_date', historyState.startDate);
        if (historyState.endDate) params.append('end_date', historyState.endDate);

        const data = await apiFetch(`/api/trades?${params.toString()}`);
        historyState.totalCount = data.total_count;

        renderTradeTable(data);
        renderPagination(data);
    } catch (error) {
        renderError(containerId, 'Failed to load trade history', 'fetchTrades');
    }
}

function renderTradeTable(data) {
    const container = document.getElementById('history-container');

    if (!data.trades || data.trades.length === 0) {
        renderEmpty('history-container', 'No trades found');
        return;
    }

    let html = `
        <table class="data-table">
            <thead>
                <tr>
                    <th>Time</th>
                    <th>Symbol</th>
                    <th>Action</th>
                    <th class="text-right">Price</th>
                    <th class="text-right">Volume</th>
                    <th class="text-right">P&L</th>
                    <th>Strategy</th>
                    <th>Reason</th>
                </tr>
            </thead>
            <tbody>
    `;

    for (const trade of data.trades) {
        const actionClass = trade.action.toLowerCase();
        const pnlClass = getPnLClass(trade.profit);
        const symbolDisplay = trade.symbol || '-';
        const marketBadge = trade.market === 'futures' ? ' <span class="market-badge futures">F</span>' : '';

        html += `
            <tr>
                <td>${formatDateTime(trade.timestamp)}</td>
                <td><span class="symbol-badge">${escapeHtml(symbolDisplay)}</span>${marketBadge}</td>
                <td><span class="action-badge ${actionClass}">${trade.action}</span></td>
                <td class="text-right">$${formatPrice(trade.price, false)}</td>
                <td class="text-right">${formatQuantity(trade.volume, 4)}</td>
                <td class="text-right ${pnlClass}">
                    ${trade.profit !== null ? formatUSD(trade.profit) : '-'}
                    ${trade.profit_pct !== null ? `(${formatPercent(trade.profit_pct)})` : ''}
                </td>
                <td>${escapeHtml(trade.strategy) || '-'}</td>
                <td>${escapeHtml(trade.reason) || '-'}</td>
            </tr>
        `;
    }

    html += `
            </tbody>
        </table>
    `;

    container.innerHTML = html;
}

function renderPagination(data) {
    const container = document.getElementById('history-pagination');
    if (!container) return;

    const totalPages = Math.ceil(data.total_count / historyState.limit);
    const currentPage = historyState.page;

    if (totalPages <= 1) {
        container.innerHTML = '';
        return;
    }

    html = `
        <button class="pagination-btn" onclick="goToPage(1)" ${currentPage === 1 ? 'disabled' : ''}>First</button>
        <button class="pagination-btn" onclick="goToPage(${currentPage - 1})" ${currentPage === 1 ? 'disabled' : ''}>Prev</button>
        <span class="pagination-info">Page ${currentPage} of ${totalPages} (${data.total_count} trades)</span>
        <button class="pagination-btn" onclick="goToPage(${currentPage + 1})" ${currentPage === totalPages ? 'disabled' : ''}>Next</button>
        <button class="pagination-btn" onclick="goToPage(${totalPages})" ${currentPage === totalPages ? 'disabled' : ''}>Last</button>
    `;

    container.innerHTML = html;
}

function goToPage(page) {
    historyState.page = page;
    fetchTrades();
}

// =====================
// Signals Tab (US3)
// =====================

function initSignalsFilters() {
    // No filters needed - show all signals
}

async function fetchSignals() {
    const containerId = 'signals-container';

    try {
        renderLoading(containerId);

        // Build query string
        const params = new URLSearchParams({ limit: 50 });

        const data = await apiFetch(`/api/signals?${params.toString()}`);
        renderSignals(data);
    } catch (error) {
        renderError(containerId, 'Failed to load signals', 'fetchSignals');
    }
}

function renderSignals(data) {
    const container = document.getElementById('signals-container');

    if (!data.signals || data.signals.length === 0) {
        renderEmpty('signals-container', 'No signals found');
        return;
    }

    let html = '';

    for (const signal of data.signals) {
        const actionClass = signal.action.toLowerCase();
        const actedClass = signal.acted ? 'yes' : 'no';
        const indicators = signal.indicators || {};
        const symbolDisplay = signal.symbol || '-';
        const marketDisplay = signal.market === 'futures' ? 'Futures' : 'Spot';

        html += `
            <div class="signal-card ${actionClass}">
                <div class="signal-header">
                    <span class="signal-time">${formatDateTime(signal.timestamp)}</span>
                    <div class="signal-badges">
                        <span class="symbol-badge">${escapeHtml(symbolDisplay)}</span>
                        <span class="signal-action ${actionClass}">${signal.action}</span>
                        <span class="acted-badge ${actedClass}">${signal.acted ? 'Executed' : 'Not Acted'}</span>
                    </div>
                </div>
                <div class="signal-body">
                    <div class="signal-info">
                        <span class="label">Symbol</span>
                        <span class="value">${escapeHtml(symbolDisplay)} (${marketDisplay})</span>
                    </div>
                    <div class="signal-info">
                        <span class="label">Strategy</span>
                        <span class="value">${escapeHtml(signal.strategy) || '-'}</span>
                    </div>
                    <div class="signal-info">
                        <span class="label">Regime</span>
                        <span class="value">${escapeHtml(signal.regime) || '-'}</span>
                    </div>
                    <div class="signal-info">
                        <span class="label">Reason</span>
                        <span class="value">${escapeHtml(signal.reason) || '-'}</span>
                    </div>
                    <div class="signal-info">
                        <span class="label">Market State</span>
                        <span class="value">${escapeHtml(signal.market_state) || '-'}</span>
                    </div>
                </div>
                ${Object.keys(indicators).length > 0 ? `
                <div class="signal-indicators">
                    ${indicators.rsi !== undefined ? `
                    <div class="indicator-item">
                        <span class="label">RSI</span>
                        <span class="value">${formatNumber(indicators.rsi, 1)}</span>
                    </div>
                    ` : ''}
                    ${indicators.mfi !== undefined ? `
                    <div class="indicator-item">
                        <span class="label">MFI</span>
                        <span class="value">${formatNumber(indicators.mfi, 1)}</span>
                    </div>
                    ` : ''}
                    ${indicators.adx !== undefined ? `
                    <div class="indicator-item">
                        <span class="label">ADX</span>
                        <span class="value">${formatNumber(indicators.adx, 1)}</span>
                    </div>
                    ` : ''}
                    ${indicators.close !== undefined ? `
                    <div class="indicator-item">
                        <span class="label">Close</span>
                        <span class="value">${formatPrice(indicators.close, true)}</span>
                    </div>
                    ` : ''}
                    ${indicators.score !== undefined ? `
                    <div class="indicator-item">
                        <span class="label">Score</span>
                        <span class="value">${indicators.score}</span>
                    </div>
                    ` : ''}
                    ${indicators.tier !== undefined ? `
                    <div class="indicator-item">
                        <span class="label">Tier</span>
                        <span class="value">${indicators.tier}</span>
                    </div>
                    ` : ''}
                </div>
                ` : ''}
            </div>
        `;
    }

    container.innerHTML = html;
}

// Decision History (within Signals tab)
async function fetchDecisions() {
    const containerId = 'decisions-container';

    try {
        renderLoading(containerId);

        const data = await apiFetch('/api/metrics/decisions?hours=24&limit=50');
        renderDecisions(data.decisions || []);
    } catch (error) {
        renderError(containerId, 'Failed to load decisions', 'fetchDecisions');
    }
}

function renderDecisions(decisions) {
    const container = document.getElementById('decisions-container');

    if (!decisions || decisions.length === 0) {
        renderEmpty('decisions-container', 'No decisions yet. Decisions are recorded hourly.');
        return;
    }

    let html = '';

    for (const decision of decisions) {
        // Support both old format (action/asset) and new format (decision/symbol)
        const decisionType = decision.decision || decision.action || 'WAIT';
        const decisionClass = decisionType.toLowerCase();
        const indicators = decision.indicators || {};
        const symbolDisplay = decision.symbol || decision.asset || '-';
        const marketDisplay = decision.market === 'futures' ? 'Futures' : 'Spot';
        const regime = decision.regime || '-';
        const position = decision.position || {};

        // Regime badge class
        let regimeClass = 'regime-unknown';
        if (regime.includes('BULL_STRONG')) regimeClass = 'regime-bull-strong';
        else if (regime.includes('BULL')) regimeClass = 'regime-bull';
        else if (regime.includes('BEAR')) regimeClass = 'regime-bear';
        else if (regime.includes('SIDEWAYS')) regimeClass = 'regime-sideways';

        // Position P&L display
        let pnlDisplay = '';
        if (position.active && position.unrealized_pnl_pct !== undefined) {
            const pnlPct = position.unrealized_pnl_pct;
            const pnlClass = pnlPct >= 0 ? 'positive' : 'negative';
            pnlDisplay = `<span class="position-pnl ${pnlClass}">${pnlPct >= 0 ? '+' : ''}${pnlPct.toFixed(2)}%</span>`;
        }

        html += `
            <div class="decision-card ${decisionClass}">
                <div class="decision-header">
                    <span class="decision-time">${formatDateTime(decision.timestamp)}</span>
                    <div class="decision-badges">
                        <span class="symbol-badge">${escapeHtml(symbolDisplay)}</span>
                        <span class="regime-badge ${regimeClass}">${escapeHtml(regime)}</span>
                        <span class="decision-action ${decisionClass}">${decisionType}</span>
                        ${pnlDisplay}
                    </div>
                </div>
                <div class="decision-body">
                    <div class="decision-info">
                        <span class="label">Strategy</span>
                        <span class="value">${escapeHtml(decision.strategy) || '-'}</span>
                    </div>
                    <div class="decision-info">
                        <span class="label">Reason</span>
                        <span class="value">${escapeHtml(decision.reason) || '-'}</span>
                    </div>
                </div>
                <div class="decision-indicators">
                    <span class="ind">Price: ${indicators.price ? formatPrice(indicators.price, true) : '-'}</span>
                    <span class="ind">MFI: ${indicators.mfi ? formatNumber(indicators.mfi, 1) : '-'}</span>
                    <span class="ind">ADX: ${indicators.adx ? formatNumber(indicators.adx, 1) : '-'}</span>
                </div>
            </div>
        `;
    }

    container.innerHTML = html;
}

// =====================
// Analytics Tab (US4)
// =====================

let analyticsState = {
    period: '30d',
    view: 'summary',  // 'summary' or 'daily'
    chart: null,
    dailyChart: null
};

function initAnalyticsPeriodSelector() {
    const periodBtns = document.querySelectorAll('.period-btn');

    periodBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            const period = btn.dataset.period;

            // Update active state
            periodBtns.forEach(b => b.classList.remove('active'));
            btn.classList.add('active');

            // Update state and fetch
            analyticsState.period = period;

            // Fetch based on current view
            if (analyticsState.view === 'summary') {
                fetchAnalytics(period);
            } else {
                fetchDailyAnalytics(period);
            }
        });
    });

    // Initialize view toggle
    initViewToggle();
}

function initViewToggle() {
    const viewBtns = document.querySelectorAll('.view-btn');
    const summaryView = document.getElementById('analytics-summary-view');
    const dailyView = document.getElementById('analytics-daily-view');

    viewBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            const view = btn.dataset.view;

            // Update active state
            viewBtns.forEach(b => b.classList.remove('active'));
            btn.classList.add('active');

            // Update state
            analyticsState.view = view;

            // Toggle views
            if (view === 'summary') {
                summaryView.style.display = 'block';
                dailyView.style.display = 'none';
                fetchAnalytics(analyticsState.period);
            } else {
                summaryView.style.display = 'none';
                dailyView.style.display = 'block';
                fetchDailyAnalytics(analyticsState.period);
            }
        });
    });
}

async function fetchAnalytics(period = '30d') {
    const metricsContainerId = 'analytics-metrics';
    const breakdownContainerId = 'analytics-strategy-breakdown';

    try {
        renderLoading(metricsContainerId);

        // Fetch both metrics and equity curve in parallel
        const [metricsData, equityData] = await Promise.all([
            apiFetch(`/api/analytics?period=${period}`),
            apiFetch(`/api/analytics/equity-curve?period=${period}`)
        ]);

        renderMetricsCards(metricsData);
        renderEquityCurve(equityData);
        renderStrategyBreakdown(metricsData.by_strategy || {});
    } catch (error) {
        renderError(metricsContainerId, 'Failed to load analytics', 'fetchAnalytics');
    }
}

function renderMetricsCards(data) {
    const container = document.getElementById('analytics-metrics');

    if (!data || data.closed_trades === 0) {
        renderEmpty('analytics-metrics', 'No trading data available for this period');
        return;
    }

    const returnClass = getPnLClass(data.total_return);
    const profitClass = getPnLClass(data.total_return_krw);

    let html = `
        <div class="metric-card highlight">
            <div class="metric-value ${returnClass}">${formatPercent(data.total_return)}</div>
            <div class="metric-label">Total Return</div>
        </div>
        <div class="metric-card">
            <div class="metric-value ${profitClass}">${formatUSDT(data.total_return_krw)}</div>
            <div class="metric-label">Profit (USDT)</div>
        </div>
        <div class="metric-card">
            <div class="metric-value">${data.win_rate.toFixed(1)}%</div>
            <div class="metric-label">Win Rate</div>
        </div>
        <div class="metric-card">
            <div class="metric-value">${data.profit_factor}</div>
            <div class="metric-label">Profit Factor</div>
        </div>
        <div class="metric-card">
            <div class="metric-value">${data.closed_trades}</div>
            <div class="metric-label">Closed Trades</div>
        </div>
        <div class="metric-card">
            <div class="metric-value">${data.winning_trades} / ${data.losing_trades}</div>
            <div class="metric-label">Wins / Losses</div>
        </div>
        <div class="metric-card">
            <div class="metric-value ${getPnLClass(data.avg_trade)}">${formatUSDT(data.avg_trade)}</div>
            <div class="metric-label">Avg Trade</div>
        </div>
        <div class="metric-card">
            <div class="metric-value positive">${formatUSDT(data.avg_win)}</div>
            <div class="metric-label">Avg Win</div>
        </div>
        <div class="metric-card">
            <div class="metric-value negative">${formatUSDT(data.avg_loss)}</div>
            <div class="metric-label">Avg Loss</div>
        </div>
        <div class="metric-card">
            <div class="metric-value">${data.sharpe_ratio}</div>
            <div class="metric-label">Sharpe Ratio</div>
        </div>
        <div class="metric-card">
            <div class="metric-value negative">${data.max_drawdown.toFixed(1)}%</div>
            <div class="metric-label">Max Drawdown</div>
        </div>
        <div class="metric-card">
            <div class="metric-value">${data.start_date || '-'} ~ ${data.end_date || '-'}</div>
            <div class="metric-label">Period</div>
        </div>
    `;

    container.innerHTML = html;
}

function renderEquityCurve(data) {
    const canvas = document.getElementById('equity-chart');
    if (!canvas) return;

    const ctx = canvas.getContext('2d');

    // Destroy existing chart if any
    if (analyticsState.chart) {
        analyticsState.chart.destroy();
        analyticsState.chart = null;
    }

    if (!data.points || data.points.length === 0) {
        // Draw empty state on canvas
        ctx.fillStyle = '#888';
        ctx.font = '14px -apple-system, sans-serif';
        ctx.textAlign = 'center';
        ctx.fillText('No equity data available', canvas.width / 2, canvas.height / 2);
        return;
    }

    // Prepare data
    const labels = data.points.map(p => {
        const date = new Date(p.timestamp);
        return date.toLocaleDateString('ko-KR', { month: 'short', day: 'numeric' });
    });

    const equityValues = data.points.map(p => p.equity);
    const drawdownValues = data.points.map(p => p.drawdown_pct);

    // Create chart
    analyticsState.chart = new Chart(ctx, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [
                {
                    label: 'Equity (USDT)',
                    data: equityValues,
                    borderColor: '#f39c12',
                    backgroundColor: 'rgba(243, 156, 18, 0.1)',
                    fill: true,
                    tension: 0.2,
                    yAxisID: 'y'
                },
                {
                    label: 'Drawdown (%)',
                    data: drawdownValues,
                    borderColor: '#e74c3c',
                    backgroundColor: 'rgba(231, 76, 60, 0.1)',
                    fill: true,
                    tension: 0.2,
                    yAxisID: 'y1'
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: {
                mode: 'index',
                intersect: false,
            },
            plugins: {
                legend: {
                    position: 'top',
                    labels: {
                        color: '#888',
                        font: { size: 11 }
                    }
                },
                tooltip: {
                    backgroundColor: 'rgba(0, 0, 0, 0.8)',
                    titleColor: '#fff',
                    bodyColor: '#fff',
                    callbacks: {
                        label: function(context) {
                            if (context.datasetIndex === 0) {
                                return `Equity: ${formatUSDT(context.raw)}`;
                            } else {
                                return `Drawdown: ${context.raw.toFixed(1)}%`;
                            }
                        }
                    }
                }
            },
            scales: {
                x: {
                    display: true,
                    grid: {
                        color: 'rgba(255, 255, 255, 0.05)'
                    },
                    ticks: {
                        color: '#888',
                        maxTicksLimit: 10,
                        maxRotation: 45,
                        minRotation: 45,
                        autoSkip: true,
                        autoSkipPadding: 10
                    }
                },
                y: {
                    type: 'linear',
                    display: true,
                    position: 'left',
                    grid: {
                        color: 'rgba(255, 255, 255, 0.05)'
                    },
                    ticks: {
                        color: '#f39c12',
                        callback: function(value) {
                            return (value / 1000000).toFixed(1) + 'M';
                        }
                    }
                },
                y1: {
                    type: 'linear',
                    display: true,
                    position: 'right',
                    grid: {
                        drawOnChartArea: false
                    },
                    ticks: {
                        color: '#e74c3c',
                        callback: function(value) {
                            return value.toFixed(0) + '%';
                        }
                    },
                    reverse: true,
                    min: 0
                }
            }
        }
    });
}

function renderStrategyBreakdown(strategies) {
    const container = document.getElementById('analytics-strategy-breakdown');
    if (!container) return;

    const strategyEntries = Object.entries(strategies);

    if (strategyEntries.length === 0) {
        container.innerHTML = '';
        return;
    }

    let html = '<h4>Strategy Breakdown</h4><div class="strategy-grid">';

    for (const [name, stats] of strategyEntries) {
        const returnClass = getPnLClass(stats.total_return);

        html += `
            <div class="strategy-card">
                <div class="strategy-name">${escapeHtml(name)}</div>
                <div class="strategy-stats">
                    <div class="stat-item">
                        <span class="label">Trades</span>
                        <span class="value">${stats.total_trades}</span>
                    </div>
                    <div class="stat-item">
                        <span class="label">Win Rate</span>
                        <span class="value">${stats.win_rate}%</span>
                    </div>
                    <div class="stat-item">
                        <span class="label">Return</span>
                        <span class="value ${returnClass}">${formatUSDT(stats.total_return)}</span>
                    </div>
                    <div class="stat-item">
                        <span class="label">Profit Factor</span>
                        <span class="value">${stats.profit_factor}</span>
                    </div>
                </div>
            </div>
        `;
    }

    html += '</div>';
    container.innerHTML = html;
}

// =====================
// Daily Analytics (US6)
// =====================

async function fetchDailyAnalytics(period = '30d') {
    const summaryContainer = document.getElementById('daily-summary');
    const breakdownContainer = document.getElementById('daily-breakdown');

    try {
        if (summaryContainer) {
            summaryContainer.innerHTML = '<p class="loading">Loading daily data...</p>';
        }

        const data = await apiFetch(`/api/analytics/daily?period=${period}`);

        renderDailySummary(data.summary);
        renderDailyChart(data.days);
        renderDailyBreakdown(data.days);
    } catch (error) {
        if (summaryContainer) {
            summaryContainer.innerHTML = `<p class="error-state">Failed to load daily analytics</p>`;
        }
    }
}

function renderDailySummary(summary) {
    const container = document.getElementById('daily-summary');
    if (!container || !summary) return;

    const profitClass = getPnLClass(summary.total_profit);

    container.innerHTML = `
        <div class="summary-card">
            <div class="value">${summary.total_days}</div>
            <div class="label">Trading Days</div>
        </div>
        <div class="summary-card">
            <div class="value ${profitClass}">${formatUSDT(summary.total_profit)}</div>
            <div class="label">Total Profit</div>
        </div>
        <div class="summary-card">
            <div class="value">${summary.total_trades}</div>
            <div class="label">Total Trades</div>
        </div>
        <div class="summary-card">
            <div class="value positive">${summary.profitable_days}</div>
            <div class="label">Profitable Days</div>
        </div>
        <div class="summary-card">
            <div class="value negative">${summary.losing_days}</div>
            <div class="label">Losing Days</div>
        </div>
        <div class="summary-card">
            <div class="value">${summary.total_wins} / ${summary.total_losses}</div>
            <div class="label">Wins / Losses</div>
        </div>
    `;
}

function renderDailyChart(days) {
    const canvas = document.getElementById('daily-pnl-chart');
    if (!canvas) return;

    const ctx = canvas.getContext('2d');

    // Destroy existing chart
    if (analyticsState.dailyChart) {
        analyticsState.dailyChart.destroy();
        analyticsState.dailyChart = null;
    }

    if (!days || days.length === 0) {
        ctx.fillStyle = '#888';
        ctx.font = '14px -apple-system, sans-serif';
        ctx.textAlign = 'center';
        ctx.fillText('No daily data available', canvas.width / 2, canvas.height / 2);
        return;
    }

    const labels = days.map(d => d.date.substring(5)); // MM-DD
    const profits = days.map(d => d.profit);

    // Colors based on profit/loss
    const colors = profits.map(p => p >= 0 ? 'rgba(46, 204, 113, 0.8)' : 'rgba(231, 76, 60, 0.8)');

    analyticsState.dailyChart = new Chart(ctx, {
        type: 'bar',
        data: {
            labels: labels,
            datasets: [{
                label: 'Daily P&L',
                data: profits,
                backgroundColor: colors,
                borderRadius: 4
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false },
                tooltip: {
                    backgroundColor: 'rgba(0, 0, 0, 0.8)',
                    callbacks: {
                        label: function(context) {
                            return `P&L: ${formatUSDT(context.raw)}`;
                        }
                    }
                }
            },
            scales: {
                x: {
                    display: true,
                    grid: { color: 'rgba(255, 255, 255, 0.05)' },
                    ticks: {
                        color: '#888',
                        maxTicksLimit: 15,
                        maxRotation: 45,
                        minRotation: 45,
                        autoSkip: true,
                        autoSkipPadding: 10
                    }
                },
                y: {
                    display: true,
                    grid: { color: 'rgba(255, 255, 255, 0.05)' },
                    ticks: {
                        color: '#888',
                        callback: value => (value / 1000000).toFixed(1) + 'M'
                    }
                }
            }
        }
    });
}

function renderDailyBreakdown(days) {
    const container = document.getElementById('daily-breakdown');
    if (!container) return;

    if (!days || days.length === 0) {
        container.innerHTML = '<p class="no-data">No daily data to display</p>';
        return;
    }

    // Find max profit for bar scaling
    const maxProfit = Math.max(...days.map(d => Math.abs(d.profit)), 1);

    let html = `
        <h4>Daily Breakdown</h4>
        <table class="daily-table">
            <thead>
                <tr>
                    <th>Date</th>
                    <th class="text-right">Trades</th>
                    <th class="text-right">Wins/Losses</th>
                    <th class="text-right">Win Rate</th>
                    <th class="text-right">P&L</th>
                    <th style="width: 100px;"></th>
                </tr>
            </thead>
            <tbody>
    `;

    // Show most recent first
    const sortedDays = [...days].reverse();

    for (const day of sortedDays) {
        const profitClass = getPnLClass(day.profit);
        const barWidth = Math.max(4, (Math.abs(day.profit) / maxProfit) * 80);
        const barClass = day.profit >= 0 ? '' : 'negative';

        html += `
            <tr data-date="${day.date}">
                <td>${day.date}</td>
                <td class="text-right">${day.trades}</td>
                <td class="text-right">${day.wins} / ${day.losses}</td>
                <td class="text-right">${day.win_rate}%</td>
                <td class="text-right profit-cell ${profitClass}">${formatUSDT(day.profit)}</td>
                <td>
                    <div class="daily-bar">
                        <div class="bar ${barClass}" style="width: ${barWidth}px;"></div>
                    </div>
                </td>
            </tr>
        `;
    }

    html += `
            </tbody>
        </table>
    `;

    container.innerHTML = html;

    // Add click handlers for drill-down (optional)
    const rows = container.querySelectorAll('tbody tr');
    rows.forEach(row => {
        row.addEventListener('click', () => {
            const date = row.dataset.date;
            if (date) {
                showDayDetail(date);
            }
        });
    });
}

function showDayDetail(date) {
    // Could expand to show trades/signals for that day
    // For now, just log it
    console.log(`Day detail requested: ${date}`);
    // Future: Could filter history tab or show modal with day's trades
}

// =====================
// Backtest Tab (US5)
// =====================

let backtestState = {
    strategies: [],
    currentJobId: null,
    pollInterval: null,
    chart: null
};

function initBacktest() {
    // Load available strategies
    fetchStrategies();

    // Load backtest history
    loadBacktestHistory();

    // Set up form handlers
    const runBtn = document.getElementById('backtest-run-btn');
    const cancelBtn = document.getElementById('backtest-cancel-btn');

    if (runBtn) {
        runBtn.addEventListener('click', startBacktest);
    }

    if (cancelBtn) {
        cancelBtn.addEventListener('click', cancelBacktest);
    }
}

async function fetchStrategies() {
    const selectEl = document.getElementById('backtest-strategy');
    if (!selectEl) return;

    try {
        const data = await apiFetch('/api/backtest/strategies');
        backtestState.strategies = data.strategies || [];

        // Populate select
        let html = '<option value="">Select strategy...</option>';
        for (const strategy of backtestState.strategies) {
            html += `<option value="${strategy.id}" title="${strategy.description}">${strategy.name}</option>`;
        }
        selectEl.innerHTML = html;
    } catch (error) {
        console.error('Failed to load strategies:', error);
        selectEl.innerHTML = '<option value="">Error loading strategies</option>';
    }
}

async function startBacktest() {
    const strategySelect = document.getElementById('backtest-strategy');
    const startDateInput = document.getElementById('backtest-start-date');
    const endDateInput = document.getElementById('backtest-end-date');
    const capitalInput = document.getElementById('backtest-capital');
    const runBtn = document.getElementById('backtest-run-btn');
    const cancelBtn = document.getElementById('backtest-cancel-btn');
    const progressDiv = document.getElementById('backtest-progress');
    const resultsDiv = document.getElementById('backtest-results');

    // Validate
    const strategy = strategySelect.value;
    if (!strategy) {
        alert('Please select a strategy');
        return;
    }

    const config = {
        strategy: strategy,
        start_date: startDateInput.value,
        end_date: endDateInput.value,
        initial_capital: parseInt(capitalInput.value) || 10000000
    };

    // Update UI
    runBtn.disabled = true;
    runBtn.textContent = 'Running...';
    cancelBtn.style.display = 'inline-block';
    progressDiv.style.display = 'block';
    resultsDiv.style.display = 'none';

    updateBacktestProgress(0, 'Starting backtest...');

    try {
        const data = await apiFetch('/api/backtest/run', {
            method: 'POST',
            body: JSON.stringify(config)
        });

        backtestState.currentJobId = data.job_id;
        pollBacktestStatus(data.job_id);
    } catch (error) {
        console.error('Failed to start backtest:', error);
        resetBacktestUI();
        alert('Failed to start backtest: ' + error.message);
    }
}

function pollBacktestStatus(jobId) {
    // Clear existing interval
    if (backtestState.pollInterval) {
        clearInterval(backtestState.pollInterval);
    }

    const poll = async () => {
        try {
            const data = await apiFetch(`/api/backtest/status/${jobId}`);

            updateBacktestProgress(data.progress, getStatusMessage(data.status, data.progress));

            if (data.status === 'completed') {
                clearInterval(backtestState.pollInterval);
                backtestState.pollInterval = null;
                renderBacktestResults(data.result);
                resetBacktestUI();
                loadBacktestHistory();  // Refresh history list
            } else if (data.status === 'failed') {
                clearInterval(backtestState.pollInterval);
                backtestState.pollInterval = null;
                resetBacktestUI();
                loadBacktestHistory();  // Refresh history list
                alert('Backtest failed: ' + (data.error || 'Unknown error'));
            } else if (data.status === 'cancelled') {
                clearInterval(backtestState.pollInterval);
                backtestState.pollInterval = null;
                resetBacktestUI();
                loadBacktestHistory();  // Refresh history list
            }
        } catch (error) {
            console.error('Poll error:', error);
            clearInterval(backtestState.pollInterval);
            backtestState.pollInterval = null;
            resetBacktestUI();
        }
    };

    // Initial poll
    poll();

    // Poll every 2 seconds
    backtestState.pollInterval = setInterval(poll, 2000);
}

function getStatusMessage(status, progress) {
    switch (status) {
        case 'pending':
            return 'Queued...';
        case 'running':
            if (progress < 30) return 'Loading data...';
            if (progress < 90) return 'Running backtest...';
            return 'Processing results...';
        case 'completed':
            return 'Complete!';
        case 'failed':
            return 'Failed';
        case 'cancelled':
            return 'Cancelled';
        default:
            return status;
    }
}

function updateBacktestProgress(progress, text) {
    const fillEl = document.getElementById('backtest-progress-fill');
    const textEl = document.getElementById('backtest-progress-text');

    if (fillEl) {
        fillEl.style.width = `${progress}%`;
    }
    if (textEl) {
        textEl.textContent = text;
    }
}

async function cancelBacktest() {
    if (!backtestState.currentJobId) return;

    try {
        await apiFetch(`/api/backtest/cancel/${backtestState.currentJobId}`, {
            method: 'POST'
        });
    } catch (error) {
        console.error('Failed to cancel:', error);
    }

    resetBacktestUI();
}

function resetBacktestUI() {
    const runBtn = document.getElementById('backtest-run-btn');
    const cancelBtn = document.getElementById('backtest-cancel-btn');
    const progressDiv = document.getElementById('backtest-progress');

    if (runBtn) {
        runBtn.disabled = false;
        runBtn.textContent = 'Run Backtest';
    }
    if (cancelBtn) {
        cancelBtn.style.display = 'none';
    }
    if (progressDiv) {
        progressDiv.style.display = 'none';
    }

    backtestState.currentJobId = null;
}

function renderBacktestResults(result) {
    const resultsDiv = document.getElementById('backtest-results');
    const metricsDiv = document.getElementById('backtest-metrics');
    const tradesDiv = document.getElementById('backtest-trades');

    if (!result || !resultsDiv) return;

    resultsDiv.style.display = 'block';

    // Render metrics with benchmark comparison
    if (metricsDiv) {
        const returnClass = getPnLClass(result.total_return_pct);
        const benchmarkReturn = result.benchmark_return_pct || 0;
        const benchmarkClass = getPnLClass(benchmarkReturn);
        const outperformance = (result.total_return_pct || 0) - benchmarkReturn;
        const outperformanceClass = outperformance >= 0 ? 'positive' : 'negative';

        metricsDiv.innerHTML = `
            <div class="backtest-metric highlight">
                <div class="value ${returnClass}">${formatPercent(result.total_return_pct)}</div>
                <div class="label">Strategy Return</div>
            </div>
            <div class="backtest-metric">
                <div class="value ${benchmarkClass}">${formatPercent(benchmarkReturn)}</div>
                <div class="label">Buy & Hold</div>
            </div>
            <div class="backtest-metric">
                <div class="value ${outperformanceClass}">${outperformance >= 0 ? '+' : ''}${outperformance.toFixed(2)}%</div>
                <div class="label">vs Benchmark</div>
            </div>
            <div class="backtest-metric">
                <div class="value ${getPnLClass(result.total_return)}">${formatUSDT(result.total_return)}</div>
                <div class="label">Profit (USDT)</div>
            </div>
            <div class="backtest-metric">
                <div class="value">${formatUSDT(result.final_capital)}</div>
                <div class="label">Final Capital</div>
            </div>
            <div class="backtest-metric">
                <div class="value">${result.total_trades}</div>
                <div class="label">Total Trades</div>
            </div>
            <div class="backtest-metric">
                <div class="value">${(result.win_rate || 0).toFixed(1)}%</div>
                <div class="label">Win Rate</div>
            </div>
            <div class="backtest-metric">
                <div class="value">${result.winning_trades} / ${result.losing_trades}</div>
                <div class="label">Wins / Losses</div>
            </div>
            <div class="backtest-metric">
                <div class="value">${result.profit_factor || 0}</div>
                <div class="label">Profit Factor</div>
            </div>
            <div class="backtest-metric">
                <div class="value">${result.sharpe_ratio || 0}</div>
                <div class="label">Sharpe Ratio</div>
            </div>
            <div class="backtest-metric">
                <div class="value negative">${(result.max_drawdown_pct || 0).toFixed(1)}%</div>
                <div class="label">Max Drawdown</div>
            </div>
        `;
    }

    // Render equity curve with benchmark
    renderBacktestEquityCurve(result.equity_curve || [], result.benchmark_curve || []);

    // Render chart image if available
    renderBacktestChartImage(result.chart_path);

    // Render MLflow link if available
    renderMLflowLink(result.mlflow_run_id, result.mlflow_url);

    // Render sample trades
    if (tradesDiv && result.trades) {
        renderBacktestTrades(result.trades);
    }
}

function renderBacktestChartImage(chartPath) {
    const container = document.getElementById('backtest-chart-image');
    if (!container) {
        // Create container if it doesn't exist
        const equityChart = document.getElementById('backtest-equity-chart');
        if (equityChart && chartPath) {
            const imageContainer = document.createElement('div');
            imageContainer.id = 'backtest-chart-image';
            imageContainer.className = 'chart-image-container';
            imageContainer.innerHTML = `
                <h4>Strategy vs Benchmark Chart</h4>
                <img src="${chartPath}" alt="Backtest Chart" style="max-width: 100%; border-radius: 8px;">
                <a href="${chartPath}" target="_blank" class="download-link">Open Full Size</a>
            `;
            equityChart.parentNode.insertBefore(imageContainer, equityChart.nextSibling);
        }
        return;
    }

    if (chartPath) {
        container.innerHTML = `
            <h4>Strategy vs Benchmark Chart</h4>
            <img src="${chartPath}" alt="Backtest Chart" style="max-width: 100%; border-radius: 8px;">
            <a href="${chartPath}" target="_blank" class="download-link">Open Full Size</a>
        `;
        container.style.display = 'block';
    } else {
        container.style.display = 'none';
    }
}

function renderMLflowLink(runId, mlflowUrl) {
    let container = document.getElementById('backtest-mlflow-link');
    if (!container) {
        // Create container if it doesn't exist
        const metricsDiv = document.getElementById('backtest-metrics');
        if (metricsDiv && runId) {
            const linkContainer = document.createElement('div');
            linkContainer.id = 'backtest-mlflow-link';
            linkContainer.className = 'mlflow-link-container';
            metricsDiv.parentNode.insertBefore(linkContainer, metricsDiv.nextSibling);
            container = linkContainer;
        } else {
            return;
        }
    }

    if (runId) {
        container.innerHTML = `
            <div class="mlflow-info">
                <span class="mlflow-label">📊 MLflow Run:</span>
                <code>${runId}</code>
                ${mlflowUrl ? `<br><small>${mlflowUrl}</small>` : ''}
            </div>
        `;
        container.style.display = 'block';
    } else {
        container.style.display = 'none';
    }
}

function renderBacktestEquityCurve(equityData, benchmarkData) {
    const canvas = document.getElementById('backtest-equity-chart');
    if (!canvas) return;

    const ctx = canvas.getContext('2d');

    // Destroy existing chart
    if (backtestState.chart) {
        backtestState.chart.destroy();
        backtestState.chart = null;
    }

    if (!equityData || equityData.length === 0) {
        ctx.fillStyle = '#888';
        ctx.font = '14px -apple-system, sans-serif';
        ctx.textAlign = 'center';
        ctx.fillText('No equity data available', canvas.width / 2, canvas.height / 2);
        return;
    }

    const labels = equityData.map((p, i) => {
        if (p.date) {
            return p.date.substring(5); // MM-DD
        }
        return i.toString();
    });

    const strategyValues = equityData.map(p => p.equity || p.value || p);

    // Build datasets
    const datasets = [{
        label: 'Strategy',
        data: strategyValues,
        borderColor: '#2ecc71',
        backgroundColor: 'rgba(46, 204, 113, 0.1)',
        fill: true,
        tension: 0.2,
        yAxisID: 'y'
    }];

    // Add benchmark if available
    const hasBenchmark = benchmarkData && benchmarkData.length > 0;
    if (hasBenchmark) {
        const benchmarkValues = benchmarkData.map(p => p.equity || p.value || p);
        datasets.push({
            label: 'Buy & Hold',
            data: benchmarkValues,
            borderColor: '#3498db',
            backgroundColor: 'rgba(52, 152, 219, 0.05)',
            fill: false,
            tension: 0.2,
            borderDash: [5, 5],
            yAxisID: 'y1'
        });
    }

    backtestState.chart = new Chart(ctx, {
        type: 'line',
        data: {
            labels: labels,
            datasets: datasets
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: {
                mode: 'index',
                intersect: false
            },
            plugins: {
                legend: {
                    display: hasBenchmark,
                    labels: { color: '#ccc' }
                },
                tooltip: {
                    backgroundColor: 'rgba(0, 0, 0, 0.8)',
                    callbacks: {
                        label: function(context) {
                            const label = context.dataset.label || '';
                            return `${label}: ${formatUSDT(context.raw)}`;
                        }
                    }
                }
            },
            scales: {
                x: {
                    display: true,
                    grid: { color: 'rgba(255, 255, 255, 0.05)' },
                    ticks: {
                        color: '#888',
                        maxTicksLimit: 10,
                        maxRotation: 45,
                        minRotation: 45,
                        autoSkip: true,
                        autoSkipPadding: 10
                    }
                },
                y: {
                    type: 'linear',
                    display: true,
                    position: 'left',
                    grid: { color: 'rgba(255, 255, 255, 0.05)' },
                    ticks: {
                        color: '#2ecc71',
                        callback: value => (value / 1000000).toFixed(1) + 'M'
                    },
                    title: {
                        display: hasBenchmark,
                        text: 'Strategy ($)',
                        color: '#2ecc71'
                    }
                },
                y1: {
                    type: 'linear',
                    display: hasBenchmark,
                    position: 'right',
                    grid: { drawOnChartArea: false },
                    ticks: {
                        color: '#3498db',
                        callback: value => (value / 1000000).toFixed(1) + 'M'
                    },
                    title: {
                        display: hasBenchmark,
                        text: 'Buy & Hold ($)',
                        color: '#3498db'
                    }
                }
            }
        }
    });
}

function renderBacktestTrades(trades) {
    const container = document.getElementById('backtest-trades');
    if (!container) return;

    if (!trades || trades.length === 0) {
        container.innerHTML = '<p class="no-data">No trades to display</p>';
        return;
    }

    let html = `
        <table class="data-table">
            <thead>
                <tr>
                    <th>Date</th>
                    <th>Symbol</th>
                    <th>Action</th>
                    <th class="text-right">Price</th>
                    <th class="text-right">P&L</th>
                </tr>
            </thead>
            <tbody>
    `;

    // Show first 20 trades
    const displayTrades = trades.slice(0, 20);
    for (const trade of displayTrades) {
        const actionClass = (trade.action || '').toLowerCase();
        const pnlClass = getPnLClass(trade.profit);
        const symbolDisplay = trade.symbol || '-';

        html += `
            <tr>
                <td>${formatDate(trade.timestamp || trade.date)}</td>
                <td><span class="symbol-badge">${escapeHtml(symbolDisplay)}</span></td>
                <td><span class="action-badge ${actionClass}">${escapeHtml(trade.action) || '-'}</span></td>
                <td class="text-right">${formatPrice(trade.price, true)}</td>
                <td class="text-right ${pnlClass}">
                    ${trade.profit !== undefined && trade.profit !== null ? formatUSDT(trade.profit) : '-'}
                </td>
            </tr>
        `;
    }

    html += `
            </tbody>
        </table>
    `;

    if (trades.length > 20) {
        html += `<p class="no-data" style="margin-top: 10px;">Showing 20 of ${trades.length} trades</p>`;
    }

    container.innerHTML = html;
}

// Backtest History Functions
async function loadBacktestHistory() {
    const container = document.getElementById('backtest-history-list');
    if (!container) return;

    try {
        const data = await apiFetch('/api/backtest/history');
        const jobs = data.jobs || [];

        if (jobs.length === 0) {
            container.innerHTML = '<p class="no-data">No backtest history</p>';
            return;
        }

        let html = '';
        for (const job of jobs) {
            const strategy = job.config?.strategy || 'Unknown';
            const date = job.created_at ? new Date(job.created_at).toLocaleString() : '-';
            const metrics = job.metrics || {};
            const returnPct = metrics.total_return_pct || 0;
            const returnClass = returnPct >= 0 ? 'positive' : 'negative';
            const statusClass = job.status || 'pending';

            html += `
                <div class="backtest-history-item" data-job-id="${job.job_id}" onclick="loadBacktestJob('${job.job_id}')">
                    <div class="history-item-info">
                        <span class="history-item-strategy">${escapeHtml(strategy)}</span>
                        <span class="history-item-date">${escapeHtml(date)}</span>
                    </div>
                    <div class="history-item-metrics">
                        ${job.status === 'completed' ? `
                            <span class="history-item-return ${returnClass}">${returnPct >= 0 ? '+' : ''}${returnPct.toFixed(2)}%</span>
                        ` : ''}
                        <span class="history-item-status ${statusClass}">${job.status}</span>
                    </div>
                </div>
            `;
        }

        container.innerHTML = html;
    } catch (error) {
        console.error('Failed to load backtest history:', error);
        container.innerHTML = '<p class="no-data">Failed to load history</p>';
    }
}

async function loadBacktestJob(jobId) {
    try {
        const data = await apiFetch(`/api/backtest/status/${jobId}`);

        if (data.status === 'completed' && data.result) {
            renderBacktestResults(data.result);

            // Highlight active item
            document.querySelectorAll('.backtest-history-item').forEach(el => {
                el.classList.remove('active');
            });
            const activeItem = document.querySelector(`[data-job-id="${jobId}"]`);
            if (activeItem) {
                activeItem.classList.add('active');
            }
        }
    } catch (error) {
        console.error('Failed to load backtest job:', error);
    }
}

console.log('Multi-Asset Dashboard initialized');
