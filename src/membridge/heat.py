"""缓存层：TMT 热度与预加载候选（论文 §3.3）。

论文公式：H(n_i) = Σ_k e^(−α_k·Δt_k) · I[device(n_i)=d_current] · γ_d

按约定，v0 采用"最近访问 + 访问频率"启发式近似，接口签名与论文对齐：
Phase 4 的 AEE/π_nav（图游走导航）只替换本模块实现，不影响上层调用。
时间衰减系数 alpha 的时间单位为小时，未来由 AEE 自适应调节（论文 §3.7.1）。
"""

from __future__ import annotations

import math
import time
from typing import Callable, List, Optional

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
