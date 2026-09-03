"""口令保险库测试（v0.22）：跨平台存取往返、文件保险库权限与降级路径。"""

import os
import stat
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from membridge import vault  # noqa: E402
from membridge.store import MemoryStore  # noqa: E402


def _store():
    return MemoryStore(os.path.join(tempfile.mkdtemp(), "m.db"), device="测试机")


def _isolated_vault_dir(fn):
    """让文件保险库写到临时目录，避免污染真实家目录。"""

    def wrapper():
        saved = os.environ.get("MEMBRIDGE_VAULT_DIR")
        os.environ["MEMBRIDGE_VAULT_DIR"] = tempfile.mkdtemp(prefix="mbvault-")
        try:
            fn()
        finally:
            if saved is None:
                os.environ.pop("MEMBRIDGE_VAULT_DIR", None)
            else:
                os.environ["MEMBRIDGE_VAULT_DIR"] = saved

    wrapper.__name__ = fn.__name__
    return wrapper


def test_supported_on_current_platform():
    assert vault.supported()


def test_vault_roundtrip():
    store = _store()
    assert vault.load_passphrase(store) is None
    vault.save_passphrase(store, "我的云盘口令123")
    assert vault.load_passphrase(store) == "我的云盘口令123"
    # 覆盖写入也能正确读回
    vault.save_passphrase(store, "换一把新口令")
    assert vault.load_passphrase(store) == "换一把新口令"
    store.close()


def test_clear_passphrase():
    store = _store()
    vault.save_passphrase(store, "口令abc")
    vault.clear_passphrase(store)
    assert vault.load_passphrase(store) is None
    store.close()


@_isolated_vault_dir
def test_file_vault_keyfile_permissions():
    if os.name == "nt":
        print("SKIP: Windows 走 DPAPI，无密钥文件")
        return
    store = _store()
    vault.save_passphrase(store, "权限检查口令")
    key_path = Path(os.environ["MEMBRIDGE_VAULT_DIR"]) / "vault.key"
    assert key_path.exists()
    mode = stat.S_IMODE(os.stat(key_path).st_mode)
    assert mode == 0o600  # 密钥文件只有本人可读写
    dir_mode = stat.S_IMODE(os.stat(key_path.parent).st_mode)
    assert dir_mode == 0o700
    assert vault.load_passphrase(store) == "权限检查口令"
    store.close()


@_isolated_vault_dir
def test_file_vault_missing_keyfile_returns_none():
    if os.name == "nt":
        print("SKIP: Windows 走 DPAPI，无密钥文件")
        return
    store = _store()
    vault.save_passphrase(store, "密钥丢失场景")
    (Path(os.environ["MEMBRIDGE_VAULT_DIR"]) / "vault.key").unlink()
    # 密钥文件丢失：视为未托管，不抛出
    assert vault.load_passphrase(store) is None
    store.close()


@_isolated_vault_dir
def test_file_vault_stored_value_prefixed():
    if os.name == "nt":
        print("SKIP: Windows 走 DPAPI，无前缀格式")
        return
    store = _store()
    vault.save_passphrase(store, "前缀检查")
    raw = store._get_meta("netdisk_key_vault")
    assert raw.startswith(vault._FILE_PREFIX)
    # 明文绝不出现在存储值里
    assert "前缀检查" not in raw
    store.close()
