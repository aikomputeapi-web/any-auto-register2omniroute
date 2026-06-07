/**
 * dashboard.js — Real-time DevTools Inspector Dashboard
 * Connects via SSE for live events and REST for on-demand data.
 */

const API = '';  // same origin

// ─── State ────────────────────────────────────────────────────────────────
let networkEntries = [];
let consoleLogs = [];
let sseConnected = false;
let activeNetworkRow = null;
let activeDetailTab = 'headers';
let consoleLevel = '';

// ─── Helpers ──────────────────────────────────────────────────────────────

async function api(path, options = {}) {
  try {
    const res = await fetch(API + path, options);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return await res.json();
  } catch (err) {
    console.error('[API]', path, err.message);
    return null;
  }
}

function fmtUrl(url) {
  try {
    const u = new URL(url);
    return { host: u.host, path: u.pathname + u.search };
  } catch {
    return { host: '', path: url };
  }
}

function fmtTime(ms) {
  const d = new Date(ms);
  return d.toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

function statusClass(status) {
  if (!status) return 'status-pending';
  if (status < 300) return 'status-2xx';
  if (status < 400) return 'status-3xx';
  if (status < 500) return 'status-4xx';
  return 'status-5xx';
}

function methodClass(method) {
  return `method-${(method || 'GET').toUpperCase()}`;
}

function escHtml(str) {
  return String(str || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function syntaxHighlightJSON(json) {
  if (typeof json !== 'string') json = JSON.stringify(json, null, 2);
  return json.replace(/("(\\u[a-zA-Z0-9]{4}|\\[^u]|[^\\"])*"(\s*:)?|\b(true|false|null)\b|-?\d+(?:\.\d*)?(?:[eE][+\-]?\d+)?)/g, match => {
    let cls = 'json-number';
    if (/^"/.test(match)) cls = /:$/.test(match) ? 'json-key' : 'json-string';
    else if (/true|false/.test(match)) cls = 'json-bool';
    else if (/null/.test(match)) cls = 'json-null';
    return `<span class="${cls}">${escHtml(match)}</span>`;
  });
}

function prettyJSON(str) {
  try {
    const parsed = JSON.parse(str);
    return syntaxHighlightJSON(JSON.stringify(parsed, null, 2));
  } catch {
    return escHtml(str);
  }
}

// ─── Status ───────────────────────────────────────────────────────────────

async function refreshStatus() {
  const data = await api('/status');
  if (!data) return;

  const dot = document.getElementById('status-dot');
  const label = document.getElementById('status-label');
  const page = document.getElementById('status-page');

  if (data.connected) {
    dot.className = 'status-indicator connected';
    label.textContent = 'Connected';
    page.textContent = data.page?.url ? `— ${data.page.url}` : '';
  } else {
    dot.className = 'status-indicator disconnected';
    label.textContent = 'Not connected';
    page.textContent = '';
  }

  // Update event bar stats
  document.getElementById('stat-requests').textContent = data.buffer?.networkRequests ?? 0;
}

// ─── Network ──────────────────────────────────────────────────────────────

function renderNetworkRow(entry) {
  const { host, path } = fmtUrl(entry.url);
  const status = entry.response?.status;
  const failed = entry.response?.failed;

  const tr = document.createElement('tr');
  tr.dataset.id = entry.id;
  tr.innerHTML = `
    <td><span class="status-pill ${failed ? 'status-failed' : statusClass(status)}">${failed ? 'ERR' : (status || '…')}</span></td>
    <td><span class="method-pill ${methodClass(entry.method)}">${escHtml(entry.method || 'GET')}</span></td>
    <td><span class="type-badge">${escHtml(entry.resourceType || '')}</span></td>
    <td class="url-cell"><span class="url-host">${escHtml(host)}</span>${escHtml(path)}</td>
    <td style="color:var(--text-faint);font-family:var(--mono);font-size:10px">${fmtTime(entry.wallTime || entry.timestamp)}</td>
  `;
  tr.addEventListener('click', () => openNetworkDetail(entry, tr));
  return tr;
}

async function loadNetwork() {
  const urlFilter = document.getElementById('network-filter').value;
  const method = document.getElementById('network-method').value;
  const type = document.getElementById('network-type').value;

  const params = new URLSearchParams();
  if (urlFilter) params.set('url', urlFilter);
  if (method) params.set('method', method);
  if (type) params.set('resourceType', type);

  const data = await api(`/network?${params}`);
  if (!data) return;

  networkEntries = data.entries;
  renderNetworkTable(networkEntries);

  document.getElementById('badge-network').textContent = networkEntries.length;
  document.getElementById('stat-requests').textContent = networkEntries.length;

  const errorCount = networkEntries.filter(e => e.response?.failed || (e.response?.status >= 400)).length;
  const errBadge = document.getElementById('badge-errors');
  document.getElementById('stat-errors').textContent = errorCount;
  if (errorCount > 0) {
    errBadge.textContent = errorCount;
    errBadge.classList.remove('hidden');
    errBadge.classList.add('error-badge');
  } else {
    errBadge.classList.add('hidden');
  }
}

function renderNetworkTable(entries) {
  const tbody = document.getElementById('network-tbody');
  const empty = document.getElementById('network-empty');
  tbody.innerHTML = '';

  if (entries.length === 0) {
    empty.style.display = 'flex';
    return;
  }
  empty.style.display = 'none';

  for (const entry of entries) {
    tbody.appendChild(renderNetworkRow(entry));
  }
}

async function openNetworkDetail(entry, tr) {
  // Deselect old
  if (activeNetworkRow) activeNetworkRow.classList.remove('selected');
  activeNetworkRow = tr;
  tr.classList.add('selected');

  // Fetch fresh detail
  const detail = await api(`/network/${entry.id}`) || entry;

  const drawer = document.getElementById('network-detail');
  drawer.classList.add('open');
  document.getElementById('detail-url').textContent = detail.url;

  renderDetailTab(detail, activeDetailTab);
}

function renderDetailTab(detail, tab) {
  const content = document.getElementById('detail-content');

  if (tab === 'headers') {
    const reqH = detail.headers || {};
    const resH = detail.response?.headers || {};
    content.innerHTML = `
      <div style="margin-bottom:12px">
        <div style="color:var(--text-dim);font-weight:600;margin-bottom:6px">Request Headers</div>
        ${Object.entries(reqH).map(([k,v]) => `<div><span style="color:var(--accent2)">${escHtml(k)}:</span> ${escHtml(v)}</div>`).join('')}
      </div>
      <div>
        <div style="color:var(--text-dim);font-weight:600;margin-bottom:6px">Response Headers</div>
        ${Object.entries(resH).map(([k,v]) => `<div><span style="color:var(--accent2)">${escHtml(k)}:</span> ${escHtml(v)}</div>`).join('')}
      </div>`;
  } else if (tab === 'body') {
    const body = detail.body;
    if (!body) {
      content.innerHTML = `<span style="color:var(--text-faint)">No response body captured (binary or too large)</span>`;
    } else {
      content.innerHTML = `<pre style="white-space:pre-wrap;word-break:break-all">${prettyJSON(body)}</pre>`;
    }
  } else if (tab === 'request') {
    const info = {
      url: detail.url,
      method: detail.method,
      resourceType: detail.resourceType,
      timestamp: detail.timestamp,
      postData: detail.postData,
      redirectFrom: detail.redirectFrom,
    };
    content.innerHTML = `<pre>${syntaxHighlightJSON(info)}</pre>`;
  }
}

// ─── Console ──────────────────────────────────────────────────────────────

function renderConsoleEntry(log) {
  const div = document.createElement('div');
  const level = log.level || 'log';
  div.className = `console-entry ${['error','warning','info'].includes(level) ? level : ''}`;

  const source = log.url ? `${log.url}${log.line ? ':' + log.line : ''}` : (log.source || '');

  div.innerHTML = `
    <span class="console-level level-${level}">${level}</span>
    <span class="console-text">${escHtml(log.text)}</span>
    ${source ? `<span class="console-source" title="${escHtml(source)}">${escHtml(source.split('/').pop() || source)}</span>` : ''}
  `;
  return div;
}

async function loadConsole() {
  const params = new URLSearchParams();
  if (consoleLevel) params.set('level', consoleLevel);

  const data = await api(`/console?${params}`);
  if (!data) return;

  const filter = document.getElementById('console-filter').value.toLowerCase();
  consoleLogs = data.logs;

  const output = document.getElementById('console-output');
  const empty = document.getElementById('console-empty');

  const filtered = filter ? consoleLogs.filter(l => (l.text || '').toLowerCase().includes(filter)) : consoleLogs;

  output.innerHTML = '';
  if (filtered.length === 0) {
    output.appendChild(empty);
    empty.style.display = 'flex';
    return;
  }
  empty.style.display = 'none';

  const frag = document.createDocumentFragment();
  for (const log of filtered) frag.appendChild(renderConsoleEntry(log));
  output.appendChild(frag);
  output.scrollTop = output.scrollHeight;
}

// ─── DOM ──────────────────────────────────────────────────────────────────

async function loadDOMSnapshot() {
  const content = document.getElementById('dom-content');
  content.innerHTML = `<div style="padding:20px;color:var(--text-dim)">Loading DOM...</div>`;

  const data = await api('/dom?format=json');
  if (!data) return;

  content.innerHTML = `<div class="dom-html-block">${escHtml(data.html || '')}</div>`;
}

async function queryDOM() {
  const selector = document.getElementById('dom-selector').value.trim();
  if (!selector) return;

  const content = document.getElementById('dom-content');
  content.innerHTML = `<div style="padding:20px;color:var(--text-dim)">Querying...</div>`;

  const data = await api(`/dom/query?selector=${encodeURIComponent(selector)}`);
  if (!data) return;

  if (data.count === 0) {
    content.innerHTML = `<div class="empty-state"><div class="empty-icon">⌀</div><p>No elements matched <code style="color:var(--accent)">${escHtml(selector)}</code></p></div>`;
    return;
  }

  const frag = document.createDocumentFragment();
  const header = document.createElement('div');
  header.style.cssText = 'padding:10px 12px;color:var(--text-dim);font-size:12px;border-bottom:1px solid var(--border)';
  header.textContent = `${data.count} element${data.count !== 1 ? 's' : ''} matched "${selector}"`;
  frag.appendChild(header);

  for (const node of data.nodes) {
    const card = document.createElement('div');
    card.className = 'dom-node fade-in';
    card.innerHTML = `
      <div>
        <span class="dom-node-tag">&lt;${escHtml(node.tag?.toLowerCase())}</span>
        ${node.id ? `<span class="dom-node-id"> #${escHtml(node.id)}</span>` : ''}
        ${node.className ? `<span class="dom-node-class"> .${escHtml(node.className.split(' ').join(' .'))}</span>` : ''}
        <span class="dom-node-tag">&gt;</span>
      </div>
      ${Object.keys(node.attributes || {}).length > 0
        ? `<div style="margin-top:4px;color:var(--text-faint)">${Object.entries(node.attributes).filter(([k]) => k !== 'id' && k !== 'class').map(([k,v]) => `<span style="color:var(--accent2)">${escHtml(k)}</span>="${escHtml(v)}"`).join(' ')}</div>`
        : ''}
      ${node.textContent ? `<div class="dom-node-text">${escHtml(node.textContent)}</div>` : ''}
    `;
    frag.appendChild(card);
  }

  content.innerHTML = '';
  content.appendChild(frag);
}

// ─── Storage ──────────────────────────────────────────────────────────────

async function loadStorage() {
  const content = document.getElementById('storage-content');
  content.innerHTML = `<div style="padding:20px;color:var(--text-dim)">Loading...</div>`;

  const [storageData, cookieData] = await Promise.all([api('/storage'), api('/cookies')]);

  content.innerHTML = '';

  // localStorage
  const lsSection = document.createElement('div');
  lsSection.className = 'storage-section';
  const ls = storageData?.localStorage || {};
  lsSection.innerHTML = `<h3>localStorage (${Object.keys(ls).length} items)</h3>` +
    (Object.keys(ls).length === 0
      ? '<div style="color:var(--text-faint);font-size:12px">Empty</div>'
      : Object.entries(ls).map(([k, v]) =>
          `<div class="storage-row"><span class="storage-key" title="${escHtml(k)}">${escHtml(k)}</span><span class="storage-val" title="${escHtml(v)}">${escHtml(v)}</span></div>`
        ).join(''));
  content.appendChild(lsSection);

  // sessionStorage
  const ssSection = document.createElement('div');
  ssSection.className = 'storage-section';
  const ss = storageData?.sessionStorage || {};
  ssSection.innerHTML = `<h3>sessionStorage (${Object.keys(ss).length} items)</h3>` +
    (Object.keys(ss).length === 0
      ? '<div style="color:var(--text-faint);font-size:12px">Empty</div>'
      : Object.entries(ss).map(([k, v]) =>
          `<div class="storage-row"><span class="storage-key" title="${escHtml(k)}">${escHtml(k)}</span><span class="storage-val" title="${escHtml(v)}">${escHtml(v)}</span></div>`
        ).join(''));
  content.appendChild(ssSection);

  // Cookies
  const cookieSection = document.createElement('div');
  cookieSection.className = 'storage-section';
  const cookies = cookieData?.cookies || [];
  cookieSection.innerHTML = `<h3>Cookies (${cookies.length})</h3>` +
    (cookies.length === 0
      ? '<div style="color:var(--text-faint);font-size:12px">No cookies</div>'
      : `<table class="cookie-table">${cookies.map(c =>
          `<tr><td>${escHtml(c.name)}</td><td>${escHtml(c.value?.slice(0, 100))}${c.value?.length > 100 ? '…' : ''}</td></tr>`
        ).join('')}</table>`);
  content.appendChild(cookieSection);
}

// ─── Tabs ─────────────────────────────────────────────────────────────────

async function loadTabs() {
  const container = document.getElementById('tabs-list');
  container.innerHTML = `<div style="padding:20px;color:var(--text-dim)">Loading...</div>`;

  const tabs = await api('/tabs');
  if (!tabs) {
    container.innerHTML = `<div class="empty-state"><div class="empty-icon">✗</div><p>Could not reach Chrome. Make sure it's running with --remote-debugging-port.</p></div>`;
    return;
  }
  if (tabs.length === 0) {
    container.innerHTML = `<div class="empty-state"><div class="empty-icon">⊞</div><p>No open tabs found.</p></div>`;
    return;
  }

  container.innerHTML = '';
  for (const tab of tabs) {
    const card = document.createElement('div');
    card.className = 'chrome-tab-card fade-in';
    card.innerHTML = `
      <img class="tab-favicon" src="${tab.faviconUrl || ''}" onerror="this.style.display='none'" />
      <div class="tab-info">
        <div class="tab-title">${escHtml(tab.title || 'Untitled')}</div>
        <div class="tab-url-small">${escHtml(tab.url)}</div>
      </div>
      <button class="btn btn-sm tab-attach-btn">Attach</button>
    `;
    card.querySelector('.tab-attach-btn').addEventListener('click', async (e) => {
      e.stopPropagation();
      const res = await api(`/tabs/${tab.id}/attach`, { method: 'POST' });
      if (res?.ok) {
        document.querySelectorAll('.chrome-tab-card').forEach(c => c.classList.remove('active-tab'));
        card.classList.add('active-tab');
        await refreshStatus();
      }
    });
    container.appendChild(card);
  }
}

// ─── SSE Stream ───────────────────────────────────────────────────────────

function connectSSE() {
  const sse = new EventSource('/events/stream');
  const sseEl = document.getElementById('sse-status');

  sse.onopen = () => {
    sseConnected = true;
    sseEl.textContent = '⬤ Live';
    sseEl.className = 'event-stat sse-status connected';
  };

  sse.onerror = () => {
    sseConnected = false;
    sseEl.textContent = '⬤ Disconnected';
    sseEl.className = 'event-stat sse-status disconnected';
  };

  sse.onmessage = (event) => {
    try {
      const { type, data } = JSON.parse(event.data);
      handleSSEEvent(type, data);
    } catch {}
  };

  return sse;
}

function handleSSEEvent(type, data) {
  if (type === 'network:request') {
    // Add to network table if on network tab
    networkEntries.push({ ...data, response: null, body: null });
    const badge = document.getElementById('badge-network');
    badge.textContent = networkEntries.length;
    document.getElementById('stat-requests').textContent = networkEntries.length;

    const tbody = document.getElementById('network-tbody');
    const empty = document.getElementById('network-empty');
    empty.style.display = 'none';
    const tr = renderNetworkRow({ ...data, response: null, body: null });
    tr.classList.add('fade-in');
    tbody.appendChild(tr);
  }

  if (type === 'network:response' || type === 'network:failed') {
    // Update existing row
    const existing = networkEntries.find(e => e.id === data.requestId);
    if (existing) {
      existing.response = data;
      const tr = document.querySelector(`tr[data-id="${data.requestId}"]`);
      if (tr) {
        const statusCell = tr.querySelector('td:first-child');
        const failed = type === 'network:failed';
        const status = data.status;
        if (statusCell) {
          statusCell.innerHTML = `<span class="status-pill ${failed ? 'status-failed' : statusClass(status)}">${failed ? 'ERR' : (status || '…')}</span>`;
        }
      }
    }

    // Update error count
    const errorCount = networkEntries.filter(e => e.response?.failed || (e.response?.status >= 400)).length;
    document.getElementById('stat-errors').textContent = errorCount;
    const errBadge = document.getElementById('badge-errors');
    if (errorCount > 0) {
      errBadge.textContent = errorCount;
      errBadge.classList.remove('hidden');
    }
  }

  if (type === 'console:entry' || type === 'console:exception') {
    consoleLogs.push(data);
    const output = document.getElementById('console-output');
    const empty = document.getElementById('console-empty');
    if (empty.style.display !== 'none') empty.style.display = 'none';

    // Only show if we're on console tab and level matches
    if (!consoleLevel || data.level === consoleLevel) {
      const filter = document.getElementById('console-filter').value.toLowerCase();
      if (!filter || (data.text || '').toLowerCase().includes(filter)) {
        const entry = renderConsoleEntry(data);
        entry.classList.add('fade-in');
        output.appendChild(entry);
        output.scrollTop = output.scrollHeight;
      }
    }
  }

  if (type === 'ws:frame') {
    document.getElementById('stat-ws').textContent =
      parseInt(document.getElementById('stat-ws').textContent || '0') + 1;
  }

  if (type === 'page:navigate') {
    const pageEl = document.getElementById('status-page');
    if (data.url) pageEl.textContent = `— ${data.url}`;
    document.getElementById('stat-page-info').textContent = data.url || '';
  }

  if (type === 'bridge:connected') {
    const dot = document.getElementById('status-dot');
    dot.className = 'status-indicator connected';
    document.getElementById('status-label').textContent = 'Connected';
    refreshStatus();
  }
  if (type === 'bridge:disconnected') {
    const dot = document.getElementById('status-dot');
    dot.className = 'status-indicator disconnected';
    document.getElementById('status-label').textContent = 'Disconnected';
  }
}

// ─── Tab switching ────────────────────────────────────────────────────────

function switchTab(tabName) {
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));

  document.getElementById(`tab-${tabName}`).classList.add('active');
  document.getElementById(`panel-${tabName}`).classList.add('active');
}

// ─── Init ─────────────────────────────────────────────────────────────────

function init() {
  // Tab buttons
  document.querySelectorAll('.tab-btn').forEach(btn => {
    btn.addEventListener('click', () => switchTab(btn.dataset.tab));
  });

  // Network controls
  document.getElementById('btn-network-refresh').addEventListener('click', loadNetwork);
  document.getElementById('network-filter').addEventListener('input', loadNetwork);
  document.getElementById('network-method').addEventListener('change', loadNetwork);
  document.getElementById('network-type').addEventListener('change', loadNetwork);

  // Drawer tabs
  document.querySelectorAll('.drawer-tab').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.drawer-tab').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      activeDetailTab = btn.dataset.dtab;
      const entry = networkEntries.find(e => e.id === activeNetworkRow?.dataset?.id);
      if (entry) renderDetailTab(entry, activeDetailTab);
    });
  });
  document.getElementById('detail-close').addEventListener('click', () => {
    document.getElementById('network-detail').classList.remove('open');
    if (activeNetworkRow) { activeNetworkRow.classList.remove('selected'); activeNetworkRow = null; }
  });

  // Console controls
  document.getElementById('btn-console-refresh').addEventListener('click', loadConsole);
  document.getElementById('console-filter').addEventListener('input', loadConsole);
  document.querySelectorAll('.level-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.level-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      consoleLevel = btn.dataset.level;
      loadConsole();
    });
  });

  // DOM controls
  document.getElementById('btn-dom-snapshot').addEventListener('click', loadDOMSnapshot);
  document.getElementById('btn-dom-query').addEventListener('click', queryDOM);
  document.getElementById('dom-selector').addEventListener('keydown', e => {
    if (e.key === 'Enter') queryDOM();
  });

  // Storage controls
  document.getElementById('btn-storage-refresh').addEventListener('click', loadStorage);

  // Tabs controls
  document.getElementById('btn-tabs-refresh').addEventListener('click', loadTabs);

  // Header buttons
  document.getElementById('btn-connect').addEventListener('click', async () => {
    await api('/connect', { method: 'POST' });
    setTimeout(refreshStatus, 500);
  });
  document.getElementById('btn-clear').addEventListener('click', async () => {
    if (!confirm('Clear all captured data?')) return;
    await api('/clear', { method: 'POST' });
    networkEntries = [];
    consoleLogs = [];
    document.getElementById('network-tbody').innerHTML = '';
    document.getElementById('network-empty').style.display = 'flex';
    document.getElementById('console-output').innerHTML = '';
    document.getElementById('badge-network').textContent = '0';
    document.getElementById('stat-requests').textContent = '0';
    document.getElementById('stat-errors').textContent = '0';
    document.getElementById('stat-ws').textContent = '0';
  });

  // Initial data load
  refreshStatus();
  loadNetwork();
  loadConsole();

  // SSE
  connectSSE();

  // Auto-refresh status every 5s
  setInterval(refreshStatus, 5000);
}

document.addEventListener('DOMContentLoaded', init);
