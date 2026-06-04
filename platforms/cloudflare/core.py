"""
Cloudflare Account Registration with API Token Generation

Process:
  1. Navigate to signup page
  2. Fill email and password
  3. Verify email with OTP
  4. Navigate to API tokens page
  5. Create API token
  6. Save token
"""

import re
import time
import random
import string
from typing import Optional, Tuple
from playwright.sync_api import sync_playwright, Page
from core.browser_runtime import ensure_browser_display_available, resolve_browser_headless
from core.proxy_utils import build_playwright_proxy_config, resolve_us_profile

CLOUDFLARE_BASE = "https://dash.cloudflare.com"
CLOUDFLARE_SIGNUP = f"{CLOUDFLARE_BASE}/sign-up"
CLOUDFLARE_API_TOKENS = f"{CLOUDFLARE_BASE}/profile/api-tokens"


def _rand_password(n=16):
    chars = string.ascii_letters + string.digits + "!@#$%^&*"
    pw = (
        random.choice(string.ascii_uppercase)
        + random.choice(string.ascii_lowercase)
        + random.choice(string.digits)
        + random.choice("!@#$%^&*")
        + "".join(random.choices(chars, k=n - 4))
    )
    lst = list(pw)
    random.shuffle(lst)
    return "".join(lst)


class CloudflareRegister:
    def __init__(self, proxy: str = None, headless: bool = True):
        self.proxy = proxy
        self.headless = headless
        self.pw = None
        self.browser = None
        self.context = None

    def log(self, msg):
        print(f"[Cloudflare] {msg}")

    def _human_sleep(self, min_sec: float = 0.5, max_sec: float = 1.5):
        time.sleep(random.uniform(min_sec, max_sec))

    def _init_browser(self):
        self.pw = sync_playwright().start()
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

        us_loc = resolve_us_profile(self.proxy)
        self.browser = self.pw.chromium.launch(**launch_opts)
        self.context = self.browser.new_context(
            viewport={"width": 1280, "height": 720},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            locale=us_loc["locale"],
            timezone_id=us_loc["timezone"],
            geolocation={"latitude": us_loc["latitude"], "longitude": us_loc["longitude"]},
            permissions=["geolocation"],
        )
        self.log(f"Browser mode: {'headless' if headless else 'headed'} ({reason})")

    def _close_browser(self):
        if self.context:
            self.context.close()
        if self.browser:
            self.browser.close()
        if self.pw:
            self.pw.stop()

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
        otp_callback=None,
    ) -> Tuple[bool, dict]:
        if not password:
            password = _rand_password()

        page = None
        
        try:
            self._init_browser()
            page = self.context.new_page()

            # Step 1: Navigate to signup page
            self.log(f"Navigating to signup page for {email}")
            page.goto(CLOUDFLARE_SIGNUP, wait_until="domcontentloaded", timeout=30000)
            self._human_sleep(2, 3)

            # Step 2: Fill signup form
            self.log("Filling signup form")
            
            # Wait for email input
            page.wait_for_selector('input[type="email"]', timeout=10000)
            
            # Fill email
            self._type_human(page, 'input[type="email"]', email)
            
            # Fill password
            self._type_human(page, 'input[type="password"]', password)
            
            # Submit form
            self.log("Submitting signup form")
            submit_selectors = [
                'button[type="submit"]',
                'button:has-text("Sign up")',
                'button:has-text("Create Account")',
            ]
            
            clicked = False
            for selector in submit_selectors:
                try:
                    btn = page.locator(selector).first
                    if btn.count() > 0 and btn.is_visible():
                        btn.click()
                        clicked = True
                        self.log(f"Clicked submit button: {selector}")
                        break
                except:
                    continue
            
            if not clicked:
                return False, {"error": "Could not find submit button"}
            
            self._human_sleep(2, 3)

            # Step 3: Handle email verification
            if not otp_callback:
                return False, {"error": "OTP callback required"}

            self.log("Waiting for email verification")
            self._human_sleep(3, 5)
            
            # Wait for verification code input
            code_input_found = False
            code_selectors = [
                'input[name="code"]',
                'input[type="text"][placeholder*="code" i]',
                'input[type="text"][placeholder*="verification" i]',
            ]
            
            for selector in code_selectors:
                try:
                    page.wait_for_selector(selector, timeout=10000, state="visible")
                    code_input_found = True
                    self.log(f"Found verification code input: {selector}")
                    break
                except:
                    continue
            
            if not code_input_found:
                page.screenshot(path="cloudflare_no_verification.png")
                return False, {"error": "Verification code input not found"}
            
            self.log("Requesting verification code from email")
            otp_code = otp_callback()
            if not otp_code:
                return False, {"error": "Email verification code not received"}

            self.log(f"Got verification code: {otp_code}")
            self._human_sleep(1, 2)

            # Step 4: Enter verification code
            for selector in code_selectors:
                try:
                    code_input = page.locator(selector).first
                    if code_input.count() > 0 and code_input.is_visible():
                        code_input.fill("")
                        self._human_sleep(0.3, 0.5)
                        self._type_human(page, selector, str(otp_code))
                        self.log(f"Entered code using selector: {selector}")
                        break
                except Exception as e:
                    continue
            
            self._human_sleep(3, 5)

            # Step 5: Navigate to API tokens page
            self.log("Navigating to API tokens page")
            page.goto(CLOUDFLARE_API_TOKENS, wait_until="domcontentloaded", timeout=30000)
            self._human_sleep(2, 3)
            
            current_url = page.url
            self.log(f"Current URL: {current_url}")
            
            # Check if logged in
            if "sign-in" in current_url or "sign-up" in current_url:
                page.screenshot(path="cloudflare_not_logged_in.png")
                return False, {"error": "Not logged in after verification"}

            # Step 6: Create API token
            self.log("Looking for create token button")
            self._human_sleep(2, 3)
            
            create_selectors = [
                'button:has-text("Create Token")',
                'a:has-text("Create Token")',
                'button:has-text("Create")',
            ]
            
            token_button_found = False
            for selector in create_selectors:
                try:
                    btn = page.locator(selector).first
                    if btn.count() > 0 and btn.is_visible():
                        self.log(f"Found create token button: {selector}")
                        btn.click()
                        token_button_found = True
                        self._human_sleep(2, 3)
                        break
                except:
                    continue
            
            if not token_button_found:
                self.log("No create token button found")
            
            # Wait for token to appear
            self._human_sleep(2, 3)
            
            # Extract API token
            api_token = None
            token_selectors = [
                'input[readonly]',
                'textarea[readonly]',
                'code',
                'pre',
            ]
            
            for selector in token_selectors:
                try:
                    elements = page.locator(selector).all()
                    for el in elements:
                        try:
                            val = el.input_value() if selector.startswith('input') or selector.startswith('textarea') else el.text_content()
                            if val and len(val) > 30:
                                api_token = val.strip()
                                self.log(f"Found API token using selector: {selector}")
                                break
                        except:
                            continue
                    if api_token:
                        break
                except:
                    continue

            if not api_token:
                page.screenshot(path="cloudflare_no_token.png")
                return False, {"error": "Failed to extract API token"}

            self.log(f"Successfully generated API token: {api_token[:20]}...")

            # Step 7: Save API token
            self._save_api_token(email, api_token)

            return True, {
                "email": email,
                "password": password,
                "api_token": api_token,
            }

        except Exception as e:
            self.log(f"Error during registration: {e}")
            if page:
                try:
                    page.screenshot(path="cloudflare_error.png")
                    self.log("Screenshot saved as cloudflare_error.png")
                except:
                    pass
            return False, {"error": str(e)}
        finally:
            self._close_browser()

    def _save_api_token(self, email: str, api_token: str):
        """Save API token to cloudflare_tokens.txt file"""
        try:
            import os
            file_path = os.path.join(os.getcwd(), "cloudflare_tokens.txt")
            with open(file_path, "a", encoding="utf-8") as f:
                f.write(f"{email}:{api_token}\n")
            self.log(f"API token saved to {file_path}")
        except Exception as e:
            self.log(f"Failed to save API token to file: {e}")
