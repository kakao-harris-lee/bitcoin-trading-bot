/**
 * Bitcoin Trading Bot Dashboard
 * Real-time status monitoring for Dual Exchange Engine
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

function formatPercent(value) {
    if (value === null || value === undefined) return '-';
    const percent = (value * 100).toFixed(2);
    return `${percent >= 0 ? '+' : ''}${percent}%`;
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

// Update Market Regime display
function updateMarketRegime(regime, marketState) {
    const section = document.querySelector('.regime-section');
    const iconEl = document.getElementById('market-regime-icon');
    const labelEl = document.getElementById('market-regime-label');
    const detailEl = document.getElementById('market-state-detail');

    section.classList.remove('regime-bull', 'regime-bear', 'regime-sideways');

    if (!regime || regime === '-') {
        iconEl.textContent = '-';
        labelEl.textContent = 'Loading...';
        detailEl.textContent = '-';
        return;
    }

    const regimeLower = regime.toLowerCase();
    if (regimeLower.includes('bull')) {
        section.classList.add('regime-bull');
        iconEl.textContent = 'BULL';
        labelEl.textContent = 'Uptrend';
    } else if (regimeLower.includes('bear')) {
        section.classList.add('regime-bear');
        iconEl.textContent = 'BEAR';
        labelEl.textContent = 'Downtrend';
    } else if (regimeLower.includes('sideways')) {
        section.classList.add('regime-sideways');
        iconEl.textContent = 'SIDE';
        labelEl.textContent = 'Sideways';
    } else {
        iconEl.textContent = '?';
        labelEl.textContent = regime;
    }

    detailEl.textContent = marketState || '-';
}

// Update status display
function updateStatus(data) {
    document.getElementById('last-update-time').textContent = formatTime(data.timestamp);

    // Market Regime
    const market = data.market || {};
    updateMarketRegime(market.regime, market.market_state);

    // Upbit
    const upbit = data.upbit || {};
    const upbitEnabled = upbit.enabled;
    document.getElementById('upbit-status').textContent = upbitEnabled ? 'Active' : 'Inactive';
    document.getElementById('upbit-status').className = `status-badge ${upbitEnabled ? 'enabled' : 'disabled'}`;
    document.getElementById('upbit-strategy').textContent = upbit.strategy || '-';

    const upbitPos = upbit.position;
    if (upbitPos && upbitPos.btc_balance > 0) {
        document.getElementById('upbit-position').textContent = `${upbitPos.btc_balance.toFixed(6)} BTC`;
    } else {
        document.getElementById('upbit-position').textContent = 'No position';
    }

    const upbitStats = upbit.statistics || {};
    document.getElementById('upbit-cash').textContent = formatKRW(upbitStats.current_cash);
    const upbitReturnEl = document.getElementById('upbit-return');
    upbitReturnEl.textContent = formatPercent(upbitStats.return_pct);
    upbitReturnEl.className = 'stat-value ' + ((upbitStats.return_pct >= 0) ? 'positive' : 'negative');

    // Binance
    const binance = data.binance || {};
    const binanceEnabled = binance.enabled;
    document.getElementById('binance-status').textContent = binanceEnabled ? 'Active' : 'Inactive';
    document.getElementById('binance-status').className = `status-badge ${binanceEnabled ? 'enabled' : 'disabled'}`;
    document.getElementById('binance-strategy').textContent = binance.strategy || '-';

    const binancePos = binance.position;
    if (binancePos && binancePos.size > 0) {
        document.getElementById('binance-position').textContent = `${binancePos.size.toFixed(4)} BTC`;
        document.getElementById('binance-entry').textContent = formatUSD(binancePos.entry_price);
    } else {
        document.getElementById('binance-position').textContent = 'No position';
        document.getElementById('binance-entry').textContent = '-';
    }

    const binanceStats = binance.statistics || {};
    document.getElementById('binance-cash').textContent = formatUSD(binanceStats.current_cash);
    const binanceReturnEl = document.getElementById('binance-return');
    binanceReturnEl.textContent = formatPercent(binanceStats.return_pct);
    binanceReturnEl.className = 'stat-value ' + ((binanceStats.return_pct >= 0) ? 'positive' : 'negative');
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

// Render signals list
function renderSignals(signals, containerId) {
    const container = document.getElementById(containerId);

    if (!signals || signals.length === 0) {
        container.innerHTML = '<p class="no-data">No signals yet</p>';
        return;
    }

    // Show last 10, newest first
    const recentSignals = signals.slice(-10).reverse();

    let html = '';
    for (const sig of recentSignals) {
        const actionClass = sig.action === 'buy' || sig.action === 'short' ? 'action-entry' :
                           sig.action === 'sell' || sig.action === 'close' ? 'action-exit' : 'action-hold';

        // Format indicators
        let indicatorStr = '';
        if (sig.indicators) {
            const parts = [];
            if (sig.indicators.rsi !== undefined) parts.push(`RSI:${sig.indicators.rsi}`);
            if (sig.indicators.mfi !== undefined) parts.push(`MFI:${sig.indicators.mfi}`);
            if (sig.indicators.adx !== undefined) parts.push(`ADX:${sig.indicators.adx}`);
            if (sig.indicators.stoch_k !== undefined) parts.push(`K:${sig.indicators.stoch_k}`);
            indicatorStr = parts.join(' ');
        }

        html += `
            <div class="signal-item">
                <div class="signal-header">
                    <span class="signal-time">${formatTime(sig.timestamp)}</span>
                    <span class="signal-strategy">${sig.strategy || '-'}</span>
                    <span class="signal-action ${actionClass}">${(sig.action || 'hold').toUpperCase()}</span>
                </div>
                <div class="signal-details">
                    <span class="signal-reason">${sig.reason || '-'}</span>
                    ${indicatorStr ? `<span class="signal-indicators">${indicatorStr}</span>` : ''}
                </div>
            </div>
        `;
    }
    container.innerHTML = html;
}

// Render trades list
function renderTrades(trades, containerId) {
    const container = document.getElementById(containerId);

    if (!trades || trades.length === 0) {
        container.innerHTML = '<p class="no-data">No trades yet</p>';
        return;
    }

    // Show last 10, newest first
    const recentTrades = trades.slice(-10).reverse();

    let html = '';
    for (const trade of recentTrades) {
        const action = (trade.type || trade.action || '').toLowerCase();
        const actionClass = action.includes('buy') || action.includes('open') ? 'action-entry' : 'action-exit';

        html += `
            <div class="trade-item">
                <span class="trade-time">${formatDateTime(trade.timestamp)}</span>
                <span class="trade-action ${actionClass}">${action.toUpperCase()}</span>
                <span class="trade-price">${trade.price ? (trade.price > 1000 ? formatKRW(trade.price) : formatUSD(trade.price)) : '-'}</span>
            </div>
        `;
    }
    container.innerHTML = html;
}

// Fetch and update status
async function fetchStatus() {
    try {
        const response = await fetch('/api/status');
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
        const response = await fetch('/api/kill_switch/status');
        if (!response.ok) throw new Error('Kill switch fetch failed');
        const data = await response.json();
        updateKillSwitch(data);
    } catch (err) {
        console.error('Kill switch fetch error:', err);
    }
}

// Fetch signals for an exchange
async function fetchSignals(exchange) {
    try {
        const response = await fetch(`/api/signals/${exchange}`);
        if (response.ok) {
            const data = await response.json();
            renderSignals(data.signals, `${exchange}-signals`);
        } else {
            renderSignals([], `${exchange}-signals`);
        }
    } catch (err) {
        console.error(`Signals fetch error (${exchange}):`, err);
        renderSignals([], `${exchange}-signals`);
    }
}

// Fetch trades for an exchange
async function fetchTrades(exchange) {
    try {
        const response = await fetch(`/api/trades/${exchange}`);
        if (response.ok) {
            const data = await response.json();
            renderTrades(data.trades, `${exchange}-trades`);
        } else {
            renderTrades([], `${exchange}-trades`);
        }
    } catch (err) {
        console.error(`Trades fetch error (${exchange}):`, err);
        renderTrades([], `${exchange}-trades`);
    }
}

// Fetch all data
async function fetchAll() {
    await Promise.all([
        fetchStatus(),
        fetchKillSwitch(),
        fetchSignals('upbit'),
        fetchSignals('binance'),
        fetchTrades('upbit'),
        fetchTrades('binance')
    ]);
}

// Initial load
document.addEventListener('DOMContentLoaded', () => {
    fetchAll();

    // Auto refresh
    setInterval(fetchAll, REFRESH_INTERVAL);
});

console.log('Dashboard initialized');
