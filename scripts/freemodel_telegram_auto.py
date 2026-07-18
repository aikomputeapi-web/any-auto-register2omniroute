"""Complete the full freemodel.dev flow including Telegram verification.

Opens the Telegram deepLink in Telegram Desktop (which is running with a session),
then polls freemodel's API until verification completes, then creates the API key.
"""
import re
import time
import json
import sys
import os
import subprocess
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.base_mailbox import ImapCatchallMailbox
from playwright.sync_api import sync_playwright


def log(msg):
    print(f"[FreeModel-Auto] {msg}", flush=True)


def open_telegram_deeplink(deep_link):
    """Open a t.me deep link in Telegram Desktop."""
    if os.name == "nt":
        # Use os.startfile to open the URL with the default handler (Telegram Desktop)
        os.startfile(deep_link)
    else:
        subprocess.Popen(["xdg-open", deep_link])


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
            log("Account created successfully!")

            # Step 4: Start Telegram bind
            log("\n=== Starting Telegram bind ===")
            resp = page.request.post(
                "https://freemodel.dev/api/telegram/start-bind",
                data="{}",
                headers={"Content-Type": "application/json"},
            )
            tg_data = resp.json()
            log(f"telegram/start-bind: {json.dumps(tg_data)}")
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
                # Step 5: Open the deepLink in Telegram Desktop
                log(f"\n=== Opening Telegram deepLink in Telegram Desktop ===")
                log(f"  Deep link: {deep_link}")
                log(f"  Telegram Desktop should open the bot chat.")
                log(f"  Please click 'Start' in the Telegram bot chat to verify.")
                open_telegram_deeplink(deep_link)

                # Step 6: Poll check-bind until verified
                log("\n=== Polling /api/telegram/check-bind (waiting for Telegram Start) ===")
                verified = False
                for i in range(60):  # 60 * 3s = 180s
                    time.sleep(3)
                    resp2 = page.request.get(
                        f"https://freemodel.dev/api/telegram/check-bind?token={token}",
                    )
                    cb_text = resp2.text()
                    try:
                        cb_data = resp2.json()
                    except Exception:
                        cb_data = {}
                    if i % 5 == 0:
                        log(f"  check-bind {i+1}: {resp2.status} {cb_text[:200]}")
                    if cb_data.get("verifiedAt") or cb_data.get("verified_at") or cb_data.get("ok"):
                        log(f"  Telegram verified! {cb_data}")
                        verified = True
                        break
                    if cb_data.get("expired"):
                        log("  Link expired!")
                        break

                if not verified:
                    log("  Telegram verification not completed within 180s.")
                    log(f"  You can manually open: {deep_link}")
                    log("  Then run the key extraction step separately.")

            # Step 7: Try creating API key
            log("\n=== POST /api/keys ===")
            resp = page.request.post(
                "https://freemodel.dev/api/keys",
                data=json.dumps({"name": "auto-key"}),
                headers={"Content-Type": "application/json"},
            )
            log(f"keys: {resp.status} {resp.text()[:500]}")
            try:
                key_data = resp.json()
            except Exception:
                key_data = {}
            api_key = key_data.get("key", "") or key_data.get("secret", "") or key_data.get("full_key", "")
            if not api_key and isinstance(key_data, dict):
                # Try to find any key-like field
                for k, v in key_data.items():
                    if isinstance(v, str) and re.match(r'^(fe_oa_|sk-|fk_)[A-Za-z0-9_-]{10,}', v):
                        api_key = v
                        break

            if api_key:
                log(f"\n{'='*60}")
                log(f"*** SUCCESS! API KEY EXTRACTED: {api_key} ***")
                log(f"{'='*60}")
                log(f"  Email: {email}")
                log(f"  API Key: {api_key}")
            else:
                log(f"\n  API key not created. Account: {email}")
                log(f"  Verification may be required. DeepLink: {deep_link}")

        except Exception as e:
            log(f"Error: {e}")
            import traceback
            traceback.print_exc()
        finally:
            context.close()
            browser.close()


if __name__ == "__main__":
    main()
