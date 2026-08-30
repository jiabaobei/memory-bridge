"""自动同步引擎测试：口令保险库、系统自动生成口令、重要度规则、批量/立即上云决策。"""

import json
import os
import sys
import tempfile
from pathlib import Path

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
    saved = os.environ.pop("MEMBRIDGE_PASSPHRASE", None)  # 隔离系统环境变量
    try:
        store = _store("手机")
        lines = []
        assert sync_agent.run_autosync(store_path=store.path, out=lines.append) == 2
        store.set_netdisk(rf"{tempfile.mkdtemp()}\chan")
        lines.clear()
        assert sync_agent.run_autosync(store_path=store.path, out=lines.append) == 2
        assert any("口令" in ln for ln in lines)
    finally:
        if saved:
            os.environ["MEMBRIDGE_PASSPHRASE"] = saved
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
    saved = os.environ.pop("MEMBRIDGE_PASSPHRASE", None)  # 隔离系统环境变量
    try:
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
        pkg = [os.path.join(ch, "outbox", f) for f in os.listdir(os.path.join(ch, "outbox"))][0]
        from membridge.transport import PassphraseCryptor

        env = json.loads(open(pkg, "rb").read().decode("utf-8"))
        cryptor = PassphraseCryptor("口令abc", salt=bytes.fromhex(env["salt"]))
        payload = json.loads(cryptor.decrypt(env["token"]))["nodes"]
        assert all(n["content"] != secret.content for n in payload)  # local 永不上云
        assert len(payload) == 5
        store.close()
    finally:
        if saved:
            os.environ["MEMBRIDGE_PASSPHRASE"] = saved


def test_init_autogenerates_passphrase_into_vault(tmp_root=None):
    """v0.6.0：init 时系统自动生成同步口令并托管，用户无需设置/记忆。"""
    import membridge.clients as clients
    import membridge.wizard as wizard

    home = Path(tempfile.mkdtemp(prefix="membridge-gen-"))
    (home / ".workbuddy").mkdir()
    # ⚠️ clients 与 wizard 各有一份 HOME_DIR，必须同时注入——漏掉 clients 会让
    # init 把真实 ~/.zcode/cli/config.json、~/.cursor/mcp.json 等改写到本临时目录
    # （v0.8.0 前的真实事故：每跑一次测试，用户各平台配置就被劫持一次）
    clients.HOME_DIR = home
    wizard.HOME_DIR = home
    try:
        from membridge.wizard import InitOptions, run_init

        lines = []
        rc = run_init(
            InitOptions(db=str(home / "mem.db"), device="测试机",
                        netdisk_dir=str(home / "chan"), no_autosync=True,
                        interactive=False),
            out=lines.append,
        )
        assert rc == 0
        text = "\n".join(lines)
        assert "自动生成" in text
        store = MemoryStore(str(home / "mem.db"))
        key = vault.load_passphrase(store)
        assert key and len(key) >= 24  # 系统生成的强随机口令
        # 再次运行不重置已托管口令
        run_init(InitOptions(db=str(home / "mem.db"), device="测试机",
                             netdisk_dir=str(home / "chan"), no_autosync=True,
                             interactive=False), out=lines.append)
        assert vault.load_passphrase(MemoryStore(str(home / "mem.db"))) == key
        store.close()
    finally:
        clients.HOME_DIR = None
        wizard.HOME_DIR = None
