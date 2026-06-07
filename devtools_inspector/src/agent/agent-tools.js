/**
 * agent-tools.js — Tool definitions for AI agent integration
 *
 * Compatible with Anthropic Claude tool-use format.
 * These tools wrap the REST API so an LLM can query the DevTools bridge.
 */

const BASE_URL = `http://localhost:${process.env.API_PORT || 3000}`;

async function apiFetch(path, options = {}) {
  const res = await fetch(`${BASE_URL}${path}`, options);
  if (!res.ok) {
    const err = await res.json().catch(() => ({ error: res.statusText }));
    throw new Error(err.error || `HTTP ${res.status}`);
  }
  return res.json();
}

// ─── Tool Implementations ──────────────────────────────────────────────────

export const toolImplementations = {
  get_status: async () => {
    return await apiFetch('/status');
  },

  list_tabs: async () => {
    return await apiFetch('/tabs');
  },

  attach_tab: async ({ tab_id }) => {
    return await apiFetch(`/tabs/${tab_id}/attach`, { method: 'POST' });
  },

  get_network_requests: async ({ url_filter, method, status, resource_type, limit }) => {
    const params = new URLSearchParams();
    if (url_filter) params.set('url', url_filter);
    if (method) params.set('method', method);
    if (status) params.set('status', status);
    if (resource_type) params.set('resourceType', resource_type);
    if (limit) params.set('limit', limit);
    return await apiFetch(`/network?${params}`);
  },

  get_failed_requests: async () => {
    return await apiFetch('/network/failed');
  },

  get_request_detail: async ({ request_id }) => {
    return await apiFetch(`/network/${request_id}`);
  },

  get_console_logs: async ({ level, limit }) => {
    const params = new URLSearchParams();
    if (level) params.set('level', level);
    if (limit) params.set('limit', limit);
    return await apiFetch(`/console?${params}`);
  },

  get_dom: async () => {
    const res = await apiFetch('/dom?format=json');
    // Truncate to 20k chars for the LLM context window
    if (res.html && res.html.length > 20000) {
      return { html: res.html.slice(0, 20000) + '\n<!-- [truncated] -->', truncated: true, originalLength: res.length };
    }
    return res;
  },

  query_dom: async ({ selector }) => {
    return await apiFetch(`/dom/query?selector=${encodeURIComponent(selector)}`);
  },

  get_page_info: async () => {
    return await apiFetch('/page');
  },

  evaluate_js: async ({ expression }) => {
    return await apiFetch('/eval', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ expression }),
    });
  },

  get_storage: async () => {
    return await apiFetch('/storage');
  },

  get_cookies: async () => {
    return await apiFetch('/cookies');
  },

  clear_buffer: async () => {
    return await apiFetch('/clear', { method: 'POST' });
  },
};

// ─── Tool Definitions (Anthropic format) ──────────────────────────────────

export const toolDefinitions = [
  {
    name: 'get_status',
    description: 'Get the current status of the DevTools bridge: connection state, current page URL/title, buffer sizes.',
    input_schema: { type: 'object', properties: {}, required: [] },
  },
  {
    name: 'list_tabs',
    description: 'List all open Chrome tabs. Returns tab IDs, URLs, and titles.',
    input_schema: { type: 'object', properties: {}, required: [] },
  },
  {
    name: 'attach_tab',
    description: 'Switch the bridge to inspect a specific Chrome tab by its ID.',
    input_schema: {
      type: 'object',
      properties: {
        tab_id: { type: 'string', description: 'The tab ID from list_tabs' },
      },
      required: ['tab_id'],
    },
  },
  {
    name: 'get_network_requests',
    description: 'Get captured network requests. Can filter by URL substring, HTTP method, status code, or resource type (XHR, Fetch, Document, Script, Stylesheet, Image, Font, Media, WebSocket, Other). Returns request + response metadata and body when available.',
    input_schema: {
      type: 'object',
      properties: {
        url_filter: { type: 'string', description: 'Filter by URL substring' },
        method: { type: 'string', description: 'HTTP method filter: GET, POST, PUT, etc.' },
        status: { type: 'string', description: 'HTTP status code filter, e.g. "404" or "500"' },
        resource_type: { type: 'string', description: 'Resource type: XHR, Fetch, Document, Script, Stylesheet, Image, Font, Media, WebSocket' },
        limit: { type: 'number', description: 'Max number of requests to return (most recent)' },
      },
      required: [],
    },
  },
  {
    name: 'get_failed_requests',
    description: 'Get all network requests that failed (network errors, not 4xx/5xx — use get_network_requests with status filter for those).',
    input_schema: { type: 'object', properties: {}, required: [] },
  },
  {
    name: 'get_request_detail',
    description: 'Get full details of a single network request including request headers, response headers, and response body.',
    input_schema: {
      type: 'object',
      properties: {
        request_id: { type: 'string', description: 'Request ID from get_network_requests' },
      },
      required: ['request_id'],
    },
  },
  {
    name: 'get_console_logs',
    description: 'Get browser console output. Includes console.log, console.error, console.warn, uncaught exceptions, and browser-generated messages.',
    input_schema: {
      type: 'object',
      properties: {
        level: { type: 'string', description: 'Filter by level: log, info, warning, error, debug' },
        limit: { type: 'number', description: 'Max number of entries to return (most recent)' },
      },
      required: [],
    },
  },
  {
    name: 'get_dom',
    description: 'Get the full live DOM of the current page as an HTML string. Truncated to 20k characters if too large.',
    input_schema: { type: 'object', properties: {}, required: [] },
  },
  {
    name: 'query_dom',
    description: 'Query the live DOM with a CSS selector. Returns matching elements with tag, id, class, text content, attributes, and bounding box.',
    input_schema: {
      type: 'object',
      properties: {
        selector: { type: 'string', description: 'CSS selector, e.g. "button.submit", "#login-form", "[data-testid=price]"' },
      },
      required: ['selector'],
    },
  },
  {
    name: 'get_page_info',
    description: 'Get current page URL, title, cookies, and navigation history.',
    input_schema: { type: 'object', properties: {}, required: [] },
  },
  {
    name: 'evaluate_js',
    description: 'Execute arbitrary JavaScript in the current page context and return the result. Use for extracting data, checking state, or interacting with the page.',
    input_schema: {
      type: 'object',
      properties: {
        expression: { type: 'string', description: 'JavaScript expression to evaluate in the page' },
      },
      required: ['expression'],
    },
  },
  {
    name: 'get_storage',
    description: 'Get the contents of localStorage and sessionStorage for the current page.',
    input_schema: { type: 'object', properties: {}, required: [] },
  },
  {
    name: 'get_cookies',
    description: 'Get all cookies for the current page.',
    input_schema: { type: 'object', properties: {}, required: [] },
  },
  {
    name: 'clear_buffer',
    description: 'Clear all buffered network requests, console logs, and page events. Useful to start fresh when navigating to a new page.',
    input_schema: { type: 'object', properties: {}, required: [] },
  },
];
