"""
NVIDIA NIM Automatic registration with API key generation

Process:
  1. Navigate to signup page at build.nvidia.com
  2. Fill email and password
  3. Submit and verify email with OTP
  4. Navigate to API keys page
  5. Generate API key
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

NVIDIA_BASE = "https://build.nvidia.com"
NVIDIA_SIGNUP = f"{NVIDIA_BASE}/?modal=signin"
NVIDIA_SIGNIN = f"{NVIDIA_BASE}/signin"
NVIDIA_API = f"{NVIDIA_BASE}/settings/api-keys"


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


class NvidiaNimRegister:
    def __init__(self, proxy: str = None, headless: bool = True, captcha_solver = None):
        self.proxy = proxy
        self.headless = headless
        self.captcha_solver = captcha_solver
        self.pw = None
        self.browser = None
        self.context = None

    def log(self, msg):
        print(f"[NVIDIA NIM] {msg}")

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
            user_data_dir = tempfile.mkdtemp(prefix="nvidia_playwright_")
            self.context = self.pw.chromium.launch_persistent_context(user_data_dir, headless=False, **context_opts)
            self.browser = None
            self.extension_loaded = True
            self.log(f"Browser mode: headed Chromium with CapSolver extension ({reason})")
            
            # Inject config into extension via service worker.
            # The extension's config parser has a type mismatch bug: isInit stays
            # as string "true" but the default is boolean false, so the type-check
            # merge never overrides it — the solve loop never starts.
            # Fix: set the config directly in chrome.storage.local.
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
            # First, find the extension ID by checking installed extensions
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
            page.goto(NVIDIA_SIGNUP, wait_until="domcontentloaded", timeout=30000)
            self._human_sleep(2, 3)

            # Dismiss cookie consent if present or hide it completely
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

            # Step 2: Fill signup/signin email modal
            self.log(f"Filling signin email input: {email}")
            
            email_input_sel = 'input[placeholder="Enter your email ID"]'
            page.wait_for_selector(email_input_sel, timeout=15000)
            self._type_human(page, email_input_sel, email)
            self._human_sleep(0.5, 1)
            
            # Find and click the visible Next button
            next_btns = page.locator('button:has-text("Next")')
            clicked_next = False
            for i in range(next_btns.count()):
                btn = next_btns.nth(i)
                if btn.is_visible():
                    btn.click(force=True)
                    clicked_next = True
                    break
            if not clicked_next:
                next_btns.first.click(force=True)
            self.log("Clicked Next, waiting for redirection to account setup...")
            
            # Wait for redirection to account setup by waiting for password field
            try:
                page.wait_for_selector('#registration_password', timeout=25000)
            except Exception as e:
                raise RuntimeError(f"Redirection timed out or invalid page: {e}")
            
            if page.locator('#registration_passwordConfirm').count() == 0:
                raise RuntimeError("Email is already registered (redirected to login page)")
            
            self.log("Filling password fields...")
            self._type_human(page, '#registration_password', password)
            self._type_human(page, '#registration_passwordConfirm', password)
            
            # Stay logged in / terms
            try:
                terms_checkbox = page.locator('#terms_and_conditions-input')
                if terms_checkbox.count() > 0:
                    terms_checkbox.first.check(force=True)
                    self._human_sleep(0.3, 0.6)
            except Exception as terms_err:
                self.log(f"Terms checkbox interaction failed (non-critical): {terms_err}")

            # Solve hCaptcha if present
            try:
                self._human_sleep(2, 3)  # Wait for hCaptcha to fully load
                hcaptcha_iframe = page.locator('iframe[src*="hcaptcha"]').first
                if hcaptcha_iframe.count() > 0 and hcaptcha_iframe.is_visible():
                    solved = False
                    
                    # Click the hCaptcha checkbox to trigger the challenge.
                    # The extension's content script should handle it, but we help
                    # by clicking the checkbox from Playwright to ensure it opens.
                    try:
                        checkbox_frame = page.frame_locator('iframe[src*="hcaptcha"]').first
                        if checkbox_frame:
                            checkbox = checkbox_frame.locator('#checkbox')
                            if checkbox.count() > 0:
                                self.log("Clicking hCaptcha checkbox to trigger challenge...")
                                checkbox.click(timeout=5000, force=True)
                                self._human_sleep(2, 3)
                    except Exception as cb_err:
                        self.log(f"Could not click hCaptcha checkbox: {cb_err}")
                    
                    # 1. Wait for extension to solve (it uses image classification API)
                    if getattr(self, "extension_loaded", False):
                        self.log("hCaptcha challenge opened, waiting for CapSolver extension to solve...")
                        for i in range(90):  # Wait up to ~90-135 seconds
                            btn = page.locator('#register_button').first
                            if btn.count() > 0 and btn.is_enabled():
                                self.log(f"hCaptcha solved by CapSolver extension! (took ~{i}s)")
                                solved = True
                                break
                            if i > 0 and i % 15 == 0:
                                self.log(f"Still waiting for extension to solve... ({i}s)")
                            self._human_sleep(1, 1.5)
                            
                    # 2. Try API solver if not solved yet and solver exists
                    if not solved and self.captcha_solver and type(self.captcha_solver).__name__.lower() != "manualcaptcha":
                        try:
                            self.log("Extension didn't solve, trying API solver...")
                            site_key = "3443d8f6-da7a-4326-929f-4d7fc89ab0d1"  # default fallback
                            src = hcaptcha_iframe.get_attribute("src")
                            if src:
                                parsed = urllib.parse.urlparse(src)
                                params = urllib.parse.parse_qs(parsed.fragment or parsed.query)
                                if "sitekey" in params:
                                    site_key = params["sitekey"][0]
                            
                            self.log(f"Sitekey: {site_key}. Solving hCaptcha via API...")
                            token = self.captcha_solver.solve_hcaptcha(page.url, site_key)
                            self.log("hCaptcha solved, injecting response token...")
                            page.evaluate("""(token) => {
                                document.querySelectorAll('textarea[name="h-captcha-response"], textarea[name="g-recaptcha-response"]').forEach(ta => {
                                    ta.value = token;
                                    ta.dispatchEvent(new Event('input', { bubbles: true }));
                                    ta.dispatchEvent(new Event('change', { bubbles: true }));
                                });
                                if (window.___hcaptcha_widget_settings) {
                                    for (const widgetId in window.___hcaptcha_widget_settings) {
                                        const widget = window.___hcaptcha_widget_settings[widgetId];
                                        if (widget && typeof widget.callback === 'function') {
                                            widget.callback(token);
                                        }
                                    }
                                }
                            }""", token)
                            self._human_sleep(1, 2)
                            solved = True
                        except Exception as api_err:
                            self.log(f"API Captcha solver failed: {api_err}")
                            
                    # 3. Fallback to manual solving in headed mode
                    if not solved:
                        self.log("Please solve the hCaptcha challenge in the browser window...")
                        for _ in range(180):  # Wait up to 3 minutes
                            btn = page.locator('#register_button').first
                            if btn.count() > 0 and btn.is_enabled():
                                self.log("hCaptcha solved manually!")
                                solved = True
                                break
                            self._human_sleep(1, 1.5)
                            
                    if not solved:
                        self.log("Warning: hCaptcha not solved, attempting submission anyway")
            except Exception as e:
                self.log(f"Error handling hCaptcha: {e}")
            
            # Click "Create Account"
            self.log("Submitting account creation form")
            register_btn = page.locator('#register_button').first
            register_btn.click()
            self._human_sleep(2, 3)
            
            # Wait for verification screen to appear — try explicit selector wait first
            self.log("Waiting for verification screen to appear...")
            for _vsel in ['input[maxlength="1"]', 'input[autocomplete="one-time-code"]',
                          'input#verificationCode', 'input[name="verificationCode"]']:
                try:
                    page.wait_for_selector(_vsel, timeout=8000)
                    self.log(f"Verification screen detected early via: {_vsel}")
                    break
                except Exception:
                    pass
            self._human_sleep(1, 2)

            # Confirm current state
            self.log("Checking if verification screen appeared...")
            self.log(f"Current URL: {page.url}")
            self.log(f"Page title: {page.title()}")
            
            verification_screen_found = False
            otp_input_selector = None
            
            # Try multiple selectors for the verification code input
            verification_selectors = [
                'input#verificationCode',
                'input#verification_code',
                'input#code',
                'input[name="code"]',
                'input[name="verificationCode"]',
                'input[name="verification_code"]',
                'input[placeholder*="code" i]',
                'input[placeholder*="verification" i]',
                'input[type="text"][maxlength="6"]',
                'input[type="tel"][maxlength="6"]',
                'input[autocomplete="one-time-code"]',
                'input[inputmode="numeric"]',
                'input[maxlength="1"]',
                'input[id*="code" i]',
                'input[name*="code" i]',
                'input[class*="code" i]',
                'input[class*="otp" i]',
            ]
            
            # First, wait a bit for the page to settle
            self._human_sleep(2, 3)
            
            # Try to find any input on the page
            all_inputs = page.locator('input').all()
            self.log(f"Found {len(all_inputs)} input elements on page")
            
            for sel in verification_selectors:
                try:
                    count = page.locator(sel).count()
                    if count > 0:
                        otp_input_selector = sel
                        verification_screen_found = True
                        self.log(f"Verification input found: {sel}")
                        break
                    else:
                        self.log(f"Selector not found: {sel}")
                except Exception as e:
                    self.log(f"Error checking selector {sel}: {e}")
            
            if not verification_screen_found:
                # Try waiting with a longer timeout
                self.log("No immediate match, waiting up to 15 seconds for verification input...")
                for sel in verification_selectors:
                    try:
                        page.wait_for_selector(sel, timeout=15000)
                        if page.locator(sel).count() > 0:
                            otp_input_selector = sel
                            verification_screen_found = True
                            self.log(f"Verification input appeared: {sel}")
                            break
                    except Exception:
                        continue
            
            if not verification_screen_found:
                self.log("Warning: No verification input detected after all attempts")
                # Save screenshot for debugging
                try:
                    page.screenshot(path="nvidia_verification_screen.png")
                    self.log("Saved screenshot: nvidia_verification_screen.png")
                except Exception as ss_err:
                    self.log(f"Could not save verification screenshot: {ss_err}")

            # Step 3: Handle email verification if OTP callback provided
            api_key = ""
            if otp_callback:
                self.log("Waiting for OTP code...")
                # If verification screen wasn't found yet, wait extra before requesting OTP
                if not verification_screen_found:
                    self.log("Verification screen not found yet — waiting an extra 10 s before requesting OTP...")
                    self._human_sleep(8, 12)
                    # Re-scan for input after extended wait
                    for sel in verification_selectors:
                        try:
                            if page.locator(sel).count() > 0:
                                otp_input_selector = sel
                                verification_screen_found = True
                                self.log(f"Verification input found after extended wait: {sel}")
                                break
                        except Exception:
                            continue
                otp = otp_callback()
                if otp:
                    self.log(f"Received OTP: {otp}")
                    self.log("Entering verification code...")
                    
                    # Check if there are 6 separate digit inputs
                    digit_inputs = []
                    try:
                        all_inputs = page.locator('input').all()
                        visible_text_inputs = []
                        for inp in all_inputs:
                            if inp.is_visible():
                                inp_type = inp.get_attribute('type') or 'text'
                                if inp_type in ['text', 'tel', 'number', 'password']:
                                    visible_text_inputs.append(inp)
                        if len(visible_text_inputs) == 6:
                            digit_inputs = visible_text_inputs
                            self.log("Detected exactly 6 visible text inputs, likely individual OTP digit inputs.")
                    except Exception as detect_err:
                        self.log(f"Error checking for 6 digit inputs: {detect_err}")

                    otp_input_found = False
                    if digit_inputs:
                        try:
                            # Focus first and enter code digit by digit
                            self.log("Entering OTP digit by digit...")
                            for idx, digit in enumerate(otp):
                                digit_inputs[idx].click()
                                self._human_sleep(0.1, 0.2)
                                digit_inputs[idx].fill(digit)
                            otp_input_found = True
                            self.log(f"Successfully entered 6-digit OTP: {otp}")
                        except Exception as e:
                            self.log(f"Digit-by-digit entry failed: {e}. Trying fallback...")

                    if not otp_input_found:
                        # Use the selector we found earlier, or try all selectors
                        input_element = None
                        if otp_input_selector and page.locator(otp_input_selector).count() > 0:
                            input_element = page.locator(otp_input_selector).first
                            otp_input_found = True
                            self.log(f"Using pre-found selector: {otp_input_selector}")
                        else:
                            # Try all selectors if the one we found earlier is gone
                            for sel in verification_selectors:
                                if page.locator(sel).count() > 0:
                                    input_element = page.locator(sel).first
                                    otp_input_found = True
                                    self.log(f"Found verification input: {sel}")
                                    break
                        
                        if otp_input_found and input_element:
                            # Clear and fill the input directly (faster and more reliable)
                            try:
                                input_element.click()
                                self._human_sleep(0.2, 0.4)
                                input_element.fill(otp)
                                self.log(f"Entered OTP: {otp}")
                                self._human_sleep(0.5, 1)
                            except Exception as e:
                                self.log(f"Fill method failed, trying keyboard input: {e}")
                                # Fallback to keyboard typing
                                input_element.click()
                                page.keyboard.press("Control+A")
                                page.keyboard.press("Backspace")
                                page.keyboard.type(otp, delay=100)
                                self._human_sleep(0.5, 1)
                    
                    # Submit OTP
                    submit_otp_selectors = [
                        'button#verify_button',
                        'button:has-text("Verify")',
                        'button[type="submit"]',
                        'button:has-text("Continue")',
                    ]
                    for sel in submit_otp_selectors:
                        if page.locator(sel).count() > 0:
                            submit_btn = page.locator(sel).first
                            if submit_btn.is_visible():
                                self.log(f"Clicking verification submit button: {sel}")
                                submit_btn.click()
                                break
                    # Wait for page to settle after OTP submit; check the URL transitions
                    self.log("OTP submitted — waiting for post-OTP redirect...")
                    try:
                        page.wait_for_url(
                            lambda url: "build.nvidia.com" in url or 
                                        "cloudaccounts.nvidia.com" in url or 
                                        "consent" in url or 
                                        "static-login.nvidia.com" in url, 
                            timeout=20000
                        )
                        self.log(f"Post-OTP URL: {page.url}")
                    except Exception:
                        self._human_sleep(2, 3)
            
            # Step 3.5: Handle redirections (Consent, Cloud Account, or Login) dynamically
            try:
                self.log("Handling post-verification flow (Consent, Cloud Account, Login)...")
                start_time = time.time()
                while time.time() - start_time < 90:  # 90 seconds timeout
                    self._human_sleep(1, 2)
                    url = page.url
                    self.log(f"Current URL in post-verification loop: {url}")
                    
                    # 1. Consent Page
                    if "consent" in url or "static-login.nvidia.com" in url:
                        self.log("Consent page detected. Clicking Submit...")
                        page.screenshot(path="scratch/consent_page_auto.png")
                        try:
                            # Check all checkboxes on the consent page
                            checkbox_locators = [
                                'input[type="checkbox"]',
                                'span.checkbox',
                                '.checkbox-label',
                                'label[for*="recommend" i]',
                                'label[for*="news" i]',
                            ]
                            checked_any = False
                            for sel in checkbox_locators:
                                locs = page.locator(sel).all()
                                if locs:
                                    for el in locs:
                                        try:
                                            if el.is_visible() and not el.is_checked():
                                                el.click(force=True)
                                                checked_any = True
                                                self._human_sleep(0.2, 0.4)
                                        except Exception:
                                            pass
                            if checked_any:
                                self.log("Checked consent options.")
                        except Exception as cb_err:
                            self.log(f"Failed to check consent checkboxes: {cb_err}")

                        submit_btn_loc = page.locator('button.button-cta:has-text("Submit"), button[type="submit"]:has-text("Submit")')
                        if submit_btn_loc.count() > 0:
                            submit_btn_loc.first.click(force=True)
                            self.log("Clicked consent Submit.")
                        self._human_sleep(2, 4)
                        continue

                    # 2. Cloud Account Setup Page
                    elif "cloudaccounts.nvidia.com" in url or "select-account" in url:
                        self.log("Cloud account setup page detected.")
                        page.screenshot(path="scratch/cloud_account_auto.png")
                        try:
                            with open("scratch/after_consent_submit.html", "w", encoding="utf-8") as f:
                                f.write(page.content())
                        except Exception:
                            pass
                            
                        # Generate random cloud account name based on email
                        local_part = email.split('@')[0]
                        org_name = "org-" + local_part[:10] + "".join(random.choices(string.digits, k=4))
                        self.log(f"Entering Cloud Account Name: {org_name}")
                        
                        input_sel = 'input[data-testid="kui-text-input-element"], input[name="name"], input[placeholder*="OrganizationName"]'
                        if page.locator(input_sel).count() > 0:
                            page.locator(input_sel).first.fill(org_name)
                            self._human_sleep(0.5, 1)
                            
                        create_btn_loc = page.locator('button:has-text("Create NVIDIA Cloud Account"), button[data-testid="kui-button"]:has-text("Create")')
                        if create_btn_loc.count() > 0:
                            create_btn_loc.first.click(force=True)
                            self.log("Clicked Create NVIDIA Cloud Account button.")
                        self._human_sleep(3, 5)
                        continue

                    # 3. Login Page (only if we actually see the input field or it's a login URL and we're not automatically redirecting)
                    elif "login" in url and page.locator('input[placeholder="Enter your email ID"]').count() > 0:
                        self.log("Login page with email input detected. Logging in...")
                        email_input_sel = 'input[placeholder="Enter your email ID"]'
                        self._type_human(page, email_input_sel, email)
                        self._human_sleep(0.5, 1)
                        
                        next_btns = page.locator('button:has-text("Next")')
                        clicked_next = False
                        for i in range(next_btns.count()):
                            btn = next_btns.nth(i)
                            if btn.is_visible():
                                btn.click(force=True)
                                clicked_next = True
                                break
                        if not clicked_next:
                            next_btns.first.click(force=True)
                            
                        self.log("Waiting for password field on login...")
                        password_sel = 'input[type="password"]'
                        page.wait_for_selector(password_sel, timeout=20000)
                        
                        self._type_human(page, password_sel, password)
                        self._human_sleep(0.5, 1)
                        
                        login_btn_selectors = [
                            'button#login-btn',
                            'button:has-text("Log In")',
                            'button:has-text("Sign In")',
                            'button[type="submit"]',
                        ]
                        for sel in login_btn_selectors:
                            if page.locator(sel).count() > 0:
                                btn = page.locator(sel).first
                                if btn.is_visible():
                                    btn.click(force=True)
                                    break
                        self.log("Clicked login submit.")
                        self._human_sleep(3, 5)
                        continue

                    # 4. Success / Landing page
                    elif "build.nvidia.com" in url and "login" not in url:
                        self.log("Successfully landed on build.nvidia.com dashboard!")
                        break
                    
                    # 5. Fallback - if we get stuck or redirecting
                    else:
                        self.log("Waiting for page redirect or next state...")
                        self._human_sleep(2, 3)
            except Exception as loop_err:
                self.log(f"Error in post-verification redirection loop: {loop_err}")

            # Step 4: Try to get API key from the dashboard
            try:
                self.log(f"Navigating to API Keys settings page: {NVIDIA_API}")
                page.goto(NVIDIA_API, wait_until="domcontentloaded", timeout=25000)
                self._human_sleep(5, 7)
                
                # Dismiss cookie consent if present on settings page
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
                
                # Take diagnostic screenshot and HTML dump
                try:
                    os.makedirs("scratch", exist_ok=True)
                    page.screenshot(path="scratch/nvidia_nim_dashboard_success.png")
                    self.log("Saved diagnostic screenshot: scratch/nvidia_nim_dashboard_success.png")
                    with open("scratch/nvidia_nim_dashboard_success.html", "w", encoding="utf-8") as f:
                        f.write(page.content())
                    self.log("Saved diagnostic HTML: scratch/nvidia_nim_dashboard_success.html")
                except Exception as dump_err:
                    self.log(f"Failed to save diagnostics: {dump_err}")
                
                # Check for "Generate Key" / "Create Key" button if no key is present or if permissions allow
                generate_btn_selectors = [
                    'button:has-text("Generate Key")',
                    'button:has-text("Create Key")',
                    'button:has-text("Generate API Key")',
                    'button:has-text("Create API Key")',
                    'button[class*="primary" i]:has-text("Key")',
                ]
                for btn_sel in generate_btn_selectors:
                    if page.locator(btn_sel).count() > 0:
                        btn = page.locator(btn_sel).first
                        if btn.is_visible() and btn.is_enabled():
                            self.log(f"Clicking Generate Key button: {btn_sel}")
                            btn.click(force=True)
                            self._human_sleep(3, 5)
                            break
                            
                # Look for API key — prefer nvapi- prefixed values to avoid picking up UI labels
                api_key_selectors = [
                    '[data-testid="api-key"]',
                    'code',
                    'pre',
                    '.api-key',
                    '[class*="api-key"]',
                    'input[readonly]',
                ]
                for sel in api_key_selectors:
                    try:
                        if page.locator(sel).count() > 0:
                            for el in page.locator(sel).all():
                                try:
                                    potential_key = (el.text_content() or el.inner_text() or el.get_attribute('value') or "").strip()
                                    if potential_key.startswith("nvapi-") or (len(potential_key) > 20 and " " not in potential_key):
                                        api_key = potential_key
                                        self.log(f"Found API key via selector '{sel}': {api_key[:12]}...")
                                        break
                                except Exception:
                                    continue
                        if api_key:
                            break
                    except Exception:
                        continue

                # Fallback 1: Check all text inputs and textareas directly
                if not api_key:
                    try:
                        for el in page.locator('input, textarea').all():
                            try:
                                val = (el.get_attribute('value') or el.text_content() or "").strip()
                                if val.startswith("nvapi-") or (len(val) > 20 and " " not in val and "-" in val):
                                    api_key = val
                                    self.log(f"Found API key in input/textarea value: {api_key[:12]}...")
                                    break
                            except Exception:
                                continue
                    except Exception:
                        pass

                # Try to extract API key via DevTools Inspector bridge first
                if not api_key:
                    self.log("Polling DevTools Inspector bridge for API key...")
                    import json
                    bridge_port = 3005
                    try:
                        from core.config_store import config_store
                        bridge_port = int(config_store.get("devtools_bridge_port", 3005))
                    except:
                        pass
                    
                    bridge_url = f"http://localhost:{bridge_port}/nvidia/extract-key"
                    for i in range(15):  # Poll for up to 30 seconds
                        try:
                            req = urllib.request.Request(bridge_url)
                            with urllib.request.urlopen(req, timeout=3) as resp:
                                res_data = json.loads(resp.read().decode('utf-8'))
                                if res_data.get("ok") and res_data.get("key"):
                                    api_key = res_data["key"]
                                    self.log(f"Successfully extracted API key from DevTools Inspector bridge ({res_data.get('source')}): {api_key[:12]}...")
                                    break
                        except Exception:
                            pass
                        time.sleep(2)

                # Fallback 2: Regex on the entire page content
                if not api_key:
                    try:
                        content = page.content()
                        match = re.search(r'(nvapi-[a-zA-Z0-9_-]{30,})', content)
                        if match:
                            api_key = match.group(1)
                            self.log(f"Found API key in page content via regex: {api_key[:12]}...")
                    except Exception as e:
                        self.log(f"Regex page search failed: {e}")
            except Exception as e:
                self.log(f"Could not retrieve API key: {e}")

            if api_key:
                self.log(f"API key successfully acquired: {api_key[:12]}...")
            else:
                self.log("API key NOT found. Keeping browser open for 180 seconds for manual inspection...")
                time.sleep(180)

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