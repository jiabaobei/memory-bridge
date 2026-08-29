"""membridge init：一问一答向导 + `--all` 一键接入（非交互环境安全）。

流程（产品决策 2026-08-29：记忆不上云，跨设备无从谈起，云盘是第一件事）：
① 云盘通道（默认必做，自动识别已装同步盘，没有则引导免费云盘）
→ ② 记忆库位置 → ③ 设备名 → ④ 平台接入（检测到即自动配置）→ 完成摘要。
所有写入幂等，重复执行安全。
"""

from __future__ import annotations

import os
import socket
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

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

# 常见"文件夹同步型"网盘的本地同步根目录（检测到即提议作为通道宿主）
SYNC_DRIVE_CANDIDATES: List[Tuple[str, Tuple[str, ...]]] = [
    ("坚果云", ("~/我的坚果云", "~/Nutstore Files")),
    ("OneDrive", ("~/OneDrive",)),
    ("百度网盘同步盘", ("~/百度网盘同步盘", "~/BaiduSyncdisk")),
    ("iCloud 云盘", ("~/iCloudDrive", "~/iCloud Drive")),
    ("Dropbox", ("~/Dropbox",)),
    ("Google Drive", ("~/GoogleDrive", "~/Google Drive")),
]

FREE_CLOUD_GUIDE = (
    "   未检测到同步盘。任选一款免费云盘即可（按论文 §4.5 测算：单用户记忆一年仅约\n"
    "   1GB、日写入约 5MB，任何免费额度都绰绰有余）：\n"
    "     1) 坚果云（推荐，专为文件夹同步设计）https://www.jianguoyun.com\n"
    "     2) OneDrive（Windows 自带 5GB）https://onedrive.live.com\n"
    "     3) 百度网盘同步空间 https://pan.baidu.com\n"
    "   安装并登录后重跑 membridge init 即可自动识别。\n"
    "   ⚠️ 只同步差分包（outbox/），不要把记忆库 .db 文件放进同步文件夹。"
)

# 测试可注入的 HOME 覆盖（None = 真实用户目录）
HOME_DIR: Optional[Path] = None


def _home() -> Path:
    return HOME_DIR if HOME_DIR is not None else Path.home()


def detect_sync_roots() -> List[Tuple[str, Path]]:
    """识别本机已安装的同步盘及其本地同步根目录。"""
    found: List[Tuple[str, Path]] = []
    for name, patterns in SYNC_DRIVE_CANDIDATES:
        for pat in patterns:
            p = Path(pat.replace("~", str(_home()), 1)) if pat.startswith("~") else Path(pat)
            if p.is_dir():
                found.append((name, p))
                break
    return found


@dataclass
class InitOptions:
    db: Optional[str] = None
    device: Optional[str] = None
    netdisk_dir: Optional[str] = None
    skip_netdisk: bool = False
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

    # ── 第一步：云盘通道（强制配置：记忆不上云，跨设备无从谈起）────
    out("—— 第一步：配置跨设备同步（云盘中转，必做）——")
    out("   原理：记忆先变成加密差分包放进你的云盘，任何设备都能接着上一台设备的进度。")
    netdisk = opts.netdisk_dir
    skipped = False
    if opts.skip_netdisk:
        skipped = True
    elif netdisk is None:
        if interactive:
            while netdisk is None and not skipped:
                found = detect_sync_roots()
                if found:
                    listing = "、".join(f"{n}（{p}）" for n, p in found)
                    out(f"   检测到本机已装的同步盘：{listing}")
                    default_dir = str(Path(found[0][1]) / "membridge")
                    raw = _ask("   通道目录（输入 skip 强制跳过）", default_dir)
                else:
                    out(FREE_CLOUD_GUIDE)
                    raw = _ask("   已有云盘？输入其同步文件夹路径（输入 skip 强制跳过）", "")
                if raw.strip().lower() == "skip":
                    confirm = _ask("   跳过后跨设备功能不可用！再次输入 skip 确认", "")
                    if confirm.strip().lower() == "skip":
                        skipped = True
                    continue
                if raw.strip():
                    netdisk = raw.strip()
        else:
            found = detect_sync_roots()
            if found:
                netdisk = str(Path(found[0][1]) / "membridge")
                out(f"   非交互模式：自动使用检测到的 {found[0][0]} 通道：{netdisk}")
            else:
                skipped = True
                out(FREE_CLOUD_GUIDE)

    # ── 第二步：记忆库位置 ────────────────────────────────────────
    db = (
        opts.db
        or os.environ.get("MEMBRIDGE_DB")
        or str(Path.home() / ".membridge" / "memory.db")
    )
    store = MemoryStore(db)

    # ── 第三步：设备名 ────────────────────────────────────────────
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

    if netdisk:
        FolderTransport(netdisk, store)
        store.set_netdisk(netdisk)
        out(f"\n☁️ 云盘通道已配置（必做项完成）：{netdisk}")
        out(f"   outbox/ 发包、archive/ 归档=T4 云端")
        out(f"   发布：membridge publish --dir \"{netdisk}\" --passphrase 你的口令")
        out(f"   取回：membridge fetch   --dir \"{netdisk}\" --passphrase 你的口令")
        out("   ⚠️ 口令自行牢记、不要写进任何文件；新设备跑一遍 init + 同一口令即可同步")
    else:
        out("\n⚠️ 未配置云盘：记忆仅存本机，跨设备功能未启用。")
        if not opts.skip_netdisk:
            out("   强烈建议重跑 membridge init 完成云盘配置（装一款免费同步盘即可，见上方指南）。")

    out(f"\n记忆库：{db}")
    out(f"设备名：{device}（当前 {store.count_nodes()} 条记忆，{store.count_edges()} 条关联）")

    # ── 第四步：平台接入 ──────────────────────────────────────────
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

    out("\n—— 其余平台手动指南 ——")
    for c in clients.manual_guides():
        out(f"  📄 {c.name}：{c.manual}")
    out("  ℹ️ 豆包 / Kimi 等封闭 App：浏览器插件在路线图 Phase 1+；"
        "CLI 剪贴板兜底始终可用：membridge context \"<主题>\"")

    store.close()
    out("\n完成 ✅  随时可运行 membridge doctor 自检")
    return 0
