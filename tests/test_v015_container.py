"""v0.15 容器一致性回归测试（RFC-002）。

覆盖四条：
1. 边类型（kind/evidence）跨设备差分往返**不丢失**——v0.14 的洞
2. 旧端三元组差分包仍能被 v0.15 正确应用（向后兼容，不劣化）
3. 本端缺列时 reconcile **就地补列**（真改表结构，非仅声明）
4. 无迁移登记的字段判不兼容，并给出升级路径

跑法：python tests/test_v015_container.py
"""

from __future__ import annotations

import os
import sqlite3
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from membridge.dss import Delta, apply_delta, compute_delta  # noqa: E402
from membridge.node import MemoryNode  # noqa: E402
from membridge.schema import local_manifest, manifest_fp, reconcile  # noqa: E402
from membridge.store import MemoryStore  # noqa: E402

PASS, FAIL = [], []


def check(name: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(name)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


class _Bare:
    """裸库包装：只用 conn + device_name，绕开 MemoryStore 的自动迁移。

    测 reconcile 补列时必须绕开——否则 __init__ 里的 _migrate_columns()
    已经把列补齐，就观察不到「缺列 → 补列」这个行为了。
    """

    def __init__(self, conn, device: str) -> None:
        self.conn = conn
        self.device_name = device


def _add_pair(store, c1, c2):
    n1 = MemoryNode(content=c1, device=store.device_name)
    n2 = MemoryNode(content=c2, device=store.device_name)
    store.add(n1)
    store.add(n2)
    return n1, n2


_KEEP: list = []


def _tmp() -> str:
    """pytest 无 conftest 的裸跑兼容：模块内自管临时目录（防提前回收）。"""
    d = tempfile.TemporaryDirectory()
    _KEEP.append(d)
    return d.name


def test_edge_kind_survives_roundtrip() -> None:
    tmp = _tmp()
    """v0.14 的洞：边类型跨设备即丢。v0.15 必须保住。"""
    print("\n① 边类型跨设备往返")
    a = MemoryStore(os.path.join(tmp, "a.db"), device="DEV-A")
    b = MemoryStore(os.path.join(tmp, "b.db"), device="DEV-B")

    n1, n2 = _add_pair(a, "记忆桥 v0.15 容器一致性", "边类型跨设备不再丢失")
    a.add_edge(n1.node_id, n2.node_id, 0.8, kind="entity", evidence="ent:memory-bridge")

    delta = compute_delta(a, b)
    check("delta 携带 edges_v2 五元组", bool(delta.edges_v2), f"{delta.edges_v2}")
    check("delta 携带容器清单 schema", delta.schema is not None, f"fp={delta.schema_fp}")

    res = apply_delta(b, delta)
    got = b.all_edges_full()
    kinds = [e[3] for e in got]
    evids = [e[4] for e in got]

    check("节点已同步到 B 端", res.get("nodes_added") == 2, f"{res}")
    check("边的 kind 保住（v0.14 会丢）", kinds == ["entity"], f"得到 {kinds}")
    check("边的 evidence 保住", evids == ["ent:memory-bridge"], f"得到 {evids}")
    check(
        "两端容器指纹一致",
        manifest_fp(local_manifest(a)) == manifest_fp(local_manifest(b)),
        f"{manifest_fp(local_manifest(a))} vs {manifest_fp(local_manifest(b))}",
    )


def test_legacy_triple_delta() -> None:
    tmp = _tmp()
    """旧端发的三元组包：v0.15 必须照旧能吃下，不劣化不崩。"""
    print("\n② 旧端三元组包向后兼容")
    b = MemoryStore(os.path.join(tmp, "legacy_recv.db"), device="DEV-B")
    n1 = MemoryNode(content="旧端记忆甲", device="DEV-A")
    n2 = MemoryNode(content="旧端记忆乙", device="DEV-A")

    legacy = Delta(from_device="DEV-A", to_device="DEV-B")
    legacy.nodes = [n1.to_dict(), n2.to_dict()]
    legacy.edges = [(n1.node_id, n2.node_id, 0.6)]  # 只有三元组，无 edges_v2

    res = apply_delta(b, legacy)
    got = b.all_edges_full()
    check("旧包节点已应用", res.get("nodes_added") == 2, f"{res}")
    check("旧包边已应用", res.get("edges_applied") == 1, f"{res}")
    check("缺失类型按 semantic 兜底", [e[3] for e in got] == ["semantic"], f"{got}")

    # 序列化往返：旧包不含新键，JSON 体积不变
    payload = legacy.to_json()
    check("旧包不写 edges_v2 新键", "edges_v2" not in payload)
    check("旧包不写 schema 新键", "schema" not in payload)


def test_reconcile_adds_missing_columns() -> None:
    tmp = _tmp()
    """本端老库（缺 kind/evidence 列）吃到新包 → 就地补列。"""
    print("\n③ 缺列自动补齐（真改表结构）")
    path = os.path.join(tmp, "legacy.db")
    conn = sqlite3.connect(path)
    # 手工造 v0.13 老库：edges 无 kind / evidence 列
    conn.executescript(
        """
        CREATE TABLE nodes (
            node_id TEXT PRIMARY KEY, content TEXT NOT NULL, embedding TEXT NOT NULL,
            tags TEXT NOT NULL DEFAULT '[]', scene TEXT NOT NULL DEFAULT 'personal',
            device TEXT NOT NULL DEFAULT 'unknown',
            migration TEXT NOT NULL DEFAULT 'edge',
            confidence REAL NOT NULL DEFAULT 1.0,
            created_at REAL NOT NULL, last_access REAL NOT NULL,
            access_count INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE edges (
            src TEXT NOT NULL, dst TEXT NOT NULL, weight REAL NOT NULL,
            PRIMARY KEY (src, dst)
        );
        CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        """
    )
    conn.commit()

    old = _Bare(conn, "DEV-OLD")  # 绕开自动迁移，才能观察补列行为
    before = [r[1] for r in old.conn.execute("PRAGMA table_info(edges)")]
    check("老库确实缺 kind/evidence 列", "kind" not in before, f"{before}")

    remote = local_manifest(MemoryStore(os.path.join(tmp, "new.db"), device="DEV-NEW"))
    rec = reconcile(old, remote)
    after = [r[1] for r in old.conn.execute("PRAGMA table_info(edges)")]

    check("对账判定可补齐", rec["ok"] is True, rec.get("note", ""))
    check("edges.kind 已 ALTER 补上", "kind" in after, f"{after}")
    check("edges.evidence 已 ALTER 补上", "evidence" in after, f"{after}")
    check(
        "nodes.kind 已 ALTER 补上",
        "kind" in [r[1] for r in old.conn.execute("PRAGMA table_info(nodes)")],
    )
    check("补列后容器指纹对齐", rec["fp_local"] == rec["fp_remote"], f"{rec['note']}")
    conn.close()


def test_incompatible_schema() -> None:
    tmp = _tmp()
    """远端要无迁移登记的字段 → 判不兼容 + 给升级路径，不静默吞掉。"""
    print("\n④ 无迁移登记字段判不兼容")
    store = MemoryStore(os.path.join(tmp, "c.db"), device="DEV-C")
    hostile = local_manifest(store)
    hostile["edge_fields"] = list(hostile["edge_fields"]) + ["brand_new_col"]
    hostile["schema_version"] = "9.99.0"

    rec = reconcile(store, hostile)
    check("判为不兼容", rec["ok"] is False, rec.get("note", ""))
    check("note 含升级路径提示", "升级记忆桥" in rec["note"], rec["note"])
    check("未误改表结构", "brand_new_col" not in
          [r[1] for r in store.conn.execute("PRAGMA table_info(edges)")])

    # apply_delta 收到不兼容包必须拒绝，而不是带病合并
    d = Delta(from_device="DEV-X", to_device="DEV-C", schema=hostile)
    res = apply_delta(store, d)
    check("apply_delta 拒绝不兼容包", res.get("rejected") == "schema_incompatible", f"{res}")


def test_storage_planes_declared() -> None:
    tmp = _tmp()
    """v0.16（mem0 借鉴）：三存储平面 graph/vector/kv 齐备才算容器一致。"""
    print("\n④ 三存储平面声明（mem0 借鉴）")
    a = MemoryStore(os.path.join(tmp, "planes.db"), device="DEV-P")
    m = local_manifest(a)
    planes = sorted(m.get("storage_planes", []))
    check("manifest 声明三存储平面", planes == ["graph", "kv", "vector"], f"{planes}")
    # 指纹纳入 planes：缺平面的端指纹必然不同（容器不一致可被检出）
    m2 = dict(m)
    m2["storage_planes"] = [p for p in planes if p != "vector"]
    check("缺 vector 平面 → 指纹不同", manifest_fp(m) != manifest_fp(m2), "")


def test_seq_watermark_and_idempotent() -> None:
    tmp = _tmp()
    """v0.16（rig 借鉴）：seq 版本协商 + watermark 只增不减 + 重复包幂等。"""
    print("\n⑤ seq 版本协商与幂等收敛（rig 借鉴）")
    a = MemoryStore(os.path.join(tmp, "a2.db"), device="DEV-A2")
    b = MemoryStore(os.path.join(tmp, "b2.db"), device="DEV-B2")
    _add_pair(a, "seq 版本协商测试", "watermark 记录同步进度")

    d1 = compute_delta(a, b)
    check("首次发包 seq=1", d1.seq == 1, f"seq={d1.seq}")
    d2 = compute_delta(a, b)
    check("二次发包 seq 递增到 2", d2.seq == 2, f"seq={d2.seq}")

    r1 = apply_delta(b, d1)
    wm = b._get_meta("sync_watermark_DEV-A2")
    check("接收端已记 watermark=1", wm == "1", f"watermark={wm}")

    # 同一包重复应用：内容指纹去重 → nodes_added=0（幂等）
    r2 = apply_delta(b, d1)
    check("重复包幂等（不重复入库）", r2.get("nodes_added") == 0, f"{r2}")

    # 乱序到达（seq=2 先到）→ watermark 只增不减，仍可正常合并
    r3 = apply_delta(b, d2)
    wm2 = b._get_meta("sync_watermark_DEV-A2")
    check("乱序包（seq=2）后 watermark 升到 2", wm2 == "2", f"watermark={wm2}")
    check("乱序包无重复入库", r3.get("nodes_added") == 0, f"{r3}")


def main() -> int:
    # Windows 上 sqlite 句柄释放有延迟，忽略清理错误，避免误报失败
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        test_edge_kind_survives_roundtrip(tmp)
        test_legacy_triple_delta(tmp)
        test_reconcile_adds_missing_columns(tmp)
        test_incompatible_schema(tmp)
        test_storage_planes_declared(tmp)
        test_seq_watermark_and_idempotent(tmp)

    print(f"\n{'=' * 46}")
    print(f"通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
    if FAIL:
        for f in FAIL:
            print(f"  ✗ {f}")
        return 1
    print("全部通过 ✅")
    return 0


if __name__ == "__main__":
    sys.exit(main())
