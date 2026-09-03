"""口令保险库：自动同步的密钥托管（绑定本机用户账户，全平台覆盖）。

设计：用户只在 init 时输入一次云盘同步口令，此后由计划任务自动同步。
口令加密后存于记忆库 meta——只有本机本用户能解，云盘上、其他账户、
其他机器都解不开。零第三方依赖，符合 ncnn 式零依赖坚守。

平台分流（v0.22）：
- Windows：DPAPI（CryptProtectData，绑定当前用户），纯 ctypes 调用系统 API。
- Linux / macOS：文件保险库——密钥文件 `~/.membridge/vault.key`（32 随机
  字节，目录 700 / 文件 600，绑定本机用户账户，与 DPAPI 的用户绑定同定位），
  SHA-256 计数流加密。存储值带 `mbvault1:` 前缀，与 DPAPI 密文可区分。

密钥文件丢失或损坏时视为「未托管」返回 None，不抛出——与 DPAPI 换用户/
换机器时的降级路径一致。
"""

from __future__ import annotations

import base64
import ctypes
import hashlib
import os
import sys
from pathlib import Path
from typing import Optional

from .store import MemoryStore

_VAULT_KEY = "netdisk_key_vault"
_FILE_PREFIX = "mbvault1:"  # 文件保险库密文前缀（区别于裸 base64 的 DPAPI 密文）
_NONCE_LEN = 12
_CRYPT32 = None
_KERNEL32 = None


class _DATA_BLOB(ctypes.Structure):
    _fields_ = [
        ("cbData", ctypes.c_ulong),
        ("pbData", ctypes.c_void_p),
    ]


def _libs():
    global _CRYPT32, _KERNEL32
    if _CRYPT32 is None:
        _CRYPT32 = ctypes.windll.crypt32
        _KERNEL32 = ctypes.windll.kernel32
        # 64 位指针参数必须显式声明，否则句柄按 32 位 int 转换会溢出
        _KERNEL32.LocalFree.argtypes = [ctypes.c_void_p]
        _KERNEL32.LocalFree.restype = ctypes.c_void_p
    return _CRYPT32, _KERNEL32


def _protect(data: bytes) -> bytes:
    crypt32, kernel32 = _libs()
    buf = ctypes.create_string_buffer(data, len(data))
    blob_in = _DATA_BLOB(len(data), ctypes.cast(buf, ctypes.c_void_p))
    blob_out = _DATA_BLOB()
    if not crypt32.CryptProtectData(
        ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out)
    ):
        raise OSError("DPAPI 加密失败")
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        kernel32.LocalFree(blob_out.pbData)


def _unprotect(blob: bytes) -> bytes:
    crypt32, kernel32 = _libs()
    buf = ctypes.create_string_buffer(blob, len(blob))
    blob_in = _DATA_BLOB(len(blob), ctypes.cast(buf, ctypes.c_void_p))
    blob_out = _DATA_BLOB()
    if not crypt32.CryptUnprotectData(
        ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out)
    ):
        raise OSError("DPAPI 解密失败（可能来自其他用户/机器）")
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        kernel32.LocalFree(blob_out.pbData)


# ---------------------------------------------------------------------------
# 文件保险库（Linux / macOS）
# ---------------------------------------------------------------------------


def _keyfile_path() -> Path:
    override = os.environ.get("MEMBRIDGE_VAULT_DIR")
    base = Path(override).expanduser() if override else Path.home() / ".membridge"
    return base / "vault.key"


def _load_key() -> Optional[bytes]:
    try:
        key = _keyfile_path().read_bytes()
    except OSError:
        return None
    return key if len(key) == 32 else None  # 长度不对视为损坏


def _ensure_key() -> bytes:
    key = _load_key()
    if key is not None:
        return key
    path = _keyfile_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path.parent, 0o700)  # 目录只对本人开放
    except OSError:
        pass  # 个别文件系统不支持 chmod，不阻塞（文件权限仍收紧）
    key = os.urandom(32)
    path.write_bytes(key)
    os.chmod(path, 0o600)
    return key


def _keystream(key: bytes, nonce: bytes, length: int) -> bytes:
    out = bytearray()
    counter = 0
    while len(out) < length:
        out += hashlib.sha256(key + nonce + counter.to_bytes(4, "big")).digest()
        counter += 1
    return bytes(out[:length])


def _file_protect(data: bytes) -> str:
    key = _ensure_key()
    nonce = os.urandom(_NONCE_LEN)
    ct = bytes(a ^ b for a, b in zip(data, _keystream(key, nonce, len(data))))
    return _FILE_PREFIX + base64.b64encode(nonce + ct).decode("ascii")


def _file_unprotect(raw: str) -> bytes:
    payload = base64.b64decode(raw[len(_FILE_PREFIX):].encode("ascii"))
    if len(payload) <= _NONCE_LEN:
        raise OSError("文件保险库密文损坏")
    key = _load_key()
    if key is None:
        raise OSError("文件保险库密钥缺失（密钥文件丢失或损坏）")
    nonce, ct = payload[:_NONCE_LEN], payload[_NONCE_LEN:]
    return bytes(a ^ b for a, b in zip(ct, _keystream(key, nonce, len(ct))))


# ---------------------------------------------------------------------------
# 对外接口
# ---------------------------------------------------------------------------


def supported() -> bool:
    return os.name == "nt" or sys.platform in ("linux", "darwin")


def save_passphrase(store: MemoryStore, passphrase: str) -> None:
    if not supported():
        raise OSError("此平台暂不支持自动同步口令托管")
    if os.name == "nt":
        blob = _protect(passphrase.encode("utf-8"))
        value = base64.b64encode(blob).decode("ascii")
    else:
        value = _file_protect(passphrase.encode("utf-8"))
    with store.transaction():
        store._set_meta(_VAULT_KEY, value)


def clear_passphrase(store: MemoryStore) -> None:
    """清除本机托管的口令（v0.17）：改用随通道同步的通道密钥，各端一把钥匙。

    用于老通道收敛——本机口令与对端口令本来就是两个（各端 init 各自生成），
    清掉之后两端才真正用同一把钥匙，也省掉了「把口令念给对端」这个动作。
    """
    with store.transaction():
        store._set_meta(_VAULT_KEY, "")


def load_passphrase(store: MemoryStore) -> Optional[str]:
    raw = store._get_meta(_VAULT_KEY)
    if not raw:
        return None
    try:
        if raw.startswith(_FILE_PREFIX):
            return _file_unprotect(raw).decode("utf-8")
        return _unprotect(base64.b64decode(raw)).decode("utf-8")
    except Exception:
        return None  # 密钥缺失/换了用户/损坏：视为未设置，不抛出
