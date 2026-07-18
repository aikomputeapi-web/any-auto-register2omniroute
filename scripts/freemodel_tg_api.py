"""Test the Telegram start-bind API and phone send-sms API with a fresh account."""
import re
import time
import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.base_mailbox import ImapCatchallMailbox
from playwright.sync_api import sync_playwright


def log(msg):
    print(f"[FreeModel-TG-API] {msg}", flush=True)


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
        browser = pw.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        context = browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        )
        page = context.new_page()

        try:
            # Signup via API (faster, no browser UI needed)
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

            # Get OTP from IMAP
            log("Polling IMAP for OTP code...")
            otp_code = mailbox.wait_for_code(mail_acct, keyword="", timeout=180, before_ids=before_ids, code_pattern=r"\b(\d{6})\b")
            if not otp_code:
                log("FAILED: No OTP code")
                return
            log(f"Extracted OTP: {otp_code}")

            # Verify OTP
            resp = page.request.post(
                "https://freemodel.dev/api/auth/verify-otp",
                data=json.dumps({"email": email, "code": otp_code}),
                headers={"Content-Type": "application/json"},
            )
            log(f"verify-otp: {resp.status} {resp.text()}")
            verify_data = resp.json()
            if not verify_data.get("ok"):
                log("verify-otp failed; aborting")
                return

            # Now try Telegram start-bind
            log("\n=== POST /api/telegram/start-bind ===")
            resp = page.request.post(
                "https://freemodel.dev/api/telegram/start-bind",
                data="{}",
                headers={"Content-Type": "application/json"},
            )
            log(f"telegram/start-bind: {resp.status}")
            log(f"body: {resp.text()[:1000]}")
            tg_data = resp.json()
            if tg_data.get("ok"):
                token = tg_data.get("token", "")
                link = tg_data.get("link", "")
                log(f"  token: {token}")
                log(f"  link: {link}")
                if tg_data.get("already_verified"):
                    log(f"  Already verified! verified_at={tg_data.get('verified_at')}")

                # If we got a link, poll check-bind
                if token:
                    log("\n=== Polling /api/telegram/check-bind ===")
                    for i in range(10):
                        time.sleep(3)
                        resp2 = page.request.get(
                            f"https://freemodel.dev/api/telegram/check-bind?token={token}",
                        )
                        log(f"  check-bind {i+1}: {resp2.status} {resp2.text()[:300]}")
                        data = resp2.json()
                        if data.get("verifiedAt") or data.get("verified_at"):
                            log("  Telegram verified!")
                            break
                        if data.get("expired"):
                            log("  Link expired!")
                            break
            else:
                log(f"  Telegram start-bind failed: {tg_data}")

            # Also try phone send-sms
            log("\n=== POST /api/phone/send-sms ===")
            resp = page.request.post(
                "https://freemodel.dev/api/phone/send-sms",
                data=json.dumps({"phone": "13800138000"}),
                headers={"Content-Type": "application/json"},
            )
            log(f"phone/send-sms: {resp.status} {resp.text()[:500]}")

            # Try creating a key (should fail without verification)
            log("\n=== POST /api/keys (expect 403) ===")
            resp = page.request.post(
                "https://freemodel.dev/api/keys",
                data=json.dumps({"name": "auto-key"}),
                headers={"Content-Type": "application/json"},
            )
            log(f"keys: {resp.status} {resp.text()[:500]}")

        except Exception as e:
            log(f"Error: {e}")
            import traceback
            traceback.print_exc()
        finally:
            context.close()
            browser.close()


if __name__ == "__main__":
    main()
