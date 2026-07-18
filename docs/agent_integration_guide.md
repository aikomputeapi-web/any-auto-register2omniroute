# Developer Guide: Integrating New Platforms in any-auto-register

Welcome, future AI agent! This guide outlines the architecture of the `any-auto-register` system and details the design, structure, and step-by-step process for creating and integrating a new registration and key extraction script.

---

## 1. System Architecture Overview

`any-auto-register` is an automated account registration and API key extraction framework. It supports:
- Multi-mailbox providers (disposable services, custom catchalls, worker-based subdomains).
- CAPTCHA-solving integrations (CapSolver, YesCaptcha, Local Solvers).
- Stealth browser execution (Playwright, Puppeteer, connection over remote CDP to a real Chrome instance to bypass Cloudflare Turnstile, Clerk, and reCAPTCHA Enterprise).
- FastAPI backend routes to schedule, manage, and log registration tasks.

### Core Directory Layout

- **`core/`**: The backbone of the project containing base classes, databases, and general utilities.
  - [base_platform.py](file:///c:/Users/Administrator/coding/any-auto-register/core/base_platform.py): The abstract base class `BasePlatform` and `Account` models.
  - [base_mailbox.py](file:///c:/Users/Administrator/coding/any-auto-register/core/base_mailbox.py): The mailbox pool base class `BaseMailbox` and the factory `create_mailbox`.
  - [registry.py](file:///c:/Users/Administrator/coding/any-auto-register/core/registry.py): Automatic scanning and dynamic loading of platform plugins.
  - [config_store.py](file:///c:/Users/Administrator/coding/any-auto-register/core/config_store.py): Global key-value configurations persistent in SQLite/environment.
  - [db.py](file:///c:/Users/Administrator/coding/any-auto-register/core/db.py): Database storage schema for created accounts.
  - [proxy_utils.py](file:///c:/Users/Administrator/coding/any-auto-register/core/proxy_utils.py) & [browser_runtime.py](file:///c:/Users/Administrator/coding/any-auto-register/core/browser_runtime.py): Helpers for browser profiles, geolocation, and proxies.
- **`platforms/`**: Platform-specific subdirectories containing registration plugins (e.g., `cerebras`, `mistral`, `openrouter`, and our newly created `baseten`).
- **`api/`**: FastAPI endpoints managing accounts, config, and backend registration tasks.
- **`scratch/`**: Location for one-off debug scripts, test suites, and inspection routines.

---

## 2. Design Patterns for Platform Plugins

Every platform inside `platforms/<name>/` must follow a strict three-file layout:

### A. `__init__.py`
Exports the registered platform subclass.
```python
from platforms.<name>.plugin import <Name>Platform
__all__ = ["<Name>Platform"]
```

### B. `plugin.py`
Extends `BasePlatform` and is decorated with `@register`. It acts as the bridge connecting the email provider's OTP polling callback with the Playwright browser registration runner.
```python
from typing import Optional
from core.base_platform import BasePlatform, Account, AccountStatus, RegisterConfig
from core.base_mailbox import BaseMailbox
from core.registry import register

@register
class NamePlatform(BasePlatform):
    name = "name"
    display_name = "Name Display"
    version = "1.0.0"
    supported_executors = ["headless", "headed"]

    def __init__(self, config: Optional[RegisterConfig] = None, mailbox: Optional[BaseMailbox] = None):
        super().__init__(config or RegisterConfig())
        self.mailbox = mailbox

    def register(self, email: str, password: Optional[str] = None) -> Account:
        from platforms.name.core import NameRegister
        
        # Configure register engine
        log_fn = getattr(self, "_log_fn", print)
        requested_headless = (self.config.executor_type or "headless") != "headed"
        reg = NameRegister(proxy=self.config.proxy, headless=requested_headless)
        reg.log = lambda msg: log_fn(f"[Name] {msg}")

        # Setup OTP verification callback
        otp_timeout = self.get_mailbox_otp_timeout()
        if self.mailbox:
            mailbox = self.mailbox
            mail_acct = mailbox.get_email()
            if not mail_acct:
                raise RuntimeError("No available email account")
            email = email or mail_acct.email
            before_ids = mailbox.get_current_ids(mail_acct)

            def otp_cb():
                return mailbox.wait_for_code(
                    mail_acct,
                    keyword="",
                    timeout=otp_timeout,
                    before_ids=before_ids,
                    code_pattern=r"\b\d{6}\b" # Adjust pattern per platform
                )
        else:
            otp_cb = None

        ok, info = reg.register(email=email, password=password, otp_callback=otp_cb)
        if not ok:
            raise RuntimeError(f"Registration failed: {info.get('error')}")

        return Account(
            platform="name",
            email=info["email"],
            password=info.get("password", ""),
            status=AccountStatus.REGISTERED,
            token=info.get("api_key", ""),
            extra={"api_key": info.get("api_key", "")}
        )

    def check_valid(self, account: Account) -> bool:
        return bool(account.extra.get("api_key") or account.token)
```

### C. `core.py`
Encapsulates the actual Playwright-based browser automation.
- **Stealth Evasion**: Standard chromium instances are easily blocked by modern anti-bot services (Clerk, Turnstile, reCAPTCHA Enterprise). Therefore, the register module should launch a real Chrome binary on a random debugging port and connect via CDP:
  ```python
  self.browser = self.pw.chromium.connect_over_cdp(cdp_endpoint)
  ```
- **Form-Filling Flow**: Emulate human typings, handle cookie banners, and use fallback selectors.
- **Email verification**: Wait for OTP input boxes to render, trigger the callback to wait for and extract the code from the mailbox, and fill them in.
- **Onboarding loops**: Handle post-signup profile surveys, terms acceptance, or team setup before proceeding to the dashboard.
- **API Key Creation/Extraction**: Navigate to settings, click the generate buttons, handle naming modals, and extract the generated token.

---

## 3. Key Lessons Learned (Baseten Case Study)

1. **Email Provider Restrictions**: 
   Many modern platforms block registration from common disposable email domains like `@catchmail.io` or `@mail.tm`.
   - *Fix*: Load the global configuration using `config_store.get_all()` and look for custom domain setups (such as `imap_catchall` using a private catchall domain like `audioplexdesigns.com`).

2. **Name Constraint Validations**:
   Watch out for field validators in API key naming modals. For example, Baseten enforces:
   `Use a unique name with lowercase letters, numbers, and hyphens only.`
   Entering `Auto-Key` failed validation, leaving the submit button disabled and stalling the automation.
   - *Fix*: Always use lowercase and hyphens (e.g., `auto-key` or `key-random`) for API key names.

3. **Dialog Selectors Overlapping**:
   Clicking `button:has-text("Create API key")` inside a modal naming form might end up matching the background page button instead if they have identical text.
   - *Fix*: Scope selectors to the modal overlay first, like `'dialog button:has-text("Create API key")'` or `'[role="dialog"] button:has-text("Create API key")'`.

4. **Network and DOM Extraction Fallbacks**:
   Sometimes, API keys are shown once and never again, or are masked on the screen immediately.
   - *Fix*: Hook network responses before clicking create:
     ```python
     captured_keys = []
     def _on_resp(response):
         # scan response.text() for key patterns
     page.on("response", _on_resp)
     ```
     Combine this with a fallback scanner that checks visible inputs, readonly text fields, and clipboard/code tags.

---

## 4. step-by-step Integration Checklist

When writing a new script:

- `[ ]` **Research Flow**: Inspect the target sign-up and settings pages. Determine if it requires email+password or is passwordless (OTP-only).
- `[ ]` **Implement Plugin**: Create `__init__.py`, `plugin.py`, and `core.py` under a new folder in `platforms/`.
- `[ ]` **Stealth Launch**: Adopt the `_launch_real_chrome()` pattern from `platforms/baseten/core.py` to launch debugging Chrome and bypass bot blockades.
- `[ ]` **Test Registry**: Check if the plugin loads correctly:
  ```powershell
  python -c "from core.registry import load_all, list_platforms; load_all(); print(list_platforms())"
  ```
- `[ ]` **Write E2E Test**: Add a test script under `scratch/` that instantiates the configured global mailbox (`create_mailbox(provider, extra)`) and invokes registration in headed mode (`headless=False`) for easier debugging.
- `[ ]` **Compilation & Run**: Ensure all files compile (`python -m py_compile <file>`) and run successfully.
