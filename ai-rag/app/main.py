"""FastAPI 应用入口。

main.py 只负责应用级资源：数据库表、短期记忆清理线程、内部认证中间件和路由注册。
具体 HTTP 处理位于 app/api，RAG 核心逻辑位于 app/rag_service 与 app/rag。
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from .api.admin_routes import router as admin_router
from .api.chat_routes import router as chat_router
from .api.system_routes import router as system_router
from .api.upload_routes import router as upload_router
from .db import init_db
from .internal_auth import InternalAuthMiddleware
from .short_term_memory import short_term_memory

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


@asynccontextmanager
async def lifespan(_: FastAPI):
    """管理数据库初始化和短期记忆清理线程的启动、关闭。"""
    init_db()
    short_term_memory.start_background_cleanup()
    try:
        yield
    finally:
        short_term_memory.stop_background_cleanup()


app = FastAPI(title="AI 咨询助手 RAG 服务", version="0.1.0", lifespan=lifespan)
app.add_middleware(InternalAuthMiddleware)

app.include_router(system_router)
app.include_router(upload_router)
app.include_router(admin_router)
app.include_router(chat_router)
