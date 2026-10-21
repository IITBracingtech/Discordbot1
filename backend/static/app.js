/* ==============================================================================
   RACE CONTROL ACTIVITY MONITOR CONTROLLER
   ============================================================================== */

let currentCategory = 'ALL';

const statusPill = document.getElementById('gateway-status-pill');
const statusLabel = document.getElementById('gateway-status-label');
const statPing = document.getElementById('stat-ping');
const statTotalPings = document.getElementById('stat-total-pings');
const statTotalApi = document.getElementById('stat-total-api');
const feedContainer = document.getElementById('activity-feed');
const logCountLabel = document.getElementById('log-count-label');
const btnManualPing = document.getElementById('btn-manual-ping');

// Format date helper (IST time)
function formatTime(isoStr) {
  if (!isoStr) return '—';
  try {
    const d = new Date(isoStr);
    return d.toLocaleTimeString('en-IN', {
      timeZone: 'Asia/Kolkata',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit'
    });
  } catch (e) {
    return isoStr;
  }
}

// Fetch logs and stats
async function fetchActivity() {
  try {
    const res = await fetch(`/api/health/logs?category=${currentCategory}&limit=100`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();

    updateStats(data.stats, data.bot_connected, data.current_ping_ms);
    renderFeed(data.logs);
  } catch (err) {
    console.error('Failed to load activity:', err);
  }
}

// Update header and stats bar
function updateStats(stats, isConnected, currentPingMs) {
  if (isConnected) {
    statusPill.className = 'status-pill online';
    statusLabel.textContent = 'GATEWAY: CONNECTED';
  } else {
    statusPill.className = 'status-pill offline';
    statusLabel.textContent = 'GATEWAY: RECONNECTING';
  }

  if (currentPingMs !== null && currentPingMs !== undefined) {
    statPing.textContent = `${currentPingMs} ms`;
  } else {
    statPing.textContent = '—';
  }

  if (stats) {
    statTotalPings.textContent = stats.total_discord_pings || 0;
    statTotalApi.textContent = stats.total_api_calls || 0;
  }
}

// Render activity cards
function renderFeed(logs) {
  if (!feedContainer) return;

  if (!logs || logs.length === 0) {
    feedContainer.innerHTML = `<div class="empty-state">No activity logged yet.</div>`;
    if (logCountLabel) logCountLabel.textContent = '0 entries';
    return;
  }

  if (logCountLabel) logCountLabel.textContent = `${logs.length} events logged`;

  feedContainer.innerHTML = logs.map(l => {
    const isPing = l.category === 'DISCORD_PING';
    const tagClass = isPing ? 'tag-ping' : 'tag-api';
    const tagLabel = isPing ? '⚡ DISCORD PING' : '🌐 API CALL';

    let latencyClass = 'fast';
    if (l.latency_ms > 150) latencyClass = 'slow';
    else if (l.latency_ms > 50) latencyClass = 'mid';

    const latencyText = l.latency_ms !== null && l.latency_ms !== undefined ? `${l.latency_ms} ms` : (l.status || 'ACK');

    return `
      <div class="activity-card">
        <div class="card-left">
          <span class="category-tag ${tagClass}">${tagLabel}</span>
          <div class="card-details">
            <span class="card-title">${escapeHtml(l.title)}</span>
            <span class="card-sub">${escapeHtml(l.details || l.status || '')}</span>
          </div>
        </div>
        <div class="card-right">
          <span class="card-latency ${latencyClass}">${latencyText}</span>
          <span class="card-time">${formatTime(l.timestamp)}</span>
        </div>
      </div>
    `;
  }).join('');
}

// Manual ping trigger
if (btnManualPing) {
  btnManualPing.addEventListener('click', async () => {
    const oldHtml = btnManualPing.innerHTML;
    btnManualPing.disabled = true;
    btnManualPing.innerHTML = `<span>⏳</span> Pinging...`;

    try {
      await fetch('/api/health/ping', { method: 'POST' });
      await fetchActivity();
    } catch (e) {
      console.error('Ping failed:', e);
    } finally {
      btnManualPing.disabled = false;
      btnManualPing.innerHTML = oldHtml;
    }
  });
}

// Filter tabs
document.querySelectorAll('.tab-btn').forEach(btn => {
  btn.addEventListener('click', (e) => {
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    e.target.classList.add('active');
    currentCategory = e.target.dataset.category || 'ALL';
    fetchActivity();
  });
});

function escapeHtml(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

// Initial Boot & 4-second Polling Loop
document.addEventListener('DOMContentLoaded', () => {
  fetchActivity();
  setInterval(fetchActivity, 4000);
});
