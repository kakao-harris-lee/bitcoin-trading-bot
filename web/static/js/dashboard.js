/**
 * Multi-Asset Trading Bot Dashboard
 * Real-time status monitoring for Multi-Asset Engine
 */

const REFRESH_INTERVAL = 30000; // 30 seconds

// Format numbers
function formatKRW(value) {
    if (value === null || value === undefined) return '-';
    return new Intl.NumberFormat('ko-KR', {
        style: 'currency',
        currency: 'KRW',
        maximumFractionDigits: 0
    }).format(value);
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

function formatPrice(price, isKRW = true) {
    if (!price) return '-';
    if (isKRW) {
        return new Intl.NumberFormat('ko-KR').format(Math.round(price));
    }
    return new Intl.NumberFormat('en-US', {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2
    }).format(price);
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

// Render asset cards
function renderAssetCards(assets) {
    const container = document.getElementById('assets-grid');
    if (!assets || Object.keys(assets).length === 0) {
        container.innerHTML = '<p class="no-data">No assets available</p>';
        return;
    }

    let html = '';
    for (const [symbol, data] of Object.entries(assets)) {
        const regimeClass = getRegimeClass(data.regime);
        const regimeLabel = getRegimeLabel(data.regime);
        const positionStatus = data.position_active ? 'Active' : 'None';
        const positionClass = data.position_active ? 'has-position' : '';

        // Get active strategy from strategies config
        let activeStrategy = '-';
        if (data.strategies) {
            const regimeKey = data.regime?.split('_')[0] || 'BULL';
            activeStrategy = data.strategies[regimeKey] || data.strategies['BULL'] || '-';
        }

        html += `
            <div class="asset-card ${regimeClass} ${positionClass}">
                <div class="asset-header">
                    <span class="asset-symbol">${symbol}</span>
                    <span class="asset-regime ${regimeClass}">${regimeLabel}</span>
                </div>
                <div class="asset-prices">
                    <div class="price-row">
                        <span class="label">Upbit</span>
                        <span class="value">${formatPrice(data.upbit_price, true)}</span>
                    </div>
                    <div class="price-row">
                        <span class="label">Binance</span>
                        <span class="value">$${formatPrice(data.binance_price, false)}</span>
                    </div>
                </div>
                <div class="asset-allocation">
                    <div class="info-row">
                        <span class="label">Allocation</span>
                        <span class="value">${(data.alpha_ratio * 100).toFixed(0)}%</span>
                    </div>
                    <div class="info-row">
                        <span class="label">Allocated</span>
                        <span class="value">${formatKRW(data.allocated_krw)}</span>
                    </div>
                    <div class="info-row">
                        <span class="label">Position Value</span>
                        <span class="value">${formatKRW(data.position_value_krw)}</span>
                    </div>
                </div>
                <div class="asset-position">
                    <div class="info-row">
                        <span class="label">Strategy</span>
                        <span class="value">${activeStrategy}</span>
                    </div>
                    <div class="info-row">
                        <span class="label">Position</span>
                        <span class="value ${positionClass}">${positionStatus}</span>
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
}

// Update portfolio summary
function updatePortfolio(portfolio) {
    if (!portfolio) return;

    document.getElementById('total-capital').textContent = formatKRW(portfolio.total_capital_krw);
    document.getElementById('total-value').textContent = formatKRW(portfolio.total_value_krw);
    document.getElementById('exposure-pct').textContent = `${(portfolio.exposure_pct || 0).toFixed(1)}%`;

    const pnlEl = document.getElementById('unrealized-pnl');
    const pnl = portfolio.unrealized_pnl || 0;
    pnlEl.textContent = formatKRW(pnl);
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
    // Update Upbit
    if (data.upbit) {
        document.getElementById('upbit-status').textContent = 'Connected';
        document.getElementById('upbit-status').className = 'exchange-status connected';
        document.getElementById('upbit-krw').textContent = formatKRW(data.upbit.krw_balance);
        document.getElementById('upbit-total').textContent = formatKRW(data.upbit.total_krw);

        // Update Upbit positions
        const upbitPositions = data.upbit.positions || [];
        const upbitPosList = document.getElementById('upbit-positions-list');
        if (upbitPositions.length > 0) {
            let html = '';
            for (const pos of upbitPositions) {
                const pnlClass = pos.pnl_krw >= 0 ? 'positive' : 'negative';
                const pnlPctClass = pos.pnl_pct >= 0 ? 'positive' : 'negative';
                html += `
                    <div class="position-item">
                        <div class="position-header">
                            <span class="position-symbol">${pos.symbol}</span>
                            <span class="position-side long">LONG</span>
                        </div>
                        <div class="position-details">
                            <div class="detail-row">
                                <span class="label">Qty</span>
                                <span class="value">${pos.quantity.toFixed(8)}</span>
                            </div>
                            <div class="detail-row">
                                <span class="label">Avg Price</span>
                                <span class="value">${formatPrice(pos.avg_price, true)}</span>
                            </div>
                            <div class="detail-row">
                                <span class="label">Value</span>
                                <span class="value">${formatKRW(pos.value_krw)}</span>
                            </div>
                            <div class="detail-row">
                                <span class="label">PnL</span>
                                <span class="value ${pnlClass}">${formatKRW(pos.pnl_krw)} (${pos.pnl_pct >= 0 ? '+' : ''}${pos.pnl_pct.toFixed(2)}%)</span>
                            </div>
                        </div>
                    </div>
                `;
            }
            upbitPosList.innerHTML = html;
        } else {
            upbitPosList.innerHTML = '<span class="no-positions">No positions</span>';
        }
    } else {
        document.getElementById('upbit-status').textContent = 'Error';
        document.getElementById('upbit-status').className = 'exchange-status error';
    }

    // Update Binance
    if (data.binance) {
        document.getElementById('binance-status').textContent = 'Connected';
        document.getElementById('binance-status').className = 'exchange-status connected';
        document.getElementById('binance-usdt').textContent = formatUSD(data.binance.usdt_balance);
        document.getElementById('binance-total').textContent = formatUSD(data.binance.total_equity);

        // Update Binance positions
        const binancePositions = data.binance.positions || [];
        const binancePosList = document.getElementById('binance-positions-list');
        if (binancePositions.length > 0) {
            let html = '';
            for (const pos of binancePositions) {
                const side = pos.size > 0 ? 'LONG' : 'SHORT';
                const sideClass = pos.size > 0 ? 'long' : 'short';
                const pnlClass = pos.unrealized_pnl >= 0 ? 'positive' : 'negative';
                html += `
                    <div class="position-item">
                        <div class="position-header">
                            <span class="position-symbol">${pos.symbol}</span>
                            <span class="position-side ${sideClass}">${side}</span>
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
                                <span class="label">PnL</span>
                                <span class="value ${pnlClass}">${formatUSD(pos.unrealized_pnl)}</span>
                            </div>
                        </div>
                    </div>
                `;
            }
            binancePosList.innerHTML = html;
        } else {
            binancePosList.innerHTML = '<span class="no-positions">No positions</span>';
        }
    } else {
        document.getElementById('binance-status').textContent = 'Error';
        document.getElementById('binance-status').className = 'exchange-status error';
    }

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
        document.getElementById('upbit-status').textContent = 'Error';
        document.getElementById('upbit-status').className = 'exchange-status error';
        document.getElementById('binance-status').textContent = 'Error';
        document.getElementById('binance-status').className = 'exchange-status error';
    }
}

// Fetch all data
async function fetchAll() {
    await Promise.all([
        fetchStatus(),
        fetchKillSwitch(),
        fetchExchangeBalances(),
    ]);
}

// Initial load
document.addEventListener('DOMContentLoaded', () => {
    fetchAll();

    // Auto refresh
    setInterval(fetchAll, REFRESH_INTERVAL);
});

console.log('Multi-Asset Dashboard initialized');
