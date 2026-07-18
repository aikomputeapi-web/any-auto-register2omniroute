"""Find the detail page URL structure on freereceivesms.com and other sites."""
import re
import time
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from playwright.sync_api import sync_playwright


def log(msg):
    print(f"[SMS-Scrape2] {msg}", flush=True)


def main():
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        context = browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        )
        page = context.new_page()

        # Inspect freereceivesms.com link structure
        log("=== Inspecting freereceivesms.com links ===")
        try:
            page.goto("https://www.freereceivesms.com/en/cn/", wait_until="domcontentloaded", timeout=20000)
            page.wait_for_timeout(3000)

            # Get all links and their hrefs
            links = page.locator("a").all()
            log(f"Total links: {len(links)}")
            for link in links[:50]:
                try:
                    href = link.get_attribute("href") or ""
                    text = (link.inner_text(timeout=500) or "").strip()
                    if "162" in text or "162" in href or "phone" in href.lower() or "number" in href.lower():
                        log(f"  [{text}] -> {href}")
                except Exception:
                    pass

            # Also try a specific phone number page: the URL format is usually /en/cn/<number>.html
            test_phone = "16265813251"
            for url_fmt in [
                f"https://www.freereceivesms.com/en/cn/{test_phone}.html",
                f"https://www.freereceivesms.com/en/cn/{test_phone}/",
                f"https://www.freereceivesms.com/cn/{test_phone}",
                f"https://www.freereceivesms.com/en/cn/8438.html",
            ]:
                log(f"\n  Trying: {url_fmt}")
                try:
                    resp = page.request.get(url_fmt, timeout=10000)
                    log(f"    Status: {resp.status}")
                    if resp.ok:
                        body = resp.text()
                        # Look for SMS messages
                        msgs = re.findall(r'(?i)(freemodel|free.?model|verification|code).{0,200}', body)
                        if msgs:
                            log(f"    Found messages: {msgs[:3]}")
                        # Look for a table of messages
                        phones = re.findall(r'\b(1[3-9]\d{9})\b', body)
                        log(f"    Phones on page: {phones[:5]}")
                except Exception as e:
                    log(f"    Error: {e}")

        except Exception as e:
            log(f"Error: {e}")

        # Try quackr.io
        log("\n=== Trying quackr.io ===")
        try:
            page.goto("https://quackr.io/temporary-numbers/china", wait_until="domcontentloaded", timeout=20000)
            page.wait_for_timeout(3000)
            html = page.content()
            phones = re.findall(r'\b(1[3-9]\d{9})\b', html)
            unique_phones = list(dict.fromkeys(phones))
            log(f"  Found {len(unique_phones)} phones: {unique_phones[:10]}")
            links = page.locator("a").all()
            for link in links[:30]:
                try:
                    href = link.get_attribute("href") or ""
                    text = (link.inner_text(timeout=500) or "").strip()
                    if any(p in text or p in href for p in unique_phones[:5]):
                        log(f"  [{text}] -> {href}")
                except Exception:
                    pass
        except Exception as e:
            log(f"  Error: {e}")

        # Try temporary-phone-number.com
        log("\n=== Trying temporary-phone-number.com ===")
        try:
            page.goto("https://temporary-phone-number.com/countrys/", wait_until="domcontentloaded", timeout=20000)
            page.wait_for_timeout(3000)
            html = page.content()
            # Look for China link
            china_links = re.findall(r'href="([^"]*[Cc]hina[^"]*)"', html)
            log(f"  China links: {china_links[:5]}")
            if china_links:
                for cl in china_links[:3]:
                    if not cl.startswith("http"):
                        cl = "https://temporary-phone-number.com" + cl if cl.startswith("/") else f"https://temporary-phone-number.com/{cl}"
                    log(f"  Visiting: {cl}")
                    page.goto(cl, wait_until="domcontentloaded", timeout=20000)
                    page.wait_for_timeout(3000)
                    html2 = page.content()
                    phones = re.findall(r'\b(1[3-9]\d{9})\b', html2)
                    unique_phones = list(dict.fromkeys(phones))
                    log(f"    Found {len(unique_phones)} phones: {unique_phones[:10]}")
                    links = page.locator("a").all()
                    for link in links[:20]:
                        try:
                            href = link.get_attribute("href") or ""
                            text = (link.inner_text(timeout=500) or "").strip()
                            if any(p in text or p in href for p in unique_phones[:5]):
                                log(f"    [{text}] -> {href}")
                        except Exception:
                            pass
        except Exception as e:
            log(f"  Error: {e}")

        context.close()
        browser.close()


if __name__ == "__main__":
    main()
