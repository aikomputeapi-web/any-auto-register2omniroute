import sys
import os
import time
import re
import argparse
import urllib.request
import urllib.error
import json

# Add root directory to python path so we can import from core
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BRIDGE_URL = "http://localhost:3005"

def bridge_get(path):
    """GET request to the CDP bridge API."""
    url = f"{BRIDGE_URL}{path}"
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"  [!] Bridge GET {path} failed: {e}")
        return None

def find_context_by_origin(origin_substr):
    """Locate context ID matching origin substring."""
    contexts = bridge_get("/contexts")
    if not contexts:
        return None
    for ctx in contexts:
        origin = ctx.get("origin", "")
        if origin_substr in origin:
            return ctx.get("id")
    return None

def get_current_context():
    """Identify which context contains the active form elements."""
    # SWS Gateway hosts the credentials and OTP pages inside iframe lmsiframeid
    ctx = find_context_by_origin("sws-gateway-nr.schwab.com")
    if ctx:
        return ctx
    
    # OLA Content houses some supplementary screens - only target if url contains olacontent
    info = bridge_get("/page")
    url = info.get("url", "") if info else ""
    if "olacontent" in url.lower():
        ctx = find_context_by_origin("olacontent.schwab.com")
        if ctx:
            return ctx
            
    return None



def bridge_eval(expression, context_id=None):
    """Execute JavaScript in the page (or a specific iframe context) via the CDP bridge."""
    if context_id is None:
        context_id = get_current_context()
        
    url = f"{BRIDGE_URL}/eval"
    payload = {"expression": expression}
    if context_id is not None:
        payload["contextId"] = context_id
        
    data = json.dumps(payload).encode("utf-8")
    try:
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            return result.get("result")
    except Exception as e:
        # Fallback to default context if context_id failed
        if context_id is not None:
            return bridge_eval(expression, context_id=None)
        print(f"  [!] Bridge eval failed: {e}")
        return None

def bridge_navigate(url):
    """Navigate the page to a URL via JS."""
    bridge_eval(f"window.location.href = '{url}'", context_id=None)

def get_page_info():
    """Get current page URL and title."""
    info = bridge_get("/page")
    if info:
        return info.get("url", ""), info.get("title", "")
    return "", ""

def get_body_text():
    """Get visible page text from main context or iframe context."""
    # Attempt to merge main and iframe text
    main_text = bridge_eval("document.body ? document.body.innerText.substring(0, 2000) : ''", context_id=None) or ""
    iframe_ctx = get_current_context()
    iframe_text = ""
    if iframe_ctx:
        iframe_text = bridge_eval("document.body ? document.body.innerText.substring(0, 2000) : ''", context_id=iframe_ctx) or ""
    return (main_text + "\n" + iframe_text).strip()

def dump_visible_inputs():
    """Get all visible form inputs from the page across default and iframe contexts."""
    # Helper execution script
    js_query = """
    JSON.stringify(Array.from(document.querySelectorAll('input, select, textarea, button, a, [role="button"], [role="radio"]'))
        .filter(el => el.offsetWidth > 0 && el.offsetHeight > 0)
        .map(el => ({
            tag: el.tagName.toLowerCase(),
            id: el.id || '',
            name: el.name || '',
            type: el.type || '',
            placeholder: el.placeholder || '',
            ariaLabel: el.getAttribute('aria-label') || '',
            dataTestId: el.getAttribute('data-testid') || '',
            value: (el.value || '').substring(0, 40),
            text: (el.textContent || '').trim().substring(0, 80)
        })))
    """
    
    # Dump main context inputs
    main_raw = bridge_eval(js_query, context_id=None)
    main_inputs = json.loads(main_raw) if main_raw else []
    
    # Dump active iframe context inputs if exists
    iframe_ctx = get_current_context()
    iframe_inputs = []
    if iframe_ctx:
        iframe_raw = bridge_eval(js_query, context_id=iframe_ctx)
        if iframe_raw:
            iframe_inputs = json.loads(iframe_raw)
            
    # Combine inputs
    return main_inputs + iframe_inputs

def fill_input_js(selector, value):
    """Fill an input field using React-compatible JS."""
    escaped_val = value.replace("\\", "\\\\").replace("'", "\\'").replace("\n", "\\n")
    result = bridge_eval(f"""
    (() => {{
        try {{
            const el = document.querySelector('{selector}');
            if (!el) return 'NOT_FOUND';
            el.focus();
            try {{
                const setter = Object.getOwnPropertyDescriptor(
                    window.HTMLInputElement.prototype, "value"
                ).set;
                setter.call(el, '{escaped_val}');
            }} catch (e) {{
                el.value = '{escaped_val}';
            }}
            el.dispatchEvent(new Event('input', {{ bubbles: true }}));
            el.dispatchEvent(new Event('change', {{ bubbles: true }}));
            el.dispatchEvent(new Event('blur', {{ bubbles: true }}));
            return 'FILLED';
        }} catch (e) {{
            return 'ERROR: ' + e.message;
        }}
    }})()
    """)
    return result == "FILLED"

def fill_input_typed(selector, value):
    """Fill by simulating focus, clear, then character-by-character input events."""
    escaped_val = value.replace("\\", "\\\\").replace("'", "\\'")
    result = bridge_eval(f"""
    (() => {{
        try {{
            const el = document.querySelector('{selector}');
            if (!el) return 'NOT_FOUND';
            el.focus();
            el.value = '';
            el.dispatchEvent(new Event('input', {{ bubbles: true }}));
            const val = '{escaped_val}';
            for (let i = 0; i < val.length; i++) {{
                el.value += val[i];
                el.dispatchEvent(new Event('input', {{ bubbles: true }}));
            }}
            el.dispatchEvent(new Event('change', {{ bubbles: true }}));
            el.dispatchEvent(new Event('blur', {{ bubbles: true }}));
            return 'TYPED';
        }} catch (e) {{
            return 'ERROR: ' + e.message;
        }}
    }})()
    """)
    return result == "TYPED"

def fill_field(selector, value):
    """Safely fill an input using React-compatible setter, falling back to typed simulation."""
    if fill_input_js(selector, value):
        return True
    return fill_input_typed(selector, value)

def select_dropdown_option(selector, value):
    """Select dropdown option by value or text, prioritizing exact matches."""
    escaped_val = value.replace("'", "\\'")
    result = bridge_eval(f"""
    (() => {{
        try {{
            const el = document.querySelector('{selector}');
            if (!el) return 'NOT_FOUND';
            if (!el.options) return 'NOT_A_SELECT';
            
            let found = false;
            // 1. Try exact value match
            for (let opt of el.options) {{
                if (opt.value === '{escaped_val}') {{
                    el.value = opt.value;
                    found = true;
                    break;
                }}
            }}
            
            // 2. Try exact text match (case-insensitive)
            if (!found) {{
                for (let opt of el.options) {{
                    if (opt.text.trim().toLowerCase() === '{escaped_val}'.toLowerCase()) {{
                        el.value = opt.value;
                        found = true;
                        break;
                    }}
                }}
            }}
            
            // 3. Try partial text match (case-insensitive fallback)
            if (!found) {{
                for (let opt of el.options) {{
                    if (opt.text.toLowerCase().includes('{escaped_val}'.toLowerCase())) {{
                        el.value = opt.value;
                        found = true;
                        break;
                    }}
                }}
            }}
            
            if (found) {{
                el.dispatchEvent(new Event('change', {{ bubbles: true }}));
                return 'SELECTED';
            }}
            return 'OPT_NOT_FOUND';
        }} catch (e) {{
            return 'ERROR: ' + e.message;
        }}
    }})()
    """)
    return result == "SELECTED"

def click_element(selector):
    """Click an element by CSS selector."""
    result = bridge_eval(f"""
    (() => {{
        try {{
            const el = document.querySelector('{selector}');
            if (!el) return 'NOT_FOUND';
            el.click();
            return 'CLICKED';
        }} catch (e) {{
            return 'ERROR: ' + e.message;
        }}
    }})()
    """)
    return result == "CLICKED"

def click_by_text(text, tag="button,a"):
    """Click a visible element matching text content."""
    escaped = text.replace("'", "\\'")
    result = bridge_eval(f"""
    (() => {{
        try {{
            const els = Array.from(document.querySelectorAll('{tag}'));
            const el = els.find(e => {{
                const rect = e.getBoundingClientRect();
                return rect.width > 0 && rect.height > 0 &&
                       e.textContent.trim().toLowerCase().includes('{escaped}'.toLowerCase());
            }});
            if (el) {{ el.click(); return 'CLICKED'; }}
            return 'NOT_FOUND';
        }} catch (e) {{
            return 'ERROR: ' + e.message;
        }}
    }})()
    """)
    return result == "CLICKED"

def parse_user_data(filepath, line_index):
    """Parse Shirley|Obrine|16857 clinton|San Leandro|CA|94578|12/04/1935|553-56-9291"""
    if not os.path.exists(filepath):
        raise FileNotFoundError(f"Dataset not found at {filepath}")
        
    with open(filepath, 'r', encoding='utf-8') as f:
        lines = [line.strip() for line in f.readlines() if line.strip()]
        
    if line_index < 0 or line_index >= len(lines):
        raise IndexError(f"Line index {line_index} out of bounds. Total lines: {len(lines)}")
        
    line = lines[line_index]
    parts = line.split('|')
    if len(parts) < 8:
        raise ValueError(f"Unexpected line format in dataset: {line}")
        
    dob = parts[6]  # 12/04/1935
    dob_match = re.match(r"(\d{2})/(\d{2})/(\d{4})", dob)
    if dob_match:
        dob_month, dob_day, dob_year = dob_match.groups()
    else:
        dob_month, dob_day, dob_year = "12", "04", "1935"
        
    return {
        "first_name": parts[0],
        "last_name": parts[1],
        "address": parts[2],
        "city": parts[3],
        "state": parts[4],
        "zip": parts[5],
        "dob_str": dob,
        "dob_month": dob_month,
        "dob_day": dob_day,
        "dob_year": dob_year,
        "ssn": parts[7].replace("-", "")
    }

def save_details(filename, user_info, email, phone, url, title, status="Unknown", username=None, password=None):
    """Save registration outcomes details."""
    with open(filename, "w", encoding="utf-8") as f:
        f.write("Charles Schwab Brokerage / Checking Account Details\n")
        f.write("=" * 50 + "\n")
        f.write(f"Name: {user_info['first_name']} {user_info['last_name']}\n")
        f.write(f"Address: {user_info['address']}, {user_info['city']}, {user_info['state']} {user_info['zip']}\n")
        f.write(f"DOB: {user_info['dob_str']}\n")
        f.write(f"SSN: {user_info['ssn']}\n")
        f.write(f"Email: {email}\n")
        f.write(f"Phone: {phone}\n")
        if username:
            f.write(f"Username: {username}\n")
        if password:
            f.write(f"Password: {password}\n")
        f.write("-" * 50 + "\n")
        f.write(f"Status: {status}\n")
        f.write(f"Final URL: {url}\n")
        f.write(f"Title: {title}\n")
        f.write(f"Timestamp: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")

def main():
    global BRIDGE_URL

    parser = argparse.ArgumentParser(description="Automate Charles Schwab checking and brokerage registration.")
    parser.add_argument("--line", type=int, default=1,
                        help="The 1-based line number of user data to register (default: 1)")
    parser.add_argument("--email", type=str, default=None,
                        help="Email address to register (defaults to derived email)")
    parser.add_argument("--phone", type=str, default="6692506085",
                        help="Phone number to register")
    parser.add_argument("--dataset", type=str, default="pointclickcare data.txt",
                        help="Path to the dataset file")
    parser.add_argument("--bridge", type=str, default="http://localhost:3005",
                        help="CDP bridge URL")
    args = parser.parse_args()
    BRIDGE_URL = args.bridge

    print("=" * 60)
    print("CHARLES SCHWAB ACCOUNT REGISTRATION (CDP Bridge)")
    print("=" * 60)

    # 1. Parse dataset row
    try:
        user_info = parse_user_data(args.dataset, args.line - 1)
        print("[OK] Successfully parsed dataset:")
        print(f"  Name: {user_info['first_name']} {user_info['last_name']}")
        print(f"  Address: {user_info['address']}, {user_info['city']}, {user_info['state']} {user_info['zip']}")
        print(f"  DOB: {user_info['dob_str']} (SSN: {user_info['ssn']})")
    except Exception as e:
        print(f"[ERROR] Failed to parse dataset: {e}")
        return

    if args.email:
        email = args.email
    else:
        email = f"{user_info['first_name']}{user_info['last_name']}@audioplexdesigns.com".lower().replace(" ", "").replace("-", "")
    phone = args.phone.replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
    print(f"  Email: {email}")
    print(f"  Phone: {phone}")

    username = f"{user_info['first_name']}{user_info['last_name']}{user_info['dob_year'][-2:]}".lower().replace(" ", "").replace("-", "")
    password = f"{user_info['first_name']}Pass{user_info['dob_year'][-2:]}!"

    # 2. Verify bridge connection
    status = bridge_get("/status")
    if not status or not status.get("connected"):
        print("[ERROR] Cannot connect to CDP bridge at " + BRIDGE_URL)
        print("  Make sure Chrome and the bridge are running:")
        print("    cd devtools-inspector && $env:CHROME_PORT=9223; npm run launch-chrome -- --url \"https://www.schwab.com/open-an-account\"")
        print("    Invoke-RestMethod -Method Post -Uri http://localhost:3005/connect")
        return

    print(f"[OK] Connected to CDP bridge: {BRIDGE_URL}")
    url, title = get_page_info()
    print(f"  Current page: {title}")
    print(f"  URL: {url}")

    # Prepare output path in registration_results
    script_dir = os.path.dirname(os.path.abspath(__file__))
    results_dir = os.path.join(script_dir, "registration_results")
    os.makedirs(results_dir, exist_ok=True)
    filename = os.path.join(results_dir, f"schwab_details_line_{args.line}.txt")

    # 3. Check / navigate to entry point
    if "schwab.com" not in url:
        print("\nNavigating to Schwab open account page...")
        bridge_navigate("https://www.schwab.com/open-an-account")
        time.sleep(5)
        url, title = get_page_info()

    # 4. Onboarding Automation Loop
    print("\nStarting onboarding loop...")
    for step_num in range(1, 35):
        time.sleep(3)
        url, title = get_page_info()
        body = get_body_text()
        body_lower = body.lower()
        inputs = dump_visible_inputs()
        
        print(f"\n--- Onboarding State {step_num} (URL: {url}) ---")
        
        # Save temporary progress in case of crash
        try:
            save_details(filename, user_info, email, phone, url, title, "In Progress", username, password)
        except Exception:
            pass

        # ===== STEP 1: Overview page click "Individual Checking" =====
        if "open-an-account" in url and "checking" not in url:
            print("  >> Step: Landing page. Navigating to checking options page...")
            bridge_navigate("https://www.schwab.com/open-an-account/checking")
            time.sleep(5)

        # ===== STEP 2: Checking Options page click Individual Checking =====
        elif "open-an-account/checking" in url:
            print("  >> Step: Checking Options. Clicking Individual Checking...")
            clicked = bridge_eval("""
            (() => {
                const link = Array.from(document.querySelectorAll('a'))
                    .find(a => a.href && a.href.includes('account=S3') && a.href.includes('registrationType=Individual') && a.offsetWidth > 0 && a.offsetHeight > 0);
                if (link) {
                    link.click();
                    return 'CLICKED_S3_INDIVIDUAL';
                }
                return 'NOT_FOUND';
            })()
            """)
            print(f"  Click result: {clicked}")
            time.sleep(5)

        # ===== STEP 3: Welcome Get Started page =====
        elif "retail/welcome" in url or "open your individual checking account" in body_lower:
            print("  >> Step: Welcome page. Clicking 'Get started'...")
            if click_by_text("Get started", "button"):
                print("  Clicked Get started button")
            time.sleep(5)

        # ===== STEP 4: Personal Information Form Filling =====
        elif "retail/personal-info" in url or "who's opening this checking" in body_lower:
            print("  >> Step: Personal Information form...")
            fill_field('#firstname-input', user_info["first_name"])
            fill_field('#lastname-input', user_info["last_name"])
            click_element('#isdomesticyes-radio-id')
            fill_field('#datepicker-input', user_info["dob_str"])
            fill_field('#social-security-number-input', user_info["ssn"])
            fill_field('#email-input', email)
            fill_field('#phonenumber-input', phone)
            
            time.sleep(2)
            if click_by_text("Continue", "button"):
                print("  Clicked Continue button")
            time.sleep(5)

        # ===== STEP 5: OTP Method Selection =====
        elif "otp/targets" in url or "Which contact method do you prefer" in body:
            print("  >> Step: Selecting OTP verification method (Email)...")
            # Select Email option (#div1)
            clicked_email = bridge_eval("""
            (() => {
                const el = document.getElementById('div1');
                if (el) {
                    el.click();
                    return 'CLICKED_EMAIL_OPTION';
                }
                return 'NOT_FOUND';
            })()
            """)
            print(f"  Selected Email Option: {clicked_email}")
            time.sleep(2)
            
            # Click Continue (#btnContinue)
            clicked_cont = bridge_eval("""
            (() => {
                const btn = document.getElementById('btnContinue');
                if (btn) {
                    btn.click();
                    return 'CLICKED_CONTINUE';
                }
                return 'NOT_FOUND';
            })()
            """)
            print(f"  Clicked Continue: {clicked_cont}")
            time.sleep(5)

        # ===== STEP 6: Generic form field handler =====
        else:
            print("  [INFO] Checking visible elements dynamically...")
            filled_any = False
            
            # Look for address confirmation modals or USPS suggestions
            has_suggested_address = bridge_eval("!!(document.querySelector('.address-suggestion') || document.body.innerText.includes('Suggested Address'))")
            if has_suggested_address:
                print("    [Modal] Address suggestion detected. Confirming Suggested address...")
                bridge_eval("(() => { const el = document.getElementById('suggested-address') || Array.from(document.querySelectorAll('input, label, button')).find(el => el.innerText && el.innerText.includes('Suggested')); if(el) el.click(); })()")
                time.sleep(1)
                if click_by_text("Confirm", "button") or click_by_text("Continue", "button"):
                    print("    [Modal] Confirmed address selection")
                    filled_any = True
                    time.sleep(2)

            # Check dynamic inputs
            for inp in inputs:
                iid = inp["id"]
                iname = inp["name"]
                combined = f"{iid} {iname} {inp.get('placeholder', '')} {inp.get('text', '')}".lower()
                selector = f'[id="{iid}"]' if iid else f"[name='{iname}']" if iname else None
                
                if not selector:
                    continue
                
                # Check options and fill
                if "occupation" in combined or "employment" in combined:
                    if inp["tag"] == "select":
                        print("    Selecting Occupation: Retired")
                        select_dropdown_option(selector, "Retired")
                        filled_any = True
                elif "income" in combined:
                    if inp["tag"] == "select":
                        print("    Selecting Income option...")
                        bridge_eval(f"(() => {{ const el = document.querySelector('{selector}'); if(el && el.options.length > 1) {{ el.selectedIndex = Math.min(2, el.options.length - 1); el.dispatchEvent(new Event('change', {{ bubbles: true }})); }} }})()")
                        filled_any = True
                elif "networth" in combined or "net-worth" in combined:
                    if inp["tag"] == "select":
                        print("    Selecting Net Worth option...")
                        bridge_eval(f"(() => {{ const el = document.querySelector('{selector}'); if(el && el.options.length > 1) {{ el.selectedIndex = Math.min(2, el.options.length - 1); el.dispatchEvent(new Event('change', {{ bubbles: true }})); }} }})()")
                        filled_any = True
                elif "username" in combined or "userid" in combined or "user-id" in combined:
                    print(f"    Auto-filling Username: {username}")
                    fill_field(selector, username)
                    filled_any = True
                elif "password" in combined:
                    print(f"    Auto-filling Password: {password}")
                    fill_field(selector, password)
                    filled_any = True
                elif "security" in combined or "challenge" in combined or "question" in combined:
                    if inp["tag"] == "select":
                        print("    Auto-selecting first security question")
                        bridge_eval(f"(() => {{ const el = document.querySelector('{selector}'); if(el && el.options.length > 1) {{ el.selectedIndex = 1; el.dispatchEvent(new Event('change', {{ bubbles: true }})); }} }})()")
                        filled_any = True
                elif "answer" in combined:
                    ans = "Hayward"
                    print(f"    Auto-filling security answer: {ans}")
                    fill_field(selector, ans)
                    filled_any = True
                elif inp["tag"] == "input" and inp["type"] == "radio" and iid.lower().endswith("no"):
                    print(f"    Checking radio 'No': {iid}")
                    bridge_eval(f"(() => {{ const el = document.getElementById('{iid}'); if(el && !el.checked) el.click(); }})()")
                    filled_any = True

            # Check dynamic agreement checkboxes
            checked_cbs = False
            for inp in inputs:
                if inp["tag"] == "input" and inp["type"] == "checkbox":
                    iid = inp["id"]
                    iname = inp["name"]
                    combined = f"{iid} {iname} {inp.get('placeholder', '')} {inp.get('text', '')}".lower()
                    if any(k in combined for k in ["agree", "accept", "terms", "consent", "disclosure", "ack"]):
                        is_checked = bridge_eval(f"!!(document.getElementById('{iid}') || document.querySelector('[name=\"{iname}\"]'))?.checked")
                        if not is_checked:
                            print(f"    Checking agreement checkbox: {iid or iname}")
                            selector = f'[id="{iid}"]' if iid else f"[name='{iname}']"
                            bridge_eval(f"(() => {{ const el = document.querySelector('{selector}'); if(el && !el.checked) el.click(); }})()")
                            checked_cbs = True

            # Attempt submission
            continued = False
            for btn_text in ["Continue", "Next", "Confirm", "Submit", "Agree and submit", "Agree and Open"]:
                if click_by_text(btn_text, "button,a"):
                    print(f"    Clicked '{btn_text}'")
                    continued = True
                    break
            
            if not continued and not filled_any and not checked_cbs:
                print("  [!] No action made. Human solver or code entry required.")
                time.sleep(5)

        # ===== STEP 7: Exit outcomes and thresholds =====
        curr_url_lower = url.lower()
        if "otp/code" in curr_url_lower or "Enter access code" in body:
            print("\n[OUTCOME] [PENDING] Reached OTP code entry screen. Access code sent to email.")
            save_details(filename, user_info, email, phone, url, title, "Pending OTP / Verification", username, password)
            break
        elif any(k in curr_url_lower for k in ["otp", "verify", "verification", "2fa", "security-code"]):
            print("\n[OUTCOME] [PENDING] Reached verification check screen.")
            save_details(filename, user_info, email, phone, url, title, "Pending OTP / Verification", username, password)
            break
        elif any(k in curr_url_lower for k in ["confirm-identity", "kba", "identity-verification"]):
            print("\n[OUTCOME] [PENDING] Reached identity verification (KBA/ID Scan).")
            save_details(filename, user_info, email, phone, url, title, "Pending Identity Verification / KBA", username, password)
            break
        elif any(k in curr_url_lower for k in ["confirmation", "success", "thank-you", "congratulations"]):
            print("\n[OUTCOME] [OK] Registration complete / Application submitted successfully!")
            save_details(filename, user_info, email, phone, url, title, "Submitted / Approved", username, password)
            break
        elif any(k in curr_url_lower for k in ["declined", "denied", "reject"]):
            print("\n[OUTCOME] Registration declined.")
            save_details(filename, user_info, email, phone, url, title, "Declined", username, password)
            break
        elif any(k in curr_url_lower for k in ["pending", "review"]):
            print("\n[OUTCOME] Registration pending review.")
            save_details(filename, user_info, email, phone, url, title, "Pending Review", username, password)
            break
    else:
        print("\n[!] Reached max loop iterations. Saving state.")
        save_details(filename, user_info, email, phone, url, title, "Incomplete / Max Steps Reached", username, password)

    print(f"\n[OK] Details saved to: {os.path.abspath(filename)}")
    print("Chrome remains open for manual code entry / next steps.")

if __name__ == "__main__":
    main()
