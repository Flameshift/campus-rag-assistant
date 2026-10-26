"""Spring Boot 到 Python 服务的内部 HMAC 认证中间件。

认证协议：
1. Spring Boot 生成 Unix 秒级时间戳 timestamp。
2. Spring Boot 按以下格式拼接签名内容：
       timestamp + "\\n" + HTTP_METHOD + "\\n" + path_and_query
3. Spring Boot 使用双方共享的 INTERNAL_AUTH_SECRET，通过 HMAC-SHA256
   计算十六进制签名。
4. Python 从请求头读取 timestamp 和 signature，按相同规则重新计算并比较。

这里的路径必须包含 query string。例如请求 /api/admin/tasks?document_id=1
时，签名内容中的路径也必须是对应的 /api/admin/tasks?document_id=1。
否则 Spring Boot 与 Python 计算的签名不一致。
"""

import hashlib
import hmac
import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from . import config


class InternalAuthMiddleware(BaseHTTPMiddleware):
    """校验 /api/ 接口的内部签名，阻止请求绕过 Spring Boot 直接调用 Python。

    该中间件只负责服务间认证，不处理用户登录态。
    登录用户和游客身份由 Spring Boot 判断，Python 只信任带有合法内部签名的请求。
    """

    async def dispatch(self, request: Request, call_next):
        # path 不包含 query，因此需要单独拼接 request.url.query，
        # 保证 Python 参与签名的路径与 Spring Boot 完全一致。
        path = request.url.path
        signed_path = path + (f"?{request.url.query}" if request.url.query else "")

        # 两类请求直接放行：
        # 1. 显式关闭内部认证时，便于本地调试；
        # 2. /health、/、/docs 等非业务接口，不属于 Spring Boot 到 Python 的内部 API 调用。
        if not config.INTERNAL_AUTH_REQUIRED or not path.startswith("/api/"):
            return await call_next(request)

        # 读取 Spring Boot 在 AiGatewayService.addInternalAuth() 中写入的两个头部。
        # 缺少任意一个时都按空字符串处理，后续会认证失败并返回 401。
        timestamp = request.headers.get("X-Internal-Timestamp", "")
        signature = request.headers.get("X-Internal-Signature", "")

        # 同时验证时间戳和签名：
        # - 时间戳限制重放攻击的有效窗口；
        # - 签名证明请求由掌握共享密钥的 Spring Boot 发出；
        # - method 和 signed_path 绑定到当前请求，防止签名被复用到其他接口。
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

        # 认证通过后继续执行 FastAPI 路由和后续业务逻辑。
        return await call_next(request)

    @staticmethod
    def _valid_timestamp(value: str) -> bool:
        """检查时间戳是否为整数，并且与服务器当前时间的偏差在允许范围内。"""
        try:
            timestamp = int(value)
        except (TypeError, ValueError):
            # 空值、非数字或恶意构造的时间戳都视为无效。
            return False

        # 使用绝对时间差，同时覆盖请求时间过早或过晚的情况。
        return abs(int(time.time()) - timestamp) <= config.INTERNAL_AUTH_MAX_SKEW_SECONDS

    @staticmethod
    def _valid_signature(
        timestamp: str,
        method: str,
        path: str,
        signature: str,
    ) -> bool:
        """使用共享密钥重新计算 HMAC-SHA256，并验证请求携带的签名。

        拼接格式必须与 Spring Boot 的 AiGatewayService.addInternalAuth() 一致：
            timestamp + "\\n" + method + "\\n" + path

        注意：
        - 三个字段之间使用换行符分隔，顺序不能改变；
        - HTTP 方法统一转成大写，避免 get 与 GET 产生不同签名；
        - path 包含 query string，确保查询参数也受到签名保护；
        - 使用 hmac.compare_digest 进行常量时间比较，降低时序攻击风险。
        """
        payload = f"{timestamp}\n{method.upper()}\n{path}".encode("utf-8")
        expected = hmac.new(
            config.INTERNAL_AUTH_SECRET.encode("utf-8"),
            payload,
            hashlib.sha256,
        ).hexdigest()

        # 不能使用普通字符串 == 比较，因为普通比较可能在首个不同字符处提前返回。
        return hmac.compare_digest(expected, signature)
