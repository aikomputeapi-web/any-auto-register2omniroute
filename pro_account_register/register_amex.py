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
    Parse a specific line of dataset:
    Shirley|Obrine|16857 clinton|San Leandro|CA|94578|12/04/1935|553-56-9291
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

# DOM manipulation helpers utilizing page.evaluate for maximum anti-bot bypass

def wait_for_element_by_id(page, element_id, timeout=30):
    start = time.time()
    while time.time() - start < timeout:
        isPresent = page.evaluate("id => !!document.getElementById(id)", element_id)
        if isPresent:
            return True
        time.sleep(0.5)
    return False

def fill_react_input(page, element_id, value):
    js_fn = """
    ([id, val]) => {
        const el = document.getElementById(id);
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
    return page.evaluate(js_fn, (element_id, value))

def select_dropdown_option(page, element_id, value):
    js_fn = """
    ([id, val]) => {
        const el = document.getElementById(id);
        if (el) {
            el.value = val;
            el.dispatchEvent(new Event('change', { bubbles: true }));
            return true;
        }
        return false;
    }
    """
    return page.evaluate(js_fn, (element_id, value))

def click_element_by_id(page, element_id):
    js_fn = """
    id => {
        const el = document.getElementById(id);
        if (el) {
            el.click();
            return true;
        }
        return false;
    }
    """
    return page.evaluate(js_fn, element_id)

def main():
    parser = argparse.ArgumentParser(description="Automate AMEX High Yield Savings Account Application.")
    parser.add_argument("--line", type=int, default=1, help="The 1-based line number of user data to register (default: 1)")
    parser.add_argument("--email", type=str, default=None, help="Email address to register (defaults to firstname+lastname@audioplexdesigns.com)")
    parser.add_argument("--phone", type=str, default="6692506085", help="Phone number to register (digits only)")
    parser.add_argument("--dataset", type=str, default="pointclickcare data.txt", help="Path to the dataset text file")
    
    args = parser.parse_args()
    line_idx = args.line - 1 # Convert to 0-based index
    
    print("=" * 60)
    print("AMERICAN EXPRESS HIGH YIELD SAVINGS ACCOUNT REGISTRATION")
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
    
    # Protect native eval from being disabled by the website's scripts
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
        url = "https://www.americanexpress.com/en-us/banking/personal/savings/apply/psa-begin?product=highYieldSavings&intlink=us-acq-consumer-banking-HYSA-openanaccount-hero&eep=81153&extlink=as%3Dsearch_br%3DGGL%3D19155272099_143460594399_18379560748_686081261958"
        print(f"Navigating to URL: {url}")
        page.goto(url, wait_until="domcontentloaded")
        time.sleep(5)
        
        # Step 1: Start Application
        print("Waiting for 'Create New Account' button...")
        if wait_for_element_by_id(page, "beginCreateNewAccount", timeout=15):
            click_element_by_id(page, "beginCreateNewAccount")
            print("✓ Clicked 'Create New Account' button.")
        else:
            print("⚠ 'Create New Account' button not found. Please click it manually.")
            
        # Step 2: Personal Information Page
        print("\nWaiting for Personal Information fields to load...")
        if wait_for_element_by_id(page, "firstName", timeout=30):
            print("Filling Personal Information...")
            fill_react_input(page, "firstName", user_info["first_name"])
            fill_react_input(page, "lastName", user_info["last_name"])
            # Format DOB as MMDDYYYY for input mask
            dob_numeric = user_info["dob_month"] + user_info["dob_day"] + user_info["dob_year"]
            fill_react_input(page, "dateOfBirth", dob_numeric)
            fill_react_input(page, "taxIdentificationNumber", user_info["ssn"])
            fill_react_input(page, "phone", phone)
            fill_react_input(page, "email", email)
            select_dropdown_option(page, "phoneType", "MOBILE")
            
            print("Submitting Personal Info...")
            click_element_by_id(page, "submit-button")
            print("✓ Submitted Personal Information.")
        else:
            raise RuntimeError("Personal Information fields failed to load.")
            
        # Step 3: Additional Information Page
        print("\nWaiting for Additional Information fields to load...")
        if wait_for_element_by_id(page, "line1", timeout=30):
            print("Filling Additional Information...")
            fill_react_input(page, "line1", user_info["address"])
            fill_react_input(page, "city", user_info["city"])
            fill_react_input(page, "postalCode", user_info["zip"])
            fill_react_input(page, "amount", "45000") # Estimated Annual Income
            select_dropdown_option(page, "region", user_info["state"])
            select_dropdown_option(page, "employmentStatus", "RETIRED")
            
            print("Submitting Additional Info...")
            click_element_by_id(page, "submit-button")
            print("✓ Submitted Additional Information.")
        else:
            raise RuntimeError("Additional Information fields failed to load.")
            
        # Step 4: Tax Withholding Page
        print("\nWaiting for Tax Withholding page to load...")
        if wait_for_element_by_id(page, "noTaxWithholdings", timeout=30):
            print("Acknowledging no backup withholding...")
            click_element_by_id(page, "noTaxWithholdings")
            click_element_by_id(page, "submit-button")
            print("✓ Tax withholding acknowledged.")
        else:
            raise RuntimeError("Tax withholding page failed to load.")
            
        # Step 5: Joint Owner Page
        print("\nWaiting for Joint Owner selection page...")
        if wait_for_element_by_id(page, "noJointUser", timeout=30):
            print("Selecting 'No joint owner'...")
            # noJointUser is usually checked by default, so just submit
            click_element_by_id(page, "submit-button")
            print("✓ Joint owner preference submitted.")
        else:
            raise RuntimeError("Joint owner selection page failed to load.")
            
        # Step 6: Terms and Conditions Page
        print("\nWaiting for Terms and Conditions page...")
        if wait_for_element_by_id(page, "electronicDeliveryConsentTerms", timeout=30):
            print("Consenting to terms...")
            click_element_by_id(page, "electronicDeliveryConsentTerms")
            print("Submitting final application...")
            click_element_by_id(page, "submit-button")
            print("✓ Application submitted successfully!")
        else:
            raise RuntimeError("Terms page failed to load.")
            
        # Step 7: Decision Processing
        print("\nWaiting for decision screen (this can take 15-20 seconds)...")
        time.sleep(15)
        
        # Capture final outcome
        title = page.title()
        curr_url = page.url
        body_text = page.evaluate("() => document.body.innerText")
        
        print("\n" + "=" * 50)
        print("APPLICATION SUBMITTED - OUTCOME SCREEN")
        print("=" * 50)
        print(f"Title: {title}")
        print(f"URL: {curr_url}")
        
        status_line = "Unknown Outcome"
        if "pending" in curr_url or "under review" in body_text.lower() or "pending" in body_text.lower():
            status_line = "Under Review (Pended)"
            print("\nOutcome: Application is Under Review / Pending.")
        elif "approved" in body_text.lower() or "welcome" in body_text.lower():
            status_line = "Approved"
            print("\nOutcome: Application Approved!")
        else:
            print("\nOutcome: Unknown or manual action required.")
            
        # Save output details
        script_dir = os.path.dirname(os.path.abspath(__file__))
        results_dir = os.path.join(script_dir, "registration_results")
        os.makedirs(results_dir, exist_ok=True)
        filename = os.path.join(results_dir, f"amex_details_line_{args.line}.txt")
        with open(filename, "w", encoding="utf-8") as f:
            f.write(f"AMEX Savings Account Application Details (Dataset Row {args.line})\n")
            f.write("=" * 50 + "\n")
            f.write(f"Name: {user_info['first_name']} {user_info['last_name']}\n")
            f.write(f"Address: {user_info['address']}, {user_info['city']}, {user_info['state']} {user_info['zip']}\n")
            f.write(f"DOB: {user_info['dob_str']}\n")
            f.write(f"SSN: {user_info['ssn']}\n")
            f.write(f"Email: {email}\n")
            f.write(f"Phone: {phone}\n")
            f.write("-" * 50 + "\n")
            f.write(f"Status: {status_line}\n")
            f.write(f"Submission URL: {curr_url}\n")
            f.write(f"Timestamp: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
            
        print(f"✓ Saved account details to file: {os.path.abspath(filename)}")
        print("=" * 50)
        
        # Keep browser open briefly for inspection
        print("Keeping browser open for 15 seconds for manual inspection...")
        time.sleep(15)
        
    except Exception as e:
        print(f"\n✗ Error during application automation: {e}")
    finally:
        executor.close()
        print("Browser closed.")

if __name__ == "__main__":
    main()
