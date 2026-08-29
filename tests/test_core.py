"""核心模块测试（pytest 风格；也可用 `python tests/run_tests.py` 无 pytest 运行）。"""

import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from membridge import dss, heat, injection, privacy  # noqa: E402
from membridge.embeddings import HashingEmbedder, cosine  # noqa: E402
from membridge.node import MemoryNode  # noqa: E402
from membridge.san import build_edges  # noqa: E402
from membridge.store import MemoryStore  # noqa: E402

COFFEE = "用户喜欢喝美式咖啡，不加糖"
LATTE = "用户也喜欢拿铁咖啡"
MEETING = "明天下午三点开项目评审会"


def _tmp_store(device: str) -> MemoryStore:
    tmp = tempfile.TemporaryDirectory()
    store = MemoryStore(os.path.join(tmp.name, "mem.db"), device=device)
    store._tmp = tmp  # 防止目录被提前回收
    return store


def test_hashing_embedder_deterministic_and_normalized():
    emb = HashingEmbedder()
    a, b = emb.embed(COFFEE), emb.embed(COFFEE)
    assert a == b
    assert abs(sum(x * x for x in a) - 1.0) < 1e-6


def test_store_roundtrip_and_search_relevance():
    store = _tmp_store("phone")
    emb = HashingEmbedder()
    for text in (COFFEE, MEETING):
        store.add(MemoryNode(content=text, embedding=emb.embed(text), device="phone"))
    hits = store.search(emb.embed("咖啡"), k=2)
    assert hits and hits[0][0].content == COFFEE
    # 检索命中应记访问（TMT 热度依据）
    top = store.get(hits[0][0].node_id)
    assert top is not None and top.access_count >= 1
    store.close()


def test_san_builds_edges_and_neighbors():
    store = _tmp_store("phone")
    emb = HashingEmbedder()
    for text in (COFFEE, LATTE, MEETING):
        store.add(MemoryNode(content=text, embedding=emb.embed(text), device="phone"))
    added = build_edges(store, emb)
    assert len(added) >= 1
    assert store.count_edges() >= 1
    coffee = [n for n in store.all_nodes() if n.content == COFFEE][0]
    nbrs = store.neighbors(coffee.node_id)
    assert nbrs and nbrs[0][0].content == LATTE
    store.close()


def test_heat_prefers_recent_and_frequent():
    now = time.time()
    old = MemoryNode(content=COFFEE, device="phone", confidence=1.0)
    old.last_access = now - 10 * 3600
    recent = MemoryNode(content=LATTE, device="phone", confidence=1.0)
    recent.last_access = now
    recent.access_count = 1
    assert heat.heat(recent, now=now) > heat.heat(old, now=now)


def test_pams_blocks_local_and_cross_scene():
    local_node = MemoryNode(content="家里 WiFi 密码是 abc123", device="phone",
                            scene="personal", migration=privacy.MIGRATION_LOCAL)
    assert not privacy.preload_allowed(local_node)
    medical = MemoryNode(content="上周复诊记录", device="phone", scene="medical",
                         migration=privacy.MIGRATION_EDGE)
    assert not privacy.preload_allowed(medical, target_scene="personal")
    assert privacy.preload_allowed(medical, target_scene="medical")
    # 敏感内容自动打上 local 标签（L1 兜底）
    assert privacy.default_migration("我的 GitHub API key 是 gho_xxx") == privacy.MIGRATION_LOCAL
    assert privacy.classify_scene("下周复诊带好病历") == "medical"


def test_dss_delta_roundtrip_between_devices():
    phone = _tmp_store("phone")
    pc = _tmp_store("pc")
    emb = HashingEmbedder()
    secret = MemoryNode(content="路由器管理密码 admin888", device="phone",
                        embedding=emb.embed("路由器管理密码 admin888"),
                        migration=privacy.MIGRATION_LOCAL)
    phone.add(MemoryNode(content=COFFEE, embedding=emb.embed(COFFEE), device="phone"))
    phone.add(MemoryNode(content=LATTE, embedding=emb.embed(LATTE), device="phone"))
    phone.add(secret)
    build_edges(phone, emb)

    delta = dss.compute_delta(phone, pc)
    # PAMS L1：local 节点绝不进入传输载荷
    assert all(n["content"] != secret.content for n in delta.nodes)
    assert len(delta.nodes) == 2

    result = dss.apply_delta(pc, delta)
    assert result["nodes_added"] == 2
    assert pc.count_nodes() == 2
    # 再次同步应收敛为空差分（指纹去重）
    assert len(dss.compute_delta(phone, pc).nodes) == 0
    # JSON 往返无损
    assert dss.Delta.from_json(delta.to_json()).nodes == delta.nodes
    phone.close()
    pc.close()


def test_path_a_serialization_and_confidence_filter():
    now = time.time()
    good = MemoryNode(content=LATTE, device="phone", confidence=0.9, created_at=now)
    weak = MemoryNode(content="低置信度内容", device="phone", confidence=0.1, created_at=now)
    block = injection.serialize([good, weak])
    assert LATTE in block and "低置信度内容" not in block
    prompt = injection.build_prompt_aug("你是用户的连续认知助手", [good], "接着早上聊的咖啡推荐继续")
    assert "你是用户的连续认知助手" in prompt and "[当前问题]" in prompt and LATTE in prompt
