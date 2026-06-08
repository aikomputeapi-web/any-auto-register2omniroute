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
  getCurrentTarget, getSseClients, getExecutionContexts
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
      await connectToTab(req.body?.tabId || null);
      res.json({ ok: true });
    } catch (err) {
      res.status(503).json({ error: err.message });
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

  // ─── Buffer Control ───────────────────────────────────────────────────────

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
