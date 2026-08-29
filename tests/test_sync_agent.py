"""自动同步引擎测试：口令保险库、重要度规则、批量/立即上云决策。"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from membridge import sync_agent, vault  # noqa: E402
from membridge.embeddings import HashingEmbedder, embedder_identity  # noqa: E402
from membridge.node import MemoryNode  # noqa: E402
from membridge.store import MemoryStore  # noqa: E402

COFFEE = "用户喜欢喝美式咖啡，不加糖"


def _store(device):
    store = MemoryStore(os.path.join(tempfile.mkdtemp(), "m.db"), device=device)
    return store


def _add(store, text, confidence=1.0, tags=(), migration="edge", access=0):
    emb = HashingEmbedder()
    node = MemoryNode(
        content=text,
        embedding=emb.embed(text),
        confidence=confidence,
        tags=list(tags),
        migration=migration,
        device=store.device_name,
        access_count=access,
    )
    store.add(node)
    return node


def test_vault_roundtrip_dpapi():
    if not vault.supported():
        print("SKIP: 非 Windows")
        return
    store = _store("手机")
    assert vault.load_passphrase(store) is None
    vault.save_passphrase(store, "我的云盘口令123")
    assert vault.load_passphrase(store) == "我的云盘口令123"
    store.close()


def test_importance_rule():
    hot = MemoryNode(content="高置信", confidence=0.9)
    used = MemoryNode(content="被多次访问", confidence=0.4)
    used.access_count = 2
    tagged = MemoryNode(content="带重要标签", confidence=0.4, tags=["重要"])
    routine = MemoryNode(content="普通", confidence=0.5)
    local = MemoryNode(content="本机隐私", confidence=1.0, migration="local")
    assert sync_agent.is_important(hot)
    assert sync_agent.is_important(used)
    assert sync_agent.is_important(tagged)
    assert not sync_agent.is_important(routine)
    assert not sync_agent.is_important(local)  # local 永不视为可上云的重要项


def test_autosync_requires_passphrase_and_channel():
    store = _store("手机")
    lines = []
    assert sync_agent.run_autosync(store_path=store.path, out=lines.append) == 2
    store.set_netdisk(rf"{tempfile.mkdtemp()}\chan")
    lines.clear()
    assert sync_agent.run_autosync(store_path=store.path, out=lines.append) == 2
    assert any("口令" in ln for ln in lines)
    store.close()


def test_autosync_important_publishes_immediately():
    store = _store("手机")
    ch = tempfile.mkdtemp()
    store.set_netdisk(ch)
    vault.save_passphrase(store, "口令abc")
    _add(store, COFFEE, confidence=0.95)
    lines = []
    assert sync_agent.run_autosync(store_path=store.path, out=lines.append) == 0
    assert any("立即上云" in ln for ln in lines)
    assert os.listdir(os.path.join(ch, "outbox"))
    # 已发布指纹记录后，重复运行不再发布
    lines.clear()
    sync_agent.run_autosync(store_path=store.path, out=lines.append)
    assert any("没有需要发布" in ln for ln in lines)
    store.close()


def test_autosync_routine_batches_and_local_never_uploaded():
    store = _store("手机")
    ch = tempfile.mkdtemp()
    store.set_netdisk(ch)
    vault.save_passphrase(store, "口令abc")
    for i in range(4):
        _add(store, f"普通记忆内容第{i}条", confidence=0.5)
    secret = _add(store, "本机隐私条目", confidence=1.0, migration="local")
    store._set_meta("last_publish_at", str(__import__("time").time()))  # 模拟刚发布过
    lines = []
    sync_agent.run_autosync(store_path=store.path, out=lines.append)
    # 4 条普通 < 5 条批量线，且无重要记忆 → 不发布；local 永不出现
    assert not os.listdir(os.path.join(ch, "outbox"))
    _add(store, "第5条普通记忆", confidence=0.5)
    lines.clear()
    sync_agent.run_autosync(store_path=store.path, out=lines.append)
    assert any("批量上云" in ln for ln in lines)
    import json

    pkg = [os.path.join(ch, "outbox", f) for f in os.listdir(os.path.join(ch, "outbox"))][0]
    from membridge.transport import PassphraseCryptor

    env = json.loads(open(pkg, "rb").read().decode("utf-8"))
    cryptor = PassphraseCryptor("口令abc", salt=bytes.fromhex(env["salt"]))
    payload = json.loads(cryptor.decrypt(env["token"]))["nodes"]
    assert all(n["content"] != secret.content for n in payload)  # local 永不上云
    assert len(payload) == 5
    store.close()
