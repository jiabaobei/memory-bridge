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
