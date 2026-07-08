from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlmodel import Session, select
from pydantic import BaseModel
from typing import Optional
from core.db import ProxyModel, engine, get_session
from core.proxy_pool import proxy_pool
from core.config_store import config_store

router = APIRouter(prefix="/proxies", tags=["proxies"])


class ProxyCreate(BaseModel):
    url: str
    region: str = ""


class ProxyBulkCreate(BaseModel):
    proxies: list[str]
    region: str = ""


class ProxyBatchDelete(BaseModel):
    ids: list[int]


@router.get("")
def list_proxies(session: Session = Depends(get_session)):
    items = session.exec(select(ProxyModel)).all()
    return items


@router.post("")
def add_proxy(body: ProxyCreate, session: Session = Depends(get_session)):
    existing = session.exec(select(ProxyModel).where(ProxyModel.url == body.url)).first()
    if existing:
        raise HTTPException(400, "Agent already exists")
    p = ProxyModel(url=body.url, region=body.region)
    session.add(p)
    session.commit()
    session.refresh(p)
    return p


@router.post("/bulk")
def bulk_add_proxies(body: ProxyBulkCreate, session: Session = Depends(get_session)):
    added = 0
    for url in body.proxies:
        url = url.strip()
        if not url:
            continue
        existing = session.exec(select(ProxyModel).where(ProxyModel.url == url)).first()
        if not existing:
            session.add(ProxyModel(url=url, region=body.region))
            added += 1
    session.commit()
    return {"added": added}


@router.delete("/{proxy_id}")
def delete_proxy(proxy_id: int, session: Session = Depends(get_session)):
    p = session.get(ProxyModel, proxy_id)
    if not p:
        raise HTTPException(404, "Agent does not exist")
    session.delete(p)
    session.commit()
    return {"ok": True}


@router.post("/batch-delete")
def batch_delete_proxies(body: ProxyBatchDelete, session: Session = Depends(get_session)):
    if not body.ids:
        raise HTTPException(400, "acting ID List cannot be empty")
    ids = list(dict.fromkeys(int(i) for i in body.ids))
    if len(ids) > 1000:
        raise HTTPException(400, "Maximum number of deletes at a time 1000 Article agent")

    proxies = session.exec(select(ProxyModel).where(ProxyModel.id.in_(ids))).all()
    found_ids = {p.id for p in proxies if p.id is not None}
    for p in proxies:
        session.delete(p)
    session.commit()

    return {
        "deleted": len(found_ids),
        "not_found": [pid for pid in ids if pid not in found_ids],
        "total_requested": len(ids),
    }


@router.patch("/{proxy_id}/toggle")
def toggle_proxy(proxy_id: int, session: Session = Depends(get_session)):
    p = session.get(ProxyModel, proxy_id)
    if not p:
        raise HTTPException(404, "Agent does not exist")
    p.is_active = not p.is_active
    session.add(p)
    session.commit()
    return {"is_active": p.is_active}


@router.post("/check")
def check_proxies(background_tasks: BackgroundTasks):
    background_tasks.add_task(proxy_pool.check_all)
    return {"message": "The detection task has been started"}


@router.post("/scrape")
def scrape_proxies(background_tasks: BackgroundTasks):
    background_tasks.add_task(proxy_pool.scrape_proxies)
    return {"message": "Scraping task started in the background"}


@router.post("/clear-all")
def clear_all_proxies(session: Session = Depends(get_session)):
    proxies = session.exec(select(ProxyModel)).all()
    for p in proxies:
        session.delete(p)
    session.commit()
    return {"deleted": len(proxies)}


@router.post("/delete-inactive")
def delete_inactive_proxies(session: Session = Depends(get_session)):
    proxies = session.exec(
        select(ProxyModel).where(
            (ProxyModel.is_active == False)
            | ((ProxyModel.fail_count > 0) & (ProxyModel.success_count == 0))
        )
    ).all()
    for p in proxies:
        session.delete(p)
    session.commit()
    return {"deleted": len(proxies)}


@router.post("/cleanup")
def cleanup_proxies(background_tasks: BackgroundTasks):
    """Check all proxies, delete dead ones, and scrape fresh proxies."""
    def _cleanup():
        count = proxy_pool.delete_dead_proxies()
        return count
    background_tasks.add_task(_cleanup)
    return {"message": "Proxy cleanup started in the background"}


@router.post("/verify")
def verify_proxies(background_tasks: BackgroundTasks):
    """Check each proxy in the pool and deactivate/delete dead ones."""
    background_tasks.add_task(proxy_pool.check_all)
    return {"message": "Proxy verification started in the background"}


# ---------------------------------------------------------------------------
# Proxy pinning — select a specific proxy (or custom proxy URL) to use for
# all subsequent registration runs until changed back to "auto" (random).
# ---------------------------------------------------------------------------

class PinnedProxyConfig(BaseModel):
    """Pinned proxy configuration.

    mode: "auto"   → randomly assign proxies from the pool (default)
    mode: "select" → use a specific proxy from the pool (by proxy_id)
    mode: "custom" → use a custom proxy URL entered by the user
    """
    mode: str = "auto"          # "auto" | "select" | "custom"
    proxy_id: Optional[int] = None
    custom_url: Optional[str] = None


@router.get("/pinned")
def get_pinned_proxy():
    """Get the current pinned proxy configuration."""
    mode = config_store.get("pinned_proxy_mode", "auto")
    proxy_id_str = config_store.get("pinned_proxy_id", "")
    custom_url = config_store.get("pinned_proxy_custom_url", "")

    result = {
        "mode": mode,
        "proxy_id": int(proxy_id_str) if proxy_id_str.isdigit() else None,
        "custom_url": custom_url,
        "resolved_url": "",
    }

    if mode == "select" and result["proxy_id"]:
        with Session(engine) as s:
            p = s.get(ProxyModel, result["proxy_id"])
            if p:
                result["resolved_url"] = p.url
            else:
                # Proxy was deleted, fall back to auto
                result["mode"] = "auto"
    elif mode == "custom" and custom_url:
        result["resolved_url"] = custom_url

    return result


@router.post("/pinned")
def set_pinned_proxy(body: PinnedProxyConfig):
    """Set the pinned proxy configuration."""
    if body.mode not in ("auto", "select", "custom"):
        raise HTTPException(400, "mode must be 'auto', 'select', or 'custom'")

    config_store.set("pinned_proxy_mode", body.mode)

    if body.mode == "select":
        if not body.proxy_id:
            raise HTTPException(400, "proxy_id is required when mode='select'")
        config_store.set("pinned_proxy_id", str(body.proxy_id))
        config_store.set("pinned_proxy_custom_url", "")
    elif body.mode == "custom":
        if not body.custom_url or not body.custom_url.strip():
            raise HTTPException(400, "custom_url is required when mode='custom'")
        config_store.set("pinned_proxy_custom_url", body.custom_url.strip())
        config_store.set("pinned_proxy_id", "")
    else:
        # auto — clear both
        config_store.set("pinned_proxy_id", "")
        config_store.set("pinned_proxy_custom_url", "")

    return get_pinned_proxy()
