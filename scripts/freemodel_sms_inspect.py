"""Inspect the supercloudsms detail page to understand the SMS message format."""
import re
import time
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from playwright.sync_api import sync_playwright


def log(msg):
    print(f"[SMS-Inspect] {msg}", flush=True)


def main():
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        context = browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        )
        page = context.new_page()

        # Visit the phone detail page that we sent the SMS to
        phone_url = "https://www.supercloudsms.com/en/message/8618425267312.html"
        log(f"Visiting {phone_url}...")
        page.goto(phone_url, wait_until="domcontentloaded", timeout=20000)
        page.wait_for_timeout(3000)

        body_text = page.locator("body").inner_text(timeout=5000)
        log(f"Full page text:\n{body_text[:5000]}")

        # Also look at the HTML structure
        log("\n=== Looking for message table/rows ===")
        for sel in ["tr", ".message-item", ".sms-item", "table tr", ".row", "[class*='message']", "[class*='sms']"]:
            els = page.locator(sel).all()
            if els:
                log(f"  {sel}: {len(els)} elements")
                for el in els[:10]:
                    try:
                        text = el.inner_text(timeout=500)
                        if text and len(text.strip()) > 5:
                            log(f"    {text[:200]}")
                    except Exception:
                        pass

        # Dump all text blocks
        log("\n=== All text blocks ===")
        for el in page.locator("div, p, span, td, li").all():
            try:
                text = el.inner_text(timeout=300)
                if text and len(text.strip()) > 10 and len(text) < 500:
                    # Check if it contains a number that looks like a code
                    if re.search(r'\b\d{4,8}\b', text):
                        log(f"  [{text[:200]}]")
            except Exception:
                pass

        context.close()
        browser.close()


if __name__ == "__main__":
    main()
