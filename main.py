"""account_manager - Multi-platform account management backend"""
import os
import sys
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from core.db import init_db
from core.registry import load_all
from api.accounts import router as accounts_router
from api.tasks import router as tasks_router
from api.platforms import router as platforms_router
from api.proxies import router as proxies_router
from api.config import router as config_router
from api.actions import router as actions_router
from api.integrations import router as integrations_router
from api.auth import router as auth_router
from api.mail_imports import router as mail_imports_router
from api.outlook import router as outlook_router
from api.contribution import router as contribution_router

EXPECTED_CONDA_ENV = os.getenv("APP_CONDA_ENV", "any-auto-register")


def _detect_conda_env() -> str:
    conda_env = os.getenv("CONDA_DEFAULT_ENV")
    if conda_env:
        return conda_env

    prefix_parts = os.path.normpath(sys.prefix).split(os.sep)
    if "envs" in prefix_parts:
        idx = prefix_parts.index("envs")
        if idx + 1 < len(prefix_parts):
            return prefix_parts[idx + 1]
    return ""


def _print_runtime_info() -> None:
    current_env = _detect_conda_env()
    print(f"[Runtime] Python: {sys.executable}")
    print(f"[Runtime] Conda Env: {current_env or 'not detected'}")
    if EXPECTED_CONDA_ENV == "docker":
        return
    if current_env and current_env != EXPECTED_CONDA_ENV:
        print(
            f"[WARN] The current environment is '{current_env}', recommended to use '{EXPECTED_CONDA_ENV}' start up,"
            "otherwise Turnstile Solver It may not start due to missing dependencies."
        )
    elif not current_env:
        print(
            f"[WARN] not detected conda environment, it is recommended to use '{EXPECTED_CONDA_ENV}' start up,"
            "otherwise Turnstile Solver It may not start due to missing dependencies."
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    _print_runtime_info()
    init_db()
    load_all()
    print("[OK] Database initialization completed")
    from core.registry import list_platforms
    print(f"[OK] Platform loaded: {[p['name'] for p in list_platforms()]}")
    from core.scheduler import scheduler
    scheduler.start()
    from services.solver_manager import start_async
    start_async()
    from services.devtools_manager import start_async as start_devtools_async
    start_devtools_async()

    # Clean up dead proxies at startup (background, non-blocking)
    def _cleanup_dead_proxies():
        try:
            from core.proxy_pool import proxy_pool
            import time
            deleted = proxy_pool.delete_dead_proxies()
            if deleted:
                print(f"[Proxy] Cleaned up {deleted} dead proxy/proxies on startup")
            # Also trigger fresh scraping in background
            result = proxy_pool.scrape_proxies()
            print(f"[Proxy] Scraped proxies: added={result.get('added', 0)} updated={result.get('updated', 0)} checked={result.get('checked', 0)}")
        except Exception as e:
            print(f"[Proxy] Startup cleanup skipped: {e}")
    import threading
    threading.Thread(target=_cleanup_dead_proxies, daemon=True).start()

    yield
    from core.scheduler import scheduler as _scheduler
    _scheduler.stop()
    from services.solver_manager import stop
    stop()
    from services.devtools_manager import stop as stop_devtools
    stop_devtools()


app = FastAPI(title="Account Manager", version="1.0.0", lifespan=lifespan)


def _cors_origins() -> list[str]:
    raw = os.getenv("APP_CORS_ORIGINS", "")
    if raw:
        return [o.strip() for o in raw.split(",") if o.strip()]
    return ["*"]


@app.middleware("http")
async def proxy_auth_middleware(request: Request, call_next):
    """Identity is provided by Authelia via Caddy's forward_auth.

    When APP_REQUIRE_PROXY_AUTH is enabled, every /api/* request (except the
    /api/auth/* status endpoints) must carry the trusted Remote-User header
    that Caddy copies from Authelia's forward-auth response. Requests that
    reach the app without it have bypassed the proxy and are rejected.
    """
    path = request.url.path
    if not path.startswith("/api/") or path.startswith("/api/auth/"):
        return await call_next(request)
    if os.getenv("APP_REQUIRE_PROXY_AUTH", "0").lower() not in {"1", "true", "yes"}:
        return await call_next(request)
    header_name = os.getenv("APP_TRUSTED_REMOTE_USER_HEADER", "Remote-User")
    if request.headers.get(header_name, ""):
        return await call_next(request)
    return JSONResponse({"detail": "Not authenticated via identity provider"}, status_code=401)


app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(accounts_router, prefix="/api")
app.include_router(tasks_router, prefix="/api")
app.include_router(platforms_router, prefix="/api")
app.include_router(proxies_router, prefix="/api")
app.include_router(config_router, prefix="/api")
app.include_router(actions_router, prefix="/api")
app.include_router(integrations_router, prefix="/api")
app.include_router(auth_router, prefix="/api")
app.include_router(mail_imports_router, prefix="/api")
app.include_router(outlook_router, prefix="/api")
app.include_router(contribution_router, prefix="/api")


@app.get("/api/solver/status")
def solver_status():
    from services.solver_manager import is_running
    return {"running": is_running()}


@app.get("/api/devtools/status")
def devtools_status():
    from services.devtools_manager import is_running as is_dt_running, _devtools_port, _devtools_enabled
    return {
        "enabled": _devtools_enabled(),
        "running": is_dt_running(),
        "port": _devtools_port()
    }


@app.post("/api/solver/restart")
def solver_restart():
    from services.solver_manager import stop, start_async
    stop()
    start_async()
    return {"message": "Restarting"}


_static_pro_dir = os.path.join(os.path.dirname(__file__), "static_pro")
if os.path.isdir(_static_pro_dir):
    app.mount("/pro/assets", StaticFiles(directory=os.path.join(_static_pro_dir, "assets")), name="pro_assets")

    @app.get("/pro/{full_path:path}", include_in_schema=False)
    def spa_pro_fallback(full_path: str):
        return FileResponse(os.path.join(_static_pro_dir, "index.html"))


_static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.isdir(_static_dir):
    app.mount("/assets", StaticFiles(directory=os.path.join(_static_dir, "assets")), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa_fallback(full_path: str):
        return FileResponse(os.path.join(_static_dir, "index.html"))



if __name__ == "__main__":
    import uvicorn

    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    reload_enabled = os.getenv("APP_RELOAD", "0").lower() in {"1", "true", "yes"}
    uvicorn.run("main:app", host=host, port=port, reload=reload_enabled)
