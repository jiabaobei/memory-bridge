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
from .store import MemoryStore, default_db_path
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
    """识别本机已安装的同步盘及其本地同步根目录。

    v0.13：OneDrive 匹配家目录下所有 `OneDrive*` 根（OneDrive - 个人 /
    OneDrive - 公司 等）——同一个云盘在不同设备上的本地根目录名常常
    不同，但只要是同一账号同步下来的，就是同一个通道宿主。
    """
    found: List[Tuple[str, Path]] = []
    home = _home()
    for name, patterns in SYNC_DRIVE_CANDIDATES:
        if name == "OneDrive":
            try:
                hits = sorted(
                    p for p in home.iterdir()
                    if p.is_dir() and p.name.lower().startswith("onedrive")
                )
            except OSError:
                hits = []
            found.extend((name, p) for p in hits)
            continue
        for pat in patterns:
            p = Path(pat.replace("~", str(home), 1)) if pat.startswith("~") else Path(pat)
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
    no_autosync: bool = False
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

    # ── 第一步：云盘通道（强制配置；通道按项目规定自动选择，零提问）──
    out("—— 第一步：配置跨设备同步（云盘中转，必做）——")
    out("   原理：记忆先变成加密差分包放进你的云盘，任何设备都能接着上一台设备的进度。")
    out("   通道自动选择规则（规定于 RFC-001）：坚果云 > OneDrive > 百度网盘同步盘 > iCloud > Dropbox > Google Drive")
    netdisk = opts.netdisk_dir
    skipped = False
    if opts.skip_netdisk:
        skipped = True
    elif netdisk is None:
        found = detect_sync_roots()
        if found:
            netdisk = str(Path(found[0][1]) / "membridge")
            alts = "、".join(n for n, _ in found[1:])
            out(f"   ☁️ 自动选定：{found[0][0]} → {netdisk}" + (f"（检测到备选：{alts}，可用 --netdisk-dir 覆盖）" if alts else ""))
        else:
            skipped = True
            out(FREE_CLOUD_GUIDE)

    # ── 第二步：记忆库位置 ────────────────────────────────────────
    db = opts.db or default_db_path()
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

        # 通道身份（v0.13）：通道文件夹里已有 channel.json（其他设备先到）
        # → 认领同一通道；否则由本设备创建，其他设备以后自动认领。
        # 这一句保证多台设备一致指向同一个网盘通道，不再靠用户记路径。
        from . import channel as _channel

        manifest, status = _channel.ensure_channel_identity(netdisk, store)
        if status == "adopted" and manifest:
            out(f"   🔗 已加入既有通道「{manifest['channel_id']}」"
                f"（由设备「{manifest.get('creator')}」创建于 {manifest.get('created')}）")
        elif status == "created":
            out(f"   🔗 已创建通道「{store.channel_id}」——"
                "其他设备运行 membridge init 检测到这个文件夹时会自动认领")

        # 同步口令由系统自动生成并托管进本机保险库——用户无需设置、无需记住。
        # 配对新设备时用 membridge show-passphrase 查看（AI 替用户记住）。
        from .vault import load_passphrase, save_passphrase

        if load_passphrase(store) is None:
            import secrets

            save_passphrase(store, secrets.token_urlsafe(24))
            out("   🔐 同步口令已由系统自动生成并托管（你无需记住；")
            out("      以后配对新设备时，运行 membridge show-passphrase 即可查看）")
        else:
            from .vault import load_passphrase

            if load_passphrase(store) is None:
                out("   ⚠️ 尚未设置自动同步口令：交互运行 membridge init 设置一次即可全自动")

        # 注册计划任务（Windows）：每 15 分钟自动双向同步，用户零点击
        if not opts.no_autosync and os.name == "nt":
            import shutil
            import subprocess

            exe = shutil.which("membridge") or shutil.which("membridge.exe")
            cmd = f'"{exe}" autosync' if exe else f'"{sys.executable}" -m membridge autosync'
            r = subprocess.run(
                ["schtasks", "/Create", "/F", "/SC", "MINUTE", "/MO", "15",
                 "/TN", "MemoryBridge AutoSync", "/TR", cmd],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
            )
            if r.returncode == 0:
                out("   ⏱ 自动同步计划任务已注册：每 15 分钟运行一次（重要记忆立即上云）")
            else:
                out(f"   ⚠️ 计划任务注册失败：{r.stderr.strip() or r.stdout.strip()}")
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
