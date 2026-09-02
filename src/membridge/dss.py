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
from typing import Any, Callable, Dict, List, Optional, Tuple

from .node import MemoryNode
from .privacy import preload_allowed
from .schema import WATERMARK_PREFIX, local_manifest, manifest_fp, reconcile
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
    edges 为权重差异超过 ε 的边。seq 为版本协商序号（v0.16 启用，单调递增，
    接收端按 watermark 识别重复/乱序包，内容指纹去重天然幂等）。
    embedder 为自描述指纹（仿 ncnn param/bin 的自描述思想）：记录产生本包
    的嵌入器身份，接收端用它做一致性握手——fp 不一致则拒绝应用向量。

    v0.15 容器一致性（RFC-002）：edges_v2 携带 (src,dst,w,kind,evidence)
    五元组，补上 v0.14「边类型跨设备即丢」的洞；edges 三元组原样保留供
    旧端读取——旧端仍只看得到权重，不劣化、不崩（双键向后兼容）。
    schema / schema_fp 为本端容器清单及其指纹，接收端先对账再合并。
    """

    from_device: str
    to_device: str
    nodes: List[Dict] = field(default_factory=list)
    edges: List[Tuple[str, str, float]] = field(default_factory=list)
    edges_v2: List[Tuple[str, str, float, str, str]] = field(default_factory=list)
    seq: int = 0
    embedder: Optional[Dict] = None
    schema: Optional[Dict] = None
    schema_fp: str = ""

    def to_json(self) -> str:
        payload = {
            "from_device": self.from_device,
            "to_device": self.to_device,
            "seq": self.seq,
            "nodes": self.nodes,
            "edges": [list(e) for e in self.edges],
            "embedder": self.embedder,
        }
        # 新键仅在本端确实有类型化边 / 容器清单时才写，旧包体积不变
        if self.edges_v2:
            payload["edges_v2"] = [list(e) for e in self.edges_v2]
        if self.schema:
            payload["schema"] = self.schema
            payload["schema_fp"] = self.schema_fp
        return json.dumps(payload, ensure_ascii=False)

    @classmethod
    def from_json(cls, s: str) -> "Delta":
        d = json.loads(s)
        return cls(
            from_device=d.get("from_device", "unknown"),
            to_device=d.get("to_device", "unknown"),
            nodes=d.get("nodes", []),
            edges=[tuple(e) for e in d.get("edges", [])],
            edges_v2=[tuple(e) for e in d.get("edges_v2", [])],
            seq=d.get("seq", 0),
            embedder=d.get("embedder"),
            schema=d.get("schema"),
            schema_fp=d.get("schema_fp", ""),
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
    # v0.15 容器一致性：附上本端容器清单，供接收端合并前先对账
    delta.schema = local_manifest(local)
    delta.schema_fp = manifest_fp(delta.schema)
    # v0.16 版本协商（rig 借鉴）：seq 单调递增，接收端按 watermark 识别
    # 重复/乱序包——内容指纹去重天然幂等，seq 仅作版本进度记录与诊断。
    _cur = int(local._get_meta("sync_seq") or 0)
    delta.seq = _cur + 1
    local._set_meta("sync_seq", str(delta.seq))

    for n in local.all_nodes():
        if not gate(n):
            continue
        if fingerprint(n.content) not in remote_fps:
            delta.nodes.append(n.to_dict())

    # 边差分：两端点在接收端"已知"（已存在或随本次差分到达）且差异超 ε 才同步
    known_target = set(remote_node_ids) | {d["node_id"] for d in delta.nodes}
    # v0.15：优先取类型化边（含 kind/evidence）；老库无该列时退回三元组
    edge_rows = (
        local.all_edges_full()
        if hasattr(local, "all_edges_full")
        else [(s, d, w, "semantic", "") for s, d, w in local.all_edges()]
    )
    for src, dst, w, kind, ev in edge_rows:
        if src not in known_target or dst not in known_target:
            continue
        rw = remote_edge_weight(src, dst) if remote_edge_weight else None
        if rw is None or abs(rw - w) > eps:
            delta.edges.append((src, dst, w))
            delta.edges_v2.append((src, dst, w, kind, ev))
    return delta


def apply_delta(store: MemoryStore, delta: Delta) -> Dict[str, Any]:
    """把差异子图并入本地库（内容冻结：原样落库）。返回计数统计。

    两道一致性握手，任一不通过即拒绝应用：
    1. embedder 指纹——两端嵌入模型不同则向量不可比（v0.x 既有）；
    2. v0.15 容器清单——先对账本端 schema 并**就地补列**，无法补齐才拒绝，
       返回升级路径。这一步正是「各端容器一致性」的落地点。
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

    # v0.15 容器一致性对账：本端缺列就地补齐，无法补齐才拒绝并给出升级路径
    aligned: List[str] = []
    fp_local = ""
    if delta.schema:
        rec = reconcile(store, delta.schema)
        fp_local = rec["fp_local"]
        if not rec["ok"]:
            return {
                "rejected": "schema_incompatible",
                "nodes_added": 0,
                "nodes_skipped": 0,
                "edges_applied": 0,
                "schema_note": rec["note"],
                "schema_fp_local": rec["fp_local"],
                "schema_fp_remote": rec["fp_remote"],
            }
        aligned = rec["applied"]

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
        # 优先 edges_v2（携带 kind/evidence）；旧包无此键时退回三元组，
        # 按 v0.14 迁移约定兜底为 semantic——这类边本就由 λ·PMI+(1-λ)·cos 算得
        pairs = delta.edges_v2 or [(s, d, w, "semantic", "") for s, d, w in delta.edges]
        for src, dst, w, kind, ev in pairs:
            if src in known and dst in known:
                store.add_edge(src, dst, w, kind, ev)
                edges_applied += 1
        # v0.16 版本协商水位线（rig 借鉴）：记录来自各设备的最近已应用 seq，
        # 重复/乱序包被内容指纹去重拦下，watermark 只增不减，供体检诊断。
        if delta.seq:
            _key = WATERMARK_PREFIX + delta.from_device
            _prev = int(store._get_meta(_key) or 0)
            if delta.seq > _prev:
                store._set_meta(_key, str(delta.seq))
    out: Dict[str, Any] = {
        "nodes_added": added,
        "nodes_skipped": skipped,
        "edges_applied": edges_applied,
    }
    if delta.seq:
        out["seq"] = delta.seq
    if delta.schema:
        out["schema_aligned"] = aligned
        out["schema_fp"] = fp_local
    return out
