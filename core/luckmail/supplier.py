"""
Supplier side API interface
Base URL: {base_url}/api/v1/openapi/supplier

All methods support synchronization/Asynchronous dual mode, automatically recognized based on the calling context.
"""

from typing import Any, Dict, List, Optional

from .http_client import LuckMailHttpClient, _is_async_context
from .models import (
    AppealDetail,
    AppealItem,
    DashboardSummary,
    ImportResult,
    PageResult,
    SupplierEmailItem,
    SupplierProfile,
)

_SUPPLIER_PREFIX = "/api/v1/openapi/supplier"


def _parse_supplier_profile(data: dict) -> SupplierProfile:
    return SupplierProfile(
        id=data.get("id", 0),
        username=data.get("username", ""),
        email=data.get("email", ""),
        balance=data.get("balance", "0.0000"),
        frozen_balance=data.get("frozen_balance", "0.0000"),
        code_commission_rate=data.get("code_commission_rate", "0.0000"),
        buy_commission_rate=data.get("buy_commission_rate", "0.0000"),
        status=data.get("status", 1),
    )


def _parse_supplier_email(data: dict) -> SupplierEmailItem:
    return SupplierEmailItem(
        id=data.get("id", 0),
        address=data.get("address", ""),
        type=data.get("type", ""),
        status=data.get("status", 1),
        domain=data.get("domain", ""),
        total_used=data.get("total_used", 0),
        success_count=data.get("success_count", 0),
        fail_count=data.get("fail_count", 0),
        is_short_term=data.get("is_short_term", 0),
    )


def _parse_appeal_item(data: dict) -> AppealItem:
    return AppealItem(
        id=data.get("id", 0),
        appeal_no=data.get("appeal_no", ""),
        order_no=data.get("order_no", ""),
        reason=data.get("reason", ""),
        status=data.get("status", 1),
        created_at=data.get("created_at", ""),
    )


def _parse_appeal_detail(data: dict) -> AppealDetail:
    return AppealDetail(
        appeal_no=data.get("appeal_no", ""),
        order_no=data.get("order_no", ""),
        reason=data.get("reason", ""),
        status=data.get("status", 1),
        supplier_reply=data.get("supplier_reply"),
        created_at=data.get("created_at"),
    )


def _parse_page_result(data: dict, item_parser=None) -> PageResult:
    items = data.get("list", [])
    if item_parser:
        items = [item_parser(i) for i in items]
    return PageResult(
        list=items,
        total=data.get("total", 0),
        page=data.get("page", 1),
        page_size=data.get("page_size", 20),
    )


class SupplierAPI:
    """
    Supplier side API interface collection
    
    All methods intelligently support synchronization/Asynchronous call:
    - exist async In the function:await client.supplier.get_profile()
    - In a normal function:client.supplier.get_profile()
    
    Args:
        http_client: LuckMailHttpClient Example
    """
    
    def __init__(self, http_client: LuckMailHttpClient):
        self._client = http_client
    
    def _path(self, path: str) -> str:
        """splicing supplier API path"""
        return f"{_SUPPLIER_PREFIX}{path}"
    
    # ===== Supplier information =====
    
    def get_profile(self):
        """
        Obtain supplier personal information
        
        Returns:
            SupplierProfile: Supplier information (balance, commission rate, etc.)
        
        Example::
            profile = client.supplier.get_profile()
            print(profile.username, profile.balance)
        """
        if _is_async_context():
            return self._async_get_profile()
        return self._sync_get_profile()
    
    async def _async_get_profile(self) -> SupplierProfile:
        data = await self._client._async_request("GET", self._path("/profile"))
        return _parse_supplier_profile(data)
    
    def _sync_get_profile(self) -> SupplierProfile:
        data = self._client._sync_request("GET", self._path("/profile"))
        return _parse_supplier_profile(data)
    
    # ===== Mailbox management =====
    
    def get_emails(
        self,
        page: int = 1,
        page_size: int = 20,
        keyword: Optional[str] = None,
        email_type: Optional[str] = None,
        is_short_term: Optional[int] = None,
        status: Optional[int] = None,
    ):
        """
        Get mailbox list (paginated)
        
        Args:
            page: Page number, default 1
            page_size: Number per page, default 20
            keyword: Email address keyword search
            email_type: Email type:ms_graph / ms_imap / google_variant / self_built
            is_short_term: Only valid for Microsoft email:0=Long lasting 1=short acting
            status: state:1=normal 2=abnormal 4=Disable
        
        Returns:
            PageResult: Paginated results,list for SupplierEmailItem list
        
        Example::
            result = client.supplier.get_emails(email_type='ms_graph', is_short_term=0)
            print(f"Long lasting MS Graph Mail: {result.total} indivual")
        """
        params = {
            "page": page,
            "page_size": page_size,
            "keyword": keyword,
            "type": email_type,
            "is_short_term": is_short_term,
            "status": status,
        }
        if _is_async_context():
            return self._async_get_emails(params)
        return self._sync_get_emails(params)
    
    async def _async_get_emails(self, params: dict) -> PageResult:
        data = await self._client._async_request("GET", self._path("/emails"), params=params)
        return _parse_page_result(data, _parse_supplier_email)
    
    def _sync_get_emails(self, params: dict) -> PageResult:
        data = self._client._sync_request("GET", self._path("/emails"), params=params)
        return _parse_page_result(data, _parse_supplier_email)
    
    def import_emails(
        self,
        email_type: str,
        emails: List[dict],
        is_short_term: int = 0,
    ):
        """
        Import mailboxes into supplier resource pool in batches
        
        Args:
            email_type: Email type:microsoft / ms_graph / ms_imap / google_variant / self_built
            emails: Email list, each item contains address,password,client_id,refresh_token wait
            is_short_term: Only valid for Microsoft email,0=long lasting (default)1=short acting
        
        Returns:
            ImportResult: Import results
        
        Example::
            result = client.supplier.import_emails(
                email_type='ms_graph',
                is_short_term=0,
                emails=[
                    {
                        'address': 'user1@outlook.com',
                        'client_id': 'xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx',
                        'refresh_token': 'xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx'
                    }
                ]
            )
            print(f"success: {result.success}, repeat: {result.duplicate}")
        """
        body: Dict[str, Any] = {
            "type": email_type,
            "is_short_term": is_short_term,
            "emails": emails,
        }
        if _is_async_context():
            return self._async_import_emails(body)
        return self._sync_import_emails(body)
    
    async def _async_import_emails(self, body: dict) -> ImportResult:
        data = await self._client._async_request(
            "POST", self._path("/emails/import"), json_data=body
        )
        return ImportResult(
            success=data.get("success", 0),
            duplicate=data.get("duplicate", 0),
            failed=data.get("failed", 0),
        )
    
    def _sync_import_emails(self, body: dict) -> ImportResult:
        data = self._client._sync_request(
            "POST", self._path("/emails/import"), json_data=body
        )
        return ImportResult(
            success=data.get("success", 0),
            duplicate=data.get("duplicate", 0),
            failed=data.get("failed", 0),
        )
    
    def export_emails(
        self,
        keyword: Optional[str] = None,
        email_type: Optional[str] = None,
        is_short_term: Optional[int] = None,
        status: Optional[int] = None,
    ):
        """
        Export mailbox (txt file stream)
        
        Args:
            keyword: keyword filter
            email_type: Email type filtering
            is_short_term: 0=Long lasting 1=short acting
            status: Status filtering
        
        Returns:
            bytes: txt File content
        
        Example::
            content = client.supplier.export_emails(email_type='ms_graph')
            with open("emails.txt", "wb") as f:
                f.write(content)
        """
        params = {
            "keyword": keyword,
            "type": email_type,
            "is_short_term": is_short_term,
            "status": status,
        }
        if _is_async_context():
            return self._client._async_get_stream(self._path("/emails/export"), params=params)
        return self._client._sync_get_stream(self._path("/emails/export"), params=params)
    
    # ===== Complaints management =====
    
    def get_appeals(
        self,
        page: int = 1,
        page_size: int = 20,
        status: Optional[int] = None,
        appeal_type: Optional[int] = None,
    ):
        """
        Get a list of representations (paginated)
        
        Args:
            page: page number
            page_size: Quantity per page
            status: Appeal status:1=Pending 2=Agreed 3=pending arbitration 4=Rejected
            appeal_type: Statement type filter
        
        Returns:
            PageResult: Paginated results,list for AppealItem list
        
        Example::
            result = client.supplier.get_appeals(status=1)
            print(f"Pending representations: {result.total} indivual")
        """
        params = {
            "page": page,
            "page_size": page_size,
            "status": status,
            "type": appeal_type,
        }
        if _is_async_context():
            return self._async_get_appeals(params)
        return self._sync_get_appeals(params)
    
    async def _async_get_appeals(self, params: dict) -> PageResult:
        data = await self._client._async_request("GET", self._path("/appeals"), params=params)
        return _parse_page_result(data, _parse_appeal_item)
    
    def _sync_get_appeals(self, params: dict) -> PageResult:
        data = self._client._sync_request("GET", self._path("/appeals"), params=params)
        return _parse_page_result(data, _parse_appeal_item)
    
    def get_appeal(self, appeal_no: str):
        """
        Get complaint details
        
        Args:
            appeal_no: Complaint number
        
        Returns:
            AppealDetail: Details of representation
        
        Example::
            detail = client.supplier.get_appeal("APL20240310001")
            print(detail.reason, detail.status)
        """
        if _is_async_context():
            return self._async_get_appeal(appeal_no)
        return self._sync_get_appeal(appeal_no)
    
    async def _async_get_appeal(self, appeal_no: str) -> AppealDetail:
        data = await self._client._async_request(
            "GET", self._path(f"/appeal/{appeal_no}")
        )
        return _parse_appeal_detail(data)
    
    def _sync_get_appeal(self, appeal_no: str) -> AppealDetail:
        data = self._client._sync_request(
            "GET", self._path(f"/appeal/{appeal_no}")
        )
        return _parse_appeal_detail(data)
    
    def reply_appeal(self, appeal_no: str, result: int, reply: str):
        """
        Handling Complaints (Reply)
        
        Args:
            appeal_no: Complaint number
            result: Processing results:1=Agree to refund 2=Refusal to represent 3=Apply for arbitration
            reply: Reply content description
        
        Returns:
            None
        
        Example::
            # Agree to refund
            client.supplier.reply_appeal("APL20240310001", result=1, reply="There is indeed something wrong with the email, I agree to refund.")
            
            # Refusal to represent
            client.supplier.reply_appeal("APL20240310001", result=2, reply="The email status is normal and the appeal is rejected.")
        """
        body = {"result": result, "reply": reply}
        if _is_async_context():
            return self._async_reply_appeal(appeal_no, body)
        return self._sync_reply_appeal(appeal_no, body)
    
    async def _async_reply_appeal(self, appeal_no: str, body: dict) -> None:
        await self._client._async_request(
            "POST", self._path(f"/appeal/{appeal_no}/reply"), json_data=body
        )
    
    def _sync_reply_appeal(self, appeal_no: str, body: dict) -> None:
        self._client._sync_request(
            "POST", self._path(f"/appeal/{appeal_no}/reply"), json_data=body
        )
    
    def batch_reply_appeals(
        self,
        appeal_nos: List[str],
        result: int,
        reply: str,
    ):
        """
        Batch processing of claims
        
        Args:
            appeal_nos: List of complaint numbers (up to 100 strip)
            result: Processing results:1=Agree to refund 2=Refusal to represent 3=Apply for arbitration
            reply: Reply content description
        
        Returns:
            dict: Include success and failed quantity
        
        Example::
            result = client.supplier.batch_reply_appeals(
                appeal_nos=["APL001", "APL002", "APL003"],
                result=2,
                reply="It has been verified that the email is normal and the appeal is rejected."
            )
            print(f"successfully processed: {result['success']}")
        """
        body = {
            "appeal_nos": appeal_nos,
            "result": result,
            "reply": reply,
        }
        if _is_async_context():
            return self._async_batch_reply_appeals(body)
        return self._sync_batch_reply_appeals(body)
    
    async def _async_batch_reply_appeals(self, body: dict) -> dict:
        return await self._client._async_request(
            "POST", self._path("/appeals/batch-reply"), json_data=body
        )
    
    def _sync_batch_reply_appeals(self, body: dict) -> dict:
        return self._client._sync_request(
            "POST", self._path("/appeals/batch-reply"), json_data=body
        )
    
    # ===== Data dashboard =====
    
    def get_dashboard(self):
        """
        Get an overview of the data dashboard
        
        Returns:
            DashboardSummary: Kanban data, including total number of mailboxes, code reception statistics, commission data, etc.
        
        Example::
            summary = client.supplier.get_dashboard()
            print(f"Main mailbox: {summary.total_emails}")
            print(f"Today's commission: {summary.today_commission}")
            print(f"success rate: {summary.success_rate}%")
        """
        if _is_async_context():
            return self._async_get_dashboard()
        return self._sync_get_dashboard()
    
    async def _async_get_dashboard(self) -> DashboardSummary:
        data = await self._client._async_request("GET", self._path("/dashboard/summary"))
        return self._build_dashboard(data)
    
    def _sync_get_dashboard(self) -> DashboardSummary:
        data = self._client._sync_request("GET", self._path("/dashboard/summary"))
        return self._build_dashboard(data)
    
    def _build_dashboard(self, data: dict) -> DashboardSummary:
        return DashboardSummary(
            total_emails=data.get("total_emails", 0),
            active_emails=data.get("active_emails", 0),
            total_assigned=data.get("total_assigned", 0),
            total_success=data.get("total_success", 0),
            success_rate=data.get("success_rate", 0.0),
            total_commission=data.get("total_commission", "0.0000"),
            available_balance=data.get("available_balance", "0.0000"),
            today_assigned=data.get("today_assigned", 0),
            today_success=data.get("today_success", 0),
            today_commission=data.get("today_commission", "0.0000"),
            email_category=data.get("email_category", {}),
        )
