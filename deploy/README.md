# VPS multi-app stack

Caddy (auto-HTTPS) fronting `any-auto-register` plus optional sibling apps
(a second "pro" instance and a bank-statement generator).

## Architecture

```
                     Internet
                        |
                   [UFW :80/:443]
                        |
                   [Caddy reverse proxy]
                   (auto Let's Encrypt TLS)
                        |
              +---------+---------+
              |                   |
    any-auto-register    any-auto-register-pro  (optional)
         :8000                 :8000
     (shm 1gb, Xvfb)      (shm 1gb, Xvfb)
              |
         [SQLite /runtime]
         (persisted via bind mount)
```

## Prerequisites (on the VPS)

- **VPS** with Ubuntu 22.04 or 24.04 (recommended: 4 GB+ RAM, 2+ vCPU)
- **Domains** with **DNS A records pointed at the VPS IP** before first start
  (Caddy needs DNS to resolve to issue Let's Encrypt certs)
- **Root SSH access** (key-based recommended)

## Quick start (automated)

Run the provisioning script on your VPS:

```bash
ssh root@YOUR_VPS_IP

# Download and run the setup script
3

https://github.com/aikomputeapi-web/any-auto-register2omniroute.git

# Reboot to apply kernel parameters
sudo reboot
```

After reboot:

```bash
ssh root@YOUR_VPS_IP

# Clone the repository
mkdir -p /opt/apps
cd /opt/apps
git clone https://github.com/YOUR_USER/any-auto-register.git
cd any-auto-register/deploy

# Configure
cp .env.example .env
nano .env    # set AAR_DOMAIN, ACME_EMAIL, etc.

# Build and start
docker compose up -d --build
```

## Manual setup (step by step)

### 1. Provision the VPS

```bash
# SSH into your VPS
ssh root@YOUR_VPS_IP

# Update system
apt-get update && apt-get upgrade -y

# Install Docker
apt-get install -y ca-certificates curl gnupg lsb-release
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | \
    gpg --dearmor -o /etc/apt/keyrings/docker.gpg
chmod a+r /etc/apt/keyrings/docker.gpg

echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
  https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | \
  tee /etc/apt/sources.list.d/docker.list > /dev/null

apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io \
    docker-buildx-plugin docker-compose-plugin

# Enable Docker on boot
systemctl enable --now docker

# Configure firewall
ufw allow ssh
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable

# Tune shared memory for browser containers
echo "kernel.shmmax = 17179869184" >> /etc/sysctl.d/99-any-auto-register.conf
echo "kernel.shmall = 4194304" >> /etc/sysctl.d/99-any-auto-register.conf
sysctl --system

# Reboot (recommended)
sudo reboot
```

### 2. Clone and configure

```bash
ssh root@YOUR_VPS_IP
cd /opt/apps
git clone https://github.com/YOUR_USER/any-auto-register.git
cd any-auto-register/deploy

# Create environment config
cp .env.example .env
nano .env
```

**Required `.env` settings:**

| Variable | Description | Example |
|----------|-------------|---------|
| `AAR_DOMAIN` | Your main domain | `register.example.com` |
| `ACME_EMAIL` | Email for Let's Encrypt | `admin@example.com` |

Optional: set `AARPRO_DOMAIN` and `BANK_DOMAIN` if you run those services.

### 3. Build and start

```bash
# Core stack only (Caddy + any-auto-register)
docker compose up -d --build

# Include optional instances
# docker compose --profile pro --profile bank up -d --build
```

### 4. Verify

```bash
# Check containers are running
docker compose ps

# Follow logs
docker compose logs -f

# Visit https://YOUR_AAR_DOMAIN in a browser
```

## Layout

```
/opt/apps/
├── any-auto-register/          # this repo (contains deploy/)
│   └── deploy/                 # <-- run commands from here
├── any-auto-register-pro/      # optional: clone of the pro repo
└── bank-statement-generator/   # optional
```

## Operations

```bash
# View logs
docker compose logs -f any-auto-register
docker compose logs -f caddy

# Restart a service
docker compose restart any-auto-register

# Reload Caddy config (after Caddyfile edit)
docker compose exec caddy caddy reload --config /etc/caddy/Caddyfile

# Rebuild and restart (after code changes)
docker compose up -d --build any-auto-register

# Pull latest Caddy image
docker compose pull caddy && docker compose up -d

# Stop everything
docker compose down

# Stop and remove volumes (destroys data)
docker compose down -v
```

## Configuration at runtime

- **Captcha keys, mail providers, integrations** — set via the web UI
  **Settings** page. These are stored in the SQLite database at
  `/runtime/account_manager.db` (persisted via the `./data/any-auto-register`
  bind mount).
- **Environment variables** (`.env`) control only Docker-level settings:
  domains, ports, browser type, data directories. No app secrets in `.env`.

## Troubleshooting

| Problem | Likely cause | Fix |
|---------|-------------|-----|
| Cert fails to issue | DNS not propagated, or port 80 blocked | `docker compose logs caddy`; check DNS A record; verify UFW allows 80/tcp |
| Container OOM kills | VPS has less than 4 GB RAM | Reduce `shm_size` in compose, or add swap |
| Solver fails to start | CamouFox / Playwright browser not installed | Check build logs; verify `CAMOUFOX_VERSION` in `.env` |
| "Too many open files" | Playwright opens many file descriptors | `ulimit -n 65536` on host, or add `nofile` limits to compose |

## Updating

```bash
cd /opt/apps/any-auto-register

# Pull latest code
git pull

# Rebuild and restart
cd deploy
docker compose up -d --build any-auto-register

# Restart Caddy to pick up any Caddyfile changes
docker compose restart caddy
```
