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

// Render last signal card
function renderLastSignal(signal, containerId) {
    const container = document.getElementById(containerId);
    if (!signal) {
        container.innerHTML = '<p class="no-data">No signal yet</p>';
        return;
    }

    const actionClass = signal.action === 'buy' || signal.action === 'short' ? 'action-entry' :
                       signal.action === 'sell' || signal.action === 'close' ? 'action-exit' : 'action-hold';

    // Format indicators if available
    let indicatorStr = '';
    if (signal.indicators) {
        const parts = [];
        if (signal.indicators.rsi !== undefined) parts.push(`RSI:${signal.indicators.rsi}`);
        if (signal.indicators.mfi !== undefined) parts.push(`MFI:${signal.indicators.mfi}`);
        if (signal.indicators.adx !== undefined) parts.push(`ADX:${signal.indicators.adx}`);
        if (signal.indicators.score !== undefined) parts.push(`Score:${signal.indicators.score}`);
        indicatorStr = parts.join(' | ');
    }

    container.innerHTML = `
        <div class="last-signal-item">
            <div class="signal-header">
                <span class="signal-time">${formatTime(signal.timestamp)}</span>
                <span class="signal-strategy">${signal.strategy || '-'}</span>
                <span class="signal-action ${actionClass}">${(signal.action || 'hold').toUpperCase()}</span>
            </div>
            <div class="signal-reason">${signal.reason || '-'}</div>
            ${indicatorStr ? `<div class="signal-indicators">${indicatorStr}</div>` : ''}
        </div>
    `;
}

// Update per-strategy allocation display with position info
function updateStrategiesInfo(strategies) {
    if (!strategies) return;

    // v35
    const v35 = strategies.v35 || {};
    const v35Row = document.getElementById('upbit-v35-row');
    if (v35Row) {
        v35Row.classList.toggle('disabled', !v35.enabled);
        v35Row.classList.toggle('has-position', v35.active);

        // Show position or cash
        let v35Status = '';
        if (v35.active && v35.btc > 0) {
            v35Status = `${v35.btc.toFixed(6)} BTC`;
        } else if (v35.cash > 0) {
            v35Status = formatKRW(v35.cash);
        } else {
            v35Status = v35.enabled ? `${(v35.ratio * 100).toFixed(0)}%` : 'OFF';
        }
        document.getElementById('upbit-v35-ratio').textContent = v35Status;
        document.getElementById('upbit-v35-regimes').textContent = v35.regimes ? v35.regimes.join('/') : '-';
    }

    // va02
    const va02 = strategies.va02 || {};
    const va02Row = document.getElementById('upbit-va02-row');
    if (va02Row) {
        va02Row.classList.toggle('disabled', !va02.enabled);
        va02Row.classList.toggle('has-position', va02.active);

        // Show position or cash
        let va02Status = '';
        if (va02.active && va02.btc > 0) {
            va02Status = `${va02.btc.toFixed(6)} BTC`;
        } else if (va02.cash > 0) {
            va02Status = formatKRW(va02.cash);
        } else {
            va02Status = va02.enabled ? `${(va02.ratio * 100).toFixed(0)}%` : 'OFF';
        }
        document.getElementById('upbit-va02-ratio').textContent = va02Status;
        document.getElementById('upbit-va02-regimes').textContent = va02.regimes ? va02.regimes.join('/') : '-';
    }
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
    // Use current_cash from response root level if available
    const upbitCash = upbit.current_cash || upbitStats.current_cash;
    document.getElementById('upbit-cash').textContent = formatKRW(upbitCash);
    const upbitReturnEl = document.getElementById('upbit-return');
    upbitReturnEl.textContent = formatPercent(upbitStats.return_pct);
    upbitReturnEl.className = 'stat-value ' + ((upbitStats.return_pct >= 0) ? 'positive' : 'negative');

    // Update per-strategy info
    updateStrategiesInfo(upbit.strategies);

    // Update last signal
    renderLastSignal(upbit.last_signal, 'upbit-last-signal');

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
    const binanceCash = binance.current_cash || binanceStats.current_cash;
    document.getElementById('binance-cash').textContent = formatUSD(binanceCash);
    const binanceReturnEl = document.getElementById('binance-return');
    binanceReturnEl.textContent = formatPercent(binanceStats.return_pct);
    binanceReturnEl.className = 'stat-value ' + ((binanceStats.return_pct >= 0) ? 'positive' : 'negative');

    // Update last signal
    renderLastSignal(binance.last_signal, 'binance-last-signal');
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

// Fetch signals for an exchange
async function fetchSignals(exchange) {
    try {
        const response = await fetch(`/api/signals/${exchange}`, { credentials: 'include' });
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
        const response = await fetch(`/api/trades/${exchange}`, { credentials: 'include' });
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

// Update hedge info display
function updateHedgeInfo(data) {
    if (!data || data.error) {
        return;
    }

    // Kimchi Premium
    const premium = data.kimchi_premium || {};
    const premiumStats = data.premium_stats || {};

    const premiumPct = premium.premium_pct || 0;
    const premiumEl = document.getElementById('premium-value');
    if (premiumEl) {
        premiumEl.textContent = `${premiumPct >= 0 ? '+' : ''}${premiumPct.toFixed(2)}%`;
        premiumEl.className = `premium-value ${premiumPct >= 0 ? 'positive' : 'negative'}`;
    }

    // Trend indicator
    const trendEl = document.getElementById('premium-trend');
    if (trendEl) {
        const volatility = premiumStats.volatility_state || 'normal';
        const trend = premiumStats.trend || 'stable';
        const volEmoji = volatility === 'high' ? '🔴' : volatility === 'elevated' ? '🟡' : '🟢';
        const trendEmoji = trend === 'rising' ? '📈' : trend === 'falling' ? '📉' : '➡️';
        trendEl.textContent = `${volEmoji} ${trendEmoji}`;
    }

    // Premium stats
    const meanEl = document.getElementById('premium-mean');
    if (meanEl) meanEl.textContent = `${(premiumStats.mean_24h || 0).toFixed(2)}%`;

    const stdEl = document.getElementById('premium-std');
    if (stdEl) stdEl.textContent = `±${(premiumStats.std_24h || 0).toFixed(2)}%`;

    const volEl = document.getElementById('premium-volatility');
    if (volEl) volEl.textContent = premiumStats.volatility_state || 'normal';

    // Price comparison
    const upbitUsdEl = document.getElementById('upbit-usd-price');
    if (upbitUsdEl) upbitUsdEl.textContent = (premium.upbit_usd || 0).toLocaleString();

    const binanceUsdEl = document.getElementById('binance-usd-price');
    if (binanceUsdEl) binanceUsdEl.textContent = (premium.binance_usd || 0).toLocaleString();

    // Hedge Ratio
    const hedge = data.hedge_ratio || {};
    const currentRatio = (hedge.hedge_ratio || 0) * 100;
    const targetRatio = (hedge.adjusted_target || hedge.target || 0.5) * 100;

    // Update bar
    const barEl = document.getElementById('ratio-bar');
    if (barEl) barEl.style.width = `${Math.min(currentRatio, 100)}%`;

    // Update target marker
    const markerEl = document.getElementById('ratio-target-marker');
    if (markerEl) markerEl.style.left = `${targetRatio}%`;

    // Update labels
    const currentEl = document.getElementById('ratio-current');
    if (currentEl) currentEl.textContent = `${currentRatio.toFixed(1)}%`;

    const targetEl = document.getElementById('ratio-target');
    if (targetEl) targetEl.textContent = `Target: ${targetRatio.toFixed(0)}%`;

    // Exposure stats
    const longEl = document.getElementById('long-exposure');
    if (longEl) longEl.textContent = formatKRW(hedge.long_exposure_krw || 0);

    const shortEl = document.getElementById('short-exposure');
    if (shortEl) shortEl.textContent = formatKRW(hedge.short_exposure_krw || 0);

    const adjEl = document.getElementById('hedge-adjustment');
    if (adjEl) adjEl.textContent = hedge.adjustment_reason || 'normal';
}

// Fetch hedge info
async function fetchHedgeInfo() {
    try {
        const response = await fetch('/api/hedge', { credentials: 'include' });
        if (!response.ok) return;
        const data = await response.json();
        updateHedgeInfo(data);
    } catch (err) {
        console.error('Hedge info fetch error:', err);
    }
}

// Fetch all data
async function fetchAll() {
    await Promise.all([
        fetchStatus(),
        fetchKillSwitch(),
        fetchHedgeInfo(),
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
