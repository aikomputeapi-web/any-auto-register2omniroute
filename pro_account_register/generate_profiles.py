import sys
import os
import time
import re
import argparse
import urllib.request
import urllib.error
import json
import socket

# Add root directory to python path so we can import from core
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def get_openrouter_key():
    # 1. Try environment variable
    if os.environ.get("OPENROUTER_API_KEY"):
        return os.environ.get("OPENROUTER_API_KEY")
        
    # 2. Try loading directly from .env file
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

def check_domain_available(domain):
    domain = domain.lower().replace("https://", "").replace("http://", "").strip("/")
    # DNS Check
    try:
        socket.gethostbyname(domain)
        return False
    except socket.gaierror:
        pass
    except Exception:
        pass

    # RDAP Check
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
    domain = f"{name.lower()}.io"
    desc = f"{name} provides a cloud-based AI platform specializing in {random.choice(categories)} using advanced deep learning models. Our services are offered on monthly and annual subscription plans."
    stmt = f"{name.upper()}*SUBSCRIBE"[:22]
    short = name.upper()[:10]
    
    return {
        "business_name": f"{name} LLC",
        "dba": name,
        "website": f"https://{domain}",
        "description": desc,
        "statement_descriptor": stmt,
        "shortened_descriptor": short,
        "domain_research_summary": "Fallback local generation used."
    }

def generate_ai_saas_profile():
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

    # 2. Attempt Gemini API as fallback/backup
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
        3. Research/verify if this domain is available or if the name is already in use by another company.
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
          "domain_research_summary": "Domain is available..."
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

def write_profile_to_file(filepath, biz_info):
    clean_domain = biz_info["website"].replace("https://", "").replace("http://", "").strip("/")
    
    content = f"""============================================================
STRIPE ACCOUNT REGISTRATION — MOCK BUSINESS PROFILE
============================================================
Business Type: Online Subscription Billing

--- BUSINESS DETAILS ---
Legal Business Name: {biz_info["business_name"]}
DBA (Doing Business As): {biz_info["dba"]}
Business Type: LLC
Business Structure: Single-member LLC
EIN (Tax ID): 84-2917365
Date of Incorporation: 03/15/2021
Business Phone: 669-250-6085
Business Website: {biz_info["website"]}
Business Address: 24647 Mohr, Hayward, CA 94545

--- INDUSTRY & PRODUCT DESCRIPTION ---
Industry / Category: Software / SaaS
MCC (Merchant Category Code): 5817 — Digital Goods: Applications
Product Description: {biz_info["description"]}
Statement Descriptor: {biz_info["statement_descriptor"]}
Shortened Descriptor: {biz_info["shortened_descriptor"]}

--- SUBSCRIPTION BILLING MODEL ---
Billing Type: Recurring (monthly & annual)
Average Transaction Amount: $29.99
Monthly Price Tiers:
  - Starter Plan: $9.99/month
  - Pro Plan: $29.99/month
  - Studio Plan: $79.99/month
Annual Price Tiers:
  - Starter Plan: $99.99/year
  - Pro Plan: $299.99/year
  - Studio Plan: $799.99/year
Estimated Monthly Volume: $15,000 - $50,000
Refund Policy: 30-day money-back guarantee on all plans

--- ACCOUNT REPRESENTATIVE (Owner) ---
Full Name: Robert Oliver
Title: Owner / CEO
Date of Birth: 04/06/1938
SSN: 545-50-5372
Email: robertoliver@audioplexdesigns.com
Phone: 669-250-6085
Personal Address: 24647 Mohr, Hayward, CA 94545
Ownership Percentage: 100%
ID Type: California Driver's License
ID Number: F5455053

--- BANK ACCOUNT FOR PAYOUTS ---
Bank Name: Wells Fargo
Account Holder Name: {biz_info["business_name"]}
Routing Number: 121042882
Account Number: 4829103756
Account Type: Business Checking

--- STRIPE ACCOUNT CREDENTIALS ---
Email: robertoliver@audioplexdesigns.com
Password: Aud10Pl3x!D3s1gns#2026

--- WEBSITE REQUIRED PAGES (for Stripe verification) ---
Terms of Service URL: {biz_info["website"].rstrip("/")}/terms
Privacy Policy URL: {biz_info["website"].rstrip("/")}/privacy
Refund Policy URL: {biz_info["website"].rstrip("/")}/refunds
Contact Page URL: {biz_info["website"].rstrip("/")}/contact

--- NOTES ---
- Generated by generate_profiles.py on {time.strftime('%Y-%m-%d %H:%M:%S')}
- Domain availability: {biz_info.get('domain_research_summary', 'N/A')}
"""
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)

def parse_profile_from_file(filepath):
    data = {}
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            m = re.match(r"^([A-Za-z][A-Za-z /&()]+?):\s*(.+)$", line)
            if m:
                data[m.group(1).strip()] = m.group(2).strip()
    return data

def update_markdown_index(out_dir):
    md_file = os.path.join(out_dir, "business_profiles.md")
    
    # Scan all .txt files except template profiles or others
    txt_files = [f for f in os.listdir(out_dir) if f.endswith(".txt") and f.startswith("profile_")]
    profiles = []
    
    for f in txt_files:
        path = os.path.join(out_dir, f)
        try:
            profile_data = parse_profile_from_file(path)
            if "Legal Business Name" in profile_data:
                profiles.append({
                    "filename": f,
                    "name": profile_data.get("Legal Business Name"),
                    "dba": profile_data.get("DBA (Doing Business As)"),
                    "website": profile_data.get("Business Website"),
                    "descriptor": profile_data.get("Statement Descriptor"),
                    "description": profile_data.get("Product Description")
                })
        except Exception as e:
            print(f"Error parsing profile {f}: {e}")
            
    # Write beautiful markdown file
    with open(md_file, "w", encoding="utf-8") as f:
        f.write("# Generated Business Profiles Index\n\n")
        f.write("This file is automatically updated by `generate_profiles.py` when profiles are created or deleted. These profiles can be supplied directly to the Stripe registration script using the `--profile` flag.\n\n")
        
        f.write("## Overview Table\n\n")
        f.write("| Legal Business Name | Website | Statement Descriptor | Profile Details File |\n")
        f.write("| --- | --- | --- | --- |\n")
        
        for p in profiles:
            f.write(f"| **{p['name']}** | [{p['website']}]({p['website']}) | `{p['descriptor']}` | [{p['filename']}](file:///{os.path.abspath(os.path.join(out_dir, p['filename'])).replace('\\', '/')}) |\n")
            
        f.write("\n---\n\n")
        f.write("## Detailed Profiles\n\n")
        
        for idx, p in enumerate(profiles, 1):
            f.write(f"### {idx}. {p['name']}\n")
            f.write(f"- **DBA (Doing Business As)**: {p['dba']}\n")
            f.write(f"- **Website**: [{p['website']}]({p['website']})\n")
            f.write(f"- **Statement Descriptor**: `{p['descriptor']}`\n")
            f.write(f"- **Product Description**: {p['description']}\n")
            f.write(f"- **File Path**: [{p['filename']}](file:///{os.path.abspath(os.path.join(out_dir, p['filename'])).replace('\\', '/')})\n\n")

def main():
    parser = argparse.ArgumentParser(description="Pre-generate AI SaaS Business Profiles for Stripe Registration.")
    parser.add_argument("--count", type=int, default=1,
                        help="Number of profiles to generate (default: 1)")
    parser.add_argument("--out-dir", type=str, default=None,
                        help="Directory to save profiles (default: pro_account_register/generated_profiles/)")
    args = parser.parse_args()
    
    script_dir = os.path.dirname(os.path.abspath(__file__))
    out_dir = args.out_dir if args.out_dir else os.path.join(script_dir, "generated_profiles")
    
    os.makedirs(out_dir, exist_ok=True)
    
    print("=" * 60)
    print(f"GENERATING {args.count} AI SaaS BUSINESS PROFILES")
    print("=" * 60)
    
    for i in range(args.count):
        print(f"\nGenerating profile {i+1} of {args.count}...")
        biz_info = generate_ai_saas_profile()
        
        name_clean = re.sub(r'[^a-zA-Z0-9]', '_', biz_info["dba"]).lower().strip('_')
        filename = f"profile_{name_clean}.txt"
        filepath = os.path.join(out_dir, filename)
        
        write_profile_to_file(filepath, biz_info)
        print(f"[OK] Saved profile to: {os.path.abspath(filepath)}")
        
    print("\nUpdating index file...")
    update_markdown_index(out_dir)
    print(f"[OK] Updated index at: {os.path.abspath(os.path.join(out_dir, 'business_profiles.md'))}")

if __name__ == "__main__":
    main()
