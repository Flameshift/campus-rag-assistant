"""文档结构分析：标题层级、章节路径、父级键和结构置信度。"""

import hashlib

from .blocks import DocumentBlock


class StructureAnalyzer:
    """把线性 DocumentBlock 补充为可检索的章节结构。"""

    HIGH_CONFIDENCE_TYPES = {"table", "record"}

    def enrich(self, blocks: list[DocumentBlock], source: str) -> list[DocumentBlock]:
        if not blocks:
            return blocks

        heading_stack: list[tuple[int, str]] = []
        heading_count = 0
        structured_count = 0

        for index, block in enumerate(blocks):
            block.order_index = index
            block.source = block.source or source
            if block.block_type == "heading" and block.content:
                heading_count += 1
                level = max(1, block.heading_level or 1)
                while heading_stack and heading_stack[-1][0] >= level:
                    heading_stack.pop()
                heading_stack.append((level, block.content.strip()))
                block.section_path = [title for _, title in heading_stack]
            else:
                block.section_path = [title for _, title in heading_stack]

            if block.block_type in self.HIGH_CONFIDENCE_TYPES:
                structured_count += 1

            scope = " > ".join(block.section_path) or "root"
            block.parent_key = hashlib.sha256(f"{source}|{scope}".encode("utf-8")).hexdigest()[:20]

        total = len(blocks)
        heading_ratio = heading_count / total
        structured_ratio = structured_count / total
        if structured_count:
            confidence = min(1.0, 0.72 + structured_ratio * 0.28)
        elif heading_count:
            confidence = min(1.0, 0.68 + heading_ratio * 0.32)
        else:
            confidence = 0.25

        for block in blocks:
            block.structure_confidence = confidence
        return blocks
