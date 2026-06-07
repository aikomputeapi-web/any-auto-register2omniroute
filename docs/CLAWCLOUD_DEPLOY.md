# use ClawCloud deploy any-auto-register

This document contains two parts:
- How to use GitHub Actions Automatically build and push images
- how to ClawCloud Run Deploy and persist data on

## 1. Preparatory conditions

- Already have GitHub Warehouse (this project)
- Already activated ClawCloud Run
- Docker Mirror repository available (recommended GHCR)

## 2. enable GitHub Actions Build image

This repository has provided workflow files:
- `.github/workflows/docker-image.yml`

It will be executed in the following scenarios:
- push to `main` or `master`
- beat `v*` tags (such as `v1.0.0`)
- manual trigger (`workflow_dispatch`)

Default pushed to GHCR, Mirror address format:
- `ghcr.io/<yourGitHubUsername or organization>/any-auto-register`

### 2.1 Warehouse settings

exist GitHub Confirmed in the warehouse:
- `Settings -> Actions -> General -> Workflow permissions` allow `Read and write permissions`
- storehouse Actions Runnable

### 2.2 Push once to trigger a build

```bash
git add .github/workflows/docker-image.yml docs/CLAWCLOUD_DEPLOY.md
git commit -m "chore: add clawcloud deployment guide and docker image workflow"
git push
```

After the build is successful, in `Packages` or Actions Mirror tags can be seen in the log, for example:
- `latest`
- `main`
- `sha-<commit-short-sha>`
- `v1.0.0`(only tag at the time of publication)

## 3. exist ClawCloud Run Create app

### 3.1 New application

- Enter ClawCloud Run console
- choose `App Launchpad` Create app
- Deployment source Select the container image (Image)
- Fill in the mirror address:
  - `ghcr.io/<yourGitHubUsername or organization>/any-auto-register:latest`

illustrate:
- if GHCR The image is private and needs to be ClawCloud Configure image warehouse credentials
- It is recommended to first set the mirror to public, deployment is simpler

### 3.2 Instances and ports

- Deploy mode:`Fixed`
- Replicas:`1`
- Exposed port:`8000`(HTTP foreign)

Optional ports:
- `8889` yes solver Port, it is usually not recommended to expose it to the public network

## 4. Persistent storage (key)

exist ClawCloud of `Persistent Storage` / `Local Storage` Add mount in:

- mount `/<storage>/runtime` path to container `/runtime`(required)
- mount `/<storage>/ext_targets` path to container `/_ext_targets`(optional)
- mount `/<storage>/external_logs` path to container `/app/services/external_logs`(optional)

Why must be mounted `/runtime`:
- `docker/entrypoint.sh` will be in `/runtime` Created under `account_manager.db`, log and cache files
- Failure to mount will result in data loss after rebuilding the container.

## 5. Environment variable configuration

exist ClawCloud Set in application environment variables:

- `HOST=0.0.0.0`
- `PORT=8000`
- `APP_RELOAD=0`
- `APP_CONDA_ENV=docker`
- `APP_RUNTIME_DIR=/runtime`
- `APP_ENABLE_SOLVER=1`
- `SOLVER_PORT=8889`
- `SOLVER_BIND_HOST=0.0.0.0`
- `LOCAL_SOLVER_URL=http://127.0.0.1:8889`
- `SOLVER_BROWSER_TYPE=camoufox`

Business-related items can be added as needed:
- `OPENAI_*`
- `SMSTOME_COOKIE`
- Other third-party service keys

## 6. Verify after startup

Check after deployment is complete:

- Open the home page:`http(s)://<your domain name>/`
- Interface check:`http(s)://<your domain name>/api/solver/status`

Expected return example:

```json
{"running": true}
```

If you disable solver(`APP_ENABLE_SOLVER=0`), the return may be:

```json
{"running": false}
```

## 7. Upgrade process

- Update the code locally and push arrive `main`
- GitHub Actions Automatically build and push new images
- exist ClawCloud Redeploy the latest tag(or keep `latest` and restart)
- because `/runtime` Already mounted, business data will be retained

## 8. FAQ

### 8.1 data loss

The reason is usually that it is not mounted `/runtime`.  
Processing: in ClawCloud Supplementary persistent storage is mounted to `/runtime`, and then redeploy.

### 8.2 Inaccessible after container startup

examine:
- Is the port exposed? `8000`
- `HOST` Is it `0.0.0.0`
- Are there any errors in the application log?

### 8.3 use SQLite Suggested number of copies

Current project default SQLite, it is recommended to run a single copy (`Replicas=1`).  
If multiple copies are required for high availability, it is recommended to transform it into PostgreSQL.

