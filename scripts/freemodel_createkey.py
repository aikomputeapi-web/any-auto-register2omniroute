"""Quick test: create a key via POST /api/keys using the browser session.

First signs up, then tries to create a key via the API directly.
"""
import re
import time
import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.base_mailbox import ImapCatchallMailbox
from playwright.sync_api import sync_playwright


def log(msg):
    print(f"[FreeModel-CreateKey] {msg}", flush=True)


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

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False, args=["--disable-blink-features=AutomationControlled"])
        context = browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        )
        page = context.new_page()

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

            # Try creating a key via API directly (uses session cookies)
            log("\n=== Trying POST /api/keys with various payloads ===")
            for payload in [
                {"name": "auto-key"},
                {"name": "auto-key", "action": "create"},
                {},
                {"label": "auto-key"},
                {"name": "auto-key", "type": "api"},
            ]:
                log(f"  Trying payload: {json.dumps(payload)}")
                try:
                    resp = page.request.post(
                        "https://freemodel.dev/api/keys",
                        data=json.dumps(payload),
                        headers={"Content-Type": "application/json"},
                    )
                    log(f"    Status: {resp.status}")
                    body = resp.text()
                    log(f"    Body: {body[:500]}")
                    if resp.ok and "fe_oa_" in body:
                        log(f"    SUCCESS! Key created!")
                        break
                except Exception as e:
                    log(f"    Error: {e}")

            # Also try the UI flow: navigate to keys page and click Create key
            log("\n=== UI flow: navigate to dashboard/keys and click Create key ===")
            # Dismiss modals
            for dismiss_text in ["Dismiss", "Got it", "Cancel"]:
                try:
                    btn = page.locator(f'button:has-text("{dismiss_text}")').first
                    if btn.count() > 0 and btn.is_visible():
                        btn.click(force=True)
                        page.wait_for_timeout(500)
                except Exception:
                    pass
            page.evaluate("""() => document.querySelectorAll('.modal-backdrop').forEach(el => el.remove())""")

            # Click API Keys nav
            page.locator('button:has-text("API Keys")').first.click(force=True)
            page.wait_for_timeout(3000)
            log(f"URL: {page.url}")

            # Click "Create key" button (the first one in the header area)
            create_btn = page.locator('button:has-text("Create key")').first
            if create_btn.count() > 0:
                log("Clicking Create key button...")
                create_btn.click()
                page.wait_for_timeout(2000)
                page.screenshot(path="freemodel_createkey_1_modal.png")
                # Dump the modal content
                body_text = page.locator("body").inner_text(timeout=3000)
                log(f"Body text after create click: {body_text[:2000]}")
                # Look for a name input and a confirm button
                name_input = page.locator('input[type="text"], input[placeholder*="name" i]').first
                if name_input.count() > 0:
                    log("Found name input, filling...")
                    name_input.fill("auto-key")
                    page.wait_for_timeout(500)
                # Look for a confirm/create button in the modal
                for confirm_text in ["Create", "Confirm", "OK", "Submit", "Generate", "Create key", "Save"]:
                    try:
                        btn = page.locator(f'button:has-text("{confirm_text}")').first
                        if btn.count() > 0 and btn.is_visible():
                            log(f"Clicking confirm button: {confirm_text}")
                            btn.click()
                            page.wait_for_timeout(3000)
                            break
                    except Exception:
                        pass
                page.screenshot(path="freemodel_createkey_2_after_confirm.png")
                # Search for the key
                body_text = page.locator("body").inner_text(timeout=3000)
                m = re.search(r'\b(fe_oa_[A-Za-z0-9_-]{5,})\b', body_text)
                if m:
                    log(f"FOUND API KEY in UI: {m.group(0)}")
                else:
                    log(f"No key found in UI text. Body: {body_text[:1500]}")
            else:
                log("Create key button not found")

        except Exception as e:
            log(f"Error: {e}")
            import traceback
            traceback.print_exc()
        finally:
            context.close()
            browser.close()


if __name__ == "__main__":
    main()
