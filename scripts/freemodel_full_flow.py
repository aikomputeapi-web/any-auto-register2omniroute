"""Try to complete Telegram verification by opening the deepLink in a browser.

Strategy:
1. Sign up + verify OTP (create account)
2. Call /api/telegram/start-bind to get the deepLink
3. Open the deepLink in a browser -> redirects to web.telegram.org
4. If Telegram web session exists, click "Start" button
5. Poll /api/telegram/check-bind until verified
6. Create API key via POST /api/keys
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
    print(f"[FreeModel-Full] {msg}", flush=True)


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
            # Step 1: Sign up
            log(f"Signing up {email} via API...")
            resp = page.request.post(
                "https://freemodel.dev/api/auth/send-otp",
                data=json.dumps({"email": email}),
                headers={"Content-Type": "application/json"},
            )
            log(f"send-otp: {resp.status} {resp.text()}")
            if resp.status != 200 or '"ok"' not in resp.text():
                log("send-otp failed; aborting")
                return

            # Step 2: Get OTP
            otp_code = mailbox.wait_for_code(mail_acct, keyword="", timeout=180, before_ids=before_ids, code_pattern=r"\b(\d{6})\b")
            if not otp_code:
                log("FAILED: No OTP code")
                return
            log(f"Extracted OTP: {otp_code}")

            # Step 3: Verify OTP
            resp = page.request.post(
                "https://freemodel.dev/api/auth/verify-otp",
                data=json.dumps({"email": email, "code": otp_code}),
                headers={"Content-Type": "application/json"},
            )
            log(f"verify-otp: {resp.status} {resp.text()[:200]}")
            verify_data = resp.json()
            if not verify_data.get("ok"):
                log("verify-otp failed; aborting")
                return

            # Step 4: Start Telegram bind
            log("\n=== Starting Telegram bind ===")
            resp = page.request.post(
                "https://freemodel.dev/api/telegram/start-bind",
                data="{}",
                headers={"Content-Type": "application/json"},
            )
            tg_data = resp.json()
            log(f"telegram/start-bind: {resp.status} {json.dumps(tg_data)}")
            if not tg_data.get("ok"):
                log("Telegram start-bind failed; aborting")
                return

            token = tg_data.get("token", "")
            deep_link = tg_data.get("deepLink", "")
            log(f"  token: {token}")
            log(f"  deepLink: {deep_link}")

            if tg_data.get("already_verified"):
                log("  Already verified! Skipping to key creation.")
            elif deep_link:
                # Step 5: Open the deepLink in a new tab to trigger Telegram
                log(f"\n=== Opening Telegram deepLink: {deep_link} ===")
                tg_page = context.new_page()
                try:
                    tg_page.goto(deep_link, wait_until="domcontentloaded", timeout=15000)
                    tg_page.wait_for_timeout(3000)
                    log(f"Telegram page URL: {tg_page.url}")
                    tg_page.screenshot(path="freemodel_full_1_telegram.png")
                    body_text = tg_page.locator("body").inner_text(timeout=3000)
                    log(f"Telegram page text: {body_text[:500]}")

                    # If it redirected to web.telegram.org, look for a Start button
                    if "web.telegram" in tg_page.url or "telegram.org" in tg_page.url:
                        log("On Telegram web. Looking for Start button...")
                        for _ in range(10):
                            try:
                                start_btn = tg_page.locator('button:has-text("Start"), button:has-text("START"), .btn-primary:has-text("Start")').first
                                if start_btn.count() > 0 and start_btn.is_visible():
                                    log("Found Start button! Clicking...")
                                    start_btn.click()
                                    tg_page.wait_for_timeout(3000)
                                    break
                            except Exception:
                                pass
                            tg_page.wait_for_timeout(1000)
                except Exception as e:
                    log(f"Telegram page error: {e}")

                # Step 6: Poll check-bind
                log("\n=== Polling /api/telegram/check-bind ===")
                verified = False
                for i in range(30):
                    time.sleep(3)
                    resp2 = page.request.get(
                        f"https://freemodel.dev/api/telegram/check-bind?token={token}",
                    )
                    cb_data = resp2.json()
                    if i % 5 == 0:
                        log(f"  check-bind {i+1}: {resp2.status} {resp2.text()[:200]}")
                    if cb_data.get("verifiedAt") or cb_data.get("verified_at") or cb_data.get("ok"):
                        log(f"  Telegram verified! {cb_data}")
                        verified = True
                        break
                    if cb_data.get("expired"):
                        log("  Link expired!")
                        break

                if not verified:
                    log("  Telegram verification not completed (no Telegram session available).")
                    log(f"  To complete manually, open this link in Telegram: {deep_link}")
                    log("  Then re-run the script with the same account.")

            # Step 7: Try creating API key
            log("\n=== POST /api/keys ===")
            resp = page.request.post(
                "https://freemodel.dev/api/keys",
                data=json.dumps({"name": "auto-key"}),
                headers={"Content-Type": "application/json"},
            )
            log(f"keys: {resp.status} {resp.text()[:500]}")
            key_data = resp.json() if resp.ok else {}
            api_key = key_data.get("key", "") or key_data.get("secret", "")
            if api_key:
                log(f"\n*** API KEY EXTRACTED: {api_key} ***")
            else:
                log("  API key not created (verification required).")
                log(f"  Account email: {email}")
                log(f"  Telegram deepLink: {deep_link}")

        except Exception as e:
            log(f"Error: {e}")
            import traceback
            traceback.print_exc()
        finally:
            context.close()
            browser.close()


if __name__ == "__main__":
    main()
