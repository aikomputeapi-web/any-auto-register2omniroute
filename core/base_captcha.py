"""Captcha solver base class"""
from abc import ABC, abstractmethod
import os


def _default_solver_url() -> str:
    return os.getenv("LOCAL_SOLVER_URL") or f"http://127.0.0.1:{os.getenv('SOLVER_PORT', '8889')}"


class BaseCaptcha(ABC):
    @abstractmethod
    def solve_turnstile(self, page_url: str, site_key: str) -> str:
        """return Turnstile token"""
        ...

    @abstractmethod
    def solve_recaptcha(self, page_url: str, site_key: str, enterprise: bool = False, invisible: bool = False) -> str:
        """return reCAPTCHA token"""
        ...

    @abstractmethod
    def solve_image(self, image_b64: str) -> str:
        """Return image verification code text"""
        ...


class YesCaptcha(BaseCaptcha):
    def __init__(self, client_key: str):
        self.client_key = client_key
        self.api = "https://api.yescaptcha.com"

    def solve_turnstile(self, page_url: str, site_key: str) -> str:
        import requests, time, urllib3
        urllib3.disable_warnings()
        r = requests.post(f"{self.api}/createTask", json={
            "clientKey": self.client_key,
            "task": {"type": "TurnstileTaskProxyless",
                     "websiteURL": page_url, "websiteKey": site_key}
        }, timeout=30, verify=False)
        task_id = r.json().get("taskId")
        if not task_id:
            raise RuntimeError(f"YesCaptcha Failed to create task: {r.text}")
        for _ in range(60):
            time.sleep(3)
            d = requests.post(f"{self.api}/getTaskResult", json={
                "clientKey": self.client_key, "taskId": task_id
            }, timeout=30, verify=False).json()
            if d.get("status") == "ready":
                return d["solution"]["token"]
            if d.get("errorId", 0) != 0:
                raise RuntimeError(f"YesCaptcha mistake: {d}")
        raise TimeoutError("YesCaptcha Turnstile time out")

    def solve_recaptcha(self, page_url: str, site_key: str, enterprise: bool = False, invisible: bool = False) -> str:
        import requests, time, urllib3
        urllib3.disable_warnings()
        task_type = "RecaptchaV2EnterpriseTaskProxyless" if enterprise else "NoCaptchaTaskProxyless"
        task = {
            "type": task_type,
            "websiteURL": page_url,
            "websiteKey": site_key
        }
        if invisible:
            task["isInvisible"] = True
        r = requests.post(f"{self.api}/createTask", json={
            "clientKey": self.client_key,
            "task": task
        }, timeout=30, verify=False)
        task_id = r.json().get("taskId")
        if not task_id:
            raise RuntimeError(f"YesCaptcha Failed to create task: {r.text}")
        for _ in range(60):
            time.sleep(3)
            d = requests.post(f"{self.api}/getTaskResult", json={
                "clientKey": self.client_key, "taskId": task_id
            }, timeout=30, verify=False).json()
            if d.get("status") == "ready":
                return d["solution"]["gRecaptchaResponse"]
            if d.get("errorId", 0) != 0:
                raise RuntimeError(f"YesCaptcha mistake: {d}")
        raise TimeoutError("YesCaptcha reCAPTCHA time out")

    def solve_image(self, image_b64: str) -> str:
        raise NotImplementedError


class CapSolver(BaseCaptcha):
    def __init__(self, client_key: str):
        self.client_key = client_key
        self.api = "https://api.capsolver.com"

    def solve_turnstile(self, page_url: str, site_key: str) -> str:
        import requests, time, urllib3
        urllib3.disable_warnings()
        r = requests.post(f"{self.api}/createTask", json={
            "clientKey": self.client_key,
            "task": {
                "type": "AntiTurnstileTaskProxyLess",
                "websiteURL": page_url,
                "websiteKey": site_key
            }
        }, timeout=30, verify=False)
        task_id = r.json().get("taskId")
        if not task_id:
            raise RuntimeError(f"CapSolver Failed to create task: {r.text}")
        for _ in range(60):
            time.sleep(3)
            d = requests.post(f"{self.api}/getTaskResult", json={
                "clientKey": self.client_key, "taskId": task_id
            }, timeout=30, verify=False).json()
            if d.get("status") == "ready":
                return d["solution"]["token"]
            if d.get("errorId", 0) != 0:
                raise RuntimeError(f"CapSolver mistake: {d}")
        raise TimeoutError("CapSolver Turnstile time out")

    def solve_recaptcha(self, page_url: str, site_key: str, enterprise: bool = False, invisible: bool = False) -> str:
        import requests, time, urllib3
        urllib3.disable_warnings()
        task_type = "ReCaptchaV2EnterpriseTaskProxyLess" if enterprise else "ReCaptchaV2TaskProxyLess"
        task = {
            "type": task_type,
            "websiteURL": page_url,
            "websiteKey": site_key
        }
        if invisible:
            task["isInvisible"] = True
        r = requests.post(f"{self.api}/createTask", json={
            "clientKey": self.client_key,
            "task": task
        }, timeout=30, verify=False)
        task_id = r.json().get("taskId")
        if not task_id:
            raise RuntimeError(f"CapSolver Failed to create task: {r.text}")
        for _ in range(60):
            time.sleep(3)
            d = requests.post(f"{self.api}/getTaskResult", json={
                "clientKey": self.client_key, "taskId": task_id
            }, timeout=30, verify=False).json()
            if d.get("status") == "ready":
                return d["solution"]["gRecaptchaResponse"]
            if d.get("errorId", 0) != 0:
                raise RuntimeError(f"CapSolver mistake: {d}")
        raise TimeoutError("CapSolver reCAPTCHA time out")

    def solve_image(self, image_b64: str) -> str:
        raise NotImplementedError


class ManualCaptcha(BaseCaptcha):
    """Manual coding, blocking waiting for user input"""
    def solve_turnstile(self, page_url: str, site_key: str) -> str:
        return input(f"Please obtain it manually Turnstile token ({page_url}): ").strip()

    def solve_recaptcha(self, page_url: str, site_key: str, enterprise: bool = False, invisible: bool = False) -> str:
        return input(f"Please obtain it manually reCAPTCHA token ({page_url}): ").strip()

    def solve_image(self, image_b64: str) -> str:
        return input("Please enter the image verification code: ").strip()


class LocalSolverCaptcha(BaseCaptcha):
    """call local api_solver Service solution Turnstile(Camoufox/patchright)"""

    def __init__(self, solver_url: str | None = None):
        self.solver_url = (solver_url or _default_solver_url()).rstrip("/")

    def solve_turnstile(self, page_url: str, site_key: str) -> str:
        import requests, time
        # Submit task
        r = requests.get(
            f"{self.solver_url}/turnstile",
            params={"url": page_url, "sitekey": site_key},
            timeout=15,
        )
        r.raise_for_status()
        task_id = r.json().get("taskId")
        if not task_id:
            raise RuntimeError(f"LocalSolver Not returned taskId: {r.text}")
        # Polling results
        for _ in range(60):
            time.sleep(2)
            res = requests.get(
                f"{self.solver_url}/result",
                params={"id": task_id},
                timeout=10,
            )
            if res.status_code == 200:
                data = res.json()
                status = data.get("status")
                if status == "ready":
                    token = data.get("solution", {}).get("token")
                    if token:
                        return token
                elif status == "CAPTCHA_FAIL":
                    raise RuntimeError("LocalSolver Turnstile fail")
        raise TimeoutError("LocalSolver Turnstile time out")

    def solve_recaptcha(self, page_url: str, site_key: str, enterprise: bool = False, invisible: bool = False) -> str:
        raise NotImplementedError("LocalSolver reCAPTCHA not implemented")

    def solve_image(self, image_b64: str) -> str:
        raise NotImplementedError

    @staticmethod
    def start_solver(headless: bool = True, browser_type: str = "camoufox",
                     port: int = 8889) -> None:
        """Start local in background thread solver Serve"""
        import subprocess, sys, os
        solver_path = os.path.join(
            os.path.dirname(__file__), "..", "services", "turnstile_solver", "start.py"
        )
        cmd = [
            sys.executable, solver_path,
            "--port", str(port),
            "--browser_type", browser_type,
        ]
        if not headless:
            cmd.append("--no-headless")
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        # Wait for the service to start
        import time, requests
        for _ in range(20):
            time.sleep(1)
            try:
                requests.get(f"http://localhost:{port}/", timeout=2)
                return
            except Exception:
                pass
        raise RuntimeError("LocalSolver Start timeout")
