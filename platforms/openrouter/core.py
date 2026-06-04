"""
OpenRouter.ai Automatic registration with API key generation

Process:
  1. Navigate to signup page (Clerk authentication)
  2. Fill firstName, lastName, emailAddress, password
  3. Submit and verify email with OTP
  4. Navigate to settings/keys page
  5. Generate API key
  6. Save API key to file
"""

import re
import json
import time
import random
import string
from typing import Optional, Tuple, Any
from playwright.sync_api import sync_playwright, TimeoutError, Page
from core.browser_runtime import ensure_browser_display_available, resolve_browser_headless

OPENROUTER_BASE = "https://openrouter.ai"
OPENROUTER_SIGNUP = f"{OPENROUTER_BASE}/sign-up"
OPENROUTER_SIGNIN = f"{OPENROUTER_BASE}/sign-in"
OPENROUTER_KEYS = f"{OPENROUTER_BASE}/workspaces/default/keys"


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


def _rand_name():
    first_names = ["John", "Jane", "Alex", "Sam", "Chris", "Jordan", "Taylor", "Morgan"]
    last_names = ["Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis"]
    return random.choice(first_names), random.choice(last_names)


class OpenRouterRegister:
    def __init__(self, proxy: str = None, headless: bool = True, captcha_solver = None):
        self.proxy = proxy
        self.headless = headless
        self.executor = None
        self.captcha_solver = captcha_solver

    def log(self, msg):
        print(f"[OpenRouter] {msg}")

    def _human_sleep(self, min_sec: float = 0.5, max_sec: float = 1.5):
        time.sleep(random.uniform(min_sec, max_sec))

    def _init_browser(self):
        """Launch Chromium with CapSolver extension loaded.
        The extension auto-solves Cloudflare Turnstile challenges in-browser."""
        import os, tempfile
        from playwright.sync_api import sync_playwright
        from core.browser_runtime import ensure_browser_display_available, resolve_browser_headless
        from core.proxy_utils import build_playwright_proxy_config, resolve_us_profile

        class _ContextWrapper:
            """Shim so OpenRouterRegister can use self.executor.page like PlaywrightExecutor."""
            def __init__(self, page, pw, context):
                self.page = page
                self._pw = pw
                self._context = context
            def close(self):
                try:
                    self._context.close()
                except Exception:
                    pass
                try:
                    self._pw.stop()
                except Exception:
                    pass

        headless, reason = resolve_browser_headless(self.headless)
        # Extensions require headed mode — force headed if headless was requested
        if headless:
            self.log("Warning: CapSolver extension requires headed mode — switching to headed")
            headless = False
        ensure_browser_display_available(headless)

        # Path to the extracted CapSolver extension
        ext_path = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "..", "capsolver-ext")
        )
        if not os.path.exists(ext_path):
            self.log(f"Warning: CapSolver extension not found at {ext_path}, falling back to plain Chromium")
            ext_path = None

        pw = sync_playwright().start()
        # Use a temp user-data-dir so we get a clean profile each run
        user_data_dir = tempfile.mkdtemp(prefix="openrouter_playwright_")

        launch_args = [
            "--disable-blink-features=AutomationControlled",
            "--disable-dev-shm-usage",
            "--no-sandbox",
            "--window-position=0,0",
        ]
        if ext_path:
            launch_args += [
                f"--disable-extensions-except={ext_path}",
                f"--load-extension={ext_path}",
            ]

        us_loc = resolve_us_profile(self.proxy)
        context_opts = dict(
            headless=False,
            args=launch_args,
            locale=us_loc["locale"],
            timezone_id=us_loc["timezone"],
            geolocation={"latitude": us_loc["latitude"], "longitude": us_loc["longitude"]},
            permissions=["geolocation"],
            viewport={"width": 1280, "height": 800},
            no_viewport=False,
        )
        if self.proxy:
            proxy_cfg = build_playwright_proxy_config(self.proxy)
            if proxy_cfg:
                context_opts["proxy"] = proxy_cfg

        context = pw.chromium.launch_persistent_context(user_data_dir, **context_opts)
        # Get the first page or open a new one
        pages = context.pages
        page = pages[0] if pages else context.new_page()
        self.executor = _ContextWrapper(page, pw, context)
        ext_status = f"with CapSolver extension ({ext_path})" if ext_path else "without extension (not found)"
        self.log(f"Browser mode: headed Chromium {ext_status}")



    def _close_browser(self):
        if self.executor:
            self.executor.close()

    def _find_turnstile_widget(self, page) -> Tuple[Optional[Any], Optional[dict]]:
        for frame in page.frames:
            if "challenges.cloudflare.com" not in frame.url:
                continue
            try:
                frame_el = frame.frame_element()
                box = frame_el.bounding_box()
            except Exception:
                box = None
            if box and box["width"] > 100 and box["height"] >= 50:
                return frame, box
        return None, None

    def _read_turnstile_token(self, page) -> str:
        return page.evaluate(
            """() => {
                return (
                    document.querySelector('input[id^="cf-chl-widget-"]')?.value ||
                    document.querySelector('input[name="cf-turnstile-response"]')?.value ||
                    ''
                );
            }"""
        )

    def _read_turnstile_sitekey(self, page) -> str:
        """Extract Cloudflare Turnstile sitekey from the page.
        Clerk embeds Turnstile inside its own iframe, so we must search across all frames."""

        # 1. Check main document first
        sitekey = page.evaluate("""() => {
            const byData = document.querySelector('[data-sitekey]')?.getAttribute('data-sitekey');
            if (byData) return byData;
            for (const iframe of document.querySelectorAll('iframe[src*="challenges.cloudflare.com"]')) {
                try {
                    const u = new URL(iframe.src, location.href);
                    const k = u.searchParams.get('k');
                    if (k) return k;
                } catch (_) {}
            }
            return '';
        }""")
        if sitekey:
            return sitekey

        # 2. Search across ALL frames (Clerk renders Turnstile inside a nested iframe)
        for frame in page.frames:
            # The Cloudflare challenge frame URL itself contains the sitekey
            if "challenges.cloudflare.com" in frame.url:
                try:
                    from urllib.parse import urlparse, parse_qs
                    parsed = urlparse(frame.url)
                    k = parse_qs(parsed.query).get("k", [""])[0]
                    if k:
                        self.log(f"  Sitekey found in frame URL: {k[:8]}...")
                        return k
                except Exception:
                    pass
            # Also check if this frame contains a Cloudflare iframe
            try:
                k = frame.evaluate("""() => {
                    const byData = document.querySelector('[data-sitekey]')?.getAttribute('data-sitekey');
                    if (byData) return byData;
                    for (const iframe of document.querySelectorAll('iframe[src*="challenges.cloudflare.com"]')) {
                        try {
                            const u = new URL(iframe.src, location.href);
                            const k = u.searchParams.get('k');
                            if (k) return k;
                        } catch (_) {}
                    }
                    return '';
                }""")
                if k:
                    self.log(f"  Sitekey found in sub-frame: {k[:8]}...")
                    return k
            except Exception:
                pass

        # 3. Search page source for the sitekey pattern (Clerk bakes it into JS config)
        try:
            src = page.content()
            import re
            # Turnstile sitekeys start with "0x" and are 32+ chars
            matches = re.findall(r'["\']?(0x[A-Za-z0-9_-]{20,})["\']?', src)
            for m in matches:
                if len(m) >= 20:
                    self.log(f"  Sitekey found in page source: {m[:8]}...")
                    return m
        except Exception:
            pass

        # 4. Hardcoded known sitekey for OpenRouter (Clerk-hosted Turnstile)
        # This sitekey is public and embedded in OpenRouter's Clerk configuration
        OPENROUTER_TURNSTILE_SITEKEY = "0x4AAAAAAA3if_LuLLDMGnv5"
        self.log(f"  Using hardcoded sitekey fallback: {OPENROUTER_TURNSTILE_SITEKEY[:8]}...")
        return OPENROUTER_TURNSTILE_SITEKEY

    def _solve_turnstile_on_page(self, page) -> str:
        self.log("Bypassing Turnstile challenge on page...")
        last_error = None

        # 1. Try CapSolver/API first (fastest, most reliable)
        try:
            token = self._solve_turnstile_by_solver(page)
            if token:
                self.log(f"  Turnstile token(solver): {token[:40]}...")
                return token
        except Exception as e:
            last_error = str(e)
            self.log(f"  Solver failed ({e}), falling back to click method...")

        # 2. Fall back to click-based solving
        for attempt in range(8):
            frame, box = self._find_turnstile_widget(page)
            if not box:
                page.wait_for_timeout(1000)
                if last_error is None:
                    last_error = "No clickable found Turnstile iframe"
                continue

            click_x = box["x"] + min(28, max(18, box["width"] * 0.08))
            click_y = box["y"] + box["height"] / 2
            self.log(
                f"  Turnstile click #{attempt + 1}: ({click_x:.1f}, {click_y:.1f})"
            )
            try:
                if frame:
                    frame.locator("body").click(
                        position={
                            "x": min(28, max(18, box["width"] * 0.08)),
                            "y": box["height"] / 2,
                        },
                        timeout=2500,
                    )
                    page.wait_for_timeout(120)
                page.mouse.move(click_x, click_y)
                page.mouse.down()
                page.wait_for_timeout(120)
                page.mouse.up()
                token = self._wait_turnstile_token(page, wait_rounds=28, wait_ms=450)
                if token:
                    self.log(f"  Turnstile token: {token[:40]}...")
                    return token
            except Exception as e:
                last_error = str(e)

            try:
                token = self._native_click_turnstile(
                    page, box, min(28, max(18, box["width"] * 0.08))
                )
                if token:
                    self.log(f"  Turnstile token: {token[:40]}...")
                    return token
            except Exception as e:
                last_error = str(e)

            if self._has_turnstile_error(page):
                self.log("  detected Turnstile Verification failed prompt, prepare to try again...")
            page.wait_for_timeout(900 + attempt * 120)

        raise RuntimeError(last_error or "Turnstile Solution failed")


    def _has_turnstile_error(self, page) -> bool:
        keywords = [
            "Authentication failed",
            "troubleshooting",
            "verification failed",
            "troubleshoot",
            "try again",
        ]
        texts = []
        try:
            texts.append(page.locator("body").inner_text(timeout=800))
        except Exception:
            pass

        for frame in page.frames:
            if "challenges.cloudflare.com" not in frame.url:
                continue
            try:
                texts.append(frame.locator("body").inner_text(timeout=500))
            except Exception:
                continue

        merged = "\n".join(texts).lower()
        return any(k.lower() in merged for k in keywords)

    def _inject_turnstile_token(self, page, token: str) -> bool:
        return bool(
            page.evaluate(
                """(token) => {
                    const selectors = [
                        'input[id^="cf-chl-widget-"]',
                        'input[name="cf-turnstile-response"]',
                        'textarea[name="cf-turnstile-response"]',
                        'textarea[name="g-recaptcha-response"]',
                    ];
                    const inputs = [];
                    for (const sel of selectors) {
                        document.querySelectorAll(sel).forEach((el) => inputs.push(el));
                    }
                    if (!inputs.length) {
                        const fallback = document.createElement('input');
                        fallback.type = 'hidden';
                        fallback.name = 'cf-turnstile-response';
                        document.body.appendChild(fallback);
                        inputs.push(fallback);
                    }
                    for (const el of inputs) {
                        el.value = token;
                        el.setAttribute('value', token);
                        el.dispatchEvent(new Event('input', { bubbles: true }));
                        el.dispatchEvent(new Event('change', { bubbles: true }));
                    }
                    return inputs.length > 0;
                }""",
                token,
            )
        )

    def _wait_turnstile_token(self, page, wait_rounds: int = 25, wait_ms: int = 500) -> str:
        for _ in range(wait_rounds):
            token = self._read_turnstile_token(page)
            if token and len(token) > 20:
                return token
            page.wait_for_timeout(wait_ms)
        return ""

    def _native_click_turnstile(self, page, box, offset_x: float) -> str:
        import ctypes
        try:
            user32 = ctypes.windll.user32
            try:
                user32.SetProcessDPIAware()
            except Exception:
                pass
        except Exception as e:
            raise RuntimeError(f"The current system does not support native clicks: {e}") from e

        page.bring_to_front()
        metrics = page.evaluate(
            """() => ({
                screenX,
                screenY,
                outerWidth,
                outerHeight,
                innerWidth,
                innerHeight,
                dpr: window.devicePixelRatio,
            })"""
        )

        border_x = max(0, (metrics["outerWidth"] - metrics["innerWidth"]) / 2)
        chrome_y = max(0, metrics["outerHeight"] - metrics["innerHeight"] - border_x)
        raw_x = metrics["screenX"] + border_x + box["x"] + offset_x
        raw_y = metrics["screenY"] + chrome_y + box["y"] + box["height"] / 2
        dpr = float(metrics.get("dpr") or 1.0)
        points = [(raw_x, raw_y)]
        if abs(dpr - 1.0) > 0.05:
            points.append((raw_x * dpr, raw_y * dpr))

        for idx, (screen_x, screen_y) in enumerate(points, start=1):
            self.log(f"  Native click #{idx}: ({screen_x:.1f}, {screen_y:.1f})")
            user32.SetCursorPos(int(screen_x), int(screen_y))
            time.sleep(0.15)
            user32.mouse_event(0x0002, 0, 0, 0, 0)
            time.sleep(0.12)
            user32.mouse_event(0x0004, 0, 0, 0, 0)

            token = self._wait_turnstile_token(page, wait_rounds=18, wait_ms=450)
            if token:
                return token

        raise RuntimeError("Native click Still haven’t gotten it yet token")

    def _solve_turnstile_by_solver(self, page) -> str:
        if not self.captcha_solver:
            return ""
        solver_name = type(self.captcha_solver).__name__.lower()
        if "manual" in solver_name:
            return ""
        client_key = getattr(self.captcha_solver, "client_key", None)
        if client_key is not None and not str(client_key).strip():
            self.log("  Not configured YesCaptcha key, skip the verification code service")
            return ""
        sitekey = self._read_turnstile_sitekey(page)
        if not sitekey:
            self.log("  Not extracted Turnstile sitekey, skip the verification code service")
            return ""
        self.log(f"  Call local/remote verification service to solve Turnstile (sitekey={sitekey[:8]}...)")
        token = self.captcha_solver.solve_turnstile(page.url, sitekey)
        if not token:
            return ""
        if self._inject_turnstile_token(page, token):
            page.wait_for_timeout(400)
            return self._read_turnstile_token(page) or token
        return ""

    def _solve_turnstile_on_page(self, page) -> str:
        self.log("Bypassing Turnstile challenge on page...")
        last_error = None
        for attempt in range(8):
            frame, box = self._find_turnstile_widget(page)
            if not box:
                page.wait_for_timeout(1000)
                if last_error is None:
                    last_error = "No clickable found Turnstile iframe"
                continue

            click_x = box["x"] + min(28, max(18, box["width"] * 0.08))
            click_y = box["y"] + box["height"] / 2
            self.log(
                f"  Turnstile click #{attempt + 1}: ({click_x:.1f}, {click_y:.1f})"
            )
            try:
                if frame:
                    frame.locator("body").click(
                        position={
                            "x": min(28, max(18, box["width"] * 0.08)),
                            "y": box["height"] / 2,
                        },
                        timeout=2500,
                    )
                    page.wait_for_timeout(120)
                page.mouse.move(click_x, click_y)
                page.mouse.down()
                page.wait_for_timeout(120)
                page.mouse.up()
                token = self._wait_turnstile_token(page, wait_rounds=28, wait_ms=450)
                if token:
                    self.log(f"  Turnstile token: {token[:40]}...")
                    return token
            except Exception as e:
                last_error = str(e)

            try:
                token = self._native_click_turnstile(
                    page, box, min(28, max(18, box["width"] * 0.08))
                )
                if token:
                    self.log(f"  Turnstile token: {token[:40]}...")
                    return token
            except Exception as e:
                last_error = str(e)

            if self._has_turnstile_error(page):
                self.log("  detected Turnstile Verification failed prompt, prepare to try again...")
            page.wait_for_timeout(900 + attempt * 120)

        try:
            token = self._solve_turnstile_by_solver(page)
            if token:
                self.log(f"  Turnstile token(solver): {token[:40]}...")
                return token
        except Exception as e:
            last_error = str(e)

        raise RuntimeError(last_error or "Turnstile Solution failed")

    def _type_human(self, page: Page, selector: str, text: str):
        """Fill a Clerk React input by clicking to focus then typing char-by-char with native events."""
        self._human_sleep(0.3, 0.6)
        el = page.locator(selector).first
        el.wait_for(state="visible", timeout=8000)
        # Click to ensure focus
        el.click()
        self._human_sleep(0.15, 0.3)
        # Select all existing content
        page.keyboard.press("Control+A")
        page.keyboard.press("Delete")
        self._human_sleep(0.1, 0.2)
        # Type character by character — this is the only reliable method for Clerk React inputs
        # because Clerk listens for native keyboard events, not programmatic value changes
        el.press_sequentially(text, delay=random.randint(60, 130))
        self._human_sleep(0.2, 0.4)

    def register(
        self,
        email: str,
        password: Optional[str] = None,
        otp_callback=None,
    ) -> Tuple[bool, dict]:
        if not password:
            password = _rand_password()

        first_name, last_name = _rand_name()
        page = None
        
        try:
            self._init_browser()
            page = self.executor.page

            # Step 1: Navigate to signup page
            self.log(f"Navigating to signup page for {email}")
            # Use networkidle to ensure Clerk JS has fully loaded before we interact
            page.goto(OPENROUTER_SIGNUP, wait_until="networkidle", timeout=45000)
            self._human_sleep(2, 3)

            # Step 2: Fill signup form (Clerk fields)
            self.log(f"Filling signup form: {first_name} {last_name}")
            
            # Wait for the Clerk email input to appear and be interactive
            page.wait_for_selector('input[name="emailAddress"]', timeout=15000, state="visible")
            self._human_sleep(1.5, 2.5)

            # Fill first name if present
            try:
                fn_loc = page.locator('input[name="firstName"]')
                if fn_loc.count() > 0 and fn_loc.first.is_visible():
                    self.log(f"Filling firstName: {first_name}")
                    self._type_human(page, 'input[name="firstName"]', first_name)
            except Exception as e:
                self.log(f"Warning: could not fill firstName: {e}")
            
            # Fill last name if present
            try:
                ln_loc = page.locator('input[name="lastName"]')
                if ln_loc.count() > 0 and ln_loc.first.is_visible():
                    self.log(f"Filling lastName: {last_name}")
                    self._type_human(page, 'input[name="lastName"]', last_name)
            except Exception as e:
                self.log(f"Warning: could not fill lastName: {e}")
            
            # Fill email
            self.log(f"Filling email: {email}")
            self._type_human(page, 'input[name="emailAddress"]', email)
            
            # Verify email was filled correctly
            try:
                actual_email = page.locator('input[name="emailAddress"]').first.input_value()
                self.log(f"  Email field verified: '{actual_email}'")
                if actual_email != email:
                    self.log(f"  Email mismatch! Expected '{email}', got '{actual_email}'. Retrying...")
                    self._type_human(page, 'input[name="emailAddress"]', email)
            except Exception as e:
                self.log(f"Warning: could not verify email field: {e}")
            
            # Fill password
            self.log("Filling password")
            self._type_human(page, 'input[name="password"]', password)
            
            # Check the Terms checkbox BEFORE trying to submit
            try:
                checkbox = page.locator('input[name="legalAccepted"]').first
                if checkbox.count() > 0 and checkbox.is_visible():
                    if not checkbox.is_checked():
                        checkbox.check()
                        self.log("Checked legalAccepted checkbox")
                    self._human_sleep(0.3, 0.6)
                else:
                    # Fallback: any visible unchecked checkbox on the page
                    terms_cb = page.locator('input[type="checkbox"]').first
                    if terms_cb.count() > 0 and terms_cb.is_visible() and not terms_cb.is_checked():
                        terms_cb.check()
                        self.log("Checked Terms checkbox (fallback)")
                        self._human_sleep(0.3, 0.5)
            except Exception as e:
                self.log(f"Warning: failed to check Terms checkbox: {e}")

            # Find and click the continue/submit button
            self.log("Submitting signup form")
            try:
                curr_email = page.locator('input[name="emailAddress"]').first.input_value()
                self.log(f"  Email field value before submit: '{curr_email}'")
            except Exception:
                pass
            page.screenshot(path="openrouter_before_submit.png")

            # NOTE: Do NOT include 'button:has-text("Sign up")' here — it matches the nav bar
            # "Sign Up" button and re-opens a fresh empty modal on retry.
            submit_selectors = [
                'button[type="submit"]',
                'button:has-text("Continue")',
                'button.cl-formButtonPrimary',
            ]

            def _refill_form_if_empty():
                """If the signup form reappeared (Clerk re-render/overlay), refill it."""
                try:
                    em = page.locator('input[name="emailAddress"]').first
                    if em.count() > 0 and em.is_visible():
                        val = em.input_value()
                        if not val or val != email:
                            self.log("  Form reappeared empty — refilling with same credentials")
                            self._type_human(page, 'input[name="emailAddress"]', email)
                            self._type_human(page, 'input[name="password"]', password)
                            # Re-check Terms if needed
                            try:
                                cb = page.locator('input[type="checkbox"]').first
                                if cb.count() > 0 and cb.is_visible() and not cb.is_checked():
                                    cb.check()
                                    self.log("  Re-checked Terms checkbox")
                            except Exception:
                                pass
                except Exception as e:
                    self.log(f"  Warning during form refill: {e}")

            def _has_otp_input():
                """Check for Clerk's email verification code input (various forms)."""
                # 1. URL changed away from signup page
                try:
                    current_url = page.url
                    if "sign-up" not in current_url and "signup" not in current_url:
                        # Navigated away — likely on OTP or dashboard
                        return True
                except Exception:
                    pass

                # 2. Page text indicates we're on verification step
                try:
                    body_text = page.locator("body").inner_text(timeout=800).lower()
                    otp_phrases = ["check your email", "verify your email", "enter the code",
                                   "verification code", "we sent", "enter code", "enter the 6"]
                    if any(ph in body_text for ph in otp_phrases):
                        return True
                except Exception:
                    pass

                # 3. Element selectors
                otp_selectors = [
                    'input[name="code"]',
                    'input[placeholder*="code" i]',
                    'input[placeholder*="verification" i]',
                    'input[placeholder*="digit" i]',
                    'input[data-otp="true"]',
                    '.cl-otpCodeField input',
                    'input[maxlength="1"][type="text"]',
                    'input[autocomplete="one-time-code"]',
                    # Clerk renders OTP as a group of 6 single-char inputs
                    '.cl-otpCodeFieldInput',
                    'input[data-testid*="otp"]',
                ]
                for sel in otp_selectors:
                    try:
                        if page.locator(sel).count() > 0 and page.locator(sel).first.is_visible():
                            return True
                    except Exception:
                        pass
                return False

            submitted_successfully = False
            for submit_attempt in range(4):
                # 1. Check for any visible Turnstile widget and solve it
                try:
                    frame, box = self._find_turnstile_widget(page)
                    if box:
                        self.log("Cloudflare Turnstile widget detected, solving...")
                        self._solve_turnstile_on_page(page)
                        self._human_sleep(0.5, 1.0)
                except Exception as e:
                    self.log(f"Warning: failed to solve Turnstile: {e}")

                # 2. Refill form if it's empty (Clerk re-rendered it)
                _refill_form_if_empty()

                # 3. Click submit button (scope to the Clerk modal, avoid nav bar buttons)
                clicked = False
                for selector in submit_selectors:
                    try:
                        # Use nth=0 and confirm it's inside the Clerk modal (not nav bar)
                        btns = page.locator(selector)
                        for i in range(btns.count()):
                            btn = btns.nth(i)
                            if not btn.is_visible():
                                continue
                            # Skip nav bar buttons by checking parent context
                            # Nav bar buttons typically don't have an emailAddress input as sibling
                            parent_form = btn.locator('xpath=ancestor::form | ancestor::*[@data-clerk-component] | ancestor::*[.//input[@name="emailAddress"]]')
                            if parent_form.count() == 0:
                                # Check if there's an emailAddress input anywhere visible on page
                                # If yes, this is likely a form submit button, not nav bar
                                email_input = page.locator('input[name="emailAddress"]')
                                if email_input.count() == 0 or not email_input.is_visible():
                                    self.log(f"  Skipping '{selector}' (no email field visible, likely nav bar)")
                                    continue
                            if btn.is_disabled():
                                self.log(f"  Submit button '{selector}' is disabled — re-checking Terms")
                                try:
                                    terms_cb = page.locator('input[type="checkbox"]').first
                                    if terms_cb.count() > 0 and terms_cb.is_visible() and not terms_cb.is_checked():
                                        terms_cb.check()
                                        self._human_sleep(0.5, 0.8)
                                except Exception:
                                    pass
                                if btn.is_disabled():
                                    continue
                            btn.click()
                            clicked = True
                            self.log(f"Clicked submit button: {selector} (attempt {submit_attempt + 1})")
                            break
                        if clicked:
                            break
                    except Exception:
                        continue

                if not clicked:
                    self.log("Warning: Could not click submit button, might be disabled or loading")

                # Give CapSolver extension time to solve Turnstile and Clerk time to process
                self._human_sleep(10, 12)

                # 4. Check if we reached the OTP verification step
                if _has_otp_input():
                    submitted_successfully = True
                    self.log("Reached email verification code step!")
                    break
                else:
                    self.log(f"Still on signup page after attempt {submit_attempt + 1}")

            if not submitted_successfully:
                page.screenshot(path="openrouter_submission_failed.png")
                return False, {"error": "Failed to submit signup form. Stayed on signup page."}


            # Step 3: Wait for email verification to be sent
            if not otp_callback:
                return False, {"error": "OTP callback required"}

            self.log("Waiting for email verification to be sent...")
            self._human_sleep(3, 5)
            
            # Wait for verification code input to appear, or check for magic link mode
            self.log("Detecting verification mode...")
            code_input_found = False
            is_magic_link_mode = False
            
            code_selectors_to_wait = [
                'input[name="code"]',
                'input[maxlength="1"][type="text"]',  # Clerk individual digit boxes
                '.cl-otpCodeField input',
                '.cl-otpCodeFieldInput',
                'input[autocomplete="one-time-code"]',
                'input[data-otp="true"]',
                'input[type="text"][placeholder*="code" i]',
                'input[type="text"][placeholder*="verification" i]',
                'input.cl-formFieldInput[type="text"]',
            ]
            
            # Poll for up to 8 seconds to see if code inputs appear or if we are in magic link mode
            for _ in range(8):
                for selector in code_selectors_to_wait:
                    try:
                        if page.locator(selector).count() > 0 and page.locator(selector).first.is_visible():
                            code_input_found = True
                            self.log(f"Found verification code input: {selector}")
                            break
                    except Exception:
                        pass
                if code_input_found:
                    break
                
                try:
                    body_text = page.locator("body").inner_text(timeout=500).lower()
                    magic_indicators = ["verification link", "sent to your email", "link sent", "click the link", "didn't receive a link"]
                    if any(ind in body_text for ind in magic_indicators):
                        is_magic_link_mode = True
                        self.log("Detected Clerk magic link verification mode.")
                        break
                except Exception:
                    pass
                page.wait_for_timeout(1000)
            
            if not code_input_found and not is_magic_link_mode:
                self.log("Neither OTP input nor magic link keywords found, defaulting to magic link mode.")
                is_magic_link_mode = True
                
            self.log("Requesting verification code or magic link from email")
            otp_code_or_url = otp_callback()
            if not otp_code_or_url:
                page.screenshot(path="openrouter_no_code.png")
                with open("openrouter_no_code.html", "w", encoding="utf-8") as f:
                    f.write(page.content())
                return False, {"error": "Email verification code/link not received. Check openrouter_no_code.png/html"}

            self._human_sleep(1, 2)
            
            if str(otp_code_or_url).startswith("http"):
                # MAGIC LINK FLOW
                verification_url = str(otp_code_or_url)
                import html
                verification_url = html.unescape(verification_url)
                self.log(f"Received magic link URL: {verification_url[:50]}...")
                self.log("Navigating to verification link...")
                page.goto(verification_url, wait_until="networkidle", timeout=45000)
                self._human_sleep(3, 5)
            else:
                # OTP CODE FLOW
                otp_code = otp_code_or_url
                self.log(f"Got verification code: {otp_code}")
                
                if not code_input_found:
                    return False, {"error": "Verification code input not found for OTP code entry."}
                    
                code_entered = False
                for selector in code_selectors_to_wait:
                    try:
                        code_input = page.locator(selector).first
                        if code_input.count() > 0 and code_input.is_visible():
                            code_input.fill("")
                            self._human_sleep(0.3, 0.5)
                            self._type_human(page, selector, str(otp_code))
                            code_entered = True
                            self.log(f"Entered code using selector: {selector}")
                            break
                    except Exception as e:
                        continue
                
                if not code_entered:
                    page.screenshot(path="openrouter_code_entry_failed.png")
                    with open("openrouter_code_entry_failed.html", "w", encoding="utf-8") as f:
                        f.write(page.content())
                    return False, {"error": "Could not enter verification code. Check openrouter_code_entry_failed.png/html"}
                
                # Submit verification code
                self._human_sleep(1, 2)
                # Solve Turnstile if present on verification page
                try:
                    frame, box = self._find_turnstile_widget(page)
                    if box:
                        self.log("Cloudflare Turnstile widget detected on OTP verification page, solving...")
                        self._solve_turnstile_on_page(page)
                        self._human_sleep(0.5, 1.0)
                except Exception as e:
                    self.log(f"Warning: failed to solve Turnstile on OTP page: {e}")
                self.log("Submitting verification code")
                
                submit_selectors = [
                    'button[type="submit"]',
                    'button:has-text("Continue")',
                    'button:has-text("Verify")',
                    'button:has-text("Submit")',
                    'button.cl-formButtonPrimary',
                ]
                
                submitted = False
                for selector in submit_selectors:
                    try:
                        btn = page.locator(selector).first
                        if btn.count() > 0 and btn.is_visible() and not btn.is_disabled():
                            btn.click()
                            submitted = True
                            self.log(f"Clicked submit button: {selector}")
                            break
                    except Exception as e:
                        continue
                
                if not submitted:
                    self.log("Warning: Could not find enabled submit button, code may auto-submit")
                self._human_sleep(3, 5)

            # Step 5: Navigate to API keys page
            self.log("Navigating to API keys page")
            page.goto(OPENROUTER_KEYS, wait_until="domcontentloaded", timeout=30000)
            self._human_sleep(2, 3)
            
            current_url = page.url
            self.log(f"Current URL: {current_url}")
            
            # Check if we're still on sign-in page (not logged in)
            if "sign-in" in current_url or "sign-up" in current_url:
                page.screenshot(path="openrouter_not_logged_in.png")
                return False, {"error": "Not logged in after verification. Check screenshot."}

            # Onboarding survey bypass
            try:
                survey_heading = page.locator('h2:has-text("Where did you first hear")').first
                if survey_heading.count() > 0 and survey_heading.is_visible():
                    self.log("Onboarding survey popup detected. Bypassing...")
                    other_opt = page.locator('button:has-text("Other / Not sure")').first
                    if other_opt.count() > 0 and other_opt.is_visible():
                        other_opt.click()
                        self._human_sleep(0.5, 0.8)
                    else:
                        for fallback_text in ["Friend / Colleague", "Google", "LinkedIn", "YouTube"]:
                            btn = page.locator(f'button:has-text("{fallback_text}")').first
                            if btn.count() > 0 and btn.is_visible():
                                btn.click()
                                self._human_sleep(0.5, 0.8)
                                break
                    
                    continue_btn = page.locator('button:has-text("Continue")').first
                    if continue_btn.count() > 0 and continue_btn.is_visible():
                        continue_btn.click()
                        self.log("Clicked Continue button on survey.")
                        self._human_sleep(2, 3)
            except Exception as e:
                self.log(f"Warning during onboarding survey bypass: {e}")

            # Step 6: Generate API key
            self.log("Step 6: Creating API key on keys page")
            self._human_sleep(2, 3)

            # Take a screenshot so we can see exactly what's on the page
            page.screenshot(path="openrouter_keys_page.png")
            self.log(f"Current URL for keys page: {page.url}")

            # --- Click the 'New Key' / 'Create API Key' button to open dialog ---
            new_key_clicked = False

            # Selectors that match the '+ New Key' button on openrouter.ai/workspaces/default/keys
            new_key_selectors = [
                'button:has-text("New Key")',
                'a:has-text("New Key")',
                'button:has-text("Create API Key")',
                'button:has-text("Create Key")',
                'button:has-text("Generate Key")',
                '[data-testid="create-key-button"]',
                'a[href*="create"]',
            ]

            for attempt in range(5):
                if new_key_clicked:
                    break
                for selector in new_key_selectors:
                    try:
                        btn = page.locator(selector).first
                        if btn.count() > 0 and btn.is_visible():
                            self.log(f"Found New Key button using selector: {selector} (attempt {attempt+1})")
                            # Scroll into view first
                            try:
                                btn.scroll_into_view_if_needed(timeout=2000)
                            except Exception:
                                pass
                            self._human_sleep(0.3, 0.6)
                            # Try normal click first
                            try:
                                btn.click(timeout=5000)
                                new_key_clicked = True
                                self.log("Clicked New Key button (normal click).")
                                break
                            except Exception as ce:
                                self.log(f"Normal click failed: {ce}, trying JS click...")
                                try:
                                    page.evaluate("el => el.click()", btn.element_handle())
                                    new_key_clicked = True
                                    self.log("Clicked New Key button (JS click).")
                                    break
                                except Exception as je:
                                    self.log(f"JS click also failed: {je}")
                    except Exception as e:
                        continue
                if not new_key_clicked:
                    page.wait_for_timeout(1500)

            if not new_key_clicked:
                self.log("Could not find New Key button. Saving debug screenshot.")
                page.screenshot(path="openrouter_no_key_btn.png")
                with open("openrouter_no_key_btn.html", "w", encoding="utf-8") as f:
                    f.write(page.content())

            # --- Wait for dialog to appear ---
            self._human_sleep(1.5, 2.5)
            page.screenshot(path="openrouter_after_new_key_click.png")

            # The dialog contains a text input for the key name
            # Try many possible selectors for the dialog
            dialog = None
            dialog_input = None

            dialog_selectors = [
                '[role="dialog"]',
                'div[role="dialog"]',
                '[data-radix-dialog-content]',
                '[data-state="open"]',
                '.modal',
                '[aria-modal="true"]',
            ]

            for sel in dialog_selectors:
                try:
                    loc = page.locator(sel).first
                    if loc.count() > 0 and loc.is_visible():
                        self.log(f"Found dialog using selector: {sel}")
                        dialog = loc
                        break
                except Exception:
                    continue

            # --- Fill the key name input ---
            key_name = "My Auto Key"

            # Try to find name input inside dialog first, then fall back to page-level
            name_input_selectors = [
                'input[placeholder*="Chatbot"]',
                'input[placeholder*="Key"]',
                'input[placeholder*="name"]',
                'input[placeholder*="Name"]',
                'input[type="text"]',
                'input',
            ]

            name_input_filled = False
            for sel in name_input_selectors:
                try:
                    if dialog:
                        inp = dialog.locator(sel).first
                    else:
                        inp = page.locator(f'[role="dialog"] {sel}, [aria-modal="true"] {sel}').first
                    if inp.count() > 0 and inp.is_visible():
                        self.log(f"Filling key name input with selector: {sel}")
                        inp.triple_click()
                        inp.fill(key_name)
                        self._human_sleep(0.4, 0.7)
                        actual_val = inp.input_value()
                        self.log(f"Key name input value: '{actual_val}'")
                        name_input_filled = True
                        break
                except Exception as e:
                    continue

            if not name_input_filled:
                self.log("Warning: Could not fill key name input. The dialog may not have appeared.")
                page.screenshot(path="openrouter_no_key.png")
                with open("openrouter_no_key.html", "w", encoding="utf-8") as f:
                    f.write(page.content())

            self._human_sleep(0.5, 1.0)

            # --- Click the Create / Submit button inside the dialog ---
            create_btn_selectors = [
                'button:has-text("Create")',
                'button[type="submit"]',
                'button:has-text("Save")',
                'button:has-text("Generate")',
                'button:has-text("Confirm")',
            ]

            create_clicked = False
            for sel in create_btn_selectors:
                try:
                    if dialog:
                        btn = dialog.locator(sel).first
                    else:
                        btn = page.locator(f'[role="dialog"] {sel}').first
                    if btn.count() > 0 and btn.is_visible() and not btn.is_disabled():
                        self.log(f"Clicking Create button: {sel}")
                        btn.click(timeout=5000)
                        create_clicked = True
                        self.log("Clicked Create button in dialog.")
                        break
                except Exception as e:
                    continue

            if not create_clicked:
                # Last resort: page-level create button
                try:
                    btn = page.locator('button:has-text("Create")').last
                    if btn.count() > 0 and btn.is_visible():
                        btn.click(timeout=5000)
                        create_clicked = True
                        self.log("Clicked Create button (page-level fallback).")
                except Exception:
                    pass

            if not create_clicked:
                self.log("Warning: Could not click Create button in dialog.")

            # Wait for the API key to be revealed
            self._human_sleep(3, 5)
            page.screenshot(path="openrouter_after_create.png")

            # --- Extract the API key ---
            api_key = None

            # Method 1: Input/textarea with sk-or- value
            key_selectors = [
                'input[value^="sk-or-"]',
                'textarea[value^="sk-or-"]',
                'input[readonly]',
                'textarea[readonly]',
                'code',
                'pre',
                '[data-testid*="key"]',
                'input[type="text"]',
            ]

            for selector in key_selectors:
                try:
                    elements = page.locator(selector).all()
                    for el in elements:
                        try:
                            if selector.startswith('input') or selector.startswith('textarea'):
                                val = el.input_value()
                            else:
                                val = el.text_content()
                            if val and ('sk-or-' in val or (val.startswith('sk-') and len(val) > 30)):
                                match = re.search(r'(sk-or-v1-[a-zA-Z0-9]{64}|sk-[a-zA-Z0-9-_]{40,})', val)
                                if match:
                                    api_key = match.group(1)
                                    self.log(f"Found API key via selector: {selector}")
                                    break
                                elif val.strip().startswith('sk-'):
                                    api_key = val.strip()
                                    self.log(f"Found API key via selector: {selector}")
                                    break
                        except Exception:
                            continue
                    if api_key:
                        break
                except Exception:
                    continue

            # Method 2: Regex on full page content
            if not api_key:
                content = page.content()
                for pattern in [r'(sk-or-v1-[a-zA-Z0-9]{64})', r'(sk-[a-zA-Z0-9-_]{40,})', r'"(sk-or-[^"]+)"']:
                    match = re.search(pattern, content)
                    if match:
                        api_key = match.group(1)
                        self.log(f"Found API key in page content via regex: {pattern}")
                        break

            if not api_key:
                self.log("Warning: Could not extract API key automatically")
                page.screenshot(path="openrouter_no_key.png")
                with open("openrouter_no_key.html", "w", encoding="utf-8") as f:
                    f.write(page.content())
                return False, {"error": "Failed to extract API key. Check openrouter_no_key.png/html"}

            self.log(f"Successfully generated API key: {api_key[:20]}...")

            # Step 7: Save API key to file
            self._save_api_key(email, api_key)

            return True, {
                "email": email,
                "password": password,
                "api_key": api_key,
                "first_name": first_name,
                "last_name": last_name,
            }

        except Exception as e:
            self.log(f"Error during registration: {e}")
            if page:
                try:
                    page.screenshot(path="openrouter_error.png")
                    self.log("Screenshot saved as openrouter_error.png")
                    with open("openrouter_error.html", "w", encoding="utf-8") as f:
                        f.write(page.content())
                except:
                    pass
            return False, {"error": str(e)}
        finally:
            self._close_browser()

    def _save_api_key(self, email: str, api_key: str):
        """Save API key to openrouter_keys.txt file"""
        try:
            import os
            file_path = os.path.join(os.getcwd(), "openrouter_keys.txt")
            with open(file_path, "a", encoding="utf-8") as f:
                f.write(f"{email}:{api_key}\n")
            self.log(f"API key saved to {file_path}")
        except Exception as e:
            self.log(f"Failed to save API key to file: {e}")
