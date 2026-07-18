"""Search the freemodel JS for phone validation and send-sms logic."""
import re
import requests

r = requests.get('https://freemodel.dev/assets/index-YnlRnpi7.js', timeout=30)
t = r.text

# Search for phone-related patterns
patterns = [
    r'send-sms',
    r'invalid_phone',
    r'phone.*replace',
    r'phone.*strip',
    r'phone.*clean',
    r'1\[3-9\]',
    r'phoneRegex',
    r'phonePattern',
    r'phoneFmt',
    r'phoneErr',
    r'errPhone',
]

for p in patterns:
    matches = [(m.start(), t[max(0,m.start()-50):m.end()+100]) for m in re.finditer(p, t, re.I)]
    if matches:
        print(f"\n=== Pattern: {p} ({len(matches)} matches) ===")
        for pos, ctx in matches[:5]:
            print(f"  @{pos}: ...{ctx}...")
