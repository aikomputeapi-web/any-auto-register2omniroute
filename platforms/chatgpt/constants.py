"""
constant definition
"""

import random
from datetime import datetime
from enum import Enum
from typing import Dict, List, Tuple


# ============================================================================
# enumeration type
# ============================================================================

class AccountStatus(str, Enum):
    """Account status"""
    ACTIVE = "active"
    EXPIRED = "expired"
    BANNED = "banned"
    FAILED = "failed"


class TaskStatus(str, Enum):
    """Task status"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class EmailServiceType(str, Enum):
    """Email service type"""
    TEMPMAIL = "tempmail"
    OUTLOOK = "outlook"
    CUSTOM_DOMAIN = "custom_domain"
    TEMP_MAIL = "temp_mail"


# ============================================================================
# application constants
# ============================================================================

APP_NAME = "OpenAI/Codex CLI Automatic registration system"
APP_VERSION = "2.0.0"
APP_DESCRIPTION = "Automatic registration OpenAI/Codex CLI Account system"

# ============================================================================
# OpenAI OAuth Related constants
# ============================================================================

# OAuth parameter
OAUTH_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
OAUTH_AUTH_URL = "https://auth.openai.com/oauth/authorize"
OAUTH_TOKEN_URL = "https://auth.openai.com/oauth/token"
OAUTH_REDIRECT_URI = "http://localhost:1455/auth/callback"
OAUTH_SCOPE = "openid email profile offline_access"

# OpenAI API endpoint
OPENAI_API_ENDPOINTS = {
    "sentinel": "https://sentinel.openai.com/backend-api/sentinel/req",
    "signup": "https://auth.openai.com/api/accounts/authorize/continue",
    "register": "https://auth.openai.com/api/accounts/user/register",
    "password_verify": "https://auth.openai.com/api/accounts/password/verify",
    "passwordless_send_otp": "https://auth.openai.com/api/accounts/passwordless/send-otp",
    "send_otp": "https://auth.openai.com/api/accounts/email-otp/send",
    "validate_otp": "https://auth.openai.com/api/accounts/email-otp/validate",
    "create_account": "https://auth.openai.com/api/accounts/create_account",
    "select_workspace": "https://auth.openai.com/api/accounts/workspace/select",
    "select_organization": "https://auth.openai.com/api/accounts/organization/select",
}

# OpenAI Page type (used to determine account status)
OPENAI_PAGE_TYPES = {
    "EMAIL_OTP_VERIFICATION": "email_otp_verification",  # Already registered account, need OTP verify
    "PASSWORD_REGISTRATION": "create_account_password",  # New account, need to set a password
    "LOGIN_PASSWORD": "login_password",  # Login process requires entering password
}

# ============================================================================
# Email service related constants
# ============================================================================

# Tempmail.lol API endpoint
TEMPMAIL_API_ENDPOINTS = {
    "create_inbox": "/inbox/create",
    "get_inbox": "/inbox",
}

# Custom domain name email API endpoint
CUSTOM_DOMAIN_API_ENDPOINTS = {
    "get_config": "/api/config",
    "create_email": "/api/emails/generate",
    "list_emails": "/api/emails",
    "get_email_messages": "/api/emails/{emailId}",
    "delete_email": "/api/emails/{emailId}",
    "get_message": "/api/emails/{emailId}/{messageId}",
}

# Email service default configuration
EMAIL_SERVICE_DEFAULTS = {
    "tempmail": {
        "base_url": "https://api.tempmail.lol/v2",
        "timeout": 30,
        "max_retries": 3,
    },
    "outlook": {
        "imap_server": "outlook.office365.com",
        "imap_port": 993,
        "smtp_server": "smtp.office365.com",
        "smtp_port": 587,
        "timeout": 30,
    },
    "custom_domain": {
        "base_url": "",  # Requires user configuration
        "api_key_header": "X-API-Key",
        "timeout": 30,
        "max_retries": 3,
    }
}

# ============================================================================
# Registration process related constants
# ============================================================================

# Verification code related
OTP_CODE_PATTERN = r"(?<!\d)(\d{6})(?!\d)"
OTP_MAX_ATTEMPTS = 40  # Maximum number of polls

# Verification code extraction regular pattern (enhanced version)
# Simple match: any 6 digits
OTP_CODE_SIMPLE_PATTERN = r"(?<!\d)(\d{6})(?!\d)"
# Semantic matching: CAPTCHA with context (e.g. "code is 123456", "Verification code 123456")
OTP_CODE_SEMANTIC_PATTERN = r'(?:code\s+is|Verification code[is for]?\s*[::]?\s*)(\d{6})'

# OpenAI Verify email sender
OPENAI_EMAIL_SENDERS = [
    "noreply@openai.com",
    "no-reply@openai.com",
    "@openai.com",     # Exact domain name matching
    ".openai.com",     # Subdomain matching (e.g. otp@tm1.openai.com)
]

# OpenAI Verification email keywords
OPENAI_VERIFICATION_KEYWORDS = [
    "verify your email",
    "verification code",
    "Verification code",
    "your openai code",
    "code is",
    "one-time code",
]

# Password generation
PASSWORD_CHARSET = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789!@#$%"
DEFAULT_PASSWORD_LENGTH = 16

# User information generation (for registration)
MIN_REGISTRATION_AGE = 20
MAX_REGISTRATION_AGE = 45

# Common English names
FIRST_NAMES = [
    "James", "John", "Robert", "Michael", "William", "David", "Richard", "Joseph", "Thomas", "Charles",
    "Emma", "Olivia", "Ava", "Isabella", "Sophia", "Mia", "Charlotte", "Amelia", "Harper", "Evelyn",
    "Alex", "Jordan", "Taylor", "Morgan", "Casey", "Riley", "Jamie", "Avery", "Quinn", "Skyler",
    "Liam", "Noah", "Ethan", "Lucas", "Mason", "Oliver", "Elijah", "Aiden", "Henry", "Sebastian",
    "Grace", "Lily", "Chloe", "Zoey", "Nora", "Aria", "Hazel", "Aurora", "Stella", "Ivy"
]

def generate_random_user_info() -> dict:
    """
    Generate random user information

    Returns:
        Include name and birthdate dictionary
    """
    # Randomly select names
    name = random.choice(FIRST_NAMES)

    # Generate a random birthday (20-45age)
    current_year = datetime.now().year
    birth_year = random.randint(current_year - MAX_REGISTRATION_AGE, current_year - MIN_REGISTRATION_AGE)
    birth_month = random.randint(1, 12)
    # Determine the number of days according to the month
    if birth_month in [1, 3, 5, 7, 8, 10, 12]:
        birth_day = random.randint(1, 31)
    elif birth_month in [4, 6, 9, 11]:
        birth_day = random.randint(1, 30)
    else:
        # 2month, simplified processing
        birth_day = random.randint(1, 28)

    birthdate = f"{birth_year}-{birth_month:02d}-{birth_day:02d}"

    return {
        "name": name,
        "birthdate": birthdate
    }

# Keep default values ​​for compatibility
DEFAULT_USER_INFO = {
    "name": "Neo",
    "birthdate": "2000-02-20",
}

# ============================================================================
# Agent related constants
# ============================================================================

PROXY_TYPES = ["http", "socks5", "socks5h"]
DEFAULT_PROXY_CONFIG = {
    "enabled": False,
    "type": "http",
    "host": "127.0.0.1",
    "port": 7890,
}

# ============================================================================
# Database related constants
# ============================================================================

# Database table name
DB_TABLE_NAMES = {
    "accounts": "accounts",
    "email_services": "email_services",
    "registration_tasks": "registration_tasks",
    "settings": "settings",
}

# Default setting
DEFAULT_SETTINGS = [
    # (key, value, description, category)
    ("system.name", APP_NAME, "System name", "general"),
    ("system.version", APP_VERSION, "System version", "general"),
    ("logs.retention_days", "30", "Log retention days", "general"),
    ("openai.client_id", OAUTH_CLIENT_ID, "OpenAI OAuth Client ID", "openai"),
    ("openai.auth_url", OAUTH_AUTH_URL, "OpenAI Authentication address", "openai"),
    ("openai.token_url", OAUTH_TOKEN_URL, "OpenAI Token address", "openai"),
    ("openai.redirect_uri", OAUTH_REDIRECT_URI, "OpenAI callback address", "openai"),
    ("openai.scope", OAUTH_SCOPE, "OpenAI Scope of authority", "openai"),
    ("proxy.enabled", "false", "Whether to enable proxy", "proxy"),
    ("proxy.type", "http", "Agent type (http/socks5)", "proxy"),
    ("proxy.host", "127.0.0.1", "proxy host", "proxy"),
    ("proxy.port", "7890", "proxy port", "proxy"),
    ("registration.max_retries", "3", "Maximum number of retries", "registration"),
    ("registration.timeout", "120", "Timeout (seconds)", "registration"),
    ("registration.default_password_length", "16", "Default password length", "registration"),
    ("webui.host", "0.0.0.0", "Web UI Listening host", "webui"),
    ("webui.port", "8000", "Web UI listening port", "webui"),
    ("webui.debug", "true", "debug mode", "webui"),
]

# ============================================================================
# Web UI Related constants
# ============================================================================

# WebSocket event
WEBSOCKET_EVENTS = {
    "CONNECT": "connect",
    "DISCONNECT": "disconnect",
    "LOG": "log",
    "STATUS": "status",
    "ERROR": "error",
    "COMPLETE": "complete",
}

# API Response status code
API_STATUS_CODES = {
    "SUCCESS": 200,
    "CREATED": 201,
    "BAD_REQUEST": 400,
    "UNAUTHORIZED": 401,
    "FORBIDDEN": 403,
    "NOT_FOUND": 404,
    "CONFLICT": 409,
    "INTERNAL_ERROR": 500,
}

# Pagination
DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100

# ============================================================================
# error message
# ============================================================================

ERROR_MESSAGES = {
    # Generic error
    "DATABASE_ERROR": "Database operation failed",
    "CONFIG_ERROR": "Configuration error",
    "NETWORK_ERROR": "Network connection failed",
    "TIMEOUT": "Operation timeout",
    "VALIDATION_ERROR": "Parameter validation failed",

    # Email service error
    "EMAIL_SERVICE_UNAVAILABLE": "Email service is unavailable",
    "EMAIL_CREATION_FAILED": "Failed to create mailbox",
    "OTP_NOT_RECEIVED": "Verification code not received",
    "OTP_INVALID": "Verification code is invalid",

    # OpenAI Related errors
    "OPENAI_AUTH_FAILED": "OpenAI Authentication failed",
    "OPENAI_RATE_LIMIT": "OpenAI Interface current limit",
    "OPENAI_CAPTCHA": "Encountered verification code",

    # proxy error
    "PROXY_FAILED": "Agent connection failed",
    "PROXY_AUTH_FAILED": "Agent authentication failed",

    # Account error
    "ACCOUNT_NOT_FOUND": "Account does not exist",
    "ACCOUNT_ALREADY_EXISTS": "Account already exists",
    "ACCOUNT_INVALID": "Account is invalid",

    # Task error
    "TASK_NOT_FOUND": "Task does not exist",
    "TASK_ALREADY_RUNNING": "Task is already running",
    "TASK_CANCELLED": "Task canceled",
}

# ============================================================================
# regular expression
# ============================================================================

REGEX_PATTERNS = {
    "EMAIL": r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$",
    "URL": r"https?://(?:[-\w.]|(?:%[\da-fA-F]{2}))+",
    "IP_ADDRESS": r"\b(?:\d{1,3}\.){3}\d{1,3}\b",
    "OTP_CODE": OTP_CODE_PATTERN,
}

# ============================================================================
# time constant
# ============================================================================

TIME_CONSTANTS = {
    "SECOND": 1,
    "MINUTE": 60,
    "HOUR": 3600,
    "DAY": 86400,
    "WEEK": 604800,
}


# ============================================================================
# Microsoft/Outlook Related constants
# ============================================================================

# Microsoft OAuth2 Token endpoint
MICROSOFT_TOKEN_ENDPOINTS = {
    # Old version IMAP endpoint used
    "LIVE": "https://login.live.com/oauth20_token.srf",
    # new version IMAP endpoint to use (requires specific scope)
    "CONSUMERS": "https://login.microsoftonline.com/consumers/oauth2/v2.0/token",
    # Graph API endpoint used
    "COMMON": "https://login.microsoftonline.com/common/oauth2/v2.0/token",
}

# IMAP Server configuration
OUTLOOK_IMAP_SERVERS = {
    "OLD": "outlook.office365.com",  # Old version IMAP
    "NEW": "outlook.live.com",       # new version IMAP
}

# Microsoft OAuth2 Scopes
MICROSOFT_SCOPES = {
    # Old version IMAP No need to specify scope
    "IMAP_OLD": "",
    # new version IMAP needed scope
    "IMAP_NEW": "https://outlook.office.com/IMAP.AccessAsUser.All offline_access",
    # Graph API needed scope
    "GRAPH_API": "https://graph.microsoft.com/.default",
}

# Outlook Provider default priority
OUTLOOK_PROVIDER_PRIORITY = ["imap_new", "imap_old", "graph_api"]
