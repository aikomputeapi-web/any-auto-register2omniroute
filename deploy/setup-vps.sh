#!/usr/bin/env bash
# =============================================================================
# any-auto-register — VPS provisioning script
# =============================================================================
# Run this on a FRESH Ubuntu 22.04 / 24.04 VPS as root or with sudo.
#
#   ssh root@YOUR_VPS_IP
#   curl -fsSL https://raw.githubusercontent.com/YOUR_USER/any-auto-register/main/deploy/setup-vps.sh | bash
#
# Or copy it up and run locally:
#   scp deploy/setup-vps.sh root@YOUR_VPS_IP:/root/
#   ssh root@YOUR_VPS_IP ./setup-vps.sh
# =============================================================================
set -euo pipefail

# ---- Colour helpers ----
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()  { printf "${GREEN}[INFO]${NC}  %s\n" "$*"; }
warn()  { printf "${YELLOW}[WARN]${NC}  %s\n" "$*"; }
err()   { printf "${RED}[ERROR]${NC} %s\n" "$*"; }

# ---- Preflight ----
if [ "$(id -u)" -ne 0 ]; then
    err "This script must be run as root (or with sudo)."
    exit 1
fi

UBUNTU_VER=$(lsb_release -rs 2>/dev/null || echo "0")
if [ "$(echo "$UBUNTU_VER >= 22.04" | bc)" != "1" ]; then
    err "Ubuntu 22.04+ is required (detected: $UBUNTU_VER)."
    exit 1
fi

info "Ubuntu $UBUNTU_VER detected — proceeding."

# ---- 1. System packages ----
info "Updating system packages..."
apt-get update -qq
apt-get upgrade -y -qq

info "Installing Docker + dependencies..."
apt-get install -y -qq \
    ca-certificates curl gnupg lsb-release \
    ufw git make bc

# ---- 2. Install Docker (official repo) ----
if ! command -v docker &>/dev/null; then
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
        | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    chmod a+r /etc/apt/keyrings/docker.gpg

    echo \
      "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
       https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" \
      | tee /etc/apt/sources.list.d/docker.list > /dev/null

    apt-get update -qq
    apt-get install -y -qq docker-ce docker-ce-cli containerd.io \
        docker-buildx-plugin docker-compose-plugin
    systemctl enable --now docker
    info "Docker installed."
else
    info "Docker already installed — skipping."
fi

# ---- 3. Firewall (UFW) ----
info "Configuring UFW..."
ufw --force reset
ufw default deny incoming
ufw default allow outgoing
ufw allow ssh                # port 22
ufw allow 80/tcp             # HTTP  (Caddy ACME challenge)
ufw allow 443/tcp            # HTTPS (Caddy)
ufw --force enable
info "UFW enabled — only ports 22, 80, 443 are open."

# ---- 4. Disable SSH password auth (optional, recommended) ----
if grep -q "^PasswordAuthentication yes" /etc/ssh/sshd_config; then
    sed -i 's/^PasswordAuthentication yes/PasswordAuthentication no/' /etc/ssh/sshd_config
    systemctl restart sshd
    info "SSH password authentication disabled — key-only now."
fi

# ---- 5. Create app directory structure ----
APP_BASE="/opt/apps"
mkdir -p "$APP_BASE"
info "Application base: $APP_BASE"

# ---- 6. Clone the repository (if not already present) ----
if [ ! -d "$APP_BASE/any-auto-register" ]; then
    warn "Repository not found at $APP_BASE/any-auto-register."
    warn "You need to clone it manually after this script finishes:"
    echo ""
    echo "    cd $APP_BASE"
    echo "    git clone https://github.com/YOUR_USER/any-auto-register.git"
    echo "    cd any-auto-register/deploy"
    echo "    cp .env.example .env"
    echo "    nano .env              # set your domains + email"
    echo "    docker compose up -d --build"
    echo ""
else
    info "Repository already present at $APP_BASE/any-auto-register."
fi

# ---- 7. Tune kernel for browser automation (shared memory) ----
info "Tuning kernel parameters for browser containers..."
cat >> /etc/sysctl.d/99-any-auto-register.conf <<'SYSCTL'
# any-auto-register: browser containers need ample shared memory
kernel.shmmax = 17179869184   # 16 GB
kernel.shmall = 4194304       # 16 GB / page size
SYSCTL
sysctl --system > /dev/null

# ---- 8. Reboot reminder ----
echo ""
info "================================================================"
info " VPS provisioning complete."
info "================================================================"
echo ""
info "A reboot is recommended to pick up the kernel parameters:"
echo ""
echo "    sudo reboot"
echo ""
info "After reboot, continue with the deploy/README.md instructions."
echo ""

# ---- 9. Print summary ----
echo "-------- Summary --------"
echo "  OS:           Ubuntu $UBUNTU_VER"
echo "  Docker:       $(docker --version 2>/dev/null || echo 'check after reboot')"
echo "  Compose:      $(docker compose version 2>/dev/null || echo 'check after reboot')"
echo "  UFW:          enabled (22, 80, 443)"
echo "  SSH password: $(grep -c 'PasswordAuthentication no' /etc/ssh/sshd_config 2>/dev/null || echo 'not changed')"
echo "  App base:     $APP_BASE"
echo "-------------------------"
