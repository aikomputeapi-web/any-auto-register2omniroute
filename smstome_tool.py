from __future__ import annotations

"""SMSToMe phone pool + OTP helper.

The file is a**separate tool script**,Responsible:

1. `update_global_phone_list`: Capture all available mobile phone numbers in multiple countries and write them locally txt.
2. `get_unused_phone`: For a certain task name, return an unused mobile phone number.
3. `wait_for_otp`: Poll the SMS page of the mobile phone number to extract the verification code.

Implementation details:
  - based on `httpx` + `selectolax` of HTTP + HTML Analysis plan;
  - Use browser style by default UA, disable system proxy (`trust_env=False`), to avoid affecting Tavily Relevant agency actions;
  - Support via environment variables `SMSTOME_COOKIE`, warehouse root directory `config.yaml` or explicit parameter injection Cookie;
  - Use a simple loop + Back off and retry to avoid additional introductions tenacity rely.

Notice:
  - txt Persistence only performs simple records and does not perform database-level state management;
  - The country will be additionally saved in the full number file. slug and details page URL, to facilitate subsequent acquisition of verification codes;
  - for each task“Used number list”is independent txt The file is only recorded on one line by mobile phone number.
"""

import os
import random
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional

import httpx
from selectolax.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

try:
    from runtime_support import get_nonempty_str, load_yaml_config
except ImportError:
    def get_nonempty_str(mapping, *keys):
        data = mapping if isinstance(mapping, dict) else {}
        for key in keys:
            value = str(data.get(key, "") or "").strip()
            if value:
                return value
        return ""

    def load_yaml_config(config_path):
        path = Path(config_path)
        if not path.exists():
            return {}
        try:
            import yaml
        except ImportError:
            return {}
        try:
            loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        return loaded if isinstance(loaded, dict) else {}


SMSTOME_BASE_URL = "https://smstome.com"
DEFAULT_CONFIG_PATH = Path(__file__).with_name("config.yaml")

# Currently supported countries slug(from site URL)
DEFAULT_COUNTRY_SLUGS: List[str] = [
    "poland",
    "united-kingdom",
    "slovenia",
    "sweden",
    "finland",
    "belgium",
]


# Full number list file (each line:phone\tcountry_slug\tdetail_url)
GLOBAL_PHONE_FILE = Path("smstome_all_numbers.txt")
DEFAULT_SYNC_MAX_PAGES_PER_COUNTRY = 5

# Each task has its own“Number used”directory (filename:<task>_used_numbers.txt)
USED_NUMBERS_DIR = Path("smstome_used")
BLACKLISTED_NUMBERS_SUFFIX = "_blacklisted_numbers.txt"
USED_NUMBERS_SUFFIX = "_used_numbers.txt"
PHONE_PREFIX_WIDTH = 7


DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "keep-alive",
}

OTP_SEPARATOR_CHARS = r"[\s\-]"
OTP_BIDI_CHARS_RE = re.compile(r"[\u200e\u200f\u202a-\u202e\u2066-\u2069]")
OTP_SPLIT_CANDIDATE_RE = re.compile(r"(?<!\d)(\d(?:[\s\-]*\d){3,7})(?!\d)")
DEFAULT_RECENT_HISTORY_MINUTES = 60.0


def _normalize_start_page(start_page: int | None) -> int:
    value = int(start_page or 1)
    if value < 1:
        raise ValueError(f"start_page must be >= 1, got {start_page}")
    return value


def _resolve_country_page_window(
    *,
    detected_max_page: int,
    start_page: int = 1,
    max_pages_per_country: Optional[int] = DEFAULT_SYNC_MAX_PAGES_PER_COUNTRY,
) -> list[int]:
    start = _normalize_start_page(start_page)
    if detected_max_page < start:
        return []
    if max_pages_per_country is None:
        end_page = detected_max_page
    else:
        if max_pages_per_country < 1:
            raise ValueError(f"max_pages_per_country must be >= 1, got {max_pages_per_country}")
        end_page = min(detected_max_page, start + max_pages_per_country - 1)
    return list(range(start, end_page + 1))


def _normalize_message_text_for_otp(message_text: str) -> str:
    text = OTP_BIDI_CHARS_RE.sub("", message_text or "")
    return text.strip()


def _extract_otp_from_text(
    message_text: str,
    *,
    min_digits: int = 4,
    max_digits: int = 8,
) -> Optional[str]:
    text = _normalize_message_text_for_otp(message_text)
    if not text:
        return None

    for match in OTP_SPLIT_CANDIDATE_RE.finditer(text):
        digits = re.sub(OTP_SEPARATOR_CHARS, "", match.group(1))
        if min_digits <= len(digits) <= max_digits:
            return digits
    return None


def _extract_recent_6digit_otp(message_text: str, received_text: str) -> Optional[str]:
    """priority matching“recent appointment 1 within minutes”of 6 Verification code."""

    msg = (message_text or "").strip()
    recv = (received_text or "").strip().lower()
    if not msg:
        return None

    recent_markers = (
        "just now",
        "few seconds",
        "second ago",
        "seconds ago",
        "sec ago",
        "secs ago",
        "now",
    )
    is_recent = any(marker in recv for marker in recent_markers)

    if not is_recent:
        # compatible "1 min ago" / "1 minute ago" etc.
        minute_match = re.search(r"(\d+)\s*(m|min|mins|minute|minutes)\b", recv)
        if minute_match:
            is_recent = int(minute_match.group(1)) <= 1

    if not is_recent:
        return None

    return _extract_otp_from_text(msg, min_digits=6, max_digits=6)


def _parse_received_age_minutes(received_text: str) -> Optional[float]:
    recv = (received_text or "").strip().lower()
    if not recv:
        return None

    immediate_markers = (
        "just now",
        "few seconds",
        "second ago",
        "seconds ago",
        "sec ago",
        "secs ago",
        "moments ago",
        "now",
    )
    if any(marker in recv for marker in immediate_markers):
        return 0.0

    if re.search(r"\ban?\s+(m|min|mins|minute|minutes)\b", recv):
        return 1.0
    if re.search(r"\ban?\s+(h|hr|hrs|hour|hours)\b", recv):
        return 60.0
    if "yesterday" in recv:
        return 24.0 * 60.0

    match = re.search(
        r"(\d+)\s*(s|sec|secs|second|seconds|m|min|mins|minute|minutes|h|hr|hrs|hour|hours|d|day|days)\b",
        recv,
    )
    if not match:
        return None

    value = int(match.group(1))
    unit = match.group(2)
    if unit.startswith("s"):
        return value / 60.0
    if unit.startswith("m"):
        return float(value)
    if unit.startswith("h"):
        return float(value) * 60.0
    if unit.startswith("d"):
        return float(value) * 24.0 * 60.0
    return None


@dataclass(frozen=True)
class PhoneEntry:
    """represents a SMSToMe Mobile phone number records."""

    country_slug: str
    phone: str  # e.g. "+48573583699"
    detail_url: str  # e.g. "https://smstome.com/poland/phone/48573583699/sms/14642"


@dataclass(frozen=True)
class SmsMessage:
    """Single message record."""

    from_label: str
    received_text: str
    message_text: str


class SmsOtpPollingError(RuntimeError):
    pass


class SmsInboxEmptyError(SmsOtpPollingError):
    pass


class SmsOtpTimeoutError(SmsOtpPollingError):
    pass


class SmsOtpFetchError(SmsOtpPollingError):
    pass


def _summarize_sms_message(message: SmsMessage | None, *, max_len: int = 96) -> str:
    if message is None:
        return "none"
    snippet = " ".join((message.message_text or "").split())
    if len(snippet) > max_len:
        snippet = snippet[: max_len - 3] + "..."
    return (
        f"from={message.from_label!r}, received={message.received_text!r}, "
        f"text={snippet!r}"
    )


def _classify_timeout_state(
    *,
    latest_message: SmsMessage | None,
    unmatched_new_message_count: int,
) -> str:
    if latest_message is None:
        return "empty-inbox"
    if unmatched_new_message_count > 0:
        return "new-messages-no-otp"
    return "stale-inbox-no-new-messages"


def _has_recent_sms_history(
    messages: Iterable[SmsMessage],
    *,
    max_age_minutes: float = DEFAULT_RECENT_HISTORY_MINUTES,
) -> bool:
    for message in messages:
        age_minutes = _parse_received_age_minutes(message.received_text)
        if age_minutes is None:
            continue
        if age_minutes <= max_age_minutes:
            return True
    return False


def _parse_cookie_header(cookie_header: str) -> Dict[str, str]:
    """Copy the browser Cookie String parsed into dictionary.

    For example:
        "a=1; b=2; cf_clearance=xxx" -> {"a": "1", "b": "2", "cf_clearance": "xxx"}
    """

    cookies: Dict[str, str] = {}
    for part in cookie_header.split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        name, value = part.split("=", 1)
        name = name.strip()
        value = value.strip()
        if name:
            cookies[name] = value
    return cookies


def _load_cookie_from_config(config_path: Path | str | None = None) -> Optional[str]:
    try:
        from core.config_store import config_store

        stored = str(config_store.get("smstome_cookie", "") or "").strip()
        if stored:
            return stored
    except Exception:
        pass

    config = load_yaml_config(config_path or DEFAULT_CONFIG_PATH)
    return get_nonempty_str(config, "SMSTOME_COOKIE", "smstome_cookie")


def _resolve_cookie_header(cookie_header: Optional[str]) -> str:
    explicit_cookie = (cookie_header or "").strip()
    if explicit_cookie:
        return explicit_cookie

    env_cookie = os.getenv("SMSTOME_COOKIE", "").strip()
    if env_cookie:
        return env_cookie

    return _load_cookie_from_config() or ""


def _build_client(*, cookie_header: Optional[str], timeout: float) -> httpx.Client:
    """structure httpx.Client,injection UA and optional Cookie, disable the system agent."""

    headers = dict(DEFAULT_HEADERS)
    cookie_header = _resolve_cookie_header(cookie_header)

    cookies: Dict[str, str] = {}
    if cookie_header:
        cookies.update(_parse_cookie_header(cookie_header))

    client = httpx.Client(
        headers=headers,
        cookies=cookies,
        timeout=timeout,
        follow_redirects=True,
        trust_env=False,  # Do not inherit the environment agent to avoid influence Tavily traffic policy
    )
    return client


def _polite_sleep(base_delay: float, jitter: float) -> None:
    """Add a little random delay between requests for simple evasion of risk control.

    Args:
        base_delay: Base delay seconds,<=0 Indicates no waiting.
        jitter: Jitter upper limit seconds,>0 time will be [0, jitter] Additional delays are randomly added between.
    """

    if base_delay <= 0:
        return
    extra = random.uniform(0, jitter) if jitter > 0 else 0.0
    time.sleep(base_delay + extra)


def _fetch_with_retries(
    client: httpx.Client,
    url: str,
    *,
    max_attempts: int = 3,
    backoff_factor: float = 0.5,
) -> str:
    """With simple retry GET Request to return text content.

    - Network anomalies / 5xx Do a limited number of retries;
    - right 4xx(For example 403/404) is thrown directly without additional special processing.
    """

    last_exc: Optional[Exception] = None
    for attempt in range(1, max_attempts + 1):
        try:
            resp = client.get(url)
            resp.raise_for_status()
            return resp.text
        except (httpx.RequestError, httpx.HTTPStatusError) as exc:  # noqa: PERF203
            last_exc = exc
            # 4xx Errors usually do not require retrying
            status = getattr(exc, "response", None)
            status_code = getattr(status, "status_code", None)
            if isinstance(status_code, int) and 400 <= status_code < 500:
                raise

            if attempt >= max_attempts:
                raise
            sleep_s = backoff_factor * attempt
            time.sleep(sleep_s)

    # Normal logic would not go here
    raise RuntimeError(f"Failed to fetch {url!r}: {last_exc}")


def _detect_max_page(tree: HTMLParser) -> int:
    """Parse the maximum page number from the country list page, and return if there is no paging 1."""

    max_page = 1
    # Only focus on inclusion `?page=` link to avoid catching other numbers
    for a in tree.css("a[href*='?page=']"):
        text = (a.text() or "").strip()
        if text.isdigit():
            try:
                value = int(text)
            except ValueError:
                continue
            if value > max_page:
                max_page = value
    return max_page


def _collect_numbers_from_country_page(
    tree: HTMLParser,
    country_slug: str,
    phone_map: Dict[str, PhoneEntry],
) -> None:
    """Parse all numbers from a single country page and write phone_map."""

    for article in tree.css("article"):
        link = article.css_first("a[href*='/phone/']")
        if link is None:
            continue
        phone_text = (link.text() or "").strip()
        if not phone_text:
            continue
        href = (link.attributes.get("href") or "").strip()
        if not href:
            continue

        detail_url = urljoin(SMSTOME_BASE_URL + "/", href)
        # Use the mobile phone number to remove duplicates, and the records that appear later will overwrite the previous ones (generally no impact)
        phone_map[phone_text] = PhoneEntry(
            country_slug=country_slug,
            phone=phone_text,
            detail_url=detail_url,
        )


def _find_phone_entry_on_country_page(
    tree: HTMLParser,
    *,
    phone: str,
    country_slug: str,
) -> Optional[PhoneEntry]:
    target_phone = (phone or "").strip()
    if not target_phone:
        return None

    phone_map: Dict[str, PhoneEntry] = {}
    _collect_numbers_from_country_page(tree, country_slug, phone_map)
    return phone_map.get(target_phone)


def resolve_live_phone_entry(
    entry: PhoneEntry,
    *,
    cookie_header: Optional[str] = None,
    request_timeout: float = 20.0,
    http_max_attempts: int = 3,
    max_pages_per_country: Optional[int] = None,
    start_page: int = 1,
    per_page_delay: float = 0.0,
    jitter: float = 0.0,
) -> Optional[PhoneEntry]:
    detail_host = (urlsplit(entry.detail_url).netloc or "").lower()
    if "smstome.com" not in detail_host:
        return entry

    client = _build_client(cookie_header=cookie_header, timeout=request_timeout)
    try:
        first_url = f"{SMSTOME_BASE_URL}/country/{entry.country_slug}"
        first_page_html = _fetch_with_retries(client, first_url, max_attempts=http_max_attempts)
        first_tree = HTMLParser(first_page_html)
        page_window = _resolve_country_page_window(
            detected_max_page=_detect_max_page(first_tree),
            start_page=start_page,
            max_pages_per_country=max_pages_per_country,
        )
        if not page_window:
            return entry

        for index, page in enumerate(page_window):
            if page == 1:
                html = first_page_html
            else:
                if index > 0:
                    _polite_sleep(per_page_delay, jitter)
                html = _fetch_with_retries(
                    client,
                    f"{first_url}?page={page}",
                    max_attempts=http_max_attempts,
                )
            tree = HTMLParser(html)
            resolved = _find_phone_entry_on_country_page(
                tree,
                phone=entry.phone,
                country_slug=entry.country_slug,
            )
            if resolved is not None:
                return resolved
            if index + 1 < len(page_window):
                _polite_sleep(per_page_delay, jitter)
        return entry
    finally:
        client.close()


def update_global_phone_list(
    *,
    cookie_header: Optional[str] = None,
    countries: Optional[Iterable[str]] = None,
    output_path: Path | str = GLOBAL_PHONE_FILE,
    request_timeout: float = 20.0,
    http_max_attempts: int = 3,
    max_pages_per_country: Optional[int] = DEFAULT_SYNC_MAX_PAGES_PER_COUNTRY,
    start_page: int = 1,
    per_page_delay: float = 1.0,
    per_country_delay: float = 3.0,
    jitter: float = 0.5,
    require_recent_history: bool = True,
    recent_history_minutes: float = DEFAULT_RECENT_HISTORY_MINUTES,
) -> int:
    """Grab numbers from multiple countries and write them txt document.

    txt Format: per line `phone\tcountry_slug\tdetail_url`,For example:

        +48573583699	poland	https://smstome.com/poland/phone/48573583699/sms/14642

    Args:
        cookie_header: Optional Cookie String; if None, then try to start from
            `SMSTOME_COOKIE` environment variables, and then return to the warehouse root directory `config.yaml`
            Read.
        countries: Countries that need to be synchronized slug list; if None, then use
            DEFAULT_COUNTRY_SLUGS.
        output_path: full number txt File path.
        request_timeout: HTTP Request timeout (seconds).
        http_max_attempts: The maximum number of retries for a single request.
        max_pages_per_country: from start_page Start, maximum number of pages to crawl, default 5.
        start_page: Which page does each country start from? Default 1.
        per_page_delay: Base delay between each page turn (seconds), default 1s.
        per_country_delay: Base delay (seconds) after each country crawl is completed, default 3s.
        jitter: The upper limit of additional jitter (seconds) will be in [0, jitter] Randomly added to the delay,
            Used to make access more paced“humanization”.

    Returns:
        The number of mobile phone numbers written to the file after deduplication.
    """

    if countries is None:
        countries = DEFAULT_COUNTRY_SLUGS

    client = _build_client(cookie_header=cookie_header, timeout=request_timeout)
    try:
        phone_map: Dict[str, PhoneEntry] = {}

        for country_slug in countries:
            first_url = f"{SMSTOME_BASE_URL}/country/{country_slug}"
            first_page_html = _fetch_with_retries(client, first_url, max_attempts=http_max_attempts)
            first_tree = HTMLParser(first_page_html)
            page_window = _resolve_country_page_window(
                detected_max_page=_detect_max_page(first_tree),
                start_page=start_page,
                max_pages_per_country=max_pages_per_country,
            )

            for index, page in enumerate(page_window):
                if page == 1:
                    html = first_page_html
                else:
                    if index > 0:
                        _polite_sleep(per_page_delay, jitter)
                    url = f"{first_url}?page={page}"
                    html = _fetch_with_retries(client, url, max_attempts=http_max_attempts)
                tree = HTMLParser(html)
                _collect_numbers_from_country_page(tree, country_slug, phone_map)
                if page == 1 and index + 1 < len(page_window):
                    _polite_sleep(per_page_delay, jitter)

            # After each country is fetched, pause briefly.
            _polite_sleep(per_country_delay, jitter)

        if require_recent_history:
            filtered_phone_map: Dict[str, PhoneEntry] = {}
            for phone in sorted(phone_map.keys()):
                entry = phone_map[phone]
                try:
                    messages = _fetch_sms_messages(
                        client,
                        entry.detail_url,
                        http_max_attempts=http_max_attempts,
                    )
                except Exception:
                    continue
                if _has_recent_sms_history(
                    messages,
                    max_age_minutes=recent_history_minutes,
                ):
                    filtered_phone_map[phone] = entry
            phone_map = filtered_phone_map

        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)

        # only request“Record all numbers”, but for subsequent convenience, additionally save the country and details URL.
        with output.open("w", encoding="utf-8") as f:
            for phone in sorted(phone_map.keys()):
                entry = phone_map[phone]
                f.write(f"{entry.phone}\t{entry.country_slug}\t{entry.detail_url}\n")

        return len(phone_map)
    finally:
        client.close()


def load_global_phone_index(path: Path | str = GLOBAL_PHONE_FILE) -> Dict[str, PhoneEntry]:
    """from full number txt Load the index into the file."""

    phone_index: Dict[str, PhoneEntry] = {}
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(f"Global phone list not found: {file_path}")

    with file_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) < 3:
                continue
            phone, country_slug, detail_url = parts[0], parts[1], parts[2]
            phone_index[phone] = PhoneEntry(
                country_slug=country_slug,
                phone=phone,
                detail_url=detail_url,
            )

    return phone_index


def _sanitize_task_name(task_name: str) -> str:
    """Convert the task name into a form suitable as a file name."""

    return re.sub(r"[^a-zA-Z0-9_.-]", "_", task_name)


def _used_numbers_file(task_name: str, *, base_dir: Path | str = USED_NUMBERS_DIR) -> Path:
    """Returns the corresponding“Number used”File path."""

    safe_name = _sanitize_task_name(task_name)
    directory = Path(base_dir)
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"{safe_name}{USED_NUMBERS_SUFFIX}"


def _blacklisted_numbers_file(task_name: str, *, base_dir: Path | str = USED_NUMBERS_DIR) -> Path:
    """Returns the corresponding“blacklist number”File path."""

    safe_name = _sanitize_task_name(task_name)
    directory = Path(base_dir)
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"{safe_name}{BLACKLISTED_NUMBERS_SUFFIX}"


def _load_phone_set(path: Path) -> set[str]:
    values: set[str] = set()
    if not path.exists():
        return values
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            value = line.strip()
            if value:
                values.add(value)
    return values


def _phone_prefix_hint(phone: str, *, width: int = PHONE_PREFIX_WIDTH) -> str:
    value = (phone or "").strip()
    if not value:
        return ""
    return value[: min(len(value), width)]


def mark_phone_blacklisted(
    task_name: str,
    phone: str,
    *,
    used_numbers_dir: Path | str = USED_NUMBERS_DIR,
) -> None:
    phone_value = (phone or "").strip()
    if not phone_value:
        return

    blacklist_file = _blacklisted_numbers_file(task_name, base_dir=used_numbers_dir)
    existing = _load_phone_set(blacklist_file)
    if phone_value in existing:
        return
    with blacklist_file.open("a", encoding="utf-8") as f:
        f.write(phone_value + "\n")


def parse_country_slugs(country_slug: Optional[str | Iterable[str]]) -> list[str]:
    if country_slug is None:
        return []

    if isinstance(country_slug, str):
        raw_parts = re.split(r"[\s,;|]+", country_slug.strip())
    else:
        raw_parts = []
        for item in country_slug:
            raw_parts.extend(re.split(r"[\s,;|]+", str(item).strip()))

    normalized: list[str] = []
    seen: set[str] = set()
    for part in raw_parts:
        value = part.strip().lower().replace("_", "-")
        if not value or value in seen:
            continue
        seen.add(value)
        normalized.append(value)
    return normalized


def get_unused_phone(
    task_name: str,
    *,
    country_slug: Optional[str | Iterable[str]] = None,
    global_file: Path | str = GLOBAL_PHONE_FILE,
    used_numbers_dir: Path | str = USED_NUMBERS_DIR,
    exclude_prefixes: Optional[Iterable[str]] = None,
) -> Optional[PhoneEntry]:
    """Returns a mobile phone number that has not been used for the specified task and immediately marks it as used.

    The caller should run once before calling `update_global_phone_list`,make sure
    `global_file` is the latest.

    Args:
        task_name: Task name (such as target site ID) to distinguish between different tasks
            Use log files.
        country_slug: If specified, only selects from this country or list of countries; supports a single
            slug, comma separated string or iterable slug gather. for None Represents any country.
        global_file: Full number file path.
        used_numbers_dir: every task“Number used”The directory where the file is located.
        exclude_prefixes: Optional mobile phone number prefix blacklist; used to avoid in a single process
            The number range that has been rejected by the target site has been identified.

    Returns:
        unused PhoneEntry;If no number is available, return None.
    """

    phone_index = load_global_phone_index(global_file)

    used_file = _used_numbers_file(task_name, base_dir=used_numbers_dir)
    blacklist_file = _blacklisted_numbers_file(task_name, base_dir=used_numbers_dir)
    used_numbers = _load_phone_set(used_file)
    blacklisted_numbers = _load_phone_set(blacklist_file)
    excluded_prefixes = {
        prefix
        for prefix in (_phone_prefix_hint(value) for value in (exclude_prefixes or ()))
        if prefix
    }

    country_slugs = parse_country_slugs(country_slug)

    candidates = [
        entry
        for entry in phone_index.values()
        if (not country_slugs or entry.country_slug in country_slugs)
        and entry.phone not in used_numbers
        and entry.phone not in blacklisted_numbers
        and _phone_prefix_hint(entry.phone) not in excluded_prefixes
    ]
    if not candidates:
        return None

    remaining = list(candidates)
    while remaining:
        entry = random.choice(remaining)
        remaining.remove(entry)
        try:
            refreshed_entry = resolve_live_phone_entry(entry)
        except Exception:
            refreshed_entry = entry
        if refreshed_entry is None:
            continue
        with used_file.open("a", encoding="utf-8") as f:
            f.write(refreshed_entry.phone + "\n")
        return refreshed_entry
    return None


def _fetch_sms_messages(
    client: httpx.Client,
    detail_url: str,
    *,
    http_max_attempts: int,
) -> List[SmsMessage]:
    """Grab the SMS list of a certain number's homepage (first page)."""

    html = _fetch_with_retries(client, detail_url, max_attempts=http_max_attempts)
    tree = HTMLParser(html)

    # There is only one main text message form on the page. Here we take the first one directly. table That’s it.
    table = tree.css_first("table")
    if table is None:
        return []

    messages: List[SmsMessage] = []
    for tr in table.css("tr"):
        # Skip header rows (including th)
        if tr.css_first("th") is not None:
            continue
        tds = tr.css("td")
        if len(tds) < 3:
            continue
        from_label = tds[0].text(strip=True)
        received_text = tds[1].text(strip=True)
        message_text = tds[2].text(separator=" ", strip=True)
        if not message_text:
            continue
        messages.append(
            SmsMessage(
                from_label=from_label,
                received_text=received_text,
                message_text=message_text,
            )
        )

    return messages


def wait_for_otp(
    entry: PhoneEntry,
    *,
    cookie_header: Optional[str] = None,
    timeout: float = 120.0,
    poll_interval: float = 5.0,
    otp_regex: str = r"\b(\d{4,8})\b",
    http_max_attempts: int = 3,
    trace: Callable[[str], None] | None = None,
    raise_on_timeout: bool = False,
) -> Optional[str]:
    """Poll the specified mobile phone number for text messages, extract the verification code and return it.

    Basic logic:
      1. At startup, the current text message list is captured once and recorded as seen;
      2. in given `timeout` within, every `poll_interval` Re-fetch in seconds;
      3. for each“never seen”SMS, use `otp_regex` Match verification code;
      4. If the match is successful, the first verification code will be returned; if it times out, it will be returned. None.

    Args:
        entry: pass `get_unused_phone` or obtained by other means PhoneEntry.
        cookie_header: Optional Cookie String; if None, then try to start from
            `SMSTOME_COOKIE` environment variables, and then return to the warehouse root directory `config.yaml`
            Read.
        timeout: Maximum wait time (seconds).
        poll_interval: Polling interval (seconds).
        otp_regex: Regular pattern used to extract verification codes from text messages, matching by default 4–8 digits.
        http_max_attempts: Every time a text message is captured HTTP Number of retries.
        trace: Optional log callback; if provided, a diagnostic summary of each poll is output.
        raise_on_timeout: If True, throw a more specific exception after the timeout instead of returning None.

    Returns:
        Matched verification code string; if not obtained after timeout, return None.
    """

    client = _build_client(cookie_header=cookie_header, timeout=timeout)
    pattern = re.compile(otp_regex)
    emit = trace or (lambda _msg: None)

    seen_messages: set[str] = set()
    unmatched_new_message_count = 0
    latest_unmatched_message: SmsMessage | None = None

    def _fetch_messages(phase: str, *, poll_number: int | None = None) -> List[SmsMessage]:
        try:
            return _fetch_sms_messages(
                client, entry.detail_url, http_max_attempts=http_max_attempts
            )
        except Exception as exc:
            label = f"{phase} fetch-error"
            if poll_number is not None:
                label += f" poll={poll_number}"
            emit(f"{label} type={type(exc).__name__} error={exc}")
            raise SmsOtpFetchError(
                f"SMSToMe {phase} fetch failed for {entry.phone}: {exc}"
            ) from exc

    # Initial capture to avoid mistaking historical text messages for“New SMS”
    initial_messages = _fetch_messages("initial")
    latest_message = initial_messages[0] if initial_messages else None
    latest_snapshot = (
        latest_message.from_label,
        latest_message.received_text,
        latest_message.message_text,
    ) if latest_message else None
    emit(
        f"poll start phone={entry.phone} messages={len(initial_messages)} "
        f"latest={_summarize_sms_message(latest_message)}"
    )
    if initial_messages:
        quick_otp = _extract_recent_6digit_otp(
            latest_message.message_text,
            latest_message.received_text,
        )
        if quick_otp:
            emit(
                "matched quick recent OTP "
                f"code={quick_otp} latest={_summarize_sms_message(latest_message)}"
            )
            return quick_otp

    for msg in initial_messages:
        seen_messages.add(msg.message_text)

    deadline = time.monotonic() + timeout
    poll_count = 0

    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            timeout_state = _classify_timeout_state(
                latest_message=latest_message,
                unmatched_new_message_count=unmatched_new_message_count,
            )
            summary = (
                f"final state={timeout_state} polls={poll_count} "
                f"latest={_summarize_sms_message(latest_message)}"
            )
            if latest_unmatched_message is not None:
                summary += (
                    " first_unmatched_new="
                    + _summarize_sms_message(latest_unmatched_message)
                )
            emit(summary)
            emit(
                f"timeout after {poll_count} poll(s); latest={_summarize_sms_message(latest_message)}"
            )
            if raise_on_timeout:
                if latest_message is None:
                    raise SmsInboxEmptyError(
                        f"SMSToMe inbox stayed empty for {entry.phone} after {poll_count} poll(s)"
                    )
                raise SmsOtpTimeoutError(
                    f"SMSToMe OTP timeout state={timeout_state} for {entry.phone} "
                    f"after {poll_count} poll(s); latest={_summarize_sms_message(latest_message)}"
                )
            return None

        sleep_s = min(poll_interval, max(remaining, 0))
        if sleep_s > 0:
            time.sleep(sleep_s)

        poll_count += 1
        messages = _fetch_messages("poll", poll_number=poll_count)
        latest_message = messages[0] if messages else None
        current_snapshot = (
            latest_message.from_label,
            latest_message.received_text,
            latest_message.message_text,
        ) if latest_message else None
        new_count = sum(1 for msg in messages if msg.message_text not in seen_messages)
        if poll_count <= 3 or current_snapshot != latest_snapshot or new_count:
            emit(
                f"poll {poll_count}: messages={len(messages)} new={new_count} "
                f"latest={_summarize_sms_message(latest_message)}"
            )
        latest_snapshot = current_snapshot
        if messages:
            quick_otp = _extract_recent_6digit_otp(
                latest_message.message_text,
                latest_message.received_text,
            )
            if quick_otp:
                emit(
                    "matched quick recent OTP "
                    f"code={quick_otp} latest={_summarize_sms_message(latest_message)}"
                )
                return quick_otp

        for msg in messages:
            if msg.message_text in seen_messages:
                continue
            seen_messages.add(msg.message_text)
            unmatched_new_message_count += 1
            latest_unmatched_message = msg
            normalized_text = _normalize_message_text_for_otp(msg.message_text)
            match = pattern.search(normalized_text)
            if match:
                code = re.sub(OTP_SEPARATOR_CHARS, "", match.group(1))
                emit(f"matched regex OTP code={code} message={_summarize_sms_message(msg)}")
                return code
            fallback_otp = _extract_otp_from_text(msg.message_text)
            if fallback_otp:
                emit(
                    f"matched fallback OTP code={fallback_otp} "
                    f"message={_summarize_sms_message(msg)}"
                )
                return fallback_otp
        if new_count and latest_unmatched_message is not None:
            emit(
                "new messages arrived without OTP match "
                f"count={new_count} sample={_summarize_sms_message(latest_unmatched_message)}"
            )


if __name__ == "__main__":  # pragma: no cover - Simple debugging entrance
    import argparse

    parser = argparse.ArgumentParser(
        description="SMSToMe phone pool & OTP helper",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    sync_parser = subparsers.add_parser(
        "sync", help="Synchronize all mobile phone numbers to txt document",
    )
    sync_parser.add_argument(
        "--cookie",
        dest="cookie",
        help="Optional Cookie String; used if empty SMSTOME_COOKIE environment variables or config.yaml",
    )
    sync_parser.add_argument(
        "--max-pages-per-country",
        dest="max_pages_per_country",
        type=int,
        default=DEFAULT_SYNC_MAX_PAGES_PER_COUNTRY,
        help=(
            "Starting from the starting page, the maximum number of pages to crawl for each country;"
            f"default {DEFAULT_SYNC_MAX_PAGES_PER_COUNTRY}"
        ),
    )
    sync_parser.add_argument(
        "--start-page",
        dest="start_page",
        type=int,
        default=1,
        help="Which page does each country start from? Default 1",
    )
    sync_parser.add_argument(
        "--countries",
        dest="countries",
        help="Optional countries slug List; supports single slug or comma separated, e.g. united-kingdom,sweden",
    )
    sync_parser.add_argument(
        "--output",
        dest="output_path",
        default=str(GLOBAL_PHONE_FILE),
        help=f"Synchronization result output file; default {GLOBAL_PHONE_FILE}",
    )
    sync_parser.add_argument(
        "--skip-history-check",
        dest="skip_history_check",
        action="store_true",
        help="Do not synchronize the historical activity of the details page; by default, numbers without minute-level historical text messages will be filtered out",
    )
    sync_parser.add_argument(
        "--recent-history-minutes",
        dest="recent_history_minutes",
        type=float,
        default=DEFAULT_RECENT_HISTORY_MINUTES,
        help=(
            "Keep only the most recent when syncing N Numbers with historical text messages within minutes;"
            f"default {int(DEFAULT_RECENT_HISTORY_MINUTES)}"
        ),
    )

    pick_parser = subparsers.add_parser(
        "pick", help="Choose an unused mobile phone number for a task",
    )
    pick_parser.add_argument("task", help="Task name, used to distinguish used number files")
    pick_parser.add_argument(
        "--country",
        dest="country",
        help="Optional countries slug(For example poland,sweden)",
    )

    args = parser.parse_args()

    if args.command == "sync":
        count = update_global_phone_list(
            cookie_header=args.cookie,
            countries=parse_country_slugs(args.countries) or None,
            output_path=args.output_path,
            max_pages_per_country=args.max_pages_per_country,
            start_page=args.start_page,
            require_recent_history=not args.skip_history_check,
            recent_history_minutes=args.recent_history_minutes,
        )
        print(f"Synced {count} phone numbers into {args.output_path}")
    elif args.command == "pick":
        entry = get_unused_phone(
            task_name=args.task,
            country_slug=args.country,
        )
        if entry is None:
            print("No unused phone available.")
        else:
            print(
                f"Task={args.task} -> {entry.phone} "
                f"(country={entry.country_slug})",
            )
