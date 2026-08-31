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

import json
import os
import time
import uuid
from typing import Dict, List, Optional, Tuple

CHANNEL_FILE = "channel.json"


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
