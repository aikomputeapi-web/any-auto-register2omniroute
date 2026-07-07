/**
 * server.js — Express API server
 * Exposes all CDP-captured data over HTTP for AI agents and tooling.
 */

import express from 'express';
import cors from 'cors';
import {
  networkRequests, networkResponses, networkBodies,
  consoleLogs, pageEvents, webSocketFrames,
  getNetworkEntries, buildNetworkEntry, clearAll
} from '../bridge/buffer.js';
import {
  connectToTab, listTabs, getDOMSnapshot, queryDOM,
  evaluateJS, getPageInfo, getStorage, getClient,
  getCurrentTarget, getSseClients, getExecutionContexts,
  navigatePage, clearBrowserCookies
} from '../bridge/cdp-client.js';

export function createServer() {
  const app = express();
  app.use(cors());
  app.use(express.json());
  app.use(express.static('public'));

  // ─── Health / Status ───────────────────────────────────────────────────────

  app.get('/status', async (req, res) => {
    const connected = !!getClient();
    let pageInfo = null;
    if (connected) {
      try { pageInfo = await getPageInfo(); } catch {}
    }
    res.json({
      connected,
      currentTarget: getCurrentTarget(),
      page: pageInfo,
      buffer: {
        networkRequests: networkRequests.size,
        consoleLogs: consoleLogs.size,
        pageEvents: pageEvents.size,
        webSocketFrames: webSocketFrames.size,
      },
      sseClients: getSseClients().size,
    });
  });

  // ─── Tab Management ────────────────────────────────────────────────────────

  app.get('/tabs', async (req, res) => {
    try {
      const tabs = await listTabs();
      res.json(tabs);
    } catch (err) {
      res.status(503).json({ error: err.message });
    }
  });

  app.post('/tabs/:id/attach', async (req, res) => {
    try {
      await connectToTab(req.params.id);
      res.json({ ok: true, tabId: req.params.id });
    } catch (err) {
      res.status(500).json({ error: err.message });
    }
  });

  app.post('/connect', async (req, res) => {
    try {
      await connectToTab(req.body?.tabId || null, req.body?.port || null);
      res.json({ ok: true });
    } catch (err) {
      res.status(503).json({ error: err.message });
    }
  });

  // ─── Navigation ────────────────────────────────────────────────────────────

  app.post('/navigate', async (req, res) => {
    if (!getClient()) return res.status(503).json({ error: 'Not connected to Chrome' });
    const { url } = req.body;
    if (!url) return res.status(400).json({ error: 'Missing url in body' });
    try {
      const result = await navigatePage(url);
      res.json({ ok: true, result });
    } catch (err) {
      res.status(500).json({ error: err.message });
    }
  });

  // ─── Network ───────────────────────────────────────────────────────────────

  app.get('/network', (req, res) => {
    const { url, method, status, resourceType, limit } = req.query;
    const entries = getNetworkEntries({ url, method, status, resourceType, limit });
    res.json({
      count: entries.length,
      entries,
    });
  });

  app.get('/network/failed', (req, res) => {
    const entries = getNetworkEntries().filter(e => e.response?.failed);
    res.json({ count: entries.length, entries });
  });

  app.get('/network/ws', (req, res) => {
    res.json({ count: webSocketFrames.size, frames: webSocketFrames.all() });
  });

  app.get('/network/:id', (req, res) => {
    const entry = buildNetworkEntry(req.params.id);
    if (!entry) return res.status(404).json({ error: 'Request not found' });
    res.json(entry);
  });

  // ─── Console ───────────────────────────────────────────────────────────────

  app.get('/console', (req, res) => {
    let logs = consoleLogs.all();
    if (req.query.level) logs = logs.filter(l => l.level === req.query.level);
    if (req.query.limit) logs = logs.slice(-parseInt(req.query.limit, 10));
    res.json({ count: logs.length, logs });
  });

  // ─── DOM ───────────────────────────────────────────────────────────────────

  app.get('/dom', async (req, res) => {
    if (!getClient()) return res.status(503).json({ error: 'Not connected to Chrome' });
    try {
      const html = await getDOMSnapshot();
      if (req.query.format === 'json') {
        res.json({ html, length: html.length });
      } else {
        res.type('text/html').send(html);
      }
    } catch (err) {
      res.status(500).json({ error: err.message });
    }
  });

  app.get('/dom/query', async (req, res) => {
    if (!getClient()) return res.status(503).json({ error: 'Not connected to Chrome' });
    const selector = req.query.selector || req.query.q;
    if (!selector) return res.status(400).json({ error: 'Missing ?selector= parameter' });
    try {
      const nodes = await queryDOM(selector);
      res.json({ selector, count: nodes?.length ?? 0, nodes });
    } catch (err) {
      res.status(500).json({ error: err.message });
    }
  });

  // ─── Page ─────────────────────────────────────────────────────────────────

  app.get('/page', async (req, res) => {
    if (!getClient()) return res.status(503).json({ error: 'Not connected to Chrome' });
    try {
      const info = await getPageInfo();
      const events = pageEvents.all();
      res.json({ ...info, events });
    } catch (err) {
      res.status(500).json({ error: err.message });
    }
  });

  // ─── JavaScript Evaluation ────────────────────────────────────────────────

  app.post('/eval', async (req, res) => {
    if (!getClient()) return res.status(503).json({ error: 'Not connected to Chrome' });
    const { expression, awaitPromise, contextId } = req.body;
    if (!expression) return res.status(400).json({ error: 'Missing expression in body' });
    try {
      const value = await evaluateJS(expression, { awaitPromise, contextId });
      res.json({ result: value });
    } catch (err) {
      res.status(500).json({ error: err.message });
    }
  });

  app.get('/contexts', async (req, res) => {
    if (!getClient()) return res.status(503).json({ error: 'Not connected to Chrome' });
    try {
      res.json(getExecutionContexts());
    } catch (err) {
      res.status(500).json({ error: err.message });
    }
  });

  // ─── Storage ──────────────────────────────────────────────────────────────

  app.get('/storage', async (req, res) => {
    if (!getClient()) return res.status(503).json({ error: 'Not connected to Chrome' });
    try {
      const storage = await getStorage();
      res.json(storage);
    } catch (err) {
      res.status(500).json({ error: err.message });
    }
  });

  app.get('/cookies', async (req, res) => {
    if (!getClient()) return res.status(503).json({ error: 'Not connected to Chrome' });
    try {
      const info = await getPageInfo();
      res.json({ count: info.cookies.length, cookies: info.cookies });
    } catch (err) {
      res.status(500).json({ error: err.message });
    }
  });

  // ─── NVIDIA API Key Extraction ─────────────────────────────────────────────

  app.get('/nvidia/extract-key', async (req, res) => {
    // Auto-connect to the NVIDIA tab if needed
    const port = 9223; // default port for nvidia
    try {
      const tabs = await listTabs(process.env.CHROME_HOST || 'localhost', port);
      const nvidiaTab = tabs.find(t => t.url && (t.url.includes('nvidia') || t.url.includes('build.nvidia.com')));
      if (nvidiaTab) {
        if (!getClient() || nvidiaTab.id !== getCurrentTarget()) {
          console.log(`[DevTools] Connecting to NVIDIA tab: ${nvidiaTab.url}`);
          await connectToTab(nvidiaTab.id, port);
        }
      } else {
        const activeTab = tabs.find(t => t.url && !t.url.startsWith('chrome:'));
        if (activeTab && (!getClient() || activeTab.id !== getCurrentTarget())) {
          console.log(`[DevTools] Connecting to active tab: ${activeTab.url}`);
          await connectToTab(activeTab.id, port);
        }
      }
    } catch (err) {
      console.warn('[DevTools] Failed to ensure connection to NVIDIA tab:', err.message);
    }

    // 1. Search in network responses
    try {
      for (const body of networkBodies.values()) {
        const match = body.match(/(nvapi-[a-zA-Z0-9_-]{30,})/);
        if (match) {
          return res.json({ ok: true, key: match[1], source: 'network' });
        }
      }
    } catch (err) {
      console.warn('[DevTools] Network body extraction failed:', err.message);
    }

    // 2. Search in console logs
    try {
      for (const log of consoleLogs.all()) {
        const match = log.text?.match(/(nvapi-[a-zA-Z0-9_-]{30,})/);
        if (match) {
          return res.json({ ok: true, key: match[1], source: 'console' });
        }
      }
    } catch (err) {
      console.warn('[DevTools] Console log extraction failed:', err.message);
    }

    // 3. Search in DOM / Evaluate JS in browser context
    if (getClient()) {
      try {
        const expr = `(() => {
          const selectors = ['[data-testid="api-key"]', 'code', 'pre', '.api-key', '[class*="api-key"]', 'input[readonly]'];
          for (const sel of selectors) {
            const els = document.querySelectorAll(sel);
            for (const el of els) {
              const text = (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA') ? el.value.trim() : el.textContent.trim();
              if (text.startsWith('nvapi-')) return text;
            }
          }
          for (const el of document.querySelectorAll('input, textarea')) {
            const val = el.value.trim();
            if (val.startsWith('nvapi-')) return val;
          }
          const match = document.documentElement.outerHTML.match(/(nvapi-[a-zA-Z0-9_-]{30,})/);
          if (match) return match[1];
          return null;
        })()`;
        const key = await evaluateJS(expr);
        if (key) {
          return res.json({ ok: true, key, source: 'dom' });
        }
      } catch (err) {
        console.warn('[DevTools] DOM extraction failed:', err.message);
      }
    }

    res.status(404).json({ ok: false, error: 'NVIDIA API key not found' });
  });

  // ─── Buffer Control ───────────────────────────────────────────────────────

  app.post('/clear-cookies', async (req, res) => {
    if (!getClient()) return res.status(503).json({ error: 'Not connected to Chrome' });
    try {
      await clearBrowserCookies();
      res.json({ ok: true });
    } catch (err) {
      res.status(500).json({ error: err.message });
    }
  });

  app.post('/clear', (req, res) => {
    clearAll();
    res.json({ ok: true, message: 'Buffer cleared' });
  });

  // ─── SSE Event Stream ─────────────────────────────────────────────────────

  app.get('/events/stream', (req, res) => {
    res.setHeader('Content-Type', 'text/event-stream');
    res.setHeader('Cache-Control', 'no-cache');
    res.setHeader('Connection', 'keep-alive');
    res.setHeader('Access-Control-Allow-Origin', '*');
    res.flushHeaders();

    // Send a heartbeat comment every 15s to keep connection alive
    const heartbeat = setInterval(() => res.write(': heartbeat\n\n'), 15000);

    getSseClients().add(res);
    res.write(`data: ${JSON.stringify({ type: 'stream:connected', ts: Date.now() })}\n\n`);

    req.on('close', () => {
      clearInterval(heartbeat);
      getSseClients().delete(res);
    });
  });

  return app;
}
