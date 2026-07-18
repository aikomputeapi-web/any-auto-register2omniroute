"""
Railway.com Automatic registration with API token generation for deployment

Process:
  1. Navigate to signup page at railway.com
  2. Fill email and password
  3. Submit and verify email with OTP
  4. Navigate to account tokens page
  5. Generate personal access token for deployment
"""

import os
import re
import json
import time
import random
import string
import urllib.parse
import urllib.request
from typing import Optional, Tuple, Callable
from playwright.sync_api import sync_playwright, TimeoutError, Page
from core.browser_runtime import ensure_browser_display_available, resolve_browser_headless
from core.proxy_utils import build_playwright_proxy_config, resolve_us_profile

RAILWAY_BASE = "https://railway.com"
RAILWAY_SIGNUP = f"{RAILWAY_BASE}/signup"
RAILWAY_LOGIN = f"{RAILWAY_BASE}/login"
RAILWAY_TOKENS = f"{RAILWAY_BASE}/account/tokens"


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


class RailwayRegister:
    def __init__(self, proxy: str = None, headless: bool = True, captcha_solver = None):
        self.proxy = proxy
        self.headless = headless
        self.captcha_solver = captcha_solver
        self.pw = None
        self.browser = None
        self.context = None

    def log(self, msg):
        print(f"[RAILWAY] {msg}")

    def _human_sleep(self, min_sec: float = 0.5, max_sec: float = 1.5):
        time.sleep(random.uniform(min_sec, max_sec))

    def _init_browser(self):
        import os
        import tempfile
        from core.proxy_utils import build_playwright_proxy_config, resolve_us_profile

        self.pw = sync_playwright().start()
        headless, reason = resolve_browser_headless(self.headless, default_headless=True)

        # Path to the extracted CapSolver extension
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
            "--remote-debugging-port=9223",
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
            "viewport": {"width": 1280, "height": 720},
        }
        if self.proxy:
            proxy_cfg = build_playwright_proxy_config(self.proxy)
            if proxy_cfg:
                context_opts["proxy"] = proxy_cfg

        if ext_path:
            user_data_dir = tempfile.mkdtemp(prefix="railway_playwright_")
            self.context = self.pw.chromium.launch_persistent_context(user_data_dir, headless=False, **context_opts)
            self.browser = None
            self.extension_loaded = True
            self.log(f"Browser mode: headed Chromium with CapSolver extension ({reason})")

            # Configure CapSolver extension
            self._configure_capsolver_extension()
        else:
            self.browser = self.pw.chromium.launch(headless=headless, args=launch_args)
            self.context = self.browser.new_context(**context_opts)
            self.extension_loaded = False
            self.log(f"Browser mode: {'headless' if headless else 'headed'} ({reason})")

    def _close_browser(self):
        if self.context:
            self.context.close()
        if self.browser:
            self.browser.close()
        if self.pw:
            self.pw.stop()

    def _configure_capsolver_extension(self):
        """Inject correct config into CapSolver extension via background/service worker."""
        from core.config_store import config_store
        api_key = config_store.get("capsolver_key", "")
        if not api_key:
            self.log("Warning: No capsolver_key configured, extension may not work")
            return

        config_js = """{
            apiKey: "%s",
            useCapsolver: true,
            enabledForHCaptcha: true,
            enabledForRecaptcha: true,
            enabledForRecaptchaV3: true,
            enabledForImageToText: true,
            enabledForAwsCaptcha: true,
            enabledForCloudflare: true,
            hCaptchaMode: "click",
            reCaptchaMode: "click",
            manualSolving: false,
            isInit: true,
            showSolveButton: true,
            hCaptchaRepeatTimes: 10,
            hCaptchaDelayTime: 0
        }""" % api_key

        injected = False

        # Approach 1: Use a page to navigate to the extension popup to trigger
        # the service worker, then set storage via the extension page context
        try:
            page = self.context.new_page()
            page.goto("chrome://extensions/", wait_until="domcontentloaded", timeout=5000)
            time.sleep(1)

            # Get extension ID from the extensions page via JS
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
                // Fallback: check data attribute
                for (const item of items) {
                    return item.id;  // return first extension
                }
                return null;
            }""")
            page.close()

            if ext_id:
                self.log(f"Found CapSolver extension ID: {ext_id}")
                # Navigate to extension popup page — this activates the service worker
                ext_page = self.context.new_page()
                ext_page.goto(f"chrome-extension://{ext_id}/www/index.html#/popup",
                             wait_until="domcontentloaded", timeout=5000)
                time.sleep(2)

                # Now set storage directly from the extension page context
                ext_page.evaluate("""(config) => {
                    chrome.storage.local.set({
                        config: config,
                        defaultConfig: config
                    });
                }""", {
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
                })
                ext_page.close()
                self.log(f"Injected CapSolver config via extension page (key: {api_key[:8]}...)")
                injected = True
        except Exception as e:
            self.log(f"Extension page config injection failed: {e}")

        # Approach 2: Try service_workers if page approach failed
        if not injected:
            try:
                time.sleep(2)
                workers = self.context.service_workers
                if workers:
                    sw = workers[0]
                    sw.evaluate("""(config) => {
                        chrome.storage.local.set({ config: config, defaultConfig: config });
                    }""", {
                        "apiKey": api_key,
                        "useCapsolver": True,
                        "enabledForHCaptcha": True,
                        "isInit": True,
                        "hCaptchaMode": "click",
                        "manualSolving": False,
                        "showSolveButton": True,
                    })
                    self.log(f"Injected CapSolver config via service worker (key: {api_key[:8]}...)")
                    injected = True
            except Exception as e:
                self.log(f"Service worker config injection failed: {e}")

        if not injected:
            self.log("Warning: Could not inject CapSolver config — extension may not auto-solve")

        time.sleep(1)  # Give the extension time to pick up the new config

    def _type_human(self, page: Page, selector: str, text: str):
        self._human_sleep(0.3, 0.7)
        el = page.locator(selector).first
        el.click()
        el.fill("")
        for char in text:
            page.keyboard.type(char, delay=random.randint(50, 150))
        self._human_sleep(0.2, 0.5)

    def register(
        self,
        email: str,
        password: Optional[str] = None,
        otp_callback: Optional[Callable] = None,
    ) -> Tuple[bool, dict]:
        if not password:
            password = _rand_password()

        first_name, last_name = _rand_name()
        page = None

        try:
            self._init_browser()
            page = self.context.new_page()
            page.on("console", lambda msg: self.log(f"[BROWSER CONSOLE] {msg.type}: {msg.text}"))

            # Step 1: Navigate to signup page
            self.log(f"Navigating to signup page for {email}")
            page.goto(RAILWAY_SIGNUP, wait_until="domcontentloaded", timeout=30000)
            self._human_sleep(2, 3)

            # Handle cookie consent if present
            try:
                page.add_style_tag(content="#onetrust-consent-sdk, .onetrust-pc-dark-filter, .onetrust-banner-sdk { display: none !important; }")
                cookie_buttons = [
                    '#onetrust-accept-btn-handler',
                    'button:has-text("Accept")',
                    'button:has-text("Accept All")',
                    'button[id*="accept"]',
                ]
                for btn_sel in cookie_buttons:
                    if page.locator(btn_sel).count() > 0:
                        page.locator(btn_sel).first.click(timeout=2000, force=True)
                        self._human_sleep(0.5, 1)
                        break
            except Exception as cookie_err:
                self.log(f"Cookie consent dismiss failed (non-critical): {cookie_err}")

            # Step 2: Fill signup form
            self.log(f"Filling email: {email}")
            email_input_sel = 'input[type="email"], input[name="email"], input[placeholder*="email" i]'
            page.wait_for_selector(email_input_sel, timeout=15000)
            self._type_human(page, email_input_sel, email)
            self._human_sleep(0.5, 1)

            self.log("Filling password")
            password_input_sel = 'input[type="password"], input[name="password"], input[placeholder*="password" i]'
            page.wait_for_selector(password_input_sel, timeout=10000)
            self._type_human(page, password_input_sel, password)
            self._human_sleep(0.5, 1)

            # Optional: Full name
            try:
                name_input_sel = 'input[name="name"], input[placeholder*="name" i], input[placeholder*="full name" i]'
                if page.locator(name_input_sel).count() > 0:
                    full_name = f"{first_name} {last_name}"
                    self.log(f"Filling full name: {full_name}")
                    self._type_human(page, name_input_sel, full_name)
                    self._human_sleep(0.5, 1)
            except Exception:
                pass

            # Step 3: Handle CAPTCHA if present
            try:
                self._human_sleep(2, 3)
                # Check for common CAPTCHA indicators
                captcha_indicators = [
                    'iframe[src*="hcaptcha"]',
                    'iframe[src*="recaptcha"]',
                    '.cf-browser-verification',
                    '#cf-challenge-running',
                    '.cf-challenge-running',
                    'text=/verify you are human/i',
                    'text=/I\'m not a robot/i'
                ]

                captcha_found = False
                for selector in captcha_indicators:
                    try:
                        if page.locator(selector).count() > 0:
                            captcha_found = True
                            self.log(f"CAPTCHA detected: {selector}")
                            break
                    except:
                        continue

                if captcha_found:
                    self.log("Handling CAPTCHA...")
                    solved = False

                    # Try extension solver first
                    if getattr(self, "extension_loaded", False):
                        self.log("Waiting for CapSolver extension to solve CAPTCHA...")
                        for i in range(120):  # Wait up to ~2-3 minutes
                            try:
                                # Check if CAPTCHA is solved by looking for success indicators
                                submit_btn = page.locator('button[type="submit"], button:has-text("Sign Up"), button:has-text("Create Account")').first
                                if submit_btn.count() > 0 and submit_btn.is_enabled() and not submit_btn.is_disabled():
                                    self.log("CAPTCHA appears to be solved by extension!")
                                    solved = True
                                    break
                            except:
                                pass
                            self._human_sleep(2, 3)

                    # Try API solver if extension didn't work
                    if not solved and self.captcha_solver and type(self.captcha_solver).__name__.lower() != "manualcaptcha":
                        try:
                            self.log("Trying API CAPTCHA solver...")
                            # Find site key
                            site_key = None
                            for frame in page.frames:
                                if 'hcaptcha.com' in frame.url:
                                    site_key = frame.evaluate("""() => {
                                        const el = document.querySelector('[data-sitekey]');
                                        return el ? el.getAttribute('data-sitekey') : null;
                                    }""")
                                    if site_key:
                                        break

                            if not site_key:
                                site_key = "00000000-0000-0000-0000-000000000001"  # hCaptcha dummy key

                            token = self.captcha_solver.solve_hcaptcha(page.url, site_key)
                            self.log("hCaptcha solved, injecting response token...")
                            page.evaluate("""(token) => {
                                const textarea = document.querySelector('[name="h-captcha-response"]');
                                if (textarea) {
                                    textarea.value = token;
                                    textarea.dispatchEvent(new Event('input', { bubbles: true }));
                                    textarea.dispatchEvent(new Event('change', { bubbles: true }));
                                }
                            }""", token)
                            self._human_sleep(1, 2)
                            solved = True
                        except Exception as api_err:
                            self.log(f"API CAPTCHA solver failed: {api_err}")

                    # Fallback to manual solving
                    if not solved:
                        self.log("Please solve the CAPTCHA in the browser window...")
                        for _ in range(180):  # Wait up to 3 minutes
                            try:
                                submit_btn = page.locator('button[type="submit"], button:has-text("Sign Up"), button:has-text("Create Account")').first
                                if submit_btn.count() > 0 and submit_btn.is_enabled() and not submit_btn.is_disabled():
                                    self.log("CAPTCHA solved manually!")
                                    solved = True
                                    break
                            except:
                                pass
                            self._human_sleep(2, 3)

                    if not solved:
                        self.log("Warning: CAPTCHA not solved, attempting submission anyway")
            except Exception as e:
                self.log(f"CAPTCHA handling error: {e}")

            # Step 4: Submit registration form
            self.log("Submitting registration form")
            submit_selectors = [
                'button[type="submit"]',
                'button:has-text("Sign Up")',
                'button:has-text("Create Account")',
                'button:has-text("Register")'
            ]
            submitted = False
            for selector in submit_selectors:
                try:
                    btn = page.locator(selector).first
                    if btn.count() > 0 and btn.is_visible() and btn.is_enabled():
                        btn.click()
                        self.log(f"Clicked submit button: {selector}")
                        submitted = True
                        break
                except:
                    continue

            if not submitted:
                # Fallback: press Enter on the last focused input
                self.log("Attempting form submission via Enter key")
                page.keyboard.press("Enter")

            self._human_sleep(3, 5)

            # Step 5: Handle email verification if OTP callback provided
            if otp_callback:
                self.log("Checking for email verification...")

                # Wait for verification page or redirect
                verification_indicators = [
                    'input[maxlength="1"]',  # OTP inputs
                    'input[autocomplete="one-time-code"]',
                    'input[name*="code" i]',
                    'input[id*="code" i]',
                    'text=/verification/i',
                    'text=/code/i',
                    'text=/confirm/i'
                ]

                verification_found = False
                otp_selector = None

                # Wait for verification page
                for _ in range(30):  # Wait up to 30 seconds
                    self._human_sleep(1, 2)
                    for selector in verification_indicators:
                        try:
                            if page.locator(selector).count() > 0:
                                verification_found = True
                                otp_selector = selector
                                self.log(f"Verification element found: {selector}")
                                break
                        except:
                            continue
                    if verification_found:
                        break

                if verification_found and otp_callback:
                    self.log("Waiting for OTP code...")
                    otp = otp_callback()
                    if otp:
                        self.log(f"Received OTP: {otp}")
                        self.log("Entering verification code...")

                        # Handle different OTP input formats
                        try:
                            # Check if there are 6 separate inputs
                            inputs = page.locator('input').all()
                            visible_inputs = [inp for inp in inputs if inp.is_visible()]
                            if len(visible_inputs) == 6 and all(inp.get_attribute('maxlength') == '1' for inp in visible_inputs[:6]):
                                # Individual digit inputs
                                for i, digit in enumerate(otp):
                                    if i < len(visible_inputs):
                                        visible_inputs[i].fill(digit)
                                        self._human_sleep(0.1, 0.2)
                            else:
                                # Single input
                                if otp_selector and page.locator(otp_selector).count() > 0:
                                    page.locator(otp_selector).first.fill(otp)
                                else:
                                    # Try to find any visible input
                                    for inp in visible_inputs:
                                        if inp.is_enabled():
                                            inp.fill(otp)
                                            break
                        except Exception as e:
                            self.log(f"Error entering OTP: {e}")

                        self._human_sleep(1, 2)

                        # Submit OTP
                        try:
                            submit_otp = page.locator('button:has-text("Verify"), button:has-text("Confirm"), button[type="submit"]').first
                            if submit_otp.count() > 0:
                                submit_otp.click()
                                self.log("Submitted OTP")
                                self._human_sleep(3, 5)
                        except Exception as e:
                            self.log(f"Error submitting OTP: {e}")
            else:
                self.log("No OTP callback provided, skipping email verification")

            # Step 6: Navigate to tokens page and generate token
            self.log("Navigating to tokens page")
            page.goto(RAILWAY_TOKENS, wait_until="domcontentloaded", timeout=20000)
            self._human_sleep(3, 5)

            # Handle any redirects or additional steps
            try:
                # Wait for dashboard or tokens page to load
                page.wait_for_url(lambda url: "railway.com" in url and ("account" in url or "dashboard" in url), timeout=15000)
            except:
                self.log("Continue to tokens page...")

            self._human_sleep(2, 3)

            # Look for token generation button
            self.log("Looking for token generation button")
            token_button_selectors = [
                'button:has-text("New Token")',
                'button:has-text("Generate Token")',
                'button:has-text("Create Token")',
                'button:has-text("New Personal Access Token")',
                'a:has-text("New Token")',
                '[data-testid*="new-token"]',
                '[data-testid*="generate-token"]'
            ]

            token_generated = False
            api_key = ""

            for selector in token_button_selectors:
                try:
                    if page.locator(selector).count() > 0:
                        btn = page.locator(selector).first
                        if btn.is_visible() and btn.is_enabled():
                            self.log(f"Clicking token button: {selector}")
                            btn.click()
                            self._human_sleep(2, 3)
                            token_generated = True
                            break
                except:
                    continue

            if not token_generated:
                # Try to find any button that might create a token
                self.log("Trying alternative token generation methods")
                buttons = page.locator('button').all()
                for btn in buttons:
                    try:
                        text = btn.inner_text().lower()
                        if any(keyword in text for keyword in ['new', 'generate', 'create', 'token']):
                            if btn.is_visible() and btn.is_enabled():
                                self.log(f"Clicking button: {text}")
                                btn.click()
                                self._human_sleep(2, 3)
                                token_generated = True
                                break
                    except:
                        continue

            # If still not found, try to see if there's already a token displayed
            if not token_generated:
                self.log("Checking for existing tokens...")
                # Look for token display elements
                token_selectors = [
                    '[data-testid*="token"]',
                    '.token-value',
                    '.api-key',
                    'code',
                    'pre',
                    '[class*="token"]',
                    '[class*="key"]'
                ]

                for selector in token_selectors:
                    try:
                        elements = page.locator(selector).all()
                        for el in elements:
                            try:
                                text = el.inner_text() or el.text_content() or ""
                                # Look for token-like patterns
                                if re.match(r'[rr]_[a-zA-Z0-9_\-]{20,}', text.strip()) or \
                                   re.match(r'[a-zA-Z0-9_\-]{32,}', text.strip()):
                                    api_key = text.strip()
                                    self.log(f"Found token via selector {selector}: {api_key[:20]}...")
                                    token_generated = True
                                    break
                            except:
                                continue
                        if token_generated:
                            break
                    except:
                        continue

            # Final attempt: extract token from page content
            if not api_key:
                self.log("Extracting token from page content...")
                content = page.content()
                # Look for Railway token patterns
                token_patterns = [
                    r'rr_[a-zA-Z0-9_\-]{20,}',  # Railway token pattern
                    r'[a-zA-Z0-9_\-]{32,}',     # Generic long token
                ]

                for pattern in token_patterns:
                    matches = re.findall(pattern, content)
                    for match in matches:
                        # Filter out unlikely matches
                        if len(match) >= 20 and not any(x in match.lower() for x in ['password', 'token', 'key', 'secret', 'auth', 'bearer']):
                            api_key = match
                            self.log(f"Found token via regex: {api_key[:20]}...")
                            token_generated = True
                            break
                    if token_generated:
                        break

            if api_key:
                self.log(f"API token successfully acquired: {api_key[:20]}...")
            else:
                self.log("API token NOT found. Keeping browser open for 60 seconds for manual inspection...")
                time.sleep(60)

            return True, {
                "email": email,
                "password": password,
                "token": api_key,
            }

        except Exception as e:
            self.log(f"Registration error: {e}")
            return False, {"error": str(e)}
        finally:
            self._close_browser()