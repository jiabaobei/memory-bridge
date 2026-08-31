"""存储层：SQLite 单文件持久化（TMT 四级驻留的 v0 载体）。

v0 实现 T3（本地长时驻留）与热度排序；T1/T2 边缘驻留、T4 云归档在 Phase 3
引入（见 docs/roadmap.md）。单文件 SQLite 的理由：全平台无部署、便于备份、
便于整库加密（Phase 2）。

v0.8 工程修订（对照 RFC 评审）：
- WAL + busy_timeout：MCP Server 多客户端并发读写不再互相锁死
- transaction() 上下文管理器：写操作收敛为单事务，替代逐语句 commit
- embedding 以 float32 BLOB 存储（JSON 文本的 1/3～1/5 体积），旧库打开时
  一次性自动迁移，差分线上格式不变（跨版本设备仍可互相同步）
- 检索两阶段：BLOB 快扫打分 → 只对 top-k 取完整节点；向量进程内缓存
- 相对阈值 rel_floor：低于 top1×rel_floor 的弱命中不返回（省 token）

向量检索 v0 为余弦暴力扫描；规模化的 sqlite-vec 走可选依赖（capabilities
探测），保持核心零依赖（见 docs/roadmap.md Phase 1+）。
"""

from __future__ import annotations

import json
import os
import sqlite3
import struct
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Tuple

from .embeddings import cosine
from .node import MemoryNode

EMBEDDING_FORMAT = "f32-blob-v1"  # meta 中记录的 embedding 存储格式
GAP_LIMIT = 20                    # 缺口发现最多保留的零命中查询条数（v0.9）


def default_db_path() -> str:
    """一台设备一份**全局记忆库**（产品语义，v0.4.1 确立）。

    记忆跟着人走而不是跟着项目走：init / doctor / add / search / stats 等
    全部命令默认解析到同一份库（环境变量 MEMBRIDGE_DB 优先，其次
    ~/.membridge/memory.db）。需要项目级隔离时显式传 --db。
    v0.8 起 MCP server 的 open_store 也走本函数——全项目禁止 CWD 相对兜底。
    """
    return os.environ.get("MEMBRIDGE_DB") or str(
        Path.home() / ".membridge" / "memory.db"
    )

_SCHEMA = """
CREATE TABLE IF NOT EXISTS nodes (
    node_id      TEXT PRIMARY KEY,
    content      TEXT NOT NULL,
    embedding    TEXT NOT NULL,
    tags         TEXT NOT NULL DEFAULT '[]',
    scene        TEXT NOT NULL DEFAULT 'personal',
    device       TEXT NOT NULL DEFAULT 'unknown',
    migration    TEXT NOT NULL DEFAULT 'edge',
    confidence   REAL NOT NULL DEFAULT 1.0,
    created_at   REAL NOT NULL,
    last_access  REAL NOT NULL,
    access_count INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS edges (
    src      TEXT NOT NULL,
    dst      TEXT NOT NULL,
    weight   REAL NOT NULL,
    kind     TEXT NOT NULL DEFAULT '',
    evidence TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (src, dst)
);
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def _pack_vec(vec: List[float]) -> bytes:
    """向量 → float32 little-endian BLOB。"""
    return struct.pack(f"<{len(vec)}f", *vec)


def _unpack_vec(blob: bytes) -> List[float]:
    """float32 BLOB → 向量。"""
    return list(struct.unpack(f"<{len(blob) // 4}f", blob))


class MemoryStore:
    """一个设备上的一份记忆库，对应论文中单设备的语义拓扑 G=(N, E, W)。

    写事务约定（v0.8）：未包事务的单条写即时提交（与 v0.7 行为一致，跨连接
    立即可见）；需要原子性的一组写入用 `with store.transaction():` 收敛为
    单次提交，异常时整体回滚。
    """

    def __init__(self, path: str = "membridge.db", device: Optional[str] = None) -> None:
        self.path = path
        # 父目录不存在时 sqlite3 会拒绝建库（v0.4.1 修复：init 在全新机器上崩溃）
        parent = os.path.dirname(os.path.abspath(path))
        os.makedirs(parent, exist_ok=True)
        # check_same_thread=False：v0.11 网关在子线程处理请求需要跨线程用连接；
        # 并发安全由 WAL + busy_timeout + 事务收敛保证（MCP 多进程场景本就如此）
        self.conn = sqlite3.connect(path, timeout=5.0, check_same_thread=False)
        # WAL：读写不互斥；busy_timeout：并发写短暂等待而非立刻报 locked
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA busy_timeout=5000")
        self.conn.executescript(_SCHEMA)
        self._migrate_columns()
        self.conn.commit()
        # 检索向量缓存：node_id → (存储字节, 解码后向量)；add 时同步更新
        self._vec_cache: Dict[str, Tuple[bytes, List[float]]] = {}
        # 事务深度：0 = 无显式事务（单条写自动提交，保持 v0.7 行为）；
        # ≥1 = 处于 transaction() 内（提交收敛到最外层出口）
        self._tx_depth = 0
        self._migrate_embedding_format()
        if device:
            with self.transaction():
                self._set_meta("device", device)

    # ---------- 事务 ----------

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """把一组写操作收敛为单个事务：异常整体回滚，正常退出一次提交。

        典型用法：memory_add 的 add + build_edges、apply_delta 的批量落库。
        事务内的单条写不再各自 commit；未包事务的零散写入仍即时提交
        （跨连接立即可见），与 v0.7 行为兼容。
        """
        self._tx_depth += 1
        try:
            yield self.conn
            self._tx_depth -= 1
            if self._tx_depth == 0:
                self.conn.commit()
        except Exception:
            self._tx_depth -= 1
            if self._tx_depth == 0:
                self.conn.rollback()
            raise

    # ---------- 设备标识 ----------

    def set_device(self, name: str) -> None:
        with self.transaction():
            self._set_meta("device", name)

    @property
    def device_name(self) -> str:
        return self._get_meta("device") or "unknown"

    # ---------- 云盘通道（跨设备同步）----------

    @property
    def netdisk(self) -> Optional[str]:
        """本机已配置的云盘通道目录（未配置时为 None）。"""
        return self._get_meta("netdisk_dir")

    def set_netdisk(self, path: str) -> None:
        with self.transaction():
            self._set_meta("netdisk_dir", path)

    @property
    def channel_id(self) -> Optional[str]:
        """本机认领的通道身份（v0.13；未认领时为 None）。"""
        return self._get_meta("channel_id")

    def set_channel_id(self, channel_id: str) -> None:
        with self.transaction():
            self._set_meta("channel_id", channel_id)

    # ---------- 节点（SAN 的 N） ----------

    def add(self, node: MemoryNode) -> MemoryNode:
        blob = _pack_vec(node.embedding)
        self.conn.execute(
            "INSERT OR REPLACE INTO nodes VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                node.node_id,
                node.content,
                sqlite3.Binary(blob),
                json.dumps(node.tags, ensure_ascii=False),
                node.scene,
                node.device,
                node.migration,
                node.confidence,
                node.created_at,
                node.last_access,
                node.access_count,
                node.kind,
            ),
        )
        self._vec_cache[node.node_id] = (blob, list(node.embedding))
        self._commit_if_autonomous()
        return node

    def get(self, node_id: str) -> Optional[MemoryNode]:
        row = self.conn.execute(
            "SELECT * FROM nodes WHERE node_id = ?", (node_id,)
        ).fetchone()
        return self._row_to_node(row) if row else None

    def all_nodes(self) -> List[MemoryNode]:
        rows = self.conn.execute("SELECT * FROM nodes").fetchall()
        return [self._row_to_node(r) for r in rows]

    def count_nodes(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]

    def touch(self, node_id: str) -> None:
        """记录一次检索命中：last_access 置为当前，access_count 加一（独立提交）。"""
        with self.transaction():
            self._touch_uncommitted(node_id)

    def _touch_uncommitted(self, node_id: str) -> None:
        self.conn.execute(
            "UPDATE nodes SET last_access = ?, access_count = access_count + 1 "
            "WHERE node_id = ?",
            (time.time(), node_id),
        )

    # ---------- 边（SAN 的 E 与 W） ----------

    def add_edge(self, src: str, dst: str, weight: float,
                 kind: str = "", evidence: str = "") -> None:
        """写入一条带类型的边。

        kind     semantic（语义/共现混合）| cooccur（字面共现主导）
                 | entity（共享确定性实体锚点）
        evidence 极短依据串（如 `cos=0.72` / `ent:memory-bridge`），
                 只在需要解释"为什么相关"时读取，不进检索上下文（省 token）。
        """
        self.conn.execute(
            "INSERT OR REPLACE INTO edges VALUES (?,?,?,?,?)",
            (src, dst, weight, kind, evidence),
        )
        self._commit_if_autonomous()

    def edge_weight(self, src: str, dst: str) -> Optional[float]:
        row = self.conn.execute(
            "SELECT weight FROM edges WHERE src = ? AND dst = ?", (src, dst)
        ).fetchone()
        return row[0] if row else None

    def all_edges(self) -> List[Tuple[str, str, float]]:
        rows = self.conn.execute("SELECT src, dst, weight FROM edges").fetchall()
        return [(r[0], r[1], r[2]) for r in rows]

    def count_edges(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0]

    def neighbor_ids(self, node_id: str) -> List[Tuple[str, float]]:
        """只取邻居 id 与权重（不解码节点）——聚类/图游走场景省 IO。"""
        rows = self.conn.execute(
            "SELECT dst, weight FROM edges WHERE src = ? "
            "UNION ALL SELECT src, weight FROM edges WHERE dst = ?",
            (node_id, node_id),
        ).fetchall()
        return [(r[0], r[1]) for r in rows]

    def all_edge_pairs(self) -> List[Tuple[str, str]]:
        """只取 (src, dst) 对——连通分量聚类用，避免解码 weight 与节点。"""
        rows = self.conn.execute("SELECT src, dst FROM edges").fetchall()
        return [(r[0], r[1]) for r in rows]

    def edge_kinds(self) -> Dict[str, int]:
        """边类型分布（stats 展示用）。"""
        out: Dict[str, int] = {}
        for kind, cnt in self.conn.execute(
            "SELECT kind, COUNT(*) FROM edges GROUP BY kind"
        ):
            out[kind or "unlabeled"] = cnt
        return out

    def neighbors(self, node_id: str) -> List[Tuple[MemoryNode, float]]:
        """SAN 邻居查询原语 N1(n)（论文 §3.7.4 动作空间的基础）。"""
        rows = self.conn.execute(
            "SELECT dst, weight FROM edges WHERE src = ? "
            "UNION ALL SELECT src, weight FROM edges WHERE dst = ?",
            (node_id, node_id),
        ).fetchall()
        out: List[Tuple[MemoryNode, float]] = []
        for other_id, w in rows:
            n = self.get(other_id)
            if n is not None:
                out.append((n, w))
        out.sort(key=lambda t: t[1], reverse=True)
        return out

    # ---------- 检索 ----------

    def search(
        self,
        query_vec: List[float],
        k: int = 5,
        record_access: bool = True,
        rel_floor: float = 0.5,
    ) -> List[Tuple[MemoryNode, float]]:
        """余弦检索，返回 (node, score) 降序。

        两阶段：先只读 node_id + embedding（BLOB 快扫打分），再仅对 top-k
        取完整节点——避免全表逐行解码。rel_floor 为相对阈值：低于
        top1×rel_floor 的弱命中不返回（噪声记忆不进上下文，省 token）；
        传 0 关闭。命中默认记一次访问（单个事务批量提交，TMT 热度依据）。
        """
        rows = self.conn.execute("SELECT node_id, embedding FROM nodes").fetchall()
        scored: List[Tuple[str, float]] = []
        for node_id, blob in rows:
            cached = self._vec_cache.get(node_id)
            if cached is not None and cached[0] == blob:
                vec = cached[1]
            else:
                vec = self._decode_embedding(blob)
                self._vec_cache[node_id] = (blob, vec)
            s = cosine(query_vec, vec)
            if s > 0.0:
                scored.append((node_id, s))
        scored.sort(key=lambda t: t[1], reverse=True)
        if scored and rel_floor > 0.0:
            floor = scored[0][1] * rel_floor
            scored = [t for t in scored if t[1] >= floor]
        hits: List[Tuple[MemoryNode, float]] = []
        for node_id, s in scored[:k]:
            node = self.get(node_id)
            if node is not None:
                hits.append((node, s))
        if record_access and hits:
            with self.transaction():
                for n, _ in hits:
                    self._touch_uncommitted(n.node_id)
        return hits

    # ---------- 缺口发现（v0.9）----------

    def record_gap(self, query: str) -> None:
        """记录一条零命中查询（纯元数据，内容冻结无损）。

        借鉴 Knowledge OS「检索即更新」的安全子集：系统只记录缺口并在
        doctor 中提醒，补写什么、要不要补永远由用户决定。
        """
        q = query.strip()
        if not q:
            return
        gaps = self.gap_queries()
        if any(g.get("q") == q for g in gaps):
            return
        gaps.insert(0, {"q": q[:80], "t": time.time()})
        with self.transaction():
            self._set_meta(
                "gap_queries", json.dumps(gaps[:GAP_LIMIT], ensure_ascii=False)
            )

    def gap_queries(self) -> List[Dict]:
        """最近的零命中查询列表（新→旧，至多 GAP_LIMIT 条）。"""
        raw = self._get_meta("gap_queries")
        if not raw:
            return []
        try:
            gaps = json.loads(raw)
            return gaps if isinstance(gaps, list) else []
        except (ValueError, TypeError):
            return []

    # ---------- 统计 ----------

    def stats(self) -> Dict:
        by_migration: Dict[str, int] = {}
        for n in self.all_nodes():
            by_migration[n.migration] = by_migration.get(n.migration, 0) + 1
        return {
            "path": self.path,
            "device": self.device_name,
            "nodes": self.count_nodes(),
            "edges": self.count_edges(),
            "by_migration": by_migration,
            "edge_kinds": self.edge_kinds(),
            "netdisk": self.netdisk or "未配置（跨设备未启用）",
        }

    # ---------- 内部 ----------

    def _migrate_columns(self) -> None:
        """旧库平滑加列（幂等）。

        v0.9 新增 nodes.kind（可选记忆类型标注）；
        v0.14 新增 edges.kind / edges.evidence（类型化边 + 证据）。
        存量边统一标记为 semantic——它们确实由 λ·PMI+(1-λ)·cos 算得，
        标注只是把既有事实显式化，不改任何权重、不碰记忆内容。
        """
        cols = [r[1] for r in self.conn.execute("PRAGMA table_info(nodes)")]
        if "kind" not in cols:
            self.conn.execute(
                "ALTER TABLE nodes ADD COLUMN kind TEXT NOT NULL DEFAULT ''"
            )
        ecols = [r[1] for r in self.conn.execute("PRAGMA table_info(edges)")]
        if "kind" not in ecols:
            self.conn.execute(
                "ALTER TABLE edges ADD COLUMN kind TEXT NOT NULL DEFAULT ''"
            )
            self.conn.execute("UPDATE edges SET kind='semantic' WHERE kind=''")
        if "evidence" not in ecols:
            self.conn.execute(
                "ALTER TABLE edges ADD COLUMN evidence TEXT NOT NULL DEFAULT ''"
            )

    def _decode_embedding(self, blob) -> List[float]:
        """兼容两种存储：v0.8 float32 BLOB（bytes）与 v0.7 JSON 文本（str）。"""
        if isinstance(blob, bytes):
            return _unpack_vec(blob)
        return json.loads(blob)

    def _migrate_embedding_format(self) -> None:
        """v0.7 及之前 embedding 以 JSON 文本存储；打开旧库时一次性迁移为 BLOB。"""
        if self._get_meta("embedding_format") == EMBEDDING_FORMAT:
            return
        rows = self.conn.execute("SELECT node_id, embedding FROM nodes").fetchall()
        for node_id, emb in rows:
            if isinstance(emb, str):
                self.conn.execute(
                    "UPDATE nodes SET embedding = ? WHERE node_id = ?",
                    (sqlite3.Binary(_pack_vec(json.loads(emb))), node_id),
                )
        with self.transaction():
            self._set_meta("embedding_format", EMBEDDING_FORMAT)

    @staticmethod
    def _row_to_node(row: Tuple) -> MemoryNode:
        emb = row[2]
        if isinstance(emb, bytes):
            emb = _unpack_vec(emb)
        else:
            emb = json.loads(emb)
        return MemoryNode(
            node_id=row[0],
            content=row[1],
            embedding=emb,
            tags=json.loads(row[3]),
            scene=row[4],
            device=row[5],
            migration=row[6],
            confidence=row[7],
            created_at=row[8],
            last_access=row[9],
            access_count=row[10],
            kind=row[11] if len(row) > 11 else "",
        )

    def _set_meta(self, key: str, value: str) -> None:
        """写 meta（不在事务内时即时提交；在事务内则收敛到外层出口）。"""
        self.conn.execute(
            "INSERT OR REPLACE INTO meta VALUES (?,?)", (key, value)
        )
        self._commit_if_autonomous()

    def _commit_if_autonomous(self) -> None:
        """事务深度为 0 时提交（保持零散写即时持久化；事务内由外层统一提交）。"""
        if self._tx_depth == 0:
            self.conn.commit()

    def _get_meta(self, key: str) -> Optional[str]:
        row = self.conn.execute(
            "SELECT value FROM meta WHERE key = ?", (key,)
        ).fetchone()
        return row[0] if row else None

    def close(self) -> None:
        """兜底提交未包事务的零散写入后关闭连接。"""
        try:
            self.conn.commit()
        except Exception:
            pass
        self.conn.close()
