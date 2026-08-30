"""核心模块测试（pytest 风格；也可用 `python tests/run_tests.py` 无 pytest 运行）。"""

import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from membridge import dss, heat, injection, privacy  # noqa: E402
from membridge.embeddings import HashingEmbedder, cosine, embedder_identity  # noqa: E402
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


def test_build_edges_incremental_only_pairs_new_node():
    """v0.8：写入时增量建边只算新节点与既有节点的关联，不再全量 O(n²) 重算。"""
    store = _tmp_store("phone")
    emb = HashingEmbedder()
    coffee = MemoryNode(content=COFFEE, embedding=emb.embed(COFFEE), device="phone")
    meeting = MemoryNode(content=MEETING, embedding=emb.embed(MEETING), device="phone")
    store.add(coffee)
    store.add(meeting)
    build_edges(store, emb, only_new=coffee)
    assert store.count_edges() == 0  # 咖啡与评审会无关联，且不会触碰 meeting 的边

    latte = MemoryNode(content=LATTE, embedding=emb.embed(LATTE), device="phone")
    store.add(latte)
    added = build_edges(store, emb, only_new=latte)
    # 新节点只与 coffee / meeting 各算一次；coffee-latte 语义相近应建边
    assert store.count_edges() == len(added) >= 1
    assert all(latte.node_id in pair for pair in ((s, d) for s, d, _ in added))
    store.close()


def test_search_relative_floor_filters_weak_hits():
    """v0.8：低于 top1×rel_floor 的弱命中不返回（省 token）；rel_floor=0 关闭。"""
    store = _tmp_store("phone")
    emb = HashingEmbedder()
    texts = (COFFEE, LATTE, MEETING)
    for text in texts:
        store.add(MemoryNode(content=text, embedding=emb.embed(text), device="phone"))
    strong = emb.embed("美式咖啡 不加糖")
    hits_default = store.search(strong, k=10)  # 默认相对阈值 0.5
    hits_all = store.search(strong, k=10, rel_floor=0.0)
    assert hits_all and hits_all[0][0].content == COFFEE
    assert len(hits_default) <= len(hits_all)
    if len(hits_all) > 1:
        assert len(hits_default) < len(hits_all) or hits_default[-1][1] >= hits_all[0][1] * 0.5
    store.close()


def test_store_transaction_rollback_on_error():
    """v0.8：transaction 内异常时整组写入回滚，不留半提交状态。"""
    store = _tmp_store("phone")
    emb = HashingEmbedder()
    before = store.count_nodes()
    try:
        with store.transaction():
            store.add(MemoryNode(content=COFFEE, embedding=emb.embed(COFFEE), device="phone"))
            raise RuntimeError("模拟中途失败")
    except RuntimeError:
        pass
    assert store.count_nodes() == before
    store.close()


def test_embedding_blob_migration_from_legacy_json():
    """v0.8：v0.7 的 JSON 文本 embedding 打开旧库时自动迁移为 float32 BLOB。"""
    import json as _json
    import sqlite3 as _sqlite3

    tmp = tempfile.mkdtemp()
    db = os.path.join(tmp, "legacy.db")
    emb = HashingEmbedder()
    # 手工造一个 v0.7 形态的库：embedding 存 JSON 文本、无 embedding_format meta
    conn = _sqlite3.connect(db)
    conn.executescript(
        "CREATE TABLE IF NOT EXISTS nodes (node_id TEXT PRIMARY KEY, content TEXT NOT NULL,"
        " embedding TEXT NOT NULL, tags TEXT NOT NULL DEFAULT '[]', scene TEXT NOT NULL DEFAULT 'personal',"
        " device TEXT NOT NULL DEFAULT 'unknown', migration TEXT NOT NULL DEFAULT 'edge',"
        " confidence REAL NOT NULL DEFAULT 1.0, created_at REAL NOT NULL, last_access REAL NOT NULL,"
        " access_count INTEGER NOT NULL DEFAULT 0);"
        "CREATE TABLE IF NOT EXISTS edges (src TEXT NOT NULL, dst TEXT NOT NULL,"
        " weight REAL NOT NULL, PRIMARY KEY (src, dst));"
        "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);"
    )
    vec = emb.embed(COFFEE)
    now = time.time()
    conn.execute(
        "INSERT INTO nodes (node_id, content, embedding, device, created_at, last_access)"
        " VALUES (?,?,?,?,?,?)",
        ("legacy01", COFFEE, _json.dumps(vec), "phone", now, now),
    )
    conn.commit()
    conn.close()

    store = MemoryStore(db)  # 打开即迁移
    assert store._get_meta("embedding_format") == "f32-blob-v1"
    raw_type = store.conn.execute(
        "SELECT typeof(embedding) FROM nodes WHERE node_id='legacy01'"
    ).fetchone()[0]
    assert raw_type == "blob"
    hits = store.search(emb.embed("咖啡"), k=3)
    assert hits and hits[0][0].content == COFFEE
    # 再开一次：幂等，不重复迁移
    store.close()
    store2 = MemoryStore(db)
    assert store2.count_nodes() == 1
    store2.close()


def test_embedder_identity_revision_semantics():
    """v0.8：revision 非空才参与指纹；为空时 fp 与 v0.7 公式完全一致（握手兼容）。"""
    import hashlib as _hashlib

    class _Plain:
        model = "m1"
        dim = 5

    class _Revised:
        model = "m1"
        dim = 5
        revision = "2024-01"

    plain_id = embedder_identity(_Plain())
    legacy_fp = _hashlib.blake2b(b"_Plain:m1:5", digest_size=8).hexdigest()
    assert plain_id["fp"] == legacy_fp and plain_id["revision"] == ""
    revised_id = embedder_identity(_Revised())
    assert revised_id["fp"] != plain_id["fp"] and revised_id["revision"] == "2024-01"


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


def test_store_creates_missing_parent_dirs():
    """回归测试（v0.4.1）：全新机器上 ~/.membridge 不存在时 init 崩溃的 bug。"""
    tmp = tempfile.mkdtemp()
    deep = os.path.join(tmp, "a", "b", "c", "mem.db")
    assert not os.path.exists(os.path.dirname(deep))
    store = MemoryStore(deep, device="regression")
    store.add(MemoryNode(content=COFFEE, device="regression"))
    assert store.count_nodes() == 1
    assert os.path.isfile(deep)
    store.close()


def test_default_db_path_prefers_env():
    saved = os.environ.get("MEMBRIDGE_DB")
    try:
        os.environ["MEMBRIDGE_DB"] = "D:/custom/mem.db"
        from membridge.store import default_db_path

        assert default_db_path() == "D:/custom/mem.db"
        del os.environ["MEMBRIDGE_DB"]
        assert default_db_path().endswith("memory.db")  # 全局默认 ~/.membridge
    finally:
        if saved:
            os.environ["MEMBRIDGE_DB"] = saved
        else:
            os.environ.pop("MEMBRIDGE_DB", None)


def test_safe_delta_file_cross_drive_bases():
    """回归（v0.8.0 实战）：allowed_bases 跨盘符时（C 盘库 + D 盘 cwd），
    commonpath 的 ValueError 不得否决其他合法基座——否则 D 盘正式库场景
    永远写不出差分包。"""
    from membridge.cli import _safe_delta_file

    tmp = tempfile.mkdtemp()
    target = os.path.join(tmp, "delta.json")
    other_drive = "D:/__membridge_nonexistent__" if os.path.exists("D:/") else None
    bases = [tmp] + ([other_drive] if other_drive else [])
    result = _safe_delta_file(target, for_write=True, allowed_bases=bases)
    assert os.path.normpath(result) == os.path.normpath(target)


def test_path_a_serialization_and_confidence_filter():
    now = time.time()
    good = MemoryNode(content=LATTE, device="phone", confidence=0.9, created_at=now)
    weak = MemoryNode(content="低置信度内容", device="phone", confidence=0.1, created_at=now)
    block = injection.serialize([good, weak])
    assert LATTE in block and "低置信度内容" not in block
    prompt = injection.build_prompt_aug("你是用户的连续认知助手", [good], "接着早上聊的咖啡推荐继续")
    assert "你是用户的连续认知助手" in prompt and "[当前问题]" in prompt and LATTE in prompt


def test_content_freeze_across_all_flows():
    """最高定律（内容冻结）：任何代码路径——建边、重建、检索、同步、迁移、
    打开旧库——都绝不允许改变记忆内容本身。此测试守护一切未来改版。"""
    contents = [
        "用户喜欢喝美式咖啡，不加糖",
        "  带有  空格 与 MixEd CaSe 的内容 Must Stay 原样！ ",
        "明天下午三点开项目评审会",
        "路由器管理密码 admin888",  # local 节点同样冻结
    ]
    store = _tmp_store("phone")
    emb = HashingEmbedder()
    for c in contents:
        store.add(MemoryNode(
            content=c, embedding=emb.embed(c), device="phone",
            migration=privacy.MIGRATION_LOCAL if "密码" in c else privacy.MIGRATION_EDGE,
        ))
    secret = [n for n in store.all_nodes() if "密码" in n.content][0]
    remote = _tmp_store("pc")

    before = {n.node_id: n.content for n in store.all_nodes()}

    # 全部结构操作走一遍：增量建边 → 全量重建 → 检索（记热度） → 差分同步 → 旧库重开（BLOB 迁移）
    build_edges(store, emb, only_new=[n for n in store.all_nodes() if "美式" in n.content][0])
    build_edges(store, emb)  # 全量重建
    store.search(emb.embed("咖啡"), k=3)
    delta = dss.compute_delta(store, remote)
    dss.apply_delta(remote, delta)
    # 重开一份连接（保持 tmp 存活），验证落盘数据与迁移后内容不变
    reopened = MemoryStore(store.path)
    reopened._tmp = store._tmp
    remote2 = MemoryStore(remote.path)
    remote2._tmp = remote._tmp
    store.close()
    remote.close()

    after = {n.node_id: n.content for n in reopened.all_nodes()}
    assert after == before, "记忆内容在结构操作中被改写——违反内容冻结最高定律"
    # local 节点也原样保留
    assert any("密码" in c for c in after.values())
    # 接收端内容与源端逐字一致（原样落库，不改写）
    for n in remote2.all_nodes():
        assert n.content in before.values()
    reopened.close()
    remote2.close()


def test_mcp_tool_surface_is_add_only():
    """最高定律的工具面保证：MCP 永远只暴露 Add / Search / Preload，
    任何改版不得出现 update / delete / summarize 等改写记忆的工具。"""
    try:
        import asyncio

        from membridge.mcp_server import create_server
    except ImportError:
        print("SKIP: mcp 未安装")
        return
    import tempfile

    server = create_server(store_path=os.path.join(tempfile.mkdtemp(), "m.db"))
    try:
        tools = asyncio.run(server.list_tools())
    except Exception:
        print("SKIP: FastMCP.list_tools 不可用")
        return
    names = {t.name for t in tools}
    assert names == {"memory_add", "memory_search", "memory_preload"}, names
    forbidden = {"memory_update", "memory_delete", "memory_summarize",
                 "memory_edit", "memory_rewrite"}
    assert not names & forbidden
