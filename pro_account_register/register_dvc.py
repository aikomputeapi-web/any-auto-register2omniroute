from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
import time
import urllib.error
import urllib.request
from dataclasses import asdict
from pathlib import Path
from typing import Any

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pro_account_register.dvc_profile_utils import (
    ProfileRecord,
    choose_random_unused_male_profile,
    save_used_line,
)

# Log redirection support for task runner UI logs
_log_fn = None


def _sanitize_text(text: str) -> str:
    """Replace characters that can't be encoded by the console (cp1252)."""
    try:
        text.encode("cp1252")
        return text
    except UnicodeEncodeError:
        return text.encode("cp1252", errors="replace").decode("cp1252")


def print(*args, **kwargs):
    global _log_fn
    kwargs.setdefault("flush", True)
    if _log_fn is not None:
        try:
            msg = _sanitize_text(" ".join(str(arg) for arg in args))
            _log_fn(msg)
            return
        except Exception:
            pass
    import builtins

    args = tuple(_sanitize_text(str(a)) for a in args)
    builtins.print(*args, **kwargs)


BRIDGE_URL = "http://localhost:3005"
TARGET_URL = "https://www.opencccapply.net/gateway/apply?cccMisCode=312"
RESULTS_DIR = Path("pro_account_register/registration_results")
DVC_USED_LINES = RESULTS_DIR / "dvc_used_lines.json"

SECURITY_QUESTIONS = [
    "What is the name of your first pet?",
    "What city were you born in?",
    "What is your mother's maiden name?",
    "What is the name of your elementary school?",
    "What is your favorite color?",
    "What is your favorite movie?",
]


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


# ─────── Bridge HTTP helpers ────────


def bridge_get(path: str) -> Any | None:
    try:
        req = urllib.request.Request(f"{BRIDGE_URL}{path}")
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"  [!] Bridge GET {path} failed: {e}")
        return None


def bridge_eval(expression: str, timeout: int = 15) -> Any | None:
    data = json.dumps({"expression": expression}).encode("utf-8")
    try:
        req = urllib.request.Request(
            f"{BRIDGE_URL}/eval", data=data,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8")).get("result")
    except Exception as e:
        print(f"  [!] Bridge eval failed: {e}")
        return None


def bridge_navigate(url: str) -> None:
    """Navigate the browser to *url*.

    Prefers the CDP ``Page.navigate`` command (exposed at ``/navigate``) which
    does not interrupt in-progress bot-protection challenges the way a
    ``window.location.href`` assignment can. Falls back to the eval approach.
    """
    data = json.dumps({"url": url}).encode("utf-8")
    try:
        req = urllib.request.Request(
            f"{BRIDGE_URL}/navigate", data=data,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            json.loads(resp.read().decode("utf-8"))
        return
    except Exception as e:
        print(f"  [!] CDP navigate failed ({e}), falling back to location.href")
    safe = url.replace("\\", "\\\\").replace("'", "\\'")
    bridge_eval(f"window.location.href = '{safe}'")


def _is_loading_interstitial() -> bool:
    """Detect the OpenCCCApply 'Please stand by' Imperva interstitial page."""
    body = get_body_text(1000).lower()
    return "please stand by" in body and "getting everything ready" in body


def _wait_for_page_ready(timeout: int = 60, poll: float = 2.0) -> bool:
    """Wait for loading interstitials and bot challenges to clear."""
    deadline = time.monotonic() + timeout
    i = 0
    while time.monotonic() < deadline:
        if _is_bot_challenge():
            if not _wait_for_security_check(timeout=30):
                return False
        if _is_loading_interstitial():
            if i % 5 == 0:
                print(f"  Waiting for page to finish loading... ({i}s)")
            time.sleep(poll)
            i += int(poll)
            continue
        return True
    return not _is_bot_challenge() and not _is_loading_interstitial()


# ─────── Page inspection ────────


def get_page_info() -> tuple[str, str]:
    info = bridge_get("/page")
    if info:
        return info.get("url", ""), info.get("title", "")
    return "", ""


def get_body_text(max_chars: int = 5000) -> str:
    return bridge_eval(f"document.body?.innerText?.substring(0, {max_chars})") or ""


def dump_visible_elements() -> list[dict[str, Any]]:
    raw = bridge_eval("""
        JSON.stringify(Array.from(document.querySelectorAll(
          'input, select, textarea, button, a, [role="button"], [role="link"]'
        )).filter(el => {
          const r = el.getBoundingClientRect();
          const s = window.getComputedStyle(el);
          return r.width > 0 && r.height > 0 &&
                 s.display !== 'none' && s.visibility !== 'hidden';
        }).map(el => ({
          tag: el.tagName.toLowerCase(), id: el.id || '', name: el.name || '',
          type: el.type || '', text: (el.textContent || '').trim().slice(0, 120),
          href: el.href || '', placeholder: el.placeholder || '',
          value: (el.value || '').slice(0, 60),
        })))
    """)
    if raw:
        return json.loads(raw) if isinstance(raw, str) else raw
    return []


def save_page_snapshot(name: str) -> str | None:
    html = bridge_eval("document.documentElement.outerHTML")
    if html:
        path = RESULTS_DIR / f"{name}.html"
        path.write_text(html, encoding="utf-8")
        return str(path)
    return None


# ─────── Bot / WAF detection ────────


def _is_incapsula_challenge() -> bool:
    # Incapsula serves a tiny page with a main-iframe pointing at _Incapsula_Resource.
    # The body text is usually empty or "Request unsuccessful." so we inspect the HTML.
    html = bridge_eval("document.documentElement.outerHTML.substring(0, 5000)") or ""
    if not html:
        return False
    if 'id="main-iframe"' in html and '_Incapsula_Resource' in html:
        return True
    # Some Incapsula variants render a bare challenge without the iframe.
    if 'Incapsula incident ID' in html and 'Request unsuccessful' in html:
        return True
    return False


def _is_bot_challenge() -> bool:
    url, _ = get_page_info()
    url = url.lower()
    body = get_body_text(3000).lower()
    if any(k in body or k in url for k in [
        "please complete the security check", "checking your browser before accessing",
        "ddos protection", "just a moment...", "we are checking your browser",
        "verify you are human", "_incapsula_resource", "request unsuccessful. incapsula",
    ]):
        return True
    return _is_incapsula_challenge()


def _wait_for_security_check(timeout: int = 120, poll: float = 1.0) -> bool:
    """Wait for a bot/WAF challenge to clear.

    Incapsula challenges often resolve themselves in the iframe after a few
    seconds once the browser executes the challenge script. We poll the page
    and return as soon as the challenge disappears.
    """
    deadline = time.monotonic() + timeout
    i = 0
    while time.monotonic() < deadline:
        if not _is_bot_challenge():
            return True
        if i % 10 == 0:
            print(f"  Waiting for security challenge... ({i}s)")
        time.sleep(poll)
        i += 1
    return not _is_bot_challenge()


# ─────── Form interaction ────────


def fill_input(selector: str, value: str) -> bool:
    safe_sel = json.dumps(selector)
    escaped = value.replace("\\", "\\\\").replace("'", "\\'").replace("\n", "\\n")
    return bridge_eval(f"""
        (()=>{{
          const el = document.querySelector({safe_sel});
          if (!el) return false;
          el.focus();
          try {{ const s = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,"value").set; s.call(el,'{escaped}'); }}
          catch(e) {{ el.value = '{escaped}'; }}
          el.dispatchEvent(new Event('input',{{bubbles:true}}));
          el.dispatchEvent(new Event('change',{{bubbles:true}}));
          el.dispatchEvent(new Event('blur',{{bubbles:true}}));
          return true;
        }})()
    """) is True


def select_option(selector: str, value: str) -> bool:
    safe_sel = json.dumps(selector)
    escaped = value.replace("'", "\\'")
    return bridge_eval(f"""
        (()=>{{
          const el = document.querySelector({safe_sel});
          if (!el || !el.options) return false;
          for (let o of el.options)
            if (o.value==='{escaped}' || o.text.trim().toLowerCase()==='{escaped}'.toLowerCase())
              {{ el.value=o.value; el.dispatchEvent(new Event('change',{{bubbles:true}})); return true; }}
          for (let o of el.options)
            if (o.text.toLowerCase().includes('{escaped}'.toLowerCase()))
              {{ el.value=o.value; el.dispatchEvent(new Event('change',{{bubbles:true}})); return true; }}
          return false;
        }})()
    """) is True


def click_element(selector: str) -> bool:
    safe_sel = json.dumps(selector)
    return bridge_eval(f"""
        (()=>{{
          const el = document.querySelector({safe_sel});
          if (!el) return false;
          el.scrollIntoView({{block: 'center', inline: 'center'}});
          el.focus?.();
          el.click();
          el.dispatchEvent(new MouseEvent('click', {{bubbles:true, cancelable:true, view:window}}));
          return true;
        }})()
    """) is True


def click_by_text(text: str, tag: str = "button,a,span") -> bool:
    escaped = text.replace("'", "\\'")
    safe_tag = json.dumps(tag)
    return bridge_eval(f"""
        (()=>{{
          const els = Array.from(document.querySelectorAll({safe_tag}));
          const found = els.find(e=>{{
            const r=e.getBoundingClientRect();
            const text=(e.textContent||'').trim().toLowerCase();
            const disabled=e.disabled || e.getAttribute('aria-disabled')==='true';
            return r.width>0&&r.height>0&&!disabled&&text.includes('{escaped}'.toLowerCase());
          }});
          if (found) {{
            found.scrollIntoView({{block: 'center', inline: 'center'}});
            found.focus?.();
            found.click();
            found.dispatchEvent(new MouseEvent('click', {{bubbles:true, cancelable:true, view:window}}));
            return true;
          }}
          return false;
        }})()
    """) is True


def click_by_exact_text(text: str, tag: str = "button,a,span") -> bool:
    """Click an element whose trimmed text exactly matches *text*.

    Use this instead of click_by_text when a substring match would hit the
    wrong element (e.g. "Skip" matching "Skip to Main Content").
    """
    escaped = text.replace("'", "\\'")
    safe_tag = json.dumps(tag)
    return bridge_eval(f"""
        (()=>{{
          const els = Array.from(document.querySelectorAll({safe_tag}));
          const found = els.find(e=>{{
            const r=e.getBoundingClientRect();
            const t=(e.textContent||'').trim().toLowerCase();
            const disabled=e.disabled || e.getAttribute('aria-disabled')==='true';
            return r.width>0&&r.height>0&&!disabled&&t==='{escaped}'.toLowerCase();
          }});
          if (found) {{
            found.scrollIntoView({{block: 'center', inline: 'center'}});
            found.focus?.();
            found.click();
            found.dispatchEvent(new MouseEvent('click', {{bubbles:true, cancelable:true, view:window}}));
            return true;
          }}
          return false;
        }})()
    """) is True


def element_exists(selector: str) -> bool:
    safe_sel = json.dumps(selector)
    return bridge_eval(f"document.querySelector({safe_sel}) !== null") is True


def get_input_value(selector: str) -> str:
    safe_sel = json.dumps(selector)
    return bridge_eval(f"(()=>{{const el=document.querySelector({safe_sel});if(!el)return '';return el.value||el.textContent||'';}})()") or ""


def is_checked(selector: str) -> bool:
    safe_sel = json.dumps(selector)
    return bridge_eval(f"!!(document.querySelector({safe_sel}))?.checked") is True


def _handle_address_verification_modal() -> bool:
    """Click 'Yes' on the OpenCCCApply 'Verify Address' suggestion modal.

    The modal asks the user to accept a USPS-standardized address. We always
    accept the suggested address so the form can advance.
    """
    return bridge_eval("""
        (() => {
          const modal = document.querySelector('.ReactModal__Content, .modal-body, .modal-content');
          if (!modal) return false;
          const text = (modal.textContent || '').toLowerCase();
          if (!text.includes('verify address') && !text.includes('suggested address')) return false;
          const btns = Array.from(modal.querySelectorAll('button, a, [role="button"]'));
          const yes = btns.find(b => {
            const r = b.getBoundingClientRect();
            const t = (b.textContent || '').trim().toLowerCase();
            return r.width > 0 && r.height > 0 && (t === 'yes' || t === 'use suggested address');
          });
          if (yes) { yes.click(); return true; }
          return false;
        })()
    """) is True


def _dismiss_modal_overlays() -> bool:
    # Handle the address verification modal first (accept the suggestion).
    if _handle_address_verification_modal():
        print("  Accepted suggested address")
        time.sleep(1)
        return True
    return bridge_eval("""
        (() => {
          let changed = false;
          const closeSelectors = [
            '#modalClosetBtn',
            '#dialogClosetBtn',
            '.ReactModalPortal button[aria-label*="close" i]',
            '.ReactModalPortal .close',
            '.ReactModalPortal button.close',
            '.modal button[aria-label*="close" i]',
            '.modal .close',
          ];
          for (const selector of closeSelectors) {
            for (const el of Array.from(document.querySelectorAll(selector))) {
              const r = el.getBoundingClientRect();
              if (r.width > 0 && r.height > 0) {
                el.click();
                changed = true;
              }
            }
          }
          for (const overlay of Array.from(document.querySelectorAll('.ReactModal__Overlay, .modal-backdrop'))) {
            overlay.style.pointerEvents = 'none';
            overlay.style.display = 'none';
            changed = true;
          }
          for (const body of [document.body, document.documentElement]) {
            if (body) {
              body.classList.remove('ReactModal__Body--open');
              body.style.overflow = 'auto';
            }
          }
          return changed;
        })()
    """) is True


def _click_first_selector(selectors: list[str]) -> bool:
    for selector in selectors:
        if element_exists(selector) and click_element(selector):
            return True
    return False


# ─────── OpenCCC page detection ────────


# The OpenCCC/Keycloak React app renders distinct page containers. Detecting
# the active page class lets us drive the flow deterministically instead of
# guessing from body text.
_OPENCCC_PAGE_CLASSES = {
    "send_code": "SendCodePage",
    "verify_code": "ContactVerifyPage",
    "registration": "RegistrationPage",
    "terms": "TermsPage",
    "review": "ReviewPage",
    "confirmation": "ConfirmationPage",
}


def _detect_openccc_page() -> str:
    """Return the active OpenCCC page type ('send_code', 'verify_code', ...) or ''."""
    raw = bridge_eval("""
        (() => {
          const root = document.querySelector('#main-content, .main-content, #app');
          if (!root) return '';
          const el = root.querySelector('[class*="Page"]');
          if (!el) return '';
          return Array.from(el.classList).join(' ');
        })()
    """)
    if not raw or not isinstance(raw, str):
        return ""
    classes = raw.lower()
    for key, cls in _OPENCCC_PAGE_CLASSES.items():
        if cls.lower() in classes:
            return key
    return ""


def _has_registration_fields() -> bool:
    """True if the Keycloak account-creation fields are present on the page."""
    return bridge_eval("""
        (() => {
          const ids = ['firstName','lastName','username','password','confirmPassword'];
          return ids.some(id => !!document.getElementById(id));
        })()
    """) is True


# ─────── Form helpers ────────


def _fill_send_code_form(email: str) -> bool:
    print("  Filling email for verification...")
    # The SendCode page has a "Use mobile phone instead" toggle. Keep email mode.
    if element_exists("#togglelink") and element_exists("#email"):
        # Already in email mode; ensure the email field is visible.
        pass
    if element_exists("#email"):
        fill_input("#email", email)
        time.sleep(0.5)
        print(f"    Filled email: {email}")
        return True
    if element_exists("[name='email']"):
        fill_input("[name='email']", email)
        time.sleep(0.5)
        return True
    print("    [!] No email field found")
    return False


def _fill_registration_form(profile: ProfileRecord, email: str, password: str, username: str) -> bool:
    print("  Filling registration form...")
    fields = {
        "firstName": profile.first_name.title(), "lastName": profile.last_name.title(),
        "email": email, "confirmEmail": email, "username": username,
        "password": password, "confirmPassword": password,
    }
    for fid, val in fields.items():
        # Try exact id, exact name, then case-insensitive id/name fallbacks
        # (OpenCCCApply uses lowercase ids like "confirmpassword").
        selectors = [f"#{fid}", f"[name='{fid}']"]
        lc = fid.lower()
        if lc != fid:
            selectors += [f"#{lc}", f"[name='{lc}']"]
        for sel in selectors:
            if element_exists(sel) and not get_input_value(sel):
                fill_input(sel, val)
                print(f"    Filled {sel}")
                time.sleep(0.2)

    if element_exists("#securityQuestion"):
        q = random.choice(SECURITY_QUESTIONS)
        bridge_eval(f"""
            (()=>{{
              const sel = document.getElementById('securityQuestion');
              if (!sel) return;
              for (let o of sel.options)
                if (o.text.trim()==='{q.replace("'","\\'")}') {{ sel.value=o.value; sel.dispatchEvent(new Event('change',{{bubbles:true}})); return; }}
              if (sel.options.length>1) {{ sel.selectedIndex=1; sel.dispatchEvent(new Event('change',{{bubbles:true}})); }}
            }})()
        """)
        print("    Selected security question")
        time.sleep(0.3)

    if element_exists("#securityAnswer"):
        fill_input("#securityAnswer", f"{profile.city}{random.randint(1,99)}")
        print("    Filled security answer")

    for cb in ["#terms", "#consent", "[name='terms']", "[name='consent']", "#agree"]:
        if element_exists(cb) and not is_checked(cb):
            click_element(cb)
            print(f"    Checked: {cb}")
            time.sleep(0.2)
    return True


def _click_submit_button() -> bool:
    if click_element("button[type='submit']:not([disabled])"):
        print("    Clicked: button[type='submit']")
        time.sleep(2)
        return True
    for bt in ["Continue", "Submit", "Create Account", "Next", "Send Code", "Verify"]:
        if click_by_text(bt, "button"):
            print(f"    Clicked: {bt}")
            time.sleep(2)
            return True
    return False


def _fill_ccc_apply_form(profile: ProfileRecord, email: str, phone: str, password: str = "") -> None:
    if _dismiss_modal_overlays():
        print("  Dismissed modal overlay")
        time.sleep(0.5)
    for mt in ["Yes, keep me signed in", "No, end my session"]:
        if click_by_text(mt, "button"):
            print(f"  Dismissed: {mt}")
            time.sleep(0.5)

    inputs = dump_visible_elements()
    print(f"  Found {len(inputs)} visible elements")
    filled_any = False

    for inp in inputs:
        iid = inp["id"]; iname = inp["name"]
        combined = f"{iid} {iname} {inp.get('placeholder','')}".lower()
        sel = f"#{iid}" if iid else f"[name='{iname}']" if iname else ""
        if not sel:
            continue
        tag = inp["tag"]; itype = inp.get("type","")

        if tag == "select":
            if "gender" in combined or "sex" in combined:
                select_option(sel, "Male")
                filled_any = True
            elif "primaryphonetype" in combined or ("phone type" in combined):
                select_option(sel, "mobile")
                print("    Selected phone type: Mobile")
                filled_any = True
            elif "state" in combined:
                select_option(sel, profile.state)
                print(f"    Selected state: {profile.state}")
                filled_any = True
            elif ("month" in combined and "birth" in combined) or "dobmonth" in combined:
                select_option(sel, profile.dob.split("/")[0])
                filled_any = True
            elif ("year" in combined and "birth" in combined) or "dobyear" in combined:
                select_option(sel, profile.dob.split("/")[2])
                filled_any = True
            elif "education" in combined or "grade" in combined or "level" in combined:
                select_option(sel, "12")
                filled_any = True
            elif "english" in combined or "language" in combined:
                select_option(sel, "Yes")
                filled_any = True
            elif "citizen" in combined or "citizenship" in combined:
                select_option(sel, "US Citizen")
                filled_any = True
            elif "country" in combined:
                if select_option(sel, "United States") or select_option(sel, "US"):
                    filled_any = True
            elif "ethnicity" in combined or "race" in combined:
                select_option(sel, "Prefer not to say")
                filled_any = True
            elif "income" in combined:
                select_option(sel, "Prefer not to say")
                filled_any = True
            elif "county" in combined:
                select_option(sel, "Alameda")
                filled_any = True
            elif "military" in combined or "veteran" in combined:
                select_option(sel, "No")
                filled_any = True
            elif "suffix" in combined:
                bridge_eval(f"(()=>{{const s=document.querySelector({json.dumps(sel)});if(s&&s.options.length>0){{s.value=s.options[0].value;s.dispatchEvent(new Event('change',{{bubbles:true}}));}}}})()")
                filled_any = True
            elif ("day" in combined and ("birth" in combined or "dob" in combined)):
                select_option(sel, profile.dob.split("/")[1])
                filled_any = True
            else:
                bridge_eval(f"(()=>{{const s=document.querySelector({json.dumps(sel)});if(s&&s.options.length>1){{for(let i=1;i<s.options.length;i++){{if(s.options[i].value){{s.value=s.options[i].value;s.dispatchEvent(new Event('change',{{bubbles:true}}));return;}}}}}}}})()")
                filled_any = True

        elif tag == "input" and itype == "text":
            val = None
            if "ssn" in combined or "social" in combined or "tax" in combined:
                val = profile.ssn.replace("-","")
            elif "first" in combined or "fname" in combined:
                val = profile.first_name.title()
            elif "last" in combined or "lname" in combined:
                val = profile.last_name.title()
            elif "middle" in combined or "mid" in combined:
                val = ""
            elif "preferred" in combined:
                val = profile.first_name.title()
            elif "address" in combined and "2" not in iid:
                val = profile.address
            elif "street1" in combined or ("street" in combined and "2" not in combined):
                val = profile.address
            elif "street2" in combined:
                val = ""
            elif "city" in combined:
                val = profile.city
            elif "zip" in combined or "postal" in combined:
                val = profile.zip_code
            elif "phone" in combined or "mobile" in combined or "telephone" in combined:
                val = phone
            elif "email" in combined:
                val = email
            if val is not None and len(get_input_value(sel)) < 2:
                fill_input(sel, val)
                print(f"    Filled {iid or iname}: {val[:20]}...")
                filled_any = True

        elif tag == "input" and itype == "password":
            val = None
            if "ssn" in combined or "social" in combined:
                val = profile.ssn.replace("-", "")
            elif "confirm" in combined and password:
                val = password
            elif "password" in combined and password:
                val = password
            if val is not None and len(get_input_value(sel)) < 2:
                fill_input(sel, val)
                print(f"    Filled {iid or iname}: {'*' * len(val)}")
                filled_any = True

        elif tag == "input" and itype == "date":
            if "dob" in combined or "birth" in combined:
                parts = profile.dob.split("/")
                if len(parts) == 3:
                    val = f"{parts[2]}-{parts[0].zfill(2)}-{parts[1].zfill(2)}"
                    if len(get_input_value(sel)) < 2:
                        if fill_input(sel, val):
                            print(f"    Filled {iid or iname}: {val}")
                            filled_any = True

        elif tag == "input" and itype == "radio":
            tl = inp.get("text","").lower(); ic = iid.lower()
            if "ssn" in combined:
                if "yes" in ic or "1" in ic:
                    click_element(sel); print(f"    Selected radio (has SSN)"); filled_any = True
            elif any(k in tl or k in combined for k in ["male","man"]):
                click_element(sel); filled_any = True
            elif "homeless" in combined and ("no" in ic or tl == "no"):
                click_element(sel); print("    Selected radio (not homeless)"); filled_any = True
            elif any(k in tl for k in ["no","none","decline"]):
                click_element(sel); filled_any = True

        elif tag == "input" and itype == "checkbox":
            text = inp.get("text","").lower()
            if "no ssn" in text or "nossn" in combined:
                continue
            if any(k in text or k in combined for k in ["agree","accept","terms","consent","confirm","understand"]):
                if not is_checked(sel):
                    click_element(sel); print(f"    Checked: {iid or iname}"); filled_any = True

    if not filled_any:
        print("  [!!] No fields filled - may need manual review")


def _advance_ccc_apply_step() -> bool:
    _dismiss_modal_overlays()

    # On the Credentials step the only actionable submit button is
    # "Create Account".  Skip the tab-navigation buttons (#btn_*) so we
    # don't bounce back to an earlier tab and get stuck in a loop.
    if element_exists("#password") or element_exists("#confirmpassword"):
        if click_by_text("Create Account", "button,input[type=submit]"):
            print("    Clicked: Create Account")
            time.sleep(2)
            return True

    selector_groups = [
        [
            "#ContactInfoNextButton",
            "#PersonalInfoNextButton",
            "#CredentialsNextButton",
            "[data-testid='contactInfoNextButton']",
            "[data-testid='personalInfoNextButton']",
            "[data-testid='credentialsNextButton']",
        ],
        [
            "#btn_personalinfo",
            "#btn_contactinfo",
            "#btn_credentials",
        ],
        [
            "button[type='submit']:not(#btn_contactinfo):not(#btn_personalinfo):not(#btn_credentials):not(#dialogClosetBtn):not(#modalClosetBtn)",
        ],
    ]
    for selectors in selector_groups:
        if _click_first_selector(selectors):
            return True
    for text in [
        "Create Account",
        "Next",
        "Continue",
        "Save and Continue",
        "Submit",
        "I Agree",
        "Agree",
        "Review",
        "Submit Application",
        "Finish",
        "Done",
        "Yes",
        "Confirm",
        "Verify Mobile Phone",
        "Verify",
    ]:
        for tag in ["button", "input[type=submit]", "a", "span"]:
            if click_by_text(text, tag):
                return True
    return False


# ─────── Email verification ────────


def _read_verification_code(email: str, timeout: int = 120) -> str | None:
    """Poll the catchmail mailbox for a 6-digit verification code.

    Prefers the project's CatchMailMailbox abstraction (which handles proxies,
    content decoding and keyword filtering) and falls back to a direct API call.
    """
    print("  Polling catchmail mailbox for verification code...")

    # Try the project mailbox abstraction first.
    try:
        from core.catchmail_mailbox import CatchMailMailbox
        from core.base_mailbox import MailboxAccount

        mailbox = CatchMailMailbox()
        account = MailboxAccount(email=email, account_id=email, extra={"provider": "catchmail"})
        code = mailbox.wait_for_code(
            account=account,
            keyword="",
            timeout=timeout,
            code_pattern=r"\b(\d{6})\b",
        )
        if code:
            print(f"  Found code: {code}")
            return code
    except Exception as e:
        print(f"  CatchMailMailbox unavailable ({e}), falling back to direct API")

    # Fallback: direct catchmail.io API polling.
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            req = urllib.request.Request(
                f"https://api.catchmail.io/api/v1/mailbox?address={email}",
                headers={"accept": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
        except Exception as e:
            elapsed = int(time.monotonic() - (deadline - timeout))
            print(f"    Mailbox poll error ({elapsed}s): {e}")
            time.sleep(5)
            continue
        messages = data if isinstance(data, list) else data.get("messages") or data.get("emails") or []
        for msg in messages:
            if not isinstance(msg, dict):
                continue
            mid = msg.get("id") or msg.get("messageId") or ""
            if not mid:
                continue
            try:
                detail_req = urllib.request.Request(
                    f"https://api.catchmail.io/api/v1/message/{mid}?mailbox={email}",
                    headers={"accept": "application/json"},
                )
                with urllib.request.urlopen(detail_req, timeout=10) as resp:
                    detail = json.loads(resp.read().decode())
            except Exception:
                continue
            search = " ".join(str(detail.get(s,"")) for s in ("subject","from","text","body","html","content"))
            codes = re.findall(r"\b(\d{6})\b", search)
            if codes:
                print(f"  Found code: {codes[0]}")
                return codes[0]
        time.sleep(3)
    print(f"  [!] No code after {timeout}s")
    return None


# ─────── Profile ────────


def _parse_dataset(path: str | Path, line_no: int) -> ProfileRecord:
    lines = [l.strip() for l in Path(path).read_text(encoding="utf-8",errors="ignore").splitlines() if l.strip()]
    if line_no < 1 or line_no > len(lines):
        raise IndexError(f"line {line_no} out of bounds")
    parts = lines[line_no-1].split("|")
    if len(parts) < 8:
        raise ValueError(f"bad format: {lines[line_no-1]!r}")
    return ProfileRecord(line_no=line_no, first_name=parts[0], last_name=parts[1],
                         address=parts[2], city=parts[3], state=parts[4],
                         zip_code=parts[5], dob=parts[6], ssn=parts[7])


def _make_email(profile: ProfileRecord, domain: str = "catchmail.io") -> str:
    first = re.sub(r"[^a-z]", "", profile.first_name.lower())
    last = re.sub(r"[^a-z]", "", profile.last_name.lower())
    return f"{first}{last}{random.randint(1000,9999)}@{domain}"


# ─────── Main ────────


def main() -> int:
    # Track generated email so callers can retrieve it after main() returns.
    global _generated_email
    _generated_email = None
    global BRIDGE_URL

    parser = argparse.ArgumentParser(description="DVC/OpenCCC account registration via CDP bridge")
    parser.add_argument("--dataset", default="pointclickcare data.txt")
    parser.add_argument("--line", type=int, default=0)
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--email-domain", default="catchmail.io")
    parser.add_argument("--email", type=str, default=None)
    parser.add_argument("--phone", type=str, default=None)
    parser.add_argument("--dry-run", action="store_true", default=False)
    parser.add_argument("--smspool-api-key", type=str, default="")
    parser.add_argument("--smspool-country", type=str, default="1")
    parser.add_argument("--smspool-service", type=str, default="")
    parser.add_argument("--smspool-pricing-option", type=str, default="1")
    parser.add_argument("--smspool-max-price", type=str, default="")
    parser.add_argument("--smspool-max-attempts", type=int, default=3)
    parser.add_argument("--smspool-poll-interval", type=int, default=5)
    parser.add_argument("--smspool-poll-timeout", type=int, default=120)
    parser.add_argument("--capsolver-key", type=str, default="")
    parser.add_argument("--bridge", type=str, default="http://localhost:3005", help="CDP bridge URL")
    args = parser.parse_args()
    BRIDGE_URL = args.bridge

    _ensure_dir(RESULTS_DIR)

    if args.line:
        profile = _parse_dataset(args.dataset, args.line)
    else:
        profile = choose_random_unused_male_profile(args.dataset, DVC_USED_LINES, seed=args.seed)

    email = args.email or _make_email(profile, domain=args.email_domain)
    _generated_email = email
    password = f"Dvc!{profile.line_no:04d}{random.randint(1000,9999)}"
    username = f"dvc{profile.line_no:04d}{random.randint(100,999)}"
    phone = args.phone or f"510{random.randint(200,999):03d}{random.randint(1000,9999):04d}"

    summary = {
        "profile": asdict(profile), "email": email, "password": password,
        "username": username, "phone": phone, "target_url": TARGET_URL,
        "dry_run": args.dry_run, "timestamp": int(time.time()),
    }
    summary_path = RESULTS_DIR / f"dvc_summary_line_{profile.line_no}.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(f"Profile line {profile.line_no}: {profile.full_name}")
    print(f"Email: {email}\nPassword: {password}\nUsername: {username}\nPhone: {phone}")

    if args.dry_run:
        print("Dry-run mode.")
        return 0

    capsolver_key = args.capsolver_key
    if not capsolver_key:
        try:
            from core.config_store import config_store as _cs
            capsolver_key = _cs.get("capsolver_key", "")
        except Exception:
            pass

    smspool_service = None
    if args.smspool_api_key:
        try:
            from platforms.chatgpt.smspool_service import SMSPoolPhoneService
            cfg = {
                "smspool_api_key": args.smspool_api_key,
                "smspool_country": args.smspool_country,
                "smspool_service": args.smspool_service or "",
                "smspool_pricing_option": args.smspool_pricing_option,
                "smspool_max_price": args.smspool_max_price,
                "smspool_max_attempts": args.smspool_max_attempts,
                "smspool_poll_interval": args.smspool_poll_interval,
                "smspool_poll_timeout": args.smspool_poll_timeout,
            }
            srv = SMSPoolPhoneService(config=cfg, log_fn=lambda m: print(f"  [SMSPool] {m}"))
            if srv.enabled:
                smspool_service = srv
                print("  SMSPool enabled")
        except Exception as e:
            print(f"  SMSPool init: {e}")

    # ── Connect to bridge ──
    status = bridge_get("/status")
    if not status or not status.get("connected"):
        print(f"[ERROR] Cannot connect to CDP bridge at {BRIDGE_URL}")
        print("  Start the bridge and Chrome:")
        print("    cd devtools-inspector && npm run launch-chrome")
        print("    cd devtools-inspector && npm start")
        return 1

    print(f"[OK] Connected to bridge: {BRIDGE_URL}")
    url, title = get_page_info()
    print(f"  Page: {title}\n  URL: {url}")

    step = 0
    try:
        # Clear session — if we're already logged in (e.g. from a previous
        # successful run) sign out via the Keycloak logout endpoint so the
        # server-side session is invalidated.  We deliberately do NOT clear
        # all browser cookies because that would also wipe the Imperva WAF
        # challenge cookies (reese84, incap_ses, visid_incap, nlbi) which
        # take a long time to re-solve and can block the entire flow.
        if "uportal" in url.lower() or "my applications" in (title or "").lower():
            print("  Already logged in — signing out first...")
            bridge_navigate("https://account.cccmypath.org/auth/realms/OpenCCC/protocol/openid-connect/logout?redirect_uri=https://www.opencccapply.net/gateway/apply?cccMisCode=312")
            time.sleep(5)
            # Verify logout worked
            url2, title2 = get_page_info()
            if "uportal" in url2.lower() and "my applications" in (title2 or "").lower():
                print("  [!] Still logged in — trying uPortal logout")
                bridge_navigate("https://www.opencccapply.net/uPortal/pLogout")
                time.sleep(5)
        # Clear JS storage only (keep Imperva cookies intact)
        bridge_eval("localStorage?.clear(); sessionStorage?.clear()")

        # ── STEP 1: Navigate ──
        step += 1
        print(f"\n{'='*60}\nStep {step}: Navigating to {TARGET_URL}")
        bridge_navigate(TARGET_URL)
        time.sleep(3)
        # Wait for the OpenCCCApply gateway to load and resolve any
        # Imperva/Incapsula interstitial ("Please stand by") or bot challenge.
        for _ in range(30):
            url, _ = get_page_info()
            if "opencccapply" in url or "cccapply" in url or "cccmypath" in url:
                if _wait_for_page_ready(timeout=60):
                    break
            time.sleep(2)
        time.sleep(2)
        save_page_snapshot(f"dvc_step_{step:02d}_landing_line_{profile.line_no}")
        url, title = get_page_info()
        print(f"  Title: {title}\n  URL: {url}")

        # WAF / interstitial handling with retry + refresh
        if _is_bot_challenge() or _is_loading_interstitial():
            print("  WAF/loading interstitial detected, waiting up to 3min...")
            resolved = _wait_for_page_ready(timeout=180)
            save_page_snapshot(f"dvc_step_{step:02d}_challenge_line_{profile.line_no}")
            if not resolved:
                print("  Trying page refresh to bypass WAF...")
                for r in range(3):
                    bridge_navigate(TARGET_URL)
                    time.sleep(5)
                    for _ in range(15):
                        url, _ = get_page_info()
                        if "opencccapply" in url or "cccapply" in url or "cccmypath" in url:
                            break
                        time.sleep(1)
                    if _wait_for_page_ready(timeout=90):
                        resolved = True
                        print("  WAF cleared after refresh!")
                        break
                    print(f"  Refresh {r+1} didn't clear WAF")
                if not resolved:
                    print("[!!] Cannot bypass WAF. Open Chrome manually and solve the challenge, then re-run.")
                    summary["status"] = "blocked_by_waf"
                    return 1

        # ── STEP 2: Registration flow ──
        step += 1
        print(f"\n{'='*60}\nStep {step}: Registration flow")
        page_type = _detect_openccc_page()
        body_text = get_body_text(3000).lower()
        print(f"  Detected page: {page_type or 'unknown'}")

        # The OpenCCC gateway sometimes lands on a "Create Account / Sign In"
        # chooser before the SendCode page.
        if not page_type and ("create account" in body_text or "create an account" in body_text):
            print("  'Create Account' chooser page")
            for bt in ["Create Account", "Create an account", "Register"]:
                if click_by_text(bt, "button,a,span"):
                    print(f"  Clicked '{bt}'")
                    time.sleep(3)
                    break
            page_type = _detect_openccc_page()

        if not page_type and "sign in" in body_text:
            print("  Sign-in page — switching to Create Account")
            if click_by_text("Create Account", "a,button,span"):
                print("  Clicked Create Account")
                time.sleep(3)
                page_type = _detect_openccc_page()

        save_page_snapshot(f"dvc_step_{step:02d}_create_account_line_{profile.line_no}")

        # ── SendCode page: enter email and request a security code ──
        if page_type == "send_code" or element_exists("#email"):
            print("  Registration email step")
            _fill_send_code_form(email)
            time.sleep(1)

            if _click_submit_button():
                print("  Verification code sent")
                save_page_snapshot(f"dvc_step_{step:02d}_after_send_code_line_{profile.line_no}")

                # Wait for the verify-code page (or a direct jump to registration).
                for _ in range(30):
                    time.sleep(2)
                    if _is_bot_challenge():
                        _wait_for_security_check(timeout=60)
                    if element_exists("#code") or element_exists("#verificationCode") or element_exists("#otp") or element_exists("[name='code']"):
                        break
                    cur_page = _detect_openccc_page()
                    if cur_page in ("registration", "terms"):
                        break
                    url, _ = get_page_info()
                    body = get_body_text(2000).lower()
                    if any(k in url.lower() for k in ["password", "username", "first-name"]):
                        break
                    if any(k in body for k in ["create your password", "set up your account", "first name"]):
                        break

                save_page_snapshot(f"dvc_step_{step:02d}_after_code_line_{profile.line_no}")

                # ── VerifyCode page: read and submit the security code ──
                code_selectors = ["#code", "#verificationCode", "#otp", "[name='code']", "[name='verificationCode']"]
                if any(element_exists(s) for s in code_selectors):
                    print("  Reading verification code...")
                    otp = _read_verification_code(email)
                    if otp:
                        print(f"  Code: {otp}")
                        for sel in code_selectors:
                            if element_exists(sel):
                                fill_input(sel, otp)
                                break
                        time.sleep(0.5)
                        if _click_submit_button():
                            print("  Code submitted")
                            time.sleep(3)
                            save_page_snapshot(f"dvc_step_{step:02d}_verified_line_{profile.line_no}")

                            # Some flows show an optional phone step after verification.
                            # The phone page is a ContactVerifyPage with a "Skip" link.
                            if element_exists("#phone") or _detect_openccc_page() in ("send_code", "verify_code"):
                                print("  Phone step detected")
                                skipped = False
                                for _ in range(3):
                                    if click_by_exact_text("Skip", "a,button,span"):
                                        print("  Clicked Skip")
                                        time.sleep(3)
                                        save_page_snapshot(f"dvc_step_{step:02d}_phone_skipped_line_{profile.line_no}")
                                        cur = _detect_openccc_page()
                                        if cur not in ("send_code", "verify_code") and not element_exists("#phone"):
                                            skipped = True
                                            break
                                        print("  Phone page still showing, retrying Skip...")
                                        time.sleep(2)
                                    else:
                                        print("  No Skip link found")
                                        break
                                if not skipped and element_exists("#phone"):
                                    print("  Phone step could not be skipped - continuing")
                    else:
                        print("  [!] No verification code received")
                else:
                    print("  Code field never appeared")

            # ── Registration page: fill account credentials ──
            time.sleep(2)
            if _has_registration_fields() or _detect_openccc_page() == "registration":
                print("  Registration form detected")
                _fill_registration_form(profile, email, password, username)
                time.sleep(0.5)
                if not _click_submit_button():
                    for bt in ["Create Account", "Submit", "Continue", "Register", "Next"]:
                        if click_by_text(bt, "button,input[type=submit],a"):
                            print(f"  Clicked '{bt}'")
                            time.sleep(3)
                            break

            save_page_snapshot(f"dvc_step_{step:02d}_after_create_account_line_{profile.line_no}")

        elif _has_registration_fields() or page_type == "registration":
            print("  Registration form (direct)")
            _fill_registration_form(profile, email, password, username)
            time.sleep(0.5)
            if not _click_submit_button():
                for bt in ["Create Account", "Submit", "Continue", "Register", "Next"]:
                    if click_by_text(bt, "button,input[type=submit],a"):
                        print(f"  Clicked '{bt}'")
                        time.sleep(3)
                        break
            save_page_snapshot(f"dvc_step_{step:02d}_after_create_account_line_{profile.line_no}")

        else:
            print("  Unknown page state. Elements:")
            save_page_snapshot(f"dvc_step_{step:02d}_unknown_line_{profile.line_no}")
            for item in dump_visible_elements()[:15]:
                print(f"  <{item['tag']}> id='{item['id']}' text='{item['text'][:60]}'")

        # ── STEPS 3-40: Form loop ──
        print(f"\n{'='*60}\nStarting application form fill loop...")
        prev_state = ""
        stuck = 0
        waf_streak = 0

        def _page_state_key(url: str, elements: list[dict[str, Any]]) -> str:
            """Compact signature of the current page to detect progress/stuck states."""
            ids = ",".join(sorted({e.get("id") or e.get("name") or "" for e in elements if e.get("id") or e.get("name")}))
            return f"{url[:120]}|{len(elements)}|{ids}"

        for form_step in range(40):
            time.sleep(2)

            # Dismiss modals
            if element_exists("#modalClosetBtn"):
                click_element("#modalClosetBtn"); print("  Dismissed modal"); time.sleep(0.5)
            for mt in ["Yes, keep me signed in", "No, end my session"]:
                if click_by_text(mt, "button"):
                    print(f"  Dismissed: {mt}"); time.sleep(0.5)

            step += 1
            url, title = get_page_info()
            body = get_body_text(3000).lower()
            if form_step <= 2:
                print(f"  [debug] body: {body[:500]}")
            print(f"\n--- Form Step {form_step+1} (URL: {url[:80]}) ---")

            # WAF during form loop
            if _is_incapsula_challenge():
                waf_streak += 1
                if waf_streak >= 3:
                    print(f"[!!] WAF {waf_streak}x consecutive - aborting")
                    summary["status"] = "blocked_by_waf"
                    save_page_snapshot(f"dvc_step_{step:02d}_waf_persisted_line_{profile.line_no}")
                    break
                print(f"  WAF (streak={waf_streak}), waiting up to 3min...")
                save_page_snapshot(f"dvc_step_{step:02d}_waf_line_{profile.line_no}")
                if _wait_for_security_check(timeout=180):
                    waf_streak = 0; print("  WAF resolved"); time.sleep(3)
                    url, _ = get_page_info(); body = get_body_text(3000).lower()
                else:
                    print("[!!] WAF persisted"); summary["status"] = "blocked_by_waf"; break
            else:
                waf_streak = 0

            # Completion check (URL + body text + OpenCCC confirmation page)
            cur_page = _detect_openccc_page()
            if cur_page == "confirmation" or any(k in url.lower() for k in ["confirmation","success","thank","complete","submitted"]):
                print("[OK] Submitted!"); save_page_snapshot(f"dvc_step_{step:02d}_submitted_line_{profile.line_no}")
                summary["status"] = "submitted"; break
            if any(k in body for k in ["your application has been submitted","thank you for applying","application complete","submission confirmation"]):
                print("[OK] Complete!"); save_page_snapshot(f"dvc_step_{step:02d}_submitted_line_{profile.line_no}")
                summary["status"] = "submitted"; break
            # After "Create Account" the browser lands on either the OpenCCCApply
            # uPortal dashboard or the ID.me identity verification page — both
            # mean the CCC account itself was created successfully.
            if "uportal" in url.lower() or ("start a new application" in body and "my applications" in body):
                print("[OK] Account created — landed on OpenCCCApply portal!")
                save_page_snapshot(f"dvc_step_{step:02d}_portal_line_{profile.line_no}")
                summary["status"] = "submitted"; break
            if "id.me" in url.lower():
                print("[OK] Account created — landed on ID.me verification page!")
                save_page_snapshot(f"dvc_step_{step:02d}_idme_line_{profile.line_no}")
                summary["status"] = "submitted"; break

            save_page_snapshot(f"dvc_step_{step:02d}_form_line_{profile.line_no}")
            elements = dump_visible_elements()
            print(f"  Elements: {len(elements)}")

            # SMS / verification code check
            pt = get_body_text(3000).lower()
            is_sms = any(k in pt for k in ["security code","verification code","code has been sent","enter the code","verify your account"])
            has_code = element_exists("#code") or any(e["id"]=="code" for e in elements)
            if is_sms or has_code:
                print("  [!] SMS code required")
                # Try to skip the phone verification step first.
                if click_by_exact_text("Skip", "a,button,span"):
                    print("  Clicked Skip on SMS/phone page")
                    time.sleep(3)
                    save_page_snapshot(f"dvc_step_{step:02d}_sms_skipped_line_{profile.line_no}")
                    continue
                if smspool_service:
                    print("  SMSPool configured - waiting for code")
                    summary["status"] = "phone_sms_required"; break
                else:
                    print("  Enter code manually in Chrome, then press Enter")
                    try:
                        input("  Press Enter after entering SMS code...")
                    except EOFError:
                        print("  [!] No interactive input available - skipping")
                        summary["status"] = "phone_sms_required"
                        break
                    save_page_snapshot(f"dvc_step_{step:02d}_sms_manual_line_{profile.line_no}")
                    continue

            # Expand error sections
            if "please finish the following steps" in body or "please finish" in body:
                print("  Expanding incomplete sections...")
                for st in ["Personal Information","Contact Information"]:
                    if click_by_text(st, "button"):
                        print(f"  Expanded '{st}'"); time.sleep(1)
                time.sleep(2)
                elements = dump_visible_elements()
                print(f"  After expand: {len(elements)}")

            # Stuck check — no actionable elements at all
            all_empty = True
            for el in elements:
                if el["tag"] in ("input","select","textarea") and el.get("value",""):
                    all_empty = False; break
            if all_empty and form_step > 2:
                bts = [el.get("text","").lower() for el in elements if el["tag"] in ("button","a")]
                known = ["verify","resend","back to sign in","skip","continue","submit","next","review","finish"]
                if not any(k in " ".join(bts) for k in known):
                    print("  [!] No actionable elements"); summary["status"] = "stuck_no_action"; break

            # Keycloak vs CCCApply
            reg = ["firstName","lastName","username","password","confirmPassword"]
            if any(el["id"] in reg for el in elements):
                print("  Keycloak registration form")
                _fill_registration_form(profile, email, password, username)
                time.sleep(0.5)
            else:
                _fill_ccc_apply_form(profile, email, phone, password)

            if form_step == 0:
                print(f"  [debug] {[(e['id'],e['tag'],e.get('type',''),e['text'][:40]) for e in elements]}")

            # Email
            for fid in ["email","confirmEmail"]:
                if element_exists(f"#{fid}") and not get_input_value(f"#{fid}"):
                    fill_input(f"#{fid}", email)
                    print(f"    Filled {fid}")

            # Phone
            if element_exists("#primaryPhone") and not get_input_value("#primaryPhone"):
                rp = f"510{random.randint(200,999):03d}{random.randint(1000,9999):04d}"
                fill_input("#primaryPhone", rp); print(f"    Filled primaryPhone")

            # Homeless
            if element_exists("#noHomestead") and not is_checked("#noHomestead"):
                click_element("#noHomestead"); print("    No homeless"); time.sleep(0.2)

            # Checkboxes
            for el in elements:
                if el["tag"] == "input" and el.get("type") == "checkbox":
                    c = f"{el['id']} {el['name']} {el.get('text','')}".lower()
                    if any(k in c for k in ["agree","accept","terms","consent","confirm","understand"]):
                        s = f"#{el['id']}" if el['id'] else f"[name='{el['name']}']"
                        if not is_checked(s):
                            click_element(s); print(f"    Checked: {el['id'] or el['name']}"); time.sleep(0.2)

            time.sleep(0.5)

            # Click nav buttons
            clicked = _advance_ccc_apply_step()
            if clicked:
                print("  Advanced to next step")
                time.sleep(1.5)
                # Handle modals that appear as a result of clicking Next
                # (e.g. the "Verify Address" suggestion modal).
                for _ in range(3):
                    if _dismiss_modal_overlays():
                        print("  Dismissed modal")
                        time.sleep(1.5)
                    else:
                        break

            # Tab nav
            if not clicked:
                hc = any(e["id"] in ("email","confirmEmail","primaryPhone","acceptedTerms") for e in elements)
                hp = any(e["id"] in ("firstname","lastname","dob","first_name","last_name","dateOfBirth") for e in elements)
                hcr = any(e["id"].lower() in ("password","confirmpassword","username","password-confirm") for e in elements)
                if hc and not hp and not hcr and element_exists("#btn_personalinfo"):
                    print("  Tab: Personal Info"); _dismiss_modal_overlays(); click_element("#btn_personalinfo"); clicked = True; time.sleep(2)
                    for _ in range(3):
                        if _dismiss_modal_overlays():
                            print("  Dismissed modal"); time.sleep(1.5)
                        else:
                            break
                elif hp and not hcr and element_exists("#btn_credentials"):
                    print("  Tab: Credentials"); _dismiss_modal_overlays(); click_element("#btn_credentials"); clicked = True; time.sleep(2)
                    for _ in range(3):
                        if _dismiss_modal_overlays():
                            print("  Dismissed modal"); time.sleep(1.5)
                        else:
                            break
                elif hcr:
                    for bt in ["Create Account","Submit","Register"]:
                        if click_by_text(bt, "button,input[type=submit],a"):
                            print(f"  Clicked '{bt}'"); clicked = True; time.sleep(2); break

            # Stuck detection using a page-state signature (URL + element count + ids).
            state_key = _page_state_key(url, elements)
            if not clicked:
                print("  [!] No nav button")
                for item in elements[:8]:
                    print(f"    <{item['tag']}> id='{item['id']}' text='{item['text'][:60]}'")
                if state_key == prev_state:
                    stuck += 1
                else:
                    stuck = 0
                prev_state = state_key
                if stuck >= 3:
                    print("  [!] Stuck 3x — aborting"); summary["status"] = "stuck_no_action"; break
                time.sleep(3)
            else:
                # Progress was made; reset stuck counter but keep tracking state.
                stuck = 0
                prev_state = state_key

        else:
            print("[!] Max steps"); summary["status"] = "incomplete"

        if summary.get("status") == "submitted":
            save_used_line(DVC_USED_LINES, profile.line_no)
            print(f"  Line {profile.line_no} marked used!")

        url, title = get_page_info()
        summary["final_url"] = url
        summary["final_title"] = title
        summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        print(f"\n Summary: {summary_path}")

    except Exception as e:
        print(f"\n[ERROR] {e}")
        import traceback; traceback.print_exc()
        summary["status"] = "error"
        summary["error"] = str(e)
        summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
