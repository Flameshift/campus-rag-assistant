"""基础探测和知识库健康接口。"""

from fastapi import APIRouter

from ..rag_service import rag_service

router = APIRouter()


@router.get("/")
def root():
    """返回服务标识和常用入口地址，便于人工检查服务是否可访问。"""
    return {"service": "ai-rag", "docs": "/docs", "health": "/health"}


@router.get("/health")
def health():
    """健康检查接口。

    mode=rag 表示已配置真实模型并执行完整 RAG 流程；
    mode=demo 表示使用假回答流程，通常用于没有模型 Key 的本地联调。
    """
    return {"status": "ok", "mode": "demo" if rag_service.use_fake else "rag"}


@router.get("/api/knowledge/count")
def knowledge_count():
    """查询向量知识库中的分块总数，主要给管理端和健康检查使用。"""
    return {"count": rag_service.knowledge_count()}
