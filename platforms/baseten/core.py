"""
Baseten Automatic registration with API key generation

Process:
  1. Navigate to signup page (app.baseten.co/signup -> login.baseten.co/sign-up)
  2. Enter email and click Continue
  3. Verify email with 6-digit OTP code
  4. Complete any onboarding steps
  5. Navigate to Settings > API Keys (app.baseten.co/settings/api_keys)
  6. Create API key and extract it
"""

import re
import os
import time
import random
import string
import tempfile
import shutil
import socket
import subprocess
from typing import Optional, Tuple, Callable
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout, Page
from core.browser_runtime import ensure_browser_display_available, resolve_browser_headless
from core.proxy_utils import build_playwright_proxy_config, resolve_us_profile

BASETEN_BASE = "https://app.baseten.co"
BASETEN_SIGNUP = f"{BASETEN_BASE}/signup"
BASETEN_API_KEYS = f"{BASETEN_BASE}/settings/api_keys"


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


class BasetenRegister:
    def __init__(self, proxy: str = None, headless: bool = True, cdp_endpoint: str = None, use_real_chrome: bool = True):
        self.proxy = proxy
        self.headless = headless
        self.cdp_endpoint = cdp_endpoint
        self.use_real_chrome = use_real_chrome
        self.pw = None
        self.browser = None
        self.context = None
        self._chrome_proc = None
        self._cdp_port = None
        self._using_real_chrome = False
        self._chrome_profile = None

    def log(self, msg):
        safe = str(msg).encode("ascii", "replace").decode("ascii")
        print(f"[Baseten] {safe}")

    def _human_sleep(self, min_sec: float = 0.5, max_sec: float = 1.5):
        time.sleep(random.uniform(min_sec, max_sec))

    @staticmethod
    def _find_chrome_path() -> str:
        """Locate a system Chrome/Edge binary."""
        candidates = []
        if os.name == "nt":
            for p in [
                r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
                r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
            ]:
                candidates.append(p)
        else:
            for name in ["google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "microsoft-edge"]:
                p = shutil.which(name)
                if p:
                    candidates.append(p)
        for c in candidates:
            if os.path.isfile(c):
                return c
        return ""

    def _launch_real_chrome(self) -> str:
        """Launch a real Chrome with --remote-debugging-port and return the CDP endpoint."""
        import urllib.request as _urlreq

        chrome_path = self._find_chrome_path()
        if not chrome_path:
            return ""

        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()

        profile_dir = tempfile.mkdtemp(prefix="baseten-chrome-")

        args = [
            chrome_path,
            f"--remote-debugging-port={port}",
            f"--user-data-dir={profile_dir}",
            "--no-first-run",
            "--disable-sync",
            "--disable-blink-features=AutomationControlled",
            "--no-default-browser-check",
            "--window-size=1280,800",
        ]
        if self.headless:
            args.append("--headless=new")
        if self.proxy:
            args.append(f"--proxy-server={self.proxy}")
        args.append("about:blank")

        self._chrome_proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self._cdp_port = port
        self._chrome_profile = profile_dir

        endpoint = f"http://127.0.0.1:{port}"
        for _ in range(30):
            try:
                _urlreq.urlopen(f"{endpoint}/json/version", timeout=2)
                return endpoint
            except Exception:
                if self._chrome_proc.poll() is not None:
                    break
                time.sleep(0.5)
        return ""

    def _init_browser(self):
        self.pw = sync_playwright().start()
        us_loc = resolve_us_profile(self.proxy)

        endpoint = self.cdp_endpoint
        if not endpoint and self.use_real_chrome:
            endpoint = self._launch_real_chrome()
            if endpoint:
                self.log(f"Launched real Chrome on {endpoint}")

        if endpoint:
            self.log(f"Connecting to real Chrome via CDP: {endpoint}")
            self.browser = self.pw.chromium.connect_over_cdp(endpoint)
            existing = self.browser.contexts
            if existing:
                self.context = existing[0]
            else:
                self.context = self.browser.new_context()
            self._using_real_chrome = True
            self.log("Connected to real Chrome via CDP (less detectable)")
            return

        headless, reason = resolve_browser_headless(self.headless, default_headless=True)
        ensure_browser_display_available(headless)

        launch_opts = {
            "headless": headless,
            "args": ["--disable-blink-features=AutomationControlled", "--no-sandbox"],
        }
        if self.proxy:
            proxy_cfg = build_playwright_proxy_config(self.proxy)
            if proxy_cfg:
                launch_opts["proxy"] = proxy_cfg

        self.browser = self.pw.chromium.launch(**launch_opts)
        self.context = self.browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            locale=us_loc["locale"],
            timezone_id=us_loc["timezone"],
            geolocation={"latitude": us_loc["latitude"], "longitude": us_loc["longitude"]},
            permissions=["geolocation"],
        )
        self.log(f"Browser mode: {'headless' if headless else 'headed'} ({reason})")

    def _close_browser(self):
        if self.cdp_endpoint or self._chrome_proc:
            if self.pw:
                try:
                    self.pw.stop()
                except Exception:
                    pass
            if self._chrome_proc:
                try:
                    self._chrome_proc.terminate()
                    self._chrome_proc.wait(timeout=5)
                except Exception:
                    try:
                        self._chrome_proc.kill()
                    except Exception:
                        pass
                self._chrome_proc = None
            if self._chrome_profile:
                try:
                    shutil.rmtree(self._chrome_profile, ignore_errors=True)
                except Exception:
                    pass
                self._chrome_profile = None
            return
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

    def _log_page_state(self, page: Page, label: str = ""):
        try:
            url = page.url
            body = ""
            try:
                body = page.locator("body").inner_text(timeout=2000)[:400]
            except Exception:
                pass
            self.log(f"Page state{' (' + label + ')' if label else ''}: url={url} body={body!r}")
        except Exception:
            pass

    def _complete_onboarding(self, page: Page, max_steps: int = 8):
        """Walk through Baseten new-account onboarding screens."""
        for step in range(max_steps):
            curr_url = page.url
            # If we're already on the dashboard or settings, we're done
            if any(path in curr_url for path in ["/models", "/settings", "/deployments", "/dashboard"]):
                self.log(f"Onboarding complete (url={curr_url})")
                return

            self.log(f"Onboarding step {step + 1} (url={curr_url})")

            # Fill any visible text inputs (name, org, team, etc.)
            try:
                for inp in page.locator('input[type="text"], input:not([type])').all():
                    try:
                        if inp.is_visible():
                            ph = (inp.get_attribute("placeholder") or "").lower()
                            name_attr = (inp.get_attribute("name") or "").lower()
                            label_text = ""
                            try:
                                # Try to find associated label
                                inp_id = inp.get_attribute("id") or ""
                                if inp_id:
                                    label_el = page.locator(f'label[for="{inp_id}"]')
                                    if label_el.count() > 0:
                                        label_text = label_el.inner_text(timeout=1000).lower()
                            except Exception:
                                pass

                            combined = f"{ph} {name_attr} {label_text}"
                            if "first" in combined and "name" in combined:
                                inp.fill("Alex")
                            elif "last" in combined and "name" in combined:
                                inp.fill("Morgan")
                            elif "name" in combined:
                                inp.fill("Alex Morgan")
                            elif "org" in combined or "company" in combined or "team" in combined or "workspace" in combined:
                                inp.fill("AutoDev")
                            elif not inp.input_value():
                                inp.fill("AutoDev")
                    except Exception:
                        pass
            except Exception:
                pass

            # Check any terms/consent checkboxes
            try:
                for cb in page.locator('input[type="checkbox"]').all():
                    try:
                        if cb.is_visible() and not cb.is_checked():
                            cb.check()
                    except Exception:
                        pass
            except Exception:
                pass

            # Select any radio buttons (e.g., use case selection)
            try:
                radios = page.locator('input[type="radio"]').all()
                if radios:
                    # Click the first visible radio
                    for radio in radios:
                        try:
                            if radio.is_visible() and not radio.is_checked():
                                radio.check()
                                break
                        except Exception:
                            pass
            except Exception:
                pass

            # Handle dropdown selects
            try:
                for sel in page.locator("select").all():
                    try:
                        if sel.is_visible():
                            options = sel.locator("option").all()
                            if len(options) > 1:
                                sel.select_option(index=1)
                    except Exception:
                        pass
            except Exception:
                pass

            # Click the primary action button to advance
            advanced = False
            for btn_sel in [
                'button:has-text("Continue")',
                'button:has-text("Next")',
                'button:has-text("Get Started")',
                'button:has-text("Agree")',
                'button:has-text("Accept")',
                'button:has-text("Finish")',
                'button:has-text("Complete")',
                'button:has-text("Submit")',
                'button:has-text("Start")',
                'button:has-text("Skip")',
                'button:has-text("Create")',
                'button:has-text("Done")',
                'button[type="submit"]',
            ]:
                try:
                    btn = page.locator(btn_sel).first
                    if btn.count() > 0 and btn.is_visible() and not btn.is_disabled():
                        self.log(f"  Clicking onboarding button: {btn_sel}")
                        btn.click()
                        advanced = True
                        break
                except Exception:
                    pass

            if not advanced:
                page.wait_for_timeout(2000)
                continue

            prev_url = curr_url
            for _ in range(8):
                self._human_sleep(0.5, 1)
                if page.url != prev_url:
                    break
            try:
                page.wait_for_load_state("networkidle", timeout=10000)
            except Exception:
                pass

    def register(
        self,
        email: str,
        password: Optional[str] = None,
        otp_callback: Optional[Callable[[], str]] = None,
    ) -> Tuple[bool, dict]:
        # Baseten uses passwordless auth, but we track a password for the account record
        if not password:
            password = _rand_password()

        page = None
        try:
            self._init_browser()
            page = self.context.new_page()

            # Clear any stale session
            try:
                self.context.clear_cookies()
            except Exception:
                pass

            # Step 1: Navigate to signup page
            self.log(f"Navigating to Baseten signup page for {email}")
            page.goto(BASETEN_SIGNUP, wait_until="domcontentloaded", timeout=30000)
            self._human_sleep(2, 4)

            # Check if the page itself shows a blocking message
            try:
                body_text = page.locator("body").inner_text(timeout=3000)
                if "access blocked" in body_text.lower() or "contact support" in body_text.lower():
                    try:
                        page.screenshot(path="baseten_otp_not_found.png", timeout=5000)
                    except Exception:
                        pass
                    raise RuntimeError(
                        f"Baseten blocked access to the signup page. "
                        f"The proxy IP may be flagged. Try a different proxy. Screenshot saved."
                    )
            except RuntimeError:
                raise
            except Exception:
                pass

            # The signup page may redirect to login.baseten.co
            # Check if we need to click "Sign up" link from the login page
            current_url = page.url
            self.log(f"Current URL after navigation: {current_url}")

            if "login.baseten.co" in current_url and "/sign-up" not in current_url:
                # We're on the login page, need to find and click "Sign up"
                self.log("On login page, looking for Sign up link...")
                signup_selectors = [
                    'a:has-text("Sign up")',
                    'a[href*="sign-up"]',
                    'button:has-text("Sign up")',
                ]
                for sel in signup_selectors:
                    try:
                        link = page.locator(sel).first
                        if link.count() > 0 and link.is_visible():
                            self.log(f"Clicking Sign up link: {sel}")
                            link.click()
                            self._human_sleep(2, 3)
                            break
                    except Exception:
                        pass

            # Wait for the email input to appear
            self.log("Waiting for email input...")
            email_selectors = [
                'input[placeholder*="email" i]',
                'input[type="email"]',
                'input[name="email"]',
                'input.rt-TextFieldInput',
            ]

            email_input_found = False
            for _ in range(15):
                for sel in email_selectors:
                    try:
                        if page.locator(sel).count() > 0 and page.locator(sel).first.is_visible():
                            email_input_found = True
                            break
                    except Exception:
                        pass
                if email_input_found:
                    break
                page.wait_for_timeout(1000)

            if not email_input_found:
                self._log_page_state(page, "email input not found")
                raise RuntimeError("Could not find email input on signup page")

            # Step 2: Fill email and submit
            self.log(f"Filling email: {email}")
            for sel in email_selectors:
                try:
                    loc = page.locator(sel).first
                    if loc.count() > 0 and loc.is_visible():
                        self._type_human(page, sel, email)
                        break
                except Exception:
                    pass

            self._human_sleep(1, 2)

            # Click Continue button
            self.log("Clicking Continue button...")
            continue_selectors = [
                'button:has-text("Continue")',
                'button:has-text("Sign up")',
                'button[type="submit"]',
            ]
            clicked = False
            for sel in continue_selectors:
                try:
                    btn = page.locator(sel).first
                    if btn.count() > 0 and btn.is_visible() and not btn.is_disabled():
                        btn.click()
                        clicked = True
                        self.log(f"Clicked: {sel}")
                        break
                except Exception:
                    pass

            if not clicked:
                page.keyboard.press("Enter")
                self.log("Pressed Enter as fallback submit")

            self._human_sleep(3, 5)

            # Check for blocking immediately after submission
            try:
                body_text = page.locator("body").inner_text(timeout=3000)
                blocked_keywords = ["access blocked", "contact support", "access denied", "suspicious", "rate limited"]
                for kw in blocked_keywords:
                    if kw in body_text.lower():
                        try:
                            page.screenshot(path="baseten_otp_not_found.png", timeout=5000)
                        except Exception:
                            pass
                        raise RuntimeError(
                            f"Baseten blocked the registration immediately after email submission "
                            f"(detected: '{kw}'). The email domain or proxy IP may be flagged. "
                            f"Try a different proxy or email provider. Screenshot saved."
                        )
            except RuntimeError:
                raise
            except Exception:
                pass

            # Step 3: Handle email verification (6-digit OTP)
            # Wait for OTP input fields or magic link screen
            self.log("Waiting for OTP verification screen...")
            otp_selectors = [
                'input.rt-TextFieldInput',  # Baseten uses Radix TextFieldInput for OTP
                'input[maxlength="1"]',
                'input[autocomplete="one-time-code"]',
                'input[name="code"]',
            ]

            code_input_found = False
            magic_link_screen = False
            blocked_detected = False
            blocked_reason = ""

            for _w in range(25):
                # Check for access blocked / error messages on the page
                try:
                    body_text = page.locator("body").inner_text(timeout=2000)
                    blocked_patterns = [
                        "access blocked",
                        "contact support",
                        "access denied",
                        "suspicious activity",
                        "please try again later",
                        "rate limited",
                        "too many requests",
                        "invalid email",
                        "email not supported",
                        "email address is not supported",
                    ]
                    for pattern in blocked_patterns:
                        if pattern in body_text.lower():
                            blocked_detected = True
                            blocked_reason = f"'{pattern}' detected in page"
                            break
                except Exception:
                    pass

                if blocked_detected:
                    self.log(f"Blocked detected: {blocked_reason}")
                    break

                # Check for OTP code input (6 individual inputs)
                for sel in otp_selectors:
                    try:
                        inputs = page.locator(sel).all()
                        visible_inputs = [inp for inp in inputs if inp.is_visible()]
                        # Baseten shows 6 individual OTP digit inputs
                        if len(visible_inputs) >= 6:
                            code_input_found = True
                            break
                    except Exception:
                        pass
                if code_input_found:
                    break

                # Check for "Check your email" text (confirmation that OTP was sent)
                try:
                    check_email_text = page.locator('text="Check your email"')
                    if check_email_text.count() > 0 and check_email_text.first.is_visible():
                        # The page shows "Check your email" which means OTP inputs should be here
                        code_input_found = True
                        break
                except Exception:
                    pass

                # Check for magic link text
                try:
                    for text in ["magic link", "verification link", "click the link"]:
                        ml = page.locator(f'text="{text}"')
                        if ml.count() > 0:
                            magic_link_screen = True
                            break
                except Exception:
                    pass
                if magic_link_screen:
                    break

                # Check if URL has changed to magic-code page
                if "magic-code" in page.url:
                    code_input_found = True
                    break

                if _w % 5 == 0:
                    self._log_page_state(page, f"waiting for verification ({_w}s)")
                page.wait_for_timeout(1000)

            if blocked_detected:
                try:
                    page.screenshot(path="baseten_otp_not_found.png", timeout=5000)
                except Exception:
                    pass
                raise RuntimeError(
                    f"Baseten blocked the registration: {blocked_reason}. "
                    f"This may be due to a flagged proxy IP or a rejected email domain. "
                    f"Try a different proxy or email provider. Screenshot saved."
                )

            if not code_input_found and not magic_link_screen:
                # Check URL one more time
                if "magic-code" in page.url:
                    code_input_found = True
                else:
                    self._log_page_state(page, "verification screen not found")
                    try:
                        page.screenshot(path="baseten_otp_not_found.png", timeout=5000)
                    except Exception:
                        pass
                    raise RuntimeError("OTP verification screen not found. Screenshot saved.")

            # Request the OTP code from the mailbox
            if not otp_callback:
                raise RuntimeError("OTP callback is required for Baseten registration (passwordless auth)")

            self.log("Requesting OTP code from mailbox...")
            otp_code = otp_callback()
            if not otp_code:
                raise RuntimeError("Failed to retrieve OTP code from mailbox")

            self.log(f"Received OTP: {otp_code}. Entering code...")

            # Enter the OTP code into the input fields
            # Baseten uses 6 individual input fields for the OTP code
            entered = False

            # Wait a moment for OTP inputs to be interactive
            self._human_sleep(0.5, 1)

            # Try to find and fill 6 individual OTP digit inputs
            for sel in otp_selectors:
                try:
                    inputs = page.locator(sel).all()
                    visible_inputs = [inp for inp in inputs if inp.is_visible()]
                    if len(visible_inputs) >= 6:
                        self.log(f"Found {len(visible_inputs)} OTP input fields")
                        for idx in range(min(6, len(otp_code))):
                            visible_inputs[idx].click()
                            visible_inputs[idx].fill(otp_code[idx])
                            self._human_sleep(0.05, 0.15)
                        entered = True
                        break
                except Exception as e:
                    self.log(f"OTP entry attempt with {sel} failed: {e}")

            # Fallback: try keyboard-typing the code directly
            if not entered:
                self.log("Fallback: typing OTP via keyboard...")
                try:
                    # Click the first visible input
                    for sel in otp_selectors:
                        loc = page.locator(sel).first
                        if loc.count() > 0 and loc.is_visible():
                            loc.click()
                            break
                    # Type each digit
                    for digit in otp_code:
                        page.keyboard.type(digit, delay=random.randint(80, 200))
                        self._human_sleep(0.05, 0.1)
                    entered = True
                except Exception as e:
                    self.log(f"Keyboard OTP entry failed: {e}")

            if not entered:
                raise RuntimeError("Could not enter OTP code")

            self._human_sleep(3, 5)

            # Wait for post-verification redirect to dashboard
            self.log("Waiting for dashboard navigation...")
            for _ in range(25):
                curr_url = page.url
                is_auth_page = (
                    "login.baseten.co" in curr_url
                    or "/sign-up" in curr_url
                    or "/sign-in" in curr_url
                    or "/magic-code" in curr_url
                )
                if "app.baseten.co" in curr_url and not is_auth_page:
                    self.log(f"Successfully authenticated. Current URL: {curr_url}")
                    break
                page.wait_for_timeout(1000)

            try:
                page.wait_for_load_state("networkidle", timeout=15000)
            except Exception:
                pass
            self._human_sleep(2, 3)

            # Complete onboarding if present
            self._complete_onboarding(page)

            # Step 4: Navigate to API Keys page
            self.log(f"Navigating to API Keys page: {BASETEN_API_KEYS}")
            try:
                page.goto(BASETEN_API_KEYS, wait_until="domcontentloaded", timeout=20000)
            except Exception:
                pass
            try:
                page.wait_for_load_state("networkidle", timeout=15000)
            except Exception:
                pass
            self._human_sleep(2, 4)

            # Verify we're on the API keys page
            curr = page.url
            self.log(f"Current URL after API keys navigation: {curr}")
            if "settings" not in curr and "api_key" not in curr:
                # Try alternative navigation via sidebar/menu
                self.log("Direct navigation may have failed, trying to find settings link...")
                for nav_sel in [
                    'a[href*="settings"]',
                    'a:has-text("Settings")',
                    'a:has-text("Account")',
                ]:
                    try:
                        link = page.locator(nav_sel).first
                        if link.count() > 0 and link.is_visible():
                            link.click()
                            self._human_sleep(1, 2)
                            break
                    except Exception:
                        pass

                # Then try to find API keys sub-navigation
                for nav_sel in [
                    'a[href*="api_key"]',
                    'a[href*="api-key"]',
                    'a:has-text("API keys")',
                    'a:has-text("API Keys")',
                ]:
                    try:
                        link = page.locator(nav_sel).first
                        if link.count() > 0 and link.is_visible():
                            link.click()
                            self._human_sleep(1, 2)
                            break
                    except Exception:
                        pass

                try:
                    page.wait_for_load_state("networkidle", timeout=10000)
                except Exception:
                    pass

            # Step 5: Create and extract API key
            self.log("Looking for existing API keys or Create button...")

            def _extract_api_key():
                """Try to extract an API key from the page."""
                # Check input/textarea elements (keys are often in readonly inputs)
                for el in page.locator('input, textarea').all():
                    try:
                        val = el.input_value()
                        if val and len(val) > 20 and not val.startswith("http"):
                            # Baseten API keys are long alphanumeric strings
                            return val
                    except Exception:
                        pass
                # Check visible text in code/span/td/div elements
                try:
                    for el in page.locator('code, span, td, div, pre, p').all():
                        try:
                            text = el.inner_text(timeout=500)
                            # Look for API key patterns - long alphanumeric strings
                            m = re.search(r'\b[A-Za-z0-9]{20,}\b', text)
                            if m:
                                key = m.group(0)
                                # Filter out common non-key strings
                                if not any(skip in key.lower() for skip in ["undefined", "function", "object"]):
                                    return key
                        except Exception:
                            pass
                except Exception:
                    pass
                return None

            api_key = _extract_api_key()

            if not api_key:
                # Generate a new key
                self.log("No existing key found; creating a new API key...")
                create_selectors = [
                    'button:has-text("Create API key")',
                    'button:has-text("Create API Key")',
                    'button:has-text("Create Key")',
                    'button:has-text("Generate API key")',
                    'button:has-text("Generate API Key")',
                    'button:has-text("New Key")',
                    'button:has-text("Add Key")',
                    'button:has-text("Create")',
                    'a:has-text("Create API key")',
                    'a:has-text("Create API Key")',
                ]

                # Set up network response listener to capture key from API response
                captured_keys = []

                def _on_resp(response):
                    try:
                        if response.ok and response.url and "api" in response.url.lower():
                            body = response.text()
                            # Look for API key patterns in JSON responses
                            # Baseten keys could be various formats
                            for m in re.finditer(r'"(?:key|api_key|token|secret)":\s*"([A-Za-z0-9_\-]{20,})"', body):
                                captured_keys.append(m.group(1))
                            # Also try to find raw key patterns
                            for m in re.finditer(r'\b[A-Za-z0-9]{30,}\b', body):
                                key = m.group(0)
                                if not any(skip in key.lower() for skip in ["undefined", "function"]):
                                    captured_keys.append(key)
                    except Exception:
                        pass

                page.on("response", _on_resp)

                create_btn = None
                for sel in create_selectors:
                    try:
                        loc = page.locator(sel).first
                        if loc.count() > 0 and loc.is_visible():
                            create_btn = loc
                            self.log(f"Found create button: {sel}")
                            break
                    except Exception:
                        pass

                if create_btn:
                    self.log("Clicking Create API key button...")
                    create_btn.click()
                    self._human_sleep(1.5, 3)

                    # Handle key naming dialog/modal
                    try:
                        dialog_input = page.locator(
                            'input[placeholder*="Key" i], '
                            'input[placeholder*="Name" i], '
                            'input[placeholder*="name" i], '
                            'input[placeholder*="Description" i], '
                            'dialog input[type="text"], '
                            '[role="dialog"] input[type="text"]'
                        ).first
                        if dialog_input.count() > 0 and dialog_input.is_visible():
                            self.log("Key naming dialog detected, entering name...")
                            dialog_input.fill("auto-key")
                            self._human_sleep(0.5, 1)
                            # Click the confirm/create button in the dialog
                            for s_sel in [
                                'dialog button:has-text("Create API key")',
                                '[role="dialog"] button:has-text("Create API key")',
                                'dialog button:has-text("Create")',
                                '[role="dialog"] button:has-text("Create")',
                                'dialog button[type="submit"]',
                                '[role="dialog"] button[type="submit"]',
                                'button:has-text("Create API key")',
                                'button:has-text("Create")',
                                'button[type="submit"]',
                            ]:
                                try:
                                    s_btn = page.locator(s_sel).first
                                    if s_btn.count() > 0 and s_btn.is_visible():
                                        s_btn.click()
                                        self.log(f"Clicked dialog confirm: {s_sel}")
                                        break
                                except Exception:
                                    pass
                    except Exception as de:
                        self.log(f"Dialog handling skipped: {de}")

                    self._human_sleep(2, 4)

                    # Try to extract the key from captured network responses first,
                    # then from the page DOM
                    for _ in range(25):
                        if captured_keys:
                            api_key = captured_keys[-1]
                            self.log("Captured API key from network response")
                            break
                        api_key = _extract_api_key()
                        if api_key:
                            self.log("Extracted API key from page DOM")
                            break
                        page.wait_for_timeout(500)

                    try:
                        page.remove_listener("response", _on_resp)
                    except Exception:
                        pass

                    # If we still don't have a key, try looking in a modal/dialog
                    if not api_key:
                        self.log("Checking for API key in modal/dialog...")
                        try:
                            # Look for copy button or revealed key text
                            for sel in [
                                'dialog code',
                                'dialog pre',
                                'dialog input[readonly]',
                                '[role="dialog"] code',
                                '[role="dialog"] pre',
                                '[role="dialog"] input[readonly]',
                                'input[readonly]',
                                '.api-key',
                                '[data-testid*="key"]',
                            ]:
                                try:
                                    el = page.locator(sel).first
                                    if el.count() > 0 and el.is_visible():
                                        val = el.input_value() if "input" in sel else el.inner_text(timeout=2000)
                                        if val and len(val) > 15:
                                            api_key = val.strip()
                                            self.log(f"Found key in {sel}")
                                            break
                                except Exception:
                                    pass
                        except Exception:
                            pass

                    # Last resort: full page HTML regex scan
                    if not api_key:
                        try:
                            html = page.content()
                            # Look for keys in JSON-like structures
                            for m in re.finditer(r'"(?:key|api_key|secret|token)":\s*"([A-Za-z0-9_\-]{20,})"', html):
                                api_key = m.group(1)
                                self.log("Extracted key from page HTML")
                                break
                        except Exception:
                            pass
                else:
                    self.log("No create-key button found on the page")
                    self._log_page_state(page, "no create key button")

            if not api_key:
                try:
                    page.screenshot(path="baseten_key_extraction_failed.png", timeout=5000)
                except Exception:
                    pass
                self._log_page_state(page, "api key extraction failed")
                raise RuntimeError("API key was not found on the page. Screenshot saved.")

            self.log(f"Extracted API Key successfully: {api_key[:12]}...")
            return True, {
                "email": email,
                "password": password,
                "api_key": api_key,
            }

        except Exception as e:
            self.log(f"Registration error: {e}")
            return False, {"error": str(e)}
        finally:
            self._close_browser()
