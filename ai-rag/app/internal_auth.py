"""Spring Boot 到 Python 服务的内部 HMAC 认证。"""

import hashlib
import hmac
import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from . import config


class InternalAuthMiddleware(BaseHTTPMiddleware):
    """校验受保护 API 的内部签名，阻止 Python 服务被直接调用。"""

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        signed_path = path + (f"?{request.url.query}" if request.url.query else "")
        if not config.INTERNAL_AUTH_REQUIRED or not path.startswith("/api/"):
            return await call_next(request)

        timestamp = request.headers.get("X-Internal-Timestamp", "")
        signature = request.headers.get("X-Internal-Signature", "")
        if not self._valid_timestamp(timestamp) or not self._valid_signature(
            timestamp,
            request.method,
            signed_path,
            signature,
        ):
            return JSONResponse(
                status_code=401,
                content={"detail": "内部服务认证失败"},
            )
        return await call_next(request)

    @staticmethod
    def _valid_timestamp(value: str) -> bool:
        try:
            timestamp = int(value)
        except (TypeError, ValueError):
            return False
        return abs(int(time.time()) - timestamp) <= config.INTERNAL_AUTH_MAX_SKEW_SECONDS

    @staticmethod
    def _valid_signature(
        timestamp: str,
        method: str,
        path: str,
        signature: str,
    ) -> bool:
        payload = f"{timestamp}\n{method.upper()}\n{path}".encode("utf-8")
        expected = hmac.new(
            config.INTERNAL_AUTH_SECRET.encode("utf-8"),
            payload,
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(expected, signature)
