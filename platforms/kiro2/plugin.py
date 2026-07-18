"""Kiro2 Platform plugin - delegates to kiro-register node CLI"""

import os
import re
import json
import random
import string
import subprocess
from typing import Optional

from core.base_platform import BasePlatform, Account, AccountStatus, RegisterConfig
from core.base_mailbox import BaseMailbox
from core.registry import register
from core.config_store import config_store


@register
class Kiro2Platform(BasePlatform):
    name = "kiro2"
    display_name = "Kiro 2"
    version = "1.0.0"
    supported_executors = ["headless", "headed"]

    def __init__(
        self,
        config: Optional[RegisterConfig] = None,
        mailbox: Optional[BaseMailbox] = None,
    ):
        super().__init__(config or RegisterConfig())
        self.mailbox = mailbox

    def register(self, email: str, password: Optional[str] = None) -> Account:
        log_fn = getattr(self, "_log_fn", print)
        
        # 1. Update config.json in kiro-register
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        kiro_register_dir = os.path.join(project_root, "kiro-register")
        
        # Retrieve GPTMail settings from FastAPI config_store
        gptmail_api_key = str(config_store.get("gptmail_api_key", "") or "").strip()
        gptmail_base_url = str(config_store.get("gptmail_base_url", "https://mail.chatgpt.org.uk") or "").strip()
        gptmail_domain = str(config_store.get("gptmail_domain", "") or "").strip()
        
        # Write config.json
        cfg_path = os.path.join(kiro_register_dir, "config.json")
        try:
            with open(cfg_path, "w", encoding="utf-8") as f:
                json.dump({
                    "gptmail_api_key": gptmail_api_key,
                    "gptmail_base_url": gptmail_base_url,
                    "gptmail_domain": gptmail_domain
                }, f, indent=2, ensure_ascii=False)
            log_fn(f"[Kiro 2] Updated {cfg_path}")
        except Exception as e:
            log_fn(f"[Kiro 2] Warning: failed to write config.json: {e}")

        # 2. Determine email, password and mailbox credentials
        ms_client_id = ""
        ms_refresh_token = ""
        mail_provider = "gptmail"  # Default
        
        # Resolve mailbox if email is empty
        if not email:
            if self.mailbox:
                mail_acct = self.mailbox.get_email()
                if not mail_acct:
                    raise RuntimeError("No available email account found from mailbox service")
                email = mail_acct.email
                log_fn(f"[Kiro 2] Obtained email from mailbox: {email}")
                
                # Check if this is an outlook/microsoft mailbox to get Oauth credentials
                if hasattr(self.mailbox, "_backend_name") or (mail_acct.extra and mail_acct.extra.get("provider") == "microsoft"):
                    mail_provider = "graph"
                    ms_client_id = mail_acct.extra.get("client_id", "")
                    ms_refresh_token = mail_acct.extra.get("refresh_token", "")
            else:
                raise RuntimeError("Email is empty, and no mailbox service is configured to generate one")
        else:
            # Email is specified. Let's see if we can deduce mail provider or get Microsoft credentials
            if self.mailbox and (hasattr(self.mailbox, "_backend_name") or self.mailbox.__class__.__name__ == "OutlookMailbox"):
                # Try to get the cached credentials or configurations
                mail_provider = "graph"

        if not password:
            # Generate random password satisfying AWS complexity
            lower = "".join(random.choices(string.ascii_lowercase, k=4))
            upper = "".join(random.choices(string.ascii_uppercase, k=4))
            digits = "".join(random.choices(string.digits, k=4))
            special = "".join(random.choices("!@#$", k=2))
            pw_chars = list(lower + upper + digits + special)
            random.shuffle(pw_chars)
            password = "".join(pw_chars)
            log_fn("[Kiro 2] Generated a secure random password for AWS Builder ID")

        # 3. Create temp account file
        data_dir = os.path.join(kiro_register_dir, "data")
        os.makedirs(data_dir, exist_ok=True)
        temp_file_name = f"temp_accounts_{re.sub(r'[^a-zA-Z0-9]', '_', email)}.txt"
        temp_file_path = os.path.join(data_dir, temp_file_name)
        
        # Format: email----password----clientId----refreshToken
        line_parts = [email, password]
        if ms_client_id and ms_refresh_token:
            line_parts.extend([ms_client_id, ms_refresh_token])
        
        try:
            with open(temp_file_path, "w", encoding="utf-8") as f:
                f.write("----".join(line_parts) + "\n")
        except Exception as e:
            raise RuntimeError(f"Failed to write temporary accounts file: {e}")

        # 4. Invoke npx tsx index.ts
        npx_exe = "npx.cmd" if os.name == "nt" else "npx"
        cmd = [npx_exe, "tsx", "index.ts", "--file", f"data/{temp_file_name}", "--mail-provider", mail_provider]
        if self.config.proxy:
            cmd.extend(["--proxy", self.config.proxy])
            
        log_fn(f"[Kiro 2] Executing command: {' '.join(cmd)} in {kiro_register_dir}")
        
        try:
            # Use binary mode so Windows charmap codec is never invoked.
            # Node.js outputs emoji/CJK characters that cp1252 cannot encode.
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=False,          # binary – we decode manually below
                bufsize=0,
                cwd=kiro_register_dir,
            )

            # Stream logs in real-time, decoding each line as UTF-8
            for raw_line in process.stdout:
                line = raw_line.decode("utf-8", errors="replace").rstrip()
                if line:
                    try:
                        log_fn(line)
                    except (UnicodeEncodeError, UnicodeDecodeError, OSError):
                        # Windows charmap codec can't handle CJK/emoji from Node output.
                        # Transliterate to ASCII so the log entry is still recorded.
                        safe = line.encode("ascii", errors="replace").decode("ascii")
                        log_fn(safe)

            process.wait()
            exit_code = process.returncode
            log_fn(f"[Kiro 2] Subprocess finished with exit code {exit_code}")
            if exit_code != 0:
                raise RuntimeError(f"kiro-register subprocess failed with code {exit_code}")
        except Exception as e:
            # Clean up temp file
            if os.path.exists(temp_file_path):
                try:
                    os.remove(temp_file_path)
                except Exception:
                    pass
            raise RuntimeError(f"Failed to execute kiro-register script: {e}")
            
        finally:
            # Clean up temp file
            if os.path.exists(temp_file_path):
                try:
                    os.remove(temp_file_path)
                except Exception:
                    pass

        # 5. Read output file
        safe_email = re.sub(r"[^a-zA-Z0-9]", "_", email)
        output_file_path = os.path.join(kiro_register_dir, "data", "output", f"{safe_email}.json")
        
        if not os.path.exists(output_file_path):
            raise RuntimeError(f"Registration output file not found: {output_file_path}. Registration might have failed.")
            
        try:
            with open(output_file_path, "r", encoding="utf-8") as f:
                res_data = json.load(f)
        except Exception as e:
            raise RuntimeError(f"Failed to read registration output file: {e}")

        # Extract tokens
        refresh_token = res_data.get("refreshToken", "")
        access_token = res_data.get("accessToken", "")
        client_id = res_data.get("clientId", "")
        client_secret = res_data.get("clientSecret", "")
        region = res_data.get("region", "us-east-1")
        aws_password = res_data.get("awsPassword", password)
        
        if not refresh_token:
            raise RuntimeError("Registration did not return a valid refreshToken")

        return Account(
            platform="kiro2",
            email=email,
            password=aws_password,
            status=AccountStatus.REGISTERED,
            token=access_token,
            region=region,
            extra={
                "name": "Kiro 2 User",
                "accessToken": access_token,
                "refreshToken": refresh_token,
                "clientId": client_id,
                "clientSecret": client_secret,
                "region": region,
                "provider": "BuilderId",
                "authMethod": "IdC",
            }
        )

    def check_valid(self, account: Account) -> bool:
        """Use refresh_kiro_token to verify if account credentials are valid"""
        extra = account.extra or {}
        refresh_token = extra.get("refreshToken", "")
        if not refresh_token:
            return False
        try:
            from platforms.kiro.switch import refresh_kiro_token

            ok, result = refresh_kiro_token(
                refresh_token,
                extra.get("clientId", ""),
                extra.get("clientSecret", ""),
            )
            if ok:
                new_access = result["accessToken"]
                new_refresh = result.get("refreshToken", refresh_token)
                account.token = new_access
                extra["accessToken"] = new_access
                extra["refreshToken"] = new_refresh
                account.extra = extra
            return ok
        except Exception:
            return False

    def get_platform_actions(self) -> list:
        return [
            {"id": "refresh_token", "label": "refresh Token", "params": []},
            {"id": "upload_to_omniroute", "label": "Upload to OmniRoute", "params": []},
        ]

    def execute_action(self, action_id: str, account: Account, params: dict) -> dict:
        extra = account.extra or {}

        if action_id == "refresh_token":
            from platforms.kiro.switch import refresh_kiro_token

            refresh_token = extra.get("refreshToken", "")
            client_id = extra.get("clientId", "")
            client_secret = extra.get("clientSecret", "")

            ok, result = refresh_kiro_token(refresh_token, client_id, client_secret)
            if ok:
                new_access = result["accessToken"]
                new_refresh = result.get("refreshToken", refresh_token)
                return {
                    "ok": True,
                    "data": {
                        "access_token": new_access,
                        "accessToken": new_access,
                        "refreshToken": new_refresh,
                    },
                }
            return {"ok": False, "error": result.get("error", "Refresh failed")}

        elif action_id == "upload_to_omniroute":
            from services.omniroute_sync import upload_to_omniroute, build_omniroute_payload
            from core.config_store import config_store

            api_url = str(config_store.get("omniroute_api_url", "") or "").strip()
            admin_password = str(config_store.get("omniroute_admin_password", "") or "").strip()
            if not api_url:
                return {"ok": False, "error": "OmniRoute API URL is not configured (omniroute_api_url)"}

            # Build and expose the payload for debugging
            try:
                payload = build_omniroute_payload(account)
            except Exception as e:
                return {"ok": False, "error": f"Failed to build OmniRoute payload: {e}"}

            ok, msg = upload_to_omniroute(account, api_url=api_url, admin_password=admin_password)
            return {
                "ok": ok,
                "data": {
                    "message": msg,
                    "payload_preview": {
                        "provider": payload.get("provider", ""),
                        "authType": payload.get("authType", ""),
                        "email": payload.get("email", ""),
                        "has_accessToken": bool(payload.get("accessToken")),
                        "has_refreshToken": bool(payload.get("refreshToken")),
                        "providerSpecificData": payload.get("providerSpecificData", {}),
                    },
                },
                "error": "" if ok else msg,
            }

        raise NotImplementedError(f"Unknown operation: {action_id}")
