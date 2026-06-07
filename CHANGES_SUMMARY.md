# Changes Summary

## Overview
Modified the registration system to:
1. Use USA location information in browser profiles
2. Format CatchMail email addresses as `firstnamelastname@catchmail.io` instead of random strings

## Files Modified

### 1. `core/catchmail_mailbox.py`
- **Modified `__init__` method**: Added `first_name` and `last_name` parameters
- **Modified `get_email` method**: Changed email generation logic to use `firstnamelastname` format when names are provided, otherwise falls back to random generation

### 2. `core/base_mailbox.py`
- **Modified `create_mailbox` function**: Updated the catchmail provider case to pass `first_name` and `last_name` from the extra config to CatchMailMailbox

### 3. `core/executors/playwright.py`
- **Modified `_init` method**: Added USA-specific browser context configuration with stealth measures:
  - Locale: `en-US`
  - Timezone: `America/Los_Angeles` (Pacific Time)
  - Geolocation: San Francisco, California coordinates (37.7749, -122.4194)
  - Permissions: Enabled geolocation
  - **Randomized User Agent**: Chrome versions 126-131 with matching client hints
  - **Randomized Viewport**: Common resolutions (1920x1080, 1366x768, 1536x864, 1440x900, etc.)
  - **Randomized Hardware**: CPU cores (4-16) and RAM (4-32GB) with realistic distributions
  - **Stealth Features**:
    - Disabled automation flags (`--disable-blink-features=AutomationControlled`)
    - Hidden `navigator.webdriver` property
    - Proper User-Agent with matching `sec-ch-ua` client hints
    - Realistic HTTP headers (Accept-Language, Sec-Fetch-*, etc.)
    - Chrome runtime object injection
    - Modified navigator.plugins and navigator.languages
    - Permissions API spoofing
    - Canvas and Audio fingerprinting protection
    - WebGL vendor/renderer spoofing
    - Navigator.userAgentData API with high entropy values

### 4. `core/user_agent_generator.py` (NEW)
- **Created UserAgentGenerator class**: Generates realistic Chrome user agents
  - Recent Chrome versions (126.0.0.0 - 131.0.0.0)
  - Matching client hints headers (sec-ch-ua, sec-ch-ua-full-version-list)
  - Platform version randomization
  - Viewport randomization with weighted distribution
  - Hardware specs randomization (CPU cores, RAM)

### 4. `api/tasks.py`
- **Modified `_build_mailbox` function**: Added `first_name` and `last_name` parameters and passes them through the extra config
- **Modified `_do_one` function**: Generates random names using `generate_random_name()` before creating the mailbox and passes them to `_build_mailbox`

## How It Works

1. When a registration task starts, the system generates a random first and last name using the existing `generate_random_name()` function from `platforms/chatgpt/utils.py`

2. These names are passed to the mailbox creation function

3. For CatchMail provider:
   - The email is formatted as `{firstname}{lastname}@catchmail.io` (all lowercase)
   - Example: If names are "John" and "Smith", email becomes `johnsmith@catchmail.io`

4. Browser profiles are configured with USA location:
   - US English locale
   - Pacific timezone (Los Angeles)
   - San Francisco, California geolocation coordinates
   - Geolocation permission enabled

## Testing

To test these changes:
1. Start a registration task using CatchMail as the email provider
2. Verify the generated email follows the `firstnamelastname@catchmail.io` format
3. Check browser fingerprint shows USA location information
