---
description: Reusable process for creating and running headed registration scripts using the CDP bridge
---

# Reusable Registration Workflow (CDP Bridge)

This workflow outlines the step-by-step process to create, test, and execute headed account registration scripts (for banks, brokerages, etc.) using the project's DevTools Inspector CDP bridge.

---

## 1. Setup the Environment

To perform automated browser actions without being blocked by anti-bot systems, always use the headed Chrome session connected to the local CDP bridge server.

1. **Launch Remote-Debugging Chrome**:
   Navigate to the devtools-inspector directory and launch Chrome with remote debugging on port `9223`:
   ```bash
   cd devtools-inspector
   npm run launch-chrome -- --url <Target_Entry_Point_URL>
   ```

2. **Start the CDP Bridge Server**:
   Start the bridge API server (runs on port `3005` by default) to accept commands:
   ```bash
   cd devtools-inspector
   npm start
   ```

3. **Verify Bridge Connectivity**:
   Ensure your Python script can query `http://localhost:3005/status` and that `connected` is `true`.

---

## 2. Script Design & Core Functions

All registration scripts must be placed in the `pro_account_register/` directory and use standard CDP API calls:

- **Page Info (`/page`)**: Retrieve current tab URL and title.
- **JavaScript Evaluation (`/eval`)**: Execute JS in the page context.
- **Input Dumper**: Extract all visible elements (`input`, `select`, `button`, `a`, etc.) with their ID, name, value, and label text.

### Critical Safety Rules for Javascript Evals
> [!IMPORTANT]
> - **IIFE Scoping**: Never evaluate raw declarations (e.g. `const el = ...`) in the global context. Always wrap them in Immediately Invoked Function Expressions:
>   `(() => { const el = document.getElementById('id'); ... })()`
>   This prevents `SyntaxError: Identifier 'el' has already been declared` across loop iterations.
> - **Robust Try-Catch wrappers**: Wrap browser JS commands inside `try { ... } catch (e) { return 'ERROR: ' + e.message; }` to prevent browser exceptions from returning HTTP 500 errors to the CDP bridge.

---

## 3. Form-Filling State Loop

Implement a loop (typically 30 maximum states) that executes every 3 seconds:

1. **Check Entry Page**: If the URL does not contain onboarding steps, navigate to the target entry URL.
2. **Address Modals**: Check for and click Recommended Address validation overlays (e.g. USPS Recommended confirm button).
3. **Form Inputs Check**: Dump all visible inputs.
4. **Dynamic Values Match**: Iteratively fill values if selectors are present:
   - **Text inputs**: First/Last Name, Street Address, City, ZIP, SSN, DOB, Email, Phone.
   - **Dropdowns**: State selection, Employment Status (`Retired`), annual income and net worth options, marital status.
   - **Agreements**: Check terms/disclosure checkboxes by evaluating ID or text keywords (`agree`, `accept`, `terms`, `consent`, `disclosure`, `ack`).
5. **Credentials creation**: Detect User ID and Password inputs, fill them with generated values, and click Submit.
6. **Submit Actions**: If any fields were filled, click standard submit buttons (`Continue`, `Next`, `Confirm`, `Submit`, `Agree and submit`).

---

## 4. Custom UI Element Handlers

When encountering elements that do not map to standard inputs:

### A. Custom Multiselect / Listboxes
If a select field is styled as a custom dropdown wrapper (e.g. `ul` lists with option `li` tags):
1. Programmatically click the toggle button (`.multiselect-toggle`) to reveal the list.
2. Click the desired option element (e.g. `li` matching "Retirement savings" or ID `102`).
3. Proceed with standard submissions.

### B. Custom Selectors Matching
Avoid selecting elements case-sensitively or partially if multiple match. Match exact dropdown values first, and fall back to case-insensitive partial match only if exact fails.

---

## 5. Threshold Detection & Manual Intervention

Registration flows often require physical user interaction or security steps. Detect these thresholds and exit gracefully:

1. **SMS OTP / 2FA**: If the page requests a verification code.
2. **Knowledge Based Authentication (KBA)**: If the page asks personal security questions.
3. **Mobile ID Scans**: If the page displays a QR code (`/confirm-identity` scan).

On matching a threshold:
- Save details file with status `"Pending Mobile Verification"`, `"Pending OTP"`, etc.
- Print a clear message to the log.
- Break the loop and leave Chrome running so the user/agent can complete the step manually.

---

## 6. Output Verification & Logging

1. **Save Outcome details**: Always write intermediate and final account outputs (including generated usernames and passwords) to `pro_account_register/registration_results/` in the format `<platform>_details_line_<N>.txt`.
2. **Commit Code**: Run the compilation checker `python -m py_compile pro_account_register/<filename>.py` and commit changes.
