"""
LuckMailSdk Exception class definition
"""


class LuckMailError(Exception):
    """LuckMail SDK Basic exception"""
    pass


class AuthError(LuckMailError):
    """Authentication failure exception"""
    def __init__(self, message: str = "Authentication failed"):
        super().__init__(message)


class APIError(LuckMailError):
    """API Call exception"""
    def __init__(self, code: int, message: str, data=None):
        self.code = code
        self.message = message
        self.data = data
        super().__init__(f"API Error [{code}]: {message}")


class NetworkError(LuckMailError):
    """Network request exception"""
    def __init__(self, message: str = "Network error occurred"):
        super().__init__(message)


class TimeoutError(LuckMailError):
    """Timeout exception"""
    def __init__(self, message: str = "Request timed out"):
        super().__init__(message)
