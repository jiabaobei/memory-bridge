"""存储层：SQLite 单文件持久化（TMT 四级驻留的 v0 载体）。

v0 实现 T3（本地长时驻留）与热度排序；T1/T2 边缘驻留、T4 云归档在 Phase 3
引入（见 docs/roadmap.md）。单文件 SQLite 的理由：全平台无部署、便于备份、
便于整库加密（Phase 2）。向量检索 v0 为余弦暴力扫描，规模化后换 sqlite-vec。
"""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .embeddings import cosine
from .node import MemoryNode


def default_db_path() -> str:
    """一台设备一份**全局记忆库**（产品语义，v0.4.1 确立）。

    记忆跟着人走而不是跟着项目走：init / doctor / add / search / stats 等
    全部命令默认解析到同一份库（环境变量 MEMBRIDGE_DB 优先，其次
    ~/.membridge/memory.db）。需要项目级隔离时显式传 --db。
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
    src    TEXT NOT NULL,
    dst    TEXT NOT NULL,
    weight REAL NOT NULL,
    PRIMARY KEY (src, dst)
);
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


class MemoryStore:
    """一个设备上的一份记忆库，对应论文中单设备的语义拓扑 G=(N, E, W)。"""

    def __init__(self, path: str = "membridge.db", device: Optional[str] = None) -> None:
        self.path = path
        # 父目录不存在时 sqlite3 会拒绝建库（v0.4.1 修复：init 在全新机器上崩溃）
        parent = os.path.dirname(os.path.abspath(path))
        os.makedirs(parent, exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.executescript(_SCHEMA)
        self.conn.commit()
        if device:
            self.set_device(device)

    # ---------- 设备标识 ----------

    def set_device(self, name: str) -> None:
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
        self._set_meta("netdisk_dir", path)

    # ---------- 节点（SAN 的 N） ----------

    def add(self, node: MemoryNode) -> MemoryNode:
        self.conn.execute(
            "INSERT OR REPLACE INTO nodes VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                node.node_id,
                node.content,
                json.dumps(node.embedding),
                json.dumps(node.tags, ensure_ascii=False),
                node.scene,
                node.device,
                node.migration,
                node.confidence,
                node.created_at,
                node.last_access,
                node.access_count,
            ),
        )
        self.conn.commit()
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
        """记录一次检索命中：last_access 置为当前，access_count 加一。"""
        import time

        self.conn.execute(
            "UPDATE nodes SET last_access = ?, access_count = access_count + 1 "
            "WHERE node_id = ?",
            (time.time(), node_id),
        )
        self.conn.commit()

    # ---------- 边（SAN 的 E 与 W） ----------

    def add_edge(self, src: str, dst: str, weight: float) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO edges VALUES (?,?,?)", (src, dst, weight)
        )
        self.conn.commit()

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
        self, query_vec: List[float], k: int = 5, record_access: bool = True
    ) -> List[Tuple[MemoryNode, float]]:
        """余弦暴力检索，返回 (node, score) 降序。命中默认记一次访问。"""
        scored = [
            (n, cosine(query_vec, n.embedding)) for n in self.all_nodes()
        ]
        scored = [t for t in scored if t[1] > 0.0]
        scored.sort(key=lambda t: t[1], reverse=True)
        hits = scored[:k]
        if record_access:
            for n, _ in hits:
                self.touch(n.node_id)
        return hits

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
            "netdisk": self.netdisk or "未配置（跨设备未启用）",
        }

    # ---------- 内部 ----------

    @staticmethod
    def _row_to_node(row: Tuple) -> MemoryNode:
        return MemoryNode(
            node_id=row[0],
            content=row[1],
            embedding=json.loads(row[2]),
            tags=json.loads(row[3]),
            scene=row[4],
            device=row[5],
            migration=row[6],
            confidence=row[7],
            created_at=row[8],
            last_access=row[9],
            access_count=row[10],
        )

    def _set_meta(self, key: str, value: str) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO meta VALUES (?,?)", (key, value)
        )
        self.conn.commit()

    def _get_meta(self, key: str) -> Optional[str]:
        row = self.conn.execute(
            "SELECT value FROM meta WHERE key = ?", (key,)
        ).fetchone()
        return row[0] if row else None

    def close(self) -> None:
        self.conn.close()
