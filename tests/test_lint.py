"""v0.28 lint 体检测试：四项结构检查 + 凭证打码 + 只删悬空边。

回归守卫：体检报告本身不得成为泄露渠道（命中原文绝不回显）；
--fix-structure 只动边、不动记忆内容（内容冻结）。
"""

import json
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from membridge.lint import run_lint  # noqa: E402
from membridge.node import MemoryNode  # noqa: E402
from membridge.store import MemoryStore  # noqa: E402


def _store() -> MemoryStore:
    tmp = tempfile.TemporaryDirectory()
    store = MemoryStore(os.path.join(tmp.name, "mem.db"))
    store._tmp = tmp  # 防 GC
    return store


def _add(store: MemoryStore, content: str) -> MemoryNode:
    node = MemoryNode(content=content, embedding=[0.0])
    return store.add(node)


def test_empty_store_is_clean():
    rep = run_lint(_store())
    assert rep["clean"] is True, rep
    assert rep["counts"] == {
        "dangling_edges": 0, "isolated": 0, "stale": 0, "secrets": 0, "errors": 0,
    }, rep["counts"]


def test_dangling_edge_detected_then_fixed_without_touching_content():
    store = _store()
    a = _add(store, "唯一一条记忆")
    store.add_edge("ghost", a.node_id, 0.5, kind="semantic")

    rep = run_lint(store)
    assert rep["counts"]["dangling_edges"] == 1, rep["counts"]
    assert rep["clean"] is False

    rep2 = run_lint(store, fix_structure=True)
    assert rep2["fixed_edges"] == 1, rep2
    assert store.count_edges() == 0
    assert store.count_nodes() == 1, "结构修复不得删除记忆内容"


def test_isolated_and_stale_are_hints_not_errors():
    store = _store()
    a = _add(store, "孤立的记忆")
    b = _add(store, "有边的记忆一")
    d = _add(store, "有边的记忆二")
    c = store.add(MemoryNode(content="陈旧的孤立记忆", embedding=[0.0],
                             last_access=time.time() - 100 * 86400))
    store.add_edge(b.node_id, d.node_id, 0.9, kind="semantic")

    rep = run_lint(store)
    assert rep["counts"]["isolated"] == 2, rep["counts"]
    assert a.node_id in rep["isolated"] and c.node_id in rep["isolated"]
    assert rep["counts"]["stale"] == 1, rep["counts"]
    assert c.node_id in rep["stale"]
    assert rep["clean"] is True, "孤立/陈旧只是提示，不作失败"


def test_secret_reported_without_echoing_plaintext():
    store = _store()
    secret = "sk-abcdefghijklmnopqrstuvwxyz012345"
    _add(store, f"我的 API key 是 {secret}，别外传")

    rep = run_lint(store)
    assert rep["counts"]["secrets"] == 1, rep["counts"]
    assert rep["clean"] is False, "凭证泄露应计为错误项"
    assert secret not in json.dumps(rep, ensure_ascii=False), "报告不得回显凭证原文"
    assert rep["secrets"][0]["pattern"] == "openai-key"
    assert "***" in rep["secrets"][0]["excerpt"]


def test_stale_days_threshold_is_configurable():
    store = _store()
    store.add(MemoryNode(content="十天未访问的孤立记忆", embedding=[0.0],
                         last_access=time.time() - 10 * 86400))

    assert run_lint(store, stale_days=90)["counts"]["stale"] == 0
    assert run_lint(store, stale_days=7)["counts"]["stale"] == 1
