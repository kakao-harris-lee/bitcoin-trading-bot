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
        minute: '2-digit',
        second: '2-digit'
    });
}

// Update status display
function updateStatus(data) {
    // Update timestamp
    document.getElementById('last-update-time').textContent = formatTime(data.timestamp);

    // Update Upbit
    const upbit = data.upbit || {};
    const upbitEnabled = upbit.enabled;
    document.getElementById('upbit-status').textContent = upbitEnabled ? 'Active' : 'Inactive';
    document.getElementById('upbit-status').className = `status-badge ${upbitEnabled ? 'enabled' : 'disabled'}`;
    document.getElementById('upbit-strategy').textContent = upbit.strategy || '-';

    // Regime (from router state if available)
    const regime = upbit.regime || '-';
    const regimeEl = document.getElementById('upbit-regime');
    regimeEl.textContent = regime;
    regimeEl.className = 'value regime-badge';
    if (regime.toLowerCase().includes('bull')) regimeEl.classList.add('bull');
    else if (regime.toLowerCase().includes('bear')) regimeEl.classList.add('bear');
    else if (regime.toLowerCase().includes('sideways')) regimeEl.classList.add('sideways');

    // Upbit position
    const upbitPos = upbit.position;
    if (upbitPos && upbitPos.btc_balance > 0) {
        document.getElementById('upbit-position').textContent = `${upbitPos.btc_balance.toFixed(6)} BTC`;
    } else {
        document.getElementById('upbit-position').textContent = 'No position';
    }

    // Upbit stats
    const upbitStats = upbit.statistics || {};
    document.getElementById('upbit-initial').textContent = formatKRW(upbitStats.initial_capital);
    document.getElementById('upbit-current').textContent = formatKRW(upbitStats.current_cash);

    const upbitReturnEl = document.getElementById('upbit-return');
    upbitReturnEl.textContent = formatPercent(upbitStats.return_pct);
    upbitReturnEl.className = 'stat-value ' + ((upbitStats.return_pct >= 0) ? 'positive' : 'negative');

    document.getElementById('upbit-trades').textContent = upbitStats.total_trades || '-';

    // Update Binance
    const binance = data.binance || {};
    const binanceEnabled = binance.enabled;
    document.getElementById('binance-status').textContent = binanceEnabled ? 'Active' : 'Inactive';
    document.getElementById('binance-status').className = `status-badge ${binanceEnabled ? 'enabled' : 'disabled'}`;
    document.getElementById('binance-strategy').textContent = binance.strategy || '-';

    // Binance position
    const binancePos = binance.position;
    if (binancePos && binancePos.size > 0) {
        document.getElementById('binance-position').textContent = `${binancePos.size.toFixed(4)} BTC`;
        document.getElementById('binance-entry').textContent = formatUSD(binancePos.entry_price);
        document.getElementById('binance-leverage').textContent = `${binancePos.leverage || 1}x`;
    } else {
        document.getElementById('binance-position').textContent = 'No position';
        document.getElementById('binance-entry').textContent = '-';
        document.getElementById('binance-leverage').textContent = '-';
    }

    // Binance stats
    const binanceStats = binance.statistics || {};
    document.getElementById('binance-initial').textContent = formatUSD(binanceStats.initial_capital);
    document.getElementById('binance-current').textContent = formatUSD(binanceStats.current_cash);

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
        text.textContent = 'ACTIVE - Trading halted';
        text.style.color = '#e74c3c';
    } else {
        indicator.className = 'indicator off';
        text.textContent = 'OFF - Trading enabled';
        text.style.color = '#2ecc71';
    }
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

// Fetch recent trades (placeholder - can be extended)
async function fetchTrades() {
    const container = document.getElementById('trades-container');
    try {
        // Try Upbit trades
        const upbitRes = await fetch('/api/trades/upbit');
        const binanceRes = await fetch('/api/trades/binance');

        let trades = [];
        if (upbitRes.ok) {
            const upbitData = await upbitRes.json();
            if (upbitData.trades) {
                trades = trades.concat(upbitData.trades.map(t => ({...t, exchange: 'Upbit'})));
            }
        }
        if (binanceRes.ok) {
            const binanceData = await binanceRes.json();
            if (binanceData.trades) {
                trades = trades.concat(binanceData.trades.map(t => ({...t, exchange: 'Binance'})));
            }
        }

        // Sort by time descending and take recent 10
        trades.sort((a, b) => new Date(b.timestamp || b.time) - new Date(a.timestamp || a.time));
        trades = trades.slice(0, 10);

        if (trades.length === 0) {
            container.innerHTML = '<p class="no-trades">No recent trades</p>';
            return;
        }

        let html = '<div class="trades-list">';
        for (const trade of trades) {
            const action = (trade.action || trade.side || '').toLowerCase();
            const actionClass = action.includes('buy') ? 'buy' : 'sell';
            html += `
                <div class="trade-item">
                    <span class="exchange">${trade.exchange}</span>
                    <span class="action ${actionClass}">${action.toUpperCase()}</span>
                    <span class="amount">${(trade.amount || trade.qty || 0).toFixed(6)}</span>
                    <span class="time">${formatTime(trade.timestamp || trade.time)}</span>
                </div>
            `;
        }
        html += '</div>';
        container.innerHTML = html;
    } catch (err) {
        console.error('Trades fetch error:', err);
        container.innerHTML = '<p class="no-trades">Could not load trades</p>';
    }
}

// Initial load
document.addEventListener('DOMContentLoaded', () => {
    fetchStatus();
    fetchKillSwitch();
    fetchTrades();

    // Auto refresh
    setInterval(() => {
        fetchStatus();
        fetchKillSwitch();
        fetchTrades();
    }, REFRESH_INTERVAL);
});

console.log('Dashboard initialized');
