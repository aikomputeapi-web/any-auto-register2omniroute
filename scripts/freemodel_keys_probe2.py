"""Focused probe: click API Keys nav button and capture key creation flow."""
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
    print(f"[FreeModel-Keys2] {msg}", flush=True)


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
            # Signup
            log(f"Navigating to {FREEMODEL_SIGNUP}")
            page.goto(FREEMODEL_SIGNUP, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(2000)
            page.fill("#emailInput", email)
            page.wait_for_timeout(500)
            page.click('button:has-text("Send verification code")')
            page.wait_for_timeout(4000)

            log("Polling IMAP for OTP code...")
            otp_code = mailbox.wait_for_code(mail_acct, keyword="", timeout=180, before_ids=before_ids, code_pattern=r"\b(\d{6})\b")
            if not otp_code:
                log("FAILED: No OTP code")
                return
            log(f"Extracted OTP: {otp_code}")

            otp_inputs = page.locator('input[maxlength="1"]')
            count = otp_inputs.count()
            for i in range(min(count, len(otp_code))):
                otp_inputs.nth(i).fill(otp_code[i])
                page.wait_for_timeout(100)

            pre_url = page.url
            for _ in range(10):
                if page.url != pre_url:
                    break
                page.wait_for_timeout(1000)
            if page.url == pre_url:
                page.keyboard.press("Enter")
            page.wait_for_timeout(5000)
            log(f"URL after verify: {page.url}")

            # Dismiss any modals (tutorial, referral popup, account verification).
            # Some modals use a modal-backdrop that intercepts pointer events.
            # We dismiss them by clicking dismiss buttons AND removing backdrops via JS.
            for attempt in range(5):
                dismissed = False
                for dismiss_text in ["Dismiss", "Got it", "Cancel", "Close", "×"]:
                    try:
                        btn = page.locator(f'button:has-text("{dismiss_text}")').first
                        if btn.count() > 0:
                            try:
                                if btn.is_visible():
                                    log(f"Dismissing modal: {dismiss_text}")
                                    btn.click(force=True)
                                    page.wait_for_timeout(800)
                                    dismissed = True
                            except Exception:
                                pass
                    except Exception:
                        pass
                # Remove any modal-backdrop elements via JS
                try:
                    page.evaluate("""() => {
                        document.querySelectorAll('.modal-backdrop, .modal-overlay').forEach(el => el.remove());
                        // Also remove open class from body if present
                        document.body.classList.remove('modal-open');
                    }""")
                except Exception:
                    pass
                if not dismissed:
                    break
                page.wait_for_timeout(500)

            # Verify no modal-backdrop remains
            backdrop_count = page.locator('.modal-backdrop').count()
            log(f"Modal backdrops remaining: {backdrop_count}")
            if backdrop_count > 0:
                page.evaluate("() => document.querySelectorAll('.modal-backdrop').forEach(el => el.remove())")

            # Click the "API Keys" nav button (SPA navigation)
            log("\n=== Clicking 'API Keys' nav button ===")
            try:
                btn = page.locator('button:has-text("API Keys")').first
                if btn.count() > 0:
                    btn.click(force=True)
                    page.wait_for_timeout(3000)
                    log(f"URL after clicking API Keys: {page.url}")
                    page.screenshot(path="freemodel_keys2_1_apikeys_page.png")
                else:
                    log("API Keys button not found!")
            except Exception as e:
                log(f"Click failed, trying JS click: {e}")
                page.evaluate("""() => {
                    const buttons = document.querySelectorAll('button');
                    for (const b of buttons) {
                        if (b.textContent.includes('API Keys')) { b.click(); return; }
                    }
                }""")
                page.wait_for_timeout(3000)
                page.screenshot(path="freemodel_keys2_1_apikeys_page.png")

            body_text = page.locator("body").inner_text(timeout=5000)
            log(f"API Keys page text:\n{body_text[:3000]}")

            # Dump buttons
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

            # Search for existing keys
            log("\n=== Searching for existing API keys (fe_oa_ pattern) ===")
            for el in page.locator("code, pre, span, div, td, input, textarea, p").all():
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
                        m = re.search(r'\b(fe_oa_[A-Za-z0-9_-]{5,})\b', text)
                        if m:
                            log(f"  FOUND API KEY: {m.group(0)}")
                except Exception:
                    pass

            # Try clicking "Create" / "Generate" key button
            log("\n=== Looking for create/generate key button ===")
            create_selectors = [
                'button:has-text("Create")', 'button:has-text("Generate")',
                'button:has-text("New Key")', 'button:has-text("New key")',
                'button:has-text("Add")', 'button:has-text("Create Key")',
                'button:has-text("Create API Key")', 'button:has-text("Generate Key")',
                'button:has-text("+")',
            ]
            clicked_create = False
            for sel in create_selectors:
                btn = page.locator(sel).first
                try:
                    if btn.count() > 0 and btn.is_visible():
                        log(f"  Found and clicking: {sel}")
                        btn.click()
                        clicked_create = True
                        page.wait_for_timeout(3000)
                        page.screenshot(path="freemodel_keys2_2_after_create.png")
                        modal_text = page.locator("body").inner_text(timeout=3000)
                        log(f"  Text after create: {modal_text[:1500]}")
                        break
                except Exception as e:
                    log(f"  {sel}: {e}")

            if not clicked_create:
                log("  No create button found. Keys may be auto-created.")

            # Wait for any key to appear in API responses
            page.wait_for_timeout(3000)

            # Search again for keys after create attempt
            log("\n=== Searching for API keys after create attempt ===")
            for el in page.locator("code, pre, span, div, td, input, textarea, p").all():
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
                        m = re.search(r'\b(fe_oa_[A-Za-z0-9_-]{5,})\b', text)
                        if m:
                            log(f"  FOUND API KEY: {m.group(0)}")
                except Exception:
                    pass

            # Dump all key-related API responses
            log("\n=== Key-related API responses ===")
            for c in api_calls:
                if c.get("type") == "RES":
                    body = c.get("body", "")
                    if re.search(r'key|fe_oa|token', body, re.I) and "auth/me" not in c["url"] and "referral" not in c["url"] and "billing" not in c["url"] and "usage" not in c["url"] and "support" not in c["url"] and "logs" not in c["url"]:
                        log(f"  {c['url']}: {body[:500]}")

            log("\n=== ALL API calls ===")
            for c in api_calls:
                log(json.dumps(c))

        except Exception as e:
            log(f"Error: {e}")
            try:
                page.screenshot(path="freemodel_keys2_error.png")
            except Exception:
                pass
            import traceback
            traceback.print_exc()
        finally:
            context.close()
            browser.close()


if __name__ == "__main__":
    main()
