"""
freemodel.dev account registration + API key extraction with manual phone verification.

This version uses a phone number you provide and asks you to enter the SMS code
you receive on that phone, making it work with real Chinese phone numbers.

Usage:
  python scripts/freemodel_manual_phone.py --phone 13800138000
  python scripts/freemodel_manual_phone.py --phone 13800138000 --headless
"""
import re
import time
import json
import sys
import os
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.base_mailbox import ImapCatchallMailbox
from playwright.sync_api import sync_playwright

FREEMODEL_BASE = "https://freemodel.dev"


def log(msg):
    print(f"[FreeModel] {msg}", flush=True)


def main():
    parser = argparse.ArgumentParser(description="FreeModel.dev auto registration with manual phone")
    parser.add_argument("--phone", required=True, help="Chinese phone number (11 digits, e.g. 13800138000)")
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--email-domain", default="audioplexdesigns.com")
    parser.add_argument("--imap-server", default="imap.titan.email")
    parser.add_argument("--imap-port", type=int, default=993)
    parser.add_argument("--imap-user", default="admin@audioplexdesigns.com")
    parser.add_argument("--imap-pass", default="Dirty2020!")
    parser.add_argument("--key-name", default="auto-key")
    parser.add_argument("--otp-timeout", type=int, default=180)
    args = parser.parse_args()

    phone = args.phone.strip().replace("+86", "").replace(" ", "")
    if not re.match(r'^1[3-9]\d{9}$', phone):
        log(f"ERROR: Invalid Chinese phone number: {phone}")
        log("Must be 11 digits starting with 1[3-9], e.g. 13800138000")
        return None

    mailbox = ImapCatchallMailbox(
        imap_server=args.imap_server,
        imap_port=args.imap_port,
        imap_username=args.imap_user,
        imap_password=args.imap_pass,
        domain=args.email_domain,
        folders="INBOX",
    )
    mailbox._log_fn = log

    log("Generating email via IMAP catchall...")
    mail_acct = mailbox.get_email()
    email = mail_acct.email
    before_ids = mailbox.get_current_ids(mail_acct)
    log(f"Email ready: {email}")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=args.headless,
            args=["--disable-blink-features=AutomationControlled"],
        )
        context = browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        )
        page = context.new_page()

        try:
            # === Step 1: Sign up ===
            log(f"\n=== Step 1: Sign up {email} ===")
            log("  Sending OTP...")
            resp = page.request.post(
                f"{FREEMODEL_BASE}/api/auth/send-otp",
                data=json.dumps({"email": email}),
                headers={"Content-Type": "application/json"},
            )
            log(f"  send-otp: {resp.status} {resp.text()[:100]}")
            if resp.status != 200 or '"ok"' not in resp.text():
                log("  FAILED: send-otp did not return ok")
                return None

            log("  Waiting for OTP email...")
            otp_code = mailbox.wait_for_code(
                mail_acct, keyword="", timeout=args.otp_timeout,
                before_ids=before_ids, code_pattern=r"\b(\d{6})\b",
            )
            if not otp_code:
                log("  FAILED: Could not retrieve OTP code from mailbox")
                return None
            log(f"  OTP received: {otp_code}")

            log("  Verifying OTP...")
            resp = page.request.post(
                f"{FREEMODEL_BASE}/api/auth/verify-otp",
                data=json.dumps({"email": email, "code": otp_code}),
                headers={"Content-Type": "application/json"},
            )
            log(f"  verify-otp: {resp.status} {resp.text()[:200]}")
            try:
                vdata = resp.json()
                if not vdata.get("ok"):
                    log("  FAILED: verify-otp did not return ok")
                    return None
            except Exception:
                log("  FAILED: verify-otp response parse error")
                return None
            log("  Account created successfully!")

            # === Step 2: Send SMS to the provided phone number ===
            log(f"\n=== Step 2: Send SMS to {phone} ===")
            resp = page.request.post(
                f"{FREEMODEL_BASE}/api/phone/send-sms",
                data=json.dumps({"phone": phone}),
                headers={"Content-Type": "application/json"},
            )
            log(f"  send-sms: {resp.status} {resp.text()[:200]}")
            if resp.status != 200:
                log("  FAILED: send-sms did not return ok")
                return None

            # === Step 3: Ask user for the SMS code ===
            log(f"\n=== Step 3: Enter SMS code ===")
            log(f"  SMS sent to {phone}. Please check your phone for the verification code.")
            log(f"  The message is from FreeModel and contains a 6-digit code.")
            sms_code = input("  Enter the 6-digit SMS code: ").strip()
            if not sms_code or not re.match(r'^\d{4,8}$', sms_code):
                log("  Invalid code entered")
                return None
            log(f"  Code entered: {sms_code}")

            # === Step 4: Verify phone ===
            log(f"\n=== Step 4: Verify phone ===")
            resp = page.request.post(
                f"{FREEMODEL_BASE}/api/phone/verify",
                data=json.dumps({"phone": phone, "code": sms_code}),
                headers={"Content-Type": "application/json"},
            )
            log(f"  phone/verify: {resp.status} {resp.text()[:200]}")
            try:
                vdata = resp.json()
                if not (vdata.get("ok") or vdata.get("success") or resp.status == 200):
                    log(f"  FAILED: phone verification failed: {vdata}")
                    return None
            except Exception:
                if resp.status != 200:
                    log("  FAILED: phone verification failed")
                    return None
            log("  Phone verified!")

            # === Step 5: Create API key ===
            log(f"\n=== Step 5: Create API key ===")
            log(f"  Creating API key '{args.key_name}'...")
            resp = page.request.post(
                f"{FREEMODEL_BASE}/api/keys",
                data=json.dumps({"name": args.key_name}),
                headers={"Content-Type": "application/json"},
            )
            log(f"  POST /api/keys: {resp.status} {resp.text()[:500]}")

            api_key = None
            try:
                kdata = resp.json()
                for field in ["key", "secret", "full_key", "apiKey", "value", "plaintext"]:
                    val = kdata.get(field, "")
                    if val and re.match(r'^(fe_oa_|sk-|fk_)[A-Za-z0-9_-]{5,}', val):
                        api_key = val
                        break
                if not api_key:
                    body = resp.text()
                    m = re.search(r'\b(fe_oa_[A-Za-z0-9_-]{5,})\b', body)
                    if m:
                        api_key = m.group(0)
            except Exception:
                pass

            if api_key:
                log(f"\n{'='*60}")
                log(f"SUCCESS!")
                log(f"  Email:   {email}")
                log(f"  Phone:   +86{phone}")
                log(f"  API Key: {api_key}")
                log(f"{'='*60}")
                result = {"email": email, "api_key": api_key, "phone": phone, "platform": "freemodel"}
                with open("freemodel_account.json", "w") as f:
                    json.dump(result, f, indent=2)
                log(f"  Saved to freemodel_account.json")
                return result
            else:
                log("  FAILED: Could not create API key")
                return None

        except Exception as e:
            log(f"Error: {e}")
            import traceback
            traceback.print_exc()
            return None
        finally:
            context.close()
            browser.close()


if __name__ == "__main__":
    result = main()
    if result and result.get("api_key"):
        print(f"\nFINAL RESULT: {json.dumps(result)}")
        sys.exit(0)
    else:
        print("\nFINAL RESULT: FAILED")
        sys.exit(1)
