/**
 * Multi-Asset Trading Bot Dashboard
 * Real-time status monitoring for Multi-Asset Engine
 */

const REFRESH_INTERVAL = 30000; // 30 seconds
const STALE_THRESHOLD = 60000; // 60 seconds - data considered stale
const MAX_RETRIES = 3;
const RETRY_DELAY = 2000; // 2 seconds
const STATUS_ENDPOINT = '/api/status';

const DASHBOARD_CONFIG = window.DASHBOARD_CONFIG || {};
const API_BASE = normalizeApiBase(DASHBOARD_CONFIG.apiBase || '');

// Track last successful fetch times
let lastFetchTimes = {};

// Price history for sparklines (symbol -> array of prices)
const priceHistory = {};
const PRICE_HISTORY_LENGTH = 60; // Keep last 60 data points

// Entry prices for position indicators (symbol -> entry price)
const entryPrices = {};
const MARKET_SNAPSHOT_FOCUS_LIMIT = 16;

let marketSnapshotExpanded = false;
let selectorFocusSymbols = new Set();
let latestStatusPayload = null;

function normalizeApiBase(base) {
    const trimmed = String(base || '').trim();
    if (!trimmed || trimmed === '/') {
        return '';
    }
    return `/${trimmed.replace(/^\/+|\/+$/g, '')}`;
}

function resolveApiEndpoint(endpoint) {
    if (/^https?:\/\//i.test(endpoint)) {
        return endpoint;
    }
    if (!endpoint.startsWith('/')) {
        return `${API_BASE}/${endpoint}`;
    }
    return `${API_BASE}${endpoint}`;
}

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
        const response = await fetch(resolveApiEndpoint(endpoint), mergedOptions);

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

function normalizeBinancePair(symbol) {
    const cleaned = String(symbol || '')
        .trim()
        .toUpperCase()
        .replace(/[^A-Z0-9]/g, '');
    if (!cleaned) {
        return { base: '', quote: 'USDT', pair: 'BTCUSDT' };
    }

    const knownQuotes = [
        'FDUSD', 'USDT', 'USDC', 'BUSD', 'TUSD', 'BTC', 'ETH', 'BNB',
        'TRY', 'BRL', 'EUR', 'GBP', 'DAI', 'RUB', 'JPY', 'AUD', 'UAH', 'USD',
    ];

    for (const quote of knownQuotes) {
        if (cleaned.length > quote.length && cleaned.endsWith(quote)) {
            const base = cleaned.slice(0, -quote.length);
            return { base, quote, pair: `${base}${quote}` };
        }
    }

    return { base: cleaned, quote: 'USDT', pair: `${cleaned}USDT` };
}

function getBinanceChartUrl(symbol, market = 'spot') {
    const { base, quote, pair } = normalizeBinancePair(symbol);
    if (!base) {
        return 'https://www.binance.com/en/markets';
    }
    const isFutures = String(market || '').toLowerCase() === 'futures';

    if (isFutures) {
        if (quote === 'USD' && base) {
            return `https://www.binance.com/en/futures/${base}USD_PERP`;
        }
        return `https://www.binance.com/en/futures/${pair}`;
    }

    const spotQuote = quote === 'USD' ? 'USDT' : quote;
    return `https://www.binance.com/en/trade/${base}_${spotQuote}?type=spot`;
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

    const statusFetchTime = lastFetchTimes[STATUS_ENDPOINT];
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

// Format entry time from Unix timestamp (ms) with relative time
function formatEntryTime(timestamp) {
    if (!timestamp || timestamp === 0) return '-';
    const date = new Date(timestamp);
    const now = new Date();
    const diffMs = now - date;
    const diffHours = Math.floor(diffMs / (1000 * 60 * 60));
    const diffDays = Math.floor(diffHours / 24);

    let relativeStr;
    if (diffDays > 0) {
        relativeStr = `${diffDays}d ${diffHours % 24}h ago`;
    } else if (diffHours > 0) {
        relativeStr = `${diffHours}h ago`;
    } else {
        const diffMins = Math.floor(diffMs / (1000 * 60));
        relativeStr = `${diffMins}m ago`;
    }

    const dateStr = date.toLocaleString('ko-KR', {
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit'
    });

    return `${dateStr} (${relativeStr})`;
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

// Format Unix timestamp (ms) to short date (MM/DD HH:mm)
function formatEntryTime(timestampMs) {
    if (!timestampMs || timestampMs === 0) return '-';
    const date = new Date(timestampMs);
    const month = String(date.getMonth() + 1).padStart(2, '0');
    const day = String(date.getDate()).padStart(2, '0');
    const hours = String(date.getHours()).padStart(2, '0');
    const minutes = String(date.getMinutes()).padStart(2, '0');
    return `${month}/${day} ${hours}:${minutes}`;
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

// Normalize symbol to base asset format (e.g., BTCUSDT -> BTC)
function normalizeSymbol(symbol) {
    if (!symbol) return '';
    let normalized = String(symbol).trim().toUpperCase();

    if (normalized.includes('/')) {
        normalized = normalized.split('/')[0];
    }
    if (normalized.includes(':')) {
        normalized = normalized.split(':')[0];
    }

    for (const suffix of ['USDT', 'BUSD', 'USDC', 'USD']) {
        if (normalized.endsWith(suffix) && normalized.length > suffix.length) {
            return normalized.slice(0, -suffix.length);
        }
    }

    return normalized;
}

// Merge assets, prices, and regime status for consistent market snapshot cards.
function buildAssetCardsData(statusData) {
    const assets = statusData.assets || {};
    const prices = statusData.prices || {};
    const regimeStatus = statusData.regime_status || {};
    const cards = {};

    for (const [key, asset] of Object.entries(assets)) {
        const symbol = normalizeSymbol(asset.symbol || key);
        if (!symbol) continue;

        const regimeInfo = regimeStatus[symbol] || {};
        const fallbackPrice = prices[symbol] ?? prices[`${symbol}USDT`] ?? 0;

        cards[key] = {
            ...asset,
            symbol,
            exchange: asset.exchange || 'binance',
            price: Number(asset.price || fallbackPrice || 0),
            regime: asset.regime || regimeInfo.regime || 'UNKNOWN',
            trend: asset.trend || regimeInfo.trend || 'UNKNOWN',
            regime_updated_at: asset.regime_updated_at || regimeInfo.timestamp || '',
        };
    }

    if (Object.keys(cards).length > 0) {
        return cards;
    }

    const snapshotSymbols = new Set();
    for (const key of Object.keys(prices)) {
        const symbol = normalizeSymbol(key);
        if (symbol) snapshotSymbols.add(symbol);
    }
    for (const key of Object.keys(regimeStatus)) {
        const symbol = normalizeSymbol(key);
        if (symbol) snapshotSymbols.add(symbol);
    }

    const orderedSymbols = Array.from(snapshotSymbols).sort();
    for (const symbol of orderedSymbols) {
        const regimeInfo = regimeStatus[symbol] || {};
        cards[`${symbol}_snapshot`] = {
            symbol,
            exchange: 'binance',
            market: 'snapshot',
            enabled: true,
            price: Number(prices[symbol] ?? prices[`${symbol}USDT`] ?? 0),
            position_active: false,
            position_qty: 0,
            direction: 'long',
            strategy: '-',
            regime: regimeInfo.regime || 'UNKNOWN',
            trend: regimeInfo.trend || 'UNKNOWN',
            regime_updated_at: regimeInfo.timestamp || '',
        };
    }

    return cards;
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

// Draw sparkline chart on canvas with optional entry price indicator
function drawSparkline(canvasId, data, entryPrice = null) {
    const canvas = document.getElementById(canvasId);
    if (!canvas || !data || data.length < 1) return;

    // Get actual rendered size from bounding rect
    const rect = canvas.getBoundingClientRect();
    const width = Math.round(rect.width);
    const height = Math.round(rect.height);

    // Skip if canvas has no dimensions yet
    if (width <= 0 || height <= 0) return;

    // Set canvas internal resolution to match CSS display size
    canvas.width = width;
    canvas.height = height;

    const ctx = canvas.getContext('2d');
    const padding = 4;

    // Clear canvas
    ctx.clearRect(0, 0, width, height);

    // Find min/max for scaling (include entry price if present)
    let min = Math.min(...data);
    let max = Math.max(...data);
    if (entryPrice && entryPrice > 0) {
        min = Math.min(min, entryPrice);
        max = Math.max(max, entryPrice);
    }
    // Add some padding to range if flat
    if (max === min) {
        const pad = min * 0.001 || 1;
        min -= pad;
        max += pad;
    }
    const range = max - min;

    // Calculate points
    const stepX = data.length > 1 ? (width - padding * 2) / (data.length - 1) : 0;
    const points = data.map((val, i) => ({
        x: padding + i * stepX,
        y: height - padding - ((val - min) / range) * (height - padding * 2)
    }));

    // Determine line color based on trend
    const isUp = data.length > 1 ? data[data.length - 1] >= data[0] : true;
    const lineColor = isUp ? '#3fb950' : '#f85149';

    // Draw entry price indicator line (dashed horizontal line)
    if (entryPrice && entryPrice > 0) {
        const entryY = height - padding - ((entryPrice - min) / range) * (height - padding * 2);
        ctx.beginPath();
        ctx.setLineDash([4, 2]);
        ctx.moveTo(padding, entryY);
        ctx.lineTo(width - padding, entryY);
        ctx.strokeStyle = '#f0c000'; // Yellow/gold for entry price
        ctx.lineWidth = 1;
        ctx.stroke();
        ctx.setLineDash([]); // Reset dash

        // Draw small "E" label at the right end
        ctx.font = '8px monospace';
        ctx.fillStyle = '#f0c000';
        ctx.fillText('E', width - 10, entryY - 2);
    }

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
    ctx.arc(lastPoint.x, lastPoint.y, 4, 0, Math.PI * 2);
    ctx.fillStyle = lineColor;
    ctx.fill();
}

// Draw all sparklines for assets
function drawAllSparklines() {
    for (const symbol of Object.keys(priceHistory)) {
        const canvasId = `sparkline-${symbol.toLowerCase()}`;
        const entryPrice = entryPrices[symbol] || null;
        drawSparkline(canvasId, priceHistory[symbol], entryPrice);
    }
}

function initAssetCardToggle() {
    const toggle = document.getElementById('asset-card-toggle');
    if (!toggle) return;
    toggle.addEventListener('click', () => {
        marketSnapshotExpanded = !marketSnapshotExpanded;
        if (!latestStatusPayload) return;
        const assetCardsData = buildAssetCardsData(latestStatusPayload);
        renderAssetCards(assetCardsData);
    });
}

function getAssetPriority(asset, symbol) {
    if (asset.position_active) return 0;
    if (selectorFocusSymbols.has(symbol)) return 1;

    const regime = String(asset.regime || '').toUpperCase();
    if (regime.startsWith('BULL')) return 2;
    if (regime.startsWith('SIDEWAYS')) return 3;
    if (regime.startsWith('BEAR')) return 4;
    return 5;
}

function compareAssetCards(a, b) {
    if (a.priority !== b.priority) {
        return a.priority - b.priority;
    }

    const aPnl = Math.abs(Number(a.asset.unrealized_pnl_pct || 0));
    const bPnl = Math.abs(Number(b.asset.unrealized_pnl_pct || 0));
    if (bPnl !== aPnl) {
        return bPnl - aPnl;
    }

    return a.symbol.localeCompare(b.symbol);
}

function updateAssetCardControls(totalCount, visibleCount) {
    const metaEl = document.getElementById('asset-card-meta');
    const toggleEl = document.getElementById('asset-card-toggle');

    if (metaEl) {
        if (totalCount <= 0) {
            metaEl.textContent = 'No symbols';
        } else if (totalCount > visibleCount) {
            metaEl.textContent = `${visibleCount}/${totalCount} shown (focus)`;
        } else {
            metaEl.textContent = `All ${totalCount} shown`;
        }
    }

    if (!toggleEl) return;
    if (totalCount <= MARKET_SNAPSHOT_FOCUS_LIMIT) {
        toggleEl.style.display = 'none';
        return;
    }
    toggleEl.style.display = '';
    toggleEl.textContent = marketSnapshotExpanded ? 'Show Focus' : `Show All (${totalCount})`;
}

function buildSelectorFocusSet(strategies) {
    const next = new Set();
    for (const strategy of strategies) {
        const selectedSymbols = strategy.selector_state?.selected_symbols;
        if (!Array.isArray(selectedSymbols)) continue;
        for (const raw of selectedSymbols) {
            const symbol = normalizeSymbol(raw);
            if (symbol) next.add(symbol);
        }
    }
    return next;
}

// Render asset cards (exchange-aware)
function renderAssetCards(assets) {
    const container = document.getElementById('assets-grid');
    if (!container) return;

    if (!assets || Object.keys(assets).length === 0) {
        updateAssetCardControls(0, 0);
        container.innerHTML = '<p class="no-data">No assets available</p>';
        return;
    }

    const orderedCards = Object.entries(assets)
        .map(([key, asset]) => {
            const symbol = normalizeSymbol(asset.symbol || key);
            return {
                key,
                symbol,
                asset,
                priority: getAssetPriority(asset, symbol),
            };
        })
        .sort(compareAssetCards);

    const totalCount = orderedCards.length;
    const visibleCards = marketSnapshotExpanded
        ? orderedCards
        : orderedCards.slice(0, MARKET_SNAPSHOT_FOCUS_LIMIT);

    updateAssetCardControls(totalCount, visibleCards.length);

    let html = '';
    for (const card of visibleCards) {
        const data = card.asset;
        const symbol = card.symbol;
        const regimeClass = getRegimeClass(data.regime) || 'regime-unknown';
        const regimeLabel = getRegimeLabel(data.regime || 'UNKNOWN');
        const exchange = (data.exchange || 'binance').toLowerCase();
        const exchangeClass = `exchange-${exchange}`;

        // Update price history for sparkline
        updatePriceHistory(symbol, data.price);

        // Position status and entry price tracking
        let positionStatus = 'None';
        let positionClass = '';
        if (data.position_active) {
            positionClass = 'has-position';
            positionStatus = data.direction === 'short' ? 'SHORT' : 'LONG';
            // Store entry price for sparkline indicator
            if (data.entry_price && data.entry_price > 0) {
                entryPrices[symbol] = data.entry_price;
            }
        } else {
            // Clear entry price when no position
            delete entryPrices[symbol];
        }

        // Get active strategy from strategies config
        let activeStrategy = typeof data.strategy === 'string' ? data.strategy.trim() : data.strategy;
        const isMissingStrategy = !activeStrategy || activeStrategy === '-' || String(activeStrategy).toLowerCase() === 'none';
        if (isMissingStrategy) {
            if (data.strategies) {
                const regimeKey = data.regime?.split('_')[0] || 'BULL';
                activeStrategy = data.strategies[regimeKey] || '-';
            } else {
                activeStrategy = '-';
            }
        }

        // Format price (USDT)
        const priceDisplay = `$${formatPrice(data.price, false)}`;

        // Direction indicator
        const directionClass = data.direction === 'short' ? 'direction-short' : 'direction-long';

        // Calculate price change percentage if we have history
        let priceChange = '';
        const history = priceHistory[symbol];
        if (history && history.length >= 2) {
            const firstPrice = history[0];
            const lastPrice = history[history.length - 1];
            const changePct = ((lastPrice - firstPrice) / firstPrice) * 100;
            const changeClass = changePct >= 0 ? 'positive' : 'negative';
            priceChange = `<span class="price-change ${changeClass}">${changePct >= 0 ? '+' : ''}${changePct.toFixed(2)}%</span>`;
        }

        // Sparkline canvas ID
        const sparklineId = `sparkline-${symbol.toLowerCase()}`;

        html += `
            <div class="asset-card ${regimeClass} ${positionClass} ${exchangeClass}">
                <div class="asset-header">
                    <span class="asset-symbol">${escapeHtml(symbol)}</span>
                    <span class="asset-exchange">${escapeHtml(exchange.toUpperCase())}</span>
                    <span class="asset-regime ${regimeClass}">${escapeHtml(regimeLabel)}</span>
                </div>
                <div class="asset-chart">
                    <canvas id="${sparklineId}"></canvas>
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
                        <span class="label">Regime</span>
                        <span class="value"><span class="regime-badge ${regimeClass}">${escapeHtml(data.regime || 'UNKNOWN')}</span></span>
                    </div>
                    <div class="info-row">
                        <span class="label">Strategy</span>
                        <span class="value">${escapeHtml(activeStrategy)}</span>
                    </div>
                    <div class="info-row">
                        <span class="label">Position</span>
                        <span class="value ${positionClass} ${directionClass}">${positionStatus}</span>
                    </div>
                    ${data.regime_updated_at ? `
                    <div class="info-row">
                        <span class="label">Regime At</span>
                        <span class="value">${formatDateTime(data.regime_updated_at)}</span>
                    </div>
                    ` : ''}
                    ${data.position_active ? `
                    <div class="info-row">
                        <span class="label">Qty</span>
                        <span class="value">${Number(data.position_qty || 0).toFixed(6)}</span>
                    </div>
                    <div class="info-row">
                        <span class="label">Entry</span>
                        <span class="value entry-price">$${formatPrice(data.entry_price, false)}</span>
                    </div>
                    <div class="info-row">
                        <span class="label">Opened</span>
                        <span class="value entry-time">${formatEntryTime(data.entry_time)}</span>
                    </div>
                    <div class="info-row">
                        <span class="label">PnL</span>
                        <span class="value ${data.unrealized_pnl >= 0 ? 'positive' : 'negative'}">${formatUSD(data.unrealized_pnl)} (${data.unrealized_pnl_pct >= 0 ? '+' : ''}${(data.unrealized_pnl_pct || 0).toFixed(2)}%)</span>
                    </div>
                    ` : ''}
                </div>
            </div>
        `;
    }
    container.innerHTML = html;

    // Draw sparklines after DOM update - needs time for layout
    setTimeout(() => {
        drawAllSparklines();
    }, 100);
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
    latestStatusPayload = data;

    document.getElementById('last-update-time').textContent = formatTime(data.timestamp);
    document.getElementById('engine-mode').textContent = (data.mode || 'paper').toUpperCase();
    document.getElementById('iteration-count').textContent = data.iteration_count || 0;

    // Update portfolio
    updatePortfolio(data.portfolio);

    // Render market snapshot cards using merged assets/prices/regime status
    const assetCardsData = buildAssetCardsData(data);
    renderAssetCards(assetCardsData);
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
        const data = await apiFetch(STATUS_ENDPOINT);
        updateStatus(data);
    } catch (err) {
        console.error('Status fetch error:', err);
    }
}

// Fetch and update kill switch
async function fetchKillSwitch() {
    try {
        const data = await apiFetch('/api/kill_switch/status');
        updateKillSwitch(data);
    } catch (err) {
        console.error('Kill switch fetch error:', err);
    }
}

// Update exchange balances display
function updateExchangeBalances(data) {
    if (!data.binance) {
        document.getElementById('futures-status').textContent = 'Error';
        document.getElementById('futures-status').className = 'exchange-status error';
        return;
    }

    const binance = data.binance;
    const spot = binance.spot || {};

    document.getElementById('spot-status').textContent = 'Connected';
    document.getElementById('spot-status').className = 'exchange-status connected';
    document.getElementById('spot-balance').textContent = formatUSD(spot.usdt_balance || 0);
    document.getElementById('spot-positions-count').textContent = (spot.positions || []).length;

    const futures = binance.futures || {};
    document.getElementById('futures-status').textContent = 'Connected';
    document.getElementById('futures-status').className = 'exchange-status connected';
    document.getElementById('futures-usdt').textContent = formatUSD(futures.usdt_balance || 0);

    // Unrealized PnL with color
    const unrealizedPnlEl = document.getElementById('futures-unrealized-pnl');
    const unrealizedPnl = futures.unrealized_pnl || 0;
    unrealizedPnlEl.textContent = formatUSD(unrealizedPnl);
    unrealizedPnlEl.className = `value ${unrealizedPnl >= 0 ? 'positive' : 'negative'}`;

    document.getElementById('futures-positions-count').textContent = (futures.positions || []).length;
    document.getElementById('futures-total').textContent = formatUSD(futures.total || 0);

    // Hedge mode badge
    const hedgeBadge = document.getElementById('hedge-mode-badge');
    if (futures.hedge_mode) {
        hedgeBadge.style.display = 'inline-block';
    } else {
        hedgeBadge.style.display = 'none';
    }

    const totalEquity = binance.total_equity || 0;
    const totalUnrealizedPnl = futures.unrealized_pnl || 0;
    const spotPositionValue = spot.position_value || 0;
    const futuresPositionValue = futures.position_value || 0;
    const totalPositionValue = spotPositionValue + futuresPositionValue;
    const exposurePct = totalEquity > 0 ? (totalPositionValue / totalEquity * 100) : 0;

    document.getElementById('total-equity').textContent = formatUSD(totalEquity);
    document.getElementById('total-capital').textContent = formatUSD(totalEquity);
    document.getElementById('total-value').textContent = formatUSD(totalEquity);
    document.getElementById('exposure-pct').textContent = `${exposurePct.toFixed(1)}%`;

    const portfolioPnlEl = document.getElementById('unrealized-pnl');
    portfolioPnlEl.textContent = formatUSD(totalUnrealizedPnl);
    portfolioPnlEl.className = `value ${totalUnrealizedPnl >= 0 ? 'positive' : 'negative'}`;

    // Show errors if any
    if (data.errors && data.errors.length > 0) {
        console.warn('Exchange balance errors:', data.errors);
    }
}

// Fetch exchange balances (hybrid: spot + futures)
async function fetchExchangeBalances() {
    try {
        const data = await apiFetch('/api/summary');
        updateHybridSummary(data);
    } catch (err) {
        console.error('Summary fetch error:', err);
        // Fallback to old API for backwards compatibility
        try {
            const data = await apiFetch('/api/exchange_balances');
            updateExchangeBalances(data);
        } catch (fallbackErr) {
            console.error('Fallback exchange balances fetch error:', fallbackErr);
            document.getElementById('futures-status').textContent = 'Error';
            document.getElementById('futures-status').className = 'exchange-status error';
        }
    }
}

// Update hybrid summary (spot + futures)
function updateHybridSummary(data) {
    // Total equity
    document.getElementById('total-equity').textContent = formatUSD(data.total_equity || 0);

    // Spot card
    const spot = data.spot || {};
    document.getElementById('spot-status').textContent = 'Connected';
    document.getElementById('spot-status').className = 'exchange-status connected';
    document.getElementById('spot-balance').textContent = formatUSD(spot.balance || 0);
    document.getElementById('spot-positions-count').textContent = spot.positions || 0;

    // Futures card
    const futures = data.futures || {};
    document.getElementById('futures-status').textContent = 'Connected';
    document.getElementById('futures-status').className = 'exchange-status connected';
    document.getElementById('futures-usdt').textContent = formatUSD(futures.balance || 0);

    const unrealizedPnlEl = document.getElementById('futures-unrealized-pnl');
    const unrealizedPnl = futures.unrealized_pnl || 0;
    unrealizedPnlEl.textContent = formatUSD(unrealizedPnl);
    unrealizedPnlEl.className = `value ${unrealizedPnl >= 0 ? 'positive' : 'negative'}`;

    document.getElementById('futures-positions-count').textContent = futures.positions || 0;
    document.getElementById('futures-total').textContent = formatUSD(futures.total || 0);

    // Hedge mode badge (futures)
    const hedgeBadge = document.getElementById('hedge-mode-badge');
    if (futures.hedge_mode) {
        hedgeBadge.style.display = 'inline-block';
    } else {
        hedgeBadge.style.display = 'none';
    }

    // Update portfolio summary
    const totalEquity = data.total_equity || 0;
    const totalUnrealizedPnl = unrealizedPnl; // Currently only futures has unrealized PnL

    document.getElementById('total-capital').textContent = formatUSD(totalEquity);
    document.getElementById('total-value').textContent = formatUSD(totalEquity);

    const portfolioPnlEl = document.getElementById('unrealized-pnl');
    portfolioPnlEl.textContent = formatUSD(totalUnrealizedPnl);
    portfolioPnlEl.className = `value ${totalUnrealizedPnl >= 0 ? 'positive' : 'negative'}`;

    const spotPositionValue = spot.position_value || 0;
    let futuresPositionValue = futures.position_value;
    if (futuresPositionValue === undefined || futuresPositionValue === null) {
        futuresPositionValue = (data.positions || [])
            .filter((pos) => pos.market === 'futures')
            .reduce((acc, pos) => acc + (Math.abs(pos.quantity || 0) * (pos.current_price || 0)), 0);
    }
    const totalPositionValue = spotPositionValue + (futuresPositionValue || 0);
    const exposurePct = totalEquity > 0 ? (totalPositionValue / totalEquity * 100) : 0;
    document.getElementById('exposure-pct').textContent = `${exposurePct.toFixed(1)}%`;
}

// Fetch leverage state
async function fetchLeverageState() {
    try {
        const data = await apiFetch('/api/metrics/leverage');
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

async function fetchSelectorSnapshot() {
    const contentEl = document.getElementById('selector-snapshot-content');
    const updatedEl = document.getElementById('selector-snapshot-updated');
    if (!contentEl) return;

    try {
        const data = await apiFetch('/api/strategies');
        const strategies = Array.isArray(data.strategies) ? data.strategies : [];
        const selectorStrategies = strategies.filter(
            (strategy) => strategy.symbol_selector && strategy.symbol_selector.enabled
        );
        selectorFocusSymbols = buildSelectorFocusSet(selectorStrategies);
        if (latestStatusPayload) {
            const cards = buildAssetCardsData(latestStatusPayload);
            renderAssetCards(cards);
        }

        if (selectorStrategies.length === 0) {
            contentEl.innerHTML = '<p class="selector-snapshot-empty">No enabled selector strategies.</p>';
            if (updatedEl) updatedEl.textContent = '-';
            return;
        }

        const latestTimestamp = selectorStrategies
            .map((strategy) => strategy.selector_state?.timestamp)
            .filter((timestamp) => Boolean(timestamp))
            .sort()
            .pop();

        contentEl.innerHTML = selectorStrategies.map((strategy) => {
            const state = strategy.selector_state || {};
            const selectedSymbols = Array.isArray(state.selected_symbols) ? state.selected_symbols : [];
            const topScores = Array.isArray(state.top_scores) ? state.top_scores : [];
            const scoreText = topScores
                .slice(0, 3)
                .map((item) => `${escapeHtml(item.symbol)}:${Number(item.score ?? 0).toFixed(3)}`)
                .join(', ');

            return `
                <div class="selector-snapshot-item">
                    <div class="selector-snapshot-line">
                        <span class="strategy-name">${escapeHtml(strategy.name)}</span>
                        <span class="selector-chip ${state.changed ? 'selected' : ''}">${state.changed ? 'changed' : 'stable'}</span>
                    </div>
                    <div class="selector-snapshot-line">
                        <span class="selector-snapshot-label">Selected</span>
                        <span>${selectedSymbols.length > 0 ? selectedSymbols.map(escapeHtml).join(', ') : '-'}</span>
                    </div>
                    <div class="selector-snapshot-line">
                        <span class="selector-snapshot-label">Top score</span>
                        <span>${scoreText || '-'}</span>
                    </div>
                </div>
            `;
        }).join('');

        if (updatedEl) {
            updatedEl.textContent = latestTimestamp ? `Updated ${formatDateTime(latestTimestamp)}` : 'Updated -';
        }
    } catch (error) {
        console.error('Selector snapshot fetch error:', error);
        contentEl.innerHTML = '<p class="error">Failed to load selector snapshot.</p>';
        if (updatedEl) updatedEl.textContent = '-';
    }
}

// Fetch all data
async function fetchAll() {
    await Promise.all([
        fetchStatus(),
        fetchKillSwitch(),
        fetchExchangeBalances(),
        fetchLeverageState(),
        fetchSelectorSnapshot(),
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

    // Initialize market filter tabs
    initMarketFilterTabs();
    initAssetCardToggle();

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
        } else if (isTabActive('strategies')) {
            fetchStrategiesTab();
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
        '5': 'backtest',
        '6': 'strategies'
    };

    document.addEventListener('keydown', (e) => {
        // Don't trigger shortcuts when typing in input fields
        if (e.target.tagName === 'INPUT' || e.target.tagName === 'SELECT' || e.target.tagName === 'TEXTAREA') {
            return;
        }

        // Tab navigation with number keys (1-6)
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
        case 'analytics':
            fetchAnalytics(analyticsState.period);
            break;
        case 'backtest':
            // Strategies are loaded on init, but refresh if empty
            if (backtestState.strategies.length === 0) {
                fetchStrategies();
            }
            break;
        case 'strategies':
            fetchStrategiesTab();
            break;
    }
}

// =====================
// Positions Tab (US1)
// =====================

let positionsData = null;

// Initialize market filter tabs
function initMarketFilterTabs() {
    const marketTabs = document.querySelectorAll('.market-tab');

    marketTabs.forEach(tab => {
        tab.addEventListener('click', () => {
            const market = tab.dataset.market;

            // Update active tab
            marketTabs.forEach(t => t.classList.remove('active'));
            tab.classList.add('active');

            // Filter positions
            filterPositionsByMarket(market);
        });
    });
}

// Filter positions by market (all, spot, futures)
function filterPositionsByMarket(market) {
    const positionCards = document.querySelectorAll('.position-card');

    positionCards.forEach(card => {
        if (market === 'all' || card.dataset.market === market) {
            card.style.display = '';
        } else {
            card.style.display = 'none';
        }
    });
}

async function fetchPositions() {
    const containerId = 'positions-container';

    try {
        renderLoading(containerId);

        // /api/positions is authoritative in both paper/live modes.
        // Keep spot endpoint as fallback only when spot positions are missing.
        const [positionsDataRaw, spotData] = await Promise.all([
            apiFetch('/api/positions').catch(err => {
                console.error('Positions fetch error:', err);
                return { positions: [], total_value: 0, total_unrealized_pnl: 0 };
            }),
            apiFetch('/api/spot/positions').catch(err => {
                console.error('Spot positions fetch error:', err);
                return { positions: [], count: 0 };
            })
        ]);

        const normalizePosition = (pos, fallbackMarket = null) => {
            const market = String(pos.market || fallbackMarket || '').toLowerCase();
            return {
                ...pos,
                market: market === 'spot' ? 'spot' : 'futures',
                exchange: pos.exchange || 'binance',
            };
        };

        const dedupePositions = (positions) => {
            const deduped = [];
            const seen = new Set();
            for (const pos of positions) {
                const key = [
                    String(pos.symbol || '').toUpperCase(),
                    String(pos.market || '').toLowerCase(),
                    String(pos.side || '').toUpperCase(),
                ].join('|');
                if (seen.has(key)) continue;
                seen.add(key);
                deduped.push(pos);
            }
            return deduped;
        };

        const mergedPositions = (positionsDataRaw.positions || []).map((p) => normalizePosition(p));
        const hasSpotInPrimary = mergedPositions.some((p) => p.market === 'spot');
        const fallbackSpotPositions = hasSpotInPrimary
            ? []
            : (spotData.positions || []).map((p) => normalizePosition(p, 'spot'));
        const allPositions = dedupePositions([...mergedPositions, ...fallbackSpotPositions]);

        // Combined data
        const combinedData = {
            positions: allPositions,
            total_value: Number(positionsDataRaw.total_value || 0),
            total_unrealized_pnl: Number(positionsDataRaw.total_unrealized_pnl || 0),
        };

        positionsData = combinedData;
        renderPositions(combinedData);
        updatePositionsSummary(combinedData);
    } catch (error) {
        console.error('Positions fetch error:', error);
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

    // Render all positions (spot + futures)
    for (const pos of data.positions) {
        const pnlClass = getPnLClass(pos.unrealized_pnl);
        const sideRaw = String(pos.side || 'LONG');
        const sideClass = sideRaw.toLowerCase();
        const market = pos.market || 'futures'; // Default to futures for backwards compatibility
        const marketBadge = market === 'spot' ? '<span class="market-badge spot">SPOT</span>' : '<span class="market-badge futures">FUTURES</span>';
        const symbolLabel = escapeHtml(pos.symbol || '-');
        const symbolChartUrl = getBinanceChartUrl(pos.symbol, market);
        const sideLabel = escapeHtml(sideRaw);

        html += `
            <div class="position-card ${pos.exchange}" data-market="${market}">
                <div class="card-header">
                    <div>
                        <span class="symbol">
                            <a href="${symbolChartUrl}" class="symbol-link" target="_blank" rel="noopener noreferrer" title="Open Binance chart">${symbolLabel}</a>
                        </span>
                        <span class="side-badge ${sideClass}">${sideLabel}</span>
                        ${marketBadge}
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
                        <span class="label">Opened</span>
                        <span class="value entry-time">${formatEntryTime(pos.entry_time)}</span>
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
                    ${pos.unrealized_pnl !== undefined && pos.unrealized_pnl !== null ? `
                    <div class="stat-row pnl-row">
                        <span class="label">Unrealized P&L</span>
                        <span class="pnl-value ${pnlClass}">
                            ${formatUSD(pos.unrealized_pnl)}
                            (${formatPercent(pos.unrealized_pnl_pct)})
                        </span>
                    </div>
                    ` : ''}
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
    symbol: '',
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
            historyState.symbol = document.getElementById('history-symbol').value.trim();
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
            document.getElementById('history-symbol').value = '';
            historyState.startDate = defaults.startDate;
            historyState.endDate = defaults.endDate;
            historyState.symbol = '';
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
        if (historyState.symbol) params.append('symbol', historyState.symbol);

        const data = await apiFetch(`/api/trades?${params.toString()}`);
        historyState.totalCount = data.total_count;

        renderHistorySummary(data);
        renderTradeTable(data);
        renderPagination(data);
    } catch (error) {
        renderError(containerId, 'Failed to load trade history', 'fetchTrades');
    }
}

function renderHistorySummary(data) {
    const summary = data.summary || {};
    const totalTradesEl = document.getElementById('history-total-trades');
    const buySellEl = document.getElementById('history-buy-sell');
    const marketSplitEl = document.getElementById('history-market-split');
    const realizedPnlEl = document.getElementById('history-realized-pnl');
    const winRateEl = document.getElementById('history-win-rate');

    if (totalTradesEl) totalTradesEl.textContent = String(data.total_count ?? 0);
    if (buySellEl) buySellEl.textContent = `${summary.buy_count ?? 0} / ${summary.sell_count ?? 0}`;
    if (marketSplitEl) marketSplitEl.textContent = `${summary.spot_count ?? 0} / ${summary.futures_count ?? 0}`;

    if (realizedPnlEl) {
        const pnl = summary.realized_pnl ?? 0;
        realizedPnlEl.textContent = formatUSD(pnl);
        realizedPnlEl.className = `value ${getPnLClass(pnl)}`;
    }

    if (winRateEl) {
        if (summary.win_rate === null || summary.win_rate === undefined) {
            winRateEl.textContent = '-';
            winRateEl.className = 'value';
        } else {
            const wr = Number(summary.win_rate);
            winRateEl.textContent = `${wr.toFixed(1)}%`;
            winRateEl.className = `value ${wr >= 50 ? 'positive' : 'negative'}`;
        }
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
        const params = new URLSearchParams({ limit: 50, hours: 24 });

        const data = await apiFetch(`/api/signals?${params.toString()}`);
        renderSignals(data);
    } catch (error) {
        renderError(containerId, 'Failed to load signals', 'fetchSignals');
    }
}

function renderSignals(data) {
    const container = document.getElementById('signals-container');

    if (!data.signals || data.signals.length === 0) {
        renderEmpty('signals-container', 'No market-analysis signals found');
        return;
    }

    // Group by strategy while preserving arrival order
    const strategyGroups = {};
    const strategyOrder = [];
    for (const signal of data.signals) {
        const strategyName = signal.strategy || 'unknown';
        if (!strategyGroups[strategyName]) {
            strategyGroups[strategyName] = [];
            strategyOrder.push(strategyName);
        }
        strategyGroups[strategyName].push(signal);
    }

    let html = '';

    for (const strategyName of strategyOrder) {
        const signals = strategyGroups[strategyName];
        const latestTs = signals[0]?.timestamp || '';

        html += `
            <div class="signal-strategy-group">
                <div class="signal-strategy-header">
                    <div class="signal-strategy-title">${escapeHtml(strategyName)}</div>
                    <div class="signal-strategy-meta">
                        <span>${signals.length} signals</span>
                        <span>Latest: ${formatDateTime(latestTs)}</span>
                    </div>
                </div>
        `;

        for (const signal of signals) {
            const decisionLabel = (signal.decision || signal.action || 'WAIT').toUpperCase();
            const actionClass = decisionLabel.toLowerCase();
            const indicators = signal.indicators || {};
            const symbolDisplay = signal.symbol || '-';
            const marketDisplay = signal.market === 'futures' ? 'Futures' : 'Spot';
            const entryImpact = String(signal.entry_impact || '').toLowerCase();
            const impactDetail = signal.impact_detail || '-';
            const impactFactors = Array.isArray(signal.impact_factors) ? signal.impact_factors : [];
            const impactLabel = ({
                entry_filled: 'ENTRY FILLED',
                entry_ordered: 'ENTRY ORDERED',
                entry_signal: 'ENTRY SIGNAL',
                entry_blocked: 'ENTRY BLOCKED',
                position_hold: 'POSITION HOLD',
                entry_wait: 'ENTRY WAIT',
            })[entryImpact] || (signal.entry_impact || '-');

            html += `
                <div class="signal-card ${actionClass}">
                    <div class="signal-header">
                        <span class="signal-time">${formatDateTime(signal.timestamp)}</span>
                        <div class="signal-badges">
                            <span class="symbol-badge">${escapeHtml(symbolDisplay)}</span>
                            <span class="signal-action ${actionClass}">${decisionLabel}</span>
                            <span class="impact-badge ${entryImpact}">${escapeHtml(impactLabel)}</span>
                            <span class="acted-badge ${signal.acted ? 'yes' : 'no'}">${signal.acted ? 'Acted' : 'Not Acted'}</span>
                        </div>
                    </div>
                    <div class="signal-body">
                        <div class="signal-info">
                            <span class="label">Symbol</span>
                            <span class="value">${escapeHtml(symbolDisplay)} (${marketDisplay})</span>
                        </div>
                        <div class="signal-info">
                            <span class="label">Regime</span>
                            <span class="value">${escapeHtml(signal.regime) || '-'}</span>
                        </div>
                        <div class="signal-info">
                            <span class="label">Decision</span>
                            <span class="value">${decisionLabel}</span>
                        </div>
                        <div class="signal-info">
                            <span class="label">Reason</span>
                            <span class="value">${escapeHtml(signal.reason) || '-'}</span>
                        </div>
                        <div class="signal-info">
                            <span class="label">Market State</span>
                            <span class="value">${escapeHtml(signal.market_state) || '-'}</span>
                        </div>
                        <div class="signal-info">
                            <span class="label">Entry Impact</span>
                            <span class="value">${escapeHtml(impactDetail)}</span>
                        </div>
                    </div>
                    ${impactFactors.length > 0 ? `
                    <div class="signal-impact-factors">
                        ${impactFactors.map((factor) => `<span class="impact-factor">${escapeHtml(factor)}</span>`).join('')}
                    </div>
                    ` : ''}
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

        html += `</div>`;
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
    const tradelogView = document.getElementById('analytics-tradelog-view');

    viewBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            const view = btn.dataset.view;

            // Update active state
            viewBtns.forEach(b => b.classList.remove('active'));
            btn.classList.add('active');

            // Update state
            analyticsState.view = view;

            // Toggle views
            summaryView.style.display = 'none';
            dailyView.style.display = 'none';
            if (tradelogView) tradelogView.style.display = 'none';

            if (view === 'summary') {
                summaryView.style.display = 'block';
                fetchAnalytics(analyticsState.period);
            } else if (view === 'daily') {
                dailyView.style.display = 'block';
                fetchDailyAnalytics(analyticsState.period);
            } else if (view === 'tradelog') {
                if (tradelogView) {
                    tradelogView.style.display = 'block';
                    fetchTradeLog();
                }
            }
        });
    });

    // Initialize trade log filters and download button
    initTradeLogControls();
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
// Trade Log View
// =====================

let tradeLogState = {
    eventFilter: '',
    symbolFilter: ''
};

function initTradeLogControls() {
    const eventFilter = document.getElementById('tradelog-event-filter');
    const symbolFilter = document.getElementById('tradelog-symbol-filter');
    const downloadBtn = document.getElementById('tradelog-download');

    if (eventFilter) {
        eventFilter.addEventListener('change', () => {
            tradeLogState.eventFilter = eventFilter.value;
            fetchTradeLog();
        });
    }

    if (symbolFilter) {
        symbolFilter.addEventListener('change', () => {
            tradeLogState.symbolFilter = symbolFilter.value;
            fetchTradeLog();
        });
    }

    if (downloadBtn) {
        downloadBtn.addEventListener('click', () => {
            const period = analyticsState.period;
            const days = period === 'all' ? 365 : parseInt(period.replace('d', ''));
            window.location.href = resolveApiEndpoint(`/api/analytics/trade-log/download?days=${days}`);
        });
    }
}

async function fetchTradeLog() {
    const container = document.getElementById('tradelog-body');
    if (!container) return;

    try {
        container.innerHTML = '<tr><td colspan="7" class="loading">Loading trade log...</td></tr>';

        const period = analyticsState.period;
        const days = period === 'all' ? 90 : parseInt(period.replace('d', ''));

        let url = `/api/analytics/trade-log?days=${days}&limit=200`;
        if (tradeLogState.eventFilter) {
            url += `&event=${tradeLogState.eventFilter}`;
        }
        if (tradeLogState.symbolFilter) {
            url += `&symbol=${tradeLogState.symbolFilter}`;
        }

        const data = await apiFetch(url);

        renderTradeLogSummary(data.summary);
        renderTradeLogTable(data.entries);
    } catch (error) {
        container.innerHTML = '<tr><td colspan="7" class="error-state">Failed to load trade log</td></tr>';
    }
}

function renderTradeLogSummary(summary) {
    const totalEl = document.getElementById('tradelog-total');
    const pnlEl = document.getElementById('tradelog-pnl');
    const winrateEl = document.getElementById('tradelog-winrate');

    if (totalEl) totalEl.textContent = summary.total || 0;
    if (pnlEl) {
        const pnl = summary.total_pnl || 0;
        pnlEl.textContent = formatUSDT(pnl);
        pnlEl.className = 'stat-value ' + getPnLClass(pnl);
    }
    if (winrateEl) {
        const winrate = summary.win_rate || 0;
        winrateEl.textContent = `${winrate}%`;
    }
}

function renderTradeLogTable(entries) {
    const container = document.getElementById('tradelog-body');
    if (!container) return;

    if (!entries || entries.length === 0) {
        container.innerHTML = '<tr><td colspan="7" class="no-data">No trade log entries found</td></tr>';
        return;
    }

    let html = '';
    for (const entry of entries) {
        const eventClass = getEventClass(entry.event);
        const pnl = entry.pnl;
        const pnlClass = pnl !== undefined ? getPnLClass(pnl) : '';
        const pnlDisplay = pnl !== undefined ? formatUSDT(pnl) : '-';
        const priceDisplay = entry.price ? `$${Number(entry.price).toLocaleString()}` : '-';
        const qtyDisplay = entry.qty ? entry.qty.toFixed(6) : '-';

        html += `
            <tr>
                <td class="time-cell">${formatTradeLogTime(entry.ts)}</td>
                <td><span class="event-badge ${eventClass}">${entry.event}</span></td>
                <td>${entry.symbol || '-'}</td>
                <td class="text-right">${priceDisplay}</td>
                <td class="text-right">${qtyDisplay}</td>
                <td class="text-right ${pnlClass}">${pnlDisplay}</td>
                <td class="strategy-cell" title="${entry.strategy || ''}">${truncateStrategy(entry.strategy)}</td>
            </tr>
        `;
    }

    container.innerHTML = html;
}

function getEventClass(event) {
    const classes = {
        'ENTRY': 'event-entry',
        'EXIT': 'event-exit',
        'FILL': 'event-fill',
        'PNL': 'event-pnl',
        'DECISION': 'event-decision',
        'ERROR': 'event-error'
    };
    return classes[event] || 'event-default';
}

function formatTradeLogTime(ts) {
    if (!ts) return '-';
    // ts is like "2026-01-25T12:00:00"
    const parts = ts.split('T');
    if (parts.length === 2) {
        return `${parts[0].substring(5)} ${parts[1]}`;
    }
    return ts;
}

function truncateStrategy(strategy) {
    if (!strategy) return '-';
    if (strategy.length > 15) {
        return strategy.substring(0, 12) + '...';
    }
    return strategy;
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

function setBacktestMessage(message, level = 'info') {
    const el = document.getElementById('backtest-message');
    if (!el) return;

    if (!message) {
        el.style.display = 'none';
        el.textContent = '';
        el.classList.remove('error', 'success');
        return;
    }

    el.textContent = message;
    el.style.display = 'block';
    el.classList.toggle('error', level === 'error');
    el.classList.toggle('success', level === 'success');
}

function initBacktest() {
    // Sensible default date range (last 365 days)
    const startDateInput = document.getElementById('backtest-start-date');
    const endDateInput = document.getElementById('backtest-end-date');
    if (startDateInput && endDateInput && (!startDateInput.value || !endDateInput.value)) {
        const today = new Date();
        const end = today.toISOString().slice(0, 10);
        const start = new Date(today.getTime() - 365 * 24 * 60 * 60 * 1000).toISOString().slice(0, 10);
        endDateInput.value = end;
        startDateInput.value = start;
    }

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
        setBacktestMessage('Failed to load strategies: ' + error.message, 'error');
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
        setBacktestMessage('Please select a strategy.', 'error');
        return;
    }

    const startDate = startDateInput.value;
    const endDate = endDateInput.value;
    if (!startDate || !endDate) {
        setBacktestMessage('Please select start and end dates.', 'error');
        return;
    }
    if (startDate > endDate) {
        setBacktestMessage('Start date must be before end date.', 'error');
        return;
    }

    const initialCapital = parseFloat(capitalInput.value);
    if (!Number.isFinite(initialCapital) || initialCapital <= 0) {
        setBacktestMessage('Initial capital must be a positive number.', 'error');
        return;
    }

    const config = {
        strategy: strategy,
        start_date: startDate,
        end_date: endDate,
        initial_capital: initialCapital
    };

    // Update UI
    runBtn.disabled = true;
    runBtn.textContent = 'Running...';
    cancelBtn.style.display = 'inline-block';
    progressDiv.style.display = 'block';
    resultsDiv.style.display = 'none';
    setBacktestMessage(null);

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
        setBacktestMessage('Failed to start backtest: ' + error.message, 'error');
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
                setBacktestMessage('Backtest completed.', 'success');
            } else if (data.status === 'failed') {
                clearInterval(backtestState.pollInterval);
                backtestState.pollInterval = null;
                resetBacktestUI();
                loadBacktestHistory();  // Refresh history list
                setBacktestMessage('Backtest failed: ' + (data.error || 'Unknown error'), 'error');
            } else if (data.status === 'cancelled') {
                clearInterval(backtestState.pollInterval);
                backtestState.pollInterval = null;
                resetBacktestUI();
                loadBacktestHistory();  // Refresh history list
                setBacktestMessage('Backtest cancelled.', 'info');
            }
        } catch (error) {
            console.error('Poll error:', error);
            clearInterval(backtestState.pollInterval);
            backtestState.pollInterval = null;
            resetBacktestUI();
            setBacktestMessage('Lost connection while polling: ' + error.message, 'error');
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

    const cancelBtn = document.getElementById('backtest-cancel-btn');
    if (cancelBtn) {
        cancelBtn.disabled = true;
        cancelBtn.textContent = 'Cancelling...';
    }

    try {
        await apiFetch(`/api/backtest/cancel/${backtestState.currentJobId}`, {
            method: 'POST'
        });
    } catch (error) {
        console.error('Failed to cancel:', error);
        setBacktestMessage('Failed to cancel: ' + error.message, 'error');
    }

    if (backtestState.pollInterval) {
        clearInterval(backtestState.pollInterval);
        backtestState.pollInterval = null;
    }

    resetBacktestUI();
    loadBacktestHistory();
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
        cancelBtn.disabled = false;
        cancelBtn.textContent = 'Cancel';
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

    // Render regime analysis chart if available (with yearly charts for long backtests)
    renderBacktestRegimeChart(result.regime_chart_path, result.yearly_chart_paths);

    // Render MLflow link if available
    renderMLflowLink(result.mlflow_run_id, result.mlflow_url);

    // Render sample trades
    if (tradesDiv && result.trades) {
        renderBacktestTrades(result.trades);
    }
}

function renderBacktestChartImage(chartPath) {
    const container = document.getElementById('backtest-chart-image');
    if (!container) return;

    if (chartPath) {
        container.innerHTML = `
            <h4>Strategy vs Benchmark Chart</h4>
            <img src="${chartPath}" alt="Backtest Chart">
            <a href="${chartPath}" target="_blank" class="download-link">Open Full Size</a>
        `;
        container.style.display = 'block';
    } else {
        container.style.display = 'none';
    }
}

function renderBacktestRegimeChart(regimeChartPath, yearlyChartPaths) {
    const container = document.getElementById('backtest-regime-chart');
    if (!container) return;

    if (regimeChartPath) {
        let yearlyLinksHtml = '';
        if (yearlyChartPaths && yearlyChartPaths.length > 0) {
            const yearLinks = yearlyChartPaths.map(path => {
                // Extract year from filename (e.g., regime_2024.png -> 2024)
                const match = path.match(/regime_(\d{4})\.png/);
                const year = match ? match[1] : path.split('/').pop();
                return `<a href="${path}" target="_blank" class="yearly-chart-link">${year}</a>`;
            }).join(' ');
            yearlyLinksHtml = `
                <div class="yearly-charts-section">
                    <span class="yearly-label">Yearly Charts (detailed view):</span>
                    ${yearLinks}
                </div>
            `;
        }

        container.innerHTML = `
            <h4>Regime Analysis Chart</h4>
            <p class="chart-description">Bollinger Bands lines (upper/middle/lower) with shaded band width between upper and lower</p>
            <img src="${regimeChartPath}" alt="Regime Analysis Chart">
            <div class="chart-links">
                <a href="${regimeChartPath}" target="_blank" class="download-link">Open Full Size</a>
            </div>
            ${yearlyLinksHtml}
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

    function formatCompactCurrency(value) {
        const abs = Math.abs(value);
        if (abs >= 1_000_000) return (value / 1_000_000).toFixed(1) + 'M';
        if (abs >= 1_000) return (value / 1_000).toFixed(1) + 'K';
        return value.toFixed(0);
    }

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
                        callback: value => formatCompactCurrency(value)
                    },
                    title: {
                        display: hasBenchmark,
                        text: 'Strategy (USDT)',
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
                        callback: value => formatCompactCurrency(value)
                    },
                    title: {
                        display: hasBenchmark,
                        text: 'Buy & Hold (USDT)',
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

        // Highlight active item
        document.querySelectorAll('.backtest-history-item').forEach(el => {
            el.classList.remove('active');
        });
        const activeItem = document.querySelector(`[data-job-id="${jobId}"]`);
        if (activeItem) {
            activeItem.classList.add('active');
        }

        if (data.status === 'running' || data.status === 'pending') {
            backtestState.currentJobId = data.job_id;
            const runBtn = document.getElementById('backtest-run-btn');
            const cancelBtn = document.getElementById('backtest-cancel-btn');
            const progressDiv = document.getElementById('backtest-progress');
            const resultsDiv = document.getElementById('backtest-results');

            if (runBtn) {
                runBtn.disabled = true;
                runBtn.textContent = 'Running...';
            }
            if (cancelBtn) {
                cancelBtn.style.display = 'inline-block';
            }
            if (progressDiv) {
                progressDiv.style.display = 'block';
            }
            if (resultsDiv) {
                resultsDiv.style.display = 'none';
            }
            setBacktestMessage('Resumed job ' + jobId + ' (' + data.status + ').');
            pollBacktestStatus(jobId);
            return;
        }

        if (data.status === 'completed' && data.result) {
            renderBacktestResults(data.result);
            setBacktestMessage(null);
        } else if (data.status === 'failed') {
            setBacktestMessage('Backtest failed: ' + (data.error || 'Unknown error'), 'error');
        } else if (data.status === 'cancelled') {
            setBacktestMessage('Backtest cancelled.', 'info');
        }
    } catch (error) {
        console.error('Failed to load backtest job:', error);
        setBacktestMessage('Failed to load backtest job: ' + error.message, 'error');
    }
}

// =====================
// Strategies Tab
// =====================

async function fetchStrategiesTab() {
    const container = document.getElementById('strategies-container');
    const selectorOverview = document.getElementById('selector-overview');
    const selectorEvents = document.getElementById('selector-events');
    if (!container) return;

    container.innerHTML = '<p class="loading">Loading strategies...</p>';
    if (selectorOverview) selectorOverview.innerHTML = '<p class="loading">Loading selector monitor...</p>';
    if (selectorEvents) selectorEvents.innerHTML = '<p class="loading">Loading selector events...</p>';

    try {
        const [data, selectorData] = await Promise.all([
            apiFetch('/api/strategies'),
            apiFetch('/api/events/selector?hours=24&limit=40&changed_only=true')
                .catch((error) => {
                    console.warn('Selector events fetch failed:', error);
                    return { events: [] };
                })
        ]);
        renderStrategiesTab(data, selectorData.events || []);
    } catch (error) {
        console.error('Failed to fetch strategies:', error);
        container.innerHTML = `<p class="error">Failed to load strategies: ${error.message}</p>`;
        if (selectorOverview) selectorOverview.innerHTML = '<p class="error">Failed to load selector monitor</p>';
        if (selectorEvents) selectorEvents.innerHTML = '<p class="error">Failed to load selector events</p>';
    }
}

function renderStrategiesTab(data, selectorEvents = []) {
    const container = document.getElementById('strategies-container');
    if (!container) return;

    const strategies = data.strategies || [];
    const symbols = data.symbols || [];
    const availableStrategies = data.available_strategies || [];

    // Update summary stats
    const countEl = document.getElementById('strategies-count');
    const tunedCountEl = document.getElementById('strategies-tuned-count');
    const positionsCountEl = document.getElementById('strategies-positions-count');

    if (countEl) countEl.textContent = strategies.length;
    if (tunedCountEl) {
        const tunedCount = strategies.filter(s => s.is_tuned).length;
        tunedCountEl.textContent = tunedCount;
    }
    if (positionsCountEl) {
        const totalPositions = strategies.reduce((sum, s) => sum + (s.active_positions?.length || 0), 0);
        positionsCountEl.textContent = totalPositions;
    }

    renderSelectorMonitor(strategies, selectorEvents);

    if (strategies.length === 0 && availableStrategies.length === 0) {
        container.innerHTML = '<p class="no-data">No strategies configured</p>';
        return;
    }

    let html = '';

    // Render enabled strategies
    for (const strategy of strategies) {
        html += renderStrategyCard(strategy, symbols);
    }

    // Render available but not enabled strategies
    if (availableStrategies.length > 0) {
        html += `
            <div class="available-strategies-section">
                <h4>Available (Not Enabled)</h4>
                <div class="available-strategies-list">
                    ${availableStrategies.map(name => `
                        <div class="available-strategy-item">
                            <span class="strategy-name">${name}</span>
                            <span class="strategy-badge disabled">Disabled</span>
                            <button class="btn-enable" data-strategy="${name}" title="Enable strategy">Enable</button>
                        </div>
                    `).join('')}
                </div>
            </div>
        `;
    }

    container.innerHTML = html;

    // Attach event handlers
    attachStrategyEventHandlers();
}

function renderSelectorMonitor(strategies, selectorEvents) {
    const overviewEl = document.getElementById('selector-overview');
    const eventsEl = document.getElementById('selector-events');
    if (!overviewEl || !eventsEl) return;

    const selectorStrategies = (strategies || []).filter(
        (s) => s.symbol_selector && s.symbol_selector.enabled
    );

    if (selectorStrategies.length === 0) {
        overviewEl.innerHTML = '<p class="empty-state">No enabled selector strategies.</p>';
    } else {
        const overviewHtml = selectorStrategies.map((strategy) => {
            const state = strategy.selector_state || {};
            const selectedSymbols = Array.isArray(state.selected_symbols) ? state.selected_symbols : [];
            const topScores = Array.isArray(state.top_scores) ? state.top_scores : [];
            const signalEvents = Array.isArray(state.signal_events) ? state.signal_events : [];
            const rejectionCounts = state.rejection_counts || {};
            const topRejections = Object.entries(rejectionCounts)
                .sort((a, b) => Number(b[1]) - Number(a[1]))
                .slice(0, 3);

            const selectedHtml = selectedSymbols.length > 0
                ? selectedSymbols.map((s) => `<span class="selector-chip selected">${escapeHtml(s)}</span>`).join('')
                : '<span class="selector-empty">No selected symbols</span>';

            const scoreHtml = topScores.length > 0
                ? topScores.slice(0, 5).map((item) => {
                    const score = Number(item.score ?? 0).toFixed(3);
                    const ignition = Number(item.ignition ?? item.score ?? 0).toFixed(3);
                    return `<span class="selector-chip">${escapeHtml(item.symbol)}:${score} (ign:${ignition})</span>`;
                }).join('')
                : '<span class="selector-empty">No score snapshot</span>';
            const signalHtml = signalEvents.length > 0
                ? signalEvents.slice(0, 5).map((item) => {
                    const score = Number(item.score ?? 0).toFixed(3);
                    return `<span class="selector-chip selected">${escapeHtml(item.type || '?')}:${escapeHtml(item.symbol || '?')}(${score})</span>`;
                }).join('')
                : '<span class="selector-empty">No signal events</span>';

            const rejectHtml = topRejections.length > 0
                ? topRejections.map(([reason, count]) =>
                    `<span class="selector-chip reject">${escapeHtml(reason)}:${Number(count)}</span>`
                ).join('')
                : '<span class="selector-empty">No rejection reasons</span>';

            return `
                <div class="selector-overview-card">
                    <div class="selector-overview-title">
                        <span class="strategy-name">${escapeHtml(strategy.name)}</span>
                        <span class="selector-flag">${state.changed ? 'Changed' : 'Stable'} · ${state.timestamp ? formatDateTime(state.timestamp) : '-'}</span>
                    </div>
                    <div class="selector-overview-row">
                        <span class="selector-overview-kv">Top N: <b>${strategy.symbol_selector?.top_n ?? '-'}</b></span>
                        <span class="selector-overview-kv">Selected: <b>${selectedSymbols.length}</b></span>
                        <span class="selector-overview-kv">Universe: <b>${state.universe_size ?? '-'}</b></span>
                    </div>
                    <div class="selector-overview-row">${selectedHtml}</div>
                    <div class="selector-overview-row">${scoreHtml}</div>
                    <div class="selector-overview-row">${signalHtml}</div>
                    <div class="selector-overview-row">${rejectHtml}</div>
                </div>
            `;
        }).join('');

        overviewEl.innerHTML = overviewHtml;
    }

    const events = Array.isArray(selectorEvents) ? selectorEvents : [];
    if (events.length === 0) {
        eventsEl.innerHTML = '<p class="empty-state">No selector change events in the last 24h.</p>';
        return;
    }

    const eventsHtml = events.slice(0, 20).map((event) => {
        const selectedSymbols = Array.isArray(event.selected_symbols) ? event.selected_symbols : [];
        const topScores = Array.isArray(event.top_scores) ? event.top_scores : [];
        const signalEvents = Array.isArray(event.signal_events) ? event.signal_events : [];
        const rejectionCounts = event.rejection_counts || {};
        const topRejections = Object.entries(rejectionCounts)
            .sort((a, b) => Number(b[1]) - Number(a[1]))
            .slice(0, 3)
            .map(([reason, count]) => `${reason}:${count}`)
            .join(', ');
        const scoreText = topScores.slice(0, 3)
            .map((item) => `${item.symbol}:${Number(item.score ?? 0).toFixed(3)}(ign:${Number(item.ignition ?? item.score ?? 0).toFixed(3)})`)
            .join(', ');
        const signalText = signalEvents.slice(0, 4)
            .map((item) => `${item.type}:${item.symbol}`)
            .join(', ');

        return `
            <div class="selector-event-item">
                <div class="selector-event-head">
                    <span class="selector-event-strategy">${escapeHtml(event.strategy || '-')}</span>
                    <span>${formatDateTime(event.timestamp)}</span>
                </div>
                <div class="selector-event-body">
                    <span class="selector-chip ${event.changed ? 'selected' : ''}">${event.changed ? 'changed' : 'stable'}</span>
                    <span class="selector-chip">selected: ${selectedSymbols.join(', ') || '-'}</span>
                    <span class="selector-chip">score: ${scoreText || '-'}</span>
                    <span class="selector-chip selected">signals: ${escapeHtml(signalText || '-')}</span>
                    <span class="selector-chip reject">reject: ${escapeHtml(topRejections || '-')}</span>
                </div>
            </div>
        `;
    }).join('');

    eventsEl.innerHTML = eventsHtml;
}

function attachStrategyEventHandlers() {
    // Enable buttons
    document.querySelectorAll('.btn-enable').forEach(btn => {
        btn.addEventListener('click', async (e) => {
            const strategyName = e.target.dataset.strategy;
            await toggleStrategy(strategyName, 'enable');
        });
    });

    // Disable buttons
    document.querySelectorAll('.btn-disable').forEach(btn => {
        btn.addEventListener('click', async (e) => {
            const strategyName = e.target.dataset.strategy;
            if (confirm(`Disable strategy "${strategyName}"?`)) {
                await toggleStrategy(strategyName, 'disable');
            }
        });
    });
}

async function toggleStrategy(strategyName, action) {
    try {
        const response = await apiFetch(`/api/strategies/${strategyName}/${action}`, {
            method: 'POST'
        });

        if (response.success) {
            // Refresh strategies tab
            fetchStrategiesTab();
            showNotification(`Strategy ${strategyName} ${action}d successfully`, 'success');
        } else {
            showNotification(response.error || `Failed to ${action} strategy`, 'error');
        }
    } catch (error) {
        console.error(`Failed to ${action} strategy:`, error);
        showNotification(error.message || `Failed to ${action} strategy`, 'error');
    }
}

function showNotification(message, type = 'info') {
    // Simple notification - could be enhanced with a toast library
    const existing = document.querySelector('.notification-toast');
    if (existing) existing.remove();

    const toast = document.createElement('div');
    toast.className = `notification-toast ${type}`;
    toast.textContent = message;
    document.body.appendChild(toast);

    setTimeout(() => toast.classList.add('show'), 10);
    setTimeout(() => {
        toast.classList.remove('show');
        setTimeout(() => toast.remove(), 300);
    }, 3000);
}

function renderStrategyCard(strategy, symbols) {
    const name = strategy.name;
    const market = strategy.market || 'futures';
    const isSpot = market === 'spot';
    const leverage = isSpot ? 1 : (strategy.leverage || 1);
    const positionPct = strategy.position_pct || 0;
    const isTuned = strategy.is_tuned;
    const activePositions = strategy.active_positions || [];
    const liveState = strategy.live_state || {};
    const selectorCfg = strategy.symbol_selector || null;
    const selectorState = strategy.selector_state || null;

    // Status badge
    let statusBadge = '';
    if (activePositions.length > 0) {
        statusBadge = '<span class="strategy-badge active">Active</span>';
    } else if (isTuned) {
        statusBadge = '<span class="strategy-badge tuned">Tuned</span>';
    }

    // Entry/Exit classes
    const entryClass = strategy.entry_class || 'Unknown';
    const exitClass = strategy.exit_class || 'Unknown';

    // Regime routing detailed view
    let regimeHtml = '';
    if (strategy.regime_routing) {
        const regimes = Object.entries(strategy.regime_routing);

        // Group by entry type for summary
        const entryGroups = {};
        regimes.forEach(([regime, cfg]) => {
            const entry = cfg.entry || 'Default';
            if (!entryGroups[entry]) entryGroups[entry] = [];
            entryGroups[entry].push(regime);
        });

        regimeHtml = `
            <div class="strategy-regime-routing">
                <h5>Regime Routing (${regimes.length} regimes)</h5>
                <div class="regime-table-container">
                    <table class="regime-table">
                        <thead>
                            <tr>
                                <th>Regime</th>
                                <th>Entry</th>
                                <th>Exit</th>
                                <th>Key Params</th>
                            </tr>
                        </thead>
                        <tbody>
                            ${regimes.map(([regime, cfg]) => {
                                const entryParams = cfg.entry_params || {};
                                const exitParams = cfg.exit_params || {};
                                const keyParams = [];

                                // Show most important params
                                if (entryParams.mfi_threshold) keyParams.push(`MFI:${entryParams.mfi_threshold.toFixed(1)}`);
                                if (entryParams.adx_threshold) keyParams.push(`ADX:${entryParams.adx_threshold.toFixed(1)}`);
                                if (entryParams.range_threshold) keyParams.push(`Range:${entryParams.range_threshold.toFixed(2)}`);
                                if (entryParams.rsi_overbought) keyParams.push(`RSI:${entryParams.rsi_overbought.toFixed(1)}`);
                                if (exitParams.trailing_stop_pct) keyParams.push(`Trail:${exitParams.trailing_stop_pct.toFixed(1)}%`);
                                if (exitParams.take_profit_pct) keyParams.push(`TP:${exitParams.take_profit_pct.toFixed(1)}%`);

                                return `
                                    <tr>
                                        <td><span class="regime-name">${regime}</span></td>
                                        <td><span class="entry-tag">${cfg.entry || 'Default'}</span></td>
                                        <td><span class="exit-tag">${cfg.exit || 'Default'}</span></td>
                                        <td class="params-cell">${keyParams.join(', ') || '-'}</td>
                                    </tr>
                                `;
                            }).join('')}
                        </tbody>
                    </table>
                </div>
                <div class="regime-summary">
                    <span class="summary-label">Entry mix:</span>
                    ${Object.entries(entryGroups).map(([entry, regimeList]) =>
                        `<span class="entry-tag">${entry}</span><span class="regime-count">(${regimeList.length})</span>`
                    ).join(' ')}
                </div>
            </div>
        `;
    }

    // Live state per symbol
    let stateHtml = '';
    if (Object.keys(liveState).length > 0) {
        stateHtml = '<div class="strategy-live-state"><h5>Live State</h5><div class="state-grid">';
        for (const [symbol, state] of Object.entries(liveState)) {
            const stateItems = Object.entries(state)
                .map(([k, v]) => {
                    const formatted = typeof v === 'number' ? formatNumber(v, 4) : v;
                    return `<span class="state-item"><span class="state-key">${k}:</span> ${formatted}</span>`;
                })
                .join('');
            stateHtml += `<div class="state-symbol"><span class="symbol-label">${symbol}</span>${stateItems}</div>`;
        }
        stateHtml += '</div></div>';
    }

    // Active positions
    let positionsHtml = '';
    if (activePositions.length > 0) {
        positionsHtml = '<div class="strategy-positions"><h5>Active Positions</h5><div class="positions-list">';
        for (const pos of activePositions) {
            const sideClass = pos.side === 'long' ? 'long' : 'short';
            positionsHtml += `
                <div class="position-item ${sideClass}">
                    <span class="pos-symbol">${pos.symbol}</span>
                    <span class="pos-side">${pos.side.toUpperCase()}</span>
                    <span class="pos-qty">${formatNumber(pos.qty, 4)}</span>
                    <span class="pos-entry">@ ${formatNumber(pos.entry_price, 2)}</span>
                </div>
            `;
        }
        positionsHtml += '</div></div>';
    }

    let selectorHtml = '';
    if (selectorCfg && selectorCfg.enabled) {
        const selectedSymbols = Array.isArray(selectorState?.selected_symbols)
            ? selectorState.selected_symbols
            : [];
        const topScores = Array.isArray(selectorState?.top_scores)
            ? selectorState.top_scores
            : [];
        const signalEvents = Array.isArray(selectorState?.signal_events)
            ? selectorState.signal_events
            : [];
        const rejected = Array.isArray(selectorState?.rejected)
            ? selectorState.rejected
            : [];
        const rejectionCounts = selectorState?.rejection_counts || {};
        const topRejectReasons = Object.entries(rejectionCounts)
            .sort((a, b) => Number(b[1]) - Number(a[1]))
            .slice(0, 3);

        selectorHtml = `
            <div class="strategy-selector">
                <h5>Symbol Selector</h5>
                <div class="selector-meta">
                    <span class="selector-kv">Top N: <b>${selectorCfg.top_n || '-'}</b></span>
                    <span class="selector-kv">Selected: <b>${selectedSymbols.length}</b></span>
                    <span class="selector-kv">Universe: <b>${selectorState?.universe_size ?? '-'}</b></span>
                </div>
                <div class="selector-selected">
                    ${(selectedSymbols.length > 0)
                        ? selectedSymbols.map(s => `<span class="selector-chip selected">${escapeHtml(s)}</span>`).join('')
                        : '<span class="selector-empty">No selected symbols</span>'}
                </div>
                <div class="selector-scores">
                    ${(topScores.length > 0)
                        ? topScores.slice(0, 5).map(item => {
                            const score = Number(item.score ?? 0).toFixed(3);
                            const ignition = Number(item.ignition ?? item.score ?? 0).toFixed(3);
                            return `<span class="selector-chip">${escapeHtml(item.symbol)}:${score} (ign:${ignition})</span>`;
                        }).join('')
                        : '<span class="selector-empty">No score snapshot</span>'}
                </div>
                <div class="selector-scores">
                    ${(signalEvents.length > 0)
                        ? signalEvents.slice(0, 6).map(item => {
                            const score = Number(item.score ?? 0).toFixed(3);
                            return `<span class="selector-chip selected">${escapeHtml(item.type || '?')}:${escapeHtml(item.symbol || '?')}(${score})</span>`;
                        }).join('')
                        : '<span class="selector-empty">No signal events</span>'}
                </div>
                <div class="selector-rejections">
                    ${(topRejectReasons.length > 0)
                        ? topRejectReasons.map(([reason, count]) =>
                            `<span class="selector-chip reject">${escapeHtml(reason)}:${Number(count)}</span>`
                        ).join('')
                        : '<span class="selector-empty">No rejection reasons</span>'}
                </div>
                ${rejected.length > 0 ? `
                    <div class="selector-rejected-list">
                        ${rejected.slice(0, 5).map(item =>
                            `<span class="selector-rejected-item">${escapeHtml(item.symbol)}(${escapeHtml(item.reason)})</span>`
                        ).join('')}
                    </div>
                ` : ''}
            </div>
        `;
    }

    // Disable button (disabled if has active positions)
    const hasPositions = activePositions.length > 0;
    const disableBtn = hasPositions
        ? `<button class="btn-disable" data-strategy="${name}" disabled title="Cannot disable: has active positions">Disable</button>`
        : `<button class="btn-disable" data-strategy="${name}" title="Disable strategy">Disable</button>`;

    return `
        <div class="strategy-card">
            <div class="strategy-header">
                <div class="strategy-title">
                    <h4 class="strategy-name">${name}</h4>
                    ${statusBadge}
                </div>
                ${disableBtn}
            </div>
            <div class="strategy-config">
                <div class="config-row">
                    <span class="config-label">Market</span>
                    <span class="config-value">${market.toUpperCase()}</span>
                </div>
                ${isSpot ? '' : `<div class="config-row">
                    <span class="config-label">Leverage</span>
                    <span class="config-value editable" onclick="editStrategyLeverage('${name}', ${leverage})" title="Click to edit">${leverage}x</span>
                </div>`}
                <div class="config-row">
                    <span class="config-label">Position %</span>
                    <span class="config-value editable" onclick="editStrategyPositionPct('${name}', ${positionPct})" title="Click to edit">${(positionPct * 100).toFixed(0)}%</span>
                </div>
                <div class="config-row">
                    <span class="config-label">Entry</span>
                    <span class="config-value entry-class">${entryClass.replace('Strategy', '')}</span>
                </div>
                <div class="config-row">
                    <span class="config-label">Exit</span>
                    <span class="config-value exit-class">${exitClass.replace('Strategy', '')}</span>
                </div>
            </div>
            ${regimeHtml}
            ${stateHtml}
            ${selectorHtml}
            ${positionsHtml}
        </div>
    `;
}

function formatNumber(value, decimals = 2) {
    if (typeof value !== 'number' || !Number.isFinite(value)) return '-';
    return value.toLocaleString('en-US', {
        minimumFractionDigits: decimals,
        maximumFractionDigits: decimals
    });
}

// Strategy config editing functions
async function editStrategyLeverage(strategyName, currentValue) {
    const newValue = prompt(`Enter new leverage for ${strategyName} (1-20):`, currentValue);
    if (newValue === null) return; // Cancelled

    const leverage = parseInt(newValue, 10);
    if (isNaN(leverage) || leverage < 1 || leverage > 20) {
        alert('Invalid leverage. Must be between 1 and 20.');
        return;
    }

    await updateStrategyConfig(strategyName, { leverage });
}

async function editStrategyPositionPct(strategyName, currentValue) {
    const currentPct = (currentValue * 100).toFixed(0);
    const newValue = prompt(`Enter new position % for ${strategyName} (1-100):`, currentPct);
    if (newValue === null) return; // Cancelled

    const pct = parseInt(newValue, 10);
    if (isNaN(pct) || pct < 1 || pct > 100) {
        alert('Invalid position %. Must be between 1 and 100.');
        return;
    }

    await updateStrategyConfig(strategyName, { position_pct: pct / 100 });
}

async function updateStrategyConfig(strategyName, updates) {
    try {
        const response = await apiFetch(`/api/strategies/${strategyName}/config`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(updates)
        });

        if (response.success) {
            showNotification(`Updated ${strategyName}: ${response.message}`, 'success');
            // Refresh strategies tab
            fetchStrategiesTab();
        } else {
            showNotification(`Failed to update: ${response.error}`, 'error');
        }
    } catch (error) {
        console.error('Error updating strategy config:', error);
        showNotification(`Error: ${error.message}`, 'error');
    }
}

function showNotification(message, type = 'info') {
    // Create notification element
    const notification = document.createElement('div');
    notification.className = `notification ${type}`;
    notification.textContent = message;
    notification.style.cssText = `
        position: fixed;
        top: 20px;
        right: 20px;
        padding: 12px 20px;
        border-radius: 6px;
        color: white;
        font-size: 14px;
        z-index: 10000;
        animation: slideIn 0.3s ease-out;
        background: ${type === 'success' ? '#3fb950' : type === 'error' ? '#f85149' : '#58a6ff'};
    `;

    document.body.appendChild(notification);

    // Remove after 3 seconds
    setTimeout(() => {
        notification.style.animation = 'fadeOut 0.3s ease-out';
        setTimeout(() => notification.remove(), 300);
    }, 3000);
}

console.log('Multi-Asset Dashboard initialized');
