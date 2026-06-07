#!/usr/bin/env node
/**
 * launch-chrome.js — Helper to launch Chrome with remote debugging enabled
 *
 * Usage:
 *   node src/launch-chrome.js              # isolated profile
 *   node src/launch-chrome.js --real       # your real Chrome profile
 *   node src/launch-chrome.js --url https://example.com
 */

import { execSync, spawn } from 'child_process';
import { existsSync, mkdirSync } from 'fs';
import { resolve } from 'path';
import { fileURLToPath } from 'url';
import { dirname } from 'path';
import 'dotenv/config';

const __dirname = dirname(fileURLToPath(import.meta.url));
const PORT = process.env.CHROME_PORT || 9222;
const args = process.argv.slice(2);
const useRealProfile = args.includes('--real');
const urlArg = args.find(a => a.startsWith('--url='))?.split('=')[1]
  || (args.includes('--url') ? args[args.indexOf('--url') + 1] : null);

const colors = {
  reset: '\x1b[0m', bright: '\x1b[1m', dim: '\x1b[2m',
  cyan: '\x1b[36m', green: '\x1b[32m', yellow: '\x1b[33m', red: '\x1b[31m',
};
const c = (color, text) => `${colors[color]}${text}${colors.reset}`;

function findChrome() {
  if (process.env.CHROME_PATH && existsSync(process.env.CHROME_PATH)) {
    return process.env.CHROME_PATH;
  }

  const candidates = [
    'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
    'C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe',
    `${process.env.LOCALAPPDATA}\\Google\\Chrome\\Application\\chrome.exe`,
    // Edge (also supports CDP)
    'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
    'C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe',
    // macOS
    '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    '/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge',
    // Linux
    '/usr/bin/google-chrome',
    '/usr/bin/chromium-browser',
    '/usr/bin/chromium',
  ];

  for (const p of candidates) {
    if (p && existsSync(p)) return p;
  }

  // Try which/where
  try {
    const found = execSync('where chrome 2>nul', { encoding: 'utf8' }).trim().split('\n')[0];
    if (found && existsSync(found)) return found;
  } catch {}
  try {
    const found = execSync('which google-chrome 2>/dev/null || which chromium-browser 2>/dev/null', { encoding: 'utf8' }).trim();
    if (found && existsSync(found)) return found;
  } catch {}

  return null;
}

function main() {
  const chromePath = findChrome();
  if (!chromePath) {
    console.error(c('red', '✗ Could not find Chrome or Edge.'));
    console.error(c('dim', '  Set CHROME_PATH in .env or install Google Chrome.'));
    process.exit(1);
  }

  console.log(c('dim', `Found browser: ${chromePath}`));

  const chromeArgs = [
    `--remote-debugging-port=${PORT}`,
    '--no-first-run',
    '--no-default-browser-check',
    '--disable-background-networking',
    '--disable-client-side-phishing-detection',
    '--disable-sync',
  ];

  if (!useRealProfile) {
    const profileDir = resolve(__dirname, '../..', 'chrome-profile');
    mkdirSync(profileDir, { recursive: true });
    chromeArgs.push(`--user-data-dir=${profileDir}`);
    console.log(c('dim', `Using isolated profile: ${profileDir}`));
  } else {
    console.log(c('yellow', '⚠ Using your real Chrome profile. DevTools bridge will have access to your cookies/sessions.'));
  }

  if (urlArg) {
    chromeArgs.push(urlArg);
  }

  console.log(c('green', `✓ Launching Chrome with --remote-debugging-port=${PORT}...`));
  console.log(c('dim', `  Args: ${chromeArgs.slice(1).join(' ')}`));
  console.log();
  console.log(c('cyan', `  DevTools available at: http://localhost:${PORT}`));
  console.log(c('cyan', `  Bridge API at:          http://localhost:${process.env.API_PORT || 3000}`));
  console.log();

  const proc = spawn(chromePath, chromeArgs, {
    detached: false,
    stdio: 'ignore',
  });

  proc.on('error', err => {
    console.error(c('red', `✗ Failed to launch Chrome: ${err.message}`));
    process.exit(1);
  });

  proc.on('exit', code => {
    console.log(c('dim', `Chrome exited with code ${code}`));
  });

  // Keep the process alive so Chrome stays open
  process.on('SIGINT', () => {
    console.log(c('dim', '\nClosing Chrome...'));
    proc.kill();
    process.exit(0);
  });
}

main();
