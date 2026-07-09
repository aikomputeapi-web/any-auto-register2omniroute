#!/bin/bash
# Auto-deploy script: pulls latest code, rebuilds Docker, restarts
# Usage: bash scripts/deploy.sh
set -eu

DEPLOY_DIR="/opt/any-auto-register"
LOG_FILE="/opt/any-auto-register/deploy.log"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"
}

log "=== Deploy started ==="

cd "$DEPLOY_DIR"

log "Pulling latest code..."
git pull origin main

log "Rebuilding Docker images..."
docker compose build --no-cache

log "Restarting containers..."
docker compose up -d

log "Cleaning up old images..."
docker image prune -f

log "=== Deploy completed successfully ==="
