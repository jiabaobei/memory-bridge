"""v0.15 交接班测试：交接卡（handover）、工作台、恒定注入与边衰减。"""

import io
import json
import os
import sys
import tempfile
import time
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from membridge import dss, injection  # noqa: E402
from membridge.embeddings import HashingEmbedder  # noqa: E402
from membridge.export import render_markdown  # noqa: E402
from membridge.handoff import (  # noqa: E402
    HANDOFF_STALE_HOURS, latest_handoff, parse_sections, summary,
    workbench, workbench_block,
)
from membridge.node import MemoryNode  # noqa: E402
from membridge.san import HANDOFF_EDGE_DECAY, build_edges  # noqa: E402
from membridge.store import MemoryStore  # noqa: E402

CARD_A = "goal: 修好同步模块\ndone: 差分计算落地"
CARD_B = (
    "goal: 交接班机制收尾\ndone: 工作台注入已合并\n"
    "failed: 全量AST解析；依赖太重；除非放弃零依赖否则别重试\n"
    "next: 收敛交接卡行前缀\nguide: 无关引导语"
)
COFFEE = "用户喜欢喝美式咖啡，不加糖"


def _tmp_store(device: str) -> MemoryStore:
    tmp = tempfile.TemporaryDirectory()
    store = MemoryStore(os.path.join(tmp.name, "mem.db"), device=device)
    store._tmp = tmp  # 防止目录被提前回收
    return store


def _add(store, emb, text, kind="", created_at=None):
    node = MemoryNode(content=text, embedding=emb.embed(text),
                      device=store.device_name, kind=kind)
    if created_at is not None:
        node.created_at = created_at
    store.add(node)
    return node


# ---------- 解析与取代 ----------

def test_parse_sections_and_extras():
    sections, extras = parse_sections(CARD_B)
    assert sections["goal"] == "交接班机制收尾"
    assert "除非放弃零依赖否则别重试" in sections["failed"]
    assert "guide" not in sections  # 未知前缀不是约定段
    assert "无关引导语" in extras
    # 全角冒号同样识别；内容不改写
    s2, _ = parse_sections("goal：测试目标")
    assert s2["goal"] == "测试目标"
    # 不合规内容不报错、照常呈现
    s3, e3 = parse_sections("随手写的交接卡")
    assert not s3 and e3 == "随手写的交接卡"


def test_latest_handoff_supersedes_by_time():
    store = _tmp_store("pc")
    emb = HashingEmbedder()
    _add(store, emb, CARD_A, kind="handover", created_at=time.time() - 3600)
    b = _add(store, emb, CARD_B, kind="handover", created_at=time.time())
    latest = latest_handoff(store)
    assert latest.node_id == b.node_id  # 新卡取代旧卡（推导，无状态位）
    assert summary(latest).startswith("交接班机制收尾")
    store.close()


def test_workbench_stale_threshold():
    store = _tmp_store("pc")
    emb = HashingEmbedder()
    old = time.time() - (HANDOFF_STALE_HOURS + 1) * 3600
    _add(store, emb, CARD_A, kind="handover", created_at=old)
    assert latest_handoff(store) is not None   # 卡还在，可审计可检索
    assert workbench(store) is None            # 过期：不再恒定注入
    assert workbench_block(store) == ""
    store.close()


def test_handover_syncs_through_delta():
    """交接卡是普通节点：差分包原样携带，跨设备自动收敛到同一张工作台。"""
    src, dst = _tmp_store("phone"), _tmp_store("pc")
    emb = HashingEmbedder()
    card = _add(src, emb, CARD_B, kind="handover")
    delta = dss.compute_delta(src, dst)
    assert any(n.get("kind") == "handover" for n in delta.nodes)
    dss.apply_delta(dst, delta)
    got = latest_handoff(dst)
    assert got is not None and got.node_id == card.node_id
    assert workbench(dst) is not None
    src.close(); dst.close()


# ---------- 注入 ----------

def test_serialize_workbench_section_and_silence_contract():
    store = _tmp_store("pc")
    emb = HashingEmbedder()
    _add(store, emb, CARD_A, kind="handover")
    wb = workbench_block(store)
    assert wb.startswith("【工作台】")
    # 无检索命中也有工作台：不是沉默（交接卡是状态声明，不走沉默契约）
    block = injection.serialize([], workbench=wb)
    assert "【工作台】" in block and "不干预" not in block
    # 无卡无命中：沉默契约原样保留
    store2 = _tmp_store("pc")
    assert injection.serialize([], workbench=workbench_block(store2)) \
        == injection.SILENCE_NOTE
    # 检索命中与工作台同在：两者都出现，工作台在前
    coffee = _add(store, emb, COFFEE)
    block2 = injection.serialize([coffee], workbench=wb)
    assert block2.index("【工作台】") < block2.index(COFFEE)
    store.close(); store2.close()


def test_serialize_workbench_prefix_truncation_keeps_content_frozen():
    store = _tmp_store("pc")
    emb = HashingEmbedder()
    long_card = "goal: " + "目标" * 500
    _add(store, emb, long_card, kind="handover")
    block = injection.serialize([], max_chars=300,
                                workbench=workbench_block(store))
    assert "[原文截断]" in block
    # 截断是取原文前缀：工作台正文从 goal 行开始，原文逐字保留
    assert "goal: 目标目标" in block.split("[原文截断]")[0]
    store.close()


# ---------- 图谱 ----------

def test_handover_edges_are_decayed():
    """交接卡触点权重衰减：工作台已恒定注入，交接卡不靠边权重抬排名。"""
    store = _tmp_store("pc")
    emb = HashingEmbedder()
    shared = "修复 membridge/store.py 的并发问题"
    other = _add(store, emb, shared)
    handover = _add(store, emb, shared + "\ngoal: 收尾", kind="handover")
    build_edges(store, emb, only_new=handover)
    w = store.edge_weight(*sorted((handover.node_id, other.node_id)))
    assert w is not None

    # 同内容、非交接卡时的对照权重
    store2 = _tmp_store("pc")
    other2 = _add(store2, emb, shared)
    plain = _add(store2, emb, shared + "\ngoal: 收尾")
    build_edges(store2, emb, only_new=plain)
    w2 = store2.edge_weight(*sorted((plain.node_id, other2.node_id)))
    assert abs(w - round(w2 * HANDOFF_EDGE_DECAY, 4)) < 1e-9
    store.close(); store2.close()


def test_preload_cluster_starts_with_active_card():
    store = _tmp_store("pc")
    emb = HashingEmbedder()
    for text in (COFFEE, "明天下午三点开项目评审会"):
        n = _add(store, emb, text)
        store.touch(n.node_id)  # 抬热度
    card = _add(store, emb, CARD_A, kind="handover")
    from membridge.heat import preload_cluster
    from membridge.privacy import preload_allowed

    cands = preload_cluster(store, allowed=preload_allowed, k=8)
    assert cands and cands[0].node_id == card.node_id
    store.close()


# ---------- 出口 ----------

def test_export_has_workbench_section_and_history():
    store = _tmp_store("pc")
    emb = HashingEmbedder()
    old = time.time() - (HANDOFF_STALE_HOURS + 1) * 3600
    _add(store, emb, CARD_A, kind="handover", created_at=old)
    _add(store, emb, CARD_B, kind="handover")
    text = render_markdown(store)
    assert "当前工作台" in text
    assert "交接班机制收尾" in text
    assert "交接卡（handover）" in text  # 过期卡进场景分组，可审计
    assert text.count("修好同步模块") >= 1
    store.close()


def test_cli_handoff_and_context_compose_workbench():
    from contextlib import redirect_stdout

    from membridge.cli import main

    tmp = tempfile.TemporaryDirectory()
    db = os.path.join(tmp.name, "mem.db")
    buf = io.StringIO()
    with redirect_stdout(buf):
        assert main(["--db", db, "add", CARD_B, "--kind", "handover"]) == 0
        assert main(["--db", db, "handoff"]) == 0
        out = buf.getvalue()
    assert "当前工作台" in out and "交接班机制收尾" in out
    buf2 = io.StringIO()
    with redirect_stdout(buf2):
        assert main(["--db", db, "context", "交接班机制"]) == 0
        ctx = buf2.getvalue()
    assert "【工作台】" in ctx
    assert ctx.count("交接班机制收尾") == 1  # 工作台与检索命中去重后只出现一次


# ---------- 网关 ----------

def test_gateway_handoff_add_and_workbench_slot():
    import threading

    from membridge.gateway import create_gateway_server

    TOKEN = "handoff-test-token"
    tmp = tempfile.TemporaryDirectory()
    store = MemoryStore(os.path.join(tmp.name, "mem.db"), device="pc")
    store._tmp = tmp
    server = create_gateway_server(store, HashingEmbedder(), TOKEN,
                                   host="127.0.0.1", port=0)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()

    def call(path, body):
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}{path}",
            data=json.dumps(body).encode("utf-8"), method="POST")
        req.add_header("Authorization", f"Bearer {TOKEN}")
        req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=5) as r:
            return json.loads(r.read().decode("utf-8"))

    r = call("/add", {"text": CARD_B, "kind": "handover"})
    assert r.get("ok") and store.get(r["node_id"]).kind == "handover"
    wb = call("/workbench", {})
    assert "【工作台】" in wb["message"]
    ctx = call("/search", {"query": "交接班机制", "as_context": True})
    assert "【工作台】" in ctx["context"]
    server.shutdown()
    server.server_close()
    store.close()
