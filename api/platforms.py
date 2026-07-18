from fastapi import APIRouter
from core.registry import list_platforms

router = APIRouter(prefix="/platforms", tags=["platforms"])

_PRO_PLATFORMS = frozenset({"amex", "jfcu", "usbank", "rrcu", "stripe"})
# Hidden from default AI UI (still registered; use type=all or type=pro as appropriate)
_AI_HIDDEN = frozenset({"cursor", "tavily"}) | _PRO_PLATFORMS


@router.get("")
def get_platforms(type: str = "ai"):
    """
    List loaded platforms.

    - type=ai   (default): main AI product list (excludes pro + cursor/tavily)
    - type=pro: pro account platforms only
    - type=all: every registered platform (best for plugin development checks)
    """
    platforms = list_platforms()
    kind = (type or "ai").strip().lower()
    if kind == "all":
        return platforms
    if kind == "pro":
        return [p for p in platforms if p["name"] in _PRO_PLATFORMS]
    return [p for p in platforms if p["name"] not in _AI_HIDDEN]

