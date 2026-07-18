import sys
import asyncio
import re
import httpx
import logging
from sqlmodel import Session, select
from core.db import ProxyModel, engine

if sys.platform == "win32":
    try:
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    except Exception:
        pass

logger = logging.getLogger("proxy_checker")

HTTP_SOURCES = [
    "https://api.proxyscrape.com/v3/free-proxy-list/get?request=getproxies&protocol=http",
    "https://api.proxyscrape.com/v3/free-proxy-list/get?request=getproxies&protocol=https",
    "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/refs/heads/master/http.txt",
    "https://raw.githubusercontent.com/proxifly/free-proxy-list/refs/heads/main/proxies/protocols/http/data.txt",
    "https://raw.githubusercontent.com/proxifly/free-proxy-list/refs/heads/main/proxies/protocols/https/data.txt",
    "https://raw.githubusercontent.com/roosterkid/openproxylist/refs/heads/main/HTTPS_RAW.txt",
    "https://raw.githubusercontent.com/sunny9577/proxy-scraper/refs/heads/master/generated/http_proxies.txt",
    # Additional high-yield HTTP proxy lists
    "https://raw.githubusercontent.com/clarketm/proxy-list/master/proxy-list-raw.txt",
    "https://raw.githubusercontent.com/mmpx12/proxy-list/master/https.txt",
    "https://raw.githubusercontent.com/vakhov/fresh-proxy-list/master/http.txt",
    "https://raw.githubusercontent.com/Zaeem20/FREE_PROXIES_LIST/master/http.txt",
    "https://raw.githubusercontent.com/jetkai/proxy-list/main/online-proxies/txt/proxies-http.txt",
    "https://raw.githubusercontent.com/jetkai/proxy-list/main/online-proxies/txt/proxies-https.txt",
]

SOCKS4_SOURCES = [
    "https://api.proxyscrape.com/v3/free-proxy-list/get?request=getproxies&protocol=socks4",
    "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/refs/heads/master/socks4.txt",
    "https://raw.githubusercontent.com/proxifly/free-proxy-list/refs/heads/main/proxies/protocols/socks4/data.txt",
    "https://raw.githubusercontent.com/roosterkid/openproxylist/refs/heads/main/SOCKS4_RAW.txt",
    "https://raw.githubusercontent.com/sunny9577/proxy-scraper/refs/heads/master/generated/socks4_proxies.txt",
    # Additional SOCKS4 proxy lists
    "https://raw.githubusercontent.com/Zaeem20/FREE_PROXIES_LIST/master/socks4.txt",
    "https://raw.githubusercontent.com/jetkai/proxy-list/main/online-proxies/txt/proxies-socks4.txt",
]

SOCKS5_SOURCES = [
    "https://api.proxyscrape.com/v3/free-proxy-list/get?request=getproxies&protocol=socks5",
    "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/refs/heads/master/socks5.txt",
    "https://raw.githubusercontent.com/hookzof/socks5_list/refs/heads/master/proxy.txt",
    "https://raw.githubusercontent.com/proxifly/free-proxy-list/refs/heads/main/proxies/protocols/socks5/data.txt",
    "https://raw.githubusercontent.com/roosterkid/openproxylist/refs/heads/main/SOCKS5_RAW.txt",
    "https://raw.githubusercontent.com/sunny9577/proxy-scraper/refs/heads/master/generated/socks5_proxies.txt",
    # Additional SOCKS5 proxy lists
    "https://raw.githubusercontent.com/mmpx12/proxy-list/master/socks5.txt",
    "https://raw.githubusercontent.com/vakhov/fresh-proxy-list/master/socks5.txt",
    "https://raw.githubusercontent.com/Zaeem20/FREE_PROXIES_LIST/master/socks5.txt",
    "https://raw.githubusercontent.com/jetkai/proxy-list/main/online-proxies/txt/proxies-socks5.txt",
]

MIXED_SOURCES = [
    # US-specific mix list
    "https://raw.githubusercontent.com/proxifly/free-proxy-list/main/proxies/countries/US/data.txt"
]

PROXY_PATTERN = re.compile(
    r"\b(?:(https?|socks4|socks5)://)?((?:\d{1,3}\.){3}\d{1,3}:\d{1,5})\b",
    re.IGNORECASE
)


def extract_proxies_from_text(text: str, default_protocol: str) -> dict[str, str]:
    """
    Extracts all proxy URLs from the given text.
    Returns a dict of proxy_url -> protocol
    """
    proxies = {}
    for match in PROXY_PATTERN.finditer(text):
        scheme, ip_port = match.groups()
        if scheme:
            proto = scheme.lower()
            if proto == "https":
                proto = "http"
            proxies[f"{proto}://{ip_port}"] = proto
        else:
            proxies[f"{default_protocol}://{ip_port}"] = default_protocol
    return proxies


async def scrape_us_proxy_org(client: httpx.AsyncClient) -> list[str]:
    url = "https://www.us-proxy.org/"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    try:
        r = await client.get(url, headers=headers, timeout=15.0)
        if r.status_code == 200:
            matches = re.findall(r"<td>((?:\d{1,3}\.){3}\d{1,3})</td>\s*<td>(\d{1,5})</td>", r.text)
            return [f"{ip}:{port}" for ip, port in matches]
    except Exception as e:
        logger.warning(f"Failed to scrape us-proxy.org: {e}")
    return []


async def scrape_free_proxy_list_net(client: httpx.AsyncClient) -> list[str]:
    url = "https://free-proxy-list.net/"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    try:
        r = await client.get(url, headers=headers, timeout=15.0)
        if r.status_code == 200:
            matches = re.findall(r"<td>((?:\d{1,3}\.){3}\d{1,3})</td>\s*<td>(\d{1,5})</td>", r.text)
            return [f"{ip}:{port}" for ip, port in matches]
    except Exception as e:
        logger.warning(f"Failed to scrape free-proxy-list.net: {e}")
    return []


async def fetch_source(client: httpx.AsyncClient, url: str) -> str:
    try:
        r = await client.get(url, timeout=15.0)
        if r.status_code == 200:
            return r.text
    except Exception as e:
        logger.warning(f"Failed to fetch proxy source {url}: {e}")
    return ""


async def scrape_all_raw_proxies() -> dict[str, str]:
    """
    Scrapes all raw proxy lists and dynamic sites concurrently.
    Returns a dict of proxy_url -> protocol
    """
    logger.info("Starting high-speed scraping of all raw proxy sources and dynamic scrapers...")
    proxies = {}  # url -> protocol/source-type
    
    async with httpx.AsyncClient(timeout=15.0, verify=False) as client:
        # Group fetches for lists
        http_tasks = [fetch_source(client, url) for url in HTTP_SOURCES]
        socks4_tasks = [fetch_source(client, url) for url in SOCKS4_SOURCES]
        socks5_tasks = [fetch_source(client, url) for url in SOCKS5_SOURCES]
        mixed_tasks = [fetch_source(client, url) for url in MIXED_SOURCES]
        
        # Dynamic scrapers
        us_proxy_task = scrape_us_proxy_org(client)
        free_proxy_task = scrape_free_proxy_list_net(client)
        
        # Gather concurrently
        http_results, socks4_results, socks5_results, mixed_results, us_proxy_ips, free_proxy_ips = await asyncio.gather(
            asyncio.gather(*http_tasks),
            asyncio.gather(*socks4_tasks),
            asyncio.gather(*socks5_tasks),
            asyncio.gather(*mixed_tasks),
            us_proxy_task,
            free_proxy_task
        )
        
        # Parse list results
        for text in http_results:
            proxies.update(extract_proxies_from_text(text, "http"))
            
        for text in socks4_results:
            proxies.update(extract_proxies_from_text(text, "socks4"))
            
        for text in socks5_results:
            proxies.update(extract_proxies_from_text(text, "socks5"))
            
        for text in mixed_results:
            proxies.update(extract_proxies_from_text(text, "socks5"))  # default to socks5 if mixed & no scheme
            
        # Parse dynamic scrapers (these return ip:port, and they are HTTP/HTTPS)
        for ip_port in us_proxy_ips:
            proxies[f"http://{ip_port}"] = "http"
            
        for ip_port in free_proxy_ips:
            proxies[f"http://{ip_port}"] = "http"
            
    # Filter out empty/dummy keys (e.g. 0.0.0.0)
    proxies = {k: v for k, v in proxies.items() if not k.split("://")[-1].startswith("0.0.0.0")}
                
    logger.info(f"Scraped {len(proxies)} unique raw proxies.")
    return proxies


# HTTPS geo endpoints that return JSON with a country code.
# Ordered by preference; each is tried over HTTPS so the proxy MUST support
# the CONNECT tunnel method (required for any HTTPS site like chatgpt.com).
# A plain-HTTP-only / transparent proxy that returns 405 to CONNECT will fail
# every endpoint here and be rejected.
_HTTPS_GEO_ENDPOINTS = [
    ("https://ipwho.is/", "country_code"),
    ("https://ipapi.co/json/", "country_code"),
    ("https://ip-api.com/json/", "countryCode"),  # https endpoint (may be rate-limited)
]


async def check_single_proxy(client: httpx.AsyncClient, url: str, timeout: float = 8.0) -> tuple[str, bool, str]:
    """
    Checks a single proxy by performing an HTTPS request through it (which
    requires a working CONNECT tunnel) and gets its region.
    Returns: (proxy_url, is_ok, region_code)

    Proxies that cannot establish an HTTPS CONNECT tunnel (e.g. transparent
    proxies that answer 405 Method Not Allowed to CONNECT) are rejected here
    so they never enter the pool and break real HTTPS-only flows.
    """
    last_err = None
    for target, country_field in _HTTPS_GEO_ENDPOINTS:
        try:
            async with httpx.AsyncClient(proxy=url, timeout=timeout, verify=False) as proxy_client:
                r = await proxy_client.get(target, timeout=timeout)
                if r.status_code == 200:
                    data = r.json()
                    country_code = str(data.get(country_field, "") or "").upper()
                    if country_code:
                        return url, True, country_code
        except Exception as e:
            last_err = e
            continue
    if last_err:
        logger.debug(f"proxy {url} failed HTTPS CONNECT check: {last_err}")
    return url, False, ""


async def verify_proxies_async(proxy_urls: list[str], max_concurrent: int = 200) -> list[tuple[str, bool, str]]:
    """
    Verifies all provided proxy URLs concurrently with a limit on active checks.
    Returns: list of (url, is_ok, region)
    """
    logger.info(f"Verifying {len(proxy_urls)} proxies concurrently (limit={max_concurrent})...")
    sem = asyncio.Semaphore(max_concurrent)

    # HTTPS CONNECT through slow free proxies can exceed the old 5s ceiling,
    # which produced false negatives. Bumped to 10s so genuine-but-slow
    # proxies survive, while 405-on-CONNECT / dead ones still fail fast.
    async with httpx.AsyncClient(timeout=10.0, verify=False) as client:
        async def worker(url):
            async with sem:
                return await check_single_proxy(client, url, timeout=10.0)
                
        tasks = [worker(url) for url in proxy_urls]
        results = await asyncio.gather(*tasks)
        return results

