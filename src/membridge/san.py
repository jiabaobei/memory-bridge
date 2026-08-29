"""蒸馏层：SAN 语义关联网络（论文 §3.2）。

论文公式：w_ij = λ·PMI(n_i, n_j) + (1-λ)·cos(e_i, e_j)

v0 的 PMI 项用"字符 n-gram 集合的 Jaccard 共现"作代理（无需语料级统计），
完整 PMI 可通过 pmi_fn 参数注入替换，上层接口不变。

架构约束（与论文一致）：SAN 只做提取与关联，绝不生成原始交互中不存在的新语义
（内容冻结原则，规避 Faulty Memory 失效域）。
"""

from __future__ import annotations

from typing import Callable, List, Tuple

from .embeddings import Embedder, cosine
from .store import MemoryStore


def _gram_set(text: str, ngram: int = 2) -> set:
    t = "".join(text.lower().split())
    if not t:
        return set()
    if len(t) <= ngram:
        return {t}
    return {t[i: i + ngram] for i in range(len(t) - ngram + 1)}


def jaccard_pmi(a: str, b: str) -> float:
    """PMI 的共现代理：两段文本共享的区分性片段占比越高，关联越强。"""
    sa, sb = _gram_set(a), _gram_set(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def build_edges(
    store: MemoryStore,
    embedder: Embedder,
    lam: float = 0.5,
    min_weight: float = 0.15,
    pmi_fn: Callable[[str, str], float] = jaccard_pmi,
) -> List[Tuple[str, str, float]]:
    """为库内节点两两建边，返回本次新增的高置信边 [(src, dst, weight)]。

    lam     论文中的平衡系数 λ：PMI 共现项与语义相似项的权重比
    min_weight  低于该权重的关联不落库（保持图稀疏，对应论文 edge density < 0.1%）
    """
    nodes = store.all_nodes()
    added: List[Tuple[str, str, float]] = []
    for i in range(len(nodes)):
        for j in range(i + 1, len(nodes)):
            a, b = nodes[i], nodes[j]
            w = lam * pmi_fn(a.content, b.content) + (1.0 - lam) * cosine(
                a.embedding, b.embedding
            )
            if w >= min_weight:
                weight = round(w, 4)
                store.add_edge(a.node_id, b.node_id, weight)
                added.append((a.node_id, b.node_id, weight))
    return added
