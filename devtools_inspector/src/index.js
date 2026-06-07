#!/usr/bin/env node
/**
 * index.js — Main entry point
 * Starts the CDP bridge + API server and attempts to auto-connect to Chrome.
 */

import 'dotenv/config';
import { createServer } from './api/server.js';
import { connectToTab, listTabs } from './bridge/cdp-client.js';

const API_PORT = parseInt(process.env.API_PORT || '3000', 10);

const colors = {
  reset: '\x1b[0m', bright: '\x1b[1m', dim: '\x1b[2m',
  cyan: '\x1b[36m', green: '\x1b[32m', yellow: '\x1b[33m', red: '\x1b[31m',
};
const c = (color, text) => `${colors[color]}${text}${colors.reset}`;

function printBanner() {
  console.log(`
${c('cyan', '╔══════════════════════════════════════════════╗')}
${c('cyan', '║')}   ${c('bright', '🔍 DevTools Inspector Bridge')} v1.0          ${c('cyan', '║')}
${c('cyan', '╚══════════════════════════════════════════════╝')}
`);
}

async function tryConnect(retries = 5, delay = 1500) {
  for (let i = 0; i < retries; i++) {
    try {
      await connectToTab();
      return true;
    } catch (err) {
      if (i < retries - 1) {
        process.stdout.write(`\r${c('yellow', `⏳ Waiting for Chrome... (attempt ${i + 1}/${retries})`)}   `);
        await new Promise(r => setTimeout(r, delay));
      }
    }
  }
  return false;
}

async function main() {
  printBanner();

  // Start API server
  const app = createServer();
  await new Promise(resolve => app.listen(API_PORT, resolve));

  console.log(c('green', `✓ API server running at http://localhost:${API_PORT}`));
  console.log(c('green', `✓ Dashboard at          http://localhost:${API_PORT}/`));
  console.log(c('green', `✓ SSE stream at         http://localhost:${API_PORT}/events/stream`));
  console.log();

  // Try to auto-connect to Chrome
  console.log(c('dim', `Attempting to connect to Chrome on port ${process.env.CHROME_PORT || 9222}...`));
  const connected = await tryConnect();

  if (connected) {
    try {
      const tabs = await listTabs();
      const tab = tabs[0];
      if (tab) {
        console.log(`\n${c('green', '✓ Connected!')} Tab: ${c('bright', tab.title || tab.url)}`);
      } else {
        console.log(`\n${c('green', '✓ Connected!')} (no tabs open yet)`);
      }
    } catch {}
  } else {
    console.log(`\n${c('yellow', '⚠ Chrome not detected.')}`);
    console.log(c('dim', '  Launch Chrome with remote debugging:'));
    console.log(c('dim', '    npm run launch-chrome'));
    console.log(c('dim', '  Or manually:'));
    console.log(c('dim', `    chrome.exe --remote-debugging-port=${process.env.CHROME_PORT || 9222} --user-data-dir=./chrome-profile`));
    console.log(c('dim', '  Then visit the dashboard to connect: http://localhost:' + API_PORT));
  }

  console.log();
  console.log(c('dim', 'Press Ctrl+C to stop.'));
  console.log();

  // Keep process alive
  process.on('SIGINT', () => {
    console.log(c('dim', '\nShutting down...'));
    process.exit(0);
  });
}

main().catch(err => {
  console.error('Fatal error:', err);
  process.exit(1);
});
