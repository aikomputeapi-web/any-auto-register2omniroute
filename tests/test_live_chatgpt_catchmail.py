import time
import requests
import json
import sys

def test_live_registration():
    url = "http://127.0.0.1:8000/api/tasks/register"
    payload = {
        "platform": "chatgpt",
        "count": 1,
        "concurrency": 1,
        "executor_type": "headed",
        "captcha_solver": "local_solver",
        "extra": {
            "mail_provider": "catchmail"
        }
    }
    
    print(f"Triggering registration task at {url}...")
    try:
        r = requests.post(url, json=payload, timeout=10)
        r.raise_for_status()
    except Exception as e:
        print(f"FAILURE: Could not trigger registration on local backend: {e}")
        return False
        
    resp_data = r.json()
    task_id = resp_data.get("task_id")
    print(f"Task successfully enqueued with ID: {task_id}")
    
    # Poll logs
    print("Streaming logs in real-time:")
    print("=" * 60)
    seen_lines = set()
    while True:
        status_url = f"http://127.0.0.1:8000/api/tasks/{task_id}"
        try:
            status_r = requests.get(status_url, timeout=10)
            status_r.raise_for_status()
            task_status = status_r.json()
        except Exception as e:
            print(f"\nError fetching status: {e}")
            break
            
        logs = task_status.get("logs") or []
        for line in logs:
            if line not in seen_lines:
                print(line)
                seen_lines.add(line)
                
        status = task_status.get("status")
        if status in ("done", "failed", "stopped"):
            print("=" * 60)
            print(f"Task completed with status: {status}")
            if status == "done":
                print("SUCCESS: Live ChatGPT registration with CatchMail.io completed successfully!")
                return True
            else:
                print(f"FAILURE: Registration failed: {task_status.get('error')}")
                return False
                
        time.sleep(2)

if __name__ == "__main__":
    success = test_live_registration()
    sys.exit(0 if success else 1)
