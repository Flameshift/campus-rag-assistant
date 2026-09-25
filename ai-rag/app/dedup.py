# 去重工具：文件级哈希 + 分块级哈希。

import hashlib
import re


def file_hash(content: bytes) -> str:
    """计算文件二进制内容的 SHA-256，用于文件级去重。"""
    return hashlib.sha256(content).hexdigest()


def normalize_for_hash(text: str) -> str:
    """归一化文本：折叠空白、统一大小写，降低排版差异对哈希的影响。

    注意：这只是基础归一化；如果内容做了语义改写，需要配合 MinHash / embedding
    做近似重复检测（见 README 的后续完善点）。
    """
    return re.sub(r"\s+", " ", text).strip().lower()


def chunk_hash(text: str) -> str:
    """计算归一化文本的 SHA-256，用于分块级去重。"""
    return hashlib.sha256(normalize_for_hash(text).encode("utf-8")).hexdigest()
