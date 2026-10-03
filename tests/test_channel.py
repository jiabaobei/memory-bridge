"""v0.13 通道身份测试：多台设备一致指向同一个云盘通道。"""

import contextlib
import io
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from membridge import channel, cli  # noqa: E402
from membridge.embeddings import HashingEmbedder  # noqa: E402
from membridge.node import MemoryNode  # noqa: E402
from membridge.store import MemoryStore  # noqa: E402
from membridge.transport import FolderTransport  # noqa: E402

COFFEE = "用户喜欢喝美式咖啡，不加糖"
DEV1, DEV2 = "PC-A", "笔记本-B"


def _store(device: str) -> MemoryStore:
    tmp = tempfile.TemporaryDirectory()
    store = MemoryStore(os.path.join(tmp.name, "mem.db"), device=device)
    store._tmp = tmp
    return store


def _remember(store: MemoryStore, text: str) -> None:
    store.add(MemoryNode(content=text, embedding=HashingEmbedder().embed(text),
                         device=store.device_name))


def test_publish_creates_channel_manifest():
    """首个发布的设备在通道里落「身份证」，本地认领同一 ID。"""
    store = _store(DEV1)
    root = tempfile.mkdtemp(prefix="membridge-netdisk-")
    _remember(store, COFFEE)
    tr = FolderTransport(root, store)
    path = tr.publish(plaintext=True)
    assert path is not None
    manifest = channel.read_manifest(root)
    assert manifest and manifest["channel_id"].startswith("mb-")
    assert manifest["creator"] == DEV1
    assert store.channel_id == manifest["channel_id"]
    assert tr.channel_status == "created"
    store.close()


def test_second_device_adopts_existing_channel():
    """第二台设备认领既有通道——不同设备一致指向同一通道，不靠用户记路径。"""
    root = tempfile.mkdtemp(prefix="membridge-netdisk-")
    a = _store(DEV1)
    _remember(a, COFFEE)
    FolderTransport(root, a).publish(plaintext=True)
    channel_id = a.channel_id

    b = _store(DEV2)
    tr_b = FolderTransport(root, b)
    tr_b.fetch()  # 通道里已有身份证 → 自动认领
    assert b.channel_id == channel_id
    assert tr_b.channel_status == "adopted"
    # 认领后再发布为 matched，身份证不被第二台设备改写
    _remember(b, "用户周三固定开会")
    tr_b.publish(plaintext=True)
    assert tr_b.channel_status == "matched"
    assert channel.read_manifest(root)["creator"] == DEV1
    a.close()
    b.close()


def test_mismatch_warns_and_never_rewrites_manifest():
    """本地通道 ID 与身份证不一致：显式告警，先到先得，身份证不改写。"""
    root = tempfile.mkdtemp(prefix="membridge-netdisk-")
    a = _store(DEV1)
    _remember(a, COFFEE)
    FolderTransport(root, a).publish(plaintext=True)
    original = channel.read_manifest(root)

    b = _store(DEV2)
    b.set_channel_id("mb-other00")  # 模拟本机曾指向另一个通道
    tr_b = FolderTransport(root, b)
    _remember(b, "用户的猫叫豆豆")
    tr_b.publish(plaintext=True)
    assert tr_b.channel_status == "mismatch"
    assert channel.read_manifest(root) == original  # 身份证不改写
    warning = channel.channel_warning(b)
    assert warning and warning["local"] == "mb-other00"
    assert warning["remote"] == original["channel_id"]
    # 修正后告警自动清除
    b.set_channel_id(original["channel_id"])
    tr_b.fetch()
    assert tr_b.channel_status == "matched"
    assert channel.channel_warning(b) is None
    a.close()
    b.close()


def test_peers_parsed_from_delta_filenames():
    """通道里出现过的设备从差分包文件名解析（设备名含连字符也正确）。"""
    root = tempfile.mkdtemp(prefix="membridge-netdisk-")
    os.makedirs(os.path.join(root, "outbox"), exist_ok=True)
    os.makedirs(os.path.join(root, "archive"), exist_ok=True)
    Path(root, "outbox", "my-old-pc-1710000000000-3n.delta.json").write_text("{}")
    Path(root, "archive", "手机-1710000000001-1n.delta.enc.json").write_text("{}")
    Path(root, "outbox", "notes.txt").write_text("干扰文件")
    peers = channel.peers(root, exclude="手机")
    assert peers == ["my-old-pc"]


def test_manifest_is_metadata_only():
    """身份证是纯元数据：不含口令，更不含任何记忆内容（内容冻结）。"""
    store = _store(DEV1)
    root = tempfile.mkdtemp(prefix="membridge-netdisk-")
    _remember(store, COFFEE)
    FolderTransport(root, store).publish(plaintext=True)
    text = Path(root, channel.CHANNEL_FILE).read_text(encoding="utf-8")
    data = json.loads(text)
    assert "passphrase" not in data and "口令" not in text
    assert COFFEE not in text
    store.close()


def test_onedrive_variant_roots_detected():
    """OneDrive 多根目录：`OneDrive - 个人` 等变体也要认出来（v0.13）。"""
    import membridge.wizard as wizard

    home = Path(tempfile.mkdtemp(prefix="membridge-home-"))
    (home / "OneDrive - Personal").mkdir()
    wizard.HOME_DIR = home
    try:
        found = wizard.detect_sync_roots()
        names = [n for n, _ in found]
        assert "OneDrive" in names
        assert any("OneDrive - Personal" in str(p) for _, p in found)
    finally:
        wizard.HOME_DIR = None


def test_channel_cli_reports_consistency():
    """membridge channel：一致报 ✅，分裂报 ⚠️，目录丢失也要明说。"""
    root = tempfile.mkdtemp(prefix="membridge-netdisk-")
    a = _store(DEV1)
    _remember(a, COFFEE)
    FolderTransport(root, a).publish(plaintext=True)
    a.set_netdisk(root)  # 真实流程由 init 写入通道目录
    a.close()

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = cli.cmd_channel(type("A", (), {"db": a._tmp.name + "/mem.db", "device": None})())
    out = buf.getvalue()
    assert rc == 0 and "✅ 通道身份一致" in out
    assert f"本机通道: {root}" in out

    # 通道目录消失 → 明确告警并返回非零
    missing = _store(DEV2)
    missing.set_netdisk(os.path.join(root, "不存在"))
    buf2 = io.StringIO()
    with contextlib.redirect_stdout(buf2):
        rc2 = cli.cmd_channel(type("A", (), {"db": missing._tmp.name + "/mem.db", "device": None})())
    assert rc2 == 1 and "通道目录不存在" in buf2.getvalue()
    missing.close()


def test_channel_cli_unconfigured():
    store = _store(DEV1)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = cli.cmd_channel(type("A", (), {"db": store._tmp.name + "/mem.db", "device": None})())
    assert rc == 2 and "尚未配置" in buf.getvalue()
    store.close()


# ---------------- v0.17：通道密钥 + 设备心跳 ----------------

def test_channel_key_travels_with_channel():
    """v0.31：通道密钥改为**从源码种子确定性派生**，不再是通道目录里的文件。

    契约反转的原因：密钥的源头若是一个需要先同步过来的文件，那「谁有那把钥匙」
    就成了要向人解释的事，与「装了项目就该通」矛盾。现在各端各自算、结果逐字节
    相同，跨设备天然同钥，且通道目录里**不再存放明文口令**。
    """
    root = tempfile.mkdtemp(prefix="membridge-netdisk-")
    k1 = channel.ensure_key(root)
    k2 = channel.ensure_key(root)
    assert k1 and k1 == k2, "同一份源码必须派生出同一把密钥"
    assert k1 == channel.derive_key(), "ensure_key 必须就是派生值（无文件时）"
    assert channel.key_fingerprint(k1) == channel.key_fingerprint(k2)
    # 关键：不再往通道目录写明文口令
    assert not Path(root, channel.KEY_FILE).exists(), "通道目录不该再存明文密钥"
    assert channel.key_fingerprint(k1) not in k1  # 输出指纹不等于泄露密钥


def test_derive_key_is_deterministic_across_calls():
    """派生必须是纯函数：同种子同结果，否则跨设备各算各的必然对不上。"""
    a = channel.derive_key()
    b = channel.derive_key()
    assert a == b
    assert len(a) == 43, "Fernet 口令形态：32 字节 base64 去 padding"
    assert "=" not in a, "base64 padding 必须去掉才能稳定拼接"


def test_derive_key_changes_with_seed():
    """换种子必须换密钥——否则改种子等于没改。"""
    base = channel.derive_key()
    other = channel.derive_key(seed="另一个种子")
    assert base != other
    assert channel.derive_key(salt="另一个盐") != base


def test_old_channel_key_file_still_wins_and_reports_mismatch():
    """旧通道（目录里已有 channel.key）必须继续用它，且明确报告与派生值不一致。

    不自动换钥匙：那样会让历史包集体解不开，把「口令不匹配」变得更难懂。
    只报告，让人决定何时轮换。
    """
    root = tempfile.mkdtemp(prefix="membridge-netdisk-")
    legacy = "Rng4rNLMk-ZnsywbGzPfyrX1kGaI92DCW0x8N-QKzr8"
    Path(root, channel.KEY_FILE).write_text(legacy, encoding="utf-8")
    assert channel.ensure_key(root) == legacy, "旧通道必须用旧密钥"
    assert channel.key_source_mismatch(root) == legacy, "且必须报告不一致"
    # 新鲜通道无此文件 → 不报告
    fresh = tempfile.mkdtemp(prefix="membridge-netdisk-")
    assert channel.key_source_mismatch(fresh) is None


def test_heartbeat_registers_device_without_publishing():
    """不发过包的设备也登记在册——「配好了却没人看得见」不再发生。"""
    root = tempfile.mkdtemp(prefix="membridge-netdisk-")
    a = _store(DEV1)
    FolderTransport(root, a)  # 只构造（init 同路径），不 publish
    roster = channel.roster(root)
    assert [r["device"] for r in roster] == [DEV1]
    assert roster[0]["nodes"] == 0
    b = _store(DEV2)
    _remember(b, "用户在四川阿坝红原县驻点")
    FolderTransport(root, b)
    roster = channel.roster(root)
    assert {r["device"] for r in roster} == {DEV1, DEV2}
    assert next(r for r in roster if r["device"] == DEV2)["nodes"] == 1
    a.close()
    b.close()


def test_each_device_writes_only_its_own_heartbeat():
    """每端只写自己的文件 → 无共享可变状态 → 天然零冲突（无「xxx (1).json」）。"""
    root = tempfile.mkdtemp(prefix="membridge-netdisk-")
    a = _store(DEV1)
    b = _store(DEV2)
    FolderTransport(root, a)
    FolderTransport(root, b)
    FolderTransport(root, a)  # A 再刷新一次，不应动 B 的文件
    files = sorted(os.listdir(os.path.join(root, channel.DEVICES_DIR)))
    assert len(files) == 2, files
    assert all(f.endswith(".json") for f in files)
    a.close()
    b.close()


def test_passphrase_free_encrypted_roundtrip():
    """v0.17 核心：不带 --passphrase 也端到端加密往返（密钥随通道同步）。"""
    try:
        import cryptography  # noqa: F401
    except ImportError:
        return  # 未装 netdisk  extras，跳过（CI 装了才验证加密链路）
    root = tempfile.mkdtemp(prefix="membridge-netdisk-")
    a = _store(DEV1)
    _remember(a, COFFEE)
    FolderTransport(root, a).publish(passphrase=channel.ensure_key(root))
    b = _store(DEV2)
    res = FolderTransport(root, b).fetch(passphrase=channel.ensure_key(root))
    assert any(r.get("nodes_added", 0) >= 1 for _, _, r in res["applied"])
    a.close()
    b.close()


def test_channel_cli_shows_fingerprint_never_secret():
    """channel 输出只给指纹不给密钥——AI 无法再把口令念进聊天记录。

    v0.31：密钥来自源码派生（通道目录里已无 channel.key），故改为断言「派生出的
    密钥本体不出现在输出里」。这层保护没变——变的只是密钥从哪来。
    """
    root = tempfile.mkdtemp(prefix="membridge-netdisk-")
    a = _store(DEV1)
    _remember(a, COFFEE)
    FolderTransport(root, a).publish(plaintext=True)
    a.set_netdisk(root)
    a.close()
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        cli.cmd_channel(type("A", (), {"db": a._tmp.name + "/mem.db", "device": None})())
    out = buf.getvalue()
    key = channel.derive_key()
    assert "通道密钥: 指纹" in out
    assert channel.key_fingerprint(key) in out, "应显示指纹便于各端核对"
    assert key not in out, "channel 命令绝不打印密钥本体"
    # 心跳名册：本机在册、容器指纹一致
    assert DEV1 in out and "（本机）" in out
    assert "✅ 各端容器指纹一致" in out


def test_channel_cli_warns_on_legacy_key_mismatch():
    """通道目录里存着旧密钥时，体检必须明确告警——不静默、不自动换钥匙。"""
    root = tempfile.mkdtemp(prefix="membridge-netdisk-")
    a = _store(DEV1)
    _remember(a, COFFEE)
    FolderTransport(root, a).publish(plaintext=True)
    Path(root, channel.KEY_FILE).write_text("旧通道遗留的密钥", encoding="utf-8")
    a.set_netdisk(root)
    a.close()
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        cli.cmd_channel(type("A", (), {"db": a._tmp.name + "/mem.db", "device": None})())
    out = buf.getvalue()
    assert "旧密钥" in out and "轮换" in out, out


def test_show_passphrase_masked_by_default():
    """show-passphrase 默认掩码，--reveal 才给原文（默认档不再泄露到聊天）。"""
    a = _store(DEV1)
    args = type("A", (), {"db": a._tmp.name + "/mem.db", "reveal": False, "device": None})()
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = cli.cmd_show_passphrase(args)
    out = buf.getvalue()
    if rc == 2:  # 本机 vault 未设置（非 Windows / 未 init）→ 只验证不打印任何密钥
        assert "尚未配置" in out
    else:
        assert "指纹" in out and "--reveal" in out
    a.close()


# ---------------- v0.20：通道迁移 --move + 宿主可达性提示 ----------------

def test_channel_cli_move_copies_and_repoints():
    """channel --move：通道文件复制到新目录 + 本机改指向；身份证随文件走不改写。"""
    root = tempfile.mkdtemp(prefix="membridge-netdisk-")
    a = _store(DEV1)
    _remember(a, COFFEE)
    FolderTransport(root, a).publish(plaintext=True)
    a.set_netdisk(root)
    channel_id = a.channel_id
    db_path = a._tmp.name + "/mem.db"
    a.close()

    new_root = tempfile.mkdtemp(prefix="membridge-moved-")
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = cli.cmd_channel(type("A", (), {"db": db_path, "device": None,
                                            "move": new_root})())
    out = buf.getvalue()
    assert rc == 0 and "通道已迁移" in out
    assert os.path.exists(os.path.join(new_root, "channel.json"))
    manifest = channel.read_manifest(new_root)
    assert manifest and manifest["channel_id"] == channel_id  # 身份不改写
    reopened = MemoryStore(db_path)
    assert reopened.netdisk == new_root
    reopened.close()


def test_channel_cli_warns_desktop_only_host():
    """v0.20 可达性：宿主是 OneDrive/iCloud 时提示容器/网页端不可达。"""
    base = tempfile.mkdtemp(prefix="membridge-")
    root = os.path.join(base, "OneDrive", "membridge")
    os.makedirs(root)
    a = _store(DEV1)
    _remember(a, COFFEE)
    FolderTransport(root, a).publish(plaintext=True)
    a.set_netdisk(root)
    db_path = a._tmp.name + "/mem.db"
    a.close()

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = cli.cmd_channel(type("A", (), {"db": db_path, "device": None})())
    assert rc == 0 and "不可达" in buf.getvalue()


def test_env_passphrase_no_longer_shadows_channel_key():
    """v0.30.3：环境变量不再盖住通道密钥（真机事故 2026-10-03）。

    v0.27.1 时这条契约是反的：环境变量优先，只做诊断不改行为（「只诊断不改行为——
    优先级一字未改」）。结果是迁移时设过环境变量的机器，自动任务发包用本机口令，
    他端用通道密钥解不开。v0.30.3 把三处口径统一成「显式 > 通道密钥 > 环境变量」，
    通道密钥压过本机历史，「装了就能通」才成立。

    保留 v0.27.1 的全部验证意图：显式口令仍是当次意图、密钥本体不落输出。
    """
    import argparse

    tmp = tempfile.TemporaryDirectory()
    root = os.path.join(tmp.name, "chan")
    key = channel.ensure_key(root)  # 通道自带的钥匙
    stale = key + "-迁移前的旧口令"

    def resolve(env, explicit=None):
        ns = argparse.Namespace(passphrase=explicit)
        saved = os.environ.get("MEMBRIDGE_PASSPHRASE")
        if env is None:
            os.environ.pop("MEMBRIDGE_PASSPHRASE", None)
        else:
            os.environ["MEMBRIDGE_PASSPHRASE"] = env
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                out = cli._resolve_passphrase(ns, root)
        finally:
            if saved is None:
                os.environ.pop("MEMBRIDGE_PASSPHRASE", None)
            else:
                os.environ["MEMBRIDGE_PASSPHRASE"] = saved
        return out, buf.getvalue()

    # ① 环境变量与通道密钥不一致 → 通道密钥赢（这是本次修的核心）
    got, _ = resolve(stale)
    assert got == key, "通道密钥必须压过环境变量旧口令，否则跨设备解不开"

    # ② 未设环境变量 → 走通道密钥
    got, _ = resolve(None)
    assert got == key

    # ③ 显式 --passphrase 是当次意图，最高优先，不算被环境变量影响
    got, log = resolve(stale, explicit="本次显式口令")
    assert got == "本次显式口令" and log.strip() == ""

    # ④ 老式通道（无 channel.key）才回落到环境变量——老用户行为不变
    legacy = os.path.join(tmp.name, "legacy")
    os.makedirs(legacy, exist_ok=True)
    got, _ = cli._resolve_passphrase(argparse.Namespace(passphrase=None), legacy), None
    assert got is not None, "老式通道应回落到环境变量或新建密钥，不得返回空"

    # ⑤ 密钥与口令本体绝不落进任何输出（只说指纹）
    _, log = resolve(stale)
    assert stale not in log and key not in log
