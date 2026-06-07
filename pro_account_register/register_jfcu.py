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
    Safely fill a React/JS input by dispatching input/change/blur events
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

def select_jqm_dropdown(page, selector, value):
    """
    Update a jQuery Mobile wrapped select element and refresh its widget
    """
    js_fn = """
    ([sel, val]) => {
        const el = document.querySelector(sel);
        if (el) {
            el.value = val;
            el.dispatchEvent(new Event('change', { bubbles: true }));
            if (window.jQuery) {
                try {
                    window.jQuery(el).selectmenu('refresh');
                } catch (e) {}
            }
            return true;
        }
        return false;
    }
    """
    return page.evaluate(js_fn, (selector, value))

def click_visible_btn(page, text_query):
    """
    Click a button based on visibility and matching text/id
    """
    js_fn = """
    ([text]) => {
        const btns = Array.from(document.querySelectorAll('a, button, div.btn-add, input[type="button"], input[type="submit"]'));
        const visibleBtn = btns.find(btn => {
            const rect = btn.getBoundingClientRect();
            const style = window.getComputedStyle(btn);
            const isVisible = rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden';
            if (!isVisible) return false;
            const btnText = (btn.textContent || "").trim().toLowerCase();
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
                    text: (el.textContent || "").trim().substring(0, 60),
                    checked: el.checked || false
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

def save_details(filename, user_info, email, phone, url, title, status="Unknown"):
    with open(filename, "w", encoding="utf-8") as f:
        f.write("Justice Federal Credit Union Account Details\n")
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

def main():
    parser = argparse.ArgumentParser(description="Automate JFCU Checking/Savings Account Application.")
    parser.add_argument("--line", type=int, default=1, help="The 1-based line number of user data to register (default: 1)")
    parser.add_argument("--email", type=str, default=None, help="Email address to register (defaults to firstname+lastname@audioplexdesigns.com)")
    parser.add_argument("--phone", type=str, default="6692506085", help="Phone number to register (digits only)")
    parser.add_argument("--dataset", type=str, default="pointclickcare data.txt", help="Path to the dataset text file")
    
    args = parser.parse_args()
    line_idx = args.line - 1
    
    print("=" * 60)
    print("JUSTICE FEDERAL CREDIT UNION REGISTRATION")
    print("=" * 60)
    
    # 1. Parse dataset
    try:
        user_info = parse_user_data(args.dataset, line_idx)
        print("[SUCCESS] Successfully parsed dataset:")
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
    phone_part1 = phone[0:3]
    phone_part2 = phone[3:6]
    phone_part3 = phone[6:10]
    print(f"  Email: {email}")
    print(f"  Phone: {phone}")
    
    # Generate plausible CA Driver's License
    dl_number = "F" + user_info["ssn"][0:7]
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
        landing_url = "https://www.jfcu.org/Join/"
        print(f"Navigating to landing page: {landing_url}")
        page.goto(landing_url, wait_until="domcontentloaded")
        time.sleep(3)
        
        # Step 1: Click "JOIN NOW"
        print("Locating and clicking 'JOIN NOW' button...")
        join_link = page.locator("a:has-text('JOIN NOW')").first
        if join_link.count() > 0:
            with page.expect_popup() as popup_info:
                join_link.click()
            app_page = popup_info.value
            app_page.wait_for_load_state("domcontentloaded")
            print("[SUCCESS] Navigated to LoansPQ portal popup: " + app_page.url)
        else:
            raise RuntimeError("Could not find 'JOIN NOW' button on landing page.")
            
        time.sleep(3)
        
        # Step 2: New Member Account Selection
        print("Clicking 'New Member Account'...")
        if not click_visible_btn(app_page, "New Member Account"):
            raise RuntimeError("Failed to click 'New Member Account'")
        time.sleep(3)
        
        # Step 3: Account Type Choice
        print("Clicking 'Personal' account type...")
        if not click_visible_btn(app_page, "Personal"):
            raise RuntimeError("Failed to click 'Personal' account type")
        time.sleep(4)
        
        # Step 4: Eligibility Selection
        print("Selecting 'Concerns of Police Survivors (C.O.P.S.) Supporter'...")
        cops_card = app_page.locator("div#sq_6")
        if cops_card.count() > 0:
            cops_card.click()
            time.sleep(2)
        else:
            raise RuntimeError("Could not find COPS Supporter eligibility card (div#sq_6).")
            
        # Select the acknowledgment option (523) in the newly visible select
        print("Acknowledging COPS donation selection...")
        app_page.evaluate("""() => {
            const el = document.querySelector('select[id*="sq_6"]');
            if (el) {
                el.value = "523";
                el.dispatchEvent(new Event('change', { bubbles: true }));
                if (window.jQuery) {
                    window.jQuery(el).selectmenu('refresh');
                }
            }
        }""")
        time.sleep(1)
        
        # Add Share Savings product (first add button)
        print("Adding Share Savings product...")
        add_btn = app_page.locator("div.btn-add").first
        if add_btn.count() > 0:
            add_btn.click()
            time.sleep(1)
        else:
            print("⚠ Add Share Savings button not found.")
            
        # Click Continue to proceed
        print("Clicking Continue...")
        if not click_visible_btn(app_page, "Continue"):
            raise RuntimeError("Failed to click 'Continue'")
        time.sleep(4)
        
        # Click No Thanks on the Prefill step
        print("Declining prefill option ('No, Thanks')...")
        if not click_visible_btn(app_page, "No, Thanks"):
            print("⚠ 'No, Thanks' prefill declination button not found, continuing...")
        time.sleep(4)
        
        # Step 5: Personal Information Form (Page 5)
        print("\nFilling Personal Information Form...")
        
        # Social Security Number
        fill_react_input(app_page, "#txtSSN1", user_info["ssn"][0:3])
        fill_react_input(app_page, "#txtSSN2", user_info["ssn"][3:5])
        fill_react_input(app_page, "#txtSSN3", user_info["ssn"][5:9])
        
        # Full Name
        fill_react_input(app_page, "#txtFName", user_info["first_name"])
        fill_react_input(app_page, "#txtLName", user_info["last_name"])
        
        # Date of Birth
        fill_react_input(app_page, "#txtDOB1", user_info["dob_month"])
        fill_react_input(app_page, "#txtDOB2", user_info["dob_day"])
        fill_react_input(app_page, "#txtDOB3", user_info["dob_year"])
        
        # Mother's Maiden Name
        fill_react_input(app_page, "#txtMotherMaidenName", "Smith")
        
        # Address
        fill_react_input(app_page, "#txtAddress", user_info["address"])
        fill_react_input(app_page, "#txtZip", user_info["zip"])
        fill_react_input(app_page, "#txtCity", user_info["city"])
        
        # Contact Details
        fill_react_input(app_page, "#txtEmail", email)
        fill_react_input(app_page, "#txtMobilePhone", phone)
        fill_react_input(app_page, "#txtHomePhone", phone)
        
        # Identification details (Driver's License)
        fill_react_input(app_page, "#txtIDCardNumber", dl_number)
        fill_react_input(app_page, "#txtIDDateIssued1", dl_issue_month)
        fill_react_input(app_page, "#txtIDDateIssued2", dl_issue_day)
        fill_react_input(app_page, "#txtIDDateIssued3", dl_issue_year)
        fill_react_input(app_page, "#txtIDDateExpire1", dl_exp_month)
        fill_react_input(app_page, "#txtIDDateExpire2", dl_exp_day)
        fill_react_input(app_page, "#txtIDDateExpire3", dl_exp_year)
        
        # Gross monthly income (Annual $45,000 -> Monthly $3,750)
        fill_react_input(app_page, "#txtGrossMonthlyIncome", "3750")
        
        # Select Dropdowns (jQuery Mobile)
        select_jqm_dropdown(app_page, "#ddlCitizenshipStatus", "USCITIZEN")
        select_jqm_dropdown(app_page, "#ddlState", user_info["state"])
        select_jqm_dropdown(app_page, "#ddlOccupyingStatus", "OWN - FREE AND CLEAR")
        select_jqm_dropdown(app_page, "#ddlOccupancyDurationYear", "10")
        select_jqm_dropdown(app_page, "#ddlOccupancyDurationMonth", "0")
        select_jqm_dropdown(app_page, "#preferredContactMethod", "CELL")
        select_jqm_dropdown(app_page, "#ddlIDCardType", "DRIVERS_LICENSE")
        select_jqm_dropdown(app_page, "#ddlIDState", user_info["state"])
        select_jqm_dropdown(app_page, "#ddlEmploymentStatus", "RETIRED")
        
        # Give jQuery Mobile time to show the dynamic job title input
        time.sleep(1.5)
        
        # Former Profession/Job Title (required when Retired is selected)
        fill_react_input(app_page, "#txtJobTitle", "Clerk")
        
        # Beneficiary and Joint Applicant selections (click No)
        if app_page.locator("#hasBeneficiaryNo").count() > 0:
            app_page.locator("#hasBeneficiaryNo").click()
        if app_page.locator("#idHasCoApplicantNo").count() > 0:
            app_page.locator("#idHasCoApplicantNo").click()
        
        time.sleep(2)
        
        # Click Continue on page 5
        print("Submitting Personal Info page...")
        if not click_visible_btn(app_page, "Continue"):
            raise RuntimeError("Failed to submit Personal Info page.")
        time.sleep(5)
        
        # Step 6: Subsequent Pages Monitoring Loop
        print("\n" + "=" * 50)
        print("Monitoring subsequent pages. The browser is in headed mode.")
        print("If you need to enter OTP or CAPTCHA, please complete it in the browser window.")
        
        script_dir = os.path.dirname(os.path.abspath(__file__))
        filename = os.path.join(script_dir, f"jfcu_details_line_{args.line}.txt")
        funding_handled = False  # Track if funding page has been handled
        for page_num in range(6, 25):
            print(f"\n--- Checking Page State {page_num} ---")
            try:
                save_details(filename, user_info, email, phone, app_page.url, app_page.title(), "Pending Submission")
            except Exception:
                pass
                
            time.sleep(3) # Wait for page rendering
            print(f"Current URL: {app_page.url}")
            print(f"Current Title: {app_page.title()}")
            
            # Save debug files
            html_path = f"debug_jfcu_step_{page_num}.html"
            with open(html_path, "w", encoding="utf-8") as f:
                f.write(app_page.content())
            print(f"Saved step HTML: {html_path}")
            
            screenshot_path = f"debug_jfcu_step_{page_num}.png"
            app_page.screenshot(path=screenshot_path)
            print(f"Saved screenshot: {screenshot_path}")
            
            # Print page inputs
            inputs = dump_page_inputs(app_page)
            print("Visible Inputs:")
            for inp in inputs:
                print(f"  <{inp['tag']}> id='{inp['id']}' name='{inp['name']}' type='{inp['type']}' placeholder='{inp['placeholder']}' text='{inp['text']}' checked={inp['checked']}")
            
            # Handle JFCU Funding Page specifically
            if "Funding" in app_page.title():
                if funding_handled:
                    print("Funding page already handled — waiting for page to advance...")
                    time.sleep(5)
                    continue
                
                print("Funding page detected — switching to Credit Card funding...")
                
                # Dismiss any open Plaid modal first
                plaid_no_thanks = app_page.locator("#btnACHContinue")
                if plaid_no_thanks.count() > 0 and plaid_no_thanks.is_visible():
                    print("Plaid modal open — dismissing...")
                    plaid_no_thanks.click()
                    time.sleep(2)
                
                # Fill the deposit amount input ($5.00 minimum)
                deposit_field_id = None
                for inp in inputs:
                    if 'txtDepositAmount' in inp.get('id', '') or inp.get('placeholder', '') == '$0.00':
                        deposit_field_id = inp['id']
                        break
                        
                if deposit_field_id:
                    print(f"Setting deposit amount to 5.00 on {deposit_field_id}...")
                    fill_react_input(app_page, f"#{deposit_field_id}", "5.00")
                    time.sleep(1)
                
                # Check if CC form is already open (cCreditCardNumber1 visible)
                cc_form_open = app_page.locator("#cCreditCardNumber1").count() > 0
                
                if not cc_form_open:
                    # Use JS to activate Credit Card JQM dialog (avoids visibility issue)
                    print("Activating Credit Card funding dialog via JS...")
                    cc_activated = app_page.evaluate("""
                    () => {
                        // Find the Credit Card option button
                        const ccBtn = document.querySelector('a[dialog-page-id="fundingCreditCard"]');
                        if (!ccBtn) return 'CC_BTN_NOT_FOUND';
                        
                        // Click it using native click (bypasses Playwright visibility check)
                        ccBtn.click();
                        
                        // Also try jQuery Mobile changePage if available
                        if (window.jQuery && window.jQuery.mobile) {
                            try {
                                window.jQuery.mobile.changePage('#fundingCreditCard', {
                                    transition: 'slide',
                                    reverse: false
                                });
                            } catch(e) {}
                        }
                        return 'CC_CLICKED';
                    }
                    """)
                    print(f"CC activation result: {cc_activated}")
                    time.sleep(3)
                    cc_form_open = app_page.locator("#cCreditCardNumber1").count() > 0
                
                app_page.screenshot(path="debug_jfcu_funding_cc.png")
                print("Screenshot: debug_jfcu_funding_cc.png")
                
                # Dump visible inputs after CC dialog should be open
                cc_inputs = dump_page_inputs(app_page)
                print("Visible inputs after CC activation:")
                for inp in cc_inputs:
                    print(f"  <{inp['tag']}> id='{inp['id']}' type='{inp['type']}' placeholder='{inp['placeholder']}'")
                
                # --- Fill Credit Card fields (actual JFCU/MeridianLink field IDs) ---
                # Card number is split into 4 groups of 4 digits
                cc_num_parts = ["4111", "1111", "1111", "1111"]
                for i, part in enumerate(cc_num_parts, 1):
                    fid = f"cCreditCardNumber{i}"
                    loc = app_page.locator(f"#{fid}")
                    if loc.count() > 0:
                        print(f"Filling CC number group {i}: #{fid} = {part}")
                        fill_react_input(app_page, f"#{fid}", part)
                        time.sleep(0.3)
                
                # Expiry: select dropdowns cExpirationDate1 (MM) and cExpirationDate2 (YYYY)
                print("Selecting expiry month (12)...")
                select_jqm_dropdown(app_page, "#cExpirationDate1", "12")
                time.sleep(0.5)
                print("Selecting expiry year (2028)...")
                select_jqm_dropdown(app_page, "#cExpirationDate2", "2028")
                time.sleep(0.5)
                
                # Name on Card (select dropdown, pre-filled with applicant name)
                name_full = f"{user_info['first_name']} {user_info['last_name']}"
                name_loc = app_page.locator("#cNameOnCard")
                if name_loc.count() > 0:
                    current_name = app_page.evaluate("() => { const el = document.querySelector('#cNameOnCard'); return el ? el.value : ''; }")
                    print(f"Name on card current value: '{current_name}'")
                    if not current_name or current_name == name_full:
                        print("Name on card already set or will be left as-is.")
                    else:
                        select_jqm_dropdown(app_page, "#cNameOnCard", name_full)
                
                time.sleep(1)
                app_page.screenshot(path="debug_jfcu_funding_cc_filled.png")
                print("Screenshot: debug_jfcu_funding_cc_filled.png")
                
                # Click the Continue button inside the active CC dialog
                print("Clicking Continue inside Credit Card dialog...")
                cc_continue_clicked = app_page.evaluate("""
                () => {
                    // Find the Continue button in the active JQM page/dialog
                    const activePages = document.querySelectorAll('[data-role="page"].ui-page-active, [data-role="dialog"].ui-page-active');
                    for (const pg of activePages) {
                        const btn = pg.querySelector('a.div-continue-button, a#btnContinue, a[onclick*="validate"]');
                        if (btn) {
                            btn.click();
                            return 'CONTINUE_CLICKED_IN_ACTIVE_PAGE';
                        }
                    }
                    // Fallback: click any visible Continue button
                    const allBtns = Array.from(document.querySelectorAll('a, button'));
                    const contBtn = allBtns.find(b => {
                        const rect = b.getBoundingClientRect();
                        return rect.width > 0 && rect.height > 0 &&
                               (b.textContent || '').trim().toLowerCase() === 'continue';
                    });
                    if (contBtn) {
                        contBtn.click();
                        return 'CONTINUE_CLICKED_FALLBACK';
                    }
                    return 'NO_CONTINUE_FOUND';
                }
                """)
                print(f"CC Continue result: {cc_continue_clicked}")
                time.sleep(5)
                
                funding_handled = True
                print("Funding step completed — monitoring for next page...")
            
            # Auto-fill helpers for compliance/review fields
            filled_any = False
            
            # Auto-select standard dropdowns if present
            dropdowns = {
                "reviewpage_ddl_aq_verafinmobileremotedeposit": "No",
                "reviewpage_ddl_aq_verafinnonuswiretransactions": "No",
                "reviewpage_ddl_aq_verafinnonuselectronictransactions": "No",
                "reviewpage_ddl_aq_verafinpoliticallyexposedperson": "No",
                "reviewpage_ddl_aq_verafinfamilyorassociateofpep": "No",
                "reviewpage_ddl_aq_verafinembassyconsulateormission": "No",
                "reviewpage_ddl_aq_memberreferral": "No",
                "reviewpage_ddl_aq_howdidyouhearaboutjusticefederal": "Other",
                "reviewpage_ddl_aq_justicefederalbranchlist": "Justice Federal Headquarters - Chantilly, VA",
                "reviewpage_ddl_aq_ssnortinbackupwithholding": "No",
                "reviewpage_ddl_aq_fatcareporting": "No"
            }
            
            for select_id, val in dropdowns.items():
                selector = f"select#{select_id}"
                loc = app_page.locator(selector)
                if loc.count() > 0 and loc.is_visible():
                    print(f"Auto-selecting {select_id} = {val}...")
                    select_jqm_dropdown(app_page, selector, val)
                    filled_any = True
                    
            # Check all visible checkboxes (Terms, disclosures, certifications)
            # Find all checkboxes that are visible and NOT yet checked
            for inp in inputs:
                if inp['tag'] == 'input' and inp['type'] == 'checkbox' and not inp['checked']:
                    cb_id = inp['id']
                    if cb_id:
                        print(f"Checking agreement checkbox: {cb_id}...")
                        app_page.locator(f"#{cb_id}").click()
                        filled_any = True
            
            # Check for Next / Continue / Submit button
            submit_btn = app_page.locator("button[id*=submit], button[id*=continue], button[id*=apply], input[type=submit], input[value*=Continue], input[value*=Submit], a:has-text('Continue'), a:has-text('Submit'), a:has-text('I Agree'), button:has-text('Continue'), button:has-text('Submit')").first
            
            if submit_btn.count() > 0 and submit_btn.is_visible():
                print("Clicking next button...")
                submit_btn.click()
                time.sleep(6)
            else:
                # Fallback to text matching click helper
                print("Attempting fallback continue button click...")
                if click_visible_btn(app_page, "Continue") or click_visible_btn(app_page, "Submit") or click_visible_btn(app_page, "I Agree"):
                    time.sleep(6)
                else:
                    print("⚠ No visible continue/submit buttons found. Waiting for manual navigation...")
                    time.sleep(5)
            
            # Check if url contains success / declined / outcome indicators
            curr_url = app_page.url.lower()
            curr_body = app_page.evaluate("() => document.body.innerText").lower()
            
            if "declined" in curr_url or "decline" in curr_url or "denied" in curr_url or "deny" in curr_url or "denied" in curr_body or "declined" in curr_body:
                print("[OUTCOME] Application outcome reached: Denied/Declined")
                save_details(filename, user_info, email, phone, app_page.url, app_page.title(), "Denied/Declined")
                break
            elif "success" in curr_url or "approve" in curr_url or "approve" in curr_body or "welcome" in curr_body or "congratulations" in curr_body:
                print("[OUTCOME] Application outcome reached: Approved!")
                save_details(filename, user_info, email, phone, app_page.url, app_page.title(), "Approved")
                break
            elif "pending" in curr_url or "review" in curr_url or "review" in curr_body or "pending" in curr_body:
                print("[OUTCOME] Application outcome reached: Under Review / Pending")
                save_details(filename, user_info, email, phone, app_page.url, app_page.title(), "Under Review / Pending")
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
