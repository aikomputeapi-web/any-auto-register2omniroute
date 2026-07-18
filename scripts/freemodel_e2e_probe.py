"""End-to-end probe for freemodel.dev signup flow using IMAP catchall mailbox.

Flow:
  1. Generate email via IMAP catchall (audioplexdesigns.com)
  2. Submit email on freemodel.dev/signup
  3. Retrieve the OTP code from IMAP
  4. Enter the OTP and verify
  5. Explore the dashboard / API keys page
"""
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
    print(f"[FreeModel-Probe] {msg}", flush=True)


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
    log(f"Before IDs count: {len(before_ids)}")

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
                    api_calls.append({"type": "RES", "status": res.status, "url": url, "body": body[:1000]})
                except Exception:
                    pass

        page.on("request", on_req)
        page.on("response", on_resp)

        try:
            log(f"Navigating to {FREEMODEL_SIGNUP}")
            page.goto(FREEMODEL_SIGNUP, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(2000)

            log(f"Filling email: {email}")
            page.fill("#emailInput", email)
            page.wait_for_timeout(500)

            log('Clicking "Send verification code"')
            page.click('button:has-text("Send verification code")')
            page.wait_for_timeout(4000)
            page.screenshot(path="freemodel_e2e_1_otp_screen.png")

            # Poll IMAP for OTP code
            log("Polling IMAP for OTP code (180s timeout)...")
            otp_code = None
            try:
                otp_code = mailbox.wait_for_code(
                    mail_acct,
                    keyword="",
                    timeout=180,
                    before_ids=before_ids,
                    code_pattern=r"\b(\d{6})\b",
                )
                if otp_code:
                    log(f"Extracted OTP: {otp_code}")
            except Exception as e:
                log(f"wait_for_code raised: {e}")

            if not otp_code:
                log("FAILED: Could not get OTP code from IMAP")
                page.screenshot(path="freemodel_e2e_no_otp.png")
                return

            # Enter OTP code
            log(f"Entering OTP code: {otp_code}")
            otp_inputs = page.locator('input[maxlength="1"]')
            count = otp_inputs.count()
            log(f"OTP input count: {count}")
            for i in range(min(count, len(otp_code))):
                otp_inputs.nth(i).fill(otp_code[i])
                page.wait_for_timeout(100)
            page.wait_for_timeout(500)
            page.screenshot(path="freemodel_e2e_2_otp_filled.png")

            # The form may auto-submit when all 6 digits are filled.
            # Wait for the URL to change; if it doesn't, try clicking verify or pressing Enter.
            log("Waiting for auto-submit or clicking verify...")
            pre_url = page.url
            for _ in range(10):
                if page.url != pre_url:
                    break
                page.wait_for_timeout(1000)

            if page.url == pre_url:
                # Try clicking the verify button (may still be present)
                try:
                    btn = page.locator('button:has-text("Verify & continue")').first
                    if btn.count() > 0 and btn.is_visible():
                        log("Clicking Verify & continue button...")
                        btn.click(timeout=5000)
                    else:
                        log("Verify button not visible; pressing Enter...")
                        page.keyboard.press("Enter")
                except Exception as e:
                    log(f"Verify click failed ({e}), pressing Enter...")
                    page.keyboard.press("Enter")

            page.wait_for_timeout(6000)
            log(f"URL after verify: {page.url}")
            page.screenshot(path="freemodel_e2e_3_after_verify.png", full_page=True)

            # Explore dashboard
            log("=== Exploring dashboard ===")
            log(f"Current URL: {page.url}")
            body_text = page.locator("body").inner_text(timeout=3000)
            log(f"Body text: {body_text[:2000]}")

            links = page.locator("a").all()
            log("\nLinks on dashboard:")
            for link in links[:40]:
                try:
                    href = link.get_attribute("href")
                    text = (link.inner_text(timeout=1000) or "").strip()
                    if href or text:
                        log(f"  [{text}] -> {href}")
                except Exception:
                    pass

            buttons = page.locator("button").all()
            log("\nButtons on dashboard:")
            for btn in buttons[:25]:
                try:
                    text = (btn.inner_text(timeout=1000) or "").strip()
                    if text:
                        log(f'  button: "{text}"')
                except Exception:
                    pass

            # Look for API key in the current page
            log("\n=== Searching for API key on current page ===")
            for el in page.locator("input, textarea, code, pre, span, div, p, td").all():
                try:
                    if el.is_visible():
                        text = el.inner_text(timeout=500)
                        # freemodel keys likely start with 'fm_' or similar
                        m = re.search(r'\b(fm_[A-Za-z0-9_-]{10,}|sk-[A-Za-z0-9_-]{10,}|fk_[A-Za-z0-9_-]{10,})\b', text)
                        if m:
                            log(f"  FOUND API KEY: {m.group(0)}")
                except Exception:
                    pass

            # Try common API key pages
            for path in ["/dashboard", "/api-keys", "/keys", "/settings", "/account", "/console", "/playground", "/docs", "/billing", "/keys/new"]:
                log(f"\n=== Trying {path} ===")
                try:
                    page.goto(f"{FREEMODEL_BASE}{path}", wait_until="domcontentloaded", timeout=15000)
                    page.wait_for_timeout(2500)
                    log(f"URL: {page.url}")
                    txt = page.locator("body").inner_text(timeout=3000)
                    if re.search(r"api.?key|key|token|secret|create|generate", txt, re.I):
                        log("  Contains key-related text!")
                        log(f"  Text preview: {txt[:1000]}")
                    # Search for API keys in inputs/code elements
                    for el in page.locator("input, textarea, code, pre").all():
                        try:
                            val = el.input_value() if el.evaluate("e => e.tagName") in ("INPUT", "TEXTAREA") else el.inner_text(timeout=500)
                            if val and re.match(r'^(fm_|sk-|fk_|freemodel_)[A-Za-z0-9_-]{10,}', val):
                                log(f"  FOUND API KEY in element: {val[:30]}...")
                        except Exception:
                            pass
                    page.screenshot(path=f"freemodel_e2e_4_{path.replace('/', '_')}.png")
                except Exception as e:
                    log(f"  failed: {str(e)[:100]}")

            log("\n=== API calls captured ===")
            for c in api_calls:
                log(json.dumps(c))

        except Exception as e:
            log(f"Error: {e}")
            try:
                page.screenshot(path="freemodel_e2e_error.png")
            except Exception:
                pass
            import traceback
            traceback.print_exc()
        finally:
            context.close()
            browser.close()


if __name__ == "__main__":
    main()
