/**
 * cdp-client.js — Chrome DevTools Protocol client
 * Connects to Chrome's remote debugging WebSocket and subscribes to all
 * relevant domains: Network, DOM, Console, Log, Page, Runtime, WebSockets.
 */

import CDP from 'chrome-remote-interface';
import {
  networkRequests, networkResponses, networkBodies,
  consoleLogs, pageEvents, webSocketFrames
} from './buffer.js';

const MAX_BODY = parseInt(process.env.MAX_BODY_SIZE || '1048576', 10);
const CAPTURABLE_TYPES = new Set(['application/json', 'text/', 'application/xml', 'application/javascript']);

let client = null;
let currentTarget = null;
const sseClients = new Set(); // SSE response objects
const executionContexts = new Map();

export function getSseClients() { return sseClients; }
export function getClient() { return client; }
export function getCurrentTarget() { return currentTarget; }
export function getExecutionContexts() { return Array.from(executionContexts.values()); }

/** Broadcast an event to all SSE listeners */
function broadcast(type, data) {
  const payload = `data: ${JSON.stringify({ type, data, ts: Date.now() })}\n\n`;
  for (const res of sseClients) {
    try { res.write(payload); } catch { sseClients.delete(res); }
  }
}

function isCapturable(mimeType = '') {
  for (const t of CAPTURABLE_TYPES) {
    if (mimeType.startsWith(t)) return true;
  }
  return false;
}

export async function listTabs(host = process.env.CHROME_HOST || 'localhost', port = process.env.CHROME_PORT || 9222) {
  try {
    const targets = await CDP.List({ host, port });
    return targets.filter(t => t.type === 'page');
  } catch (err) {
    throw new Error(`Cannot reach Chrome on ${host}:${port}. Is it running with --remote-debugging-port=${port}? (${err.message})`);
  }
}

export async function connectToTab(tabId = null) {
  if (client) {
    try { await client.close(); } catch {}
    client = null;
  }

  const host = process.env.CHROME_HOST || 'localhost';
  const port = parseInt(process.env.CHROME_PORT || '9222', 10);

  const opts = { host, port };
  if (tabId) opts.target = tabId;

  console.log(`[CDP] Connecting to Chrome at ${host}:${port}${tabId ? ` (tab: ${tabId})` : ' (default tab)'}...`);

  client = await CDP(opts);
  currentTarget = tabId;

  const { Network, DOM, Console, Log, Page, Runtime } = client;

  // Track execution contexts (register listeners BEFORE enable to avoid missing initial events)
  executionContexts.clear();
  Runtime.executionContextCreated(({ context }) => {
    executionContexts.set(context.id, context);
  });
  Runtime.executionContextDestroyed(({ executionContextId }) => {
    executionContexts.delete(executionContextId);
  });
  Runtime.executionContextsCleared(() => {
    executionContexts.clear();
  });

  // Enable all domains
  await Promise.all([
    Network.enable({ maxPostDataSize: 65536 }),
    DOM.enable(),
    Page.enable(),
    Log.enable(),
    Runtime.enable(),
  ]).catch(err => console.warn('[CDP] Some domains failed to enable:', err.message));

  // ─── Network Events ───────────────────────────────────────────────────────

  Network.requestWillBeSent(({ requestId, request, type, timestamp, redirectResponse }) => {
    const entry = {
      id: requestId,
      url: request.url,
      method: request.method,
      headers: request.headers,
      postData: request.postData || null,
      resourceType: type,
      timestamp: timestamp * 1000,
      wallTime: Date.now(),
      redirectFrom: redirectResponse ? { url: redirectResponse.url, status: redirectResponse.status } : null,
    };
    networkRequests.push(entry);
    broadcast('network:request', entry);
  });

  Network.responseReceived(({ requestId, response, type, timestamp }) => {
    const entry = {
      requestId,
      url: response.url,
      status: response.status,
      statusText: response.statusText,
      headers: response.headers,
      mimeType: response.mimeType,
      remoteIPAddress: response.remoteIPAddress,
      timing: response.timing,
      fromCache: response.fromDiskCache || response.fromServiceWorker || false,
      timestamp: timestamp * 1000,
    };
    networkResponses.set(requestId, entry);
    broadcast('network:response', entry);

    // Attempt to fetch body for capturable types
    if (isCapturable(response.mimeType)) {
      Network.getResponseBody({ requestId })
        .then(({ body, base64Encoded }) => {
          if (!base64Encoded && body.length <= MAX_BODY) {
            networkBodies.set(requestId, body);
            broadcast('network:body', { requestId, size: body.length });
          }
        })
        .catch(() => {}); // body not available yet — will retry on loadingFinished
    }
  });

  Network.loadingFinished(({ requestId, encodedDataLength }) => {
    const res = networkResponses.get(requestId);
    if (res && isCapturable(res.mimeType) && !networkBodies.has(requestId)) {
      Network.getResponseBody({ requestId })
        .then(({ body, base64Encoded }) => {
          if (!base64Encoded && body.length <= MAX_BODY) {
            networkBodies.set(requestId, body);
          }
        })
        .catch(() => {});
    }
    broadcast('network:done', { requestId, encodedDataLength });
  });

  Network.loadingFailed(({ requestId, errorText, canceled, blockedReason }) => {
    const res = networkResponses.get(requestId) || {};
    networkResponses.set(requestId, { ...res, failed: true, errorText, canceled, blockedReason });
    broadcast('network:failed', { requestId, errorText, canceled, blockedReason });
  });

  Network.webSocketCreated(({ requestId, url }) => {
    broadcast('ws:created', { requestId, url });
  });
  Network.webSocketFrameSent(({ requestId, timestamp, response }) => {
    const frame = { requestId, direction: 'sent', payload: response.payloadData, timestamp: timestamp * 1000 };
    webSocketFrames.push(frame);
    broadcast('ws:frame', frame);
  });
  Network.webSocketFrameReceived(({ requestId, timestamp, response }) => {
    const frame = { requestId, direction: 'received', payload: response.payloadData, timestamp: timestamp * 1000 };
    webSocketFrames.push(frame);
    broadcast('ws:frame', frame);
  });

  // ─── Console / Log Events ─────────────────────────────────────────────────

  Log.entryAdded(({ entry }) => {
    const log = {
      level: entry.level,
      text: entry.text,
      source: entry.source,
      url: entry.url,
      line: entry.lineNumber,
      timestamp: entry.timestamp,
      networkRequestId: entry.networkRequestId,
      stackTrace: entry.stackTrace,
    };
    consoleLogs.push(log);
    broadcast('console:entry', log);
  });

  Runtime.consoleAPICalled(({ type, args, stackTrace, timestamp }) => {
    const text = args.map(a => a.value ?? a.description ?? JSON.stringify(a)).join(' ');
    const log = { level: type, text, stackTrace, timestamp, source: 'javascript' };
    consoleLogs.push(log);
    broadcast('console:entry', log);
  });

  Runtime.exceptionThrown(({ timestamp, exceptionDetails }) => {
    const log = {
      level: 'error',
      text: exceptionDetails.text || exceptionDetails.exception?.description || 'Unknown exception',
      url: exceptionDetails.url,
      line: exceptionDetails.lineNumber,
      col: exceptionDetails.columnNumber,
      stackTrace: exceptionDetails.stackTrace,
      timestamp,
      source: 'javascript',
    };
    consoleLogs.push(log);
    broadcast('console:exception', log);
  });

  // ─── Page Events ──────────────────────────────────────────────────────────

  Page.frameNavigated(({ frame }) => {
    if (!frame.parentId) { // main frame only
      const ev = { type: 'navigate', url: frame.url, title: frame.name, timestamp: Date.now() };
      pageEvents.push(ev);
      broadcast('page:navigate', ev);
    }
  });

  Page.loadEventFired(({ timestamp }) => {
    const ev = { type: 'load', timestamp: timestamp * 1000 };
    pageEvents.push(ev);
    broadcast('page:load', ev);
  });

  Page.domContentEventFired(({ timestamp }) => {
    const ev = { type: 'domContentLoaded', timestamp: timestamp * 1000 };
    pageEvents.push(ev);
    broadcast('page:domContentLoaded', ev);
  });

  client.on('disconnect', () => {
    console.warn('[CDP] Disconnected from Chrome.');
    client = null;
    broadcast('bridge:disconnected', {});
  });

  console.log('[CDP] Connected and listening.');
  broadcast('bridge:connected', { host, port, tabId });

  return client;
}

/** Take a full DOM snapshot — returns outer HTML of the document */
export async function getDOMSnapshot() {
  if (!client) throw new Error('Not connected to Chrome');
  const { Runtime } = client;
  const result = await Runtime.evaluate({
    expression: 'document.documentElement.outerHTML',
    returnByValue: true,
  });
  return result.result.value;
}

/** Run querySelector and return matching elements as plain objects */
export async function queryDOM(selector) {
  if (!client) throw new Error('Not connected to Chrome');
  const { Runtime } = client;
  const result = await Runtime.evaluate({
    expression: `
      (function() {
        const nodes = Array.from(document.querySelectorAll(${JSON.stringify(selector)}));
        return nodes.map(n => ({
          tag: n.tagName,
          id: n.id,
          className: n.className,
          textContent: n.textContent?.trim().slice(0, 500),
          innerHTML: n.innerHTML?.slice(0, 2000),
          attributes: Object.fromEntries(Array.from(n.attributes).map(a => [a.name, a.value])),
          rect: n.getBoundingClientRect ? JSON.parse(JSON.stringify(n.getBoundingClientRect())) : null,
        }));
      })()
    `,
    returnByValue: true,
    awaitPromise: false,
  });
  if (result.exceptionDetails) throw new Error(result.exceptionDetails.text);
  return result.result.value;
}

/** Evaluate arbitrary JS in the page context */
export async function evaluateJS(expression, { awaitPromise = false, contextId = undefined } = {}) {
  if (!client) throw new Error('Not connected to Chrome');
  const { Runtime } = client;
  const options = {
    expression,
    returnByValue: true,
    awaitPromise,
    generatePreview: true,
  };
  if (contextId !== undefined && contextId !== null) {
    options.contextId = contextId;
  }
  const result = await Runtime.evaluate(options);
  if (result.exceptionDetails) {
    throw new Error(result.exceptionDetails.text + '\n' + (result.exceptionDetails.exception?.description || ''));
  }
  return result.result.value ?? result.result.description;
}

/** Get page metadata: URL, title, cookies */
export async function getPageInfo() {
  if (!client) throw new Error('Not connected to Chrome');
  const { Target, Network, Runtime } = client;
  const [titleResult, urlResult, cookieResult] = await Promise.all([
    Runtime.evaluate({ expression: 'document.title', returnByValue: true }),
    Runtime.evaluate({ expression: 'location.href', returnByValue: true }),
    Network.getCookies().catch(() => ({ cookies: [] })),
  ]);
  return {
    title: titleResult.result.value,
    url: urlResult.result.value,
    cookies: cookieResult.cookies,
  };
}

/** Dump localStorage and sessionStorage */
export async function getStorage() {
  if (!client) throw new Error('Not connected to Chrome');
  const { Runtime } = client;
  const result = await Runtime.evaluate({
    expression: `
      (function() {
        function dump(store) {
          const out = {};
          for (let i = 0; i < store.length; i++) {
            const k = store.key(i);
            out[k] = store.getItem(k);
          }
          return out;
        }
        return { localStorage: dump(localStorage), sessionStorage: dump(sessionStorage) };
      })()
    `,
    returnByValue: true,
  });
  return result.result.value;
}
