"""Click 'RECEIVE SMS' on freereceivesms.com to find detail page, then read messages."""
import re
import time
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from playwright.sync_api import sync_playwright


def log(msg):
    print(f"[SMS-Scrape4] {msg}", flush=True)


def main():
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        context = browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        )
        page = context.new_page()

        log("=== Navigating to freereceivesms.com/en/cn/ ===")
        page.goto("https://www.freereceivesms.com/en/cn/", wait_until="domcontentloaded", timeout=20000)
        page.wait_for_timeout(3000)

        # Find and click the first "RECEIVE SMS" link
        log("Looking for 'RECEIVE SMS' links...")
        receive_links = page.locator('a:has-text("RECEIVE SMS")')
        count = receive_links.count()
        log(f"Found {count} 'RECEIVE SMS' links")

        if count > 0:
            # Get the href of the first one
            first_link = receive_links.first
            href = first_link.get_attribute("href")
            text = first_link.inner_text(timeout=1000)
            log(f"First link: text='{text}' href='{href}'")

            # Also get all hrefs
            all_hrefs = []
            for i in range(min(count, 5)):
                try:
                    h = receive_links.nth(i).get_attribute("href")
                    all_hrefs.append(h)
                    log(f"  Link {i}: href={h}")
                except Exception:
                    pass

            # Click the first one and see where it goes
            log("Clicking first 'RECEIVE SMS' link...")
            try:
                first_link.click()
                page.wait_for_timeout(3000)
                log(f"Navigated to: {page.url}")
                page.screenshot(path="freemodel_sms_detail.png")

                # Read the messages on the detail page
                body_text = page.locator("body").inner_text(timeout=3000)
                log(f"Detail page text (first 2000):\n{body_text[:2000]}")

                # Look for SMS messages
                # Messages usually have sender, content, and timestamp
                msgs = re.findall(r'(?i)(freemodel|verification|code|verify|sms).{0,200}', body_text)
                log(f"\nMessages with keywords: {msgs[:10]}")

                # Dump all text blocks that look like messages
                # SMS sites usually have table rows or div blocks with messages
                for el in page.locator("tr, .message, .sms, .msg-box, div").all():
                    try:
                        text = el.inner_text(timeout=300)
                        if text and len(text) > 10 and len(text) < 500:
                            if re.search(r'(?i)(freemodel|verification|code|otp|\d{4,6})', text):
                                log(f"  Potential message: {text[:200]}")
                    except Exception:
                        pass

            except Exception as e:
                log(f"Click error: {e}")
                # Try navigating directly
                if href:
                    full_url = href if href.startswith("http") else f"https://www.freereceivesms.com{href}"
                    log(f"Trying direct nav: {full_url}")
                    page.goto(full_url, wait_until="domcontentloaded", timeout=20000)
                    page.wait_for_timeout(3000)
                    body_text = page.locator("body").inner_text(timeout=3000)
                    log(f"Detail page text (first 2000):\n{body_text[:2000]}")

        context.close()
        browser.close()


if __name__ == "__main__":
    main()
