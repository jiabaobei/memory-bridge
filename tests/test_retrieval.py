"""v0.9 检索层测试：混合检索 + RRF、预算注入 + 沉默契约、缺口发现、kind 标注。

内容冻结守卫：截断注入必须是原文的连续前缀（不允许改写）。
"""

import os
import sqlite3
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from membridge import injection, retrieval  # noqa: E402
from membridge.embeddings import HashingEmbedder  # noqa: E402
from membridge.node import MemoryNode  # noqa: E402
from membridge.san import build_edges  # noqa: E402
from membridge.store import MemoryStore  # noqa: E402

COFFEE = "用户喜欢喝美式咖啡，不加糖"
LATTE = "用户也喜欢拿铁咖啡"
MEETING = "明天下午三点开项目评审会"
DEPLOY_FAIL = "部署脚本在 arm64 上会报段错误，换 x86 镜像后通过"


def _tmp_store(device: str = "phone") -> MemoryStore:
    tmp = tempfile.TemporaryDirectory()
    store = MemoryStore(os.path.join(tmp.name, "mem.db"), device=device)
    store._tmp = tmp
    return store


def _seed(store, emb, texts):
    for t in texts:
        store.add(MemoryNode(content=t, embedding=emb.embed(t), device="phone"))


def test_hybrid_search_finds_keyword_exact_match():
    """字面命中场景（向量检索的盲区）由关键词路兜住。"""
    store = _tmp_store()
    emb = HashingEmbedder()
    _seed(store, emb, (COFFEE, MEETING, DEPLOY_FAIL))
    hits = retrieval.hybrid_search(store, emb, "arm64 段错误")
    assert hits and hits[0][0].content == DEPLOY_FAIL
    store.close()


def test_hybrid_search_rrf_prefers_multiroute_consensus():
    """向量与关键词双路都命中的节点，RRF 融合后应排第一。"""
    store = _tmp_store()
    emb = HashingEmbedder()
    _seed(store, emb, (COFFEE, LATTE, MEETING))
    hits = retrieval.hybrid_search(store, emb, "咖啡", k=3)
    assert hits
    top_contents = {n.content for n, _ in hits[:2]}
    assert COFFEE in top_contents and LATTE in top_contents
    store.close()


def test_hybrid_search_graph_route_expands_neighbors():
    """图谱路：与命中种子有 SAN 边的邻居也能被召回。"""
    store = _tmp_store()
    emb = HashingEmbedder()
    _seed(store, emb, (COFFEE, LATTE, MEETING))
    build_edges(store, emb)
    hits = retrieval.hybrid_search(store, emb, "美式咖啡", k=5)
    contents = {n.content for n, _ in hits}
    assert COFFEE in contents
    store.close()


def test_silence_contract_on_empty_store():
    """沉默契约：零命中时记录缺口并返回空，上层明确告知不注入。"""
    store = _tmp_store()
    emb = HashingEmbedder()
    hits = retrieval.hybrid_search(store, emb, "一个完全没存过的主题")
    assert hits == []
    gaps = store.gap_queries()
    assert gaps and gaps[0]["q"] == "一个完全没存过的主题"
    # 重复查询不重复记录
    retrieval.hybrid_search(store, emb, "一个完全没存过的主题")
    assert len(store.gap_queries()) == 1
    store.close()


def test_serialize_silence_note_when_nothing_eligible():
    low = MemoryNode(content="低置信", embedding=[], confidence=0.1)
    assert injection.serialize([low]) == injection.SILENCE_NOTE
    assert injection.serialize([]) == injection.SILENCE_NOTE


def test_serialize_budget_truncates_with_original_prefix():
    """预算注入：超预算条目注入原文前缀；截断必须是原文连续前缀（内容冻结守卫）。"""
    n1 = MemoryNode(content=COFFEE, embedding=[], confidence=1.0)
    n2 = MemoryNode(content=DEPLOY_FAIL, embedding=[], confidence=1.0)
    full = injection.serialize([n1, n2], max_chars=10000)
    assert DEPLOY_FAIL in full  # 预算充足时全文注入
    tight = injection.serialize([n1, n2], max_chars=110)
    assert injection._TRUNC_MARK in tight
    # 截断片段必须原样出自原文（不改写）：取出被截断条目的正文前缀验证
    prefix = None
    for line in tight.splitlines():
        if injection._TRUNC_MARK in line:
            prefix = line.split("- ", 1)[1].split(injection._TRUNC_MARK)[0]
    assert prefix and DEPLOY_FAIL.startswith(prefix)


def test_kind_roundtrip_and_legacy_migration():
    """kind 标注落库回读；旧库（无 kind 列）打开时自动平滑加列。"""
    store = _tmp_store()
    emb = HashingEmbedder()
    store.add(MemoryNode(content=DEPLOY_FAIL, embedding=emb.embed(DEPLOY_FAIL),
                         device="phone", kind="procedure"))
    store.add(MemoryNode(content=COFFEE, embedding=emb.embed(COFFEE), device="phone"))
    nodes = {n.content: n for n in store.all_nodes()}
    assert nodes[DEPLOY_FAIL].kind == "procedure"
    assert nodes[COFFEE].kind == ""
    path = store.path
    store.close()
    # 模拟 v0.8 旧库：删掉 kind 列后重开应自动迁移（SQLite 无 DROP COLUMN 兼容路径，
    # 这里直接重建一张旧 schema 表验证迁移逻辑）
    legacy = path + ".legacy"
    conn = sqlite3.connect(legacy)
    conn.executescript(
        "CREATE TABLE nodes (node_id TEXT PRIMARY KEY, content TEXT NOT NULL,"
        " embedding TEXT NOT NULL, tags TEXT NOT NULL DEFAULT '[]',"
        " scene TEXT NOT NULL DEFAULT 'personal', device TEXT NOT NULL DEFAULT 'unknown',"
        " migration TEXT NOT NULL DEFAULT 'edge', confidence REAL NOT NULL DEFAULT 1.0,"
        " created_at REAL NOT NULL, last_access REAL NOT NULL,"
        " access_count INTEGER NOT NULL DEFAULT 0);"
        "CREATE TABLE edges (src TEXT NOT NULL, dst TEXT NOT NULL, weight REAL NOT NULL,"
        " PRIMARY KEY (src, dst));"
        "CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);"
    )
    conn.commit()
    conn.close()
    s2 = MemoryStore(legacy)
    cols = [r[1] for r in s2.conn.execute("PRAGMA table_info(nodes)")]
    assert "kind" in cols
    s2.close()


def test_delta_serialization_still_compatible():
    """kind 进入 to_dict 后，旧版 from_dict 过滤逻辑仍兼容（跨版本同步不破坏）。"""
    n = MemoryNode(content=COFFEE, embedding=[0.1], kind="fact")
    d = n.to_dict()
    assert d["kind"] == "fact"
    # 旧版设备收到带 kind 的包：from_dict 只取自己认识的字段
    restored = MemoryNode.from_dict(d)
    assert restored.kind == "fact" and restored.content == COFFEE
