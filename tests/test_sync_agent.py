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


def test_autosync_requires_channel_and_falls_back_to_channel_key():
    """v0.17：通道仍必配；口令不再是必需项——没有口令就用随通道同步的通道密钥。

    否则自动任务（保险库口令）与手动 sync（通道密钥）会往同一条通道里发
    两种钥匙的包，对端解不开，又是静默分裂。
    """
    saved = os.environ.pop("MEMBRIDGE_PASSPHRASE", None)  # 隔离系统环境变量
    try:
        store = _store("手机")
        lines = []
        assert sync_agent.run_autosync(store_path=store.path, out=lines.append) == 2
        assert any("云盘通道" in ln for ln in lines)
        store.set_netdisk(rf"{tempfile.mkdtemp()}\chan")
        lines.clear()
        assert sync_agent.run_autosync(store_path=store.path, out=lines.append) == 0
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


def _fake_rclone_with_conf(tmp: Path) -> None:
    """假 rclone + 含坚果云授权段的配置（has_remote 为真）。"""
    conf = tmp / "rclone.conf"
    conf.write_text("[membridge_jgy]\ntype = webdav\nurl = https://x/dav/\n",
                    encoding="utf-8")
    fake = tmp / "rclone"
    fake.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "config" ] && [ "$2" = "file" ]; then\n'
        f'  echo "{conf}"\n  exit 0\nfi\n'
        "exit 0\n",
        encoding="utf-8",
    )
    fake.chmod(0o755)


def test_autosync_runs_folder_round_when_rclone_wired():
    """v0.24：rclone 接线的机器，自动循环先跑文件夹级双向再跑包级。"""
    saved = os.environ.pop("MEMBRIDGE_PASSPHRASE", None)
    tmp = Path(tempfile.mkdtemp(prefix="mb-as-"))
    _fake_rclone_with_conf(tmp)
    old_path = os.environ.get("PATH", "")
    os.environ["PATH"] = str(tmp) + os.pathsep + old_path
    try:
        store = _store("手机")
        chan = tempfile.mkdtemp()
        store.set_netdisk(chan)
        (Path(chan) / ".membridge-netdisk.json").write_text(
            json.dumps({"jianguoyun": {"remote_path": "membridge",
                                       "local_dir": chan, "role": "primary"}}),
            encoding="utf-8",
        )
        lines = []
        assert sync_agent.run_autosync(store_path=store.path, out=lines.append) == 0
        assert any("网盘双向" in ln for ln in lines)
        store.close()
    finally:
        os.environ["PATH"] = old_path
        if saved:
            os.environ["MEMBRIDGE_PASSPHRASE"] = saved


def test_autosync_skips_folder_round_without_remote():
    """v0.24：本机云盘客户端机器（无授权段）静默跳过文件夹轮，不报错。"""
    saved = os.environ.pop("MEMBRIDGE_PASSPHRASE", None)
    tmp = Path(tempfile.mkdtemp(prefix="mb-as2-"))
    _fake_rclone_with_conf(tmp)  # 配置里没有 [membridge_od] → has_remote 为假
    old_path = os.environ.get("PATH", "")
    os.environ["PATH"] = str(tmp) + os.pathsep + old_path
    try:
        store = _store("手机")
        chan = tempfile.mkdtemp()
        store.set_netdisk(chan)
        (Path(chan) / ".membridge-netdisk.json").write_text(
            json.dumps({"onedrive": {"remote_path": "membridge",
                                     "local_dir": chan, "role": "backup"}}),
            encoding="utf-8",
        )
        lines = []
        assert sync_agent.run_autosync(store_path=store.path, out=lines.append) == 0
        assert not any("网盘双向" in ln for ln in lines)
        store.close()
    finally:
        os.environ["PATH"] = old_path
        if saved:
            os.environ["MEMBRIDGE_PASSPHRASE"] = saved


def test_posix_cron_autosync_registration():
    """v0.24：Linux 初始化注册用户 cron（带标记、幂等）。"""
    import membridge.wizard as wiz

    tmp = Path(tempfile.mkdtemp(prefix="mb-cron-"))
    state = tmp / "crontab.store"
    fake = tmp / "crontab"
    fake.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "-l" ]; then cat "' + str(state) + '" 2>/dev/null; exit 0; fi\n'
        'if [ "$1" = "-" ]; then cat > "' + str(state) + '"; exit 0; fi\n'
        "exit 0\n",
        encoding="utf-8",
    )
    fake.chmod(0o755)
    old_path = os.environ.get("PATH", "")
    os.environ["PATH"] = str(tmp) + os.pathsep + old_path
    try:
        lines = []
        wiz._register_posix_autosync(lines.append)
        assert any("cron 已注册" in ln for ln in lines)
        body = state.read_text(encoding="utf-8")
        assert "membridge-autosync" in body and "*/15" in body
        # 幂等：再注册一次仍只有一行标记
        wiz._register_posix_autosync(lines.append)
        assert body and state.read_text(encoding="utf-8").count("membridge-autosync") == 1
    finally:
        os.environ["PATH"] = old_path
