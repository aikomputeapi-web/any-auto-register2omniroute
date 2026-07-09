#!/usr/bin/env python3
"""
Lightweight GitHub webhook listener for auto-deploy.

Listens for GitHub push events and triggers deploy.sh in the background.

Setup on VPS:
  1. pip install flask
  2. python scripts/webhook_listener.py
  3. Set up a systemd service (see below)
  4. Configure GitHub webhook: http://<your-vps-ip>:9000/webhook

GitHub webhook config:
  - Payload URL: http://<your-vps-ip>:9000/webhook
  - Content type: application/json
  - Secret: (set WEBHOOK_SECRET env var to the same value)
  - Events: Just the push event
"""

import hashlib
import hmac
import os
import subprocess
import sys
import threading

try:
    from flask import Flask, request, jsonify
except ImportError:
    print("Installing flask...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "flask", "-q"])
    from flask import Flask, request, jsonify

app = Flask(__name__)

WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "")
DEPLOY_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "deploy.sh")
DEPLOY_DIR = os.environ.get("DEPLOY_DIR", "/opt/any-auto-register")


def verify_signature(payload_body, signature_header):
    """Verify GitHub webhook signature (HMAC-SHA256)."""
    if not WEBHOOK_SECRET or not signature_header:
        return not WEBHOOK_SECRET  # skip verification if no secret set
    expected = "sha256=" + hmac.new(
        WEBHOOK_SECRET.encode(),
        payload_body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature_header)


def run_deploy():
    """Run the deploy script in a background thread."""
    try:
        result = subprocess.run(
            ["bash", DEPLOY_SCRIPT],
            cwd=DEPLOY_DIR,
            capture_output=True,
            text=True,
            timeout=600,
        )
        log_path = os.path.join(DEPLOY_DIR, "deploy.log")
        with open(log_path, "a") as f:
            if result.stdout:
                f.write(result.stdout)
            if result.stderr:
                f.write(f"[stderr] {result.stderr}")
        print(f"[deploy] Completed with exit code {result.returncode}")
    except Exception as e:
        print(f"[deploy] Failed: {e}")


@app.route("/webhook", methods=["POST"])
def webhook():
    # Verify signature
    sig = request.headers.get("X-Hub-Signature-256", "")
    if not verify_signature(request.data, sig):
        return jsonify({"error": "Invalid signature"}), 403

    # Check for push event
    event = request.headers.get("X-GitHub-Event", "")
    if event == "ping":
        return jsonify({"msg": "pong"})
    if event != "push":
        return jsonify({"msg": f"Ignored event: {event}"}), 200

    payload = request.json or {}
    ref = payload.get("ref", "")
    branch = ref.replace("refs/heads/", "")
    repo = payload.get("repository", {}).get("full_name", "")

    print(f"[webhook] Push to {repo} branch={branch}")

    # Only deploy on main branch pushes
    if branch not in ("main", "master"):
        return jsonify({"msg": f"Ignored push to branch: {branch}"}), 200

    # Trigger deploy in background
    threading.Thread(target=run_deploy, daemon=True).start()
    return jsonify({"msg": "Deploy triggered"}), 200


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    port = int(os.environ.get("WEBHOOK_PORT", 9000))
    print(f"Webhook listener running on port {port}")
    print(f"Deploy script: {DEPLOY_SCRIPT}")
    print(f"Deploy dir: {DEPLOY_DIR}")
    if WEBHOOK_SECRET:
        print("Webhook signature verification: ENABLED")
    else:
        print("Webhook signature verification: DISABLED (set WEBHOOK_SECRET env var)")
    app.run(host="0.0.0.0", port=port)
