"""传输通道（网盘中转）测试。"""

import builtins
import os
import sys
import tempfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from membridge import privacy, transport  # noqa: E402
from membridge.embeddings import HashingEmbedder  # noqa: E402
from membridge.node import MemoryNode  # noqa: E402
from membridge.san import build_edges  # noqa: E402
from membridge.store import MemoryStore  # noqa: E402
from membridge.transport import PassphraseCryptor  # noqa: E402

try:
    import cryptography  # noqa: F401
    HAS_CRYPTO = True
except ImportError:
    HAS_CRYPTO = False

COFFEE = "用户喜欢喝美式咖啡，不加糖"
LATTE = "用户也喜欢手冲咖啡"
DEV1, DEV2 = "手机", "PC"


def _store(device: str) -> MemoryStore:
    tmp = tempfile.TemporaryDirectory()
    store = MemoryStore(os.path.join(tmp.name, "mem.db"), device=device)
    store._tmp = tmp
    return store


def _channel() -> str:
    return tempfile.mkdtemp(prefix="membridge-netdisk-")


def _add(store: MemoryStore, texts) -> None:
    emb = HashingEmbedder()
    for t in texts:
        store.add(MemoryNode(
            content=t,
            embedding=emb.embed(t),
            device=store.device_name,
            migration=privacy.default_migration(t),
        ))
    build_edges(store, emb)


def test_folder_transport_plaintext_roundtrip():
    ch = _channel()
    a, b = _store(DEV1), _store(DEV2)
    _add(a, (COFFEE, LATTE))
    ta = transport.FolderTransport(ch, a)
    tb = transport.FolderTransport(ch, b)

    # 发布 → 接收
    path = ta.publish(plaintext=True)
    assert path and os.path.exists(path)
    result = tb.fetch()
    assert len(result["applied"]) == 1
    assert b.count_nodes() == 2
    assert b.count_edges() >= 1

    # 幂等：没有新内容时不产生新包；重复 fetch 不重复应用
    assert ta.publish(plaintext=True) is None
    assert tb.fetch()["applied"] == []

    # 增量发布
    _add(a, ("用户在开发记忆桥项目",))
    assert ta.publish(plaintext=True)
    result = tb.fetch()
    assert len(result["applied"]) == 1 and b.count_nodes() == 3

    # 成功应用后包归档（T4），outbox 清空；自己的包不会被自己应用
    assert os.listdir(os.path.join(ch, "archive"))
    _add(a, ("再来一条新记忆",))
    ta.publish(plaintext=True)
    assert ta.fetch()["applied"] == []  # 自己发的包跳过
    a.close()
    b.close()


def test_folder_transport_requires_encryption_decision():
    a = _store(DEV1)
    _add(a, (COFFEE,))
    ta = transport.FolderTransport(_channel(), a)
    try:
        ta.publish()  # 既无口令又不显式明文 → 必须拒绝
        assert False, "应当拒绝未决状态"
    except ValueError:
        pass
    a.close()


def test_folder_transport_encrypted_roundtrip():
    if not HAS_CRYPTO:
        print("\nSKIP: 未安装 cryptography（pip install 'membridge[netdisk]'）")
        return
    ch = _channel()
    a, b = _store(DEV1), _store(DEV2)
    _add(a, (COFFEE, LATTE))
    ta = transport.FolderTransport(ch, a)
    tb = transport.FolderTransport(ch, b)

    path = ta.publish(passphrase="跨设备口令123")
    assert path and path.endswith(".enc.json")
    with open(path, "r", encoding="utf-8") as f:
        assert "COFFEE" not in f.read()[:0]  # 信封为 JSON，密文不以明文出现

    result = tb.fetch(passphrase="跨设备口令123")
    assert len(result["applied"]) == 1 and b.count_nodes() == 2

    # 错误口令：只跳过，不影响其他包
    _add(a, ("新增一条待同步记忆",))
    ta.publish(passphrase="跨设备口令123")
    bad = tb.fetch(passphrase="wrong")
    assert bad["applied"] == [] and bad["skipped"]
    assert b.count_nodes() == 2

    # 正确口令补收
    assert len(tb.fetch(passphrase="跨设备口令123")["applied"]) == 1
    a.close()
    b.close()


def test_publish_sanitizes_hostile_device_name():
    """设备名属半可信输入：含路径成分时文件名必须被消毒，落点必须在 outbox 内。"""
    a = _store("..\\..\\evil")
    _add(a, (COFFEE,))
    ch = _channel()
    ta = transport.FolderTransport(ch, a)
    path = ta.publish(plaintext=True)
    base = os.path.basename(path)
    assert ".." not in Path(base).parts  # ".." 不得作为路径成分出现
    assert "\\" not in base and "/" not in base
    assert os.path.dirname(os.path.realpath(path)) == os.path.realpath(os.path.join(ch, "outbox"))
    # 接收端仍可正常应用
    b = _store(DEV2)
    tb = transport.FolderTransport(ch, b)
    assert len(tb.fetch()["applied"]) == 1
    a.close()
    b.close()


def test_passphrase_cryptor_roundtrip():
    if not HAS_CRYPTO:
        print("\nSKIP: 未安装 cryptography")
        return
    c = PassphraseCryptor("口令", salt=b"0123456789abcdef")
    token = c.encrypt("机密内容")
    assert "机密" not in token
    assert PassphraseCryptor("口令", salt=b"0123456789abcdef").decrypt(token) == "机密内容"


def test_publish_force_rebuilds_channel_after_loss():
    """云盘侧差分包丢失后，普通 publish 会认为「已发布」而拒绝；--force 必须能重建。

    真实故障：OneDrive 同步清空了 outbox，本地 published_fps 仍在，记忆被永久锁死。
    """
    a = _store(DEV1)
    _add(a, (COFFEE, LATTE))
    ch = _channel()
    ta = transport.FolderTransport(ch, a)
    first = ta.publish(plaintext=True)
    assert first is not None

    # 模拟云盘侧文件丢失
    os.remove(first)
    assert not os.listdir(os.path.join(ch, "outbox"))

    # 不 force：本地仍认为已发布 → 拒绝重发
    assert ta.publish(plaintext=True) is None
    # force：重建全量
    rebuilt = ta.publish(plaintext=True, force=True)
    assert rebuilt is not None
    delta = transport.Delta.from_json(open(rebuilt, encoding="utf-8").read())
    assert len(delta.nodes) == 2
    a.close()


def test_publish_force_is_idempotent_when_nothing_new():
    """force 只是忽略「已发布」记录，内容仍由差分包本身决定，不会凭空造包。"""
    a = _store(DEV1)
    _add(a, (COFFEE,))
    ch = _channel()
    ta = transport.FolderTransport(ch, a)
    assert ta.publish(plaintext=True) is not None
    # 第一次 force：文件仍在通道里，内容已发布过 → 仍会重发（force 语义）
    assert ta.publish(plaintext=True, force=True) is not None
    a.close()


def test_fetch_three_devices_all_receive_same_package():
    """三台以上设备：先取的设备把包移入 archive，后续设备必须仍能补取。"""
    a = _store(DEV1)
    _add(a, (COFFEE, LATTE))
    ch = _channel()
    transport.FolderTransport(ch, a).publish(plaintext=True)

    peers = [_store(f"设备{i}") for i in "BCD"]
    for p in peers:
        tp = transport.FolderTransport(ch, p)
        result = tp.fetch()
        # 每个包只应被处理一次（不能因扫了 archive 而重复计数）
        assert len(result["applied"]) == 1, f"{p.device_name} 处理了 {len(result['applied'])} 次"
        assert p.stats()["nodes"] == 2

    # 取完后包应停留在 archive，供后续新设备继续补取
    assert os.listdir(os.path.join(ch, "archive"))
    a.close()
    for p in peers:
        p.close()


def test_fetch_missing_passphrase_message_is_actionable():
    """未提供口令时，提示必须说清怎么补，而不是干巴巴一句。"""
    a = _store(DEV1)
    _add(a, (COFFEE,))
    ch = _channel()
    transport.FolderTransport(ch, a).publish(passphrase="正确口令")

    b = _store(DEV2)
    result = transport.FolderTransport(ch, b).fetch()
    assert result["applied"] == []
    reason = result["skipped"][0][1]
    assert "PASSPHRASE" in reason, reason  # 必须指名环境变量
    a.close()
    b.close()


def test_fetch_oserror_goes_to_errors_and_retries():
    """v0.8：环境错误（磁盘满/权限/I/O）必须与数据错误分流——进 errors、
    包保留原位待重试，而不是被当成坏包静默跳过。"""
    a = _store(DEV1)
    _add(a, (COFFEE,))
    ch = _channel()
    transport.FolderTransport(ch, a).publish(plaintext=True)

    b = _store(DEV2)
    tb = transport.FolderTransport(ch, b)
    real_open = builtins.open

    def raising_open(path, *args, **kwargs):
        # 只对通道里的差分包注入 PermissionError，其余文件照常
        if str(path).endswith(".delta.json"):
            raise PermissionError(13, "模拟权限/磁盘故障")
        return real_open(path, *args, **kwargs)

    with mock.patch("builtins.open", side_effect=raising_open):
        result = tb.fetch()
    assert result["applied"] == []
    assert result["skipped"] == []
    assert result["errors"] and "重试" in result["errors"][0][1]
    # 包未被归档，仍在 outbox——下次 fetch 可重试
    assert os.listdir(os.path.join(ch, "outbox"))

    # 故障解除后重试成功
    result2 = tb.fetch()
    assert len(result2["applied"]) == 1 and b.count_nodes() == 1
    a.close()
    b.close()


def test_fetch_wrong_passphrase_message_is_actionable():
    """口令错误时，提示必须区分于「未提供」，并给出 show-passphrase 指引。"""
    if not HAS_CRYPTO:
        print("\nSKIP: 未安装 cryptography")
        return
    a = _store(DEV1)
    _add(a, (COFFEE,))
    ch = _channel()
    transport.FolderTransport(ch, a).publish(passphrase="正确口令")

    b = _store(DEV2)
    result = transport.FolderTransport(ch, b).fetch(passphrase="错误口令")
    assert result["applied"] == []
    reason = result["skipped"][0][1]
    assert "口令不匹配" in reason, reason
    assert "show-passphrase" in reason, reason
    a.close()
    b.close()
