/**
 * buffer.js — Ring buffer for CDP events
 * Stores the last N events per category in memory.
 */

const DEFAULT_MAX = parseInt(process.env.BUFFER_SIZE || '500', 10);

class RingBuffer {
  constructor(max = DEFAULT_MAX) {
    this.max = max;
    this.items = [];
  }
  push(item) {
    this.items.push(item);
    if (this.items.length > this.max) this.items.shift();
  }
  all() { return [...this.items]; }
  last(n) { return this.items.slice(-n); }
  clear() { this.items = []; }
  get size() { return this.items.length; }
}

export const networkRequests = new RingBuffer();  // { id, url, method, headers, postData, timestamp, resourceType }
export const networkResponses = new Map();         // requestId → response metadata
export const networkBodies = new Map();            // requestId → response body string
export const consoleLogs = new RingBuffer();       // { level, text, timestamp, source, url, line }
export const pageEvents = new RingBuffer();        // { type, url, timestamp }
export const webSocketFrames = new RingBuffer();   // { requestId, direction, payload, timestamp }

export function clearAll() {
  networkRequests.clear();
  networkResponses.clear();
  networkBodies.clear();
  consoleLogs.clear();
  pageEvents.clear();
  webSocketFrames.clear();
}

/** Build a rich network entry combining request + response + body */
export function buildNetworkEntry(requestId) {
  const req = networkRequests.all().find(r => r.id === requestId);
  if (!req) return null;
  const res = networkResponses.get(requestId);
  const body = networkBodies.get(requestId);
  return { ...req, response: res || null, body: body || null };
}

/** Get all network entries with optional filters */
export function getNetworkEntries({ url, method, status, resourceType, limit } = {}) {
  let entries = networkRequests.all().map(req => ({
    ...req,
    response: networkResponses.get(req.id) || null,
    body: networkBodies.get(req.id) || null,
  }));

  if (url) entries = entries.filter(e => e.url.includes(url));
  if (method) entries = entries.filter(e => e.method?.toLowerCase() === method.toLowerCase());
  if (resourceType) entries = entries.filter(e => e.resourceType?.toLowerCase() === resourceType.toLowerCase());
  if (status) {
    const s = parseInt(status, 10);
    entries = entries.filter(e => e.response?.status === s);
  }
  if (limit) entries = entries.slice(-parseInt(limit, 10));

  return entries;
}
