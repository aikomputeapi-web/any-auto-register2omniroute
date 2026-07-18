"""Probe Telegram verification: dismiss tutorial, click Bind Telegram, capture flow."""
import re
import time
import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.base_mailbox import ImapCatchallMailbox
from playwright.sync_api import sync_playwright


def log(msg):
    print(f"[FreeModel-TG] {msg}", flush=True)


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

            # Dismiss the tutorial modal (the one with the YouTube iframe)
            # and the referral popup. Keep the account verification modal.
            log("Dismissing tutorial modal...")
            for dismiss_text in ["Dismiss", "Got it", "×", "Close"]:
                try:
                    btn = page.locator(f'button:has-text("{dismiss_text}")').first
                    if btn.count() > 0 and btn.is_visible():
                        btn.click(force=True)
                        page.wait_for_timeout(500)
                except Exception:
                    pass
            # Remove any modal-backdrop that contains the tutorial iframe
            page.evaluate("""() => {
                document.querySelectorAll('.modal-backdrop').forEach(el => {
                    if (el.querySelector('iframe[src*="youtube"]')) {
                        el.remove();
                    }
                });
                document.body.style.overflow = '';
            }""")
            page.wait_for_timeout(1000)
            page.screenshot(path="freemodel_tg_1_after_dismiss.png")

            # Now click "Bind Telegram" with force=True
            log("\n=== Clicking 'Bind Telegram' (force) ===")
            tg_btn = page.locator('button:has-text("Bind Telegram")').first
            if tg_btn.count() > 0:
                log("Found Bind Telegram button, clicking with force=True...")
                tg_btn.click(force=True)
                page.wait_for_timeout(3000)
                page.screenshot(path="freemodel_tg_2_telegram.png")
                body_text = page.locator("body").inner_text(timeout=5000)
                log(f"Body after Telegram click: {body_text[:2000]}")

                # Dump all links (looking for t.me link)
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

                # Dump all buttons
                buttons = page.locator("button").all()
                log("\nButtons after Telegram click:")
                for btn in buttons[:20]:
                    try:
                        text = (btn.inner_text(timeout=1000) or "").strip()
                        if text:
                            log(f'  button: "{text}"')
                    except Exception:
                        pass

                # Search page HTML for t.me or telegram links
                log("\n=== Searching page content for Telegram links ===")
                html = page.content()
                tg_links = re.findall(r'(https?://t\.me/[^\s"\'<>]+)', html)
                for tl in tg_links:
                    log(f"  Telegram link: {tl}")
                bot_links = re.findall(r'(@[A-Za-z0-9_]+bot)', html, re.I)
                for bl in bot_links:
                    log(f"  Bot mention: {bl}")

                # Search for any text containing telegram
                log("\n=== Searching visible text for Telegram-related content ===")
                for el in page.locator("div, span, p, code, pre, a, input, textarea").all():
                    try:
                        text = ""
                        try:
                            text = el.inner_text(timeout=500)
                        except Exception:
                            try:
                                text = el.input_value()
                            except Exception:
                                pass
                        if text and ("telegram" in text.lower() or "t.me" in text.lower() or "bot" in text.lower()):
                            log(f"  TG-related text: {text[:300]}")
                    except Exception:
                        pass
            else:
                log("Bind Telegram button not found")

            # Also try the phone verification - send a code and see what API is used
            log("\n=== Trying phone 'Send code' button ===")
            try:
                # First close the telegram modal if any, then click phone
                cancel_btn = page.locator('button:has-text("Cancel")').first
                if cancel_btn.count() > 0 and cancel_btn.is_visible():
                    cancel_btn.click(force=True)
                    page.wait_for_timeout(1000)

                # Re-open verification modal
                verify_btn = page.locator('button:has-text("Verify now")').first
                if verify_btn.count() > 0 and verify_btn.is_visible():
                    verify_btn.click(force=True)
                    page.wait_for_timeout(1000)

                phone_btn = page.locator('button:has-text("Bind phone number")').first
                if phone_btn.count() > 0 and phone_btn.is_visible():
                    phone_btn.click(force=True)
                    page.wait_for_timeout(2000)
                    page.screenshot(path="freemodel_tg_3_phone.png")

                    # Look for the phone input
                    phone_input = page.locator('input').all()
                    log(f"Inputs on phone form: {len(phone_input)}")
                    for inp in phone_input[:10]:
                        try:
                            placeholder = inp.get_attribute("placeholder")
                            type_attr = inp.get_attribute("type")
                            val = inp.input_value()
                            log(f'  input type={type_attr} placeholder={placeholder} value={val}')
                        except Exception:
                            pass

                    # Click "Send code" and capture the API call
                    send_btn = page.locator('button:has-text("Send code")').first
                    if send_btn.count() > 0 and send_btn.is_visible():
                        log("Clicking Send code...")
                        send_btn.click(force=True)
                        page.wait_for_timeout(2000)
                        page.screenshot(path="freemodel_tg_4_send_code.png")
                        body_text = page.locator("body").inner_text(timeout=3000)
                        log(f"Body after Send code: {body_text[:1000]}")
            except Exception as e:
                log(f"Phone flow error: {e}")

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
