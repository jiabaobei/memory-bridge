"""v0.26.1 容器对账测试：reconcile 补列的字符串默认值转义 + 登记表白名单。

回归守卫：edges.kind 的默认值 'semantic' 不再被丢成空串；
未登记的远程字段名被拒绝（登记表即白名单，无 SQL 注入面）。
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from membridge.schema import local_manifest, reconcile  # noqa: E402
from membridge.store import MemoryStore  # noqa: E402


def _old_style_store() -> MemoryStore:
    """构造一个缺 edges.kind / edges.evidence 的旧式库（v0.13 及之前的容器）。"""
    tmp = tempfile.TemporaryDirectory()
    store = MemoryStore(os.path.join(tmp.name, "mem.db"))
    store._tmp = tmp  # 防 GC
    store.conn.execute("DROP TABLE edges")
    store.conn.execute(
        "CREATE TABLE edges (src TEXT NOT NULL, dst TEXT NOT NULL, "
        "weight REAL NOT NULL, PRIMARY KEY (src, dst))"
    )
    store.conn.execute("INSERT INTO edges VALUES ('a', 'b', 1.0)")
    return store


def test_reconcile_kind_default_is_semantic():
    """存量边补列后 kind 应为 'semantic'（而非空串）——与 _migrate_columns 行为一致。"""
    store = _old_style_store()
    remote = local_manifest(store)
    remote["edge_fields"] = sorted(set(remote["edge_fields"]) | {"kind", "evidence"})
    rec = reconcile(store, remote)
    assert rec["ok"], rec
    kind = store.conn.execute("SELECT kind FROM edges WHERE src='a'").fetchone()[0]
    assert kind == "semantic", f"存量边 kind 应为 semantic，实得 {kind!r}"


def test_reconcile_rejects_unregistered_field():
    """未登记的远程字段名必须拒绝——登记表即白名单，不可注入任意 SQL。"""
    store = _old_style_store()
    remote = local_manifest(store)
    remote["edge_fields"] = sorted(set(remote["edge_fields"]) | {"evil; DROP TABLE nodes"})
    rec = reconcile(store, remote)
    assert not rec["ok"], rec
    assert "evil" in rec["note"], rec
