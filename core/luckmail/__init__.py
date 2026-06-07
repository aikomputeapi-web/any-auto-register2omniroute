"""
LuckMailSdk - Python SDK for LuckMail Email System
Support synchronization/Asynchronous dual mode, intelligent identification and automatic switching of calling context
"""

from .client import LuckMailClient
from .user import UserAPI
from .supplier import SupplierAPI
from .exceptions import (
    LuckMailError,
    AuthError,
    APIError,
    NetworkError,
    TimeoutError,
)
from .models import (
    UserInfo,
    EmailItem,
    ProjectItem,
    OrderInfo,
    OrderCode,
    PurchaseItem,
    TagItem,
    TokenCode,
    TokenAliveResult,
    TokenMailItem,
    TokenMailList,
    TokenMailDetail,
    AppealInfo,
    SupplierProfile,
    SupplierEmailItem,
    AppealItem,
    DashboardSummary,
)

__version__ = "1.2.1"
__all__ = [
    "LuckMailClient",
    "UserAPI",
    "SupplierAPI",
    "LuckMailError",
    "AuthError",
    "APIError",
    "NetworkError",
    "TimeoutError",
    "UserInfo",
    "EmailItem",
    "ProjectItem",
    "OrderInfo",
    "OrderCode",
    "PurchaseItem",
    "TagItem",
    "TokenCode",
    "TokenAliveResult",
    "TokenMailItem",
    "TokenMailList",
    "TokenMailDetail",
    "AppealInfo",
    "SupplierProfile",
    "SupplierEmailItem",
    "AppealItem",
    "DashboardSummary",
]
