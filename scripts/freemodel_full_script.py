"""
freemodel.dev automatic account registration + API key extraction.

Full flow:
  1. Generate email via IMAP catchall mailbox
  2. Sign up on freemodel.dev (email OTP)
  3. Get a free temp China +86 phone number from supercloudsms.com
  4. Send SMS verification code via freemodel's /api/phone/send-sms
  5. Read the SMS code from supercloudsms.com
  6. Verify the phone via /api/phone/verify
  7. Create an API key via /api/keys
  8. Extract and return the API key

Requirements:
  - Python with playwright, requests
  - IMAP catchall mailbox configured
  - Chrome/Chromium installed

Usage:
  python scripts/freemodel_full_script.py
  python scripts/freemodel_full_script.py --headless
  python scripts/freemodel_full_script.py --email-domain yourdomain.com
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
FREEMODEL_SIGNUP = f"{FREEMODEL_BASE}/signup"
SUPERLOUDSMS_LIST = "https://www.supercloudsms.com/en/country/china/1.html"


def log(msg):
    print(f"[FreeModel] {msg}", flush=True)


# ---------------------------------------------------------------------------
# SMS provider: supercloudsms.com
# ---------------------------------------------------------------------------

def get_china_phone_numbers(page):
    """Scrape available Chinese phone numbers from supercloudsms.com."""
    log("Fetching Chinese phone numbers from supercloudsms.com...")
    page.goto(SUPERLOUDSMS_LIST, wait_until="domcontentloaded", timeout=20000)
    page.wait_for_timeout(3000)

    links = page.locator('a[href*="/en/message/"]').all()
    phones = []
    for link in links:
        try:
            href = link.get_attribute("href") or ""
            m = re.search(r'/en/message/(\d+)\.html', href)
            if m:
                full = m.group(1)  # e.g. 8618958009044
                if full.startswith("86") and len(full) == 13:
                    phone = full[2:]  # strip 86 prefix -> 11 digits
                    phones.append({"phone": phone, "full": full, "url": f"https://www.supercloudsms.com{href}"})
        except Exception:
            pass

    seen = set()
    unique = []
    for p in phones:
        if p["phone"] not in seen:
            seen.add(p["phone"])
            unique.append(p)

    log(f"  Found {len(unique)} phone numbers: {[p['phone'] for p in unique[:10]]}")
    return unique


def read_sms_code(page, phone_url, sender_keyword="FreeModel", timeout=180):
    """Poll the supercloudsms detail page for an SMS containing a verification code.

    The SMS messages on supercloudsms are formatted as:
        <time> ago
        <sender_id>
        【<sender_name>】验证码 <code>，...

    We look for a message from "FreeModel" (the sender name) and extract
    the 6-digit verification code from that specific message.
    """
    log(f"Polling SMS at {phone_url} (timeout {timeout}s)...")
    deadline = time.time() + timeout
    poll_interval = 8  # seconds between polls
    while time.time() < deadline:
        try:
            page.goto(phone_url, wait_until="domcontentloaded", timeout=15000)
            page.wait_for_timeout(2000)
            body_text = page.locator("body").inner_text(timeout=3000)

            # Look for FreeModel in the message text (sender name in 【brackets】 or plain text)
            # The SMS from FreeModel will contain "FreeModel" somewhere in the message body
            lines = body_text.split("\n")
            for i, line in enumerate(lines):
                if "freemodel" in line.lower() or "free model" in line.lower() or "free_model" in line.lower():
                    # Get the full message context (this line + surrounding lines)
                    context = " ".join(lines[max(0, i - 2):i + 3])
                    log(f"  Found FreeModel SMS: {context[:300]}")
                    # Extract 6-digit code from this message
                    # The code appears after 验证码/code/verification or as a standalone 6-digit number
                    codes = re.findall(r'\b(\d{6})\b', context)
                    if codes:
                        log(f"  Extracted SMS code: {codes[0]}")
                        return codes[0]
                    # Try 4-8 digit codes as fallback
                    codes = re.findall(r'\b(\d{4,8})\b', context)
                    if codes:
                        log(f"  Extracted SMS code: {codes[-1]}")
                        return codes[-1]

            # If no FreeModel message found yet, wait and retry
            remaining = int(deadline - time.time())
            if remaining > 0:
                log(f"  No FreeModel SMS yet, {remaining}s remaining...")

        except Exception as e:
            log(f"  Poll error: {e}")

        time.sleep(poll_interval)

    log("  SMS code not received within timeout")
    return None


# ---------------------------------------------------------------------------
# Main flow
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="FreeModel.dev auto registration")
    parser.add_argument("--headless", action="store_true", help="Run browser headless")
    parser.add_argument("--email-domain", default="audioplexdesigns.com", help="IMAP catchall domain")
    parser.add_argument("--imap-server", default="imap.titan.email")
    parser.add_argument("--imap-port", type=int, default=993)
    parser.add_argument("--imap-user", default="admin@audioplexdesigns.com")
    parser.add_argument("--imap-pass", default="Dirty2020!")
    parser.add_argument("--key-name", default="auto-key")
    parser.add_argument("--otp-timeout", type=int, default=180)
    parser.add_argument("--sms-timeout", type=int, default=300)
    args = parser.parse_args()

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
        sms_page = context.new_page()

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

            # === Step 2: Get phone number ===
            log(f"\n=== Step 2: Get Chinese phone number ===")
            phones = get_china_phone_numbers(sms_page)
            if not phones:
                log("  FAILED: No phone numbers available")
                return None

            api_key = None
            for phone_info in phones[:3]:
                phone = phone_info["phone"]
                log(f"\n  Trying phone: {phone}")

                # === Step 3: Send SMS ===
                # freemodel expects the raw 11-digit Chinese mobile number (no +86 prefix)
                # validated server-side against ^1[3-9]\d{9}$
                log("  Sending SMS verification code...")
                resp = page.request.post(
                    f"{FREEMODEL_BASE}/api/phone/send-sms",
                    data=json.dumps({"phone": phone}),
                    headers={"Content-Type": "application/json"},
                )
                log(f"  send-sms: {resp.status} {resp.text()[:200]}")
                if resp.status != 200:
                    log(f"  send-sms failed for {phone}, trying next...")
                    # freemodel rate-limits SMS sending (429), wait longer between attempts
                    time.sleep(30)
                    continue

                # === Step 4: Read SMS code ===
                sms_url = f"https://www.supercloudsms.com/en/message/86{phone}.html"
                log(f"  Polling for SMS at {sms_url}...")
                sms_code = read_sms_code(sms_page, sms_url, sender_keyword="FreeModel", timeout=args.sms_timeout)
                if not sms_code:
                    log(f"  No SMS code received for +86{phone}, trying next...")
                    continue

                # === Step 5: Verify phone ===
                log(f"  Verifying phone with code {sms_code}...")
                resp = page.request.post(
                    f"{FREEMODEL_BASE}/api/phone/verify",
                    data=json.dumps({"phone": phone, "code": sms_code}),
                    headers={"Content-Type": "application/json"},
                )
                log(f"  phone/verify: {resp.status} {resp.text()[:200]}")
                try:
                    vdata = resp.json()
                    if vdata.get("ok") or vdata.get("success") or resp.status == 200:
                        log("  Phone verified!")

                        # === Step 6: Create API key ===
                        log(f"\n=== Step 6: Create API key ===")
                        log(f"  Creating API key '{args.key_name}'...")
                        resp = page.request.post(
                            f"{FREEMODEL_BASE}/api/keys",
                            data=json.dumps({"name": args.key_name}),
                            headers={"Content-Type": "application/json"},
                        )
                        log(f"  POST /api/keys: {resp.status} {resp.text()[:500]}")
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
                            break
                        else:
                            log("  Key creation failed after verification")
                    else:
                        log(f"  Phone verification failed: {vdata}")
                except Exception:
                    log(f"  Phone verify response error")
                time.sleep(2)

            if api_key:
                log(f"\n{'='*60}")
                log(f"SUCCESS!")
                log(f"  Email:   {email}")
                log(f"  API Key: {api_key}")
                log(f"{'='*60}")
                result = {"email": email, "api_key": api_key, "platform": "freemodel"}
                with open("freemodel_account.json", "w") as f:
                    json.dump(result, f, indent=2)
                log(f"  Saved to freemodel_account.json")
                return result
            else:
                log(f"\nFAILED: Could not create API key")
                log(f"  Account email: {email}")
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
        print("\nFINAL RESULT: FAILED to extract API key")
        sys.exit(1)
