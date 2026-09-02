"""容器一致性层（v0.16）：跨端 schema 协商、对账与自动对齐。

背景（RFC-002）：v0.13「通道归一」只统一了**通道指向哪个云盘**，
没有统一**容器长什么样**——各端 SQLite 字段集 / 边类型枚举各写各的，
跨设备 fetch 后边类型被丢成默认，即用户观察到的「路通了、容器不一致」。

v0.16 在 v0.15 基础上吸收三个开源借鉴：
- mem0：三存储平面声明（graph/vector/kv），三平面齐备才算容器一致；
- zillur-av/docker-image-schemavalidator：差分包携带 schema 指纹，
  接收端先对账后合并；
- 0xPlaygrounds/rig：seq 版本协商 + 幂等收敛（watermark 只增不减）。

本层做四件事：
1. 容器清单 manifest：每端**从实际表结构读出**自述（不硬编码相信声明）
2. 差分携带指纹：delta 包带 schema，接收端**先对账后合并**
3. 自动对齐：缺字段按 MIGRATIONS **真 ALTER 补列**（不是只声明），
   无迁移登记才拒绝并给出升级路径
4. 三存储平面与同步水位线：体检可查缺平面 / 各设备最近同步进度

零依赖（仅标准库）；不改写任何既有记忆内容，只补结构。
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List, Tuple

SCHEMA_VERSION = "0.16.0"

# 容器字段声明（跨端按集合比较，顺序无关）
NODE_FIELDS = (
    "node_id content embedding tags scene device migration confidence "
    "kind created_at last_access access_count"
).split()
EDGE_FIELDS = ["src", "dst", "weight", "kind", "evidence"]

# 边类型枚举：v0.14 三型 + v0.15 补 handoff（交接） / supersede（取代）
KIND_ENUM = ["semantic", "cooccur", "entity", "handoff", "supersede"]

# 三存储平面声明（借鉴 mem0 的 Graph+Vector+KV 模型：三平面齐备才算容器一致）
#   graph  —— edges 表：图结构（src/dst/weight/kind/evidence）
#   vector —— nodes.embedding 列：向量召回
#   kv     —— meta 表：键值元数据（设备名/嵌入器指纹/同步水位线）
STORAGE_PLANES = {
    "graph": "edges",
    "vector": "nodes.embedding",
    "kv": "meta",
}

# 同步水位线 meta 键前缀：sync_watermark_<device> = 该设备最近一次已应用的 seq。
# 借鉴 rig 的 CRDT 思想（manifest 协商 + 序号）：seq 单调递增，重复/乱序包
# 由内容指纹去重天然幂等，watermark 记录版本协商进度供体检诊断。
WATERMARK_PREFIX = "sync_watermark_"

# 迁移登记表： "<表>.<列>" -> (引入版本, SQLite 类型, 默认值)
MIGRATIONS: Dict[str, Tuple[str, str, Any]] = {
    "nodes.kind": ("0.9", "TEXT", ""),
    "edges.kind": ("0.14", "TEXT", "semantic"),
    "edges.evidence": ("0.14", "TEXT", ""),
}


def _norm(names) -> List[str]:
    """字段集归一：去空白 + 排序，保证跨端顺序无关比较。"""
    return sorted({str(n).strip() for n in names if str(n).strip()})


def manifest_fp(manifest: Dict) -> str:
    """容器指纹：字段集 + 类型枚举的哈希（不含 device / 时间等易变项）。

    顺序无关——两端字段声明顺序不同不算不一致，避免误报。
    """
    core = {
        "schema_version": str(manifest.get("schema_version", "")),
        "node_fields": _norm(manifest.get("node_fields", [])),
        "edge_fields": _norm(manifest.get("edge_fields", [])),
        "kind_enum": _norm(manifest.get("kind_enum", [])),
        "storage_planes": _norm(manifest.get("storage_planes", [])),
    }
    blob = json.dumps(core, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.blake2b(blob, digest_size=8).hexdigest()


def _storage_planes(store) -> List[str]:
    """从实际表结构读出本端具备的存储平面（缺表/缺列即不算有）。"""
    tables = {
        r[0] for r in store.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    planes: List[str] = []
    if "edges" in tables:
        ec = {r[1] for r in store.conn.execute("PRAGMA table_info(edges)")}
        if {"src", "dst", "weight"} <= ec:
            planes.append("graph")
    if "nodes" in tables:
        nc = {r[1] for r in store.conn.execute("PRAGMA table_info(nodes)")}
        if "embedding" in nc:
            planes.append("vector")
    if "meta" in tables:
        planes.append("kv")
    return planes


def local_manifest(store) -> Dict:
    """生成本端容器自述清单（从实际表结构读出，而非相信硬编码声明）。"""
    ncols = [r[1] for r in store.conn.execute("PRAGMA table_info(nodes)")]
    ecols = [r[1] for r in store.conn.execute("PRAGMA table_info(edges)")]
    return {
        "schema_version": SCHEMA_VERSION,
        "device": getattr(store, "device_name", "unknown"),
        "node_fields": ncols,
        "edge_fields": ecols,
        "kind_enum": list(KIND_ENUM),
        "storage_planes": _storage_planes(store),
        "migrations": {k: [v[0], v[1], v[2]] for k, v in MIGRATIONS.items()},
    }


def diff_manifest(local: Dict, remote: Dict) -> Dict[str, List[str]]:
    """对账：远端有哪些本端没有的字段 / 类型枚举 / 存储平面。"""
    ln, le = _norm(local.get("node_fields")), _norm(local.get("edge_fields"))
    rn, re_ = _norm(remote.get("node_fields")), _norm(remote.get("edge_fields"))
    lk, rk = _norm(local.get("kind_enum")), _norm(remote.get("kind_enum"))
    lp, rp = _norm(local.get("storage_planes")), _norm(remote.get("storage_planes"))
    return {
        "missing_node_fields": [f for f in rn if f not in ln],
        "missing_edge_fields": [f for f in re_ if f not in le],
        "missing_kinds": [k for k in rk if k not in lk],
        "missing_storage_planes": [p for p in rp if p not in lp],
    }


def reconcile(store, remote: Dict) -> Dict:
    """跨端容器对账 + 自动对齐（真 ALTER 补列）。

    返回 {ok, fp_local, fp_remote, diff, applied, missing_kinds, note}。
    本端能补的列就地补齐；无迁移登记的字段才判不兼容并给出升级路径。
    """
    local = local_manifest(store)
    d = diff_manifest(local, remote)
    applied: List[str] = []

    for table, fields in (
        ("nodes", d["missing_node_fields"]),
        ("edges", d["missing_edge_fields"]),
    ):
        for f in fields:
            reg = MIGRATIONS.get(f"{table}.{f}")
            if not reg:
                return {
                    "ok": False,
                    "fp_local": manifest_fp(local),
                    "fp_remote": manifest_fp(remote),
                    "diff": d,
                    "applied": applied,
                    "missing_kinds": d["missing_kinds"],
                    "missing_storage_planes": d["missing_storage_planes"],
                    "note": (
                        f"无法自动补列 {table}.{f}（无迁移登记）；"
                        f"请升级记忆桥到 >= {remote.get('schema_version', '?')}"
                    ),
                }
            _ver, typ, default = reg
            lit = "''" if isinstance(default, str) else str(default)
            store.conn.execute(
                f"ALTER TABLE {table} ADD COLUMN {f} {typ} NOT NULL DEFAULT {lit}"
            )
            applied.append(f"{table}.{f}")

    if applied:
        store.conn.commit()
        local = local_manifest(store)

    return {
        "ok": True,
        "fp_local": manifest_fp(local),
        "fp_remote": manifest_fp(remote),
        "diff": d,
        "applied": applied,
        "missing_kinds": d["missing_kinds"],
        "missing_storage_planes": d["missing_storage_planes"],
        "note": ("已补列：" + "、".join(applied)) if applied else "容器已一致",
    }
