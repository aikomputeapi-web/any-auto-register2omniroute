"""Probe the verification modal by clicking 'Verify now' and capturing API calls."""
import re
import time
import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.base_mailbox import ImapCatchallMailbox
from playwright.sync_api import sync_playwright


def log(msg):
    print(f"[FreeModel-Verify2] {msg}", flush=True)


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

            # Don't dismiss the account verification modal — keep it open.
            # Just dismiss the tutorial/referral modals but keep the verification one.
            for dismiss_text in ["Dismiss", "Got it"]:
                try:
                    btn = page.locator(f'button:has-text("{dismiss_text}")').first
                    if btn.count() > 0 and btn.is_visible():
                        # Check if this is the tutorial modal (has "Tutorial" text nearby)
                        btn.click(force=True)
                        page.wait_for_timeout(500)
                except Exception:
                    pass

            # Remove backdrops that block interaction but keep the verification modal
            page.evaluate("""() => {
                // Only remove backdrops if there's no verification text visible
                const body = document.body.innerText;
                if (!body.includes('Verify your account') && !body.includes('Bind phone') && !body.includes('Bind Telegram')) {
                    document.querySelectorAll('.modal-backdrop').forEach(el => el.remove());
                }
            }""")

            # If the verification modal isn't visible, click "Verify now"
            verify_modal_visible = False
            try:
                body_text = page.locator("body").inner_text(timeout=3000)
                if "Bind phone" in body_text or "Bind Telegram" in body_text or "Buy API credit" in body_text:
                    verify_modal_visible = True
                    log("Verification modal is already open!")
            except Exception:
                pass

            if not verify_modal_visible:
                log("Verification modal not open. Clicking 'Verify now'...")
                try:
                    btn = page.locator('button:has-text("Verify now")').first
                    if btn.count() > 0:
                        btn.click(force=True)
                        page.wait_for_timeout(2000)
                        page.screenshot(path="freemodel_verify2_1_modal.png")
                except Exception as e:
                    log(f"Verify now click failed: {e}")

            # Now the verification modal should be open. Dump its content.
            body_text = page.locator("body").inner_text(timeout=5000)
            log(f"\nVerification modal text:\n{body_text[:3000]}")

            # Dump all buttons in the modal
            buttons = page.locator("button").all()
            log("\nAll buttons:")
            for btn in buttons[:30]:
                try:
                    text = (btn.inner_text(timeout=1000) or "").strip()
                    if text:
                        try:
                            visible = btn.is_visible()
                        except Exception:
                            visible = False
                        log(f'  button: "{text}" visible={visible}')
                except Exception:
                    pass

            # Click "Bind Telegram" to see what happens
            log("\n=== Clicking 'Bind Telegram' ===")
            try:
                tg_btn = page.locator('button:has-text("Bind Telegram")').first
                if tg_btn.count() > 0 and tg_btn.is_visible():
                    tg_btn.click()
                    page.wait_for_timeout(3000)
                    page.screenshot(path="freemodel_verify2_2_telegram.png")
                    body_text = page.locator("body").inner_text(timeout=5000)
                    log(f"Body after Telegram click: {body_text[:2000]}")

                    # Look for telegram links or instructions
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
                else:
                    log("Bind Telegram button not found or not visible")
            except Exception as e:
                log(f"Telegram click failed: {e}")

            # Also try clicking "Buy API credit"
            log("\n=== Clicking 'Buy API credit' ===")
            try:
                buy_btn = page.locator('button:has-text("Buy API credit")').first
                if buy_btn.count() > 0 and buy_btn.is_visible():
                    buy_btn.click()
                    page.wait_for_timeout(3000)
                    page.screenshot(path="freemodel_verify2_3_buy.png")
                    body_text = page.locator("body").inner_text(timeout=5000)
                    log(f"Body after Buy click: {body_text[:2000]}")
                else:
                    log("Buy API credit button not found")
            except Exception as e:
                log(f"Buy click failed: {e}")

            # Also try the phone verification - click "Bind phone number"
            log("\n=== Clicking 'Bind phone number' ===")
            try:
                phone_btn = page.locator('button:has-text("Bind phone number")').first
                if phone_btn.count() > 0 and phone_btn.is_visible():
                    phone_btn.click()
                    page.wait_for_timeout(3000)
                    page.screenshot(path="freemodel_verify2_4_phone.png")
                    body_text = page.locator("body").inner_text(timeout=5000)
                    log(f"Body after phone click: {body_text[:2000]}")

                    # Look for phone input and send code button
                    phone_input = page.locator('input[type="tel"], input[placeholder*="phone" i], input[placeholder*="+86"]').first
                    if phone_input.count() > 0:
                        log("Found phone input!")
                        log(f"  placeholder: {phone_input.get_attribute('placeholder')}")
                        log(f"  type: {phone_input.get_attribute('type')}")

                    # Try sending a code via the API
                    log("\n=== Trying phone send-code API ===")
                    for endpoint, payload in [
                        ("/api/phone/send-code", {"phone": "+8613800138000"}),
                        ("/api/verify/phone/send", {"phone": "+8613800138000"}),
                        ("/api/sms/send", {"phone": "+8613800138000"}),
                        ("/api/phone/verify", {"phone": "+8613800138000"}),
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
                else:
                    log("Bind phone number button not found")
            except Exception as e:
                log(f"Phone click failed: {e}")

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
