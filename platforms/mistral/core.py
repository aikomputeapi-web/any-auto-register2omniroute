"""
Mistral AI Automatic registration with API key generation

Process:
  1. Navigate to signup page
  2. Fill email and password
  3. Submit and verify email with OTP
  4. Navigate to settings/API page
  5. Generate API key
"""

import re
import json
import time
import random
import string
from typing import Optional, Tuple
from playwright.sync_api import sync_playwright, TimeoutError, Page
from core.browser_runtime import ensure_browser_display_available, resolve_browser_headless
from core.proxy_utils import build_playwright_proxy_config, resolve_us_profile

MISTRAL_BASE = "https://console.mistral.ai"
MISTRAL_SIGNUP = f"{MISTRAL_BASE}/auth/signup"
MISTRAL_SIGNIN = f"{MISTRAL_BASE}/auth/signin"
MISTRAL_API = f"{MISTRAL_BASE}/api-keys"


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


class MistralRegister:
    def __init__(self, proxy: str = None, headless: bool = True):
        self.proxy = proxy
        self.headless = headless
        self.pw = None
        self.browser = None
        self.context = None

    def log(self, msg):
        print(f"[Mistral] {msg}")

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

        first_name, last_name = _rand_name()
        page = None
        
        try:
            self._init_browser()
            page = self.context.new_page()

            # Step 1: Navigate to signup page
            self.log(f"Navigating to signup page for {email}")
            page.goto(MISTRAL_SIGNUP, wait_until="domcontentloaded", timeout=30000)
            self._human_sleep(2, 3)

            # Step 2: Fill signup form
            self.log("Filling email...")
            
            # Wait for email input to be ready
            page.wait_for_selector('input[name="email"], input[type="email"]', timeout=10000)
            
            # Fill email
            email_selectors = ['input[name="email"]', 'input[type="email"]', 'input[placeholder*="email" i]']
            email_filled = False
            for sel in email_selectors:
                if page.locator(sel).count() > 0:
                    self._type_human(page, sel, email)
                    email_filled = True
                    break
            
            if not email_filled:
                return False, {"error": "Could not find email input field"}
            
            # Check the legal acceptance checkbox if present
            try:
                checkbox = page.locator('input[name="terms"], input[type="checkbox"]').first
                if checkbox.count() > 0 and checkbox.is_visible():
                    checkbox.check()
                    self._human_sleep(0.3, 0.6)
            except:
                pass
            
            # Find and click the continue/submit button to submit email
            self.log("Submitting email")
            submit_selectors = [
                'button[type="submit"]',
                'button:has-text("Continue")',
                'button:has-text("Sign up")',
                'button:has-text("Create")',
            ]
            clicked = False
            for sel in submit_selectors:
                btn = page.locator(sel).first
                if btn.count() > 0 and btn.is_visible():
                    btn.click()
                    clicked = True
                    break
            if not clicked:
                page.keyboard.press("Enter")
            
            self._human_sleep(2, 4)

            # Wait for password input to appear on the second screen
            self.log("Waiting for password screen...")
            page.wait_for_selector('input[name="password"]', timeout=10000)

            # Fill password
            pw_selectors = ['input[name="password"]', 'input[type="password"]', 'input[placeholder*="password" i]']
            password_filled = False
            for sel in pw_selectors:
                if page.locator(sel).count() > 0:
                    self._type_human(page, sel, password)
                    password_filled = True
                    break

            if not password_filled:
                return False, {"error": "Could not find password input field"}

            # Check legal checkbox if present on the second screen
            try:
                checkbox = page.locator('input[name="terms"], input[type="checkbox"]').first
                if checkbox.count() > 0 and checkbox.is_visible():
                    checkbox.check()
                    self._human_sleep(0.3, 0.6)
            except:
                pass

            # Submit password
            self.log("Submitting password")
            clicked = False
            for sel in submit_selectors:
                btn = page.locator(sel).first
                if btn.count() > 0 and btn.is_visible():
                    btn.click()
                    clicked = True
                    break
            if not clicked:
                page.keyboard.press("Enter")
            
            self._human_sleep(2, 4)

            # Check if First Name / Last Name inputs appear (third screen of signup)
            try:
                if page.locator('input[name="firstName"]').count() > 0:
                    self.log(f"Filling first and last name: {first_name} {last_name}")
                    self._type_human(page, 'input[name="firstName"]', first_name)
                    self._type_human(page, 'input[name="lastName"]', last_name)
                    
                    # Check legal checkbox if present on the third screen
                    try:
                        checkbox = page.locator('input[name="terms"], input[type="checkbox"]').first
                        if checkbox.count() > 0 and checkbox.is_visible():
                            checkbox.check()
                            self._human_sleep(0.3, 0.6)
                    except:
                        pass
                    
                    self.log("Submitting name info")
                    clicked = False
                    for sel in submit_selectors:
                        btn = page.locator(sel).first
                        if btn.count() > 0 and btn.is_visible():
                            btn.click()
                            clicked = True
                            break
                    if not clicked:
                        page.keyboard.press("Enter")
                    self._human_sleep(2, 4)
            except Exception as e:
                self.log(f"Name input step skipped or failed: {e}")

            # Step 3: Handle email verification if OTP callback provided
            api_key = ""
            if otp_callback:
                self.log("Waiting for OTP code...")
                otp = otp_callback()
                if otp:
                    self.log(f"Submitting OTP: {otp}")
                    # Look for OTP input field
                    otp_selectors = [
                        'input[name="code"]',
                        'input[placeholder*="code" i]',
                        'input[maxlength="6"]',
                    ]
                    for sel in otp_selectors:
                        if page.locator(sel).count() > 0:
                            self._type_human(page, sel, otp)
                            break
                    
                    # Submit OTP
                    for sel in submit_selectors:
                        if page.locator(sel).count() > 0:
                            page.locator(sel).first.click()
                            break
                    self._human_sleep(2, 3)
            
            # Step 4: Try to get API key from the dashboard
            try:
                page.goto(MISTRAL_API, wait_until="domcontentloaded", timeout=15000)
                self._human_sleep(2, 3)
                
                # Look for API key or generate button
                # The actual implementation may vary based on Mistral's UI
                api_key_selectors = [
                    'code',
                    '[data-testid="api-key"]',
                    'pre',
                ]
                for sel in api_key_selectors:
                    if page.locator(sel).count() > 0:
                        key_el = page.locator(sel).first
                        potential_key = key_el.inner_text()
                        if potential_key and len(potential_key) > 10:
                            api_key = potential_key.strip()
                            break
            except Exception as e:
                self.log(f"Could not retrieve API key: {e}")

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