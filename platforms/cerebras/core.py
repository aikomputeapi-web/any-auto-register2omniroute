"""
Cerebras AI Cloud Automatic registration with API key generation
"""

import re
import time
import random
import string
import urllib.parse
from typing import Optional, Tuple, Callable
from playwright.sync_api import sync_playwright, TimeoutError, Page
from core.browser_runtime import ensure_browser_display_available, resolve_browser_headless
from core.proxy_utils import build_playwright_proxy_config, resolve_us_profile

CEREBRAS_BASE = "https://cloud.cerebras.ai"
CEREBRAS_API_KEYS = f"{CEREBRAS_BASE}/api-keys"


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


class CerebrasRegister:
    def __init__(self, proxy: str = None, headless: bool = True, captcha_solver = None):
        self.proxy = proxy
        self.headless = headless
        self.captcha_solver = captcha_solver
        self.pw = None
        self.browser = None
        self.context = None

    def log(self, msg):
        print(f"[Cerebras] {msg}")

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
            viewport={"width": 1280, "height": 800},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            locale=us_loc["locale"],
            timezone_id=us_loc["timezone"],
            geolocation={"latitude": us_loc["latitude"], "longitude": us_loc["longitude"]},
            permissions=["geolocation"],
        )
        self.log(f"Browser mode: {'headless' if headless else 'headed'} ({reason})")

    def _close_browser(self):
        if self.context:
            try:
                self.context.close()
            except:
                pass
        if self.browser:
            try:
                self.browser.close()
            except:
                pass
        if self.pw:
            try:
                self.pw.stop()
            except:
                pass

    def _type_human(self, page: Page, selector: str, text: str):
        self._human_sleep(0.3, 0.7)
        el = page.locator(selector).first
        el.click()
        el.fill("")
        for char in text:
            page.keyboard.type(char, delay=random.randint(50, 150))
        self._human_sleep(0.2, 0.5)

    def _extract_site_key(self, page: Page) -> str:
        # Check if we can find reCAPTCHA sitekey dynamically
        site_keys = []
        try:
            iframes = page.locator('iframe[src*="recaptcha"]').all()
            for iframe in iframes:
                src = iframe.get_attribute("src")
                if src:
                    parsed = urllib.parse.urlparse(src)
                    params = urllib.parse.parse_qs(parsed.query)
                    if "k" in params:
                        sk = params["k"][0]
                        visible = iframe.is_visible()
                        site_keys.append({"key": sk, "visible": visible})
        except Exception as e:
            self.log(f"Error extracting sitekey dynamically: {e}")

        # Choose the best sitekey: prefer visible iframes
        for entry in site_keys:
            if entry["visible"]:
                self.log(f"Extracted visible reCAPTCHA sitekey dynamically: {entry['key']}")
                return entry["key"]
                
        if site_keys:
            self.log(f"Extracted first reCAPTCHA sitekey dynamically: {site_keys[0]['key']}")
            return site_keys[0]["key"]

        default_key = "6LdnMCUrAAAAAJ7n8mbQNU6YbWxxARSlZC3Mkuv9"
        self.log(f"Using default reCAPTCHA sitekey: {default_key}")
        return default_key

    def _inject_recaptcha_response(self, page: Page, token: str, site_key: str) -> bool:
        self.log("Injecting reCAPTCHA token and hooking execute method...")
        js_code = """(args) => {
            const token = args.token;
            const site_key = args.site_key;
            
            // 1. Inject into textareas
            const textareas = document.querySelectorAll('textarea[id^="g-recaptcha-response"], textarea[name="g-recaptcha-response"]');
            textareas.forEach(ta => {
                ta.value = token;
                ta.dispatchEvent(new Event('input', { bubbles: true }));
                ta.dispatchEvent(new Event('change', { bubbles: true }));
            });
            
            // 2. Hook grecaptcha.enterprise.execute and grecaptcha.execute
            if (typeof grecaptcha !== 'undefined') {
                if (grecaptcha.enterprise && typeof grecaptcha.enterprise.execute === 'function') {
                    grecaptcha.enterprise.execute = () => Promise.resolve(token);
                }
                if (typeof grecaptcha.execute === 'function') {
                    grecaptcha.execute = () => Promise.resolve(token);
                }
            }
            
            // Helper to recursively find sitekey in a client object
            function findSitekeyInObject(obj, targetSitekey, depth = 0) {
                if (depth > 5) return false;
                if (!obj || typeof obj !== 'object') return false;
                for (const key in obj) {
                    try {
                        const val = obj[key];
                        if (typeof val === 'string' && val === targetSitekey) {
                            return true;
                        } else if (typeof val === 'object' && val !== null) {
                            if (!(val instanceof HTMLElement)) {
                                if (findSitekeyInObject(val, targetSitekey, depth + 1)) {
                                    return true;
                                }
                            }
                        }
                    } catch(e) {}
                }
                return false;
            }
            
            // Helper to recursively find and execute callbacks
            function triggerCallbacks(obj, depth = 0) {
                if (depth > 5) return;
                if (!obj || typeof obj !== 'object') return;
                
                for (const key in obj) {
                    try {
                        const val = obj[key];
                        if (typeof val === 'function') {
                            if (key === 'callback' || key === 'promise-callback') {
                                val(token);
                                called = true;
                            }
                        } else if (typeof val === 'object' && val !== null) {
                            if (!(val instanceof HTMLElement)) {
                                triggerCallbacks(val, depth + 1);
                            }
                        }
                    } catch (e) {}
                }
            }
            
            // 3. Robust traversal of ___grecaptcha_cfg.clients matching site_key
            let called = false;
            if (window.___grecaptcha_cfg && window.___grecaptcha_cfg.clients) {
                const clients = window.___grecaptcha_cfg.clients;
                for (const clientKey in clients) {
                    const client = clients[clientKey];
                    if (findSitekeyInObject(client, site_key)) {
                        triggerCallbacks(client);
                    }
                }
            }
            return called;
        }"""
        result = page.evaluate(js_code, {"token": token, "site_key": site_key})
        self.log(f"reCAPTCHA callback injection result: {result}")
        return result


    def register(
        self,
        email: str,
        password: Optional[str] = None,
        otp_callback: Optional[Callable[[], str]] = None,
    ) -> Tuple[bool, dict]:
        if not password:
            password = _rand_password()

        page = None
        try:
            self._init_browser()
            page = self.context.new_page()

            # Step 1: Navigate to signup page
            self.log(f"Navigating to Cerebras signup page for {email}")
            page.goto(CEREBRAS_BASE, wait_until="domcontentloaded", timeout=30000)
            self._human_sleep(2, 4)

            # Accept cookies if present
            try:
                cookie_btn = page.locator('button:has-text("Accept All"), button:has-text("Accept"), button:has-text("Reject All")').first
                if cookie_btn.count() > 0 and cookie_btn.is_visible():
                    self.log("Accepting cookie consent...")
                    cookie_btn.click()
                    self._human_sleep(0.5, 1)
            except Exception as e:
                self.log(f"Failed to handle cookie consent: {e}")

            # Check if email input is already there
            page.wait_for_selector('input[type="email"], input#email', timeout=15000)
            self.log("Filling email...")
            self._type_human(page, 'input[type="email"], input#email', email)
            self._human_sleep(1, 2)

            # Submit form first to trigger verification flow
            self.log("Submitting initial sign up form...")
            submit_btn = page.locator('button[type="submit"]').first
            
            # Check if submit button is disabled. If so, try to enable it or JS click it.
            if submit_btn.is_disabled():
                self.log("Submit button is disabled, attempting to force click via JS...")
                page.evaluate("el => el.removeAttribute('disabled')", submit_btn.element_handle())
                page.evaluate("el => el.click()", submit_btn.element_handle())
            else:
                submit_btn.click()

            self._human_sleep(2, 4)

            # Wait for Clerk OTP inputs, Magic Link, or reCAPTCHA to appear
            otp_selectors = [
                'input[maxlength="1"][type="text"]',
                '.cl-otpCodeField input',
                '.cl-otpCodeFieldInput',
                'input[autocomplete="one-time-code"]',
                'input[name="code"]',
            ]
            magic_link_selectors = [
                'text="Check your email"',
                'h1:has-text("Check your email")',
                'button:has-text("Go back")',
            ]
            
            captcha_detected = False
            code_input_found = False
            magic_link_screen_found = False
            
            for _ in range(15):
                # Check for OTP
                for sel in otp_selectors:
                    if page.locator(sel).count() > 0 and page.locator(sel).first.is_visible():
                        code_input_found = True
                        break
                if code_input_found:
                    break
                
                # Check for Magic Link screen
                for sel in magic_link_selectors:
                    if page.locator(sel).count() > 0 and page.locator(sel).first.is_visible():
                        magic_link_screen_found = True
                        break
                if magic_link_screen_found:
                    break
                
                # Check for reCAPTCHA
                iframe = page.locator('iframe[src*="recaptcha"]').first
                if iframe.count() > 0 and iframe.is_visible():
                    captcha_detected = True
                    break
                
                page.wait_for_timeout(1000)

            # Step 2: Solve reCAPTCHA if detected
            if captcha_detected:
                self.log("reCAPTCHA detected, solving...")
                site_key = self._extract_site_key(page)
                if not self.captcha_solver:
                    raise RuntimeError("No captcha solver configured for reCAPTCHA")
                
                self.log("Solving reCAPTCHA Enterprise...")
                captcha_token = self.captcha_solver.solve_recaptcha(page.url, site_key, enterprise=True, invisible=False)
                self.log("reCAPTCHA solved successfully")

                # Inject response
                self._inject_recaptcha_response(page, captcha_token, site_key)
                self._human_sleep(1, 2)

                # Re-submit form after solving captcha
                self.log("Re-submitting sign up form after solving reCAPTCHA...")
                submit_btn = page.locator('button[type="submit"]').first
                if submit_btn.is_disabled():
                    self.log("Submit button is disabled, attempting to force click via JS...")
                    page.evaluate("el => el.removeAttribute('disabled')", submit_btn.element_handle())
                    page.evaluate("el => el.click()", submit_btn.element_handle())
                else:
                    submit_btn.click()
                self._human_sleep(3, 5)

                # After re-submission, wait for OTP or Magic Link screen to appear
                self.log("Waiting for verification screen after re-submitting...")
                for _ in range(15):
                    for sel in otp_selectors:
                        if page.locator(sel).count() > 0 and page.locator(sel).first.is_visible():
                            code_input_found = True
                            break
                    if code_input_found:
                        break
                    
                    for sel in magic_link_selectors:
                        if page.locator(sel).count() > 0 and page.locator(sel).first.is_visible():
                            magic_link_screen_found = True
                            break
                    if magic_link_screen_found:
                        break
                    page.wait_for_timeout(1000)

            # Step 3: Handle Verification (OTP or Magic Link)
            if not otp_callback:
                raise RuntimeError("OTP callback is required for passwordless registration")

            if not code_input_found and not magic_link_screen_found:
                # Save screenshot to debug
                page.screenshot(path="cerebras_otp_input_not_found.png")
                raise RuntimeError("Neither OTP verification inputs nor Magic Link screen found. Screenshot saved.")

            if magic_link_screen_found:
                self.log("Magic Link screen detected. Requesting verification magic link...")
                verify_link = otp_callback()
                if not verify_link:
                    raise RuntimeError("Failed to retrieve magic link from mailbox")
                if not verify_link.startswith("http"):
                    raise RuntimeError(f"Expected verification URL, but got: {verify_link}")
                
                self.log(f"Navigating to Magic Link: {verify_link[:40]}...")
                page.goto(verify_link, wait_until="domcontentloaded", timeout=30000)
                self._human_sleep(3, 5)
            else:
                self.log("OTP verification screen detected. Requesting code...")
                otp_code = otp_callback()
                if not otp_code:
                    raise RuntimeError("Failed to retrieve OTP code from mailbox")

                self.log(f"Received OTP: {otp_code}. Entering code...")
                
                # Find the active selector and fill the code
                entered = False
                for sel in otp_selectors:
                    loc = page.locator(sel)
                    if loc.count() > 0 and loc.first.is_visible():
                        if loc.count() == 6:
                            # 6 distinct input fields
                            for idx in range(6):
                                loc.nth(idx).fill(otp_code[idx])
                                self._human_sleep(0.1, 0.2)
                            entered = True
                        else:
                            loc.first.fill("")
                            self._type_human(page, sel, otp_code)
                            entered = True
                        break

                if not entered:
                    raise RuntimeError("Could not enter OTP code")

                self._human_sleep(3, 5)

            # Wait for dashboard page url (usually contains /workspaces or not /sign-in /sign-up)
            self.log("Waiting for dashboard/navigation...")
            for _ in range(10):
                curr_url = page.url
                if "/workspaces" in curr_url or "api-keys" in curr_url or "cloud.cerebras.ai" in curr_url and "/sign-in" not in curr_url and "/sign-up" not in curr_url:
                    self.log(f"Successfully authenticated. Current URL: {curr_url}")
                    break
                page.wait_for_timeout(1000)

            # Step 4: Navigate to API Keys page and create a key
            self.log(f"Navigating to API Keys page: {CEREBRAS_API_KEYS}")
            page.goto(CEREBRAS_API_KEYS, wait_until="domcontentloaded", timeout=20000)
            self._human_sleep(2, 4)

            # Locate button to create a new key
            create_key_selectors = [
                'button:has-text("Create API Key")',
                'button:has-text("Create Key")',
                'button:has-text("New Key")',
                'button:has-text("Generate Key")',
                'a:has-text("Create API Key")',
            ]
            
            create_btn = None
            for sel in create_key_selectors:
                loc = page.locator(sel).first
                if loc.count() > 0 and loc.is_visible():
                    create_btn = loc
                    break

            if not create_btn:
                page.screenshot(path="cerebras_no_create_key_button.png")
                raise RuntimeError("Create API Key button not found. Screenshot saved.")

            self.log("Clicking Create API Key button...")
            create_btn.click()
            self._human_sleep(1.5, 3)

            # Handle possible key naming dialog/modal
            # E.g. prompt for key name, let's type a name and press Create
            try:
                dialog_input = page.locator('input[placeholder*="Key" i], input[placeholder*="Name" i], input[type="text"]').first
                if dialog_input.count() > 0 and dialog_input.is_visible():
                    self.log("Key naming dialog detected, entering name...")
                    dialog_input.fill("Auto-Key")
                    self._human_sleep(0.5, 1)
                    
                    submit_selectors = [
                        'button:has-text("Create")',
                        'button:has-text("Generate")',
                        'button[type="submit"]',
                    ]
                    for s_sel in submit_selectors:
                        s_btn = page.locator(s_sel).first
                        if s_btn.count() > 0 and s_btn.is_visible():
                            s_btn.click()
                            break
                    self._human_sleep(2, 4)
            except Exception as de:
                self.log(f"Dialog handling skipped or not found: {de}")

            # Step 5: Extract the generated API Key (typically starts with csk-)
            api_key = None
            self.log("Searching page content for Cerebras API key...")
            
            # Check input elements first (often keys are displayed in readonly inputs/textareas)
            for input_el in page.locator('input').all():
                try:
                    val = input_el.input_value()
                    if val and val.startswith("csk-"):
                        api_key = val
                        break
                except:
                    pass

            if not api_key:
                # Fallback to general regex search in page HTML
                html_content = page.content()
                match = re.search(r'\bcsk-[a-zA-Z0-9_-]+\b', html_content)
                if match:
                    api_key = match.group(0)

            if not api_key:
                # Save screenshot to debug
                page.screenshot(path="cerebras_key_extraction_failed.png")
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
