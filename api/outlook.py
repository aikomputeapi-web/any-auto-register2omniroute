from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Any, Dict, List
from services.mail_imports import MailImportExecuteRequest, mail_import_registry

router = APIRouter(prefix="/outlook", tags=["Microsoft Email (Outlook / Hotmail)"])


class OutlookBatchImportRequest(BaseModel):
    data: str
    enabled: bool = True


class OutlookBatchImportResponse(BaseModel):
    total: int
    success: int
    failed: int
    accounts: List[Dict[str, Any]]
    errors: List[str]


@router.post("/batch-import", response_model=OutlookBatchImportResponse)
def batch_import_outlook(request: OutlookBatchImportRequest):
    """
    Import Microsoft mailboxes in batches (Outlook / Hotmail) account

    Two formats are supported (one account per line, fields with ---- separated):
    - Mail----password----client_id----refresh_token(Microsoft OAuth)
    - Mail----mailapi_url(MailAPI URL Polling code acquisition)

    Used by default at runtime Graph The backend reads emails;MailAPI URL The account will go URL Polling to get the code.
    """
    try:
        strategy = mail_import_registry.get("microsoft")
        result = strategy.execute(
            MailImportExecuteRequest(
                type="microsoft",
                content=request.data,
                enabled=request.enabled,
            )
        )
        return OutlookBatchImportResponse(
            total=result.summary.total,
            success=result.summary.success,
            failed=result.summary.failed,
            accounts=list(result.meta.get("accounts") or []),
            errors=result.errors,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

