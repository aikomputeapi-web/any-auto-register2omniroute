import sys
import os
import time
import re
import argparse

# Add root directory to python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.executors.playwright import PlaywrightExecutor

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
    Safely fill a React input by dispatching input/change/blur events
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

def select_react_dropdown(page, selector, value):
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

def click_element(page, selector):
    js_fn = """
    sel => {
        const el = document.querySelector(sel);
        if (el) {
            el.click();
            return true;
        }
        return false;
    }
    """
    return page.evaluate(js_fn, selector)

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
                    text: (el.textContent || "").trim().substring(0, 60)
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

def save_details(filename, user_info, email, phone, url, title):
    with open(filename, "w", encoding="utf-8") as f:
        f.write("U.S. Bank Checking Account Application Details\n")
        f.write("=" * 50 + "\n")
        f.write(f"Name: {user_info['first_name']} {user_info['last_name']}\n")
        f.write(f"Address: {user_info['address']}, {user_info['city']}, {user_info['state']} {user_info['zip']}\n")
        f.write(f"DOB: {user_info['dob_str']}\n")
        f.write(f"SSN: {user_info['ssn']}\n")
        f.write(f"Email: {email}\n")
        f.write(f"Phone: {phone}\n")
        f.write("-" * 50 + "\n")
        f.write(f"Final URL: {url}\n")
        f.write(f"Title: {title}\n")
        f.write(f"Timestamp: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")

def main():
    parser = argparse.ArgumentParser(description="Automate US Bank Checking Account Application.")
    parser.add_argument("--line", type=int, default=1, help="The 1-based line number of user data to register (default: 1)")
    parser.add_argument("--email", type=str, default=None, help="Email address to register (defaults to firstname+lastname@audioplexdesigns.com)")
    parser.add_argument("--phone", type=str, default="6692506085", help="Phone number to register (digits only)")
    parser.add_argument("--dataset", type=str, default="pointclickcare data.txt", help="Path to the dataset text file")
    
    args = parser.parse_args()
    line_idx = args.line - 1
    
    print("=" * 60)
    print("U.S. BANK CHECKING ACCOUNT REGISTRATION")
    print("=" * 60)
    
    # 1. Parse dataset
    try:
        user_info = parse_user_data(args.dataset, line_idx)
        print("✓ Successfully parsed dataset:")
        print(f"  Name: {user_info['first_name']} {user_info['last_name']}")
        print(f"  Address: {user_info['address']}, {user_info['city']}, {user_info['state']} {user_info['zip']}")
        print(f"  DOB: {user_info['dob_str']} (SSN: {user_info['ssn']})")
    except Exception as e:
        print(f"✗ Failed to parse dataset: {e}")
        return
        
    if args.email:
        email = args.email
    else:
        email = f"{user_info['first_name']}{user_info['last_name']}@audioplexdesigns.com".lower().replace(" ", "").replace("-", "")
    phone = args.phone.replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
    print(f"  Email: {email}")
    print(f"  Phone: {phone}")
    
    # 2. Launch browser in headed mode
    print("\nLaunching browser in headed mode...")
    executor = PlaywrightExecutor(headless=False)
    page = executor.page
    
    # Protect native eval
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
    
    try:
        landing_url = "https://www.usbank.com/bank-accounts/checking-accounts/bank-smartly-checking.html"
        print(f"Navigating to landing page: {landing_url}")
        page.goto(landing_url, wait_until="domcontentloaded")
        time.sleep(5)
        
        # Step 1: Click "Open an account"
        print("Locating 'Open an account' button...")
        btn = page.locator("a.zip-util-link").first
        if btn.count() > 0:
            print("✓ Clicking 'Open an account' button...")
            btn.click()
            time.sleep(2)
        else:
            raise RuntimeError("Could not find 'Open an account' button.")
            
        # Step 2: ZIP Code Modal
        print("Checking for ZIP Code dialog...")
        try:
            page.wait_for_selector("#zipcode_entry", timeout=5000)
            zip_input = page.locator("#zipcode_entry")
            print(f"Entering ZIP code: {user_info['zip']}...")
            zip_input.fill(user_info["zip"])
            time.sleep(1)
            
            go_btn = page.locator("button.zipInputButton").first
            print("✓ Submitting ZIP code...")
            go_btn.click()
            time.sleep(2)
        except Exception:
            print("⚠ ZIP code modal not shown, continuing...")
            
        # Step 3: Customer Question Page
        print("Checking for 'Are you a U.S. Bank customer?' page...")
        try:
            # Wait for loading spinner to disappear if it exists
            try:
                page.wait_for_selector("text=Loading", state="hidden", timeout=15000)
            except Exception:
                pass
                
            page.wait_for_selector("#usb-login-radio-groupChoice2", timeout=45000)
            no_radio = page.locator("#usb-login-radio-groupChoice2")
            print("✓ Selecting 'No'...")
            no_radio.click()
            time.sleep(1)
            
            submit_btn = page.locator("#submitButton")
            print("✓ Clicking Continue...")
            submit_btn.click()
            time.sleep(2)
        except Exception:
            print("⚠ Customer choice page not shown or already passed.")
            
        # Step 4: Contact Info Page ("Let's get started")
        print("Checking for Contact Info fields...")
        try:
            try:
                page.wait_for_selector("text=Loading", state="hidden", timeout=15000)
            except Exception:
                pass
                
            page.wait_for_selector("#input_firstName", timeout=30000)
            print("Filling Contact Information...")
            fill_react_input(page, "#input_firstName", user_info["first_name"])
            fill_react_input(page, "#input_lastName", user_info["last_name"])
            fill_react_input(page, "#input_email", email)
            fill_react_input(page, "#input_mobileNumber", phone)
            time.sleep(1)
            
            submit_btn = page.locator("#submitButton")
            print("✓ Clicking Save & Continue...")
            submit_btn.click()
            time.sleep(5)
        except Exception:
            raise RuntimeError("Contact Info page failed to load.")
            
        # Step 5: Follow-up Pages
        # Since we don't know the exact inputs on subsequent pages, we loop and print inputs,
        # prompting the user if we get stuck or reach a disclosure screen.
        print("\n%s" % ("=" * 50))
        print("Monitoring subsequent pages. The browser is in headed mode.")
        print("If you need to enter OTP or CAPTCHA, please complete it in the browser window.")
        
        # Loop for up to 15 subsequent pages
        script_dir = os.path.dirname(os.path.abspath(__file__))
        results_dir = os.path.join(script_dir, "registration_results")
        os.makedirs(results_dir, exist_ok=True)
        filename = os.path.join(results_dir, f"usbank_details_line_{args.line}.txt")
        for page_num in range(1, 16):
            print(f"\n--- Checking Page State {page_num} ---")
            try:
                save_details(filename, user_info, email, phone, page.url, page.title())
            except Exception:
                pass
            
            # Wait for loading spinner to disappear if it exists
            try:
                page.wait_for_selector("text=Loading", state="hidden", timeout=15000)
            except Exception:
                pass
            time.sleep(2) # Allow React render to stabilize
            
            print(f"Current URL: {page.url}")
            print(f"Current Title: {page.title()}")
            
            # Save HTML for analysis
            html_path = f"debug_usbank_step_{page_num}.html"
            with open(html_path, "w", encoding="utf-8") as f:
                f.write(page.content())
            print(f"Saved page HTML: {html_path}")
            
            # Print visible inputs and select options
            inputs = dump_page_inputs(page)
            print("Visible Inputs:")
            for inp in inputs:
                print(f"  <{inp['tag']}> id='{inp['id']}' name='{inp['name']}' type='{inp['type']}' placeholder='{inp['placeholder']}' text='{inp['text']}'")
                if inp["tag"] == "select":
                    # Print select options
                    try:
                        opts = page.evaluate(f"() => Array.from(document.getElementById('{inp['id']}')?.options || []).map(o => o.value + ' | ' + o.text)")
                        print(f"    Options: {opts}")
                    except Exception:
                        pass
                
            # Take screenshot for record
            screenshot_path = f"debug_usbank_step_{page_num}.png"
            page.screenshot(path=screenshot_path)
            print(f"Saved screenshot: {screenshot_path}")
            
            # Auto-fill helpers for common fields if they appear on this page
            filled_any = False
            
            # Check for DOB (e.g. dateOfBirth)
            dob_input = page.locator("#input_dateOfBirth, input[id*=dob], input[name*=dob]").first
            if dob_input.count() > 0 and dob_input.is_visible():
                dob_val = f"{user_info['dob_month']}{user_info['dob_day']}{user_info['dob_year']}"
                print(f"Auto-filling DOB field: {dob_val}")
                dob_input.fill(dob_val)
                filled_any = True
                
            # Check for Address (e.g. address, street, line1)
            addr_input = page.locator("#input_address-collection-input_address1, input[id*=address1]").first
            if addr_input.count() > 0 and addr_input.is_visible():
                print(f"Auto-filling street address: {user_info['address']}")
                addr_input.fill(user_info["address"])
                filled_any = True
                
            # Check for SSN (e.x. ssn, taxId, taxIdentificationNumber)
            ssn_input = page.locator("#input_ssn, input[id*=ssn]").first
            if ssn_input.count() > 0 and ssn_input.is_visible():
                print(f"Auto-filling SSN: {user_info['ssn']}")
                ssn_input.fill(user_info["ssn"])
                filled_any = True
                
            # Check for City
            city_input = page.locator("#input_address-collection-input_city, input[id*=city]").first
            if city_input.count() > 0 and city_input.is_visible():
                print(f"Auto-filling city: {user_info['city']}")
                city_input.fill(user_info["city"])
                filled_any = True
                
            # Check for State
            state_select = page.locator("#select_address-collection-input_state, select[id*=state]").first
            if state_select.count() > 0 and state_select.is_visible():
                print(f"Auto-selecting state: {user_info['state']}")
                select_react_dropdown(page, "#select_address-collection-input_state", user_info["state"])
                filled_any = True
                
            # Check for Zip
            zip_input_f = page.locator("#input_address-collection-input_postalCode, input[id*=postalCode]").first
            if zip_input_f.count() > 0 and zip_input_f.is_visible():
                print(f"Auto-filling zip: {user_info['zip']}")
                zip_input_f.fill(user_info["zip"])
                filled_any = True
                
            # Check for US citizenship radio
            us_citizen_radio = page.locator("#citizenshipRadioButtonChoice1")
            if us_citizen_radio.count() > 0 and us_citizen_radio.is_visible():
                print("Selecting Yes for US citizenship...")
                us_citizen_radio.click()
                filled_any = True
                
            # Check for Country of permanent residence
            residence_select = page.locator("#select_countryOfPermanentResidence")
            if residence_select.count() > 0 and residence_select.is_visible():
                print("Selecting permanent residence...")
                select_react_dropdown(page, "#select_countryOfPermanentResidence", "US")
                filled_any = True
 
            # Check for Employment Status
            emp_status_select = page.locator("#select_employmentStatus").first
            if emp_status_select.count() > 0 and emp_status_select.is_visible():
                print("Auto-selecting employment status: RETIRED")
                select_react_dropdown(page, "#select_employmentStatus", "RETIRED")
                filled_any = True
 
            # Check for Recent Occupation (appears if RETIRED is selected)
            occupation_select = page.locator("#select_recentOccupation").first
            if occupation_select.count() > 0 and occupation_select.is_visible():
                print("Auto-selecting recent occupation: ADMN")
                select_react_dropdown(page, "#select_recentOccupation", "ADMN")
                filled_any = True
 
            # Check for Recent Occupation Description
            occupation_desc = page.locator("#input_recentOccupationDesc").first
            if occupation_desc.count() > 0 and occupation_desc.is_visible():
                print("Auto-filling occupation description: Clerk")
                fill_react_input(page, "#input_recentOccupationDesc", "Clerk")
                filled_any = True
 
            # Check for Total Annual Income
            income_input = page.locator("#input_totalAnnualIncome").first
            if income_input.count() > 0 and income_input.is_visible():
                print("Auto-filling total annual income: 45000")
                fill_react_input(page, "#input_totalAnnualIncome", "45000")
                filled_any = True
 
            # Check for Pension/retirement checkbox
            pension_cb = page.locator("#input_incomeSources_1_0").first
            if pension_cb.count() > 0 and pension_cb.is_visible():
                if not pension_cb.is_checked():
                    print("Selecting Pension/retirement checkbox...")
                    pension_cb.click()
                    filled_any = True
 
            # Check for Social Security checkbox
            ss_cb = page.locator("#input_incomeSources_1_2").first
            if ss_cb.count() > 0 and ss_cb.is_visible():
                if not ss_cb.is_checked():
                    print("Selecting Social Security checkbox...")
                    ss_cb.click()
                    filled_any = True
                
            # Check for Electronic Documents Agreement checkbox
            esign_cb = page.locator("#input_electronic-documents-checkbox").first
            if esign_cb.count() > 0 and esign_cb.is_visible():
                if not esign_cb.is_checked():
                    print("Selecting Electronic Documents Agreement...")
                    esign_cb.click()
                    filled_any = True
 
            # Check for Terms & Conditions checkbox
            terms_cb = page.locator("#input_terms-conditions-checkbox").first
            if terms_cb.count() > 0 and terms_cb.is_visible():
                if not terms_cb.is_checked():
                    print("Selecting Terms & Conditions...")
                    terms_cb.click()
                    filled_any = True
 
            # Check for Debit Card Options Choice 1
            card_radio = page.locator("#debitCardOptionsChoice1").first
            if card_radio.count() > 0 and card_radio.is_visible():
                if not card_radio.is_checked():
                    print("Selecting Debit Card Choice 1...")
                    card_radio.click()
                    filled_any = True
 
            # Check for Taxpayer Certification checkbox
            tax_cb = page.locator("#input_taxpayer-info-usb-checkbox").first
            if tax_cb.count() > 0 and tax_cb.is_visible():
                if not tax_cb.is_checked():
                    print("Selecting Taxpayer Certification...")
                    tax_cb.click()
                    filled_any = True
                
            # Check for Next / Continue / Submit / Apply button
            submit_btn = page.locator("button[id*=submit], button[id*=continue], button[id*=apply], button:has-text('Save'), button:has-text('Continue'), button:has-text('Next'), button:has-text('Apply')").first
            
            # Check if any loading spinner is visible
            spinner_visible = False
            for spinner_sel in [".loader", ".loader-container", ".submitLoader", "[class*=loader]", "[id*=loader]"]:
                try:
                    if page.locator(spinner_sel).first.is_visible():
                        spinner_visible = True
                        break
                except Exception:
                    pass
 
            if spinner_visible:
                print("⚠ Loading spinner/processing overlay is visible. Waiting...")
                time.sleep(5)
            elif submit_btn.count() > 0 and submit_btn.is_visible():
                print("Clicking next button...")
                submit_btn.click()
                time.sleep(8)
            else:
                time.sleep(5)
                
            # Check if url contains a success/outcome pattern
            if "decision" in page.url or "confirmation" in page.url or "outcome" in page.url or "success" in page.url or "denied" in page.url or "decline" in page.url:
                print("✓ Reached potential outcome page!")
                break
                
        # Save output details one last time
        try:
            save_details(filename, user_info, email, phone, page.url, page.title())
        except Exception:
            pass
        print("=" * 50)
        
        print("Keeping browser open for 15 seconds...")
        time.sleep(15)
        
    except Exception as e:
        print(f"\n✗ Error during application automation: {e}")
    finally:
        executor.close()
        print("Browser closed.")

if __name__ == "__main__":
    main()
