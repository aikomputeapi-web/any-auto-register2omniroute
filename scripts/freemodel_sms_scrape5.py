"""Try multiple SMS sites to find one without Cloudflare that shows messages."""
import re
import time
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from playwright.sync_api import sync_playwright


def log(msg):
    print(f"[SMS-Scrape5] {msg}", flush=True)


def try_site(page, name, list_url, phone_url_pattern=None):
    """Try a site and return phone numbers and a working detail URL."""
    log(f"\n=== {name}: {list_url} ===")
    try:
        page.goto(list_url, wait_until="domcontentloaded", timeout=20000)
        page.wait_for_timeout(4000)
        url = page.url
        log(f"  Final URL: {url}")

        # Check for Cloudflare challenge
        body_text = page.locator("body").inner_text(timeout=3000)
        if "cloudflare" in body_text.lower() or "security verification" in body_text.lower() or "just a moment" in body_text.lower():
            log("  BLOCKED by Cloudflare!")
            return []

        # Find phone numbers
        phones = re.findall(r'\b(1[3-9]\d{9})\b', body_text)
        unique_phones = list(dict.fromkeys(phones))
        log(f"  Found {len(unique_phones)} phones: {unique_phones[:10]}")

        # Find detail page links
        links = page.locator("a[href]").all()
        detail_links = []
        for link in links[:100]:
            try:
                href = link.get_attribute("href") or ""
                text = (link.inner_text(timeout=500) or "").strip()
                if href and not href.startswith("#") and not href.startswith("javascript"):
                    # Check if it looks like a phone detail page
                    if any(p in text for p in unique_phones[:5]) or "/cn/" in href or "phone" in href.lower() or "number" in href.lower() or re.search(r'/\d{4,}\.html', href):
                        detail_links.append({"text": text[:50], "href": href})
            except Exception:
                pass
        log(f"  Detail links: {detail_links[:10]}")

        # If we have detail links, try visiting one
        if detail_links:
            for dl in detail_links[:3]:
                href = dl["href"]
                if not href.startswith("http"):
                    if href.startswith("/"):
                        href = "/".join(list_url.split("/")[:3]) + href
                    else:
                        href = list_url.rstrip("/") + "/" + href
                log(f"  Trying detail page: {href}")
                try:
                    page.goto(href, wait_until="domcontentloaded", timeout=20000)
                    page.wait_for_timeout(4000)
                    detail_text = page.locator("body").inner_text(timeout=3000)
                    if "cloudflare" in detail_text.lower() or "security verification" in detail_text.lower():
                        log("    Detail page BLOCKED by Cloudflare!")
                        continue
                    log(f"    Detail page loaded! Text (first 1000): {detail_text[:1000]}")
                    # Look for SMS messages
                    msgs = re.findall(r'(?i)(freemodel|verification|code|verify|\d{4,6}).{0,100}', detail_text)
                    log(f"    Messages: {msgs[:10]}")
                    return unique_phones
                except Exception as e:
                    log(f"    Error: {e}")

        return unique_phones
    except Exception as e:
        log(f"  Error: {e}")
        return []


def main():
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        context = browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        )
        page = context.new_page()

        # Try receive-sms.cc with specific phone
        try_site(page, "receive-sms.cc", "https://receive-sms.cc/China-Phone-Number/")
        # Try the specific phone page
        log("\n  Trying specific: https://receive-sms.cc/China-Phone-Number/8618866478549")
        try:
            page.goto("https://receive-sms.cc/China-Phone-Number/8618866478549", wait_until="domcontentloaded", timeout=20000)
            page.wait_for_timeout(4000)
            body_text = page.locator("body").inner_text(timeout=3000)
            log(f"    Text (first 1000): {body_text[:1000]}")
        except Exception as e:
            log(f"    Error: {e}")

        # Try supercloudsms
        try_site(page, "supercloudsms", "https://www.supercloudsms.com/en/country/china/1.html")

        # Try 1001sms
        try_site(page, "1001sms", "https://www.1001sms.com/china")

        context.close()
        browser.close()


if __name__ == "__main__":
    main()
