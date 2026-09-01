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


def scope_allowed(scope: str):
    """解析范围直达参数（v0.13.1，借鉴 Context7「已知目标直达」）。

    调用方已知道记忆在哪个范围时，先按范围过滤再融合——跳过无关候选，
    更准、更省。支持 `tag:<名>` / `scene:<名>` / `kind:<fact|procedure|handover>`。
    空串或无法解析（未知字段、缺值）返回 None = 不过滤，行为与之前完全一致。
    只读过滤元数据，不触碰记忆内容。
    """
    if not scope or ":" not in scope:
        return None
    field, _, value = scope.partition(":")
    field, value = field.strip().lower(), value.strip()
    if not value:
        return None
    if field in ("tag", "tags"):
        return lambda n: value in n.tags
    if field == "scene":
        return lambda n: n.scene == value
    if field == "kind":
        return lambda n: n.kind == value
    return None


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


def search_with_reasons(
    store: MemoryStore,
    embedder: Embedder,
    query: str,
    k: int = 5,
    record_access: bool = True,
    scope: str = "",
) -> List[Tuple[MemoryNode, float, str]]:
    """三路混合检索 + RRF 融合，返回 (node, rrf_score, reason)。

    三路：向量（余弦，含相对阈值滤弱命中）+ 关键词（n-gram 重叠）+
    图谱（种子一跳邻居）。融合得分 = Σ 1/(排名 + RRF_K)，只看排名，
    多路共识天然加分。全路无命中时记录一条缺口（纯元数据）后返回空列表。

    reason 为极短的命中路径串（如"向量+图谱"），用于注入上下文时标注
    "为什么召回这条"——用户一眼判断该不该信（v0.14）。理由只由检索路径
    产生，不触碰记忆内容；字符串刻意压缩到几个字，服从省 token 原则。

    scope（v0.13.1，可选）：范围直达，形如 `tag:dev` / `scene:work` /
    `kind:procedure`——调用方已知记忆所在范围时先过滤再融合，更准更省。
    指定了范围而无命中属预期（该范围内没有），不记缺口。
    """
    allowed = scope_allowed(scope)
    vec_hits = store.search(
        embedder.embed(query), k=k * 2, record_access=False, rel_floor=0.5
    )
    kw_hits = keyword_recall(store, query)
    seeds = [n for n, _ in vec_hits[:GRAPH_SEEDS]] + [
        n for n, _ in kw_hits[:GRAPH_SEEDS]
    ]
    named = [("向量", vec_hits), ("关键词", kw_hits),
             ("图谱", graph_recall(store, seeds))]
    if allowed is not None:
        named = [(name, [(n, s) for n, s in hits if allowed(n)])
                 for name, hits in named]

    scores: dict = {}
    nodes: dict = {}
    why: dict = {}
    for name, route in named:
        for rank, (n, _) in enumerate(route):
            scores[n.node_id] = scores.get(n.node_id, 0.0) + 1.0 / (rank + RRF_K)
            nodes[n.node_id] = n
            seen = why.setdefault(n.node_id, [])
            if name not in seen:
                seen.append(name)
    fused = sorted(scores.items(), key=lambda t: t[1], reverse=True)[:k]
    hits = [
        (nodes[nid], s, "+".join(why.get(nid, [])))
        for nid, s in fused
        if nodes.get(nid) is not None
    ]

    if not hits:
        if allowed is None:  # 无范围限定才算"缺口"；范围内没有是预期
            store.record_gap(query)
        return []
    if record_access:
        with store.transaction():
            for n, _, _ in hits:
                store._touch_uncommitted(n.node_id)
    return hits


def hybrid_search(
    store: MemoryStore,
    embedder: Embedder,
    query: str,
    k: int = 5,
    record_access: bool = True,
    scope: str = "",
) -> List[Tuple[MemoryNode, float]]:
    """不带理由的兼容封装：返回 (node, rrf_score)，行为与 v0.13 一致。"""
    return [
        (n, s)
        for n, s, _ in search_with_reasons(
            store, embedder, query, k=k, record_access=record_access, scope=scope
        )
    ]
