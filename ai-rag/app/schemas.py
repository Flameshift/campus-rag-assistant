# 请求/响应数据模型：使用 Pydantic 做参数校验，并自动生成 Swagger 文档。

from typing import Any, Dict, List

from pydantic import BaseModel


class ChatMessage(BaseModel):
    """对话历史中的单条消息。"""

    role: str  # 消息角色：user（用户）/ assistant（助手）
    content: str  # 消息内容


class ChatRequest(BaseModel):
    """问答接口的请求体。"""

    question: str  # 用户提出的问题
    history: List[ChatMessage] = []  # 多轮对话历史，用于保持上下文连贯
    thread_id: str | None = None  # 短期记忆线程标识；为空时保持无状态调用
    history_trusted: bool = False  # 仅由受信网关设置为 true


class Source(BaseModel):
    """RAG 返回的参考来源。"""

    content: str  # 命中知识库的片段内容
    metadata: Dict[str, Any] = {}  # 来源信息，如文件名、页码等


class ChatResponse(BaseModel):
    """问答接口的响应体。"""

    answer: str  # 最终生成的回答
    sources: List[Source] = []  # 本次回答引用的知识片段
    mode: str = "rag"  # 运行模式：rag=真实模型 / demo=演示模式
    timings: Dict[str, float] = {}  # 各阶段耗时，单位毫秒
    request_id: str = ""  # 单次请求追踪 ID
    confidence: Dict[str, Any] = {}  # 综合置信度、动作和明细信号


class UploadResponse(BaseModel):
    """上传接口的响应体。"""

    filename: str = ""  # 写入知识库的文件名
    chunks: int = 0  # 该文件被切分的块数
    message: str = ""  # 给前端展示的提示信息
