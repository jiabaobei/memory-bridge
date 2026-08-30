"""同步层：DSS 增量语义同步（论文 §3.4）。

    ΔG_{A→B} = (G_A \\ G_B) ∪ {w_ij | w_ij^A ≠ w_ij^B}

- 节点指纹：对规范化内容做哈希（语义哈希 h(n_i)），存在性比较 O(1)
- 边差异量化：仅 |Δw| > ε 才同步，避免浮点漂移导致的无效传输
- v0 覆盖差异计算 + 编码 + 应用（纯本地计算，无网络依赖）；
  传输通道（端到端加密中继）在 Phase 2 接入，见 docs/threat-model.md

发送端门控：migration=local 的节点在差分包生成前即被 PAMS L1 过滤，
永不进入传输载荷。
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

from .node import MemoryNode
from .privacy import preload_allowed
from .store import MemoryStore

EPSILON = 0.01  # 论文 §4.1 可复现性声明：DSS 边差异阈值 ε


def fingerprint(content: str) -> str:
    """节点语义哈希 h(n_i)：空白与大小写归一后的内容指纹。"""
    normalized = re.sub(r"\s+", "", content.lower())
    return hashlib.blake2b(normalized.encode("utf-8"), digest_size=16).hexdigest()


@dataclass
class Delta:
    """一份跨设备同步差异（语义子图差分）。

    nodes 为缺失节点的只读拷贝（内容冻结：接收端原样落库，不改写）；
    edges 为权重差异超过 ε 的边。seq 字段为版本向量占位，Phase 2 启用。
    embedder 为自描述指纹（仿 ncnn param/bin 的自描述思想）：记录产生本包
    的嵌入器身份，接收端用它做一致性握手——fp 不一致则拒绝应用向量。
    """

    from_device: str
    to_device: str
    nodes: List[Dict] = field(default_factory=list)
    edges: List[Tuple[str, str, float]] = field(default_factory=list)
    seq: int = 0
    embedder: Optional[Dict] = None

    def to_json(self) -> str:
        return json.dumps(
            {
                "from_device": self.from_device,
                "to_device": self.to_device,
                "seq": self.seq,
                "nodes": self.nodes,
                "edges": [list(e) for e in self.edges],
                "embedder": self.embedder,
            },
            ensure_ascii=False,
        )

    @classmethod
    def from_json(cls, s: str) -> "Delta":
        d = json.loads(s)
        return cls(
            from_device=d.get("from_device", "unknown"),
            to_device=d.get("to_device", "unknown"),
            nodes=d.get("nodes", []),
            edges=[tuple(e) for e in d.get("edges", [])],
            seq=d.get("seq", 0),
            embedder=d.get("embedder"),
        )


def compute_delta(
    local: MemoryStore,
    remote: MemoryStore,
    allowed: Optional[Callable[[MemoryNode], bool]] = None,
    eps: float = EPSILON,
    embedder_info: Optional[Dict] = None,
) -> Delta:
    """计算 local → remote 的差异子图（纯本地计算，可直接单机双库模拟）。"""
    return _delta_against(
        local,
        remote_fps={fingerprint(n.content) for n in remote.all_nodes()},
        remote_node_ids={n.node_id for n in remote.all_nodes()},
        remote_edge_weight=remote.edge_weight,
        allowed=allowed,
        eps=eps,
        to_device=remote.device_name,
        embedder_info=embedder_info,
    )


def delta_unsent(
    local: MemoryStore,
    published_fps: set,
    allowed: Optional[Callable[[MemoryNode], bool]] = None,
    eps: float = EPSILON,
    embedder_info: Optional[Dict] = None,
) -> Delta:
    """计算本设备"尚未发布过"的差异包（网盘中转通道使用）。

    published_fps 为本设备已向通道发布过的节点指纹集合（由调用方持久化，
    见 transport.FolderTransport）。远端节点集合未知，因此边只随新节点
    一起发布；接收端按指纹去重，重复接收亦幂等。
    """
    return _delta_against(
        local,
        remote_fps=set(published_fps),
        remote_node_ids=set(),
        remote_edge_weight=None,
        allowed=allowed,
        eps=eps,
        to_device="*",
        embedder_info=embedder_info,
    )


def _delta_against(
    local: MemoryStore,
    remote_fps: set,
    remote_node_ids: set,
    remote_edge_weight: Optional[Callable[[str, str], Optional[float]]],
    allowed: Optional[Callable[[MemoryNode], bool]],
    eps: float,
    to_device: str,
    embedder_info: Optional[Dict] = None,
) -> Delta:
    gate = allowed if allowed is not None else (lambda n: preload_allowed(n))
    delta = Delta(from_device=local.device_name, to_device=to_device, embedder=embedder_info)

    for n in local.all_nodes():
        if not gate(n):
            continue
        if fingerprint(n.content) not in remote_fps:
            delta.nodes.append(n.to_dict())

    # 边差分：两端点在接收端"已知"（已存在或随本次差分到达）且差异超 ε 才同步
    known_target = set(remote_node_ids) | {d["node_id"] for d in delta.nodes}
    for src, dst, w in local.all_edges():
        if src not in known_target or dst not in known_target:
            continue
        rw = remote_edge_weight(src, dst) if remote_edge_weight else None
        if rw is None or abs(rw - w) > eps:
            delta.edges.append((src, dst, w))
    return delta


def apply_delta(store: MemoryStore, delta: Delta) -> Dict[str, int]:
    """把差异子图并入本地库（内容冻结：原样落库）。返回计数统计。

    一致性握手：若差分包携带 embedder 指纹且与本库记录的不一致
    （两端嵌入模型不同，向量不可比），拒绝应用并返回 rejected 原因。
    """
    local_id = store._get_meta("embedder_id")
    incoming = delta.embedder
    if incoming and local_id:
        try:
            local = json.loads(local_id)
        except Exception:
            local = None
        if local and incoming.get("fp") != local.get("fp"):
            return {
                "rejected": "embedder_mismatch",
                "nodes_added": 0,
                "nodes_skipped": 0,
                "edges_applied": 0,
                "local_fp": local.get("fp"),
                "incoming_fp": incoming.get("fp"),
            }
    if incoming and not local_id:
        store._set_meta("embedder_id", json.dumps(incoming, ensure_ascii=False))

    local_fps = {fingerprint(n.content) for n in store.all_nodes()}
    added = skipped = 0
    with store.transaction():
        if incoming and not local_id:
            store._set_meta("embedder_id", json.dumps(incoming, ensure_ascii=False))
        for d in delta.nodes:
            node = MemoryNode.from_dict(d)
            if fingerprint(node.content) in local_fps:
                skipped += 1
                continue
            store.add(node)
            local_fps.add(fingerprint(node.content))
            added += 1

        known = {n.node_id for n in store.all_nodes()}
        edges_applied = 0
        for src, dst, w in delta.edges:
            if src in known and dst in known:
                store.add_edge(src, dst, w)
                edges_applied += 1
    return {"nodes_added": added, "nodes_skipped": skipped, "edges_applied": edges_applied}
