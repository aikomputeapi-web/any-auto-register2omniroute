"""Scrape free temp China +86 phone numbers from SMS receiving websites using Playwright."""
import re
import time
import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from playwright.sync_api import sync_playwright


def log(msg):
    print(f"[SMS-Scrape] {msg}", flush=True)


def main():
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        context = browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        )
        page = context.new_page()

        # Try receive-sms.cc
        log("=== Trying receive-sms.cc ===")
        try:
            page.goto("https://receive-sms.cc/China-Phone-Number/", wait_until="domcontentloaded", timeout=20000)
            page.wait_for_timeout(3000)
            html = page.content()
            # Find phone numbers (Chinese mobile: 1[3-9]xxxxxxxxx, 11 digits)
            phones = re.findall(r'\b(1[3-9]\d{9})\b', html)
            unique_phones = list(dict.fromkeys(phones))  # preserve order, dedupe
            log(f"  Found {len(unique_phones)} phone numbers: {unique_phones[:10]}")

            # Find links to individual phone pages
            links = page.locator("a").all()
            phone_links = []
            for link in links:
                try:
                    href = link.get_attribute("href") or ""
                    text = (link.inner_text(timeout=500) or "").strip()
                    # Match phone numbers in the link text or href
                    for p in unique_phones[:10]:
                        if p in text or p in href:
                            phone_links.append({"phone": p, "text": text, "href": href})
                            break
                except Exception:
                    pass
            log(f"  Phone detail links: {phone_links[:5]}")

            if phone_links:
                # Visit the first phone's detail page
                first = phone_links[0]
                phone = first["phone"]
                href = first["href"]
                if not href.startswith("http"):
                    href = "https://receive-sms.cc" + href if href.startswith("/") else f"https://receive-sms.cc/{href}"
                log(f"\n  Visiting detail page for {phone}: {href}")
                page.goto(href, wait_until="domcontentloaded", timeout=20000)
                page.wait_for_timeout(3000)
                detail_html = page.content()
                # Look for SMS messages
                # Messages usually contain "FreeModel" or verification codes
                messages = re.findall(r'(?i)(freemodel|free model|verification|code|verify).{0,200}', detail_html)
                log(f"  Messages containing 'freemodel/code': {messages[:5]}")
                # Dump some text from the page
                body_text = page.locator("body").inner_text(timeout=3000)
                log(f"  Page text (first 1000): {body_text[:1000]}")
        except Exception as e:
            log(f"  Error: {e}")

        # Try smsonline.cloud
        log("\n=== Trying smsonline.cloud ===")
        try:
            page.goto("https://www.smsonline.cloud/country/China", wait_until="domcontentloaded", timeout=20000)
            page.wait_for_timeout(3000)
            html = page.content()
            phones = re.findall(r'\b(1[3-9]\d{9})\b', html)
            unique_phones = list(dict.fromkeys(phones))
            log(f"  Found {len(unique_phones)} phones: {unique_phones[:10]}")

            links = page.locator("a").all()
            phone_links = []
            for link in links:
                try:
                    href = link.get_attribute("href") or ""
                    text = (link.inner_text(timeout=500) or "").strip()
                    for p in unique_phones[:10]:
                        if p in text or p in href:
                            phone_links.append({"phone": p, "text": text, "href": href})
                            break
                except Exception:
                    pass
            log(f"  Phone detail links: {phone_links[:5]}")
        except Exception as e:
            log(f"  Error: {e}")

        # Try freereceivesms
        log("\n=== Trying freereceivesms.com ===")
        try:
            page.goto("https://www.freereceivesms.com/en/cn/", wait_until="domcontentloaded", timeout=20000)
            page.wait_for_timeout(3000)
            html = page.content()
            phones = re.findall(r'\b(1[3-9]\d{9})\b', html)
            unique_phones = list(dict.fromkeys(phones))
            log(f"  Found {len(unique_phones)} phones: {unique_phones[:10]}")

            links = page.locator("a").all()
            phone_links = []
            for link in links:
                try:
                    href = link.get_attribute("href") or ""
                    text = (link.inner_text(timeout=500) or "").strip()
                    for p in unique_phones[:10]:
                        if p in text or p in href:
                            phone_links.append({"phone": p, "text": text, "href": href})
                            break
                except Exception:
                    pass
            log(f"  Phone detail links: {phone_links[:5]}")
        except Exception as e:
            log(f"  Error: {e}")

        # Try mytempsms
        log("\n=== Trying mytempsms.com ===")
        try:
            page.goto("https://mytempsms.com/receive-sms-online/china-phone-number.html", wait_until="domcontentloaded", timeout=20000)
            page.wait_for_timeout(3000)
            html = page.content()
            phones = re.findall(r'\b(1[3-9]\d{9})\b', html)
            unique_phones = list(dict.fromkeys(phones))
            log(f"  Found {len(unique_phones)} phones: {unique_phones[:10]}")

            links = page.locator("a").all()
            phone_links = []
            for link in links:
                try:
                    href = link.get_attribute("href") or ""
                    text = (link.inner_text(timeout=500) or "").strip()
                    for p in unique_phones[:10]:
                        if p in text or p in href:
                            phone_links.append({"phone": p, "text": text, "href": href})
                            break
                except Exception:
                    pass
            log(f"  Phone detail links: {phone_links[:5]}")
        except Exception as e:
            log(f"  Error: {e}")

        context.close()
        browser.close()


if __name__ == "__main__":
    main()
