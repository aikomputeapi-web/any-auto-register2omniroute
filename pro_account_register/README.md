# Professional Account Registration Scripts
## Usage Guide & Instructions

This folder contains automated Playwright scripts for programmatically registering savings and checking accounts at major financial institutions using bulk data profiles stored in a pipe-delimited text file (compatible with CSV tools).

---

## Table of Contents

1. [Prerequisites & Setup](#prerequisites--setup)
2. [Data Profile Format (CSV/Pipe-Delimited)](#data-profile-format-csvpipe-delimited)
3. [Automation Scripts Overview](#automation-scripts-overview)
4. [Step-by-Step Usage Instructions](#step-by-step-usage-instructions)
5. [Expected Output Files](#expected-output-files)
6. [Manual Steps & Human-in-the-Loop Requirements](#manual-steps--human-in-the-loop-requirements)
7. [Troubleshooting](#troubleshooting)

---

## Prerequisites & Setup

### 1. Conda Environment

All scripts must be run inside the `any-auto-register` conda environment:

```bash
conda activate any-auto-register
```

### 2. Install Dependencies

From the project root directory (`any-auto-register/`):

```bash
pip install -r requirements.txt
playwright install chromium
```

### 3. Verify the Core Module Is Accessible

All scripts auto-add the root directory to `sys.path`. Running them from the **project root** (not from inside `pro_account_register/`) is recommended:

```bash
# Always run from project root:
cd c:\Users\Administrator\coding\any-auto-register
python pro_account_register/register_jfcu.py --line 39
```

---

## Data Profile Format (CSV/Pipe-Delimited)

### File: `pointclickcare data.txt`

Each line in the dataset file represents one person's profile. Lines use the **pipe (`|`) delimiter** and are **1-indexed** when referenced by the `--line` argument.

### Column Schema

| Col # | Field Name    | Format/Notes                            | Example          |
|-------|---------------|-----------------------------------------|------------------|
| 1     | `FirstName`   | String                                  | `Robert`         |
| 2     | `LastName`    | String                                  | `Oliver`         |
| 3     | `Address`     | Street number + street name             | `24647 Mohr`     |
| 4     | `City`        | String                                  | `Hayward`        |
| 5     | `State`       | 2-letter state abbreviation             | `CA`             |
| 6     | `ZipCode`     | 5-digit zip                             | `94545`          |
| 7     | `DateOfBirth` | `MM/DD/YYYY` format                     | `04/06/1938`     |
| 8     | `SSN`         | 9-digit SSN, dashes optional            | `545-50-5372`    |

### Example Lines (Raw Format)

```
Robert|Oliver|24647 Mohr|Hayward|CA|94545|04/06/1938|545-50-5372
Shirley|Obrine|16857 Clinton|San Leandro|CA|94578|12/04/1935|553-56-9291
```

### Notes on Data Format

- Lines are **1-indexed** in `--line` argument (line 1 = first line of file)
- SSN dashes are automatically stripped by the parser
- Scripts auto-generate a **CA Driver's License number** from the SSN prefix: `F` + first 7 SSN digits
- Scripts auto-generate a **plausible gross monthly income** of `$3,750` (annual $45,000)
- The **email** and **phone** arguments are passed separately (not in the dataset file) since they may vary per run

---

## Automation Scripts Overview

### Script 1: American Express High Yield Savings

| Field       | Value                                                          |
|-------------|----------------------------------------------------------------|
| **File**    | `pro_account_register/register_amex.py`                        |
| **Account** | AMEX High Yield Savings Account                                |
| **URL**     | `https://www.americanexpress.com/en-us/banking/personal/savings/apply/psa-begin` |
| **Output**  | `pro_account_register/registration_results/amex_details_line_<N>.txt` |

**What it automates:**
1. Navigates to the AMEX savings application landing page
2. Clicks "Create New Account" to begin a fresh application
3. Fills in: SSN, first/last name, date of birth, email, phone, address, employment status
4. Handles "Create Your User ID & Password" page (generates login credentials)
5. Progresses through disclosure/agreement pages (auto-checks checkboxes)
6. Monitors for success/decline/pending outcome

---

### Script 2: U.S. Bank Smartly Checking

| Field       | Value                                                           |
|-------------|-----------------------------------------------------------------|
| **File**    | `pro_account_register/register_usbank.py`                       |
| **Account** | U.S. Bank Smartly® Checking Account                             |
| **URL**     | `https://www.usbank.com/bank-accounts/checking-accounts/bank-smartly-checking.html` |
| **Output**  | `pro_account_register/registration_results/usbank_details_line_<N>.txt` |

**What it automates:**
1. Navigates to the U.S. Bank Smartly Checking product page
2. Clicks "Open an account" and selects "I'm new to U.S. Bank"
3. Fills personal information: SSN, name, DOB, address, phone, email, citizenship
4. Fills employment/income information
5. Fills ID verification details (driver's license)
6. Handles disclosure agreements and terms acceptance
7. Monitors for approval/decline/pending decision pages

---

### Script 3: Justice Federal Credit Union (JFCU) Membership

| Field       | Value                                                           |
|-------------|-----------------------------------------------------------------|
| **File**    | `pro_account_register/register_jfcu.py`                         |
| **Account** | JFCU Share Savings Account (new membership)                     |
| **URL**     | `https://www.jfcu.org/Join/`                                    |
| **Output**  | `pro_account_register/registration_results/jfcu_details_line_<N>.txt` |

**What it automates:**
1. Navigates to JFCU Join portal and clicks "JOIN NOW" (opens LoansPQ popup)
2. Selects "New Member Account" → "Personal"
3. Selects eligibility: **Concerns of Police Survivors (C.O.P.S.) Supporter** (div#sq_6)
4. Acknowledges COPS donation and adds Share Savings product
5. Declines the auto-fill/prefill option ("No, Thanks")
6. Fills the full Personal Info form (Page 5):
   - SSN (3-part entry: `txtSSN1`, `txtSSN2`, `txtSSN3`)
   - Name, DOB, Mother's Maiden Name
   - Address (street, zip, city)
   - Phone (mobile + home), Email
   - Driver's License (number, issued date, expiry date)
   - Gross Monthly Income
   - Dropdown selections: citizenship, state, housing status, employment, contact preference
   - Employment status: **RETIRED** + job title (triggers dynamic form refresh)
   - Beneficiary: **No** (`a#hasBeneficiaryNo`)
   - Joint Applicant: **No** (`a#idHasCoApplicantNo`)
7. Handles Funding page: selects Credit Card funding method, fills CC details
8. Handles subsequent review/compliance pages (auto-selects dropdowns, checks agreements)
9. Monitors for approval/decline/pending outcome

---

### Script 4: Stripe Merchant Account Registration

| Field       | Value                                                           |
|-------------|-----------------------------------------------------------------|
| **File**    | `pro_account_register/register_stripe.py`                       |
| **Account** | Stripe Merchant / Payments Account                              |
| **URL**     | `https://dashboard.stripe.com/register`                         |
| **Output**  | `pro_account_register/registration_results/stripe_results_line_<N>.txt` (specific) and `stripe_results.txt` (unified) |

**What it automates:**
1. Navigates to Stripe registration page.
2. Fills in account registration credentials (email, name, password).
3. Automates the onboarding flow page-by-page.
4. Auto-fills generated or pre-generated AI SaaS business details: DBA, Business Website, Product Description, Statement Descriptor, etc.
5. Auto-fills representative personal details, SSN last 4 or full, DOB, address, and bank routing/account details.
6. Acknowledges tax declarations and terms checkbox, submitting the merchant registration.
7. Logs credentials, status, and final outcomes.

---

## Step-by-Step Usage Instructions

### Running a Script for a Specific Profile

```bash
# General syntax (run from project root):
python pro_account_register/register_<institution>.py --line <LINE> --email <EMAIL> --phone <PHONE>
```

### Full Example: Row 39 (Robert Oliver)

```bash
# American Express (auto-defaults to robertoliver@audioplexdesigns.com)
python pro_account_register/register_amex.py --line 39 --phone 6692506085

# U.S. Bank (auto-defaults to robertoliver@audioplexdesigns.com)
python pro_account_register/register_usbank.py --line 39 --phone 6692506085

# Justice Federal Credit Union (auto-defaults to robertoliver@audioplexdesigns.com)
python pro_account_register/register_jfcu.py --line 39 --phone 6692506085
```

### All Available Arguments

| Argument    | Default Value                | Description                                     |
|-------------|------------------------------|-------------------------------------------------|
| `--line`    | `1`                          | 1-based line number from the dataset file       |
| `--email`   | `firstname+lastname@audioplexdesigns.com` | Email address to use (dynamically derived from name if omitted) |
| `--phone`   | `6692506085`                 | 10-digit phone number (digits only)             |
| `--dataset` | `pointclickcare data.txt`    | Path to the pipe-delimited dataset file         |

### Running Multiple Profiles in Sequence

```bash
# Loop over lines 39 through 50 for JFCU:
for ($i = 39; $i -le 50; $i++) {
    python pro_account_register/register_jfcu.py --line $i --phone 6692506085
    Start-Sleep -Seconds 10
}
```

---

## Expected Output Files

All registration scripts save their outcomes inside the `pro_account_register/registration_results/` folder:

```
pro_account_register/registration_results/amex_details_line_39.txt
pro_account_register/registration_results/usbank_details_line_39.txt
pro_account_register/registration_results/jfcu_details_line_39.txt
pro_account_register/registration_results/stripe_results_line_39.txt
pro_account_register/registration_results/stripe_results.txt
```

- **Line-based files** (`<institution>_details_line_<N>.txt` or `stripe_results_line_<N>.txt`): Save the registration details of the specific run matching the dataset row number.
- **Stripe results file** (`stripe_results.txt`): A unified transaction log listing all Stripe merchant registrations, credentials, and outcome statuses in one place.

### Output File Format

```
Justice Federal Credit Union Account Details
==================================================
Name: Robert Oliver
Address: 24647 Mohr, Hayward, CA 94545
DOB: 04/06/1938
SSN: 545505372
Email: robertoliver@audioplexdesigns.com
Phone: 6692506085
--------------------------------------------------
Status: Approved
Final URL: https://app.loanspq.com/...
Title: Confirmation
Timestamp: 2026-06-02 22:15:43
```

**Status values:**
- `Approved` — Application was accepted
- `Denied/Declined` — Application was rejected
- `Under Review / Pending` — Application queued for manual review
- `Pending Submission` — Script did not reach a final outcome page (check browser)

---

## Business Profile Pre-Generation & Stripe Usage

To avoid calling the LLM at Stripe registration runtime, you can generate business profiles ahead of time and load them directly.

### 1. Generating Business Profiles Ahead of Time

Run the `generate_profiles.py` script from the project root. This calls OpenRouter/Gemini (or falls back to rule-based random generation) to create unique AI SaaS businesses:

```bash
# Generate 5 business profiles
python pro_account_register/generate_profiles.py --count 5
```

- **Output Directory**: Profiles are saved under `pro_account_register/generated_profiles/` as individual text files (e.g., `profile_neuroflow.txt`).
- **Profiles Index**: A unified Markdown index page is automatically updated at `pro_account_register/generated_profiles/business_profiles.md` with links and summaries of all pre-generated profiles.

### 2. Using Pre-Generated Profiles in Stripe Registration

Provide the path of a generated profile to the `--profile` argument of the Stripe registration script. When a custom profile is provided (or when `--use-pregenerated` is set), the script automatically skips LLM calls and registers using the pre-generated profile's data:

```bash
python pro_account_register/register_stripe.py --line 39 --phone 6692506085 --profile pro_account_register/generated_profiles/profile_neuroflow.txt
```

---

## Manual Steps & Human-in-the-Loop Requirements

All scripts run in **headed mode** (visible browser window). Some situations require manual intervention:

### OTP / SMS Verification

Many financial institutions send a one-time passcode (OTP) to the phone number provided. When prompted:

1. Watch the browser window for an OTP entry screen
2. Check the phone number `6692506085` for the SMS code
3. Type it directly into the browser window
4. The script's page-monitoring loop will detect the page advance and continue

### CAPTCHA Challenges

If a CAPTCHA (reCAPTCHA, hCAPTCHA, etc.) appears:

1. Solve the CAPTCHA manually in the browser window
2. The script will resume once it detects the page has moved forward

### Funding / Payment Information

- **JFCU** requires a minimum $5.00 deposit for the Share Savings account
- The script handles this by selecting Credit Card as the funding method and filling in CC details
- If the portal requires Plaid bank verification, click "No Thanks" in the browser to use manual transfer

### Identity Verification (ID Upload)

Some portals may request a photo ID upload or a selfie for identity verification. If this occurs:
1. The script will pause (no visible continue button will match)
2. Complete the ID upload or verification step manually in the browser
3. The monitoring loop will detect when you progress to the next page

---

## Troubleshooting

### Script Errors

| Error                            | Likely Cause                       | Fix                                              |
|----------------------------------|------------------------------------|--------------------------------------------------|
| `ModuleNotFoundError`            | Wrong working directory            | Run from `any-auto-register/` root               |
| `FileNotFoundError: dataset`     | Dataset file path wrong            | Use `--dataset` with correct path                |
| `Page.evaluate: eval is disabled`| Site patched `eval`                | Script patches `window.eval` — ensure init script is present |
| Script loops on same page        | A required field not filled        | Check debug screenshots (`debug_jfcu_step_N.png`) |
| Browser closes immediately       | Exception in automation            | Read the error message printed to console        |

### Debug Files

Every script saves debug artifacts on each page iteration:

```
debug_jfcu_step_6.png   ← Screenshot of page 6
debug_jfcu_step_6.html  ← Full HTML of page 6
debug_jfcu_step_7.png
debug_jfcu_step_7.html
...
```

These files are saved in the **project root directory** and are invaluable for diagnosing what the browser sees at each step.

### Checking Script Progress

Watch the console output. Each step is printed:

```
============================================================
JUSTICE FEDERAL CREDIT UNION REGISTRATION
============================================================
[SUCCESS] Successfully parsed dataset:
  Name: Robert Oliver
  ...

Navigating to landing page: https://www.jfcu.org/Join/
Locating and clicking 'JOIN NOW' button...
[SUCCESS] Navigated to LoansPQ portal popup: ...

Filling Personal Information Form...
Submitting Personal Info page...

--- Checking Page State 6 ---
Current URL: https://app.loanspq.com/...
Current Title: Funding
Funding page detected...
```
