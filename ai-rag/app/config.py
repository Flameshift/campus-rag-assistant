# 配置文件：集中管理环境变量与默认值。
# 所有可调参数都可以在项目根目录的 .env 文件中覆盖。

import os

from dotenv import load_dotenv

# 启动时自动加载 .env 文件（如果存在），不会覆盖系统已有的环境变量。
load_dotenv()

# ---------- 大模型（生成回答）配置 ----------
LLM_MODEL = os.getenv("LLM_MODEL", "deepseek-flash")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.deepseek.com")
LLM_API_KEY = os.getenv("LLM_API_KEY", "")

# Spring Boot -> Python 内部调用认证。
INTERNAL_AUTH_REQUIRED = os.getenv("INTERNAL_AUTH_REQUIRED", "true").lower() == "true"
INTERNAL_AUTH_SECRET = os.getenv(
    "INTERNAL_AUTH_SECRET",
    "local-dev-internal-auth-secret",
)
INTERNAL_AUTH_MAX_SKEW_SECONDS = int(os.getenv("INTERNAL_AUTH_MAX_SKEW_SECONDS", "300"))

# ---------- Embedding（向量化）配置 ----------
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "qwen3.7-text-embedding-flash")
EMBEDDING_BASE_URL = os.getenv(
    "EMBEDDING_BASE_URL",
    "https://dashscope.aliyuncs.com/compatible-mode/v1",
)
EMBEDDING_API_KEY = os.getenv("EMBEDDING_API_KEY", "")
# 千问 Embedding 单次最多 25 条文本，LangChain 按该值分批请求。
EMBEDDING_BATCH_SIZE = int(os.getenv("EMBEDDING_BATCH_SIZE", "25"))
EMBEDDING_MAX_CONCURRENCY = int(os.getenv("EMBEDDING_MAX_CONCURRENCY", "3"))
EMBEDDING_QUERY_BATCH_ENABLED = (
    os.getenv("EMBEDDING_QUERY_BATCH_ENABLED", "true").lower() == "true"
)

# ---------- RAG 参数 ----------
# 向量数据库持久化目录（千问 Embedding 为 1024 维）。
VECTOR_DB_DIR = os.getenv("VECTOR_DB_DIR", "./data/chroma_qwen")
CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "600"))
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "80"))
CHUNK_SEPARATOR = ["\n\n", "\n", "。", "？", "！", ".", "?", "!", " ", ""]
# 结构化摄取：按内容类型选择章节、表格、记录或递归分块器。
CHUNK_INCLUDE_SECTION_PATH = os.getenv("CHUNK_INCLUDE_SECTION_PATH", "true").lower() == "true"
CHUNK_RECORD_MAX_SIZE = int(os.getenv("CHUNK_RECORD_MAX_SIZE", "1200"))
CHUNK_TABLE_ROWS_PER_GROUP = int(os.getenv("CHUNK_TABLE_ROWS_PER_GROUP", "12"))
PARSER_VERSION = os.getenv("PARSER_VERSION", "v2")
CHUNKER_VERSION = os.getenv("CHUNKER_VERSION", "v2")

# LLM 仅用于规则无法判断结构的低置信度文档，返回结构计划而不是重写正文。
STRUCTURE_LLM_ENABLED = os.getenv("STRUCTURE_LLM_ENABLED", "true").lower() == "true"
STRUCTURE_LLM_MODEL = os.getenv("STRUCTURE_LLM_MODEL", "deepseek-chat")
STRUCTURE_LLM_MIN_CONFIDENCE = float(os.getenv("STRUCTURE_LLM_MIN_CONFIDENCE", "0.65"))
STRUCTURE_LLM_MAX_BLOCKS_PER_CALL = int(os.getenv("STRUCTURE_LLM_MAX_BLOCKS_PER_CALL", "80"))
STRUCTURE_LLM_CACHE_SIZE = int(os.getenv("STRUCTURE_LLM_CACHE_SIZE", "128"))

# 检索后带出命中分块的同文件相邻分块，缓解条文被切断的问题。
NEIGHBOR_EXPANSION_ENABLED = os.getenv("NEIGHBOR_EXPANSION_ENABLED", "true").lower() == "true"
NEIGHBOR_CONDITIONAL_ENABLED = (
    os.getenv("NEIGHBOR_CONDITIONAL_ENABLED", "true").lower() == "true"
)
NEIGHBOR_EXPANSION_WINDOW = int(os.getenv("NEIGHBOR_EXPANSION_WINDOW", "1"))
NEIGHBOR_EXPANSION_MAX_ADDED = int(os.getenv("NEIGHBOR_EXPANSION_MAX_ADDED", "3"))

# 父级分组与检索时父上下文扩展。
PARENT_GROUP_TARGET_CHARS = int(os.getenv("PARENT_GROUP_TARGET_CHARS", "2400"))
PARENT_GROUP_MAX_CHILDREN = int(os.getenv("PARENT_GROUP_MAX_CHILDREN", "8"))
PARENT_EXPANSION_ENABLED = os.getenv("PARENT_EXPANSION_ENABLED", "true").lower() == "true"
PARENT_EXPANSION_MAX_ADDED = int(os.getenv("PARENT_EXPANSION_MAX_ADDED", "6"))
PARENT_EXPANSION_MAX_CHILDREN = int(os.getenv("PARENT_EXPANSION_MAX_CHILDREN", "6"))
PARENT_EXPANSION_MAX_CHARS = int(os.getenv("PARENT_EXPANSION_MAX_CHARS", "3000"))
# 同一条款、同一父级的连续子块合并为 Evidence Object。
EVIDENCE_OBJECT_ENABLED = os.getenv("EVIDENCE_OBJECT_ENABLED", "true").lower() == "true"
EVIDENCE_OBJECT_MAX_CHILDREN = int(os.getenv("EVIDENCE_OBJECT_MAX_CHILDREN", "8"))
EVIDENCE_OBJECT_MAX_CHARS = int(os.getenv("EVIDENCE_OBJECT_MAX_CHARS", "4000"))

# 多轮追问检索改写：结合历史生成自包含查询，只用于检索，不替换回答问题。
QUERY_REWRITE_ENABLED = os.getenv("QUERY_REWRITE_ENABLED", "true").lower() == "true"
QUERY_REWRITE_MODEL = os.getenv("QUERY_REWRITE_MODEL", "deepseek-chat")
QUERY_REWRITE_MAX_HISTORY = int(os.getenv("QUERY_REWRITE_MAX_HISTORY", "6"))
QUERY_REWRITE_CACHE_SIZE = int(os.getenv("QUERY_REWRITE_CACHE_SIZE", "256"))
QUERY_REWRITE_TIMEOUT = int(os.getenv("QUERY_REWRITE_TIMEOUT", "30"))
# 单轮口语化问题和超长问题也可以在无历史时做规范化/压缩。
QUERY_REWRITE_STANDALONE_ENABLED = (
    os.getenv("QUERY_REWRITE_STANDALONE_ENABLED", "true").lower() == "true"
)
QUERY_REWRITE_LONG_THRESHOLD = int(os.getenv("QUERY_REWRITE_LONG_THRESHOLD", "160"))
QUERY_REWRITE_MAX_QUERY_CHARS = int(os.getenv("QUERY_REWRITE_MAX_QUERY_CHARS", "500"))
# 领域别名使用 "挂科=考核不合格;延毕=延长修业年限" 的形式配置。
QUERY_ALIASES = os.getenv("QUERY_ALIASES", "")

# 查询规划：只做规则化时间语义、子问题拆分和指代风险判断。
QUERY_PLANNER_ENABLED = os.getenv("QUERY_PLANNER_ENABLED", "true").lower() == "true"
# 高风险指代问题先要求补充文档或事项，不直接进行低置信回答。
QUERY_CLARIFICATION_ENABLED = (
    os.getenv("QUERY_CLARIFICATION_ENABLED", "true").lower() == "true"
)
# 将 Planner 产生的子问题分别送入混合召回，再用 RRF 合并。
MULTI_QUERY_ENABLED = os.getenv("MULTI_QUERY_ENABLED", "true").lower() == "true"
MULTI_QUERY_MAX_QUERIES = int(os.getenv("MULTI_QUERY_MAX_QUERIES", "3"))
MULTI_QUERY_MAX_WORKERS = int(os.getenv("MULTI_QUERY_MAX_WORKERS", "3"))
MULTI_QUERY_RRF_K = int(os.getenv("MULTI_QUERY_RRF_K", "60"))
MULTI_QUERY_SECONDARY_WEIGHT = float(
    os.getenv("MULTI_QUERY_SECONDARY_WEIGHT", "0.85")
)
# 对未覆盖的子问题，只使用 BM25 做低成本补召回，避免额外 Embedding 调用。
EVIDENCE_COVERAGE_ENABLED = os.getenv("EVIDENCE_COVERAGE_ENABLED", "true").lower() == "true"
EVIDENCE_COVERAGE_MAX_SUBQUESTIONS = int(
    os.getenv("EVIDENCE_COVERAGE_MAX_SUBQUESTIONS", "3")
)
EVIDENCE_COVERAGE_TOP_K = int(os.getenv("EVIDENCE_COVERAGE_TOP_K", "4"))
EVIDENCE_COVERAGE_MAX_ADDED = int(os.getenv("EVIDENCE_COVERAGE_MAX_ADDED", "4"))

# 回答完整性复核：发现问题时使用同一批证据补全一次回答。
ANSWER_VERIFICATION_ENABLED = (
    os.getenv("ANSWER_VERIFICATION_ENABLED", "true").lower() == "true"
)
ANSWER_VERIFICATION_MODEL = os.getenv("ANSWER_VERIFICATION_MODEL", "deepseek-chat")
ANSWER_VERIFICATION_TIMEOUT = int(os.getenv("ANSWER_VERIFICATION_TIMEOUT", "30"))
ANSWER_NUMERIC_VALIDATION_ENABLED = (
    os.getenv("ANSWER_NUMERIC_VALIDATION_ENABLED", "true").lower() == "true"
)

# 请求级 RAG 追踪：实验时开启，生产默认关闭。
RAG_TRACE_ENABLED = os.getenv("RAG_TRACE_ENABLED", "false").lower() == "true"
RAG_TRACE_DIR = os.getenv("RAG_TRACE_DIR", "./data/rag_traces")
RAG_TRACE_RETENTION_DAYS = int(os.getenv("RAG_TRACE_RETENTION_DAYS", "7"))
RAG_TRACE_MAX_FILES = int(os.getenv("RAG_TRACE_MAX_FILES", "500"))
RAG_TRACE_MAX_TOTAL_BYTES = int(
    os.getenv("RAG_TRACE_MAX_TOTAL_BYTES", str(50 * 1024 * 1024))
)

# 短期会话记忆：thread_id 对应一份最近对话状态，State 可迁移到 LangGraph Checkpointer。
SHORT_TERM_MEMORY_ENABLED = os.getenv("SHORT_TERM_MEMORY_ENABLED", "true").lower() == "true"
SHORT_TERM_MEMORY_MAX_MESSAGES = int(os.getenv("SHORT_TERM_MEMORY_MAX_MESSAGES", "20"))
SHORT_TERM_CONTEXT_MESSAGES = int(os.getenv("SHORT_TERM_CONTEXT_MESSAGES", "6"))
SHORT_TERM_MEMORY_TTL_HOURS = int(os.getenv("SHORT_TERM_MEMORY_TTL_HOURS", "72"))
SHORT_TERM_MEMORY_CLEANUP_INTERVAL_SECONDS = int(
    os.getenv("SHORT_TERM_MEMORY_CLEANUP_INTERVAL_SECONDS", "3600")
)

# 综合置信度：检索质量、生成一致性、风险惩罚和动作分级。
CONFIDENCE_ENABLED = os.getenv("CONFIDENCE_ENABLED", "true").lower() == "true"
CONFIDENCE_HIGH_THRESHOLD = float(os.getenv("CONFIDENCE_HIGH_THRESHOLD", "0.78"))
CONFIDENCE_VERIFY_THRESHOLD = float(os.getenv("CONFIDENCE_VERIFY_THRESHOLD", "0.62"))
CONFIDENCE_RETRIEVE_THRESHOLD = float(os.getenv("CONFIDENCE_RETRIEVE_THRESHOLD", "0.45"))
# 最终送给 LLM 的分块数量。
TOP_K = int(os.getenv("TOP_K", "5"))

# ---------- 混合检索（BM25 + 向量） ----------
BM25_ENABLED = os.getenv("BM25_ENABLED", "true").lower() == "true"
BM25_WEIGHT = float(os.getenv("BM25_WEIGHT", "0.4"))
VECTOR_WEIGHT = float(os.getenv("VECTOR_WEIGHT", "0.6"))
# 融合前每一路召回的候选数量。
RETRIEVE_CANDIDATES = int(os.getenv("RETRIEVE_CANDIDATES", "20"))

# ---------- 语义去重 ----------
SEMANTIC_DEDUP_ENABLED = os.getenv("SEMANTIC_DEDUP_ENABLED", "true").lower() == "true"
SEMANTIC_DEDUP_THRESHOLD = float(os.getenv("SEMANTIC_DEDUP_THRESHOLD", "0.75"))
SEMANTIC_DEDUP_GRAY_LOW = float(os.getenv("SEMANTIC_DEDUP_GRAY_LOW", "0.60"))
SEMANTIC_DEDUP_TOP_K = int(os.getenv("SEMANTIC_DEDUP_TOP_K", "3"))
SEMANTIC_DEDUP_LLM_CONFIRM = os.getenv("SEMANTIC_DEDUP_LLM_CONFIRM", "true").lower() == "true"
SEMANTIC_DEDUP_JUDGE_MODEL = os.getenv("SEMANTIC_DEDUP_JUDGE_MODEL", "deepseek-chat")

# ---------- Rerank 精排 ----------
# 粗筛先召回 RERANK_CANDIDATES 条，再由 Rerank 精排到 TOP_K 条。
RERANK_ENABLED = os.getenv("RERANK_ENABLED", "true").lower() == "true"
RERANK_MODEL = os.getenv("RERANK_MODEL", "qwen3.7-text-rerank")
RERANK_BASE_URL = os.getenv(
    "RERANK_BASE_URL",
    "https://dashscope.aliyuncs.com/api/v1/services/rerank/text-rerank/text-rerank",
)
# Rerank 直接复用 `.env` 中的 Embedding Key（同一百炼账号）。
RERANK_API_KEY = os.getenv("RERANK_API_KEY", "") or EMBEDDING_API_KEY
RERANK_CANDIDATES = int(os.getenv("RERANK_CANDIDATES", "20"))
RERANK_TIMEOUT = int(os.getenv("RERANK_TIMEOUT", "20"))
