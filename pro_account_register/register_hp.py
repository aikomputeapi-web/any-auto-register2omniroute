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
            text: (el.textContent || '').trim().substring(0, 80)
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

def save_details(filename, user_info, email, phone, url, title, status="Unknown", tier=None):
    """Save registration outcomes details."""
    with open(filename, "w", encoding="utf-8") as f:
        f.write("HP Laptop Subscription Account Registration Details\n")
        f.write("=" * 50 + "\n")
        f.write(f"Name: {user_info['first_name']} {user_info['last_name']}\n")
        f.write(f"Address: {user_info['address']}, {user_info['city']}, {user_info['state']} {user_info['zip']}\n")
        f.write(f"DOB: {user_info['dob_str']}\n")
        f.write(f"SSN: {user_info['ssn']}\n")
        f.write(f"Email: {email}\n")
        f.write(f"Phone: {phone}\n")
        if tier:
            f.write(f"Selected Subscription Tier: {tier}\n")
        f.write("-" * 50 + "\n")
        f.write(f"Status: {status}\n")
        f.write(f"Final URL: {url}\n")
        f.write(f"Title: {title}\n")
        f.write(f"Timestamp: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")

def select_highest_tier():
    """Finds all cards or elements with pricing patterns, identifies the highest price, and clicks it."""
    js_fn = """
    (() => {
        try {
            const clickables = Array.from(document.querySelectorAll('button, a, [role="button"]')).filter(el => {
                const rect = el.getBoundingClientRect();
                return rect.width > 0 && rect.height > 0;
            });

            let maxPrice = -1;
            let targetButton = null;

            for (const clickable of clickables) {
                let text = clickable.textContent || '';
                let current = clickable;
                // Walk up to 4 parents to find a price tag associated with this button
                for (let i = 0; i < 4; i++) {
                    if (!current) break;
                    text += ' ' + (current.textContent || '');
                    current = current.parentElement;
                }

                const priceMatches = text.match(/\\$\\s*(\\d+(?:\\.\\d{2})?)/g);
                if (priceMatches) {
                    for (const match of priceMatches) {
                        const val = parseFloat(match.replace('$', '').trim());
                        if (val > maxPrice) {
                            maxPrice = val;
                            targetButton = clickable;
                        }
                    }
                }
            }

            if (targetButton) {
                targetButton.focus();
                targetButton.click();
                return 'CLICKED_TIER_WITH_PRICE_$' + maxPrice;
            }
            
            // Fallback: search general cards/sections
            return 'NO_TIER_FOUND';
        } catch (e) {
            return 'ERROR: ' + e.message;
        }
    })()
    """
    return bridge_eval(js_fn)

def main():
    global BRIDGE_URL

    parser = argparse.ArgumentParser(description="Automate HP Laptop Subscription registration.")
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
    print("HP LAPTOP SUBSCRIPTION REGISTRATION")
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

    # 2. Verify bridge connection
    status = bridge_get("/status")
    if not status or not status.get("connected"):
        print("[ERROR] Cannot connect to CDP bridge at " + BRIDGE_URL)
        print("  Make sure Chrome and the bridge are running:")
        print("    cd devtools-inspector && npm run launch-chrome -- --url \"https://hplaptopsubscription.hp.com\"")
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
    filename = os.path.join(results_dir, f"hp_details_line_{args.line}.txt")

    # 3. Check / navigate to entry point
    if "hplaptopsubscription" not in url:
        print("\nNavigating to HP Laptop Subscription home page...")
        bridge_navigate("https://hplaptopsubscription.hp.com")
        time.sleep(5)
        url, title = get_page_info()

    # 4. Onboarding Automation Loop
    print("\nStarting onboarding loop...")
    selected_tier = None
    for step_num in range(1, 30):
        time.sleep(3)
        url, title = get_page_info()
        body = get_body_text()
        inputs = dump_visible_inputs()
        
        print(f"\n--- Onboarding State {step_num} (URL: {url}) ---")
        
        # Save temporary progress
        try:
            save_details(filename, user_info, email, phone, url, title, "In Progress", selected_tier)
        except Exception:
            pass

        # If we are on the landing/tiers page, find the highest tier and select it
        if "hplaptopsubscription.hp.com" in url and ("subscribe" in body.lower() or "choose" in body.lower() or not selected_tier):
            if not selected_tier:
                print("  >> Step: Selecting the highest-priced subscription tier...")
                res = select_highest_tier()
                print(f"  Selection result: {res}")
                if "CLICKED_TIER" in res:
                    selected_tier = res.split("WITH_PRICE_")[-1]
                else:
                    # Fallback to standard click by text
                    if click_by_text("Subscribe", "button,a") or click_by_text("Select", "button,a") or click_by_text("Get Started", "button,a"):
                        selected_tier = "Selected Tier"
                        print("  Clicked subscribe button fallback")
                time.sleep(5)
                continue

        # Form Filling state
        print("  [INFO] Checking visible elements dynamically...")
        filled_any = False
        
        # Check fields and fill
        for inp in inputs:
            iid = inp["id"]
            iname = inp["name"]
            combined = f"{iid} {iname} {inp.get('placeholder', '')} {inp.get('text', '')}".lower()
            selector = f'[id="{iid}"]' if iid else f"[name='{iname}']" if iname else None
            
            if not selector:
                continue
                
            if "first" in combined and "name" in combined:
                print(f"    Auto-filling First Name: {user_info['first_name']}")
                fill_field(selector, user_info["first_name"])
                filled_any = True
            elif "last" in combined and "name" in combined:
                print(f"    Auto-filling Last Name: {user_info['last_name']}")
                fill_field(selector, user_info["last_name"])
                filled_any = True
            elif "email" in combined:
                print(f"    Auto-filling Email: {email}")
                fill_field(selector, email)
                filled_any = True
            elif "phone" in combined or "mobile" in combined:
                print(f"    Auto-filling Phone: {phone}")
                fill_field(selector, phone)
                filled_any = True
            elif "address1" in combined or "address" in combined or "street" in combined:
                print(f"    Auto-filling Address: {user_info['address']}")
                fill_field(selector, user_info["address"])
                filled_any = True
            elif "city" in combined:
                print(f"    Auto-filling City: {user_info['city']}")
                fill_field(selector, user_info["city"])
                filled_any = True
            elif "state" in combined:
                if inp["tag"] == "select":
                    print(f"    Auto-selecting State: {user_info['state']}")
                    select_dropdown_option(selector, user_info["state"])
                    filled_any = True
            elif "zip" in combined or "postal" in combined:
                print(f"    Auto-filling Zip Code: {user_info['zip']}")
                fill_field(selector, user_info["zip"])
                filled_any = True
            elif "ssn" in combined or "social" in combined:
                print(f"    Auto-filling SSN: {user_info['ssn']}")
                fill_field(selector, user_info["ssn"])
                filled_any = True
            elif "dob" in combined or "birth" in combined:
                print(f"    Auto-filling DOB: {user_info['dob_str']}")
                fill_field(selector, user_info["dob_str"])
                filled_any = True

        # Check compliance / agreement checkboxes
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

        # Click next / submit buttons
        continued = False
        for btn_text in ["Continue", "Next", "Submit", "Agree", "Confirm", "Sign Up", "Create Account"]:
            if click_by_text(btn_text, "button,a"):
                print(f"    Clicked '{btn_text}' button")
                continued = True
                break

        if not continued and not filled_any and not checked_cbs:
            print("  [!] No action taken. Pausing for human intervention/OTP/Captcha solving if necessary.")
            time.sleep(5)

        # Check exit / success criteria
        curr_url_lower = url.lower()
        if any(k in curr_url_lower for k in ["confirmation", "success", "thank-you"]):
            print("\n[OUTCOME] [OK] Registration complete!")
            save_details(filename, user_info, email, phone, url, title, "Approved / Submitted", selected_tier)
            break
        elif any(k in curr_url_lower for k in ["otp", "2fa", "verify-phone"]):
            print("\n[OUTCOME] [PENDING] Reached OTP verification.")
            save_details(filename, user_info, email, phone, url, title, "Pending OTP", selected_tier)
            break
        elif any(k in curr_url_lower for k in ["captcha", "challenge"]):
            print("\n[OUTCOME] [PENDING] Reached Captcha verification.")
            save_details(filename, user_info, email, phone, url, title, "Pending Captcha", selected_tier)
            break
    else:
        print("\n[!] Reached max loop iterations. Saving state.")
        save_details(filename, user_info, email, phone, url, title, "Incomplete / Max Steps Reached", selected_tier)

    print(f"\n[OK] Details saved to: {os.path.abspath(filename)}")

if __name__ == "__main__":
    main()
