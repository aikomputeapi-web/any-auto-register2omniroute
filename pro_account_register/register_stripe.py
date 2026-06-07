"""
Stripe Account Registration Script (CDP Bridge Edition)
========================================================
Automates account creation at https://dashboard.stripe.com/register
using the devtools-inspector CDP bridge (localhost:3005) to drive a real
Chrome instance, bypassing Stripe's anti-bot protections.

Prerequisites:
    1. Launch Chrome: cd devtools-inspector && npm run launch-chrome -- --url https://dashboard.stripe.com/register
    2. Start bridge:  cd devtools-inspector && npm start
    3. Then run:      python pro_account_register/register_stripe.py

Usage:
    python pro_account_register/register_stripe.py
    python pro_account_register/register_stripe.py --profile pro_account_register/stripe_business_profile.txt
    python pro_account_register/register_stripe.py --bridge http://localhost:3005
"""
import sys
import os
import time
import re
import json
import argparse
import urllib.request
import urllib.error


BRIDGE_URL = "http://localhost:3005"


def bridge_get(path):
    """GET request to the CDP bridge API."""
    url = f"{BRIDGE_URL}{path}"
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8")
        print(f"  [!] Bridge GET {path} failed: {e.code} - {err_body}")
        return None
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
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8")
        print(f"  [!] Bridge eval failed: {e.code} - {err_body}")
        return None
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


def fill_input_js(selector, value):
    """Fill an input field using React-compatible JS."""
    escaped_val = value.replace("\\", "\\\\").replace("'", "\\'").replace("\n", "\\n")
    result = bridge_eval(f"""
    (() => {{
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
    }})()
    """)
    return result == "FILLED"


def fill_input_typed(selector, value):
    """Fill by simulating focus, clear, then character-by-character input events."""
    escaped_val = value.replace("\\", "\\\\").replace("'", "\\'")
    result = bridge_eval(f"""
    (() => {{
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
    }})()
    """)
    return result == "TYPED"


def fill_field(selector, value):
    """Safely fill an input using React-compatible setter, falling back to typed simulation."""
    if fill_input_js(selector, value):
        return True
    return fill_input_typed(selector, value)


def click_element(selector):
    """Click an element by CSS selector."""
    result = bridge_eval(f"""
    (() => {{
        const el = document.querySelector('{selector}');
        if (!el) return 'NOT_FOUND';
        el.click();
        return 'CLICKED';
    }})()
    """)
    return result == "CLICKED"


def click_by_text(text, tag="button,a"):
    """Click a visible element matching text content."""
    escaped = text.replace("'", "\\'")
    result = bridge_eval(f"""
    (() => {{
        const els = Array.from(document.querySelectorAll('{tag}'));
        const el = els.find(e => {{
            const rect = e.getBoundingClientRect();
            return rect.width > 0 && rect.height > 0 &&
                   e.textContent.trim().toLowerCase().includes('{escaped}'.toLowerCase());
        }});
        if (el) {{ el.click(); return 'CLICKED'; }}
        return 'NOT_FOUND';
    }})()
    """)
    return result == "CLICKED"


def dump_visible_inputs():
    """Get all visible form inputs from the page."""
    raw = bridge_eval("""
    JSON.stringify(Array.from(document.querySelectorAll('input, select, textarea, button[type="submit"]'))
        .filter(el => el.offsetWidth > 0 && el.offsetHeight > 0)
        .map(el => ({
            tag: el.tagName.toLowerCase(),
            id: el.id || '',
            name: el.name || '',
            type: el.type || '',
            placeholder: el.placeholder || '',
            ariaLabel: el.getAttribute('aria-label') || '',
            dataTestId: el.getAttribute('data-testid') || '',
            value: (el.value || '').substring(0, 40)
        })))
    """)
    if raw:
        return json.loads(raw)
    return []


def get_body_text():
    """Get visible page text."""
    raw = bridge_eval("document.body.innerText.substring(0, 3000)")
    return raw or ""


def parse_business_profile(filepath):
    """Parse the business profile text file into a dict."""
    if not os.path.exists(filepath):
        raise FileNotFoundError(f"Business profile not found at {filepath}")
    data = {}
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            m = re.match(r"^([A-Za-z][A-Za-z /&()]+?):\s*(.+)$", line)
            if m:
                data[m.group(1).strip()] = m.group(2).strip()
    return data


def save_details(filename, profile, email, password, status="Unknown", url="", title=""):
    """Save registration outcome."""
    with open(filename, "w", encoding="utf-8") as f:
        f.write("Stripe Account Registration Details\n")
        f.write("=" * 50 + "\n")
        f.write(f"Business: {profile.get('Legal Business Name', 'N/A')}\n")
        f.write(f"DBA: {profile.get('DBA (Doing Business As)', 'N/A')}\n")
        f.write(f"Industry: {profile.get('Industry / Category', 'N/A')}\n")
        f.write(f"Representative: {profile.get('Full Name', 'N/A')}\n")
        f.write("-" * 50 + "\n")
        f.write(f"Username (Email): {email}\n")
        f.write(f"Password: {password}\n")
        f.write("-" * 50 + "\n")
        f.write(f"Status: {status}\n")
        f.write(f"Final URL: {url}\n")
        f.write(f"Title: {title}\n")
        f.write(f"Timestamp: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")


def parse_dataset_line(filepath, line_index=None):
    """Parse a specific line of dataset or pick a random one if line_index is None."""
    if not os.path.exists(filepath):
        raise FileNotFoundError(f"Dataset not found at {filepath}")
        
    with open(filepath, 'r', encoding='utf-8') as f:
        lines = [line.strip() for line in f.readlines() if line.strip()]
        
    if not lines:
        raise ValueError(f"Dataset file is empty: {filepath}")
        
    import random
    if line_index is None:
        line_index = random.randint(0, len(lines) - 1)
        print(f"  [Dataset] Randomly selected line index {line_index + 1} (1-based) out of {len(lines)} total lines")
    elif line_index < 0 or line_index >= len(lines):
        raise IndexError(f"Line index {line_index} out of bounds. Total lines: {len(lines)}")
        
    line = lines[line_index]
    parts = line.split('|')
    if len(parts) < 8:
        raise ValueError(f"Unexpected line format in dataset: {line}")
        
    dob = parts[6]  # 12/04/1935
    
    return {
        "first_name": parts[0],
        "last_name": parts[1],
        "address": parts[2],
        "city": parts[3],
        "state": parts[4],
        "zip": parts[5],
        "dob_str": dob,
        "ssn": parts[7].replace("-", "")
    }, line_index


def generate_fallback_saas_profile():
    import random
    prefixes = ["Neuro", "Aether", "Synthetix", "Optima", "Vertex", "Kinetix", "Aura", "Quantum", "Nexus", "Cognito"]
    suffixes = ["Flow", "Forge", "Grid", "Labs", "Systems", "Mind", "Core", "Node", "Pulse", "Sphere"]
    categories = [
        "customer support automation", 
        "code generation and refactoring", 
        "automated marketing copy", 
        "video synthesis", 
        "automated spreadsheet analysis", 
        "data extraction"
    ]
    
    name = f"{random.choice(prefixes)}{random.choice(suffixes)}"
    domain = f"https://{name.lower()}.io"
    desc = f"{name} provides a cloud-based AI platform specializing in {random.choice(categories)} using advanced deep learning models. Our services are offered on monthly and annual subscription plans."
    stmt = f"{name.upper()}*SUBSCRIBE"[:22]
    short = name.upper()[:10]
    
    return {
        "business_name": f"{name} LLC",
        "dba": name,
        "website": domain,
        "description": desc,
        "statement_descriptor": stmt,
        "shortened_descriptor": short,
        "domain_research_summary": "Fallback local generation used."
    }


def check_domain_available(domain):
    import socket
    import urllib.request
    import urllib.error
    domain = domain.lower().replace("https://", "").replace("http://", "").strip("/")
    
    # 1. DNS check (fastest)
    try:
        socket.gethostbyname(domain)
        return False
    except socket.gaierror:
        pass
    except Exception:
        pass

    # 2. RDAP check
    url = f"https://rdap.org/domain/{domain}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return False
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return True
        return False
    except Exception:
        return True


def get_openrouter_key():
    import os
    # 1. Try environment variable
    if os.environ.get("OPENROUTER_API_KEY"):
        return os.environ.get("OPENROUTER_API_KEY")
        
    # 2. Try loading directly from .env file (for local run flexibility)
    try:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        for base_dir in [script_dir, os.path.dirname(script_dir)]:
            env_file = os.path.join(base_dir, ".env")
            if os.path.exists(env_file):
                with open(env_file, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line.startswith("OPENROUTER_API_KEY="):
                            val = line.split("=", 1)[1].strip()
                            if len(val) >= 2 and val[0] == val[-1] and val[0] in {"'", '"'}:
                                val = val[1:-1]
                            return val
    except Exception:
        pass

    # 3. Try config store
    try:
        from core.config_store import config_store
        key = config_store.get("OPENROUTER_API_KEY")
        if key:
            return key
    except Exception:
        pass

    # 4. Try openrouter_keys.txt
    try:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        for base_dir in [script_dir, os.path.dirname(script_dir)]:
            keys_file = os.path.join(base_dir, "openrouter_keys.txt")
            if os.path.exists(keys_file):
                with open(keys_file, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if ":" in line:
                            _, key = line.split(":", 1)
                            key = key.strip()
                            if key.startswith("sk-or-"):
                                return key
    except Exception:
        pass
    return None



def query_openrouter(prompt, model="openrouter/free"):
    import urllib.request
    import json
    key = get_openrouter_key()
    if not key:
        return None
        
    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/aikomputeapi-web/devtools-inspector",
        "X-Title": "DevTools Inspector"
    }
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}]
    }
    try:
        req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers)
        with urllib.request.urlopen(req, timeout=30) as resp:
            res = json.loads(resp.read().decode("utf-8"))
            choices = res.get("choices", [])
            if choices:
                content = choices[0]["message"]["content"]
                return content.strip() if content is not None else None
    except Exception as e:
        print(f"  [LLM] OpenRouter API query failed: {e}")
    return None


def extract_json(text):
    import json
    import re
    if not text:
        return None
    m = re.search(r"(\{.*\}|\[.*\])", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except Exception:
            pass
    try:
        return json.loads(text)
    except Exception:
        pass
    return None


def generate_ai_saas_profile():
    import os
    import json
    import urllib.request
    import urllib.error
    
    # 1. Attempt OpenRouter pipeline
    or_key = get_openrouter_key()
    if or_key:
        print("  [LLM] Using OpenRouter to generate business names and research domains...")
        prompt_candidates = """
        Propose a JSON array containing 5 unique, realistic, brand-new AI SaaS startup company names and matching domain names (.com, .io, or .ai) that don't already exist.
        Choose modern, creative names in the AI space.
        Respond ONLY with the JSON array, no conversational text. Example format:
        [
          {"name": "CognitoFlow", "domain": "cognitoflow.io"},
          {"name": "AetherForge", "domain": "aetherforge.ai"}
        ]
        """
        response = query_openrouter(prompt_candidates)
        candidates = extract_json(response)
        if candidates and isinstance(candidates, list):
            selected_candidate = None
            for cand in candidates:
                name = cand.get("name")
                domain = cand.get("domain")
                if not name or not domain:
                    continue
                print(f"  [LLM] Researching availability for '{domain}'...")
                if check_domain_available(domain):
                    print(f"    >> '{domain}' is available! Selecting it.")
                    selected_candidate = cand
                    break
                else:
                    print(f"    >> '{domain}' is already registered/taken.")
            
            if selected_candidate:
                name = selected_candidate["name"]
                domain = selected_candidate["domain"]
                prompt_details = f"""
                Write complete business details for the AI SaaS company "{name}" with website "https://{domain}".
                The business specializes in customer support automation or software engineering tooling using advanced AI.
                
                Respond ONLY with a valid JSON object matching this structure:
                {{
                  "business_name": "{name} LLC",
                  "dba": "{name}",
                  "website": "https://{domain}",
                  "description": "Provide a detailed 2-3 sentence product description of what this AI SaaS does.",
                  "statement_descriptor": "STATEMENT_DESCRIPTOR (max 22 characters, e.g. '{name.upper()[:10]}*SUBSCRIBE')",
                  "shortened_descriptor": "SHORTNAME (max 10 characters, e.g. '{name.upper()[:10]}')",
                  "domain_research_summary": "Domain is available according to DNS and RDAP checks."
                }}
                """
                response_details = query_openrouter(prompt_details)
                details = extract_json(response_details)
                if details and "business_name" in details:
                    return details

    # 2. Attempt Gemini API (original implementation) as fallback/backup
    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        try:
            from core.config_store import config_store
            api_key = config_store.get("GOOGLE_API_KEY")
        except Exception:
            pass
            
    if api_key:
        print("  [LLM] Attempting Gemini API fallback...")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={api_key}"
        prompt = """
        Generate unique business details for a brand new, non-existent AI SaaS (Software as a Service) startup.
        The details must be fully realistic for a real business.
        
        Requirements:
        1. Propose a unique business name that does not exist yet (e.g. something creative and modern in the AI space).
        2. Propose a matching domain name (.com, .io, or .ai).
        3. Research/verify if this domain is available or if the name is already in use by another company. Use your search tool to check if it's taken.
        4. Provide a detailed 2-3 sentence product description of what the AI SaaS does.
        5. Provide a statement descriptor (max 22 characters, e.g. "BRANDNAME*SUBSCRIBE").
        6. Provide a shortened descriptor (max 10 characters, e.g. "BRANDNAME").
        
        Respond ONLY with a valid JSON object matching this structure:
        {
          "business_name": "Proposed Name LLC",
          "dba": "Proposed Name",
          "website": "https://proposeddomain.com",
          "description": "Product description...",
          "statement_descriptor": "STATEMENT_DESCRIPTOR",
          "shortened_descriptor": "SHORTNAME",
          "domain_research_summary": "Domain is available because search for it returned..."
        }
        """
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "tools": [{"google_search": {}}],
            "generationConfig": {"responseMimeType": "application/json"}
        }
        headers = {"Content-Type": "application/json"}
        try:
            req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers)
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw_response = json.loads(resp.read().decode("utf-8"))
                candidates = raw_response.get("candidates", [])
                if candidates:
                    text_content = candidates[0]["content"]["parts"][0]["text"].strip()
                    return json.loads(text_content)
        except Exception as e:
            print(f"  [LLM] Gemini API attempt failed: {e}")
            
    print("  [LLM] Falling back to rule-based random AI SaaS generation...")
    return generate_fallback_saas_profile()


def main():
    global BRIDGE_URL

    parser = argparse.ArgumentParser(description="Automate Stripe Account Registration via CDP Bridge.")
    parser.add_argument("--profile", type=str,
                        default="pro_account_register/stripe_business_profile.txt",
                        help="Path to the business profile text file")
    parser.add_argument("--bridge", type=str, default="http://localhost:3005",
                        help="CDP bridge URL (default: http://localhost:3005)")
    parser.add_argument("--dataset", type=str, default="pointclickcare data.txt",
                        help="Path to the user dataset file (default: pointclickcare data.txt)")
    parser.add_argument("--line", type=int, default=None,
                        help="The 1-based line number of user data to use. If omitted, a random line is selected.")
    args = parser.parse_args()
    BRIDGE_URL = args.bridge

    print("=" * 60)
    print("STRIPE ACCOUNT REGISTRATION (CDP Bridge)")
    print("=" * 60)

    # 1. Parse business profile and representative details
    try:
        profile = parse_business_profile(args.profile)
        print(f"\n[OK] Parsed business profile:")
        print(f"  Business: {profile.get('Legal Business Name', 'N/A')}")
        print(f"  Industry: {profile.get('Industry / Category', 'N/A')}")
        print(f"  Email: {profile.get('Email', 'N/A')}")
        
        # Parse and override with representative/owner dataset details
        line_idx = args.line - 1 if args.line is not None else None
        user_info, selected_line = parse_dataset_line(args.dataset, line_idx)
        print(f"  [Dataset] Successfully parsed representative details (Row {selected_line + 1}):")
        print(f"    Name: {user_info['first_name']} {user_info['last_name']}")
        print(f"    Address: {user_info['address']}, {user_info['city']}, {user_info['state']} {user_info['zip']}")
        print(f"    DOB: {user_info['dob_str']} (SSN: {user_info['ssn']})")
        
        # Override profile keys
        profile["Full Name"] = f"{user_info['first_name']} {user_info['last_name']}"
        profile["Representative First Name"] = user_info["first_name"]
        profile["Representative Last Name"] = user_info["last_name"]
        profile["Date of Birth"] = user_info["dob_str"]
        profile["SSN"] = user_info["ssn"]
        profile["Representative Address"] = user_info["address"]
        profile["Representative City"] = user_info["city"]
        profile["Representative State"] = user_info["state"]
        profile["Representative Zip"] = user_info["zip"]
        
        print(f"  Representative: {profile.get('Full Name', 'N/A')}")

        # Generate and override business details
        print("\n[INFO] Generating unique AI SaaS business details via LLM...")
        biz_info = generate_ai_saas_profile()
        print(f"  [LLM] Generated Business: {biz_info['business_name']}")
        print(f"    DBA: {biz_info['dba']}")
        print(f"    Website: {biz_info['website']}")
        print(f"    Descriptor: {biz_info['statement_descriptor']}")
        print(f"    Shortened: {biz_info['shortened_descriptor']}")
        print(f"    Research Summary: {biz_info.get('domain_research_summary', 'N/A')}")
        
        # Override profile keys with generated business details
        profile["Legal Business Name"] = biz_info["business_name"]
        profile["DBA (Doing Business As)"] = biz_info["dba"]
        profile["Business Website"] = biz_info["website"]
        profile["Product Description"] = biz_info["description"]
        profile["Statement Descriptor"] = biz_info["statement_descriptor"]
        profile["Shortened Descriptor"] = biz_info["shortened_descriptor"]
    except Exception as e:
        print(f"[ERROR] {e}")
        return

    # 2. Verify bridge connection
    status = bridge_get("/status")
    if not status or not status.get("connected"):
        print("[ERROR] Cannot connect to CDP bridge at " + BRIDGE_URL)
        print("  Make sure Chrome and the bridge are running:")
        print("    cd devtools-inspector && npm run launch-chrome -- --url https://dashboard.stripe.com/register")
        print("    cd devtools-inspector && npm start")
        return

    print(f"[OK] Connected to CDP bridge: {BRIDGE_URL}")
    url, title = get_page_info()
    print(f"  Current page: {title}")
    print(f"  URL: {url}")

    full_name = profile.get("Full Name", "")
    password = profile.get("Password", "")
    script_dir = os.path.dirname(os.path.abspath(__file__))
    filename = os.path.join(script_dir, "stripe_registration_details.txt")

    # Compute email as firstname+lastname@audioplexdesigns.com
    names = full_name.lower().split()
    if len(names) >= 2:
        email = f"{names[0]}{names[-1]}@audioplexdesigns.com"
    else:
        email = f"{full_name.lower()}@audioplexdesigns.com"
    email = email.replace(" ", "").replace("-", "")

    if not email or not password or not full_name:
        print("[ERROR] Missing Email, Password, or Full Name in profile.")
        return

    # 3. Navigate to registration if not already there
    if "/register" not in url and "/welcome" not in url and "/setup" not in url:
        print("\nNavigating to Stripe registration...")
        bridge_eval("window.location.href = 'https://dashboard.stripe.com/register'")
        time.sleep(5)

    url, title = get_page_info()
    print(f"\nPage: {title}")

    # 4. Check what inputs are visible
    inputs = dump_visible_inputs()
    print(f"Visible inputs: {len(inputs)}")
    for inp in inputs:
        print(f"  <{inp['tag']}> id='{inp['id']}' name='{inp['name']}' type='{inp['type']}' dt='{inp.get('dataTestId','')}'")

    # ===== STEP 1: Fill Registration Form =====
    print("\n--- STEP 1: Fill Registration Form ---")

    # Email
    print(f"  Filling email: {email}")
    fill_field("#register-email-input", email)

    time.sleep(0.5)

    # Full Name
    print(f"  Filling name: {full_name}")
    fill_field("#register-name-input", full_name)

    time.sleep(0.5)

    # Country — check current value
    country_text = bridge_eval("""
    (() => {
        // Check for combobox button
        const btn = document.querySelector('button[aria-label="Select country"]');
        if (btn) return btn.textContent.trim();
        // Check for data-testid
        const dt = document.querySelector('[data-testid="register-country-select"]');
        if (dt) return dt.textContent.trim();
        // Check for any country-related element
        const labels = Array.from(document.querySelectorAll('label'));
        const countryLabel = labels.find(l => l.textContent.includes('Country'));
        if (countryLabel) {
            const parent = countryLabel.closest('.FormField') || countryLabel.parentElement;
            if (parent) return parent.textContent.trim();
        }
        return 'NOT_FOUND';
    })()
    """)
    print(f"  Country: {country_text}")

    time.sleep(0.5)

    # Password
    print(f"  Filling password: {'*' * len(password)}")
    fill_field("#register-password-input-with-description", password)

    time.sleep(1)

    # Verify fields are filled
    verification = bridge_eval("""
    JSON.stringify({
        email: document.querySelector('#register-email-input')?.value || '',
        name: document.querySelector('#register-name-input')?.value || '',
        password: document.querySelector('#register-password-input-with-description')?.value?.length || 0
    })
    """)
    print(f"  Verification: {verification}")

    # ===== STEP 2: Submit =====
    print("\n--- STEP 2: Submit Registration ---")
    print("[!] NOTE: hCaptcha may appear — solve it manually in the browser window.")

    clicked = click_element('button[data-testid="register-submit-button"]')
    if not clicked:
        clicked = click_by_text("Create account")
    print(f"  Submit clicked: {clicked}")

    # Wait for CAPTCHA or page transition
    print("\nWaiting for page transition...")
    for wait_i in range(36):  # Up to 3 minutes
        time.sleep(5)
        new_url, new_title = get_page_info()
        body = get_body_text().lower()

        # Check for CAPTCHA
        has_captcha = bridge_eval("""
        (() => {
            const iframes = document.querySelectorAll('iframe');
            for (const f of iframes) {
                if (f.src && (f.src.includes('hcaptcha') || f.src.includes('recaptcha'))) {
                    const rect = f.getBoundingClientRect();
                    const style = window.getComputedStyle(f);
                    const isVisible = rect.width > 50 && rect.height > 50 && 
                                      style.display !== 'none' && style.visibility !== 'hidden';
                    if (isVisible) return true;
                }
            }
            return false;
        })()
        """)

        if has_captcha:
            if wait_i == 0:
                print("\n  [!] CAPTCHA DETECTED — Please solve it in the browser window!")
            print(f"  Waiting for CAPTCHA solve... ({(wait_i+1)*5}s)")
            continue

        if "/register" not in new_url:
            print(f"\n  Page transitioned to: {new_url}")
            print(f"  Title: {new_title}")
            break

        # Check for email verification
        if "verify" in body or ("email" in body and "check" in body):
            print(f"\n  [!] EMAIL VERIFICATION REQUIRED — Check inbox for {email}")
            print(f"  Waiting... ({(wait_i+1)*5}s)")
            continue

        print(f"  Still on registration page... ({(wait_i+1)*5}s)")
    else:
        print("  [!] Timeout waiting for page transition.")

    time.sleep(3)
    url, title = get_page_info()
    print(f"\nCurrent: {title} ({url})")

    # ===== STEP 3: Business Onboarding =====
    print("\n" + "=" * 50)
    print("BUSINESS ONBOARDING FLOW")
    print("=" * 50)

    for step_num in range(1, 35):
        time.sleep(4)
        url, title = get_page_info()
        body = get_body_text()

        print(f"\n--- Onboarding Step {step_num} ---")
        print(f"  URL: {url}")
        print(f"  Title: {title}")

        inputs = dump_visible_inputs()
        print(f"  Visible inputs: {len(inputs)}")
        for inp in inputs:
            print(f"    <{inp['tag']}> id='{inp['id']}' name='{inp['name']}' "
                  f"type='{inp['type']}' ph='{inp['placeholder']}' "
                  f"dt='{inp.get('dataTestId','')}'")

        body_lower = body.lower()

        # --- Auto-fill known fields ---
        filled_any = False

        for inp in inputs:
            iid = inp["id"]
            iname = inp["name"]
            idt = inp.get("dataTestId", "")
            iph = inp.get("placeholder", "")
            ial = inp.get("ariaLabel", "")
            combined = f"{iid} {iname} {idt} {ial} {iph}".lower()
            selector = f'[id="{iid}"]' if iid else f"[name='{iname}']" if iname else None

            if not selector:
                continue

            # Business name
            if any(k in combined for k in ["business_name", "company_name", "legal_name",
                                            "business-name", "company-name", "legal-name"]):
                val = profile.get("Legal Business Name", "")
                if val:
                    print(f"    >> Filling business name: {val}")
                    fill_field(selector, val)
                    filled_any = True

            # DBA
            elif any(k in combined for k in ["doing_business", "dba", "trade_name"]):
                val = profile.get("DBA (Doing Business As)", "")
                if val:
                    print(f"    >> Filling DBA: {val}")
                    fill_field(selector, val)
                    filled_any = True

            # EIN / Tax ID
            elif any(k in combined for k in ["ein", "tax_id", "tax-id", "employer_id",
                                              "tax_identification"]):
                val = profile.get("EIN (Tax ID)", "").replace("-", "")
                if val:
                    print(f"    >> Filling EIN: {val}")
                    fill_field(selector, val)
                    filled_any = True

            # Website / URL
            elif any(k in combined for k in ["business_url", "website", "company_url",
                                              "business-url", "url"]) and "email" not in combined:
                val = profile.get("Business Website", "")
                if val:
                    print(f"    >> Filling website: {val}")
                    fill_field(selector, val)
                    filled_any = True

            # Product description
            elif any(k in combined for k in ["product_description", "business_description",
                                              "product-description", "description"]) and inp["tag"] != "button":
                val = profile.get("Product Description", "")
                if val:
                    print(f"    >> Filling product description")
                    fill_field(selector, val[:500])
                    filled_any = True

            # Statement descriptor
            elif any(k in combined for k in ["statement_descriptor", "statement-descriptor",
                                              "descriptor"]):
                if "short" in combined:
                    val = profile.get("Shortened Descriptor", "")
                else:
                    val = profile.get("Statement Descriptor", "")
                if val:
                    print(f"    >> Filling statement descriptor: {val}")
                    fill_field(selector, val)
                    filled_any = True

            # Phone
            elif any(k in combined for k in ["phone", "telephone"]) and "personal" not in combined:
                val = profile.get("Business Phone", "").replace("-", "")
                if val:
                    print(f"    >> Filling phone: {val}")
                    fill_field(selector, val)
                    filled_any = True

            # First name
            elif any(k in combined for k in ["first_name", "first-name", "firstname"]):
                val = profile.get("Representative First Name", profile.get("Full Name", "").split()[0])
                print(f"    >> Filling first name: {val}")
                fill_field(selector, val)
                filled_any = True

            # Last name
            elif any(k in combined for k in ["last_name", "last-name", "lastname"]):
                val = profile.get("Representative Last Name", " ".join(profile.get("Full Name", "").split()[1:]))
                print(f"    >> Filling last name: {val}")
                fill_field(selector, val)
                filled_any = True

            # DOB
            elif any(k in combined for k in ["dob", "date_of_birth", "date-of-birth",
                                              "birthday", "birth"]):
                dob = profile.get("Date of Birth", "")
                val = dob.replace("/", "")
                print(f"    >> Filling DOB: {dob}")
                fill_field(selector, val)
                filled_any = True

            # SSN (full)
            elif any(k in combined for k in ["ssn", "social_security", "social-security",
                                              "id_number"]) and "last" not in combined:
                val = profile.get("SSN", "").replace("-", "")
                print(f"    >> Filling SSN: ***-**-{val[-4:]}")
                fill_field(selector, val)
                filled_any = True

            # SSN last 4
            elif "ssn" in combined and "last" in combined:
                val = profile.get("SSN", "").replace("-", "")[-4:]
                print(f"    >> Filling SSN last 4: {val}")
                fill_field(selector, val)
                filled_any = True

            # Address line 1
            elif any(k in combined for k in ["address_line1", "address-line1",
                                              "street_address", "line1", "address1"]):
                if any(p in combined for p in ["home", "personal", "representative"]):
                    val = profile.get("Representative Address", profile.get("Business Address", "").split(",")[0].strip())
                else:
                    val = profile.get("Business Address", "").split(",")[0].strip()
                print(f"    >> Filling address: {val}")
                fill_field(selector, val)
                filled_any = True

            # City
            elif any(k in combined for k in ["address_city", "address-city", "city"]):
                if any(p in combined for p in ["home", "personal", "representative"]):
                    val = profile.get("Representative City", "Hayward")
                else:
                    val = "Hayward"
                print(f"    >> Filling city: {val}")
                fill_field(selector, val)
                filled_any = True

            # ZIP
            elif any(k in combined for k in ["address_zip", "address-zip", "postal_code",
                                              "postal-code", "zip"]):
                if any(p in combined for p in ["home", "personal", "representative"]):
                    val = profile.get("Representative Zip", "94545")
                else:
                    val = "94545"
                print(f"    >> Filling zip: {val}")
                fill_field(selector, val)
                filled_any = True

            # State
            elif any(k in combined for k in ["state", "region"]):
                if any(p in combined for p in ["home", "personal", "representative"]):
                    val = profile.get("Representative State", "CA")
                else:
                    val = "CA"
                print(f"    >> Filling state: {val}")
                fill_field(selector, val)
                filled_any = True

            # Routing number
            elif any(k in combined for k in ["routing", "routing_number", "routing-number"]):
                val = profile.get("Routing Number", "")
                print(f"    >> Filling routing: {val}")
                fill_field(selector, val)
                filled_any = True

            # Account number
            elif any(k in combined for k in ["account_number", "account-number"]) \
                    and "routing" not in combined and "confirm" not in combined:
                val = profile.get("Account Number", "")
                print(f"    >> Filling account number: {val}")
                fill_field(selector, val)
                filled_any = True

            # Confirm account number
            elif any(k in combined for k in ["confirm_account", "confirm-account",
                                              "re_enter", "verify_account"]):
                val = profile.get("Account Number", "")
                print(f"    >> Confirming account number")
                fill_field(selector, val)
                filled_any = True

        # Handle business type selections
        if "business type" in body_lower or "type of business" in body_lower:
            print("  >> Business type page — selecting LLC")
            time.sleep(1)
            if not click_by_text("LLC") and not click_by_text("Limited liability company"):
                click_by_text("Company")

        # Handle industry selection
        if "industry" in body_lower and "select" in body_lower:
            print("  >> Industry page — selecting Software")
            click_by_text("Software")
            time.sleep(1)

        # Click Continue/Next/Submit
        time.sleep(1)
        continued = False
        for btn_text in ["Continue", "Next", "Submit", "Save", "Agree and submit",
                         "Done", "Activate payments", "Activate"]:
            if click_by_text(btn_text, "button,a"):
                print(f"  >> Clicked '{btn_text}'")
                continued = True
                break

        if not continued:
            for dt in ["merchant-form-submit", "continue-button", "submit-button", "next-button",
                       "requirements-index-done-button"]:
                if click_element(f'button[data-testid="{dt}"], a[data-testid="{dt}"]'):
                    print(f"  >> Clicked data-testid='{dt}'")
                    continued = True
                    break

        if not continued:
            print("  [!] No Continue/Submit button — may need manual action")

        time.sleep(3)

        # Check for completion
        new_url, _ = get_page_info()
        new_body = get_body_text().lower()

        from urllib.parse import urlparse
        parsed = urlparse(new_url.lower())
        path = parsed.path
        is_onboarding = any(p in path for p in ["/register", "/welcome", "/setup", "/onboarding"])
        is_dashboard = any(p in path for p in ["/dashboard", "/home", "/payments", "/apikeys", "/developers"]) or path == "/"

        if not is_onboarding and is_dashboard:
            print("\n[OUTCOME] [OK] Reached Stripe Dashboard — Account setup complete!")
            save_details(filename, profile, email, password, "Account Created / Dashboard Reached",
                        new_url, title)
            break
        elif "verification" in new_body and "pending" in new_body:
            print("\n[OUTCOME] Account created — Verification pending")
            save_details(filename, profile, email, password, "Created - Verification Pending",
                        new_url, title)
            break
    else:
        print("\n[!] Reached max steps. Saving current state.")
        save_details(filename, profile, email, password, "Onboarding Incomplete", url, title)

    print(f"\n[OK] Details saved to: {os.path.abspath(filename)}")
    print("Chrome remains open for manual inspection.")


if __name__ == "__main__":
    main()
