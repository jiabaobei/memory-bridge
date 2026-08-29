"""membridge init：一问一答向导 + `--all` 一键接入（非交互环境安全）。

流程：记忆库位置 → 设备名 → 平台接入（检测到即自动配置）→ 手动指南 →
可选网盘通道 → 完成摘要。所有写入幂等，重复执行安全。
"""

from __future__ import annotations

import os
import socket
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from . import clients
from .store import MemoryStore
from .transport import FolderTransport

STATUS_MARK = {
    "configured": "✅",
    "already": "✅",
    "not-detected": "⏭",
    "manual": "📄",
    "error": "❌",
}


@dataclass
class InitOptions:
    db: Optional[str] = None
    device: Optional[str] = None
    netdisk_dir: Optional[str] = None
    all_mode: bool = False
    interactive: Optional[bool] = None  # None = 按 stdin 是否 TTY 自动判断


def _ask(prompt: str, default: str = "") -> str:
    try:
        ans = input(f"{prompt} [{default}]: ").strip()
    except (EOFError, OSError):
        return default
    return ans or default


def run_init(opts: InitOptions, out=print) -> int:
    interactive = sys.stdin.isatty() if opts.interactive is None else opts.interactive

    # 1) 记忆库位置
    db = (
        opts.db
        or os.environ.get("MEMBRIDGE_DB")
        or str(Path.home() / ".membridge" / "memory.db")
    )
    store = MemoryStore(db)  # 顺带校验路径可写

    # 2) 设备名
    default_device = (
        opts.device
        or os.environ.get("MEMBRIDGE_DEVICE")
        or socket.gethostname()
    )
    if interactive and opts.device is None:
        device = _ask("本机设备名（会出现在记忆来源标注里）", default_device)
    else:
        device = default_device
    store.set_device(device)
    out(f"\n记忆库：{db}")
    out(f"设备名：{device}（当前 {store.count_nodes()} 条记忆，{store.count_edges()} 条关联）")

    # 3) 平台接入：检测到即自动配置（幂等）；交互模式下逐个确认
    out("\n—— 平台接入 ——")
    for c in clients.registry():
        if c.tier == "manual":
            continue
        if not c.detect():
            out(f"  ⏭ {c.name}：未安装，跳过")
            continue
        if interactive and not opts.all_mode:
            try:
                ans = input(f"  接入 {c.name}? [Y/n]: ").strip().lower()
            except (EOFError, OSError):
                ans = ""
            if ans == "n":
                out(f"  ⏭ {c.name}：按你的选择跳过")
                continue
        r = c.configure(db, device)
        out(f"  {STATUS_MARK.get(r.status, '?')} {c.name}：{r.detail}")

    # 4) 手动指南（--all 或始终展示，保持指南可见）
    out("\n—— 其余平台手动指南 ——")
    for c in clients.manual_guides():
        out(f"  📄 {c.name}：{c.manual}")
    out("  ℹ️ 豆包 / Kimi 等封闭 App：浏览器插件在路线图 Phase 1+；"
        "CLI 剪贴板兜底始终可用：membridge context \"<主题>\"")

    # 5) 网盘通道（灵魂功能，可选）
    netdisk = opts.netdisk_dir
    if netdisk is None and interactive and not opts.all_mode:
        try:
            ans = input("\n现在配置跨设备同步（网盘中转）? [y/N]: ").strip().lower()
        except (EOFError, OSError):
            ans = ""
        if ans == "y":
            netdisk = _ask("同步文件夹路径（网盘同步盘内，如 D:\\百度网盘同步盘\\membridge）")
    if netdisk:
        FolderTransport(netdisk, store)
        out(f"\n☁️ 网盘通道就绪：{netdisk}")
        out(f"   发布：membridge publish --dir \"{netdisk}\" --passphrase 你的口令")
        out(f"   取回：membridge fetch   --dir \"{netdisk}\" --passphrase 你的口令")
        out("   ⚠️ 口令自行牢记、不要写进任何文件；新设备跑一遍 init + 同一口令即可同步")

    store.close()
    out("\n完成 ✅  随时可运行 membridge doctor 自检")
    return 0
