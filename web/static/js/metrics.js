/**
 * Real-Time Trading Metrics Dashboard
 *
 * Polls /api/metrics/realtime every 4 seconds and updates the DOM
 * with current strategy decisions, positions, and market regime.
 */

const POLLING_INTERVAL = 4000;  // 4 seconds
const STALE_THRESHOLD = 30;     // 30 seconds

let lastUpdateTime = null;

/**
 * Fetch real-time metrics from the API
 */
async function fetchRealtimeMetrics() {
    try {
        const response = await fetch('/api/metrics/realtime');

        if (response.status === 404) {
            showNoDataState();
            return;
        }

        if (!response.ok) {
            throw new Error(`HTTP error: ${response.status}`);
        }

        const data = await response.json();

        if (data.error) {
            showNoDataState();
            return;
        }

        hideNoDataState();
        updateDashboard(data);
        lastUpdateTime = new Date();
        updateFreshness(data);

    } catch (error) {
        console.error('Error fetching metrics:', error);
        updateFreshnessError();
    }
}

/**
 * Fetch decision history from the API
 */
async function fetchDecisionHistory() {
    try {
        const response = await fetch('/api/metrics/decisions?hours=24&limit=50');

        if (!response.ok) {
            return;
        }

        const data = await response.json();
        updateDecisionHistory(data.decisions || []);

    } catch (error) {
        console.error('Error fetching decision history:', error);
    }
}

/**
 * Show the no-data state
 */
function showNoDataState() {
    document.getElementById('no-data-state').style.display = 'block';
    document.getElementById('main-content').style.display = 'none';
}

/**
 * Hide the no-data state
 */
function hideNoDataState() {
    document.getElementById('no-data-state').style.display = 'none';
    document.getElementById('main-content').style.display = 'block';
}

/**
 * Update the entire dashboard with new data
 */
function updateDashboard(data) {
    // Update connection status
    updateConnectionStatus(data.connection_status || []);

    // Update Upbit data
    if (data.upbit) {
        updateStrategyDecision('upbit', data.upbit);
        updatePositionMetrics('upbit', data.upbit);
        updateMarketRegime(data.upbit);
    } else {
        document.getElementById('upbit-card').style.display = 'none';
        document.getElementById('upbit-position-card').style.display = 'none';
    }

    // Update Binance data
    if (data.binance) {
        updateStrategyDecision('binance', data.binance);
        updatePositionMetrics('binance', data.binance);
        // Use binance regime if upbit not available
        if (!data.upbit) {
            updateMarketRegime(data.binance);
        }
    } else {
        document.getElementById('binance-card').style.display = 'none';
        document.getElementById('binance-position-card').style.display = 'none';
    }

    // Update last update time
    document.getElementById('last-update').textContent =
        `Updated: ${new Date().toLocaleTimeString()}`;
}

/**
 * Update strategy decision display for an exchange
 */
function updateStrategyDecision(exchange, data) {
    const card = document.getElementById(`${exchange}-card`);
    card.style.display = 'block';

    // Update mode badge
    const modeBadge = document.getElementById(`${exchange}-mode`);
    modeBadge.textContent = data.mode.toUpperCase();
    modeBadge.className = `mode-badge ${data.mode}`;

    // Update strategy name
    document.getElementById(`${exchange}-strategy`).textContent =
        `Strategy: ${data.strategy || 'Unknown'}`;

    // Update decision
    const lastDecision = data.last_decision;
    if (lastDecision) {
        const actionEl = document.getElementById(`${exchange}-action`);
        actionEl.textContent = lastDecision.action.toUpperCase();
        actionEl.className = `decision-action ${lastDecision.action}`;

        document.getElementById(`${exchange}-reason`).textContent =
            lastDecision.reason || '-';

        document.getElementById(`${exchange}-time`).textContent =
            formatTimestamp(lastDecision.timestamp);
    } else {
        document.getElementById(`${exchange}-action`).textContent = '-';
        document.getElementById(`${exchange}-reason`).textContent = 'No recent decision';
        document.getElementById(`${exchange}-time`).textContent = '-';
    }
}

/**
 * Update position metrics for an exchange
 */
function updatePositionMetrics(exchange, data) {
    const card = document.getElementById(`${exchange}-position-card`);

    if (!data.position_active) {
        card.style.display = 'none';
        return;
    }

    card.style.display = 'block';

    // Entry price
    document.getElementById(`${exchange}-entry-price`).textContent =
        formatPrice(data.entry_price, exchange);

    // Current price
    document.getElementById(`${exchange}-current-price`).textContent =
        formatPrice(data.current_price, exchange);

    // Position size
    document.getElementById(`${exchange}-position-size`).textContent =
        formatBtc(data.position_qty);

    // Unrealized P&L
    const pnlEl = document.getElementById(`${exchange}-pnl`);
    const pnl = data.unrealized_pnl || 0;
    const pnlPct = data.unrealized_pnl_pct || 0;

    pnlEl.textContent = `${formatCurrency(pnl, exchange)} (${pnlPct.toFixed(2)}%)`;
    pnlEl.className = `value ${pnl >= 0 ? 'positive' : 'negative'}`;
}

/**
 * Update market regime display
 */
function updateMarketRegime(data) {
    const regimeBadge = document.getElementById('regime-badge');
    const regime = data.regime || 'UNKNOWN';

    regimeBadge.textContent = regime;
    regimeBadge.className = `regime-badge ${regime.toLowerCase()}`;

    document.getElementById('market-state').textContent =
        data.market_state ? `State: ${data.market_state}` : '';
}

/**
 * Update connection status indicators
 */
function updateConnectionStatus(statuses) {
    for (const status of statuses) {
        const dot = document.getElementById(`${status.exchange}-connection`);
        if (!dot) continue;

        if (!status.connected) {
            dot.className = 'connection-dot disconnected';
        } else if (status.is_stale) {
            dot.className = 'connection-dot stale';
        } else {
            dot.className = 'connection-dot connected';
        }
    }
}

/**
 * Update decision history list
 */
function updateDecisionHistory(decisions) {
    const container = document.getElementById('decision-history');

    if (!decisions || decisions.length === 0) {
        container.innerHTML = '<div class="no-data" style="padding: 20px;">No decisions in the last 24 hours</div>';
        return;
    }

    let html = '';
    for (const decision of decisions) {
        const id = `decision-${decision.exchange}-${decision.timestamp}`;
        html += `
            <div class="decision-item" onclick="toggleDecisionDetails('${id}')">
                <span class="action-badge ${decision.action}">${decision.action}</span>
                <div class="details">
                    <div class="reason-text">${decision.reason || '-'}</div>
                    <div class="time-text">${formatTimestamp(decision.timestamp)} - ${decision.exchange || ''}</div>
                </div>
                <span class="expand-icon">&#9660;</span>
            </div>
            <div class="decision-details" id="${id}">
                <div class="indicators-grid">
                    ${formatIndicators(decision.indicators)}
                </div>
            </div>
        `;
    }

    container.innerHTML = html;
}

/**
 * Toggle decision details visibility
 */
function toggleDecisionDetails(id) {
    const details = document.getElementById(id);
    if (details) {
        details.classList.toggle('expanded');
    }
}

/**
 * Format indicators for display
 */
function formatIndicators(indicators) {
    if (!indicators) return '<div class="indicator-item">No indicators available</div>';

    const items = [];

    if (indicators.rsi !== undefined) {
        items.push(`<div class="indicator-item"><span class="name">RSI</span><span class="val">${indicators.rsi.toFixed(1)}</span></div>`);
    }
    if (indicators.mfi !== undefined) {
        items.push(`<div class="indicator-item"><span class="name">MFI</span><span class="val">${indicators.mfi.toFixed(1)}</span></div>`);
    }
    if (indicators.adx !== undefined) {
        items.push(`<div class="indicator-item"><span class="name">ADX</span><span class="val">${indicators.adx.toFixed(1)}</span></div>`);
    }
    if (indicators.score !== undefined) {
        items.push(`<div class="indicator-item"><span class="name">Score</span><span class="val">${indicators.score}</span></div>`);
    }
    if (indicators.tier !== undefined) {
        items.push(`<div class="indicator-item"><span class="name">Tier</span><span class="val">${indicators.tier}</span></div>`);
    }
    if (indicators.close !== undefined) {
        items.push(`<div class="indicator-item"><span class="name">Price</span><span class="val">${formatCompactPrice(indicators.close)}</span></div>`);
    }

    return items.join('');
}

/**
 * Update freshness indicator based on data staleness
 */
function updateFreshness(data) {
    const dot = document.getElementById('freshness-dot');
    const text = document.getElementById('freshness-text');

    // Check if any connection is stale
    let isStale = false;
    let maxStaleSeconds = 0;

    for (const status of (data.connection_status || [])) {
        if (status.connected && status.is_stale) {
            isStale = true;
            maxStaleSeconds = Math.max(maxStaleSeconds, status.stale_seconds || 0);
        }
    }

    if (isStale) {
        dot.className = 'freshness-dot stale';
        text.className = 'freshness-text stale';
        text.textContent = `Stale: ${maxStaleSeconds}s ago`;
    } else {
        dot.className = 'freshness-dot';
        text.className = 'freshness-text';
        text.textContent = 'Live';
    }
}

/**
 * Update freshness indicator on error
 */
function updateFreshnessError() {
    const dot = document.getElementById('freshness-dot');
    const text = document.getElementById('freshness-text');

    dot.className = 'freshness-dot stale';
    text.className = 'freshness-text stale';
    text.textContent = 'Error';
}

/**
 * Format timestamp for display
 */
function formatTimestamp(timestamp) {
    if (!timestamp) return '-';

    try {
        const date = new Date(timestamp);
        return date.toLocaleString('en-US', {
            month: 'short',
            day: 'numeric',
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit'
        });
    } catch {
        return timestamp;
    }
}

/**
 * Format price based on exchange
 */
function formatPrice(price, exchange) {
    if (!price) return '-';

    if (exchange === 'upbit') {
        // KRW - no decimals
        return new Intl.NumberFormat('ko-KR', {
            style: 'currency',
            currency: 'KRW',
            maximumFractionDigits: 0
        }).format(price);
    } else {
        // USDT - 2 decimals
        return new Intl.NumberFormat('en-US', {
            style: 'currency',
            currency: 'USD',
            maximumFractionDigits: 2
        }).format(price);
    }
}

/**
 * Format compact price for indicators
 */
function formatCompactPrice(price) {
    if (!price) return '-';

    if (price >= 1000000) {
        return (price / 1000000).toFixed(1) + 'M';
    } else if (price >= 1000) {
        return (price / 1000).toFixed(1) + 'K';
    }
    return price.toFixed(2);
}

/**
 * Format BTC amount
 */
function formatBtc(amount) {
    if (!amount) return '0 BTC';
    return `${amount.toFixed(6)} BTC`;
}

/**
 * Format currency based on exchange
 */
function formatCurrency(amount, exchange) {
    if (exchange === 'upbit') {
        return new Intl.NumberFormat('ko-KR', {
            style: 'currency',
            currency: 'KRW',
            maximumFractionDigits: 0
        }).format(amount);
    } else {
        return new Intl.NumberFormat('en-US', {
            style: 'currency',
            currency: 'USD',
            maximumFractionDigits: 2
        }).format(amount);
    }
}

// Initialize: Fetch data immediately, then start polling
fetchRealtimeMetrics();
fetchDecisionHistory();

setInterval(fetchRealtimeMetrics, POLLING_INTERVAL);
setInterval(fetchDecisionHistory, POLLING_INTERVAL * 3);  // Less frequent for history
