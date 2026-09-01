"""缓存层：TMT 热度与预加载候选（论文 §3.3）。

论文公式：H(n_i) = Σ_k e^(−α_k·Δt_k) · I[device(n_i)=d_current] · γ_d

按约定，v0 采用"最近访问 + 访问频率"启发式近似，接口签名与论文对齐：
Phase 4 的 AEE/π_nav（图游走导航）只替换本模块实现，不影响上层调用。
时间衰减系数 alpha 的时间单位为小时，未来由 AEE 自适应调节（论文 §3.7.1）。
"""

from __future__ import annotations

import math
import time
from typing import Callable, Dict, List, Optional

from .node import MemoryNode
from .store import MemoryStore

# 论文 §4.1 可复现性声明中的默认阈值
THETA_HOT = 0.4       # 热驻留阈值：H(n) 低于该值视为冷节点
THETA_PRELOAD = 0.6   # 预加载阈值
PRELOAD_BUDGET = 8    # 单次预加载节点数上限（对应导航游走的 budget K）


def heat(node: MemoryNode, now: Optional[float] = None, alpha: float = 0.5) -> float:
    """v0 热度 = recency（指数时间衰减）× frequency（对数频次增益）× confidence。"""
    dt_hours = ((now if now is not None else time.time()) - node.last_access) / 3600.0
    recency = math.exp(-alpha * max(0.0, dt_hours))
    frequency = 1.0 + math.log1p(node.access_count)
    return recency * frequency * node.confidence


def preload_candidates(
    store: MemoryStore,
    allowed: Callable[[MemoryNode], bool],
    k: int = PRELOAD_BUDGET,
    hot_only: bool = True,
) -> List[MemoryNode]:
    """按热度选出允许推送到目标设备的节点（TMT 预加载 v0：全局热度 Top-K）。

    allowed 为 PAMS L1/L2 门控（privacy.preload_allowed 的偏函数），
    论文 §3.7.4 的 π_nav 图游走导航在 Phase 4 替换此实现。
    """
    nodes = [n for n in store.all_nodes() if allowed(n)]
    ranked = sorted(nodes, key=heat, reverse=True)
    if hot_only:
        ranked = [n for n in ranked if heat(n) >= THETA_HOT]
    return ranked[:k]


def clusters(store: MemoryStore) -> Dict[str, int]:
    """连通分量聚类：把 SAN 切成记忆簇（v0.14，借鉴代码图谱的社区划分思路）。

    零依赖并查集实现，只为"整簇预加载"服务——切换设备时把当前任务所在
    的整簇记忆一次带过去，而不是零散按热度取 k 条。
    纯读图结构（只取边对），不触碰任何记忆内容。
    """
    parent: Dict[str, str] = {}

    def find(x: str) -> str:
        parent.setdefault(x, x)
        root = x
        while parent[root] != root:
            root = parent[root]
        while parent[x] != root:  # 路径压缩
            parent[x], x = root, parent[x]
        return root

    for n in store.all_nodes():
        find(n.node_id)
    for src, dst in store.all_edge_pairs():
        rs, rd = find(src), find(dst)
        if rs != rd:
            parent[rs] = rd

    remap: Dict[str, int] = {}
    out: Dict[str, int] = {}
    for nid in list(parent):
        root = find(nid)
        if root not in remap:
            remap[root] = len(remap)
        out[nid] = remap[root]
    return out


def preload_cluster(
    store: MemoryStore,
    allowed: Callable[[MemoryNode], bool],
    k: int = PRELOAD_BUDGET,
) -> List[MemoryNode]:
    """整簇预加载：取"当前最热节点所在的记忆簇"，按热度排序返回至多 k 条。

    与 preload_candidates（全局热度 Top-K）互补：全局热度给"最近常用的
    零散记忆"，整簇给"当前这条任务线上的完整上下文"——对应论文预加载
    主张的"切换即连续"：到新设备，整条任务线的记忆都已就位。

    v0.15：最新未过期交接卡若不在簇内（任务线刚开了新卡），把它顶到
    首位一起预加载——交接物先于记忆到位，接班才有"看交接单"的入口。
    """
    from .handoff import workbench

    groups = clusters(store)
    nodes = [n for n in store.all_nodes() if allowed(n)]
    if not nodes:
        return []
    hottest = max(nodes, key=heat)
    cid = groups.get(hottest.node_id)
    if cid is None:  # 无边 → 该节点自成一簇
        same = [hottest]
    else:
        same = [n for n in nodes if groups.get(n.node_id) == cid]
        same.sort(key=heat, reverse=True)
    card = workbench(store)
    if card is not None and allowed(card) and \
            all(n.node_id != card.node_id for n in same):
        same.insert(0, card)
    return same[:k]
