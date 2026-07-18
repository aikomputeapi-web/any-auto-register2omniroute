"""
Zeabur.com Automatic registration with API token generation for deployment

Process:
  1. Navigate to login page at zeabur.com/login
  2. Enter email (triggers automatic signup for new users)
  3. Check email for magic link or OTP
  4. Complete login/signup via email verification
  5. Navigate to dashboard settings API keys
  6. Generate new API token
  7. Extract token for deployment authorization
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

ZABEUR_BASE = "https://zeabur.com"
ZABEUR_LOGIN = f"{ZABEUR_BASE}/login"
ZABEUR_DASHBOARD = f"{ZABEUR_BASE}/projects"  # Main dashboard
ZABEUR_API_KEYS = f"{ZABEUR_BASE}/settings/api-keys"  # API keys page


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


class ZeaburRegister:
    def __init__(self, proxy: str = None, headless: bool = True, captcha_solver = None):
        self.proxy = proxy
        self.headless = headless
        self.captcha_solver = captcha_solver
        self.pw = None
        self.browser = None
        self.context = None

    def log(self, msg):
        print(f"[ZEABUR] {msg}")

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
            user_data_dir = tempfile.mkdtemp(prefix="zeabur_playwright_")
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
        # Note: Zeabur doesn't use traditional password login - it uses email magic links
        # But we'll generate a password anyway for storage consistency
        if not password:
            password = _rand_password()

        first_name, last_name = _rand_name()
        page = None

        try:
            self._init_browser()
            page = self.context.new_page()
            page.on("console", lambda msg: self.log(f"[BROWSER CONSOLE] {msg.type}: {msg.text}"))

            # Step 1: Navigate to login page
            self.log(f"Navigating to login page for {email}")
            page.goto(ZABEUR_LOGIN, wait_until="domcontentloaded", timeout=30000)
            self._human_sleep(2, 3)

            # Step 2: Fill email and click "Continue with Email"
            self.log(f"Filling email: {email}")
            email_input_sel = 'input[type="email"], input[name="email"], input[placeholder*="email" i]'
            page.wait_for_selector(email_input_sel, timeout=15000)
            self._type_human(page, email_input_sel, email)
            self._human_sleep(0.5, 1)

            # Click the "Continue with Email" button
            continue_button_selectors = [
                'button:has-text("Continue with Email")',
                'button:has-text("Continue")',
                'button[type="submit"]'
            ]

            clicked = False
            for selector in continue_button_selectors:
                try:
                    btn = page.locator(selector).first
                    if btn.count() > 0 and btn.is_visible() and btn.is_enabled():
                        btn.click()
                        self.log(f"Clicked continue button: {selector}")
                        clicked = True
                        break
                except Exception as e:
                    self.log(f"Failed to click button {selector}: {e}")
                    continue

            if not clicked:
                # Fallback: press Enter
                self.log("Attempting form submission via Enter key")
                page.keyboard.press("Enter")

            self._human_sleep(2, 3)

            # Step 3: Handle terms acceptance if needed
            try:
                # Look for checkbox for terms acceptance
                terms_checkbox = page.locator('input[type="checkbox"]')
                if terms_checkbox.count() > 0:
                    # Check if it's visible and needs to be checked
                    first_checkbox = terms_checkbox.first
                    if first_checkbox.is_visible() and not first_checkbox.is_checked():
                        self.log("Checking terms and conditions checkbox")
                        first_checkbox.check()
                        self._human_sleep(0.5, 1)
            except Exception as e:
                self.log(f"Terms checkbox handling (non-critical): {e}")

            # Step 4: Wait for email verification
            # Zeabur sends a magic link to email - we need to wait for user to click it
            # or handle OTP if provided via callback
            self.log("Waiting for email verification...")

            if otp_callback:
                self.log("Using OTP callback for verification...")
                # Wait a bit for email to arrive
                self._human_sleep(3, 5)

                otp = otp_callback()
                if otp:
                    self.log(f"Received OTP: {otp}")
                    # Look for OTP input fields
                    otp_selectors = [
                        'input[inputmodem="numeric"]',
                        'input[maxlength="6"]',
                        'input[name*="code" i]',
                        'input[id*="code" i]',
                        'input[placeholder*="code" i]',
                        'input[placeholder*="verification" i]'
                    ]

                    otp_filled = False
                    for selector in otp_selectors:
                        try:
                            inputs = page.locator(selector).all()
                            visible_inputs = [inp for inp in inputs if inp.is_visible() and inp.is_enabled()]

                            if len(visible_inputs) >= 6 and all(inp.get_attribute('maxlength') == '1' for inp in visible_inputs[:6]):
                                # Individual digit inputs
                                for i, digit in enumerate(otp):
                                    if i < len(visible_inputs):
                                        visible_inputs[i].fill(digit)
                                        self._human_sleep(0.1, 0.2)
                                otp_filled = True
                                break
                            elif len(visible_inputs) >= 1:
                                # Single input field
                                visible_inputs[0].fill(otp)
                                otp_filled = True
                                break
                        except Exception as e:
                            self.log(f"Error with OTP selector {selector}: {e}")
                            continue

                    if otp_filled:
                        self.log("OTP entered successfully")
                        # Look for submit/verify button
                        verify_selectors = [
                            'button:has-text("Verify")',
                            'button:has-text("Confirm")',
                            'button:has-text("Continue")',
                            'button[type="submit"]'
                        ]
                        for selector in verify_selectors:
                            try:
                                btn = page.locator(selector).first
                                if btn.count() > 0 and btn.is_visible() and btn.is_enabled():
                                    btn.click()
                                    self.log(f"Clicked verification button: {selector}")
                                    self._human_sleep(3, 5)
                                    break
                            except Exception as e:
                                self.log(f"Error clicking verify button: {e}")
                                continue
                    else:
                        self.log("Could not find appropriate OTP input fields")
                else:
                    self.log("No OTP received")
            else:
                # No OTP callback - wait for manual email verification
                self.log("No OTP callback provided - waiting for manual email verification...")
                self.log("Please check your email and click the magic link from Zeabur")

                # Wait for redirect to dashboard or successful login
                # We'll wait up to 2 minutes for manual verification
                start_time = time.time()
                timeout = 120  # 2 minutes

                while time.time() - start_time < timeout:
                    try:
                        current_url = page.url
                        self.log(f"Current URL: {current_url}")

                        # Check if we've reached the dashboard or projects page
                        if "zeabur.com" in current_url and ("projects" in current_url or "dashboard" in current_url):
                            self.log("Successfully redirected to dashboard!")
                            break

                        # Check if we're still on login-related page
                        if "login" in current_url.lower():
                            self.log("Still on login page, waiting...")
                        else:
                            self.log("On some other page, continuing to wait...")

                    except Exception as e:
                        self.log(f"Error checking URL: {e}")

                    self._human_sleep(3, 5)

                # Additional wait to ensure we're fully logged in
                self._human_sleep(3, 5)

            # Step 5: Navigate to API keys page to generate token
            self.log("Navigating to API keys page...")
            try:
                page.goto(ZABEUR_API_KEYS, wait_until="domcontentloaded", timeout=20000)
                self._human_sleep(3, 5)
            except Exception as e:
                self.log(f"Could not navigate directly to API keys page: {e}")
                # Try to navigate via dashboard first
                try:
                    page.goto(ZABEUR_DASHBOARD, wait_until="domcontentloaded", timeout=15000)
                    self._human_sleep(2, 3)

                    # Look for navigation to settings
                    settings_selectors = [
                        'a:has-text("Settings")',
                        '[href*="settings"]',
                        'text=Settings'
                    ]
                    for selector in settings_selectors:
                        try:
                            link = page.locator(selector).first
                            if link.count() > 0 and link.is_visible():
                                link.click()
                                self.log(f"Clicked settings link: {selector}")
                                self._human_sleep(2, 3)
                                break
                        except Exception as e:
                            self.log(f"Could not click settings link {selector}: {e}")
                            continue

                    # Now look for API keys section
                    api_key_selectors = [
                        'a:has-text("API Keys")',
                        '[href*="api-key"]',
                        'text=API Keys'
                    ]
                    for selector in api_key_selectors:
                        try:
                            link = page.locator(selector).first
                            if link.count() > 0 and link.is_visible():
                                link.click()
                                self.log(f"Clicked API keys link: {selector}")
                                self._human_sleep(2, 3)
                                break
                        except Exception as e:
                            self.log(f"Could not click API keys link {selector}: {e}")
                            continue

                except Exception as e2:
                    self.log(f"Alternative navigation also failed: {e2}")

            self._human_solid_sleep(2, 3)

            # Step 6: Generate new API token
            self.log("Looking for API token generation button...")

            generate_button_selectors = [
                'button:has-text("Generate API Key")',
                'button:has-text("Create API Key")',
                'button:has-text("New Token")',
                'button:has-text("Generate Token")',
                'button:has-text("Add Key")',
                'button:has-text("Create Key")'
            ]

            token_generated = False
            api_key = ""

            for selector in generate_button_selectors:
                try:
                    btn = page.locator(selector).first
                    if btn.count() > 0 and btn.is_visible() and btn.is_enabled():
                        btn.click()
                        self.log(f"Clicked generate button: {selector}")
                        self._human_sleep(3, 5)
                        token_generated = True
                        break
                except Exception as e:
                    self.log(f"Error clicking generate button {selector}: {e}")
                    continue

            if not token_generated:
                # Try to find any button that might create a key
                self.log("Trying to find any button that could create an API key...")
                buttons = page.locator('button').all()
                for btn in buttons:
                    try:
                        text = btn.inner_text().lower()
                        if any(keyword in text for keyword in ['generate', 'create', 'new', 'add']) and \
                           any(keyword in text for keyword in ['key', 'token']):
                            if btn.is_visible() and btn.is_enabled():
                                btn.click()
                                self.log(f"Clicked button with text: {text}")
                                self._human_sleep(3, 5)
                                token_generated = True
                                break
                    except Exception as e:
                        continue

            # Step 7: Extract the generated API token
            self.log("Extracting API token from page...")

            # Wait a bit for token to appear
            self._human_sleep(2, 3)

            # Look for token display elements
            token_selectors = [
                '[data-testid*="api-key"]',
                '[data-testid*="token"]',
                '.api-key-value',
                '.token-value',
                'code',
                'pre',
                '[class*="key"]',
                '[class*="token"]',
                '.font-mono'  # Often used for displaying codes/tokens
            ]

            token_found = False
            for selector in token_selectors:
                try:
                    elements = page.locator(selector).all()
                    for el in elements:
                        try:
                            text = el.inner_text() or el.text_content() or ""
                            text = text.strip()

                            # Skip empty text or UI labels
                            if not text or len(text) < 10:
                                continue

                            # Look for token-like patterns
                            # Zeabur tokens typically look like: ztau_... or similar patterns
                            if (re.match(r'[zt][a-zA-Z0-9_-]{20,}', text) or
                                re.match(r'[a-zA-Z0-9_-]{32,}', text) or
                                'ztau_' in text.lower()):

                                # Additional filtering to avoid false positives
                                if not any(word in text.lower() for word in ['button', 'click', 'here', 'label', 'title']):
                                    api_key = text
                                    self.log(f"Found API token via selector '{selector}': {api_key[:20]}...")
                                    token_found = True
                                    break
                        except Exception as e:
                            continue
                    if token_found:
                        break
                except Exception as e:
                    self.log(f"Error with token selector {selector}: {e}")
                    continue

            # Fallback: extract from page content using regex
            if not token_found:
                self.log("Trying to extract token from page content using regex...")
                try:
                    content = page.content()

                    # Common token patterns
                    patterns = [
                        r'ztau_[a-zA-Z0-9_-]{20,}',  # Likely Zeabur pattern
                        r'[a-zA-Z0-9_-]{32,}',        # Generic long token
                        r'[a-zA-Z0-9_-]{40,}',        # Even longer token
                        r'Bearer\s+[a-zA-Z0-9_-]+',   # Bearer token format
                    ]

                    for pattern in patterns:
                        matches = re.findall(pattern, content)
                        for match in matches:
                            # Clean up the match
                            clean_match = re.sub(r'Bearer\s+', '', match)
                            clean_match = clean_match.strip()

                            if len(clean_match) >= 20 and \
                               not any(word in clean_match.lower() for word in ['button', 'click', 'here', 'label', 'title', 'the', 'and', 'for', 'with']):
                                api_key = clean_match
                                self.log(f"Found API token via regex pattern '{pattern}': {api_key[:20]}...")
                                token_found = True
                                break
                        if token_found:
                            break

                except Exception as e:
                    self.log(f"Error extracting token from page content: {e}")

            if api_key:
                self.log(f"API token successfully acquired: {api_key[:20]}...")
            else:
                self.log("API token NOT found. Keeping browser open for 30 seconds for manual inspection...")
                time.sleep(30)

            return True, {
                "email": email,
                "password": password,  # Stored for consistency, though not used for Zeabur login
                "token": api_key,
            }

        except Exception as e:
            self.log(f"Registration error: {e}")
            import traceback
            self.log(f"Full traceback: {traceback.format_exc()}")
            return False, {"error": str(e)}
        finally:
            self._close_browser()