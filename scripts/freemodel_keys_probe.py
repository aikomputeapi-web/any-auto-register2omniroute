"""Focused probe: navigate to API Keys page and capture the key creation flow."""
import re
import time
import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.base_mailbox import ImapCatchallMailbox
from playwright.sync_api import sync_playwright

FREEMODEL_BASE = "https://freemodel.dev"
FREEMODEL_SIGNUP = f"{FREEMODEL_BASE}/signup"


def log(msg):
    print(f"[FreeModel-Keys] {msg}", flush=True)


def main():
    mailbox = ImapCatchallMailbox(
        imap_server="imap.titan.email",
        imap_port=993,
        imap_username="admin@audioplexdesigns.com",
        imap_password="Dirty2020!",
        domain="audioplexdesigns.com",
        folders="INBOX",
    )
    mailbox._log_fn = log

    log("Generating email via IMAP catchall...")
    mail_acct = mailbox.get_email()
    email = mail_acct.email
    log(f"Email ready: {email}")
    before_ids = mailbox.get_current_ids(mail_acct)

    api_calls = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False, slow_mo=60, args=["--disable-blink-features=AutomationControlled"])
        context = browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        )
        page = context.new_page()

        def on_req(req):
            url = req.url
            if "freemodel.dev/api" in url:
                try:
                    api_calls.append({"type": "REQ", "method": req.method, "url": url, "postData": req.post_data})
                except Exception:
                    pass

        def on_resp(res):
            url = res.url
            if "freemodel.dev/api" in url:
                try:
                    body = res.text()
                except Exception:
                    body = ""
                try:
                    api_calls.append({"type": "RES", "status": res.status, "url": url, "body": body[:2000]})
                except Exception:
                    pass

        page.on("request", on_req)
        page.on("response", on_resp)

        try:
            # Step 1: Signup
            log(f"Navigating to {FREEMODEL_SIGNUP}")
            page.goto(FREEMODEL_SIGNUP, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(2000)
            page.fill("#emailInput", email)
            page.wait_for_timeout(500)
            page.click('button:has-text("Send verification code")')
            page.wait_for_timeout(4000)

            # Step 2: Get OTP
            log("Polling IMAP for OTP code...")
            otp_code = mailbox.wait_for_code(mail_acct, keyword="", timeout=180, before_ids=before_ids, code_pattern=r"\b(\d{6})\b")
            if not otp_code:
                log("FAILED: No OTP code")
                return
            log(f"Extracted OTP: {otp_code}")

            # Step 3: Enter OTP
            otp_inputs = page.locator('input[maxlength="1"]')
            count = otp_inputs.count()
            for i in range(min(count, len(otp_code))):
                otp_inputs.nth(i).fill(otp_code[i])
                page.wait_for_timeout(100)

            # Wait for auto-submit
            pre_url = page.url
            for _ in range(10):
                if page.url != pre_url:
                    break
                page.wait_for_timeout(1000)
            if page.url == pre_url:
                page.keyboard.press("Enter")
            page.wait_for_timeout(5000)
            log(f"URL after verify: {page.url}")

            # Step 4: Navigate to API Keys page
            log("\n=== Navigating to /api-keys ===")
            page.goto(f"{FREEMODEL_BASE}/api-keys", wait_until="domcontentloaded", timeout=15000)
            page.wait_for_timeout(3000)
            log(f"URL: {page.url}")
            page.screenshot(path="freemodel_keys_1_page.png")

            body_text = page.locator("body").inner_text(timeout=5000)
            log(f"API Keys page text:\n{body_text[:3000]}")

            # Dump all buttons
            buttons = page.locator("button").all()
            log("\nButtons on API Keys page:")
            for btn in buttons[:30]:
                try:
                    text = (btn.inner_text(timeout=1000) or "").strip()
                    if text:
                        try:
                            visible = btn.is_visible()
                        except Exception:
                            visible = False
                        log(f'  button: "{text}" visible={visible}')
                except Exception:
                    pass

            # Dump all inputs
            inputs = page.locator("input, textarea").all()
            log(f"\nInputs on API Keys page: {len(inputs)}")
            for inp in inputs[:15]:
                try:
                    tag = inp.evaluate("e => e.tagName")
                    val = inp.input_value() if tag in ("INPUT", "TEXTAREA") else ""
                    placeholder = inp.get_attribute("placeholder")
                    log(f"  <{tag} value=\"{val}\" placeholder=\"{placeholder}\">")
                except Exception:
                    pass

            # Look for existing API keys in code/pre/span elements
            log("\n=== Searching for existing API keys ===")
            for el in page.locator("code, pre, span, div, td, input, textarea").all():
                try:
                    text = ""
                    try:
                        text = el.inner_text(timeout=500)
                    except Exception:
                        try:
                            text = el.input_value()
                        except Exception:
                            pass
                    if text:
                        # Try various key patterns
                        for pattern in [r'\b(fm_[A-Za-z0-9_-]{10,})\b', r'\b(sk-[A-Za-z0-9_-]{10,})\b', r'\b(fk_[A-Za-z0-9_-]{10,})\b', r'\b(FRE-[A-Za-z0-9]+)\b', r'\b([A-Za-z0-9]{32,})\b']:
                            m = re.search(pattern, text)
                            if m:
                                log(f"  FOUND potential key: {m.group(0)[:30]}... (pattern: {pattern})")
                except Exception:
                    pass

            # Step 5: Try clicking "Create" or "Generate" key button
            log("\n=== Looking for create/generate key button ===")
            create_selectors = [
                'button:has-text("Create")', 'button:has-text("Generate")',
                'button:has-text("New")', 'button:has-text("Add")',
                'button:has-text("Create Key")', 'button:has-text("Create API Key")',
                'button:has-text("New Key")', 'button:has-text("Generate Key")',
            ]
            for sel in create_selectors:
                btn = page.locator(sel).first
                try:
                    if btn.count() > 0 and btn.is_visible():
                        log(f"  Found create button: {sel}")
                        log(f"  Clicking {sel}...")
                        btn.click()
                        page.wait_for_timeout(3000)
                        page.screenshot(path="freemodel_keys_2_after_create.png")
                        # Check for dialog/modal
                        modal_text = page.locator("body").inner_text(timeout=3000)
                        log(f"  Text after create click: {modal_text[:1000]}")
                        # Look for key in response
                        break
                except Exception as e:
                    log(f"  {sel}: {e}")

            # Look for key in captured API responses
            log("\n=== API calls with key-related content ===")
            for c in api_calls:
                if c.get("type") == "RES":
                    body = c.get("body", "")
                    if re.search(r'key|token|secret', body, re.I) and len(body) > 20:
                        log(f"  {c['url']}: {body[:500]}")

            log("\n=== All API calls ===")
            for c in api_calls:
                log(json.dumps(c))

        except Exception as e:
            log(f"Error: {e}")
            try:
                page.screenshot(path="freemodel_keys_error.png")
            except Exception:
                pass
            import traceback
            traceback.print_exc()
        finally:
            context.close()
            browser.close()


if __name__ == "__main__":
    main()
