"""自动同步引擎：按记忆重要程度自动上云 + 自动取回（v0.5.0，用户零点击）。

重要程度规则（在项目里规定死，见 RFC-001）：
- 重要记忆 = confidence ≥ 0.8，或被访问 ≥ 2 次，或带 important/重要 标签
  → **立即上云**
- 普通记忆 → 攒够 5 条，或距上次发布 ≥ 24 小时，才批量上云
- migration=local 的记忆 **永不上云**（PAMS L1，优先级高于一切）

入口：membridge autosync（由 init 注册的 Windows 计划任务每 15 分钟调用；
也可手动运行）。口令来自口令保险库（vault：Windows 走 DPAPI，Linux / macOS
走文件保险库，均绑定本机用户账户），用户无需再输入。
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from . import dss
from . import channel as _channel
from .dss import Delta
from .embeddings import HashingEmbedder, embedder_identity
from .node import MemoryNode
from .store import MemoryStore, default_db_path
from .transport import FolderTransport
from .vault import load_passphrase

IMPORTANT_CONFIDENCE = 0.8
IMPORTANT_ACCESS = 2
IMPORTANT_TAGS = ("important", "重要")
ROUTINE_BATCH = 5
ROUTINE_MAX_DELAY_HOURS = 24.0
LAST_PUBLISH_KEY = "last_publish_at"


def is_important(node) -> bool:
    if node.migration == "local":
        return False
    if node.confidence >= IMPORTANT_CONFIDENCE:
        return True
    if node.access_count >= IMPORTANT_ACCESS:
        return True
    return any(t.lower() in IMPORTANT_TAGS for t in node.tags)


def _split_by_importance(delta: Delta) -> Tuple[List[Dict], List[Dict]]:
    important, routine = [], []
    for n in delta.nodes:
        node = MemoryNode.from_dict(n) if isinstance(n, dict) else n
        (important if is_important(node) else routine).append(n)
    return important, routine


def _filter_edges(delta: Delta, node_ids: set) -> List:
    return [e for e in delta.edges if e[0] in node_ids and e[1] in node_ids]


def _hours_since_last_publish(store: MemoryStore) -> float:
    raw = store._get_meta(LAST_PUBLISH_KEY)
    if not raw:
        return float("inf")
    return (time.time() - float(raw)) / 3600.0


def _folder_round(netdisk: str, out) -> None:
    """v0.24：文件夹级双向并入自动循环。

    rclone 接线的机器先对齐文件夹再跑包级；本机有云盘客户端的机器没有
    授权段（has_remote 为假）静默跳过——客户端自己维持文件夹同步。
    """
    from . import netdisk_sync

    try:
        state = json.loads(
            (Path(netdisk) / ".membridge-netdisk.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    if isinstance(state, dict) and "remote_path" in state:  # v0.18 旧格式兼容
        state = {"onedrive": state}
    for provider in sorted(
            state or {},
            key=lambda k: 0 if (state[k] or {}).get("role") == "primary" else 1):
        conf = state[provider] or {}
        if not netdisk_sync.has_remote(provider):
            continue
        _ok, detail = netdisk_sync.bisync(
            netdisk, conf.get("remote_path", "membridge"), provider=provider)
        out(f"网盘双向：{detail}")


def run_autosync(store_path: Optional[str] = None, passphrase: Optional[str] = None,
                 out=print) -> int:
    store = MemoryStore(store_path or default_db_path())
    netdisk = store.netdisk
    if not netdisk:
        out("⚠️ 尚未配置云盘通道：请先运行 membridge init")
        return 2
    _folder_round(netdisk, out)
    pass_ = (
        passphrase
        or os.environ.get("MEMBRIDGE_PASSPHRASE")
        or load_passphrase(store)
        # v0.17：与 CLI 同一条回落链。否则自动任务用保险库口令、手动 sync 用
        # 通道密钥，同一台设备会同时往一条通道里发两种钥匙的包——又是一次静默分裂
        or _channel.ensure_key(netdisk)
    )
    if not pass_:
        out("⚠️ 尚未设置自动同步口令：请运行 membridge init 一次性设置")
        return 2

    tr = FolderTransport(netdisk, store)
    delta = dss.delta_unsent(
        store, tr._published_fps(), embedder_info=embedder_identity(HashingEmbedder())
    )
    published = 0
    if delta.nodes:
        important, routine = _split_by_importance(delta)
        last_h = _hours_since_last_publish(store)
        if important:
            out(f"检测到 {len(important)} 条重要记忆：立即上云")
            chosen_ids = {n["node_id"] for n in important}
            pkg = Delta(
                from_device=delta.from_device, to_device=delta.to_device,
                nodes=important, edges=_filter_edges(delta, chosen_ids),
                embedder=delta.embedder,
            )
            path = tr.publish(passphrase=pass_, delta=pkg)
            published += 1 if path else 0
        elif len(routine) >= ROUTINE_BATCH or last_h >= ROUTINE_MAX_DELAY_HOURS:
            out(f"普通记忆 {len(routine)} 条，达到批量条件（≥{ROUTINE_BATCH} 条或 ≥24h）：批量上云")
            path = tr.publish(passphrase=pass_, delta=delta)
            published += 1 if path else 0
        else:
            out(f"普通记忆 {len(routine)} 条未达批量条件（≥{ROUTINE_BATCH} 条或 ≥24h），暂缓")
    else:
        out("没有需要发布的新记忆")

    result = tr.fetch(passphrase=pass_)
    for fn, src, r in result["applied"]:
        if r.get("rejected"):
            out(f"⚠️ 拒绝来自 {src} 的差分包：嵌入器不一致（见 RFC §4）")
            continue
        out(f"已取回 {src} 的记忆：新增 {r['nodes_added']} 条")
    if tr.channel_status == "mismatch":
        out("⚠️ 通道身份不一致：本机通道 ID 与云盘身份证（channel.json）不符，"
            "疑似与其他设备分裂到了不同通道——运行 membridge channel 查看")
    out(f"自动同步完成（发布 {published} 个差分包）")
    with store.transaction():
        store._set_meta(LAST_PUBLISH_KEY, str(time.time()))
    store.close()
    return 0
