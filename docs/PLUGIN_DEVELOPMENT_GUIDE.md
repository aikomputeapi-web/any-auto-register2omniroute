# Plugin Development Guide (Any Auto Register)

How to add a new registration platform. Designed for humans and AI agents: minimal required surface, auto-discovery, no manual wiring.

---

## Fast path (recommended)

```bash
# From repo root
python scripts/new_platform.py my_platform --display-name "My Platform"
# Edit platforms/my_platform/core.py (registration steps)
# Restart backend
python main.py
# Confirm discovery
curl -s "http://localhost:8000/api/platforms?type=all" | findstr my_platform
```

That creates:

```
platforms/my_platform/
  __init__.py      # empty package marker
  plugin.py        # REQUIRED — @register class discovered at startup
  core.py          # optional — put automation here (HTTP / Playwright / etc.)
```

**You do not** edit `main.py`, the registry list, or the frontend to make a platform appear.  
`core/registry.py` loads every `platforms/<name>/plugin.py` automatically.

---

## What the system requires

| Requirement | Detail |
|---|---|
| Directory | `platforms/<name>/` — lowercase `a-z`, digits, underscores; starts with a letter |
| Package file | `__init__.py` (can be empty) |
| Plugin file | `plugin.py` with a class decorated `@register` |
| Base class | extends `BasePlatform` |
| Identity | `name` **must equal** the directory name (registry key + import path) |
| Methods | `register(email, password=None) -> Account` and `check_valid(account) -> bool` |
| On failure | raise `RuntimeError` (or another exception); do not return a half-filled success |

Everything else (`core.py`, custom API routes, platform actions, frontend polish) is optional.

---

## Architecture

```
Startup (main.py lifespan)
  └─ load_all()                 # core/registry.py
       └─ import platforms.<name>.plugin for each subdir
            └─ @register puts cls into _registry[cls.name]

Task (POST /api/tasks/register)
  └─ get(platform)              # hot-reloads core/plugin when already imported
  └─ create mailbox from config/extra (mail_provider)
  └─ PlatformCls(config=RegisterConfig(...), mailbox=mailbox)
  └─ platform._log_fn = task logger
  └─ platform.bind_task_control(...)
  └─ platform.register(email, password)
  └─ save Account to DB + optional integrations upload
```

### Runtime injects (do not invent your own task plumbing)

| Attribute | Source | Use |
|---|---|---|
| `self.config` | `RegisterConfig` | `executor_type`, `captcha_solver`, `proxy`, `extra` |
| `self.mailbox` | `create_mailbox(...)` | email + OTP |
| `self._log_fn` | task runner | prefer `self.log(...)` |
| task control | `bind_task_control` | skip/stop while waiting on mail |

---

## Minimal plugin (copy-paste)

Use helpers on `BasePlatform` — they remove most mailbox/OTP/account boilerplate.

```python
"""Example platform plugin"""
from typing import Optional

from core.base_platform import BasePlatform, Account, AccountStatus, RegisterConfig
from core.base_mailbox import BaseMailbox
from core.registry import register


@register
class ExamplePlatform(BasePlatform):
    name = "example"                    # MUST match directory platforms/example/
    display_name = "Example"
    version = "1.0.0"
    supported_executors = ["headless", "headed"]  # unsupported values are auto-downgraded

    def __init__(
        self,
        config: Optional[RegisterConfig] = None,
        mailbox: Optional[BaseMailbox] = None,
    ):
        super().__init__(config or RegisterConfig())
        self.mailbox = mailbox

    def register(self, email: str, password: str = None) -> Account:
        from platforms.example.core import ExampleRegister

        password = password or self.generate_password()
        email, otp_cb = self.prepare_mailbox_otp(
            email,
            code_pattern=r"(\d{6})",
            require_mailbox=True,
        )

        reg = ExampleRegister(proxy=self.config.proxy, headless=self.wants_headless)
        reg.log = self.log

        ok, info = reg.register(email=email, password=password, otp_callback=otp_cb)
        if not ok:
            raise RuntimeError(f"Registration failed: {info.get('error')}")

        return self.make_account(
            email=info.get("email") or email,
            password=info.get("password") or password,
            token=info.get("token") or info.get("api_key") or "",
            status=AccountStatus.REGISTERED,
            extra={"api_key": info.get("api_key", "")},
        )

    def check_valid(self, account: Account) -> bool:
        return bool(account.token or (account.extra or {}).get("api_key"))
```

### Helpers (use these)

| Helper | Purpose |
|---|---|
| `self.log(msg)` | Task logs with `[Display Name]` prefix |
| `self.wants_headless` | `True` unless `executor_type == "headed"` |
| `self.generate_password(n=16)` | Random password |
| `self.prepare_mailbox_otp(email, ...)` | Resolve mailbox email + OTP callback |
| `self.make_account(...)` | Build `Account` with `platform=self.name` |
| `self.get_mailbox_otp_timeout()` | OTP wait seconds from config `extra` |
| `self._make_executor()` | `protocol` / Playwright executor (`with` supported) — call from **plugin.py** |
| `self._make_captcha()` | Solver from config — call from **plugin.py** |

`prepare_mailbox_otp` returns `(resolved_email, otp_callback | None)`.  
If `require_mailbox=True` and no mailbox/account is available, it raises `RuntimeError`.

---

## Optional `core.py`

Keep automation out of the plugin class. **Not required** by the loader (many plugins only have `plugin.py`).

```python
"""Core registration logic"""
from typing import Callable, Optional, Tuple


class ExampleRegister:
    def __init__(self, proxy: Optional[str] = None, headless: bool = True):
        self.proxy = proxy
        self.headless = headless
        self.log: Callable[[str], None] = print

    def register(
        self,
        email: str,
        password: Optional[str] = None,
        otp_callback: Optional[Callable[[], Optional[str]]] = None,
    ) -> Tuple[bool, dict]:
        self.log(f"Starting registration for {email}")
        # 1. Navigate / API call
        # 2. Fill form
        # 3. Captcha if needed
        # 4. if otp_callback: code = otp_callback()
        # 5. Extract token / api_key
        return True, {
            "email": email,
            "password": password,
            "token": "",
            "api_key": "",
        }
```

### Which executor?

| Mode | When | How |
|---|---|---|
| `protocol` | Pure HTTP/API | `with self._make_executor() as ex:` in plugin, pass `ex` into core |
| `headless` | Browser needed, no window | Playwright (built-in executor or your own `sync_playwright`) |
| `headed` | Debug / anti-headless | Same as headless with visible browser |

Declare only what you support in `supported_executors`. Requested modes outside that list are **automatically downgraded** (prefer `protocol`, else first listed).

**Do not** call `_make_executor` / `_make_captcha` from a plain core class unless you pass the platform instance in — those methods live on `BasePlatform`.

### Captcha

`self.config.captcha_solver` values:

| Value | Class |
|---|---|
| `yescaptcha` | `YesCaptcha` |
| `capsolver` | `CapSolver` |
| `manual` | `ManualCaptcha` |
| `local_solver` | `LocalSolverCaptcha` (local Turnstile solver) |

Keys resolve from `kwargs` → `config.extra` → `config_store` (`yescaptcha_key` / `capsolver_key`).

### Proxy

- Format: `protocol://user:pass@host:port` (or host:port variants accepted by proxy utils)
- Plugin: `self.config.proxy`
- Playwright helpers: `core.proxy_utils.build_playwright_proxy_config`

### Account status

```python
from core.base_platform import AccountStatus

AccountStatus.REGISTERED
AccountStatus.TRIAL
AccountStatus.SUBSCRIBED
AccountStatus.EXPIRED
AccountStatus.INVALID
```

Store platform-specific data in `Account.extra` (api keys, cookies, cashier URLs, provider metadata).

### Platform actions (optional)

```python
def get_platform_actions(self):
    return [
        {"id": "refresh_token", "label": "Refresh Token", "params": []},
    ]

def execute_action(self, action_id, account, params):
    if action_id == "refresh_token":
        return {"ok": True, "data": {"token": "..."}}
    return {"ok": False, "error": f"Unknown action: {action_id}"}
```

---

## Scaffold CLI

```bash
python scripts/new_platform.py my_platform
python scripts/new_platform.py my_platform --display-name "My Platform"
python scripts/new_platform.py my_platform --executors protocol
python scripts/new_platform.py my_platform --executors headless,headed
python scripts/new_platform.py my_platform --no-core      # plugin.py only
python scripts/new_platform.py my_platform --force        # overwrite scaffold files
```

---

## Verify

### 1. Start backend

```bash
python main.py
```

Startup log should include your platform name under `Platform loaded: [...]`.

### 2. List platforms

```http
GET http://localhost:8000/api/platforms?type=all
```

| `type` | Result |
|---|---|
| `ai` (default) | Main AI UI list (hides `cursor`, `tavily`, and pro platforms) |
| `pro` | `amex`, `jfcu`, `usbank`, `rrcu`, `stripe` |
| `all` | Every registered plugin — **use this when developing** |

Auth: if `auth_password_hash` is configured, send `Authorization: Bearer <token>` for `/api/*`.

### 3. Register task

```http
POST http://localhost:8000/api/tasks/register
Content-Type: application/json

{
  "platform": "my_platform",
  "email": null,
  "password": null,
  "count": 1,
  "concurrency": 1,
  "executor_type": "headless",
  "captcha_solver": "yescaptcha",
  "proxy": null,
  "extra": {
    "mail_provider": "luckmail"
  }
}
```

Notes:

- `email` is optional; the mailbox usually supplies it (`prepare_mailbox_otp`).
- Mail settings often come from global config; `extra` overrides per task.
- Default mailbox provider when unset: `luckmail` (see `api/tasks.py`).
- Other useful request fields: `register_delay_seconds`, richer `extra` keys for your flow.

Response: `{"task_id": "..."}`. Watch task logs in the UI or task stream endpoints.

---

## Optional extras

### Custom API routes

Add `api/<name>.py` with an `APIRouter`, then `app.include_router(..., prefix="/api")` in `main.py`. Only needed for OAuth callbacks, special status probes, etc.

### Frontend

Main UI is **React + Vite** (`frontend/`), not Vue. Most platforms need **no** frontend change — they appear from `GET /api/platforms`. Add custom controls only if the product UI must expose platform-specific fields (see ChatGPT helpers under `frontend/src/`).

### Tests

Add `tests/test_<name>.py` for pure logic (OTP parsing, HTTP client, account mapping). Prefer not to hit live signup endpoints in CI.

---

## Hard rules / pitfalls

1. **`name` ≠ directory** → import/`get()` breaks. Keep them identical.
2. **Missing `@register`** → never loaded.
3. **Missing `plugin.py`** → directory skipped (`ModuleNotFoundError` swallowed).
4. **Disabled names** → `trae` and `qwen` are hard-blocked in `core/registry.py`.
5. **Returning success without tokens** → account is saved but unusable; put keys in `token` and/or `extra`.
6. **Hardcoding mailbox polling** → use `prepare_mailbox_otp` / injected `self.mailbox` so skip/stop and timeouts work.
7. **Assuming `GET /api/platforms` shows everything** → use `?type=all` while developing.
8. **Calling `_make_executor` inside a detached core class** → pass executor/captcha in from the plugin.

---

## Study existing plugins

| Plugin | Why |
|---|---|
| `platforms/mistral/` | Clean Playwright plugin + core split |
| `platforms/tavily/` | Protocol executor + `_make_captcha` / `_make_executor` |
| `platforms/openrouter/` | Browser + captcha + OTP + email caveats |
| `platforms/chatgpt/` | Complex: modes, actions, uploads (advanced only) |
| `platforms/amex/` | Plugin-only (no `core.py`); wraps external register module |

---

## Checklist

- [ ] `python scripts/new_platform.py <name>` (or manual equivalent)
- [ ] `name` == directory name
- [ ] `@register` on a `BasePlatform` subclass
- [ ] `register()` returns `Account` via `make_account` (or equivalent)
- [ ] Failures raise exceptions with clear messages
- [ ] `check_valid()` implemented
- [ ] OTP via `prepare_mailbox_otp` when email verification is needed
- [ ] Secrets/tokens in `token` / `Account.extra`
- [ ] `supported_executors` matches real capability
- [ ] Restart backend; appears in `GET /api/platforms?type=all`
- [ ] One successful `POST /api/tasks/register` smoke test
