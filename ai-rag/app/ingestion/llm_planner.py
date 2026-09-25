"""低置信度文档的结构规划器，只返回边界和策略，不重写原文。"""

import hashlib
import json
import logging
import re
from collections import OrderedDict

from langchain_openai import ChatOpenAI

from .. import config
from .blocks import DocumentBlock

logger = logging.getLogger(__name__)

ALLOWED_STRATEGIES = {"section", "table", "record", "recursive"}


class StructureLLMPlanner:
    """规则无法识别结构时调用 LLM，输出可校验的结构计划。"""

    def __init__(self) -> None:
        self._llm: ChatOpenAI | None = None
        self._cache: OrderedDict[str, dict] = OrderedDict()

    def should_plan(self, blocks: list[DocumentBlock]) -> bool:
        if not blocks or not config.STRUCTURE_LLM_ENABLED or not config.LLM_API_KEY:
            return False
        confidence = max((block.structure_confidence for block in blocks), default=0.0)
        return confidence < config.STRUCTURE_LLM_MIN_CONFIDENCE

    def plan(self, blocks: list[DocumentBlock], source: str) -> list[DocumentBlock]:
        if not self.should_plan(blocks):
            return blocks

        cache_key = hashlib.sha256(
            (source + "|" + "\n".join(block.content for block in blocks)).encode("utf-8")
        ).hexdigest()
        cached = self._cache.get(cache_key)
        if cached is not None:
            return self._apply_plan(blocks, cached)

        plan = self._request_plan(blocks)
        if not plan:
            return blocks
        self._cache[cache_key] = plan
        self._cache.move_to_end(cache_key)
        while len(self._cache) > config.STRUCTURE_LLM_CACHE_SIZE:
            self._cache.popitem(last=False)
        return self._apply_plan(blocks, plan)

    def _get_llm(self) -> ChatOpenAI:
        if self._llm is None:
            self._llm = ChatOpenAI(
                model=config.STRUCTURE_LLM_MODEL,
                api_key=config.LLM_API_KEY,
                base_url=config.LLM_BASE_URL,
                temperature=0,
                max_tokens=1000,
                timeout=60,
                max_retries=1,
            )
        return self._llm

    def _request_plan(self, all_blocks: list[DocumentBlock]) -> dict | None:
        """按窗口调用模型，避免长文档一次性超过上下文限制。"""
        merged_sections: list[dict] = []
        window_size = config.STRUCTURE_LLM_MAX_BLOCKS_PER_CALL
        for offset in range(0, len(all_blocks), window_size):
            window = all_blocks[offset : offset + window_size]
            response = self._request_window(window, offset)
            if not response:
                continue
            for section in response.get("sections", []):
                section["start_block"] = int(section.get("start_block", 0)) + offset
                section["end_block"] = int(section.get("end_block", 0)) + offset
                merged_sections.append(section)
        if not merged_sections:
            return None
        return {"sections": merged_sections, "confidence": 0.8}

    def _request_window(self, blocks: list[DocumentBlock], offset: int) -> dict | None:
        lines = []
        for local_index, block in enumerate(blocks):
            text = block.content.replace("\n", " ")[:500]
            lines.append(f"[{local_index}] ({block.block_type}) {text}")

        prompt = f"""你是文档结构分析器。下面是按顺序编号的文档块。
只判断分块边界，不得改写、总结或生成新的正文。
返回 JSON，不要输出 Markdown：
{{
  "sections": [
    {{
      "start_block": 0,
      "end_block": 3,
      "title": "章节标题，无法判断时填空字符串",
      "strategy": "section|table|record|recursive",
      "confidence": 0.0
    }}
  ]
}}
要求：
1. start_block 和 end_block 均为包含式索引。
2. 覆盖所有输入块，不要遗漏。
3. 表格使用 table，CSV/JSON 记录使用 record。
4. 无法识别的正文使用 recursive 或 section。

文件：{blocks[0].source if blocks else ""}
文档块：
{chr(10).join(lines)}
"""
        try:
            response = self._get_llm().invoke(prompt)
            content = getattr(response, "content", "") or ""
            match = re.search(r"\{.*\}", content, re.S)
            if not match:
                return None
            data = json.loads(match.group(0))
            return data if isinstance(data.get("sections"), list) else None
        except Exception as exc:
            logger.warning("LLM 结构规划失败，将使用递归分块兜底: %s", exc)
            return None

    def _apply_plan(self, blocks: list[DocumentBlock], plan: dict) -> list[DocumentBlock]:
        confidence = float(plan.get("confidence", 0.0) or 0.0)
        if confidence < config.STRUCTURE_LLM_MIN_CONFIDENCE:
            return blocks

        for section in sorted(plan.get("sections", []), key=lambda item: int(item.get("start_block", 0))):
            try:
                start = max(0, int(section.get("start_block", 0)))
                end = min(len(blocks) - 1, int(section.get("end_block", start)))
                strategy = str(section.get("strategy", "recursive")).lower()
                title = str(section.get("title", "")).strip()
            except (TypeError, ValueError):
                continue
            if start > end or strategy not in ALLOWED_STRATEGIES:
                continue

            section_path = [title] if title else []
            for block in blocks[start : end + 1]:
                if section_path:
                    block.section_path = section_path
                    scope = " > ".join(section_path)
                    block.parent_key = hashlib.sha256(
                        f"{block.source}|{scope}".encode("utf-8")
                    ).hexdigest()[:20]
                block.metadata["planned_strategy"] = strategy
                block.metadata["structure_planner"] = config.STRUCTURE_LLM_MODEL
        return blocks
