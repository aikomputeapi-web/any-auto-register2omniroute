# 🔍 Using DevTools Inspector with Any-Auto-Register

This guide explains how to use the **DevTools Inspector** bridge side-by-side with **Any-Auto-Register** to inspect, monitor, and debug web automation and registration tasks in real-time.

---

## 🏗️ Architecture & Flow

When a registration task runs (e.g., ChatGPT, Grok, Trae), the system often launches a browser instance via Playwright to solve Cloudflare Turnstile, execute Sentinel SDK logic, or automate form completion.

By exposing a Remote Debugging Port on the Playwright browser, the **DevTools Inspector** bridge connects to it over the Chrome DevTools Protocol (CDP), capturing:
- **Network Traffic**: Requests, headers, request/response bodies, and response times.
- **Console Logs**: JavaScript log/warn/error entries, uncaught exceptions.
- **DOM State**: Live HTML content and DOM query selections.
- **State**: Cookies, localStorage, and sessionStorage.

```
                  any-auto-register (FastAPI Backend)
                                │
                                ▼ launches (headed/headless)
           Playwright Browser (with --remote-debugging-port=9222)
                                │
                                │ CDP WebSocket
                                ▼
                       devtools-inspector (Node.js Bridge)
                                │
          ┌─────────────────────┴─────────────────────┐
          ▼                                           ▼
   REST API / SSE Streams                      Interactive Dashboard
   (http://localhost:3000)                    (http://localhost:3000)
          │
          ▼
   AI Agents / Debuggers
```

---

## 🚀 Quick Start Guide

### 1. Enable Remote Debugging in Any-Auto-Register
The Playwright actuator has been configured to automatically launch with the remote debugging port active. 

In [core/executors/playwright.py](file:///c:/Users/Administrator/coding/any-auto-register/core/executors/playwright.py), the `launch_opts` contains:
```python
launch_opts = {
    "headless": headless,
    "args": [
        # ... other stealth args
        "--remote-debugging-port=9222"
    ]
}
```

> [!NOTE]
> Make sure no other process (like a standalone Chrome instance) is occupying port `9222` when the registration task starts, otherwise the Playwright launch will fail.

### 2. Start the DevTools Inspector Bridge
Open a terminal in the `devtools-inspector` directory and run:

```bash
# Install dependencies if not done already
npm install

# Start the bridge server
npm start
```

This starts the bridge on port `3000` (Dashboard: http://localhost:3000). The bridge will wait for a browser on port `9222` to become available and connect automatically when it starts.

### 3. Run a Registration Task
Start the `any-auto-register` backend:
```bash
# In the any-auto-register directory
.venv\Scripts\python main.py
```

Then trigger a headed or headless task. For example, using the live test script:
```bash
.venv\Scripts\python tests/test_live_chatgpt_catchmail.py
```

---

## 🛠️ Debugging Registration Tasks

Once the registration task launches Chrome, the DevTools Inspector console will log `[CDP] Connected and listening`. You can now use the following options to debug the session:

### A. The Web Dashboard
Open **`http://localhost:3000`** in your browser. The dashboard displays:
- **Network Panel**: Filterable log of HTTP requests and responses. Click on any row to view full headers and response payloads.
- **Console Panel**: Live feed of console messages and script exceptions from ChatGPT/OpenAI's page.
- **DOM Inspector**: View/inspect the page source in real-time.

### B. REST API (For AI Agents or scripts)
You can query the bridge server dynamically to examine the state of the registration flow:

- **Check Current Page/Cookies**:
  ```bash
  curl http://localhost:3000/page
  curl http://localhost:3000/cookies
  ```
- **List All Network Requests**:
  ```bash
  curl http://localhost:3000/network
  ```
- **Find Failed Requests**:
  ```bash
  curl http://localhost:3000/network/failed
  ```
- **Query the Live DOM**:
  ```bash
  curl http://localhost:3000/dom/query?selector=button.submit
  ```
- **Execute JS expression inside the browser context**:
  ```bash
  curl -X POST -H "Content-Type: application/json" -d '{"expression": "document.title"}' http://localhost:3000/eval
  ```

---

## ⚠️ Troubleshooting

1. **"Failed to launch browser: port 9222 in use"**
   - **Reason**: A standalone Chrome instance or another test task is already occupying port 9222.
   - **Solution**: Kill any lingering Chrome processes or shut down the debug browser before restarting the registration task.

2. **"DevTools not connecting/No tabs found"**
   - **Reason**: The registration task is running in pure protocol mode and has not launched a browser.
   - **Solution**: Set the task parameters to use `headed` or `headless` browser executor instead of `protocol`. The bridge will hook in as soon as the Playwright browser is created.
