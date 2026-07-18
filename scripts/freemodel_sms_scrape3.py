"""Carefully inspect freereceivesms.com to find phone detail page URLs."""
import re
import time
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from playwright.sync_api import sync_playwright


def log(msg):
    print(f"[SMS-Scrape3] {msg}", flush=True)


def main():
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        context = browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        )
        page = context.new_page()

        log("=== Inspecting freereceivesms.com page structure ===")
        try:
            page.goto("https://www.freereceivesms.com/en/cn/", wait_until="domcontentloaded", timeout=20000)
            page.wait_for_timeout(3000)

            # Dump all links with hrefs
            links = page.locator("a[href]").all()
            log(f"Total a[href] links: {len(links)}")
            for link in links[:80]:
                try:
                    href = link.get_attribute("href") or ""
                    text = (link.inner_text(timeout=500) or "").strip()
                    if href and not href.startswith("#") and not href.startswith("javascript"):
                        if "162" in text or "162" in href or "/cn/" in href or "/8" in href or "phone" in href.lower():
                            log(f"  [{text[:50]}] -> {href}")
                except Exception:
                    pass

            # Also dump the body text to see phone numbers and their context
            body_text = page.locator("body").inner_text(timeout=3000)
            log(f"\nBody text (first 2000):\n{body_text[:2000]}")

            # Try clicking on a phone number element
            log("\n=== Looking for clickable phone elements ===")
            # Phone numbers might be in div/span/a elements
            for sel in ['a:has-text("16265813251")', 'div:has-text("16265813251")', 'span:has-text("16265813251")']:
                el = page.locator(sel).first
                if el.count() > 0:
                    log(f"  Found: {sel}")
                    tag = el.evaluate("e => e.tagName")
                    href = el.get_attribute("href") or ""
                    onclick = el.get_attribute("onclick") or ""
                    log(f"    tag={tag} href={href} onclick={onclick}")
                    # Try clicking it
                    if href and href != "#":
                        full_url = href if href.startswith("http") else f"https://www.freereceivesms.com{href}"
                        log(f"    Navigating to: {full_url}")
                        page.goto(full_url, wait_until="domcontentloaded", timeout=20000)
                        page.wait_for_timeout(3000)
                        detail_text = page.locator("body").inner_text(timeout=3000)
                        log(f"    Detail page text (first 1500): {detail_text[:1500]}")
                    break

        except Exception as e:
            log(f"Error: {e}")

        # Also try quackr.io with detail page
        log("\n=== Trying quackr.io detail page ===")
        try:
            page.goto("https://quackr.io/temporary-numbers/china", wait_until="domcontentloaded", timeout=20000)
            page.wait_for_timeout(3000)
            # Find phone links
            links = page.locator("a[href]").all()
            for link in links[:30]:
                try:
                    href = link.get_attribute("href") or ""
                    text = (link.inner_text(timeout=500) or "").strip()
                    if "168" in text or "166" in text or "phone" in href.lower() or "number" in href.lower():
                        log(f"  [{text}] -> {href}")
                except Exception:
                    pass

            # Try the phone number detail page
            test_phone = "16872978524"
            for url_fmt in [
                f"https://quackr.io/temporary-numbers/china/{test_phone}",
                f"https://quackr.io/temporary-numbers/{test_phone}",
            ]:
                log(f"\n  Trying: {url_fmt}")
                try:
                    page.goto(url_fmt, wait_until="domcontentloaded", timeout=20000)
                    page.wait_for_timeout(3000)
                    detail_text = page.locator("body").inner_text(timeout=3000)
                    log(f"    Detail page text (first 1500): {detail_text[:1500]}")
                    # Look for SMS messages
                    msgs = re.findall(r'(?i)(freemodel|verification|code|sms).{0,200}', detail_text)
                    if msgs:
                        log(f"    Found messages: {msgs[:5]}")
                except Exception as e:
                    log(f"    Error: {e}")
        except Exception as e:
            log(f"  Error: {e}")

        context.close()
        browser.close()


if __name__ == "__main__":
    main()
