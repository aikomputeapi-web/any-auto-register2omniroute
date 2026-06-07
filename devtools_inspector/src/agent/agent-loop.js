#!/usr/bin/env node
/**
 * agent-loop.js — Interactive AI agent CLI
 *
 * Uses Claude with tool-use to answer questions about the current browser session.
 * The agent can see: network traffic, DOM, console logs, cookies, storage, and more.
 *
 * Usage:
 *   node src/agent/agent-loop.js
 *   node src/agent/agent-loop.js "What API calls did this page make?"
 */

import 'dotenv/config';
import readline from 'readline';
import Anthropic from '@anthropic-ai/sdk';
import { toolDefinitions, toolImplementations } from './agent-tools.js';

const client = new Anthropic({ apiKey: process.env.ANTHROPIC_API_KEY });
const MODEL = 'claude-opus-4-5';

const SYSTEM_PROMPT = `You are a browser debugging assistant with direct access to a Chrome DevTools bridge.
You can inspect everything happening in the user's browser in real-time:
- Network requests and responses (including API calls, XHR, Fetch, WebSocket frames)
- The full live DOM
- Console logs, errors, and warnings
- localStorage, sessionStorage, and cookies
- You can also execute JavaScript in the page

When the user asks a question:
1. Always start by calling get_status to confirm you're connected and see the current page
2. Use the appropriate tools to gather data before answering
3. Be specific and actionable in your answers — include URLs, status codes, error messages, etc.
4. If you see errors or issues, proactively mention them even if not asked

Current date: ${new Date().toISOString()}`;

const colors = {
  reset: '\x1b[0m',
  bright: '\x1b[1m',
  dim: '\x1b[2m',
  cyan: '\x1b[36m',
  green: '\x1b[32m',
  yellow: '\x1b[33m',
  red: '\x1b[31m',
  blue: '\x1b[34m',
  magenta: '\x1b[35m',
};
const c = (color, text) => `${colors[color]}${text}${colors.reset}`;

function printBanner() {
  console.log(`
${c('cyan', '╔════════════════════════════════════════════╗')}
${c('cyan', '║')}   ${c('bright', '🔍 DevTools AI Agent')}                    ${c('cyan', '║')}
${c('cyan', '║')}   ${c('dim', 'Connected to Chrome via CDP')}              ${c('cyan', '║')}
${c('cyan', '╚════════════════════════════════════════════╝')}
${c('dim', 'Type your question and press Enter. Type "exit" to quit.')}
${c('dim', 'Examples:')}
${c('dim', '  • What API calls did this page make?')}
${c('dim', '  • Are there any console errors?')}
${c('dim', '  • What is in localStorage?')}
${c('dim', '  • Find all buttons on the page')}
${c('dim', '  • Is there an auth token in the cookies?')}
`);
}

async function runToolCall(toolName, toolInput) {
  const impl = toolImplementations[toolName];
  if (!impl) throw new Error(`Unknown tool: ${toolName}`);
  return await impl(toolInput);
}

async function chat(messages) {
  let response = await client.messages.create({
    model: MODEL,
    max_tokens: 4096,
    system: SYSTEM_PROMPT,
    tools: toolDefinitions,
    messages,
  });

  const allMessages = [...messages];

  // Agentic loop — keep calling tools until the model stops
  while (response.stop_reason === 'tool_use') {
    const toolUseBlocks = response.content.filter(b => b.type === 'tool_use');

    // Print tool calls
    for (const block of toolUseBlocks) {
      const inputStr = Object.keys(block.input || {}).length
        ? ` ${c('dim', JSON.stringify(block.input))}`
        : '';
      console.log(`  ${c('yellow', '⚙')} ${c('yellow', block.name)}${inputStr}`);
    }

    // Execute all tool calls
    const toolResults = await Promise.all(
      toolUseBlocks.map(async block => {
        try {
          const result = await runToolCall(block.name, block.input);
          return {
            type: 'tool_result',
            tool_use_id: block.id,
            content: JSON.stringify(result, null, 2),
          };
        } catch (err) {
          return {
            type: 'tool_result',
            tool_use_id: block.id,
            is_error: true,
            content: err.message,
          };
        }
      })
    );

    allMessages.push({ role: 'assistant', content: response.content });
    allMessages.push({ role: 'user', content: toolResults });

    response = await client.messages.create({
      model: MODEL,
      max_tokens: 4096,
      system: SYSTEM_PROMPT,
      tools: toolDefinitions,
      messages: allMessages,
    });
  }

  const textContent = response.content
    .filter(b => b.type === 'text')
    .map(b => b.text)
    .join('\n');

  return textContent;
}

async function checkBridgeReachable() {
  const port = process.env.API_PORT || 3000;
  try {
    const res = await fetch(`http://localhost:${port}/status`);
    const data = await res.json();
    return data;
  } catch {
    return null;
  }
}

async function main() {
  printBanner();

  // Check bridge is running
  const status = await checkBridgeReachable();
  if (!status) {
    console.error(c('red', `✗ Cannot reach the DevTools bridge on port ${process.env.API_PORT || 3000}.`));
    console.error(c('dim', '  Make sure to run "npm start" first, then run "npm run agent" in a separate terminal.'));
    process.exit(1);
  }

  if (status.connected) {
    console.log(c('green', `✓ Connected to: ${status.page?.url || 'unknown page'}`));
  } else {
    console.log(c('yellow', '⚠ Bridge is running but not connected to Chrome yet.'));
    console.log(c('dim', '  Open the dashboard at http://localhost:3000 and click Connect.'));
  }
  console.log();

  // One-shot mode: question passed as CLI argument
  const cliQuestion = process.argv.slice(2).join(' ');
  if (cliQuestion) {
    console.log(c('bright', `You: `) + cliQuestion);
    console.log();
    try {
      const answer = await chat([{ role: 'user', content: cliQuestion }]);
      console.log(c('cyan', 'Agent: ') + answer);
    } catch (err) {
      console.error(c('red', 'Error: ') + err.message);
    }
    return;
  }

  // Interactive REPL mode
  const rl = readline.createInterface({ input: process.stdin, output: process.stdout });
  const conversationHistory = [];

  const askQuestion = () => {
    rl.question(`${c('bright', 'You: ')}`, async (input) => {
      const question = input.trim();

      if (!question) { askQuestion(); return; }
      if (question.toLowerCase() === 'exit' || question.toLowerCase() === 'quit') {
        console.log(c('dim', 'Goodbye!'));
        rl.close();
        return;
      }
      if (question.toLowerCase() === 'clear') {
        conversationHistory.length = 0;
        console.log(c('dim', 'Conversation history cleared.'));
        askQuestion();
        return;
      }

      conversationHistory.push({ role: 'user', content: question });
      console.log();

      try {
        const answer = await chat(conversationHistory);
        conversationHistory.push({ role: 'assistant', content: answer });

        console.log(c('cyan', 'Agent: ') + answer);
        console.log();
      } catch (err) {
        console.error(c('red', 'Error: ') + err.message);
        console.log();
      }

      askQuestion();
    });
  };

  askQuestion();
}

main().catch(err => {
  console.error('Fatal error:', err);
  process.exit(1);
});
