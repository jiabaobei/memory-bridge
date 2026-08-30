"""口令保险库：自动同步的密钥托管（Windows DPAPI，绑定当前用户账户）。

设计：用户只在 init 时输入一次云盘同步口令，此后由计划任务自动同步。
口令用 Windows DPAPI（CryptProtectData，绑定当前用户）加密后存于记忆库
meta——只有本机本用户能解，云盘上、其他账户、其他机器都解不开。
零第三方依赖（纯 ctypes 调用系统 API），符合 ncnn 式零依赖坚守。

非 Windows 平台暂不支持自动同步口令托管（可显式传 --passphrase 手动同步）。
"""

from __future__ import annotations

import base64
import ctypes
import os
from typing import Optional

from .store import MemoryStore

_VAULT_KEY = "netdisk_key_vault"
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


def supported() -> bool:
    return os.name == "nt"


def save_passphrase(store: MemoryStore, passphrase: str) -> None:
    if not supported():
        raise OSError("自动同步口令托管目前仅支持 Windows")
    blob = _protect(passphrase.encode("utf-8"))
    with store.transaction():
        store._set_meta(_VAULT_KEY, base64.b64encode(blob).decode("ascii"))


def load_passphrase(store: MemoryStore) -> Optional[str]:
    raw = store._get_meta(_VAULT_KEY)
    if not raw:
        return None
    try:
        return _unprotect(base64.b64decode(raw)).decode("utf-8")
    except Exception:
        return None  # 换了用户/损坏：视为未设置，不抛出
