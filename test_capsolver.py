"""Test CapSolver API for Turnstile"""
from core.config_store import config_store
import json, urllib.request, time

api_key = config_store.get("capsolver_key", "")
print(f"API Key: {api_key[:10]}...")

payload = {
    "clientKey": api_key,
    "task": {
        "type": "AntiTurnstileTaskProxyLess",
        "websiteURL": "https://railway.com/login",
        "websiteKey": "0x4AAAAAAC1ksDZJd9ksGuf7",
        "metadata": {"action": "", "cdata": ""},
    },
}

print("Creating Turnstile solve task...")
data = json.dumps(payload).encode("utf-8")
req = urllib.request.Request(
    "https://api.capsolver.com/createTask",
    data=data,
    headers={"Content-Type": "application/json"},
)
resp = urllib.request.urlopen(req, timeout=30)
result = json.loads(resp.read().decode())
print(f"Create response: {json.dumps(result, indent=2)[:200]}")

task_id = result.get("taskId")
if not task_id:
    print(f"No task ID: {result}")
    exit(1)

print(f"Task ID: {task_id}")
print("Polling for result...")

for i in range(60):
    time.sleep(3)
    payload2 = {"clientKey": api_key, "taskId": task_id}
    data2 = json.dumps(payload2).encode("utf-8")
    req2 = urllib.request.Request(
        "https://api.capsolver.com/getTaskResult",
        data=data2,
        headers={"Content-Type": "application/json"},
    )
    resp2 = urllib.request.urlopen(req2, timeout=30)
    result2 = json.loads(resp2.read().decode())
    status = result2.get("status")
    if status == "ready":
        token = result2.get("solution", {}).get("token", "")
        print(f"Solved! Token: {token[:50]}...")
        break
    elif status == "failed":
        print(f"Failed: {result2}")
        break
    else:
        print(f"  Poll {i}: status={status}")
else:
    print("Timed out")
