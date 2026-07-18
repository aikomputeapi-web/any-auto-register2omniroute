"""
J3GB (VIP) Automatic registration with API key generation

Process:
  1. Navigate to vip.j3gb.com/register?aff=...
  2. Click "Continue with Universe Federation" (MiAuth SSO)
  3. On the MiAuth page (dc.hhhl.cc), click "Add account" → "Create account"
  4. Agree to server rules and important notes
  5. Fill the Misskey federation registration form (username, email, password)
     - Email must be @gmail.com or @qq.com
  6. Submit and verify email with OTP code
  7. Authorize the MiAuth request (click "Continue")
  8. Get redirected back to vip.j3gb.com (now logged in)
  9. Navigate to the API keys / token page and create an API key
"""

import os
import re
import json
import time
import random
import string
from typing import Optional, Tuple, Callable
from playwright.sync_api import sync_playwright, TimeoutError, Page
from core.browser_runtime import ensure_browser_display_available, resolve_browser_headless
from core.proxy_utils import build_playwright_proxy_config, resolve_us_profile

J3GB_BASE = "https://vip.j3gb.com"
J3GB_REGISTER = f"{J3GB_BASE}/register?aff=GEAFWK9ABJB9"
J3GB_LOGIN = f"{J3GB_BASE}/login"
# The token/API-key page on the VIP dashboard
J3GB_TOKEN_PAGE = f"{J3GB_BASE}/panel/tokens"

# Federation (Misskey) instance
FED_BASE = "https://dc.hhhl.cc"


def _rand_password(n=16):
    chars = string.ascii_letters + string.digits + "!@#$%"
    pw = (
        random.choice(string.ascii_uppercase)
        + random.choice(string.ascii_lowercase)
        + random.choice(string.digits)
        + random.choice("!@#$%")
        + "".join(random.choices(chars, k=n - 4))
    )
    lst = list(pw)
    random.shuffle(lst)
    return "".join(lst)


def _rand_username(n=10):
    """Generate a random lowercase username (Misskey usernames are lowercase alphanumeric + underscore)."""
    chars = string.ascii_lowercase + string.digits
    return "".join(random.choices(chars, k=n))


def _gmail_dot_trick(base_email: str) -> str:
    """Generate a unique gmail address using the dot trick.

    Gmail ignores dots in the local part, so u.s.e.r@gmail.com delivers to
    user@gmail.com.  We insert random dots into the local part to create a
    unique-looking address that still lands in the same inbox.

    Also appends a random + tag for extra uniqueness when the local part is
    too short for enough dot combinations.
    """
    if "@" not in base_email:
        raise ValueError(f"Invalid email: {base_email}")
    local, domain = base_email.rsplit("@", 1)
    local = local.replace(".", "")  # normalise

    if domain.lower() != "gmail.com":
        # Not a gmail address — fall back to plus addressing
        tag = "".join(random.choices(string.ascii_lowercase + string.digits, k=8))
        return f"{local}+{tag}@{domain}"

    # Insert random dots between characters (positions 1..len-1)
    if len(local) >= 3:
        positions = list(range(1, len(local)))
        num_dots = random.randint(1, max(1, len(positions) // 2))
        dot_positions = sorted(random.sample(positions, min(num_dots, len(positions))))
        result = []
        for i, ch in enumerate(local):
            result.append(ch)
            if i + 1 in dot_positions and i + 1 < len(local):
                result.append(".")
        dotted = "".join(result)
    else:
        dotted = local

    # Gmail ignores dots, so dots alone are sufficient for uniqueness.
    # Do NOT append a +tag — many sites reject plus-addressed emails.
    return f"{dotted}@{domain}"


class GmailDotTrickMailbox:
    """POP3 mailbox for gmail dot-trick addresses.

    Generates dotted gmail variants from a base gmail address and polls the
    gmail POP3 inbox (pop.gmail.com:995) for verification codes addressed
    to the generated variant.
    """

    POP_SERVER = "pop.gmail.com"
    POP_PORT = 995

    def __init__(
        self,
        base_email: str,
        app_password: str,
        proxy: str = None,
    ):
        self.base_email = base_email
        self.app_password = app_password
        self._proxy = proxy
        self._generated_email = None
        self._log_fn = None
        self._task_control = None
        self._task_attempt_token = None

    def _log(self, msg):
        if callable(self._log_fn):
            self._log_fn(msg)

    def _checkpoint(self):
        if self._task_control:
            self._task_control.checkpoint(
                attempt_id=self._task_attempt_token,
            )

    def get_email(self):
        email = _gmail_dot_trick(self.base_email)
        self._generated_email = email
        self._log(f"[Gmail Dot Trick] Generated: {email}")
        from core.base_mailbox import MailboxAccount
        return MailboxAccount(email=email, account_id=email, extra={"provider": "gmail_dot_trick"})

    def _open_pop(self):
        import poplib
        conn = poplib.POP3_SSL(self.POP_SERVER, self.POP_PORT, timeout=30)
        conn.user(self.base_email)
        conn.pass_(self.app_password)
        return conn

    def get_current_ids(self, account) -> set:
        conn = None
        try:
            conn = self._open_pop()
            count, _ = conn.stat()
            seen = set()
            # POP3 message numbers are 1-based; record the current count
            # so we only look at new messages in wait_for_code
            seen.add(f"count:{count}")
            return seen
        except Exception as exc:
            self._log(f"[Gmail Dot Trick] get_current_ids error: {exc}")
            return set()
        finally:
            try:
                if conn:
                    conn.quit()
            except Exception:
                pass

    def wait_for_code(
        self,
        account,
        keyword: str = "",
        timeout: int = 120,
        before_ids: set = None,
        code_pattern: str = None,
        **kwargs,
    ) -> str:
        import email as email_module
        from email.header import decode_header

        before_ids = before_ids or set()
        # Extract the baseline count from before_ids
        baseline_count = 0
        for item in before_ids:
            if isinstance(item, str) and item.startswith("count:"):
                try:
                    baseline_count = int(item.split(":", 1)[1])
                except (ValueError, IndexError):
                    pass

        target_email = account.email.lower()
        deadline = time.monotonic() + max(int(timeout), 1)

        while time.monotonic() < deadline:
            self._checkpoint()
            conn = None
            try:
                conn = self._open_pop()
                count, _size = conn.stat()
                self._log(f"[Gmail Dot Trick] POP3 inbox has {count} messages (baseline: {baseline_count})")

                # Check messages from newest to oldest, but only those after baseline
                start = max(baseline_count + 1, 1)
                for msg_num in range(count, start - 1, -1):
                    try:
                        resp, lines, _octets = conn.retr(msg_num)
                        raw = b"\r\n".join(lines)
                        msg = email_module.message_from_bytes(raw)

                        # Check if this email is addressed to our generated address
                        matched = False
                        for header_name in ("To", "Delivered-To", "X-Original-To", "Envelope-To"):
                            value = str(msg.get(header_name) or "").lower()
                            if target_email in value:
                                matched = True
                                break
                        if not matched:
                            continue

                        # Extract subject and body
                        subject_raw = msg.get("Subject", "")
                        parts = []
                        for part, charset in decode_header(str(subject_raw)):
                            if isinstance(part, bytes):
                                parts.append(part.decode(charset or "utf-8", errors="ignore"))
                            else:
                                parts.append(str(part))
                        subject = " ".join(parts).strip()

                        body_parts = []
                        def _walk(payload):
                            if payload.is_multipart():
                                for sub in payload.iter_parts():
                                    _walk(sub)
                            else:
                                ct = str(payload.get_content_type() or "")
                                if ct.startswith("text/"):
                                    b = payload.get_content()
                                    if isinstance(b, bytes):
                                        b = b.decode("utf-8", errors="ignore")
                                    body_parts.append(str(b or ""))
                        _walk(msg)
                        body = " ".join(body_parts)
                        body = re.sub(r"<[^>]+>", " ", body)
                        body = re.sub(r"\s+", " ", body).strip()

                        full_text = f"{subject} {body}"

                        if keyword and keyword.lower() not in full_text.lower():
                            continue

                        # Extract verification code
                        patterns = []
                        if code_pattern:
                            patterns.append(code_pattern)
                        patterns.extend([
                            r"(?is)(?:verification\s+code|one[-\s]*time\s+(?:password|code)|security\s+code|login\s+code|验证码|認証コード|code)[^0-9]{0,30}(\d{6})",
                            r"(?is)\bcode\b[^0-9]{0,12}(\d{6})",
                            r"(?<![a-zA-Z0-9])(\d{6})(?![a-zA-Z0-9])",
                        ])

                        for pat in patterns:
                            m = re.search(pat, full_text)
                            if m:
                                code = m.group(1) if m.groups() else m.group(0)
                                self._log(f"[Gmail Dot Trick] Extracted code: {code}")
                                return code

                    except Exception as exc:
                        self._log(f"[Gmail Dot Trick] error reading message {msg_num}: {exc}")

                try:
                    if conn:
                        conn.quit()
                except Exception:
                    pass
            except Exception as exc:
                self._log(f"[Gmail Dot Trick] polling error: {exc}")
            finally:
                try:
                    if conn:
                        conn.quit()
                except Exception:
                    pass

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            chunk = min(5.0, remaining)
            time.sleep(chunk)

        raise TimeoutError(f"Gmail dot trick: no verification code received within {timeout}s")


class J3gbRegister:
    def __init__(self, proxy: str = None, headless: bool = True, captcha_solver=None):
        self.proxy = proxy
        self.headless = headless
        self.captcha_solver = captcha_solver
        self.pw = None
        self.browser = None
        self.context = None

    def log(self, msg):
        print(f"[J3GB] {msg}")

    def _human_sleep(self, min_sec: float = 0.5, max_sec: float = 1.5):
        time.sleep(random.uniform(min_sec, max_sec))

    def _init_browser(self):
        import tempfile

        self.pw = sync_playwright().start()
        headless, reason = resolve_browser_headless(self.headless, default_headless=True)

        # Path to the extracted CapSolver extension (for Cloudflare Turnstile solving)
        ext_path = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "..", "capsolver-ext")
        )
        if not os.path.exists(ext_path):
            self.log(f"Warning: CapSolver extension not found at {ext_path}")
            ext_path = None

        if ext_path and headless:
            self.log("CapSolver extension requires headed mode — switching to headed")
            headless = False

        ensure_browser_display_available(headless)

        launch_args = [
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--window-position=0,0",
        ]
        if ext_path:
            launch_args += [
                f"--disable-extensions-except={ext_path}",
                f"--load-extension={ext_path}",
            ]

        us_loc = resolve_us_profile(self.proxy)

        context_opts = {
            "args": launch_args,
            "locale": us_loc["locale"],
            "timezone_id": us_loc["timezone"],
            "geolocation": {"latitude": us_loc["latitude"], "longitude": us_loc["longitude"]},
            "permissions": ["geolocation"],
            "viewport": {"width": 1280, "height": 800},
        }
        if self.proxy:
            proxy_cfg = build_playwright_proxy_config(self.proxy)
            if proxy_cfg:
                context_opts["proxy"] = proxy_cfg

        if ext_path:
            user_data_dir = tempfile.mkdtemp(prefix="j3gb_playwright_")
            self.context = self.pw.chromium.launch_persistent_context(
                user_data_dir, headless=False, **context_opts
            )
            self.browser = None
            self.extension_loaded = True
            self.log(f"Browser mode: headed Chromium with CapSolver extension ({reason})")
            self._configure_capsolver_extension()
        else:
            self.browser = self.pw.chromium.launch(headless=headless, args=launch_args)
            self.context = self.browser.new_context(**context_opts)
            self.extension_loaded = False
            self.log(f"Browser mode: {'headless' if headless else 'headed'} ({reason})")

    def _configure_capsolver_extension(self):
        """Inject correct config into CapSolver extension via the popup page."""
        from core.config_store import config_store
        api_key = config_store.get("capsolver_key", "")
        if not api_key:
            self.log("Warning: No capsolver_key configured, extension may not work")
            return

        # A plain Python dict is auto-serialised by Playwright when passed as
        # an argument to page.evaluate — it lands as a JS object, so we can
        # call chrome.storage.local.set({ config: cfg, defaultConfig: cfg })
        # directly without risky JSON.parse on a JS object literal.
        config = {
            "apiKey": api_key,
            "useCapsolver": True,
            "enabledForHCaptcha": True,
            "enabledForRecaptcha": True,
            "enabledForRecaptchaV3": True,
            "enabledForImageToText": True,
            "enabledForAwsCaptcha": True,
            "enabledForCloudflare": True,
            "hCaptchaMode": "click",
            "reCaptchaMode": "click",
            "manualSolving": False,
            "isInit": True,
            "showSolveButton": True,
            "hCaptchaRepeatTimes": 10,
            "hCaptchaDelayTime": 0,
        }

        try:
            page = self.context.new_page()
            page.goto("chrome://extensions/", wait_until="domcontentloaded", timeout=5000)
            time.sleep(1)
            ext_id = page.evaluate("""() => {
                const manager = document.querySelector('extensions-manager');
                if (!manager || !manager.shadowRoot) return null;
                const itemsList = manager.shadowRoot.querySelector('extensions-item-list');
                if (!itemsList || !itemsList.shadowRoot) return null;
                const items = itemsList.shadowRoot.querySelectorAll('extensions-item');
                for (const item of items) {
                    if (item.shadowRoot) {
                        const name = item.shadowRoot.querySelector('#name');
                        if (name && name.textContent.includes('Captcha Solver')) {
                            return item.id;
                        }
                    }
                }
                for (const item of items) {
                    return item.id;
                }
                return null;
            }""")
            page.close()

            if not ext_id:
                self.log("Warning: Could not locate CapSolver extension id")
                return

            ext_page = self.context.new_page()
            # CapSolver extension ships a popup at www/index.html#/popup
            # (popup.html does not exist in the bundle).
            ext_page.goto(
                f"chrome-extension://{ext_id}/www/index.html#/popup",
                wait_until="domcontentloaded",
                timeout=8000,
            )
            time.sleep(2)
            result = ext_page.evaluate("""(cfg) => {
                try {
                    chrome.storage.local.set({ config: cfg, defaultConfig: cfg });
                    return 'ok';
                } catch(e) {
                    return 'error: ' + e.message;
                }
            }""", config)
            ext_page.close()
            if result == "ok":
                self.log(f"CapSolver extension configured (key: {api_key[:6]}...)")
            else:
                self.log(f"Warning: CapSolver config write returned: {result}")
        except Exception as e:
            self.log(f"Warning: Could not configure CapSolver extension: {e}")

    def _close_browser(self):
        if self.context:
            try:
                self.context.close()
            except Exception:
                pass
        if self.browser:
            try:
                self.browser.close()
            except Exception:
                pass
        if self.pw:
            try:
                self.pw.stop()
            except Exception:
                pass

    def _type_human(self, page: Page, selector: str, text: str):
        self._human_sleep(0.3, 0.7)
        el = page.locator(selector).first
        el.click()
        el.fill("")
        for char in text:
            page.keyboard.type(char, delay=random.randint(50, 150))
        self._human_sleep(0.2, 0.5)

    def _wait_for_turnstile_token(self, page, timeout_ms=30000):
        """Wait for Cloudflare Turnstile token to be filled (by CapSolver extension)."""
        deadline = time.time() + (timeout_ms / 1000)
        while time.time() < deadline:
            try:
                token = page.evaluate("""() => {
                    const el = document.querySelector('input[name="cf-turnstile-response"]');
                    return el ? el.value : '';
                }""")
                if token and len(token) > 20:
                    return token
            except Exception:
                pass
            time.sleep(1)
        return None

    def _click_button_by_text(self, page, text, exact=False):
        """Click a button by its text content."""
        selector = f'button:has-text("{text}")'
        if exact:
            # Try exact match first
            btns = page.locator("button")
            count = btns.count()
            for i in range(count):
                btn = btns.nth(i)
                try:
                    if btn.inner_text(timeout=500).strip() == text:
                        if btn.is_visible():
                            btn.click(timeout=5000)
                            return True
                except Exception:
                    continue
        btn = page.locator(selector).first
        if btn.count() > 0 and btn.is_visible():
            btn.click(timeout=5000)
            return True
        return False

    def register(
        self,
        email: str,
        password: Optional[str] = None,
        otp_callback: Optional[Callable] = None,
        username: Optional[str] = None,
    ) -> Tuple[bool, dict]:
        if not password:
            password = _rand_password()
        if not username:
            username = _rand_username()

        page = None

        try:
            self._init_browser()
            page = self.context.new_page()

            # ─── Step 1: Navigate to j3gb registration page ───────────────────
            self.log(f"Navigating to registration page: {J3GB_REGISTER}")
            page.goto(J3GB_REGISTER, wait_until="domcontentloaded", timeout=45000)
            self._human_sleep(3, 5)

            # Retry if we hit a Cloudflare 5xx error
            for retry in range(5):
                title = page.title()
                if "521" in title or "502" in title or "503" in title or "Web server is down" in title:
                    self.log(f"Server error ({title}), retrying in 10s... (attempt {retry+1}/5)")
                    time.sleep(10)
                    page.reload(wait_until="domcontentloaded", timeout=30000)
                    self._human_sleep(3, 5)
                else:
                    break

            # Verify we're on the registration page
            body_text = page.locator("body").inner_text(timeout=5000)
            if "Create Account" not in body_text and "Sign up" not in body_text.lower():
                page.screenshot(path="j3gb_register_load_failed.png")
                return False, {"error": f"Registration page did not load properly. Title: {page.title()}"}

            self.log("Registration page loaded successfully")

            # ─── Step 2: Click "Continue with Universe Federation" ─────────────
            self.log("Clicking 'Continue with Universe Federation'...")
            clicked = False
            for attempt in range(10):
                try:
                    btns = page.locator("button")
                    count = btns.count()
                    for i in range(count):
                        btn = btns.nth(i)
                        try:
                            text = btn.inner_text(timeout=500)
                            if "Federation" in text and btn.is_visible():
                                btn.click(timeout=5000)
                                clicked = True
                                self.log("Clicked Federation button")
                                break
                        except Exception:
                            continue
                    if clicked:
                        break
                except Exception:
                    pass
                time.sleep(1)

            if not clicked:
                page.screenshot(path="j3gb_no_federation_btn.png")
                return False, {"error": "Could not find 'Continue with Universe Federation' button"}

            # Wait for redirect to MiAuth page (dc.hhhl.cc)
            self.log("Waiting for redirect to MiAuth page...")
            self._human_sleep(3, 5)

            for _ in range(30):
                current_url = page.url
                if "dc.hhhl.cc" in current_url or "miauth" in current_url.lower():
                    self.log(f"Reached MiAuth page: {current_url[:80]}...")
                    break
                time.sleep(1)
            else:
                page.screenshot(path="j3gb_no_miauth_redirect.png")
                return False, {"error": "Did not redirect to MiAuth page"}

            self._human_sleep(2, 3)

            # ─── Step 3: Click "Add account" on MiAuth page ────────────────────
            self.log("Clicking 'Add account' on MiAuth page...")
            self._click_button_by_text(page, "Add account", exact=True)
            self._human_sleep(2, 3)

            # ─── Step 4: Click "Create account" ────────────────────────────────
            self.log("Clicking 'Create account'...")
            self._click_button_by_text(page, "Create account", exact=True)
            self._human_sleep(2, 3)

            # ─── Step 5: Agree to server rules and important notes ─────────────
            self.log("Agreeing to server rules and important notes...")

            # Misskey wraps each agreement switch behind a confirmation modal:
            # clicking the visible "toggle" opens a dialog (with an "OK"
            # button) that must be confirmed to actually mark the field as
            # agreed.  The "Continue" button (data-cy-signup-rules-continue)
            # stays disabled until every agreement has been confirmed.
            for attempt in range(15):
                toggles = page.locator('[data-cy-switch-toggle]')
                try:
                    toggle_count = toggles.count()
                except Exception:
                    toggle_count = 0

                # Confirm any toggle that is not yet checked.
                confirmed_any = False
                for i in range(toggle_count):
                    try:
                        toggle = toggles.nth(i)
                        # Determine whether this switch is already checked
                        # by looking at the paired <input> state.
                        checked = False
                        try:
                            inp = page.locator('.MkSwitch-root-1kPZ').nth(i).locator('input.MkSwitch-input-6eY1')
                            checked = bool(inp.is_checked())
                        except Exception:
                            pass
                        if checked:
                            continue
                        # Open the confirmation modal (force-click as
                        # overlay divs intercept normal clicks)
                        toggle.click(timeout=2000, force=True)
                        self._human_sleep(1.0, 1.5)
                        # Confirm with the "OK" button that appears in the modal
                        if self._click_button_by_text(page, "OK", exact=True):
                            confirmed_any = True
                            self._human_sleep(0.5, 1.0)
                    except Exception:
                        continue

                # Stop early if the Continue button is enabled
                cont_btn = page.locator('button[data-cy-signup-rules-continue]')
                if cont_btn.count() > 0:
                    try:
                        if not cont_btn.first.is_disabled():
                            self.log("All agreement switches confirmed")
                            break
                    except Exception:
                        pass
                if not confirmed_any and toggle_count == 0:
                    # Possibly already past the agreement screen
                    break
                self._human_sleep(0.5, 1.0)

            self._human_sleep(1, 2)

            # Click the agreement "Continue" button (data-cy-signup-rules-continue).
            self.log("Clicking Continue after agreements...")
            cont_clicked = False
            for attempt in range(10):
                cont_btn = page.locator('button[data-cy-signup-rules-continue]')
                if cont_btn.count() > 0:
                    try:
                        if not cont_btn.first.is_disabled():
                            cont_btn.first.click(timeout=5000)
                            cont_clicked = True
                            break
                    except Exception:
                        pass
                # Fallback: use the text-based locator of the last Continue
                fb = page.locator('button:has-text("Continue")')
                fb_count = fb.count()
                if fb_count > 0:
                    try:
                        last = fb.nth(fb_count - 1)
                        if last.is_visible() and not last.is_disabled():
                            last.click(timeout=5000)
                            cont_clicked = True
                            break
                    except Exception:
                        pass
                # Try confirming any leftover modal OK first
                self._click_button_by_text(page, "OK", exact=True)
                self._human_sleep(0.5, 1.0)

            self._human_sleep(2, 3)

            # ─── Step 6: Fill the Misskey federation registration form ──────────
            self.log("Waiting for registration form to appear...")

            # Wait for the username input to appear
            username_input = None
            for _ in range(30):
                try:
                    inputs = page.locator('input.MkInput-inputCore-ndfW')
                    if inputs.count() >= 4:
                        username_input = inputs.nth(0)
                        if username_input.is_visible():
                            break
                except Exception:
                    pass
                time.sleep(1)

            if not username_input:
                page.screenshot(path="j3gb_no_register_form.png")
                with open("j3gb_no_register_form.html", "w", encoding="utf-8") as f:
                    f.write(page.content())
                return False, {"error": "Registration form did not appear"}

            self.log(f"Filling registration form (username={username})...")

            # Fill username (input[type=text] with MkInput class)
            text_inputs = page.locator('input.MkInput-inputCore-ndfW[type="text"]')
            if text_inputs.count() > 0:
                self._type_human(page, 'input.MkInput-inputCore-ndfW[type="text"]', username)
            else:
                # Fallback: first MkInput
                inputs = page.locator('input.MkInput-inputCore-ndfW')
                if inputs.count() > 0:
                    inputs.nth(0).click()
                    inputs.nth(0).fill("")
                    for char in username:
                        page.keyboard.type(char, delay=random.randint(50, 150))

            self._human_sleep(0.5, 1)

            # Fill email (input[type=email])
            self.log(f"Filling email: {email}")
            email_input = page.locator('input.MkInput-inputCore-ndfW[type="email"]')
            if email_input.count() > 0:
                self._type_human(page, 'input.MkInput-inputCore-ndfW[type="email"]', email)
            else:
                # Fallback: second MkInput
                inputs = page.locator('input.MkInput-inputCore-ndfW')
                if inputs.count() > 1:
                    inputs.nth(1).click()
                    inputs.nth(1).fill("")
                    for char in email:
                        page.keyboard.type(char, delay=random.randint(50, 150))

            self._human_sleep(0.5, 1)

            # Fill password (first password input)
            self.log("Filling password...")
            pw_inputs = page.locator('input.MkInput-inputCore-ndfW[type="password"]')
            if pw_inputs.count() >= 2:
                pw_inputs.nth(0).click()
                pw_inputs.nth(0).fill("")
                for char in password:
                    page.keyboard.type(char, delay=random.randint(50, 150))
                self._human_sleep(0.3, 0.5)
                pw_inputs.nth(1).click()
                pw_inputs.nth(1).fill("")
                for char in password:
                    page.keyboard.type(char, delay=random.randint(50, 150))

            self._human_sleep(1, 2)

            # Wait for Turnstile to be solved (CapSolver extension handles it)
            self.log("Waiting for Cloudflare Turnstile to be solved...")
            token = self._wait_for_turnstile_token(page, timeout_ms=60000)
            if token:
                self.log(f"Turnstile token received: {token[:30]}...")
            else:
                self.log("Warning: Turnstile token not detected, proceeding anyway...")

            # ─── Step 7: Click "Begin" to submit the registration form ──────────
            self.log("Clicking 'Begin' to submit registration form...")
            begin_clicked = False
            for attempt in range(10):
                try:
                    if self._click_button_by_text(page, "Begin", exact=True):
                        begin_clicked = True
                        break
                except Exception:
                    pass
                time.sleep(1)

            if not begin_clicked:
                page.screenshot(path="j3gb_no_begin_btn.png")
                with open("j3gb_no_begin_btn.html", "w", encoding="utf-8") as f:
                    f.write(page.content())
                return False, {"error": "Could not find/click 'Begin' button"}

            self._human_sleep(3, 5)

            # ─── Step 8: Handle email verification (OTP) ────────────────────────
            # Misskey sends a verification code to the email
            if otp_callback:
                self.log("Waiting for email verification code...")

                # Check if we need to enter a verification code
                otp_code = None
                for _ in range(10):
                    try:
                        body = page.locator("body").inner_text(timeout=2000).lower()
                        if "verification" in body or "code" in body or "verify" in body or "验证" in body:
                            break
                    except Exception:
                        pass
                    time.sleep(2)

                otp_code = otp_callback()
                if otp_code:
                    self.log(f"Got verification code: {otp_code}")
                    # Find OTP input field
                    otp_selectors = [
                        'input.MkInput-inputCore-ndfW[type="text"]',
                        'input[type="text"]',
                        'input[maxlength="6"]',
                        'input[placeholder*="code" i]',
                        'input.MkInput-inputCore-ndfW',
                    ]
                    otp_entered = False
                    for sel in otp_selectors:
                        try:
                            inp = page.locator(sel).first
                            if inp.count() > 0 and inp.is_visible():
                                inp.click()
                                inp.fill("")
                                for char in str(otp_code):
                                    page.keyboard.type(char, delay=random.randint(50, 150))
                                otp_entered = True
                                self.log(f"Entered OTP using selector: {sel}")
                                break
                        except Exception:
                            continue

                    if not otp_entered:
                        self.log("Warning: Could not find OTP input field")

                    self._human_sleep(1, 2)

                    # Submit the OTP (look for a submit/verify button or press Enter)
                    submitted = False
                    for btn_text in ["Verify", "Submit", "Continue", "OK", "Confirm"]:
                        if self._click_button_by_text(page, btn_text):
                            submitted = True
                            break
                    if not submitted:
                        page.keyboard.press("Enter")

                    self._human_sleep(3, 5)
                else:
                    self.log("Warning: No verification code received")
            else:
                self.log("No OTP callback provided, skipping email verification")

            # ─── Step 9: Authorize the MiAuth request ───────────────────────────
            # After registration/verification, we may need to click "Continue" to authorize
            self.log("Looking for MiAuth authorization button...")
            self._human_sleep(2, 3)

            for attempt in range(15):
                try:
                    body = page.locator("body").inner_text(timeout=2000)
                    # Check if we're back on j3gb (success)
                    if "vip.j3gb.com" in page.url:
                        self.log("Redirected back to vip.j3gb.com!")
                        break
                    # Look for authorization continue button
                    if "Continue" in body or "authorize" in body.lower() or "授权" in body:
                        # Click the main Continue button to authorize
                        cont_btns = page.locator('button:has-text("Continue")')
                        if cont_btns.count() > 0:
                            # Click the first visible one
                            for i in range(cont_btns.count()):
                                btn = cont_btns.nth(i)
                                if btn.is_visible():
                                    btn.click(timeout=5000)
                                    self.log("Clicked Continue to authorize MiAuth")
                                    break
                            self._human_sleep(2, 3)
                except Exception:
                    pass
                time.sleep(2)

            self._human_sleep(3, 5)

            # ─── Step 10: Verify we're logged in on vip.j3gb.com ────────────────
            current_url = page.url
            self.log(f"Current URL after federation: {current_url}")

            if "vip.j3gb.com" not in current_url:
                # Try navigating directly to the dashboard
                self.log("Not redirected to j3gb, navigating to dashboard...")
                page.goto(f"{J3GB_BASE}/panel", wait_until="domcontentloaded", timeout=30000)
                self._human_sleep(3, 5)
                current_url = page.url

            # Check if we're logged in
            body_text = page.locator("body").inner_text(timeout=5000)
            if "login" in current_url.lower() or "sign in" in body_text.lower():
                page.screenshot(path="j3gb_not_logged_in.png")
                with open("j3gb_not_logged_in.html", "w", encoding="utf-8") as f:
                    f.write(page.content())
                return False, {"error": "Not logged in after federation registration"}

            self.log("Successfully logged in to vip.j3gb.com!")

            # ─── Step 11: Navigate to token/API key page and create key ─────────
            api_key = self._create_api_key(page)

            if not api_key:
                self.log("Warning: Could not extract API key automatically")
                page.screenshot(path="j3gb_no_api_key.png")
                with open("j3gb_no_api_key.html", "w", encoding="utf-8") as f:
                    f.write(page.content())

            # Save to file
            if api_key:
                self._save_api_key(email, username, password, api_key)

            return True, {
                "email": email,
                "password": password,
                "username": username,
                "api_key": api_key,
            }

        except Exception as e:
            self.log(f"Registration error: {e}")
            if page:
                try:
                    page.screenshot(path="j3gb_error.png")
                    with open("j3gb_error.html", "w", encoding="utf-8") as f:
                        f.write(page.content())
                except Exception:
                    pass
            return False, {"error": str(e)}
        finally:
            self._close_browser()

    def _create_api_key(self, page: Page) -> str:
        """Create an API key using the J3GB REST API.

        The VIP dashboard stores the auth token in localStorage('auth_token')
        and uses an axios instance with baseURL '/api/v1'.  We extract the
        token from the page context and call POST /api/v1/keys directly,
        which is far more reliable than scraping the UI.
        """
        # Step 1: Extract the auth token from localStorage
        self.log("Extracting auth token from localStorage...")
        auth_token = ""
        for attempt in range(10):
            try:
                auth_token = page.evaluate("""() => {
                    try {
                        return localStorage.getItem('auth_token') || '';
                    } catch(e) { return ''; }
                }""")
                if auth_token:
                    break
            except Exception:
                pass
            # Navigate to the panel to ensure localStorage is populated
            try:
                page.goto(f"{J3GB_BASE}/panel", wait_until="domcontentloaded", timeout=15000)
                self._human_sleep(2, 3)
            except Exception:
                pass
            time.sleep(1)

        if not auth_token:
            self.log("Could not extract auth_token from localStorage")
            # Fallback: try UI-based key creation
            return self._create_api_key_ui(page)

        self.log(f"Auth token extracted: {auth_token[:20]}...")

        # Step 2: Call POST /api/v1/keys to create a new key
        key_name = f"AutoKey_{int(time.time())}"
        self.log(f"Creating API key via API (name={key_name})...")

        try:
            result = page.evaluate("""async (params) => {
                try {
                    const resp = await fetch('/api/v1/keys', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                            'Authorization': 'Bearer ' + params.token,
                        },
                        body: JSON.stringify({ name: params.name }),
                    });
                    const data = await resp.json();
                    return JSON.stringify(data);
                } catch(e) {
                    return JSON.stringify({error: e.message});
                }
            }""", {"token": auth_token, "name": key_name})

            data = json.loads(result)
            self.log(f"API response: {json.dumps(data)[:200]}")

            # The response should contain the key
            api_key = self._extract_key_from_response(data)
            if api_key:
                self.log(f"API key created successfully: {api_key[:20]}...")
                return api_key

            # If the key wasn't in the direct response, try listing keys
            self.log("Key not in create response, listing keys...")
            list_result = page.evaluate("""async (params) => {
                try {
                    const resp = await fetch('/api/v1/keys?page=1&page_size=5', {
                        method: 'GET',
                        headers: {
                            'Authorization': 'Bearer ' + params.token,
                        },
                    });
                    const data = await resp.json();
                    return JSON.stringify(data);
                } catch(e) {
                    return JSON.stringify({error: e.message});
                }
            }""", {"token": auth_token})

            list_data = json.loads(list_result)
            self.log(f"Keys list: {json.dumps(list_data)[:300]}")
            api_key = self._extract_key_from_response(list_data)
            if api_key:
                self.log(f"API key found in key list: {api_key[:20]}...")
                return api_key

        except Exception as e:
            self.log(f"API key creation via API failed: {e}")

        # Fallback: try UI-based approach
        self.log("Falling back to UI-based API key creation...")
        return self._create_api_key_ui(page)

    def _extract_key_from_response(self, data) -> str:
        """Extract an API key string from a JSON API response."""
        if not data:
            return ""

        # The key might be at various levels in the response
        # Common field names: key, api_key, token, secret, access_token
        key_fields = ["key", "api_key", "apikey", "token", "secret", "access_token", "value"]

        def _search(obj, depth=0):
            if depth > 5:
                return ""
            if isinstance(obj, str):
                # Check if this string looks like an API key
                if len(obj) >= 20 and re.match(r'^[a-zA-Z0-9\-_]+$', obj):
                    return obj
                return ""
            if isinstance(obj, dict):
                for field in key_fields:
                    val = obj.get(field)
                    if val and isinstance(val, str) and len(val) >= 20:
                        if re.match(r'^[a-zA-Z0-9\-_]+$', val):
                            return val
                # Search in nested objects
                for k, v in obj.items():
                    if k in ("data", "result", "item", "items", "list", "records"):
                        found = _search(v, depth + 1)
                        if found:
                            return found
                # Last resort: search all values
                for v in obj.values():
                    found = _search(v, depth + 1)
                    if found:
                        return found
            if isinstance(obj, list):
                for item in obj:
                    found = _search(item, depth + 1)
                    if found:
                        return found
            return ""

        return _search(data)

    def _create_api_key_ui(self, page: Page) -> str:
        """Fallback: Create API key via UI interaction."""
        self.log("Attempting UI-based API key creation...")

        # Navigate to the keys page
        key_urls = [
            f"{J3GB_BASE}/panel/keys",
            f"{J3GB_BASE}/panel/tokens",
            f"{J3GB_BASE}/panel/api-keys",
            f"{J3GB_BASE}/panel",
        ]

        for url in key_urls:
            try:
                self.log(f"Navigating to: {url}")
                page.goto(url, wait_until="domcontentloaded", timeout=20000)
                self._human_sleep(2, 3)

                if "login" in page.url.lower():
                    continue

                # Try to find and click a create button
                for btn_text in ["Create", "New", "Generate", "Add", "创建", "新建"]:
                    try:
                        btn = page.locator(f'button:has-text("{btn_text}")').first
                        if btn.count() > 0 and btn.is_visible():
                            btn.click(timeout=5000)
                            self.log(f"Clicked: {btn_text}")
                            self._human_sleep(2, 3)
                            break
                    except Exception:
                        continue

                # Fill name if dialog appears
                try:
                    name_input = page.locator('input[type="text"]').first
                    if name_input.count() > 0 and name_input.is_visible():
                        name_input.fill("Auto Key")
                        self._human_sleep(0.5, 1)
                except Exception:
                    pass

                # Click confirm
                for btn_text in ["Create", "Confirm", "OK", "Save", "Generate"]:
                    try:
                        btn = page.locator(f'button:has-text("{btn_text}")').last
                        if btn.count() > 0 and btn.is_visible():
                            btn.click(timeout=5000)
                            break
                    except Exception:
                        continue

                self._human_sleep(3, 5)

                # Try to extract key from UI
                key = self._extract_api_key_from_ui(page)
                if key:
                    return key

            except Exception as e:
                self.log(f"UI approach error at {url}: {e}")

        return ""

    def _extract_api_key_from_ui(self, page: Page) -> str:
        """Extract API key from the UI after creation."""
        # Look for elements displaying the key
        selectors = [
            'input[readonly]',
            'textarea[readonly]',
            'code',
            'pre',
            '[data-testid*="key"]',
            'input[type="text"]',
        ]

        for sel in selectors:
            try:
                elements = page.locator(sel).all()
                for el in elements:
                    try:
                        if sel.startswith("input") or sel.startswith("textarea"):
                            val = el.input_value()
                        else:
                            val = el.text_content()
                        if val and len(val.strip()) >= 20:
                            val = val.strip()
                            if re.match(r'^[a-zA-Z0-9\-_]+$', val):
                                self.log(f"Found key via UI selector: {sel}")
                                return val
                    except Exception:
                        continue
            except Exception:
                continue

        # Regex on page content
        try:
            content = page.content()
            patterns = [
                r'(sk-[a-zA-Z0-9\-_]{20,})',
                r'"key"\s*:\s*"([a-zA-Z0-9\-_]{20,})"',
                r'([a-zA-Z0-9\-_]{32,})',
            ]
            for pat in patterns:
                m = re.search(pat, content)
                if m:
                    return m.group(1)
        except Exception:
            pass

        return ""

    def _save_api_key(self, email: str, username: str, password: str, api_key: str):
        """Save API key to j3gb_keys.txt file."""
        try:
            file_path = os.path.join(os.getcwd(), "j3gb_keys.txt")
            with open(file_path, "a", encoding="utf-8") as f:
                f.write(f"email={email}\n")
                f.write(f"username={username}\n")
                f.write(f"password={password}\n")
                f.write(f"api_key={api_key}\n")
                f.write(f"federation=dc.hhhl.cc\n")
                f.write(f"---\n")
            self.log(f"API key saved to {file_path}")
        except Exception as e:
            self.log(f"Failed to save API key to file: {e}")
