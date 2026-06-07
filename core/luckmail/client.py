"""
LuckMailClient - Main client entrance

Integrate client and supplier API, providing a unified access entrance.
Support synchronization/Asynchronous dual mode, intelligent identification of calling context.
"""

from typing import Optional

from .http_client import LuckMailHttpClient
from .user import UserAPI
from .supplier import SupplierAPI


class LuckMailClient:
    """
    LuckMail SDK main client
    
    Provide client (user) and supplier side (supplier) two sets API Access entrance.
    all API All methods support synchronization/Asynchronous dual mode, automatically recognized according to the calling context,
    No manual differentiation is required, significantly reducing access costs.
    
    Args:
        base_url: API Base URL,like https://your-domain.com
        api_key: API Key(Generated on the platform’s “Personal Settings” page)
        api_secret: API Secret(optional, for HMAC Signature verification, higher security)
        timeout: Request timeout (seconds), default 30
        use_hmac: Whether to use HMAC Signature verification, default False
    
    Client example (synchronization)::
    
        from luckmail import LuckMailClient
        
        client = LuckMailClient(
            base_url="https://your-domain.com",
            api_key="your_api_key_here"
        )
        
        # Check balance
        balance = client.user.get_balance()
        print(f"Balance: {balance}")
        
        # Receive code (all done in one line)
        code = client.user.create_and_wait('twitter')
        print(f"Verification code: {code.verification_code}")
    
    Client example (asynchronous)::
    
        import asyncio
        from luckmail import LuckMailClient
        
        client = LuckMailClient(
            base_url="https://your-domain.com",
            api_key="your_api_key_here"
        )
        
        async def main():
            balance = await client.user.get_balance()
            print(f"Balance: {balance}")
            
            code = await client.user.create_and_wait('twitter')
            print(f"Verification code: {code.verification_code}")
        
        asyncio.run(main())
    
    Supplier side example::
    
        # View data dashboard
        summary = client.supplier.get_dashboard()
        print(f"Receive code today: {summary.today_assigned}")
        
        # Handling representations
        client.supplier.reply_appeal("APL001", result=1, reply="Agree to refund")
    """
    
    def __init__(
        self,
        base_url: str,
        api_key: str,
        api_secret: Optional[str] = None,
        timeout: float = 30.0,
        use_hmac: bool = False,
        proxy_url: Optional[str] = None,
    ):
        self._http = LuckMailHttpClient(
            base_url=base_url,
            api_key=api_key,
            api_secret=api_secret,
            timeout=timeout,
            use_hmac=use_hmac,
            proxy_url=proxy_url,
        )
        # client API
        self.user = UserAPI(self._http)
        # Supplier side API
        self.supplier = SupplierAPI(self._http)
    
    # ===== Shortcut methods (common operations on the user side)=====
    
    def create_and_wait(
        self,
        project_code: str,
        email_type: Optional[str] = None,
        domain: Optional[str] = None,
        specified_email: Optional[str] = None,
        variant_mode: Optional[str] = None,
        timeout: int = 300,
        interval: float = 3.0,
        on_poll=None,
    ):
        """
        Create a code pickup order and wait for the verification code (one-stop method)
        
        Automatically create orders and poll for verification codes, intelligent identification and synchronization/Asynchronous context.
        
        Args:
            project_code: Project coding, such as 'twitter', 'facebook'
            email_type: Email type (optional)
            domain: Specify domain name (optional)
            specified_email: Specify email address (optional)
            variant_mode: Google variant mode (optional, only email_type=google_variant valid at the time): dot / plus / mixed / all
            timeout: Maximum wait time (seconds), default 300
            interval: Polling interval (seconds), default 3.0
            on_poll: Callback function for each poll (optional)
        
        Returns:
            OrderCode: Verification code result
        
        Synchronization example::
        
            result = client.create_and_wait('twitter')
            if result.status == 'success':
                print(f"✅ Verification code: {result.verification_code}")
                print(f"📧 from: {result.mail_from}")
            else:
                print(f"❌ Failed to receive code: {result.status}")
        
        Asynchronous example::
        
            result = await client.create_and_wait('twitter', email_type='ms_graph')
            if result.status == 'success':
                print(f"✅ Verification code: {result.verification_code}")
        
        Example with progress callback::
        
            def on_poll(code_result):
                print(f"Polling... state: {code_result.status}")
            
            result = client.create_and_wait('twitter', on_poll=on_poll)
        """
        from .http_client import _is_async_context
        if _is_async_context():
            return self._async_create_and_wait(
                project_code, email_type, domain, specified_email, variant_mode,
                timeout, interval, on_poll
            )
        return self._sync_create_and_wait(
            project_code, email_type, domain, specified_email, variant_mode,
            timeout, interval, on_poll
        )
    
    async def _async_create_and_wait(
        self, project_code, email_type, domain, specified_email, variant_mode,
        timeout, interval, on_poll
    ):
        """Create asynchronously and wait for verification code"""
        body = {"project_code": project_code}
        if email_type:
            body["email_type"] = email_type
        if domain:
            body["domain"] = domain
        if specified_email:
            body["specified_email"] = specified_email
        if variant_mode:
            body["variant_mode"] = variant_mode
        
        order = await self.user._async_create_order(body)
        return await self.user._async_wait_for_code(
            order.order_no, timeout, interval, on_poll
        )
    
    def _sync_create_and_wait(
        self, project_code, email_type, domain, specified_email, variant_mode,
        timeout, interval, on_poll
    ):
        """Create synchronously and wait for verification code"""
        body = {"project_code": project_code}
        if email_type:
            body["email_type"] = email_type
        if domain:
            body["domain"] = domain
        if specified_email:
            body["specified_email"] = specified_email
        if variant_mode:
            body["variant_mode"] = variant_mode
        
        order = self.user._sync_create_order(body)
        return self.user._sync_wait_for_code(
            order.order_no, timeout, interval, on_poll
        )
    
    def close(self):
        """Close client (sync)"""
        self._http.close()
    
    async def aclose(self):
        """Close the client (asynchronously)"""
        await self._http.aclose()
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.aclose()
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
    
    def __repr__(self) -> str:
        return (
            f"LuckMailClient(base_url={self._http.base_url!r}, "
            f"api_key={self._http.api_key[:8]}...)"
        )
