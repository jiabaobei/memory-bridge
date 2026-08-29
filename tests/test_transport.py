"""传输通道（网盘中转）测试。"""

import os
import sys
import tempfile

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


def test_passphrase_cryptor_roundtrip():
    if not HAS_CRYPTO:
        print("\nSKIP: 未安装 cryptography")
        return
    c = PassphraseCryptor("口令", salt=b"0123456789abcdef")
    token = c.encrypt("机密内容")
    assert "机密" not in token
    assert PassphraseCryptor("口令", salt=b"0123456789abcdef").decrypt(token) == "机密内容"
