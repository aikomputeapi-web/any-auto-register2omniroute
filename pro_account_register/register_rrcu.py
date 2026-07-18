import sys
import os
import time
import re
import argparse
import json

# Add root directory to python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.executors.playwright import PlaywrightExecutor

# Landing pages / portal endpoints
RRCU_LANDING_URL = "https://www.rrcu.com/become-member"
RRCU_APPLY_DIRECT_URL = "https://onboard.cotribute.co/flows/bc40fb2f-7bbd-4096-bccb-4facf4eedd62"


def parse_user_data(filepath, line_index):
    """
    Parse Shirley|Obrine|16857 clinton|San Leandro|CA|94578|12/04/1935|553-56-9291
    """
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


def fill_react_input(page, selector, value):
    """
    Safely fill a React/JS input by dispatching input/change/blur events.
    Accepts selector string OR a Playwright Locator.
    """
    js_fn = """
    ([sel, val]) => {
        const el = document.querySelector(sel);
        if (el) {
            try {
                const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value").set;
                setter.call(el, val);
            } catch (e) {
                el.value = val;
            }
            el.dispatchEvent(new Event('input', { bubbles: true }));
            el.dispatchEvent(new Event('change', { bubbles: true }));
            el.dispatchEvent(new Event('blur', { bubbles: true }));
            return true;
        }
        return false;
    }
    """
    return page.evaluate(js_fn, (selector, value))


def fill_react_textarea(page, selector, value):
    js_fn = """
    ([sel, val]) => {
        const el = document.querySelector(sel);
        if (el) {
            try {
                const setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, "value").set;
                setter.call(el, val);
            } catch (e) {
                el.value = val;
            }
            el.dispatchEvent(new Event('input', { bubbles: true }));
            el.dispatchEvent(new Event('change', { bubbles: true }));
            el.dispatchEvent(new Event('blur', { bubbles: true }));
            return true;
        }
        return false;
    }
    """
    return page.evaluate(js_fn, (selector, value))


def select_dropdown(page, selector, value):
    """Select an option on a native <select>, also React-safe."""
    js_fn = """
    ([sel, val]) => {
        const el = document.querySelector(sel);
        if (el) {
            el.value = val;
            el.dispatchEvent(new Event('input', { bubbles: true }));
            el.dispatchEvent(new Event('change', { bubbles: true }));
            el.dispatchEvent(new Event('blur', { bubbles: true }));
            return true;
        }
        return false;
    }
    """
    return page.evaluate(js_fn, (selector, value))


def click_visible_btn(page, text_query):
    """Find and click a visible button/link whose text matches the given query."""
    js_fn = """
    ([text]) => {
        const btns = Array.from(document.querySelectorAll('a, button, div.btn-add, input[type="button"], input[type="submit"]'));
        const visibleBtn = btns.find(btn => {
            const rect = btn.getBoundingClientRect();
            const style = window.getComputedStyle(btn);
            const isVisible = rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden';
            if (!isVisible) return false;
            const btnText = (btn.textContent || btn.value || "").trim().toLowerCase();
            return btnText.includes(text.toLowerCase()) || btn.id === text || btn.className.includes(text);
        });

        const fallbackBtns = Array.from(document.querySelectorAll('*')).filter(el => {
            const rect = el.getBoundingClientRect();
            const style = window.getComputedStyle(el);
            const isVisible = rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden';
            return isVisible && (el.tagName === 'A' || el.tagName === 'BUTTON' || el.getAttribute('role') === 'button' || el.tagName === 'INPUT');
        });

        const bestBtn = fallbackBtns.find(btn => (btn.textContent || btn.value || "").trim().toLowerCase().includes(text.toLowerCase()));

        const target = bestBtn || visibleBtn;
        if (target) {
            target.click();
            return true;
        }
        return false;
    }
    """
    return page.evaluate(js_fn, [text_query])


def dump_page_inputs(page):
    js_fn = """
    () => {
        const results = [];
        const inputs = document.querySelectorAll("input, select, textarea, button");
        for (const el of inputs) {
            if (el.offsetWidth > 0 && el.offsetHeight > 0) {
                results.push({
                    tag: el.tagName.toLowerCase(),
                    id: el.id || "",
                    name: el.name || "",
                    type: el.type || "",
                    placeholder: el.placeholder || "",
                    text: (el.textContent || "").trim().substring(0, 80),
                    value: (el.tagName === 'SELECT' ? el.value : (el.value || "")),
                    checked: el.checked || false,
                    label: (el.labels && el.labels[0]) ? el.labels[0].textContent.trim() : ""
                });
            }
        }
        return results;
    }
    """
    try:
        return page.evaluate(js_fn)
    except Exception:
        return []


def find_label_input(page, label_pattern):
    """Return the input element id whose associated label or nearby text matches the label regex."""
    js_fn = """
    ([pat]) => {
        const re = new RegExp(pat, 'i');
        const inputs = document.querySelectorAll('input, select, textarea');
        for (const el of inputs) {
            if (!(el.offsetWidth > 0 && el.offsetHeight > 0)) continue;
            // Associated label via <label for=id>
            let labelText = '';
            if (el.id) {
                const lab = document.querySelector(`label[for="${el.id}"]`);
                if (lab) labelText = lab.textContent || '';
            }
            if (!labelText && el.labels && el.labels[0]) {
                labelText = el.labels[0].textContent || '';
            }
            // Fallback to placeholder / aria-label / aria-labelledby
            if (!labelText) labelText = el.placeholder || el.getAttribute('aria-label') || '';
            if (!labelText && el.getAttribute('aria-labelledby')) {
                const lb = document.getElementById(el.getAttribute('aria-labelledby'));
                if (lb) labelText = lb.textContent || '';
            }
            if (re.test(labelText)) {
                return { id: el.id, name: el.name, type: el.type, label: labelText.trim() };
            }
        }
        return null;
    }
    """
    try:
        return page.evaluate(js_fn, [label_pattern])
    except Exception:
        return None


def click_input_with_label(page, label_pattern):
    """Click the first input/radio/checkbox whose label matches the given pattern."""
    js_fn = """
    ([pat]) => {
        const re = new RegExp(pat, 'i');
        const inputs = document.querySelectorAll('input[type="checkbox"], input[type="radio"]');
        for (const el of inputs) {
            if (!(el.offsetWidth > 0 && el.offsetHeight > 0)) continue;
            let labelText = '';
            if (el.id) {
                const lab = document.querySelector(`label[for="${el.id}"]`);
                if (lab) labelText = lab.textContent || '';
            }
            if (!labelText && el.labels && el.labels[0]) {
                labelText = el.labels[0].textContent || '';
            }
            if (!labelText) labelText = el.getAttribute('aria-label') || '';
            if (re.test(labelText)) {
                el.click();
                return { id: el.id, label: labelText.trim() };
            }
        }
        return null;
    }
    """
    try:
        return page.evaluate(js_fn, [label_pattern])
    except Exception:
        return None


def save_details(filename, user_info, email, phone, url, title, status="Unknown"):
    with open(filename, "w", encoding="utf-8") as f:
        f.write("Red River Credit Union Account Details\n")
        f.write("=" * 50 + "\n")
        f.write(f"Name: {user_info['first_name']} {user_info['last_name']}\n")
        f.write(f"Address: {user_info['address']}, {user_info['city']}, {user_info['state']} {user_info['zip']}\n")
        f.write(f"DOB: {user_info['dob_str']}\n")
        f.write(f"SSN: {user_info['ssn']}\n")
        f.write(f"Email: {email}\n")
        f.write(f"Phone: {phone}\n")
        f.write("-" * 50 + "\n")
        f.write(f"Status: {status}\n")
        f.write(f"Final URL: {url}\n")
        f.write(f"Title: {title}\n")
        f.write(f"Timestamp: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")


def fill_labeled_input(page, label_pattern, value):
    """Find input by label and fill it. Returns success bool."""
    found = find_label_input(page, label_pattern)
    if not found:
        return False
    sel = ""
    if found.get("id"):
        sel = f"#{found['id']}"
    elif found.get("name"):
        sel = f"[name=\"{found['name']}\"]"
    if not sel:
        return False
    return bool(fill_react_input(page, sel, str(value)))


def submit_form_if_possible(page):
    """Try multiple strategies to click the next/submit/continue button on the current step."""
    candidates = ["Continue", "Next", "Submit", "I Agree", "Apply Now", "Get Started", "Confirm", "Save and Continue"]
    submit_btn = page.locator(
        "button[id*=submit], button[id*=continue], button[id*=apply], button[id*=next], "
        "input[type=submit], input[value*=Continue], input[value*=Submit], input[value*=Next], "
        "a:has-text('Continue'), a:has-text('Submit'), a:has-text('Next'), "
        "button:has-text('Continue'), button:has-text('Submit'), button:has-text('Next'), "
        "button:has-text('I Agree'), button:has-text('Apply Now'), button:has-text('Get Started')"
    ).first
    try:
        if submit_btn.count() > 0 and submit_btn.is_visible():
            submit_btn.click()
            return True
    except Exception:
        pass
    for c in candidates:
        if click_visible_btn(page, c):
            return True
    return False


def main():
    parser = argparse.ArgumentParser(description="Automate Red River Credit Union Checking Account Application.")
    parser.add_argument("--line", type=int, default=1, help="The 1-based line number of user data to register (default: 1)")
    parser.add_argument("--email", type=str, default=None, help="Email address to register (defaults to firstname+lastname@audioplexdesigns.com)")
    parser.add_argument("--phone", type=str, default="6692506085", help="Phone number to register (digits only)")
    parser.add_argument("--dataset", type=str, default="pointclickcare data.txt", help="Path to the dataset text file")

    args = parser.parse_args()
    line_idx = args.line - 1

    print("=" * 60)
    print("RED RIVER CREDIT UNION REGISTRATION")
    print("=" * 60)

    # 1. Parse dataset
    try:
        user_info = parse_user_data(args.dataset, line_idx)
        print(f"[OK] Parsed dataset: {user_info['first_name']} {user_info['last_name']}")
    except Exception as e:
        print(f"[ERROR] Failed to parse dataset: {e}")
        return

    if args.email:
        email = args.email
    else:
        email = f"{user_info['first_name']}{user_info['last_name']}@audioplexdesigns.com".lower().replace(" ", "").replace("-", "")
    phone = re.sub(r"\D", "", args.phone)
    phone_part1 = phone[0:3]
    phone_part2 = phone[3:6]
    phone_part3 = phone[6:10]
    print(f"  Email: {email}")
    print(f"  Phone: {phone}")

    # Generate plausible Driver's License for the user's state
    dl_number = user_info["ssn"][0:9]
    dl_issue_month = user_info["dob_month"]
    dl_issue_day = user_info["dob_day"]
    dl_issue_year = "2023"
    dl_exp_month = user_info["dob_month"]
    dl_exp_day = user_info["dob_day"]
    dl_exp_year = "2031"

    # 2. Launch browser in headed mode
    print("\nLaunching browser in headed mode...")
    executor = PlaywrightExecutor(headless=False)
    page = executor.page

    # Protect native eval (Cotribute's framework crashes if eval is replaced)
    page.add_init_script("""
        try {
            const nativeEval = window.eval;
            Object.defineProperty(window, 'eval', {
                value: nativeEval,
                writable: false,
                configurable: false
            });
        } catch (e) {}
    """)

    script_dir = os.path.dirname(os.path.abspath(__file__))
    results_dir = os.path.join(script_dir, "registration_results")
    os.makedirs(results_dir, exist_ok=True)
    detail_file = os.path.join(results_dir, f"rrcu_details_line_{args.line}.txt")

    try:
        # Navigate directly to the Cotribute onboard flow (the "Open A Membership" target)
        print(f"Navigating to RRCU onboarding portal: {RRCU_APPLY_DIRECT_URL}")
        page.goto(RRCU_APPLY_DIRECT_URL, wait_until="domcontentloaded")
        time.sleep(3)

        # ===== Step 1: Email entry on welcome page =====
        print("\n[Step 1] Entering email address on welcome page...")
        email_input = None
        for sel in [
            'input[type="email"]',
            'input[placeholder*="email" i]',
            'input[placeholder*="Email" i]',
            'input',
        ]:
            loc = page.locator(sel).first
            if loc.count() > 0:
                email_input = loc
                break
        if email_input is None:
            raise RuntimeError("Could not find email input on welcome page.")

        email_input.click()
        email_input.fill("")
        email_input.fill(email)
        email_input.dispatchEvent("input")
        email_input.dispatchEvent("change")
        time.sleep(0.5)

        # Click "APPLY NOW" button
        if not click_visible_btn(page, "APPLY NOW") and not click_visible_btn(page, "Apply"):
            apply_btn = page.locator('button:has-text("APPLY"), button[type="submit"]').first
            if apply_btn.count() > 0:
                apply_btn.click()
            else:
                raise RuntimeError("Could not find APPLY NOW button.")
        time.sleep(4)

        # ===== Step 2: OTP / Verification (manual or auto) =====
        # The Cotribute flow typically sends an OTP to the email. If a mailbox
        # OTP integration is wired up via task_control, the operator can paste it
        # into the headed browser window. We just pause here and monitor.
        print("\n[Step 2] Waiting for OTP/verification step (if any)...")
        otp_handled = False
        for _ in range(3):
            try:
                # Common Cotribute OTP input selector
                otp_input = page.locator('input[name*="otp" i], input[name*="code" i], input[placeholder*="code" i], input[placeholder*="OTP" i]').first
                if otp_input.count() > 0 and otp_input.is_visible():
                    print("OTP input detected — please enter the OTP code from the email in the browser window.")
                    # Wait for the OTP field to be cleared (operator fills it and continues)
                    try:
                        page.wait_for_function(
                            "() => { const el = document.querySelector('input[name*=\"otp\" i], input[name*=\"code\" i], input[placeholder*=\"code\" i], input[placeholder*=\"OTP\" i]'); return el && el.value && el.value.length >= 4; }",
                            timeout=180000,
                        )
                        otp_handled = True
                    except Exception:
                        # If operator already advanced to the next page, consider it handled
                        otp_handled = True
                    break
            except Exception:
                pass
            time.sleep(2)

        if otp_handled:
            print("OTP field detected. Attempting to advance...")
            submit_form_if_possible(page)
            time.sleep(4)
        else:
            print("No OTP step detected — continuing.")

        # ===== Step 3: Personal Information Page =====
        print("\n[Step 3] Filling Personal Information form...")

        # First Name
        if not fill_labeled_input(page, r"first\s*name", user_info["first_name"]):
            fill_labeled_input(page, r"^\s*Name\b", user_info["first_name"])
        # Last Name
        fill_labeled_input(page, r"last\s*name", user_info["last_name"])

        # SSN (some flows ask full, some split; handle both)
        if not fill_labeled_input(page, r"social\s*security|SSN", user_info["ssn"]):
            # Split SSN fields
            fill_labeled_input(page, r"ssn.*(1|first)|social.*1", user_info["ssn"][0:3])
            fill_labeled_input(page, r"ssn.*(2|middle)|social.*2", user_info["ssn"][3:5])
            fill_labeled_input(page, r"ssn.*(3|last)|social.*3", user_info["ssn"][5:9])

        # Date of Birth (varied formats)
        if not fill_labeled_input(page, r"date\s*of\s*birth|DOB|birthday", user_info["dob_str"]):
            if not fill_labeled_input(page, r"birth.*month|DOB.*1|month", user_info["dob_month"]):
                # try splitting on slash-delimited single input first via dump
                pass
            fill_labeled_input(page, r"birth.*day|DOB.*2", user_info["dob_day"])
            fill_labeled_input(page, r"birth.*year|DOB.*3", user_info["dob_year"])
            # Some Cotribute forms use MM/DD/YYYY single input
            fill_labeled_input(page, r"MM/DD/YYYY|birth|DOB", user_info["dob_str"])

        # Address
        fill_labeled_input(page, r"street|address|residential\s*address", user_info["address"])
        # City
        fill_labeled_input(page, r"^city\b", user_info["city"])
        # State (dropdown)
        state_inputs = dump_page_inputs(page)
        state_filled = False
        for inp in state_inputs:
            if inp["tag"] == "select" and re.search(r"state", inp.get("label", "") or inp.get("id", "") or "", re.I):
                if select_dropdown(page, f"#{{{inp['id']}}}", user_info["state"]):
                    state_filled = True
                    break
                elif inp.get("name"):
                    if select_dropdown(page, f"[name=\"{inp['name']}\"]", user_info["state"]):
                        state_filled = True
                        break
        if not state_filled:
            fill_labeled_input(page, r"state", user_info["state"])

        # ZIP code
        fill_labeled_input(page, r"zip|postal", user_info["zip"])

        # Email (if requested again on this page)
        fill_labeled_input(page, r"email", email)

        # Phone — single or split
        if not fill_labeled_input(page, r"phone|mobile", phone):
            fill_labeled_input(page, r"phone.*(1|area|first)", phone_part1)
            fill_labeled_input(page, r"phone.*(2|prefix|middle)", phone_part2)
            fill_labeled_input(page, r"phone.*(3|line|last)", phone_part3)

        # Mother's Maiden Name (some CU forms)
        fill_labeled_input(page, r"maiden\s*name", "Smith")

        # ID Card / Driver's License
        fill_labeled_input(page, r"driver|id\s*card|license|identification", dl_number)
        fill_labeled_input(page, r"issue.*date|date.*issued", f"{dl_issue_month}/{dl_issue_day}/{dl_issue_year}")
        fill_labeled_input(page, r"expir.*date|date.*expir", f"{dl_exp_month}/{dl_exp_day}/{dl_exp_year}")

        # Income
        fill_labeled_input(page, r"income|gross\s*monthly|monthly\s*income", "3750")

        # Citizenship / Employment dropdowns (best-effort)
        for inp in dump_page_inputs(page):
            if inp["tag"] != "select":
                continue
            label_text = (inp.get("label", "") + " " + inp.get("id", "") + " " + inp.get("name", "")).lower()
            sel = f"#{inp['id']}" if inp.get("id") else f"[name=\"{inp['name']}\"]"
            if "citizen" in label_text:
                select_dropdown(page, sel, "USCITIZEN")
            elif "employ" in label_text:
                select_dropdown(page, sel, "RETIRED")
            elif "occup" in label_text and "status" in label_text:
                select_dropdown(page, sel, "OWN")

        # Citizenship booleans (radio/checkbox)
        click_input_with_label(page, r"us\s*citizen|citizen.*yes|^yes$")

        time.sleep(1.5)

        # ===== Step 4: Eligibility — American Consumer Council (ACC) =====
        print("\n[Step 4] Selecting ACC (American Consumer Council) eligibility if shown...")
        click_input_with_label(page, r"american\s*consumer\s*council|ACC")
        click_input_with_label(page, r"cornerstone|CCUF")

        time.sleep(1)

        # ===== Step 5: Submit personal info page =====
        print("Submitting Personal Info step...")
        if not submit_form_if_possible(page):
            print("⚠ No visible continue/submit button found on personal info step. Waiting for manual advance...")
            time.sleep(20)

        time.sleep(5)

        # ===== Step 6: Monitoring loop =====
        print("\n" + "=" * 50)
        print("Monitoring subsequent pages. The browser is in headed mode.")
        print("If you need to enter OTP or CAPTCHA, please complete it in the browser window.")

        funding_handled = False
        for page_num in range(7, 30):
            print(f"\n--- Checking Page State {page_num} ---")
            try:
                save_details(detail_file, user_info, email, phone, page.url, page.title(), "Pending Submission")
            except Exception:
                pass

            time.sleep(3)
            print(f"Current URL: {page.url}")
            print(f"Current Title: {page.title()}")

            # Dump visible inputs for debugging
            inputs = dump_page_inputs(page)
            print("Visible Inputs:")
            for inp in inputs:
                print(f"  <{inp['tag']}> id='{inp['id']}' name='{inp['name']}' type='{inp['type']}' label='{inp.get('label','')}' placeholder='{inp['placeholder']}'")

            # Track whether we made any change on this pass
            filled_any = False

            # Funding page heuristic — fill $5 deposit & credit card field if present
            page_title = page.title() or ""
            page_text = ""
            try:
                page_text = page.evaluate("() => document.body.innerText || ''") or ""
            except Exception:
                page_text = ""
            page_text_lower = page_text.lower()

            if "funding" in page_title.lower() or "funding" in page_text_lower or "deposit" in page_text_lower:
                if not funding_handled:
                    print("Funding page detected — filling $5 deposit amount...")
                    # Try to find amount input
                    amount_input = None
                    for inp in inputs:
                        if inp["tag"] == "input" and re.search(r"amount|deposit|initial", inp.get("label", "") + " " + inp.get("placeholder", ""), re.I):
                            amount_input = inp
                            break
                    if amount_input:
                        sel = f"#{amount_input['id']}" if amount_input.get("id") else f"[name=\"{amount_input['name']}\"]"
                        fill_react_input(page, sel, "5.00")
                        filled_any = True
                        time.sleep(1)

                    # Try to switch to credit card if available
                    if click_visible_btn(page, "Credit Card") or click_visible_btn(page, "Card"):
                        time.sleep(2)
                        filled_any = True

                    # Fill credit card number (split or single) with test VISA 4111...
                    cc_num = "4111111111111111"
                    for i in range(1, 5):
                        fid = f"cCreditCardNumber{i}"
                        if page.locator(f"#{fid}").count() > 0:
                            fill_react_input(page, f"#{fid}", cc_num[(i-1)*4:i*4])
                            filled_any = True

                    # Single CC number input
                    if not filled_any and fill_labeled_input(page, r"card\s*number|credit\s*card", cc_num):
                        filled_any = True

                    # Expiry
                    fill_labeled_input(page, r"expir", "12/28")
                    # CVV
                    fill_labeled_input(page, r"cvv|cvc|security\s*code", "123")
                    # Name on card
                    fill_labeled_input(page, r"name\s*on\s*card|cardholder", f"{user_info['first_name']} {user_info['last_name']}")
                    # Billing zip
                    fill_labeled_input(page, r"billing\s*zip|zip", user_info["zip"])

                    funding_handled = True
                    print("Funding form filled — submitting...")
                    submit_form_if_possible(page)
                    time.sleep(5)
                    continue

            # Compliance / disclosure checkboxes & dropdowns
            for inp in inputs:
                # Disclosures / terms checkboxes
                if inp["tag"] == "input" and inp["type"] == "checkbox" and not inp["checked"]:
                    if inp.get("id"):
                        try:
                            page.locator(f"#{inp['id']}").click()
                            filled_any = True
                        except Exception:
                            pass
                # Compliance dropdowns default to "No"
                if inp["tag"] == "select":
                    label_text = (inp.get("label", "") + " " + inp.get("id", "")).lower()
                    if any(k in label_text for k in ("pep", "verafin", "wire", "electronic", "backup", "fatca", "referral")):
                        sel = f"#{inp['id']}" if inp.get("id") else f"[name=\"{inp['name']}\"]"
                        if select_dropdown(page, sel, "No"):
                            filled_any = True

            time.sleep(1)

            # Try clicking next/submit
            if not submit_form_if_possible(page):
                print("⚠ No visible continue/submit button found. Waiting for manual navigation...")
                time.sleep(8)

            # Outcome detection
            curr_url = (page.url or "").lower()
            curr_body = page_text_lower
            if any(k in curr_body or k in curr_url for k in ("declined", "denied", "deny")):
                print("[OUTCOME] Application outcome reached: Denied/Declined")
                save_details(detail_file, user_info, email, phone, page.url, page.title(), "Denied/Declined")
                break
            elif any(k in curr_body or k in curr_url for k in ("approved", "welcome", "congratulations", "success")):
                print("[OUTCOME] Application outcome reached: Approved!")
                save_details(detail_file, user_info, email, phone, page.url, page.title(), "Approved")
                break
            elif any(k in curr_body for k in ("pending", "under review", "review")):
                print("[OUTCOME] Application outcome reached: Under Review / Pending")
                save_details(detail_file, user_info, email, phone, page.url, page.title(), "Under Review / Pending")
                break

        # Final wait/inspect
        print("\nApplication automation run complete. Keeping browser open for 15 seconds...")
        time.sleep(15)

    except Exception as e:
        print(f"\n[ERROR] Error during application automation: {e}")
    finally:
        executor.close()
        print("Browser closed.")


if __name__ == "__main__":
    main()