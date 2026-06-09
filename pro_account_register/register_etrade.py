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

def bridge_eval(expression):
    """Execute JavaScript in the page via the CDP bridge."""
    url = f"{BRIDGE_URL}/eval"
    data = json.dumps({"expression": expression}).encode("utf-8")
    try:
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            return result.get("result")
    except Exception as e:
        print(f"  [!] Bridge eval failed: {e}")
        return None

def bridge_navigate(url):
    """Navigate the page to a URL via JS."""
    bridge_eval(f"window.location.href = '{url}'")

def get_page_info():
    """Get current page URL and title."""
    info = bridge_get("/page")
    if info:
        return info.get("url", ""), info.get("title", "")
    return "", ""

def get_body_text():
    """Get visible page text."""
    raw = bridge_eval("document.body.innerText.substring(0, 3000)")
    return raw or ""

def dump_visible_inputs():
    """Get all visible form inputs from the page."""
    raw = bridge_eval("""
    JSON.stringify(Array.from(document.querySelectorAll('input, select, textarea, button, a, [role="button"]'))
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
            text: (el.textContent || '').trim().substring(0, 60)
        })))
    """)
    if raw:
        return json.loads(raw)
    return []

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
    """Parse a specific line of dataset."""
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
    """Save E*TRADE registration details outcome."""
    with open(filename, "w", encoding="utf-8") as f:
        f.write("E*TRADE Checking/Savings & Brokerage Account Details\n")
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

    parser = argparse.ArgumentParser(description="Automate E*TRADE Brokerage and Checking/Savings registration.")
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
    print("E*TRADE ACCOUNT REGISTRATION (CDP Bridge)")
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
        print("    cd devtools-inspector && npm run launch-chrome -- --url https://express.etrade.com/etx/rtao/ma/account-category")
        print("    cd devtools-inspector && npm start")
        return

    print(f"[OK] Connected to CDP bridge: {BRIDGE_URL}")
    url, title = get_page_info()
    print(f"  Current page: {title}")
    print(f"  URL: {url}")

    # Prepare output path in registration_results
    script_dir = os.path.dirname(os.path.abspath(__file__))
    results_dir = os.path.join(script_dir, "registration_results")
    os.makedirs(results_dir, exist_ok=True)
    filename = os.path.join(results_dir, f"etrade_details_line_{args.line}.txt")

    # 3. Check / navigate to entry point
    if "/account-category" not in url and "/account-types" not in url and "/login" not in url and "/name-contact" not in url:
        print("\nNavigating to E*TRADE Account Category page...")
        bridge_navigate("https://express.etrade.com/etx/rtao/ma/account-category")
        time.sleep(5)

    # 4. Onboarding Automation Loop
    print("\nStarting onboarding loop...")
    for step_num in range(1, 30):
        time.sleep(3)
        url, title = get_page_info()
        body = get_body_text()
        
        print(f"\n--- Checking Onboarding State {step_num} (URL: {url}) ---")
        
        # Save temporary progress in case of crash
        try:
            save_details(filename, user_info, email, phone, url, title, "In Progress", username, password)
        except Exception:
            pass

        body_lower = body.lower()
        inputs = dump_visible_inputs()
        
        # ===== STEP 1: Account Category =====
        if "/account-category" in url:
            print("  >> Step: Account Category Select")
            
            # Select Brokerage
            bridge_eval("(() => { const el = document.getElementById('brokerage'); if(el && !el.checked) el.click(); })()")
            # Select Bank (Savings, checking, CD)
            bridge_eval("(() => { const el = document.getElementById('bank'); if(el && !el.checked) el.click(); })()")
            
            time.sleep(1)
            clicked = click_by_text("Continue", "button")
            print(f"  Clicked Continue: {clicked}")
            
        # ===== STEP 2: Account Types =====
        elif "/account-types" in url:
            print("  >> Step: Choose Brokerage Account Type")
            
            # Select Individual
            bridge_eval("(() => { const el = document.getElementById('INDIVIDUAL'); if(el && !el.checked) el.click(); })()")
            
            time.sleep(1)
            clicked = click_by_text("Continue", "button")
            print(f"  Clicked Continue: {clicked}")
            
        # ===== STEP 3: Existing Customer Login Check =====
        elif "/login" in url:
            print("  >> Step: Existing Customer Check")
            
            # Select No
            bridge_eval("(() => { const el = document.getElementById('isExistingCustomerNo'); if(el && !el.checked) el.click(); })()")
            
            time.sleep(1)
            clicked = click_by_text("Continue", "button")
            print(f"  Clicked Continue: {clicked}")
            
        # ===== STEP 4: Personal Contact Info =====
        elif "/name-contact" in url:
            print("  >> Step: Contact Information Form")
            
            # Fill inputs
            fill_field("#firstName", user_info["first_name"])
            fill_field("#lastName", user_info["last_name"])
            fill_field("#phoneNumber", phone)
            fill_field("#email", email)
            
            # Select mobile phone type
            select_dropdown_option("select[name='phoneType']", "Mobile")
            
            time.sleep(1)
            clicked = click_by_text("Continue", "button")
            print(f"  Clicked Continue: {clicked}")

        # ===== DYNAMIC OTHERS =====
        else:
            print("  [INFO] Checking visible inputs dynamically...")
            filled_any = False
            
            # Check for address verification modal first
            has_address_modal = bridge_eval("!!document.getElementById('USPS_RECOMMENDED')")
            if has_address_modal:
                print("    [Modal] Address confirmation modal detected - selecting USPS Recommended...")
                bridge_eval("(() => { const el = document.getElementById('USPS_RECOMMENDED'); if(el) el.click(); })()")
                time.sleep(1)
                if click_by_text("Confirm", "button"):
                    print("    [Modal] Clicked Confirm button")
                    filled_any = True
                    time.sleep(2)
            
            # Check for custom multiselect toggle button on regulatory2
            has_multiselect = bridge_eval("!!document.querySelector('.multiselect-toggle')")
            if has_multiselect and not filled_any:
                btn_text = bridge_eval("document.querySelector('.multiselect-toggle').innerText")
                if btn_text and "select" in btn_text.lower():
                    print("    [Multiselect] Custom multiselect detected - selecting 'Retirement savings'...")
                    bridge_eval("document.querySelector('.multiselect-toggle').click();")
                    time.sleep(1)
                    clicked_opt = bridge_eval("(() => { const el = document.getElementById('102') || Array.from(document.querySelectorAll('li')).find(li => li.innerText.includes('Retirement')); if(el) { el.click(); return 'CLICKED'; } return 'NOT_FOUND'; })()")
                    print(f"    [Multiselect] Option clicked: {clicked_opt}")
                    filled_any = True
                    time.sleep(1)

            if not filled_any:
                # Helper dynamic fill mapping
                for inp in inputs:
                    iid = inp["id"]
                    iname = inp["name"]
                    combined = f"{iid} {iname} {inp.get('placeholder', '')}".lower()
                    selector = f'[id="{iid}"]' if iid else f"[name='{iname}']" if iname else None
                    
                    if not selector:
                        continue
                    
                    # Check fields and fill
                    if "address1" in combined or iid == "residentialAddress1":
                        print(f"    Auto-filling Address Line 1: {user_info['address']}")
                        fill_field(selector, user_info["address"])
                        filled_any = True
                    elif "address2" in combined or iid == "residentialAddress2":
                        # Explicitly keep address 2 empty unless it is a new fill
                        pass
                    elif "street" in combined or "address" in combined:
                        print(f"    Auto-filling Address: {user_info['address']}")
                        fill_field(selector, user_info["address"])
                        filled_any = True
                    elif "city" in combined:
                        print(f"    Auto-filling City: {user_info['city']}")
                        fill_field(selector, user_info["city"])
                        filled_any = True
                    elif "state" in combined and inp["tag"] == "select":
                        print(f"    Auto-selecting State: {user_info['state']}")
                        select_dropdown_option(selector, user_info["state"])
                        filled_any = True
                    elif "zip" in combined or "postal" in combined:
                        print(f"    Auto-filling Zip Code: {user_info['zip']}")
                        fill_field(selector, user_info["zip"])
                        filled_any = True
                    elif any(k in combined for k in ["ssn", "social", "taxid"]):
                        print(f"    Auto-filling SSN: {user_info['ssn']}")
                        fill_field(selector, user_info["ssn"])
                        filled_any = True
                    elif "dob" in combined or "birth" in combined:
                        print(f"    Auto-filling DOB: {user_info['dob_str']}")
                        val = user_info["dob_str"].replace("/", "")
                        fill_field(selector, val)
                        filled_any = True
                    elif "citizenship" in combined and inp["tag"] == "select":
                        print("    Auto-selecting Citizenship: US Citizen")
                        select_dropdown_option(selector, "US Citizen")
                        filled_any = True
                    elif "occupation" in combined and inp["tag"] == "select":
                        print("    Auto-selecting Occupation: Retired")
                        select_dropdown_option(selector, "Retired")
                        filled_any = True
                    elif "annualincome" in combined and inp["tag"] == "select":
                        print("    Auto-selecting Annual Income: $50,001 - $100,000")
                        select_dropdown_option(selector, "$50,001 - $100,000")
                        filled_any = True
                    elif "liquidnetworth" in combined and inp["tag"] == "select":
                        print("    Auto-selecting Liquid Net Worth: $50,001 - $100,000")
                        select_dropdown_option(selector, "$50,001 - $100,000")
                        filled_any = True
                    elif "totalnetworth" in combined and inp["tag"] == "select":
                        print("    Auto-selecting Total Net Worth: $100,001 - $150,000")
                        select_dropdown_option(selector, "$100,001 - $150,000")
                        filled_any = True
                    elif "investmentexperience" in combined and inp["tag"] == "select":
                        print("    Auto-selecting Investment Experience: Good")
                        select_dropdown_option(selector, "Good")
                        filled_any = True
                    elif "maritalstatus" in combined and inp["tag"] == "select":
                        print("    Auto-selecting Marital Status: Single")
                        select_dropdown_option(selector, "Single")
                        filled_any = True
                    elif "purposeandexpecteduse" in combined and inp["tag"] == "select":
                        print("    Auto-selecting Account Purpose: Wealth Accumulation/ Investment")
                        select_dropdown_option(selector, "Wealth Accumulation/ Investment")
                        filled_any = True
                    elif "username" in combined or "userid" in combined or "user-id" in combined:
                        uname = f"{user_info['first_name']}{user_info['last_name']}{user_info['dob_year'][-2:]}".lower().replace(" ", "").replace("-", "")
                        print(f"    Auto-filling Username: {uname}")
                        fill_field(selector, uname)
                        filled_any = True
                    elif "password" in combined:
                        passwd = f"{user_info['first_name']}Pass{user_info['dob_year'][-2:]}!"
                        print(f"    Auto-filling Password: {passwd}")
                        fill_field(selector, passwd)
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
                        print(f"    Auto-checking radio button 'No': {iid}")
                        bridge_eval(f"(() => {{ const el = document.getElementById('{iid}'); if(el && !el.checked) el.click(); }})()")
                        filled_any = True
                
                # Handle standard compliance checkboxes
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
                
                # Click Continue, Submit, or Confirm if available
                time.sleep(1)
                continued = False
                for btn_text in ["Continue", "Next", "Confirm", "Submit", "Agree and submit", "Done"]:
                    if click_by_text(btn_text, "button,a"):
                        print(f"    Clicked '{btn_text}'")
                        continued = True
                        break
                        
                if not continued and not filled_any and not checked_cbs:
                    print("  [!] Pausing. Human intervention or OTP may be required. Solvers should run manually in Chrome window.")
                    time.sleep(5)
                
        # Capture final outcome
        if "confirm-identity" in url.lower():
            print("\n[OUTCOME] [PENDING] Reached Mobile Identity Verification (QR code scan required).")
            save_details(filename, user_info, email, phone, url, title, "Pending Mobile Verification / QR Code Scan", username, password)
            break
        elif "confirmation" in url.lower() or "success" in url.lower() or "thank-you" in url.lower():
            print("\n[OUTCOME] [OK] Registration complete / Reached confirmation screen!")
            save_details(filename, user_info, email, phone, url, title, "Approved / Submitted", username, password)
            break
        elif "declined" in url.lower() or "denied" in url.lower():
            print("\n[OUTCOME] Registration declined.")
            save_details(filename, user_info, email, phone, url, title, "Declined", username, password)
            break
        elif "pending" in url.lower() or "review" in url.lower():
            print("\n[OUTCOME] Registration pending review.")
            save_details(filename, user_info, email, phone, url, title, "Pending Review", username, password)
            break
    else:
        print("\n[!] Reached max loop checks. Saving state.")
        save_details(filename, user_info, email, phone, url, title, "Incomplete / Max Steps Reached", username, password)

    print(f"\n[OK] Details saved to: {os.path.abspath(filename)}")
    print("Chrome remains open for manual inspection.")

if __name__ == "__main__":
    main()
