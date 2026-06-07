"""
client API interface
Base URL: {base_url}/api/v1/openapi

All methods support synchronization/Asynchronous dual mode, automatically recognized based on the calling context:
- exist async in function await Call: asynchronous mode
- Call directly in a normal function: synchronous mode
"""

import asyncio
import time
from typing import Any, Dict, List, Optional, Union

from .http_client import LuckMailHttpClient, _is_async_context
from .models import (
    AppealInfo,
    EmailItem,
    ImportResult,
    OrderCode,
    OrderInfo,
    PageResult,
    ProjectItem,
    ProjectPrice,
    PurchaseItem,
    TagItem,
    TokenCode,
    TokenAliveResult,
    TokenMailDetail,
    TokenMailItem,
    TokenMailList,
    UserInfo,
)


def _parse_page_result(data: dict, item_parser=None) -> PageResult:
    """Parse paginated results"""
    items = data.get("list", [])
    if item_parser:
        items = [item_parser(i) for i in items]
    return PageResult(
        list=items,
        total=data.get("total", 0),
        page=data.get("page", 1),
        page_size=data.get("page_size", 20),
    )


def _parse_user_info(data: dict) -> UserInfo:
    return UserInfo(
        id=data.get("id", 0),
        username=data.get("username", ""),
        email=data.get("email", ""),
        balance=data.get("balance", "0.0000"),
        status=data.get("status", 1),
        api_email_enabled=data.get("api_email_enabled", 0),
        api_email_price=data.get("api_email_price", "0.0000"),
    )


def _parse_email_item(data: dict) -> EmailItem:
    return EmailItem(
        id=data.get("id", 0),
        address=data.get("address", ""),
        type=data.get("type", ""),
        status=data.get("status", 1),
        domain=data.get("domain", ""),
        total_used=data.get("total_used", 0),
        success_count=data.get("success_count", 0),
        fail_count=data.get("fail_count", 0),
    )


def _parse_project_item(data: dict) -> ProjectItem:
    prices = [
        ProjectPrice(
            email_type=p.get("email_type", ""),
            code_price=p.get("code_price", "0.0000"),
            buy_price=p.get("buy_price", "0.0000"),
        )
        for p in data.get("prices", [])
    ]
    return ProjectItem(
        id=data.get("id", 0),
        name=data.get("name", ""),
        code=data.get("code", ""),
        email_types=data.get("email_types", []),
        timeout_seconds=data.get("timeout_seconds", 300),
        warranty_hours=data.get("warranty_hours", 0),
        daily_limit=data.get("daily_limit", 0),
        description=data.get("description", ""),
        prices=prices,
    )


def _parse_order_info(data: dict) -> OrderInfo:
    return OrderInfo(
        order_no=data.get("order_no", ""),
        email_address=data.get("email_address", ""),
        project=data.get("project", ""),
        price=data.get("price", "0.0000"),
        timeout_seconds=data.get("timeout_seconds", 300),
        expired_at=data.get("expired_at", ""),
    )


def _parse_order_code(data: dict) -> OrderCode:
    return OrderCode(
        order_no=data.get("order_no", ""),
        status=data.get("status", "pending"),
        verification_code=data.get("verification_code"),
        mail_from=data.get("mail_from"),
        mail_subject=data.get("mail_subject"),
        mail_body_html=data.get("mail_body_html"),
    )


def _parse_purchase_item(data: dict) -> PurchaseItem:
    return PurchaseItem(
        id=data.get("id", 0),
        email_address=data.get("email_address", ""),
        token=data.get("token", ""),
        project_name=data.get("project_name", ""),
        price=data.get("price", "0.0000"),
        status=data.get("status", 1),
        tag_id=data.get("tag_id", 0),
        tag_name=data.get("tag_name", ""),
        user_disabled=data.get("user_disabled", 0),
        warranty_hours=data.get("warranty_hours", 0),
        warranty_until=data.get("warranty_until"),
        created_at=data.get("created_at"),
    )


def _parse_tag_item(data: dict) -> TagItem:
    return TagItem(
        id=data.get("id", 0),
        name=data.get("name", ""),
        remark=data.get("remark", ""),
        limit_type=data.get("limit_type", 0),
        purchase_count=data.get("purchase_count", 0),
        created_at=data.get("created_at"),
    )


def _parse_token_code(data: dict) -> TokenCode:
    return TokenCode(
        email_address=data.get("email_address", ""),
        project=data.get("project", ""),
        has_new_mail=data.get("has_new_mail", False),
        verification_code=data.get("verification_code"),
        mail=data.get("mail"),
    )


def _parse_token_alive_result(data: dict) -> TokenAliveResult:
    return TokenAliveResult(
        email_address=data.get("email_address", ""),
        project=data.get("project", ""),
        alive=data.get("alive", False),
        status=data.get("status", "failed"),
        message=data.get("message", ""),
        mail_count=data.get("mail_count", 0),
    )


def _parse_token_mail_item(data: dict) -> TokenMailItem:
    return TokenMailItem(
        message_id=data.get("message_id", ""),
        from_addr=data.get("from", ""),
        subject=data.get("subject", ""),
        body=data.get("body", ""),
        html_body=data.get("html_body", ""),
        received_at=data.get("received_at", ""),
    )


def _parse_token_mail_list(data: dict) -> TokenMailList:
    mails_raw = data.get("mails", [])
    mails = [_parse_token_mail_item(m) for m in mails_raw] if mails_raw else []
    return TokenMailList(
        email_address=data.get("email_address", ""),
        project=data.get("project", ""),
        warranty_until=data.get("warranty_until", ""),
        mails=mails,
    )


def _parse_token_mail_detail(data: dict) -> TokenMailDetail:
    return TokenMailDetail(
        message_id=data.get("message_id", ""),
        from_addr=data.get("from", ""),
        to=data.get("to", ""),
        subject=data.get("subject", ""),
        body_text=data.get("body_text", ""),
        body_html=data.get("body_html", ""),
        received_at=data.get("received_at", ""),
        verification_code=data.get("verification_code", ""),
    )


class UserAPI:
    """
    client API interface collection
    
    All methods intelligently support synchronization/Asynchronous call:
    - exist async In the function:await client.user.get_user_info()
    - In a normal function:client.user.get_user_info()
    
    Args:
        http_client: LuckMailHttpClient Example
    """
    
    def __init__(self, http_client: LuckMailHttpClient):
        self._client = http_client
    
    # ===== User information =====
    
    def get_user_info(self):
        """
        Get user information and balance
        
        Returns:
            UserInfo: User information object
        
        Synchronous call::
            info = client.user.get_user_info()
            print(info.username, info.balance)
        
        asynchronous call::
            info = await client.user.get_user_info()
            print(info.username, info.balance)
        """
        if _is_async_context():
            return self._async_get_user_info()
        return self._sync_get_user_info()
    
    async def _async_get_user_info(self) -> UserInfo:
        data = await self._client._async_request("GET", "/api/v1/openapi/user/info")
        return _parse_user_info(data)
    
    def _sync_get_user_info(self) -> UserInfo:
        data = self._client._sync_request("GET", "/api/v1/openapi/user/info")
        return _parse_user_info(data)
    
    def get_balance(self):
        """
        Check balance
        
        Returns:
            str: Balance string, such as "150.0000"
        
        Example::
            balance = client.user.get_balance()
            print(f"Balance: {balance}")
        """
        if _is_async_context():
            return self._async_get_balance()
        return self._sync_get_balance()
    
    async def _async_get_balance(self) -> str:
        data = await self._client._async_request("GET", "/api/v1/openapi/balance")
        return data.get("balance", "0.0000")
    
    def _sync_get_balance(self) -> str:
        data = self._client._sync_request("GET", "/api/v1/openapi/balance")
        return data.get("balance", "0.0000")
    
    # ===== Email type =====
    
    def get_email_types(self):
        """
        Get a list of supported email types
        
        Returns:
            List[dict]: List of mailbox types, each item contains type,name,description
        
        Example::
            types = client.user.get_email_types()
            for t in types:
                print(t['type'], t['name'])
        """
        if _is_async_context():
            return self._async_get_email_types()
        return self._sync_get_email_types()
    
    async def _async_get_email_types(self) -> List[dict]:
        return await self._client._async_request("GET", "/api/v1/openapi/email-types")
    
    def _sync_get_email_types(self) -> List[dict]:
        return self._client._sync_request("GET", "/api/v1/openapi/email-types")
    
    # ===== My email management =====
    
    def get_emails(
        self,
        page: int = 1,
        page_size: int = 20,
        keyword: Optional[str] = None,
        status: Optional[int] = None,
    ):
        """
        Get my email list (paginated)
        
        Args:
            page: Page number, default 1
            page_size: Number per page, default 20
            keyword: Email address keyword search
            status: Status filtering:1=normal 2=abnormal 4=Disable
        
        Returns:
            PageResult: Paginated results,list for EmailItem list
        
        Example::
            result = client.user.get_emails(page=1, keyword="outlook")
            for email in result.list:
                print(email.address, email.status)
        """
        params = {
            "page": page,
            "page_size": page_size,
            "keyword": keyword,
            "status": status,
        }
        if _is_async_context():
            return self._async_get_emails(params)
        return self._sync_get_emails(params)
    
    async def _async_get_emails(self, params: dict) -> PageResult:
        data = await self._client._async_request("GET", "/api/v1/openapi/emails", params=params)
        return _parse_page_result(data, _parse_email_item)
    
    def _sync_get_emails(self, params: dict) -> PageResult:
        data = self._client._sync_request("GET", "/api/v1/openapi/emails", params=params)
        return _parse_page_result(data, _parse_email_item)
    
    def import_emails(self, email_type: str, emails: List[dict]):
        """
        Import mailboxes into a private mailbox pool
        
        Args:
            email_type: Email type, such as 'ms_graph', 'ms_imap', 'google_variant', 'self_built'
            emails: Email list, each item is dict,Include address,password,client_id,refresh_token wait
        
        Returns:
            ImportResult: Import results (success/duplicate/failed quantity)
        
        Example::
            result = client.user.import_emails(
                email_type='ms_graph',
                emails=[
                    {
                        'address': 'user@outlook.com',
                        'password': 'pass123',
                        'client_id': 'xxx-xxx-xxx',
                        'refresh_token': 'xxxxxxxxxxxxxxxx'
                    }
                ]
            )
            print(f"success: {result.success}, repeat: {result.duplicate}, fail: {result.failed}")
        """
        body = {"type": email_type, "emails": emails}
        if _is_async_context():
            return self._async_import_emails(body)
        return self._sync_import_emails(body)
    
    async def _async_import_emails(self, body: dict) -> ImportResult:
        data = await self._client._async_request("POST", "/api/v1/openapi/emails/import", json_data=body)
        return ImportResult(
            success=data.get("success", 0),
            duplicate=data.get("duplicate", 0),
            failed=data.get("failed", 0),
        )
    
    def _sync_import_emails(self, body: dict) -> ImportResult:
        data = self._client._sync_request("POST", "/api/v1/openapi/emails/import", json_data=body)
        return ImportResult(
            success=data.get("success", 0),
            duplicate=data.get("duplicate", 0),
            failed=data.get("failed", 0),
        )
    
    def export_emails(
        self,
        keyword: Optional[str] = None,
        status: Optional[int] = None,
    ):
        """
        Export mailbox (txt file stream)
        
        Args:
            keyword: keyword filter
            status: Status filtering:1=normal 2=abnormal 4=Disable
        
        Returns:
            bytes: txt File content, format of each line:address----password or address----client_id----refresh_token
        
        Example::
            content = client.user.export_emails(keyword="outlook")
            with open("emails.txt", "wb") as f:
                f.write(content)
        """
        params = {"keyword": keyword, "status": status}
        if _is_async_context():
            return self._client._async_get_stream("/api/v1/openapi/emails/export", params=params)
        return self._client._sync_get_stream("/api/v1/openapi/emails/export", params=params)
    
    # ===== Project list =====
    
    def get_projects(self, page: int = 1, page_size: int = 50):
        """
        Get project list
        
        Args:
            page: Page number, default 1
            page_size: Number per page, default 50,maximum 500
        
        Returns:
            PageResult: Paginated results,list for ProjectItem list
        
        Example::
            result = client.user.get_projects()
            for p in result.list:
                print(p.name, p.code)
        """
        params = {"page": page, "page_size": page_size}
        if _is_async_context():
            return self._async_get_projects(params)
        return self._sync_get_projects(params)
    
    async def _async_get_projects(self, params: dict) -> PageResult:
        data = await self._client._async_request("GET", "/api/v1/openapi/projects", params=params)
        return _parse_page_result(data, _parse_project_item)
    
    def _sync_get_projects(self, params: dict) -> PageResult:
        data = self._client._sync_request("GET", "/api/v1/openapi/projects", params=params)
        return _parse_page_result(data, _parse_project_item)
    
    # ===== Receive code order =====
    
    def create_order(
        self,
        project_code: str,
        email_type: Optional[str] = None,
        domain: Optional[str] = None,
        specified_email: Optional[str] = None,
        variant_mode: Optional[str] = None,
    ):
        """
        Create code receiving order
        
        Args:
            project_code: Project coding, such as 'twitter', 'facebook'
            email_type: Email type (optional):ms_graph / ms_imap / self_built / google_variant
            domain: Specify the domain name (optional), such as 'outlook.com'
            specified_email: Specify email address (optional)
            variant_mode: Google variant mode (optional, only email_type=google_variant valid at the time): dot=dot variant / plus=+number variant / mixed=Mixed variants / all=randomly selected
        
        Returns:
            OrderInfo: Order information, including order_no and allocated email_address
        
        Example::
            order = client.user.create_order('twitter', email_type='ms_graph')
            print(f"Order number: {order.order_no}")
            print(f"Mail: {order.email_address}")
        """
        body: Dict[str, Any] = {"project_code": project_code}
        if email_type:
            body["email_type"] = email_type
        if domain:
            body["domain"] = domain
        if specified_email:
            body["specified_email"] = specified_email
        if variant_mode:
            body["variant_mode"] = variant_mode
        
        if _is_async_context():
            return self._async_create_order(body)
        return self._sync_create_order(body)
    
    async def _async_create_order(self, body: dict) -> OrderInfo:
        data = await self._client._async_request("POST", "/api/v1/openapi/order/create", json_data=body)
        return _parse_order_info(data)
    
    def _sync_create_order(self, body: dict) -> OrderInfo:
        data = self._client._sync_request("POST", "/api/v1/openapi/order/create", json_data=body)
        return _parse_order_info(data)
    
    def get_order_code(self, order_no: str):
        """
        Query verification code (single query)
        
        Args:
            order_no: order number
        
        Returns:
            OrderCode: Verification code result,status for 'success' included when verification_code
        
        Example::
            code = client.user.get_order_code(order.order_no)
            if code.status == 'success':
                print(f"Verification code: {code.verification_code}")
        """
        if _is_async_context():
            return self._async_get_order_code(order_no)
        return self._sync_get_order_code(order_no)
    
    async def _async_get_order_code(self, order_no: str) -> OrderCode:
        data = await self._client._async_request(
            "GET", f"/api/v1/openapi/order/{order_no}/code"
        )
        return _parse_order_code(data)
    
    def _sync_get_order_code(self, order_no: str) -> OrderCode:
        data = self._client._sync_request(
            "GET", f"/api/v1/openapi/order/{order_no}/code"
        )
        return _parse_order_code(data)
    
    def cancel_order(self, order_no: str):
        """
        Cancel order
        
        Args:
            order_no: order number
        
        Returns:
            None
        
        Example::
            client.user.cancel_order(order.order_no)
        """
        if _is_async_context():
            return self._async_cancel_order(order_no)
        return self._sync_cancel_order(order_no)
    
    async def _async_cancel_order(self, order_no: str) -> None:
        await self._client._async_request(
            "POST", f"/api/v1/openapi/order/{order_no}/cancel"
        )
    
    def _sync_cancel_order(self, order_no: str) -> None:
        self._client._sync_request(
            "POST", f"/api/v1/openapi/order/{order_no}/cancel"
        )
    
    def get_orders(
        self,
        page: int = 1,
        page_size: int = 20,
        status: Optional[int] = None,
        project_id: Optional[int] = None,
    ):
        """
        Get order list (pagination)
        
        Args:
            page: page number
            page_size: Quantity per page
            status: Status filtering:1=Waiting code 2=Completed 3=Timed out 4=Canceled 5=Refunded
            project_id: by project ID filter
        
        Returns:
            PageResult: Paginated results,list for orders dict list
        
        Example::
            result = client.user.get_orders(status=2)
            print(f"common {result.total} completed orders")
        """
        params = {
            "page": page,
            "page_size": page_size,
            "status": status,
            "project_id": project_id,
        }
        if _is_async_context():
            return self._async_get_orders(params)
        return self._sync_get_orders(params)
    
    async def _async_get_orders(self, params: dict) -> PageResult:
        data = await self._client._async_request("GET", "/api/v1/openapi/orders", params=params)
        return _parse_page_result(data)
    
    def _sync_get_orders(self, params: dict) -> PageResult:
        data = self._client._sync_request("GET", "/api/v1/openapi/orders", params=params)
        return _parse_page_result(data)
    
    # ===== Code reception polling (advanced method)=====
    
    def wait_for_code(
        self,
        order_no: str,
        timeout: int = 300,
        interval: float = 3.0,
        on_poll: Optional[callable] = None,
    ):
        """
        Waiting for code reception (with automatic polling), intelligent identification and synchronization/asynchronous context
        
        will automatically occur every interval Query once every second until verification code is received or timeout occurs.
        
        Args:
            order_no: order number
            timeout: Maximum wait time (seconds), default 300
            interval: Polling interval (seconds), default 3.0
            on_poll: The callback function for each polling, receives OrderCode Parameters (optional)
        
        Returns:
            OrderCode: final result,status for 'success' or 'timeout'/'cancelled'
        
        Synchronous call example::
            order = client.user.create_order('twitter')
            result = client.user.wait_for_code(order.order_no, timeout=300)
            if result.status == 'success':
                print(f"✅ Verification code: {result.verification_code}")
            else:
                print(f"❌ Failed to receive code: {result.status}")
        
        Asynchronous call example::
            order = await client.user.create_order('twitter')
            result = await client.user.wait_for_code(order.order_no, timeout=300)
            if result.status == 'success':
                print(f"✅ Verification code: {result.verification_code}")
        """
        if _is_async_context():
            return self._async_wait_for_code(order_no, timeout, interval, on_poll)
        return self._sync_wait_for_code(order_no, timeout, interval, on_poll)
    
    async def _async_wait_for_code(
        self,
        order_no: str,
        timeout: int,
        interval: float,
        on_poll: Optional[callable],
    ) -> OrderCode:
        """Asynchronous polling waiting for verification code"""
        start = time.time()
        while True:
            result = await self._async_get_order_code(order_no)
            
            if on_poll:
                if asyncio.iscoroutinefunction(on_poll):
                    await on_poll(result)
                else:
                    on_poll(result)
            
            if result.status in ("success", "timeout", "cancelled"):
                return result
            
            elapsed = time.time() - start
            if elapsed >= timeout:
                return result
            
            await asyncio.sleep(interval)
    
    def _sync_wait_for_code(
        self,
        order_no: str,
        timeout: int,
        interval: float,
        on_poll: Optional[callable],
    ) -> OrderCode:
        """Synchronous polling waiting for verification code"""
        start = time.time()
        while True:
            result = self._sync_get_order_code(order_no)
            
            if on_poll:
                on_poll(result)
            
            if result.status in ("success", "timeout", "cancelled"):
                return result
            
            elapsed = time.time() - start
            if elapsed >= timeout:
                return result
            
            time.sleep(interval)
    
    # ===== Buy email =====
    
    def purchase_emails(
        self,
        project_code: str,
        quantity: int,
        email_type: Optional[str] = None,
        domain: Optional[str] = None,
        variant_mode: Optional[str] = None,
    ):
        """
        Buy email
        
        Args:
            project_code: Project code
            quantity: Purchase quantity (1-10000)
            email_type: Email type (optional)
            domain: Specify domain name (optional)
            variant_mode: Google variant mode (optional, only email_type=google_variant valid at the time): dot=dot variant / plus=+number variant / mixed=Mixed variants / all=randomly selected
        
        Returns:
            dict: Purchase results include purchases list,total_cost,balance_after
        
        Example::
            result = client.user.purchase_emails('twitter', quantity=5, email_type='ms_graph')
            for item in result['purchases']:
                print(item['email_address'], item['token'])
        """
        body: Dict[str, Any] = {
            "project_code": project_code,
            "quantity": quantity,
        }
        if email_type:
            body["email_type"] = email_type
        if domain:
            body["domain"] = domain
        if variant_mode:
            body["variant_mode"] = variant_mode
        
        if _is_async_context():
            return self._async_purchase_emails(body)
        return self._sync_purchase_emails(body)
    
    async def _async_purchase_emails(self, body: dict) -> dict:
        return await self._client._async_request("POST", "/api/v1/openapi/email/purchase", json_data=body)
    
    def _sync_purchase_emails(self, body: dict) -> dict:
        return self._client._sync_request("POST", "/api/v1/openapi/email/purchase", json_data=body)
    
    def get_purchases(
        self,
        page: int = 1,
        page_size: int = 20,
        project_id: Optional[int] = None,
        tag_id: Optional[int] = None,
        keyword: Optional[str] = None,
        user_disabled: Optional[int] = None,
    ):
        """
        Get the purchased email list
        
        Args:
            page: page number
            page_size: Quantity per page
            project_id: by project ID filter
            tag_id: by tag ID filter
            keyword: Email address keyword search
            user_disabled: Disabled state:0=normal 1=Disabled
        
        Returns:
            PageResult: Paginated results,list for PurchaseItem list
        
        Example::
            result = client.user.get_purchases(tag_id=1, keyword="outlook")
            for item in result.list:
                print(item.email_address, item.token, item.tag_name)
        """
        params = {
            "page": page,
            "page_size": page_size,
            "project_id": project_id,
            "tag_id": tag_id,
            "keyword": keyword,
            "user_disabled": user_disabled,
        }
        if _is_async_context():
            return self._async_get_purchases(params)
        return self._sync_get_purchases(params)
    
    async def _async_get_purchases(self, params: dict) -> PageResult:
        data = await self._client._async_request("GET", "/api/v1/openapi/email/purchases", params=params)
        return _parse_page_result(data, _parse_purchase_item)
    
    def _sync_get_purchases(self, params: dict) -> PageResult:
        data = self._client._sync_request("GET", "/api/v1/openapi/email/purchases", params=params)
        return _parse_page_result(data, _parse_purchase_item)
    
    def get_token_code(self, token: str):
        """
        pass Token Get the latest verification code (purchased email address)
        
        Args:
            token: Purchased email address token
        
        Returns:
            TokenCode: Verification code result
        
        Example::
            result = client.user.get_token_code("tok_abc123def456")
            if result.has_new_mail:
                print(f"Verification code: {result.verification_code}")
        """
        if _is_async_context():
            return self._async_get_token_code(token)
        return self._sync_get_token_code(token)
    
    async def _async_get_token_code(self, token: str) -> TokenCode:
        data = await self._client._async_request(
            "GET", f"/api/v1/openapi/email/token/{token}/code"
        )
        return _parse_token_code(data)
    
    def _sync_get_token_code(self, token: str) -> TokenCode:
        data = self._client._sync_request(
            "GET", f"/api/v1/openapi/email/token/{token}/code"
        )
        return _parse_token_code(data)

    def check_token_alive(self, token: str):
        """
        pass Token Test whether the purchased mailbox can obtain the mailing list normally

        Args:
            token: Purchased email address token

        Returns:
            TokenAliveResult: Activity test results

        Example::
            result = client.user.check_token_alive("tok_abc123def456")
            print(result.alive, result.message)
        """
        if _is_async_context():
            return self._async_check_token_alive(token)
        return self._sync_check_token_alive(token)

    async def _async_check_token_alive(self, token: str) -> TokenAliveResult:
        data = await self._client._async_request(
            "GET", f"/api/v1/openapi/email/token/{token}/alive"
        )
        return _parse_token_alive_result(data)

    def _sync_check_token_alive(self, token: str) -> TokenAliveResult:
        data = self._client._sync_request(
            "GET", f"/api/v1/openapi/email/token/{token}/alive"
        )
        return _parse_token_alive_result(data)
    
    def wait_for_token_code(
        self,
        token: str,
        timeout: int = 300,
        interval: float = 3.0,
        on_poll: Optional[callable] = None,
    ):
        """
        wait Token Verification code for email (with automatic polling), intelligent identification and synchronization/asynchronous context
        
        Args:
            token: Purchased email address token
            timeout: Maximum waiting time (seconds)
            interval: Polling interval (seconds)
            on_poll: callback for each poll
        
        Returns:
            TokenCode: final result
        
        Example::
            result = client.user.wait_for_token_code("tok_abc123", timeout=120)
            if result.has_new_mail:
                print(f"✅ Verification code: {result.verification_code}")
        """
        if _is_async_context():
            return self._async_wait_for_token_code(token, timeout, interval, on_poll)
        return self._sync_wait_for_token_code(token, timeout, interval, on_poll)
    
    async def _async_wait_for_token_code(
        self, token: str, timeout: int, interval: float, on_poll
    ) -> TokenCode:
        start = time.time()
        while True:
            result = await self._async_get_token_code(token)
            
            if on_poll:
                if asyncio.iscoroutinefunction(on_poll):
                    await on_poll(result)
                else:
                    on_poll(result)
            
            if result.has_new_mail:
                return result
            
            if time.time() - start >= timeout:
                return result
            
            await asyncio.sleep(interval)
    
    def _sync_wait_for_token_code(
        self, token: str, timeout: int, interval: float, on_poll
    ) -> TokenCode:
        start = time.time()
        while True:
            result = self._sync_get_token_code(token)
            
            if on_poll:
                on_poll(result)
            
            if result.has_new_mail:
                return result
            
            if time.time() - start >= timeout:
                return result
            
            time.sleep(interval)
    
    # ===== Purchased email list and details =====
    
    def get_token_mails(self, token: str):
        """
        pass Token Get the mailing list of purchased mailboxes
        
        Args:
            token: Purchased email address token
        
        Returns:
            TokenMailList: Mailing list results, including email_address,project,warranty_until,mails
        
        Example::
            result = client.user.get_token_mails("tok_abc123def456")
            print(f"Mail: {result.email_address}, project: {result.project}")
            for mail in result.mails:
                print(f"  [{mail.received_at}] {mail.from_addr}: {mail.subject}")
        """
        if _is_async_context():
            return self._async_get_token_mails(token)
        return self._sync_get_token_mails(token)
    
    async def _async_get_token_mails(self, token: str) -> TokenMailList:
        data = await self._client._async_request(
            "GET", f"/api/v1/openapi/email/token/{token}/mails"
        )
        return _parse_token_mail_list(data)
    
    def _sync_get_token_mails(self, token: str) -> TokenMailList:
        data = self._client._sync_request(
            "GET", f"/api/v1/openapi/email/token/{token}/mails"
        )
        return _parse_token_mail_list(data)
    
    def get_token_mail_detail(self, token: str, message_id: str):
        """
        pass Token Get the email details of the purchased email address
        
        Args:
            token: Purchased email address token
            message_id: mail ID(from get_token_mails obtained from the returned list)
        
        Returns:
            TokenMailDetail: Email details, including message_id,from_addr,to,subject,body_text,body_html,verification_code
        
        Example::
            detail = client.user.get_token_mail_detail("tok_abc123", "AAMkAGI2...")
            print(f"theme: {detail.subject}")
            print(f"text: {detail.body_text}")
            if detail.verification_code:
                print(f"Verification code: {detail.verification_code}")
        """
        if _is_async_context():
            return self._async_get_token_mail_detail(token, message_id)
        return self._sync_get_token_mail_detail(token, message_id)
    
    async def _async_get_token_mail_detail(self, token: str, message_id: str) -> TokenMailDetail:
        data = await self._client._async_request(
            "GET", f"/api/v1/openapi/email/token/{token}/mails/{message_id}"
        )
        return _parse_token_mail_detail(data)
    
    def _sync_get_token_mail_detail(self, token: str, message_id: str) -> TokenMailDetail:
        data = self._client._sync_request(
            "GET", f"/api/v1/openapi/email/token/{token}/mails/{message_id}"
        )
        return _parse_token_mail_detail(data)
    
    # ===== representation =====
    
    def create_appeal(
        self,
        appeal_type: int,
        reason: str,
        description: str,
        order_id: Optional[int] = None,
        purchase_id: Optional[int] = None,
        evidence_urls: Optional[List[str]] = None,
    ):
        """
        Submit a representation
        
        Args:
            appeal_type: Complaint type:1=Receive code order 2=Buy email
            reason: State the reasons for the complaint, such as 'no_code', 'wrong_code', 'email_invalid'
            description: Detailed description
            order_id: Receive code order ID(appeal_type=1 Required)
            purchase_id: Purchase history ID(appeal_type=2 Required)
            evidence_urls: Evidence screenshot URL list (optional)
        
        Returns:
            dict: Include appeal_no dictionary
        
        Example::
            result = client.user.create_appeal(
                appeal_type=1,
                order_id=123,
                reason='no_code',
                description='wait 5 No verification code received in minutes'
            )
            print(f"Complaint number: {result['appeal_no']}")
        """
        body: Dict[str, Any] = {
            "appeal_type": appeal_type,
            "reason": reason,
            "description": description,
        }
        if order_id is not None:
            body["order_id"] = order_id
        if purchase_id is not None:
            body["purchase_id"] = purchase_id
        if evidence_urls:
            body["evidence_urls"] = evidence_urls
        
        if _is_async_context():
            return self._async_create_appeal(body)
        return self._sync_create_appeal(body)
    
    async def _async_create_appeal(self, body: dict) -> dict:
        return await self._client._async_request(
            "POST", "/api/v1/openapi/appeal/create", json_data=body
        )
    
    def _sync_create_appeal(self, body: dict) -> dict:
        return self._client._sync_request(
            "POST", "/api/v1/openapi/appeal/create", json_data=body
        )

    # ===== Disable management of purchased mailboxes =====

    def set_purchase_disabled(self, purchase_id: int, disabled: int):
        """
        Set the disabled status of the purchased email address

        Args:
            purchase_id: Purchased email address ID
            disabled: Disabled state:0=enable 1=Disable

        Returns:
            None

        Example::
            client.user.set_purchase_disabled(1, 1)  # Disable
            client.user.set_purchase_disabled(1, 0)  # enable
        """
        body = {"disabled": disabled}
        if _is_async_context():
            return self._async_set_purchase_disabled(purchase_id, body)
        return self._sync_set_purchase_disabled(purchase_id, body)

    async def _async_set_purchase_disabled(self, purchase_id: int, body: dict) -> None:
        await self._client._async_request(
            "PUT", f"/api/v1/openapi/email/purchases/{purchase_id}/disabled", json_data=body
        )

    def _sync_set_purchase_disabled(self, purchase_id: int, body: dict) -> None:
        self._client._sync_request(
            "PUT", f"/api/v1/openapi/email/purchases/{purchase_id}/disabled", json_data=body
        )

    def batch_set_purchase_disabled(self, ids: List[int], disabled: int):
        """
        Set the disabled status of purchased mailboxes in batches

        Args:
            ids: Purchased email address ID list
            disabled: Disabled state:0=enable 1=Disable

        Returns:
            None

        Example::
            client.user.batch_set_purchase_disabled([1, 2, 3], 1)  # Batch disable
        """
        body = {"ids": ids, "disabled": disabled}
        if _is_async_context():
            return self._async_batch_set_purchase_disabled(body)
        return self._sync_batch_set_purchase_disabled(body)

    async def _async_batch_set_purchase_disabled(self, body: dict) -> None:
        await self._client._async_request(
            "POST", "/api/v1/openapi/email/purchases/batch-disabled", json_data=body
        )

    def _sync_batch_set_purchase_disabled(self, body: dict) -> None:
        self._client._sync_request(
            "POST", "/api/v1/openapi/email/purchases/batch-disabled", json_data=body
        )

    # ===== Purchased email label management =====

    def set_purchase_tag(
        self,
        purchase_id: int,
        tag_id: Optional[int] = None,
        tag_name: Optional[str] = None,
    ):
        """
        Set a purchased email label

        Args:
            purchase_id: Purchased email address ID
            tag_id: Label ID(and tag_name Choose one of the two, pass 0 means remove tag)
            tag_name: tag name (with tag_id Choose one of the two)

        Returns:
            None

        Example::
            client.user.set_purchase_tag(1, tag_id=1)
            client.user.set_purchase_tag(1, tag_name="Main account")
            client.user.set_purchase_tag(1, tag_id=0)  # Remove tag
        """
        body: Dict[str, Any] = {}
        if tag_id is not None:
            body["tag_id"] = tag_id
        if tag_name is not None:
            body["tag_name"] = tag_name
        if _is_async_context():
            return self._async_set_purchase_tag(purchase_id, body)
        return self._sync_set_purchase_tag(purchase_id, body)

    async def _async_set_purchase_tag(self, purchase_id: int, body: dict) -> None:
        await self._client._async_request(
            "PUT", f"/api/v1/openapi/email/purchases/{purchase_id}/tag", json_data=body
        )

    def _sync_set_purchase_tag(self, purchase_id: int, body: dict) -> None:
        self._client._sync_request(
            "PUT", f"/api/v1/openapi/email/purchases/{purchase_id}/tag", json_data=body
        )

    def batch_set_purchase_tag(
        self,
        ids: List[int],
        tag_id: Optional[int] = None,
        tag_name: Optional[str] = None,
    ):
        """
        Set purchased email labels in batches

        Args:
            ids: Purchased email address ID list
            tag_id: Label ID(and tag_name Choose one of the two, pass 0 means remove tag)
            tag_name: tag name (with tag_id Choose one of the two)

        Returns:
            None

        Example::
            client.user.batch_set_purchase_tag([1, 2, 3], tag_name="Main account")
        """
        body: Dict[str, Any] = {"ids": ids}
        if tag_id is not None:
            body["tag_id"] = tag_id
        if tag_name is not None:
            body["tag_name"] = tag_name
        if _is_async_context():
            return self._async_batch_set_purchase_tag(body)
        return self._sync_batch_set_purchase_tag(body)

    async def _async_batch_set_purchase_tag(self, body: dict) -> None:
        await self._client._async_request(
            "POST", "/api/v1/openapi/email/purchases/batch-tag", json_data=body
        )

    def _sync_batch_set_purchase_tag(self, body: dict) -> None:
        self._client._sync_request(
            "POST", "/api/v1/openapi/email/purchases/batch-tag", json_data=body
        )

    def api_get_purchases(
        self,
        count: int,
        tag_id: Optional[int] = None,
        tag_name: Optional[str] = None,
        mark_tag_id: Optional[int] = None,
        mark_tag_name: Optional[str] = None,
    ):
        """
        Get purchased email addresses by label (API issued)

        Only return tags that are not disabled and limit_type=1(can be sent to) email address.
        You can choose to mark the obtained mailbox with another label.

        Args:
            count: get quantity (1-100)
            tag_id: by tag ID Filter (with tag_name Choose one of the two)
            tag_name: Filter by tag name (with tag_id Choose one of the two)
            mark_tag_id: After retrieval, mark the mailbox with this label ID(and mark_tag_name Choose one of the two)
            mark_tag_name: After retrieval, mark the mailbox with this label name (the same as mark_tag_id Choose one of the two)

        Returns:
            List[PurchaseItem]: Purchased email list

        Example::
            items = client.user.api_get_purchases(5, tag_name="Main account", mark_tag_name="Already used")
            for item in items:
                print(item.email_address, item.token)
        """
        body: Dict[str, Any] = {"count": count}
        if tag_id is not None:
            body["tag_id"] = tag_id
        if tag_name is not None:
            body["tag_name"] = tag_name
        if mark_tag_id is not None:
            body["mark_tag_id"] = mark_tag_id
        if mark_tag_name is not None:
            body["mark_tag_name"] = mark_tag_name
        if _is_async_context():
            return self._async_api_get_purchases(body)
        return self._sync_api_get_purchases(body)

    async def _async_api_get_purchases(self, body: dict) -> List[PurchaseItem]:
        data = await self._client._async_request(
            "POST", "/api/v1/openapi/email/purchases/api-get", json_data=body
        )
        return [_parse_purchase_item(i) for i in data]

    def _sync_api_get_purchases(self, body: dict) -> List[PurchaseItem]:
        data = self._client._sync_request(
            "POST", "/api/v1/openapi/email/purchases/api-get", json_data=body
        )
        return [_parse_purchase_item(i) for i in data]

    # ===== tag management =====

    def create_tag(self, name: str, limit_type: int, remark: Optional[str] = None):
        """
        Create mailbox labels

        Args:
            name: Tag name (unique under user)
            limit_type: Restriction type:0=Not issued 1=Can be issued
            remark: Remarks (optional)

        Returns:
            TagItem: Created label information

        Example::
            tag = client.user.create_tag("Main account", limit_type=1, remark="Main mailbox pool")
            print(f"Label ID: {tag.id}, name: {tag.name}")
        """
        body: Dict[str, Any] = {"name": name, "limit_type": limit_type}
        if remark is not None:
            body["remark"] = remark
        if _is_async_context():
            return self._async_create_tag(body)
        return self._sync_create_tag(body)

    async def _async_create_tag(self, body: dict) -> "TagItem":
        data = await self._client._async_request(
            "POST", "/api/v1/openapi/email/tags", json_data=body
        )
        return _parse_tag_item(data)

    def _sync_create_tag(self, body: dict) -> "TagItem":
        data = self._client._sync_request(
            "POST", "/api/v1/openapi/email/tags", json_data=body
        )
        return _parse_tag_item(data)

    def get_tags(self):
        """
        Get a list of all tags

        Returns:
            List[TagItem]: tag list

        Example::
            tags = client.user.get_tags()
            for tag in tags:
                print(tag.id, tag.name, tag.limit_type, tag.purchase_count)
        """
        if _is_async_context():
            return self._async_get_tags()
        return self._sync_get_tags()

    async def _async_get_tags(self) -> List["TagItem"]:
        data = await self._client._async_request("GET", "/api/v1/openapi/email/tags")
        return [_parse_tag_item(i) for i in data]

    def _sync_get_tags(self) -> List["TagItem"]:
        data = self._client._sync_request("GET", "/api/v1/openapi/email/tags")
        return [_parse_tag_item(i) for i in data]

    def update_tag(
        self,
        tag_id_or_name: Union[int, str],
        limit_type: int,
        name: Optional[str] = None,
        remark: Optional[str] = None,
    ):
        """
        Update label

        Args:
            tag_id_or_name: Label ID(number) or label name (string)
            limit_type: Restriction type:0=Not issued 1=Can be issued
            name: New label name (optional)
            remark: Remarks (optional)

        Returns:
            None

        Example::
            client.user.update_tag(1, limit_type=1, name="Alternate number")
            client.user.update_tag("Main account", limit_type=0)
        """
        body: Dict[str, Any] = {"limit_type": limit_type}
        if name is not None:
            body["name"] = name
        if remark is not None:
            body["remark"] = remark
        if _is_async_context():
            return self._async_update_tag(tag_id_or_name, body)
        return self._sync_update_tag(tag_id_or_name, body)

    async def _async_update_tag(self, tag_id_or_name: Union[int, str], body: dict) -> None:
        await self._client._async_request(
            "PUT", f"/api/v1/openapi/email/tags/{tag_id_or_name}", json_data=body
        )

    def _sync_update_tag(self, tag_id_or_name: Union[int, str], body: dict) -> None:
        self._client._sync_request(
            "PUT", f"/api/v1/openapi/email/tags/{tag_id_or_name}", json_data=body
        )

    def delete_tag(self, tag_id_or_name: Union[int, str]):
        """
        Delete tag

        After deletion, the purchased mailbox under the label will become unlabeled.

        Args:
            tag_id_or_name: Label ID(number) or label name (string)

        Returns:
            None

        Example::
            client.user.delete_tag(1)
            client.user.delete_tag("Already used")
        """
        if _is_async_context():
            return self._async_delete_tag(tag_id_or_name)
        return self._sync_delete_tag(tag_id_or_name)

    async def _async_delete_tag(self, tag_id_or_name: Union[int, str]) -> None:
        await self._client._async_request(
            "DELETE", f"/api/v1/openapi/email/tags/{tag_id_or_name}"
        )

    def _sync_delete_tag(self, tag_id_or_name: Union[int, str]) -> None:
        self._client._sync_request(
            "DELETE", f"/api/v1/openapi/email/tags/{tag_id_or_name}"
        )
