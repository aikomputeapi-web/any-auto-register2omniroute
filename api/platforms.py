from fastapi import APIRouter
from core.registry import list_platforms

router = APIRouter(prefix="/platforms", tags=["platforms"])


@router.get("")
def get_platforms(type: str = "ai"):
    platforms = list_platforms()
    if type == "pro":
        return [p for p in platforms if p["name"] in ("amex", "jfcu", "usbank", "stripe")]
    return [p for p in platforms if p["name"] not in ("cursor", "tavily", "amex", "jfcu", "usbank", "stripe")]

