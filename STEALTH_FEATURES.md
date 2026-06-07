# Browser Stealth Features

## Overview
The Playwright executor now includes comprehensive stealth measures to avoid bot detection.

## Implemented Stealth Techniques

### 1. **WebDriver Detection Bypass**
- ✅ Hides `navigator.webdriver` property
- ✅ Removes `--enable-automation` flag
- ✅ Disables `AutomationControlled` blink features
- ✅ Removes Playwright-specific window properties (`__playwright`, `__pw_manual`, `__PW_inspect`)

### 2. **User Agent Randomization** 🆕
- ✅ **Random Chrome versions**: 126.0.0.0 - 131.0.0.0 (last 6 months)
- ✅ **Matching client hints**: sec-ch-ua, sec-ch-ua-full-version-list, sec-ch-ua-platform-version
- ✅ **Navigator.userAgentData API**: Complete implementation with getHighEntropyValues()
- ✅ **Consistent fingerprint**: All UA-related properties match perfectly
- ✅ **Realistic distribution**: More common versions weighted higher
- ✅ **Full version list**: Includes Chrome, Chromium, and Not_A Brand

### 3. **Viewport & Hardware Randomization** 🆕
- ✅ **Random viewports**: 
  - 1920x1080 (40% - most common)
  - 1366x768 (25% - second most common)
  - 1536x864 (15% - common laptop)
  - 1440x900 (10% - MacBook-like)
  - 1280x720 (5% - HD)
  - 1600x900 (5% - 16:9)
- ✅ **Random CPU cores**: 4, 6, 8, 12, 16 (8 cores most common at 40%)
- ✅ **Random RAM**: 4GB, 8GB, 16GB, 32GB (8GB most common at 50%)
- ✅ **Consistent screen properties**: Viewport matches screen size
- ✅ **Logged on startup**: Shows fingerprint details in logs

### 4. **Navigator Properties Spoofing**
- ✅ **Plugins**: Realistic Chrome PDF Plugin, PDF Viewer, and Native Client
- ✅ **MimeTypes**: Proper PDF and NaCl mime types
- ✅ **Languages**: `['en-US', 'en']`
- ✅ **Platform**: `Win32`
- ✅ **HardwareConcurrency**: 8 CPU cores
- ✅ **DeviceMemory**: 8 GB RAM
- ✅ **Connection**: 4G network with realistic RTT and downlink

### 3. **Chrome Runtime Spoofing**
- ✅ Injects `window.chrome` object with app, runtime, loadTimes, and csi properties
- ✅ Makes chrome object appear native

### 4. **Canvas Fingerprinting Protection**
- ✅ Modifies canvas `toDataURL()` output with subtle pixel manipulation
- ✅ Makes canvas fingerprint unique per session
- ✅ Prevents consistent canvas fingerprinting

### 5. **Audio Fingerprinting Protection**
- ✅ Wraps AudioContext oscillator methods
- ✅ Prevents audio fingerprinting detection

### 6. **WebGL Fingerprinting Protection**
- ✅ Spoofs WebGL vendor: "Intel Inc."
- ✅ Spoofs WebGL renderer: "Intel Iris OpenGL Engine"
- ✅ Prevents WebGL-based fingerprinting

### 7. **User Agent Randomization** ✅ NEW
- ✅ **Random Chrome versions**: 126-131 (last 6 months)
- ✅ **Matching client hints**: sec-ch-ua, sec-ch-ua-full-version-list, sec-ch-ua-platform-version
- ✅ **Navigator.userAgentData API**: Complete with getHighEntropyValues()
- ✅ **Consistent fingerprint**: All UA-related properties match
- ✅ **Weighted randomization**: More common versions appear more frequently

### 8. **Viewport & Hardware Randomization** ✅ NEW
- ✅ **Random viewports**: 1920x1080 (40%), 1366x768 (25%), 1536x864 (15%), etc.
- ✅ **Random CPU cores**: 4-16 cores with realistic distribution (8 cores most common)
- ✅ **Random RAM**: 4-32GB with realistic distribution (8GB most common)
- ✅ **Consistent screen properties**: Viewport matches screen size

### 9. **Screen & Viewport Randomization**
- ✅ Randomizes viewport dimensions (1920x1080, 1366x768, 1536x864, 1440x900)
- ✅ Matches screen size to viewport
- ✅ Sets realistic color depth (24-bit)
- ✅ Proper pixel depth

### 8. **Timezone Consistency**
- ✅ Sets timezone to `America/Los_Angeles` (PST/PDT)
- ✅ Overrides `Date.prototype.getTimezoneOffset()` to return 420 minutes
- ✅ Patches `Intl.DateTimeFormat` for timezone consistency
- ✅ Prevents timezone leaks

### 9. **Geolocation**
- ✅ San Francisco, California coordinates (37.7749, -122.4194)
- ✅ Geolocation permission granted
- ✅ Consistent with timezone

### 10. **Battery API Spoofing**
- ✅ Mocks `navigator.getBattery()`
- ✅ Returns realistic battery data (charging, full battery)

### 11. **Permissions API**
- ✅ Spoofs notification permissions
- ✅ Returns realistic permission states

### 12. **HTTP Headers**
- ✅ Realistic `Accept-Language`: `en-US,en;q=0.9`
- ✅ Proper `Accept-Encoding`: `gzip, deflate, br`
- ✅ Complete `Accept` header with image formats
- ✅ `Sec-Fetch-*` headers (Site, Mode, User, Dest)
- ✅ `sec-ch-ua` client hints headers
- ✅ `Upgrade-Insecure-Requests`

### 13. **Function.prototype.toString Protection**
- ✅ Overrides toString to hide proxy behavior
- ✅ Makes spoofed functions appear native

### 14. **Mouse Movement Tracking**
- ✅ Tracks mouse movements to simulate human behavior
- ✅ Can be used for behavioral analysis

### 15. **Launch Arguments**
```
--disable-blink-features=AutomationControlled
--disable-dev-shm-usage
--no-sandbox
--disable-setuid-sandbox
--disable-web-security
--disable-features=IsolateOrigins,site-per-process
--disable-site-isolation-trials
--disable-infobars
--window-position=0,0
--ignore-certificate-errors
```

## Detection Test Results

Test your stealth on these sites:

### ✅ Should Pass:
- **bot.sannysoft.com** - Basic bot detection
- **arh.antoinevastel.com/bots/areyouheadless** - Headless detection
- **pixelscan.net** - Comprehensive fingerprinting
- **browserleaks.com** - Browser leak tests
- **f.vision** - Advanced bot detection

### ⚠️ May Still Detect (Advanced):
- **datadome.co** - Enterprise bot detection
- **cloudflare.com** - Turnstile challenges (use local solver)
- **recaptcha.net** - reCAPTCHA v3 (behavioral analysis)

## Additional Recommendations

### For Even Better Stealth:

1. **Use Residential Proxies**
   - Datacenter IPs are often flagged
   - Residential IPs appear more legitimate

2. **Add Random Delays**
   - Simulate human typing speed
   - Add pauses between actions

3. **Randomize User Agents**
   - Rotate between recent Chrome versions
   - Match OS and browser version

4. **Use Camoufox Instead**
   - The project already has Camoufox installed
   - Camoufox is specifically designed for stealth
   - Consider creating a Camoufox executor

5. **Implement Behavioral Patterns**
   - Random mouse movements
   - Scroll patterns
   - Click patterns
   - Typing patterns with mistakes

6. **Session Persistence**
   - Save and reuse cookies
   - Maintain consistent fingerprints per account

## Known Limitations

1. **Headless Mode**: Still detectable by advanced systems
   - Consider using headed mode with Xvfb on Linux
   - Or use virtual display

2. **CDP Detection**: Chrome DevTools Protocol can be detected
   - Some sites check for CDP connections

3. **Timing Attacks**: Perfect timing can reveal automation
   - Add random delays and jitter

4. **TLS Fingerprinting**: Not addressed by browser-level stealth
   - Use curl_cffi or similar for TLS fingerprint randomization

## Future Improvements

- [ ] Create Camoufox executor (already installed)
- [ ] Add behavioral simulation (mouse movements, scrolling)
- [ ] Implement session persistence
- [ ] Add User-Agent rotation
- [ ] Add font fingerprinting protection
- [ ] Implement WebRTC leak protection
- [ ] Add more realistic timing patterns
