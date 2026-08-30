"""蒸馏层：SAN 语义关联网络（论文 §3.2）。

论文公式：w_ij = λ·PMI(n_i, n_j) + (1-λ)·cos(e_i, e_j)

v0 的 PMI 项用"字符 n-gram 集合的 Jaccard 共现"作代理（无需语料级统计），
完整 PMI 可通过 pmi_fn 参数注入替换，上层接口不变。

架构约束（与论文一致）：SAN 只做提取与关联，绝不生成原始交互中不存在的新语义
（内容冻结原则，规避 Faulty Memory 失效域）。

v0.8 工程修订：建边从「每次 add 全量 O(n²) 重算」改为增量——写入时只算新节点
与既有节点的关联（O(n)）；全量两两重建仅用于 init / rebuild-edges 命令。
内容冻结原则下边本就只增不改，增量建边不损失语义；已存在且权重未变的边
不再重写（写放大归零）。
"""

from __future__ import annotations

from typing import Callable, Iterator, List, Optional, Tuple

from .embeddings import Embedder, cosine
from .node import MemoryNode
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
    only_new: Optional[MemoryNode] = None,
) -> List[Tuple[str, str, float]]:
    """建边，返回本次实际写入的新增边 [(src, dst, weight)]。

    only_new   增量模式：传入刚写入的新节点，只计算它与库内既有节点的
               关联（O(n)）——memory_add / cli add 的常规路径。
    全量模式   only_new=None 时全库两两重建（O(n²)）——仅 init 后首次建图
               或 membridge rebuild-edges 显式触发。
    lam        论文中的平衡系数 λ：PMI 共现项与语义相似项的权重比
    min_weight 低于该权重的关联不落库（保持图稀疏，对应论文 edge density < 0.1%）

    embedder 参数保留以兼容既有调用签名；权重直接由已存储的向量计算。
    """
    if only_new is not None:
        others = (n for n in store.all_nodes() if n.node_id != only_new.node_id)
        pairs: Iterator[Tuple[MemoryNode, MemoryNode]] = (
            (only_new, b) for b in others
        )
    else:
        nodes = store.all_nodes()
        pairs = (
            (nodes[i], nodes[j])
            for i in range(len(nodes))
            for j in range(i + 1, len(nodes))
        )
    added: List[Tuple[str, str, float]] = []
    for a, b in pairs:
        w = lam * pmi_fn(a.content, b.content) + (1.0 - lam) * cosine(
            a.embedding, b.embedding
        )
        if w < min_weight:
            continue
        weight = round(w, 4)
        if store.edge_weight(a.node_id, b.node_id) == weight:
            continue  # 已存在且权重未变：不重写（幂等，写放大归零）
        store.add_edge(a.node_id, b.node_id, weight)
        added.append((a.node_id, b.node_id, weight))
    return added
