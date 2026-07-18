"""Probe the account verification flow (Telegram binding)."""
import re
import time
import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.base_mailbox import ImapCatchallMailbox
from playwright.sync_api import sync_playwright


def log(msg):
    print(f"[FreeModel-Verify] {msg}", flush=True)


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
    before_ids = mailbox.get_current_ids(mail_acct)

    api_calls = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False, args=["--disable-blink-features=AutomationControlled"])
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
            page.goto("https://freemodel.dev/signup", wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(2000)
            page.fill("#emailInput", email)
            page.wait_for_timeout(500)
            page.click('button:has-text("Send verification code")')
            page.wait_for_timeout(4000)

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

            # Dismiss modals
            for dismiss_text in ["Dismiss", "Got it"]:
                try:
                    btn = page.locator(f'button:has-text("{dismiss_text}")').first
                    if btn.count() > 0 and btn.is_visible():
                        btn.click(force=True)
                        page.wait_for_timeout(500)
                except Exception:
                    pass
            page.evaluate("""() => document.querySelectorAll('.modal-backdrop').forEach(el => el.remove())""")

            # Click "Bind Telegram" button
            log("\n=== Clicking 'Bind Telegram' ===")
            tg_btn = page.locator('button:has-text("Bind Telegram")').first
            if tg_btn.count() > 0:
                log("Found Bind Telegram button, clicking...")
                tg_btn.click(force=True)
                page.wait_for_timeout(3000)
                page.screenshot(path="freemodel_verify_1_telegram.png")
                body_text = page.locator("body").inner_text(timeout=5000)
                log(f"Body text after Telegram click: {body_text[:2000]}")

                # Dump all buttons and links
                buttons = page.locator("button").all()
                log("\nButtons after Telegram click:")
                for btn in buttons[:20]:
                    try:
                        text = (btn.inner_text(timeout=1000) or "").strip()
                        if text:
                            log(f'  button: "{text}"')
                    except Exception:
                        pass

                links = page.locator("a").all()
                log("\nLinks after Telegram click:")
                for link in links[:20]:
                    try:
                        href = link.get_attribute("href")
                        text = (link.inner_text(timeout=1000) or "").strip()
                        if href or text:
                            log(f'  [{text}] -> {href}')
                    except Exception:
                        pass

                # Look for a Telegram bot link or verification code
                log("\n=== Searching for Telegram bot link or code ===")
                for el in page.locator("a, code, pre, span, div, p, input, textarea").all():
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
                            # Look for telegram links or codes
                            if "t.me" in text or "telegram" in text.lower() or "@freemodel" in text.lower():
                                log(f"  Telegram-related: {text[:200]}")
                            if re.search(r'\b[A-Za-z0-9]{6,}\b', text) and len(text) < 100:
                                log(f"  Short code-like text: {text}")
                    except Exception:
                        pass
            else:
                log("Bind Telegram button not found. Looking for verification options...")
                body_text = page.locator("body").inner_text(timeout=3000)
                log(f"Body text: {body_text[:2000]}")

                # Try the Account Verification section
                log("\n=== Looking for verification options ===")
                for vbtn_text in ["Bind phone number", "Bind Telegram", "Buy API credit", "Verify now", "Send code"]:
                    try:
                        btn = page.locator(f'button:has-text("{vbtn_text}")').first
                        if btn.count() > 0:
                            log(f"  Found: {vbtn_text} (visible={btn.is_visible()})")
                    except Exception:
                        pass

            # Also try the phone verification API
            log("\n=== Trying phone verification APIs ===")
            for endpoint, payload in [
                ("/api/verify/phone", {"phone": "+1234567890"}),
                ("/api/verify/send-code", {"phone": "+1234567890"}),
                ("/api/verify/telegram", {}),
                ("/api/verify/telegram/start", {}),
                ("/api/auth/verify", {}),
                ("/api/verify", {}),
            ]:
                try:
                    resp = page.request.post(
                        f"https://freemodel.dev{endpoint}",
                        data=json.dumps(payload),
                        headers={"Content-Type": "application/json"},
                    )
                    log(f"  {endpoint}: {resp.status} {resp.text()[:300]}")
                except Exception as e:
                    log(f"  {endpoint}: error {e}")

            # Also try GET endpoints
            for endpoint in ["/api/verify/telegram", "/api/verify/status", "/api/verify/telegram/status"]:
                try:
                    resp = page.request.get(f"https://freemodel.dev{endpoint}")
                    log(f"  GET {endpoint}: {resp.status} {resp.text()[:300]}")
                except Exception as e:
                    log(f"  GET {endpoint}: error {e}")

            log("\n=== All API calls ===")
            for c in api_calls:
                log(json.dumps(c))

        except Exception as e:
            log(f"Error: {e}")
            import traceback
            traceback.print_exc()
        finally:
            context.close()
            browser.close()


if __name__ == "__main__":
    main()
