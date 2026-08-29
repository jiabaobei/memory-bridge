"""嵌入层：文本 → 语义向量 e_i（论文 §3.2）。

默认提供零依赖的确定性哈希嵌入（本地 / 测试 / 离线环境开箱即用）；
生产环境建议 `pip install "membridge[openai]"` 后使用真实 embedding 模型。

跨设备一致性约束：所有设备必须使用同一个 embedder（同模型、同维度），
否则向量不可比、DSS 差分无意义 —— 详见 docs/RFC-001-architecture.md §4。
"""

from __future__ import annotations

import hashlib
import math
from typing import List, Protocol


def cosine(a: List[float], b: List[float]) -> float:
    """余弦相似度。空向量或维度不一致时返回 0。"""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


class Embedder(Protocol):
    def embed(self, text: str) -> List[float]:  # pragma: no cover
        ...


class HashingEmbedder:
    """字符 n-gram 特征哈希嵌入：无需模型、无需网络、跨平台结果一致。

    仅用于开发 / 测试 / 离线环境，语义质量远低于真实 embedding 模型。
    """

    def __init__(self, dim: int = 256, ngram: int = 2) -> None:
        self.dim = dim
        self.ngram = ngram

    def _grams(self, text: str) -> List[str]:
        t = "".join(text.lower().split())
        if not t:
            return []
        if len(t) <= self.ngram:
            return [t]
        return [t[i: i + self.ngram] for i in range(len(t) - self.ngram + 1)]

    def embed(self, text: str) -> List[float]:
        vec = [0.0] * self.dim
        for g in self._grams(text):
            h = int.from_bytes(
                hashlib.blake2b(g.encode("utf-8"), digest_size=8).digest(), "big"
            )
            vec[h % self.dim] += 1.0 if (h >> 32) & 1 else -1.0
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]


class OpenAIEmbedder:
    """OpenAI embeddings API（可选依赖：pip install "membridge[openai]"）。"""

    def __init__(self, model: str = "text-embedding-3-small") -> None:
        try:
            from openai import OpenAI  # 延迟导入，保持核心零依赖
        except ImportError as exc:  # pragma: no cover
            raise ImportError(
                '需要 openai 依赖：pip install "membridge[openai]"'
            ) from exc
        self._client = OpenAI()
        self.model = model

    def embed(self, text: str) -> List[float]:
        resp = self._client.embeddings.create(input=[text], model=self.model)
        return list(resp.data[0].embedding)
