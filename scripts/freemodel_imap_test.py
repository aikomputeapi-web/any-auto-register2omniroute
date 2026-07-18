"""Test: send freemodel OTP and retrieve it via IMAP catchall mailbox."""
import sys
import os
import time
import re
import email as email_mod

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests
from core.base_mailbox import ImapCatchallMailbox


def log(msg):
    print(f"[IMAPTest] {msg}", flush=True)


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

    # Generate a fresh email
    mail_acct = mailbox.get_email()
    target_email = mail_acct.email
    log(f"Generated email: {target_email}")
    before_ids = mailbox.get_current_ids(mail_acct)
    log(f"Before IDs count: {len(before_ids)}")

    # Send OTP via freemodel API
    log(f"Sending OTP to {target_email}...")
    r = requests.post(
        "https://freemodel.dev/api/auth/send-otp",
        json={"email": target_email},
        headers={"Content-Type": "application/json"},
        timeout=15,
    )
    log(f"send-otp response: {r.status_code} {r.text}")
    if r.status_code != 200 or '"ok"' not in r.text:
        log("send-otp did not return ok; aborting")
        return

    # Poll IMAP for the OTP using the mailbox's wait_for_code
    log("Polling IMAP for OTP code (up to 180s)...")
    try:
        code = mailbox.wait_for_code(
            mail_acct,
            keyword="",
            timeout=180,
            before_ids=before_ids,
            code_pattern=r"\b(\d{6})\b",
        )
        if code:
            log(f"SUCCESS! Extracted OTP: {code}")
        else:
            log("wait_for_code returned empty")
    except Exception as e:
        log(f"wait_for_code failed: {e}")


if __name__ == "__main__":
    main()
