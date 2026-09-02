"""通道身份层：让多台设备的「云盘通道」一致指向同一个（v0.13）。

背景：`netdisk_dir` 原本只是每台设备的本地路径——两台设备装的同步盘
不同时（一台有坚果云 + OneDrive、另一台只有 OneDrive），自动选择规则
会各自选到不同的云，记忆圈**静默分裂**，没有任何警告。

本模块给通道目录一个自描述清单 `channel.json`：
  - 首个发布/初始化的设备**创建**它；
  - 后续设备**认领**同一个通道（adopt），`membridge init` 明确提示；
  - 本地记录与清单不一致时**显式告警**（疑似通道分裂），不改写清单。

约束：清单是纯元数据（通道 ID / 创建者 / 时间 / 嵌入器指纹），
**不含口令、不触碰任何记忆内容**——内容冻结原则不受影响。
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import sys
import time
import uuid
from typing import Dict, List, Optional, Tuple

CHANNEL_FILE = "channel.json"
KEY_FILE = "channel.key"
DEVICES_DIR = "devices"


def manifest_path(root: str) -> str:
    return os.path.join(root, CHANNEL_FILE)


def read_manifest(root: str) -> Optional[Dict]:
    """读取通道清单；不存在或损坏返回 None（按无清单处理）。"""
    try:
        with open(manifest_path(root), "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) and data.get("channel_id") else None
    except (OSError, ValueError):
        return None


def write_manifest(root: str, manifest: Dict) -> str:
    """先写临时文件再改名，避免网盘读到半包（与差分包同一防御）。"""
    final = manifest_path(root)
    tmp = final + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    os.replace(tmp, final)
    return final


def new_channel_id() -> str:
    return "mb-" + uuid.uuid4().hex[:8]


def peers(root: str, exclude: str = "") -> List[str]:
    """从 outbox/archive 的差分包文件名解析通道里出现过的设备（纯元数据）。

    文件名形如 `<设备>-<毫秒时间戳>-<条数>n.delta[.enc].json`；
    设备名经消毒后仍可能含 `-`，故从右侧切两刀取前缀。
    """
    seen: List[str] = []
    for sub in ("outbox", "archive"):
        d = os.path.join(root, sub)
        if not os.path.isdir(d):
            continue
        for fn in sorted(os.listdir(d)):
            if ".delta" not in fn or fn.endswith(".tmp"):
                continue
            parts = fn.rsplit("-", 2)
            if len(parts) != 3:
                continue
            dev = parts[0]
            if dev and dev != exclude and dev not in seen:
                seen.append(dev)
    return seen


def ensure_channel_identity(root: str, store) -> Tuple[Optional[Dict], str]:
    """发布/取回/配置通道时调用：清单存在 → 认领或核对；不存在 → 创建。

    返回 (manifest, status)，status ∈
      created   本设备创建了通道清单（首个设备）
      adopted   认领了既有通道（本地之前没有通道 ID）
      matched   本地通道 ID 与清单一致
      mismatch  本地通道 ID 与清单不一致（疑似分裂，已记录告警，清单不改写）
      absent    通道目录不存在
    """
    if not os.path.isdir(root):
        return None, "absent"
    local_id = store._get_meta("channel_id")
    manifest = read_manifest(root)

    if manifest is None:
        channel_id = local_id or new_channel_id()
        manifest = {
            "channel_id": channel_id,
            "name": os.path.basename(os.path.normpath(os.path.abspath(root))),
            "created": time.strftime("%Y-%m-%d %H:%M:%S"),
            "creator": store.device_name,
            "embedder": store._get_meta("embedder_id"),
        }
        try:
            write_manifest(root, manifest)
        except OSError:
            # 清单写不进（权限/网盘只读）不阻断同步主流程——身份核对降级为无
            return None, "absent"
        if not local_id:
            with store.transaction():
                store._set_meta("channel_id", channel_id)
        return manifest, "created"

    remote_id = manifest["channel_id"]
    if not local_id:
        with store.transaction():
            store._set_meta("channel_id", remote_id)
        _clear_channel_warning(store)
        return manifest, "adopted"
    if local_id == remote_id:
        _clear_channel_warning(store)
        return manifest, "matched"

    # 分裂：先到先得，不改写清单；记录告警由 doctor / channel 命令显式呈现
    with store.transaction():
        store._set_meta(
            "channel_warning",
            json.dumps(
                {
                    "local": local_id,
                    "remote": remote_id,
                    "root": root,
                    "seen": time.strftime("%Y-%m-%d %H:%M:%S"),
                },
                ensure_ascii=False,
            ),
        )
    return manifest, "mismatch"


def channel_warning(store) -> Optional[Dict]:
    raw = store._get_meta("channel_warning")
    if not raw:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return None


def _clear_channel_warning(store) -> None:
    if store._get_meta("channel_warning"):
        with store.transaction():
            store._set_meta("channel_warning", "")


# ---------------- v0.17：通道密钥 + 设备心跳 ----------------

def key_path(root: str) -> str:
    return os.path.join(root, KEY_FILE)


def ensure_key(root: str, create: bool = True) -> Optional[str]:
    """通道密钥随通道走：没有就生成，随网盘同步到各端（v0.17）。

    各端零输入、零托管、零复述——用户与 AI 都不接触密钥，漏洞「AI 把口令
    念进聊天」从根上消失。安全档位：默认防明文落地 / 防误分享（密钥在网盘里）；
    需要严格端到端加密时另设 --passphrase，此时口令优先、通道密钥自动让位。

    create=False：只读不建。取回侧用它——v0.16 及更早的通道本来就用口令，
    不该因为升级而悄悄换钥匙（那样只会把「口令不匹配」的提示变得更难懂）。
    """
    final = key_path(root)
    try:
        with open(final, "r", encoding="utf-8") as f:
            key = f.read().strip()
        if key:
            return key
    except OSError:
        pass
    if not create:
        return None
    os.makedirs(root, exist_ok=True)
    key = base64.urlsafe_b64encode(os.urandom(32)).decode("ascii").rstrip("=")
    tmp = final + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(key)
    os.replace(tmp, final)
    return key


def key_fingerprint(key: str) -> str:
    """密钥指纹：只用于各端核对「是不是同一把钥匙」，永不打印密钥本体。"""
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:4]


def _safe_dev(device: str) -> str:
    return "".join(c if c.isalnum() or c in "._-" else "_" for c in device) or "device"


def heartbeat(root: str, store) -> Optional[str]:
    """刷新本设备心跳（v0.17）：每端只写自己的 devices/<设备>.json。

    只写自己的文件 → 无共享可变状态 → 天然零冲突（也避开了网盘生成
    「xxx (1).json」冲突副本）。init 也会触发（构造 FolderTransport 时），
    所以「设备已在通道里但从没发过包」这种隐身状态不再出现。
    """
    from .schema import local_manifest, manifest_fp

    rec = {
        "device": store.device_name,
        "platform": sys.platform,
        "last_seen": time.strftime("%Y-%m-%d %H:%M:%S"),
        "nodes": store.count_nodes(),
        "channel_id": store.channel_id or "",
        "container": manifest_fp(local_manifest(store))[:8],
    }
    d = os.path.join(root, DEVICES_DIR)
    try:
        os.makedirs(d, exist_ok=True)
        final = os.path.join(d, _safe_dev(store.device_name) + ".json")
        tmp = final + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(rec, f, ensure_ascii=False, indent=2)
        os.replace(tmp, final)
        return final
    except Exception:
        return None  # 心跳是纯元数据，失败绝不阻断同步主流程


def roster(root: str) -> List[Dict]:
    """读取通道内全部设备心跳，按最后活跃倒序（v0.17）。"""
    d = os.path.join(root, DEVICES_DIR)
    if not os.path.isdir(d):
        return []
    out: List[Dict] = []
    for fn in sorted(os.listdir(d)):
        if not fn.endswith(".json"):
            continue
        try:
            with open(os.path.join(d, fn), "r", encoding="utf-8") as f:
                rec = json.load(f)
        except (OSError, ValueError):
            continue
        if rec.get("device"):
            out.append(rec)
    out.sort(key=lambda r: r.get("last_seen", ""), reverse=True)
    return out
