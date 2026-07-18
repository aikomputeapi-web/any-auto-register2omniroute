"""Focused test: create mail.tm mailbox, send freemodel OTP, check delivery."""
import sys
import os
import time
import re

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests
from core.mailtm_mailbox import MailTmMailbox


def log(msg):
    print(f"[MailTest] {msg}", flush=True)


def main():
    mailbox = MailTmMailbox()
    mailbox._log_fn = log

    log("Creating mail.tm mailbox...")
    mail_acct = mailbox.get_email()
    email = mail_acct.email
    token = mail_acct.extra.get("token")
    log(f"Mailbox ready: {email}")
    before_ids = mailbox.get_current_ids(mail_acct)

    log(f"Sending OTP to {email} via freemodel API...")
    r = requests.post(
        "https://freemodel.dev/api/auth/send-otp",
        json={"email": email},
        headers={"Content-Type": "application/json"},
        timeout=15,
    )
    log(f"send-otp response: {r.status_code} {r.text}")
    if r.status_code != 200 or '"ok"' not in r.text:
        log("send-otp did not return ok; aborting")
        return

    log("Polling mail.tm for the OTP email (up to 180s)...")
    for attempt in range(60):
        time.sleep(3)
        try:
            r2 = requests.get(
                "https://api.mail.tm/messages",
                headers={"Authorization": f"Bearer {token}", "accept": "application/json"},
                timeout=10,
            )
            data = r2.json()
            msgs = data.get("hydra:member", data) if isinstance(data, dict) else data
            log(f"  attempt {attempt+1}: {len(msgs)} messages")
            for m in msgs:
                mid = m.get("id")
                log(f"    msg: subject={m.get('subject', '')} from={m.get('from', {}).get('address', '')}")
                detail = requests.get(
                    f"https://api.mail.tm/messages/{mid}",
                    headers={"Authorization": f"Bearer {token}", "accept": "application/json"},
                    timeout=10,
                ).json()
                text = f"{detail.get('subject','')} {detail.get('text','')} {detail.get('intro','')}"
                log(f"    body preview: {detail.get('text','')[:400]}")
                match = re.search(r"\b(\d{6})\b", text)
                if match:
                    log(f"    EXTRACTED OTP: {match.group(1)}")
                    return
        except Exception as e:
            log(f"  poll error: {e}")

    log("FAILED: No OTP email arrived after 180s")


if __name__ == "__main__":
    main()
