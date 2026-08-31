"""检索层：三路混合检索 + RRF 融合 + 缺口发现（v0.9 借鉴版）。

外部借鉴（对应 docs/roadmap.md「v0.9 借鉴版」，全部只落在检索/调度层，
不触碰记忆内容——内容冻结原则完整保持）：

- 三路召回 + RRF 排名融合（Knowledge OS / GraphRAG 混合检索实践）：
  向量、关键词、图谱各有盲区，RRF 只看排名不看原始分数，天然奖励多路
  共识且无需归一化、无新参数可调。
- 缺口发现（Knowledge OS「检索即更新」的安全子集）：零命中查询只记
  元数据，由 doctor 提醒用户补写——系统只提醒，内容永远由用户写。
- 「沉默也是动作」（Meta Proactive Memory Agent）：没有高质量命中时
  明确返回空结果，由上层显式告知"本轮不注入"，而不是硬凑弱命中。
"""

from __future__ import annotations

from typing import List, Tuple

from .embeddings import Embedder
from .node import MemoryNode
from .san import _gram_set
from .store import MemoryStore

RRF_K = 60          # 标准值（2009 SIGIR 确立），无需调参
GRAPH_SEEDS = 2     # 取前两路各前 2 名作为图扩展种子
GRAPH_FANOUT = 3    # 每个种子最多扩展的 SAN 邻居数


def keyword_recall(store: MemoryStore, query: str) -> List[Tuple[MemoryNode, float]]:
    """关键词路：字符 n-gram 集合重叠度（复用 SAN 的 n-gram 基建，零依赖）。

    与向量路互补：精确术语、错误信息、人名等"字面命中"场景向量检索常漏。
    """
    qg = _gram_set(query)
    if not qg:
        return []
    scored: List[Tuple[MemoryNode, float]] = []
    for n in store.all_nodes():
        ng = _gram_set(n.content)
        if not ng:
            continue
        overlap = len(qg & ng)
        if overlap == 0:
            continue
        scored.append((n, overlap / len(qg | ng)))
    scored.sort(key=lambda t: t[1], reverse=True)
    return scored


def graph_recall(
    store: MemoryStore, seeds: List[MemoryNode]
) -> List[Tuple[MemoryNode, float]]:
    """图谱路：种子的 SAN 一跳邻居按边权展开（GraphRAG Local Search 的极简版）。"""
    seen = {s.node_id for s in seeds}
    scored: List[Tuple[MemoryNode, float]] = []
    for seed in seeds[:GRAPH_SEEDS]:
        for nbr, w in store.neighbors(seed.node_id)[:GRAPH_FANOUT]:
            if nbr.node_id in seen:
                continue
            seen.add(nbr.node_id)
            scored.append((nbr, w))
    scored.sort(key=lambda t: t[1], reverse=True)
    return scored


def hybrid_search(
    store: MemoryStore,
    embedder: Embedder,
    query: str,
    k: int = 5,
    record_access: bool = True,
) -> List[Tuple[MemoryNode, float]]:
    """三路混合检索 + RRF 融合，返回 (node, rrf_score) 降序。

    三路：向量（余弦，含相对阈值滤弱命中）+ 关键词（n-gram 重叠）+
    图谱（种子一跳邻居）。融合得分 = Σ 1/(排名 + RRF_K)，只看排名，
    多路共识天然加分。全路无命中时记录一条缺口（纯元数据）后返回空列表。
    """
    vec_hits = store.search(
        embedder.embed(query), k=k * 2, record_access=False, rel_floor=0.5
    )
    kw_hits = keyword_recall(store, query)
    seeds = [n for n, _ in vec_hits[:GRAPH_SEEDS]] + [
        n for n, _ in kw_hits[:GRAPH_SEEDS]
    ]
    routes = [vec_hits, kw_hits, graph_recall(store, seeds)]

    scores: dict = {}
    nodes: dict = {}
    for route in routes:
        for rank, (n, _) in enumerate(route):
            scores[n.node_id] = scores.get(n.node_id, 0.0) + 1.0 / (rank + RRF_K)
            nodes[n.node_id] = n
    fused = sorted(scores.items(), key=lambda t: t[1], reverse=True)[:k]
    hits = [(nodes[nid], s) for nid, s in fused if nodes.get(nid) is not None]

    if not hits:
        store.record_gap(query)
        return []
    if record_access:
        with store.transaction():
            for n, _ in hits:
                store._touch_uncommitted(n.node_id)
    return hits
