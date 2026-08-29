"""能力调度与 embedder 一致性握手测试（v0.4.0，借鉴 ncnn 运行时调度思想）。"""

import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from membridge import capabilities, dss  # noqa: E402
from membridge.embeddings import (  # noqa: E402
    HashingEmbedder,
    embedder_identity,
)
from membridge.store import MemoryStore  # noqa: E402

COFFEE = "用户喜欢喝美式咖啡，不加糖"


def test_probe_returns_capability_profile():
    info = capabilities.probe()
    assert set(info["extras"]) >= {"mcp", "crypto", "openai", "vec_index"}
    assert isinstance(info["sync_drives"], list)
    assert info["python"] and info["platform"]


def test_best_embedder_graceful_fallback():
    saved = os.environ.pop("OPENAI_API_KEY", None)
    try:
        emb = capabilities.best_embedder()
        assert isinstance(emb, HashingEmbedder)  # 无密钥时优雅降级
    finally:
        if saved:
            os.environ["OPENAI_API_KEY"] = saved


def test_embedder_identity_stable_and_dim_sensitive():
    i1 = embedder_identity(HashingEmbedder())
    i2 = embedder_identity(HashingEmbedder())
    assert i1 == i2 and i1["fp"] and i1["dim"] == 256
    assert embedder_identity(HashingEmbedder(dim=128))["fp"] != i1["fp"]


def _store(device, fp_meta=None):
    store = MemoryStore(os.path.join(tempfile.mkdtemp(), "m.db"), device=device)
    if fp_meta:
        store._set_meta("embedder_id", json.dumps(fp_meta))
    return store


def test_handshake_rejects_embedder_mismatch():
    a, b = _store("手机"), _store("PC")
    b._set_meta("embedder_id", json.dumps({"fp": "different"}))
    delta = dss.delta_unsent(a, set(), embedder_info=embedder_identity(HashingEmbedder()))
    delta.nodes.append({"node_id": "x", "content": COFFEE})
    result = dss.apply_delta(b, delta)
    assert result["rejected"] == "embedder_mismatch"
    assert b.count_nodes() == 0  # 拒绝后向量不得进入本库
    a.close()
    b.close()


def test_handshake_records_first_seen_and_backcompat():
    a, b = _store("手机"), _store("PC")
    ident = embedder_identity(HashingEmbedder())
    delta = dss.delta_unsent(a, set(), embedder_info=ident)
    delta.nodes.append({"node_id": "x", "content": COFFEE})
    assert dss.apply_delta(b, delta)["nodes_added"] == 1
    # 首次见到后已记录，同指纹再应用不再拒绝
    delta2 = dss.delta_unsent(a, set(), embedder_info=ident)
    delta2.nodes.append({"node_id": "y", "content": "另一条新记忆内容"})
    assert dss.apply_delta(b, delta2)["nodes_added"] == 1
    assert json.loads(b._get_meta("embedder_id"))["fp"] == ident["fp"]
    # 向后兼容：旧格式差分包（无 embedder 字段）照常应用
    old = dss.Delta.from_json(json.dumps({"from_device": "旧设备", "to_device": "PC",
                                          "nodes": [{"node_id": "z", "content": "旧格式包内容"}],
                                          "edges": []}))
    assert dss.apply_delta(b, old)["nodes_added"] == 1
    a.close()
    b.close()
