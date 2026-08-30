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


def embedder_identity(emb) -> dict:
    """嵌入器的自描述指纹（仿 ncnn param 文件的自描述思想）。

    返回 {"type", "name", "dim", "revision", "fp"}：跨设备同步前用 fp 做一致性
    握手——两端 fp 不同说明嵌入模型不一致，向量不可比，必须拒绝互相同步向量。

    revision：嵌入模型版本标识（可选属性）。同名模型不同版本的向量不可比，
    嵌入器可通过定义 `revision` 属性参与指纹计算；为空时指纹与 v0.7 完全一致
    （跨版本握手兼容）。局限：embedding API 本身不暴露权重版本，OpenAI 嵌入器
    默认无法自动感知静默升级——显式构造时建议传入 revision 固定版本。
    """
    name = getattr(emb, "model", None) or f"hashing-{getattr(emb, 'dim', 0)}"
    dim = int(getattr(emb, "dim", 0) or 0)
    revision = str(getattr(emb, "revision", "") or "")
    basis = f"{type(emb).__name__}:{name}:{dim}" + (f":{revision}" if revision else "")
    fp = hashlib.blake2b(basis.encode("utf-8"), digest_size=8).hexdigest()
    return {
        "type": type(emb).__name__,
        "name": name,
        "dim": dim,
        "revision": revision,
        "fp": fp,
    }


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
    """OpenAI embeddings API（可选依赖：pip install "membridge[openai]"）。

    revision：模型版本标识。embedding API 不暴露权重版本，同名模型可能静默
    升级导致向量不可比——在意跨设备一致性的用户应显式传入并保持各端一致。
    """

    def __init__(self, model: str = "text-embedding-3-small", revision: str = "") -> None:
        try:
            from openai import OpenAI  # 延迟导入，保持核心零依赖
        except ImportError as exc:  # pragma: no cover
            raise ImportError(
                '需要 openai 依赖：pip install "membridge[openai]"'
            ) from exc
        self._client = OpenAI()
        self.model = model
        self.revision = revision

    def embed(self, text: str) -> List[float]:
        resp = self._client.embeddings.create(input=[text], model=self.model)
        return list(resp.data[0].embedding)
