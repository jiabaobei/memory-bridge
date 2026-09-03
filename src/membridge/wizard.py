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
    "     1) 坚果云（推荐主通道，全端可达：WebDAV 让网页端容器也能接）https://www.jianguoyun.com\n"
    "     2) OneDrive（Windows 自带 5GB；仅本机桌面客户端可达，适合当备胎）https://onedrive.live.com\n"
    "     3) 百度网盘同步空间（仅本机桌面客户端可达）https://pan.baidu.com\n"
    "   安装并登录后重跑 membridge init 即可自动识别。\n"
    "   ⚠️ 只同步差分包（outbox/），不要把记忆库 .db 文件放进同步文件夹。"
)

# 各网盘可达性（v0.20 文案）：决定网页端容器 / 手机平板端能不能到达这个通道宿主
REACHABILITY = {
    "坚果云": "全端可达（WebDAV）",
    "OneDrive": "仅本机桌面客户端可达",
    "百度网盘同步盘": "仅本机桌面客户端可达",
    "iCloud 云盘": "仅本机桌面客户端可达",
    "Dropbox": "仅本机桌面客户端可达",
    "Google Drive": "仅本机桌面客户端可达",
}

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


def _register_posix_autosync(out) -> None:
    """Linux / macOS 自动任务（v0.24）：与 Windows 计划任务同节奏（每 15 分钟）。

    Linux 走用户 crontab（带标记行、幂等）；macOS 写 LaunchAgent plist。
    注册不上只告警不阻塞——自动同步是锦上添花，手动 sync 永远兜底。
    """
    import shutil
    import subprocess

    exe = shutil.which("membridge") or f"{sys.executable} -m membridge"
    if sys.platform == "linux":
        cron = shutil.which("crontab")
        if not cron:
            out("   ⚠️ 无 crontab：未能注册自动任务（可手动跑 membridge autosync）")
            return
        cur = subprocess.run([cron, "-l"], capture_output=True, text=True).stdout or ""
        kept = [l for l in cur.splitlines() if "membridge-autosync" not in l]
        kept.append(f"*/15 * * * * {exe} autosync >/dev/null 2>&1  # membridge-autosync")
        r = subprocess.run([cron, "-"], input="\n".join(kept) + "\n",
                           capture_output=True, text=True)
        if r.returncode == 0:
            out("   ⏱ 自动同步 cron 已注册：每 15 分钟运行一次（重要记忆立即上云）")
        else:
            out(f"   ⚠️ cron 注册失败：{(r.stderr or r.stdout).strip()}")
    elif sys.platform == "darwin":
        plist = _home() / "Library/LaunchAgents/com.membridge.autosync.plist"
        try:
            plist.parent.mkdir(parents=True, exist_ok=True)
            plist.write_text(
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
                '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
                '<plist version="1.0"><dict>\n'
                '<key>Label</key><string>com.membridge.autosync</string>\n'
                '<key>ProgramArguments</key><array>'
                f'<string>{exe}</string><string>autosync</string></array>\n'
                '<key>StartInterval</key><integer>900</integer>\n'
                "</dict></plist>\n",
                encoding="utf-8",
            )
            subprocess.run(["launchctl", "load", str(plist)],
                           capture_output=True, text=True)
            out("   ⏱ 自动同步 LaunchAgent 已注册：每 15 分钟运行一次")
        except OSError as exc:
            out(f"   ⚠️ LaunchAgent 注册失败：{exc}")


def guided_netdisk_setup(out, ask_fn=None, secret_fn=None):
    """v0.25 第一步引导接线（交互式「提示框」）：安心文案 → 逐步配坚果云主通道
    （连接达标才继续）→ 顺问 OneDrive 备胎（可跳过）。

    返回 (通道目录, 是否稍后配置, [(provider, 远端子路径, 角色)])。
    未达标且用户选稍后：(None, True, [])——门槛留一个明确出口，不拦安装。
    """
    import getpass

    from . import netdisk_sync

    ask_fn = ask_fn or _ask
    secret_fn = secret_fn or getpass.getpass
    out("   😌 配置前三个安心点：")
    out("      · 坚果云免费版就够——同步的都是文本记忆，一年不到 1G，容量充足；")
    out("      · 配的是「应用密码」（专用钥匙）而非账户密码，随时可一键作废；")
    out("      · 配好后一切自动：每 15 分钟自动同步，零点击。")
    out("   📝 坚果云应用密码获取：坚果云网页 → 账户信息 → 安全选项 →")
    out("      第三方应用管理 → 添加应用密码（只显示一次，请复制好）。")
    chan = str(_home() / ".membridge" / "channel")
    connected: List[Tuple[str, str, str]] = []
    for _attempt in range(3):
        user = (ask_fn("坚果云账号（留空 = 稍后配置）") or "").strip()
        if not user:
            break
        secret = secret_fn("坚果云应用密码（输入时不显示）")
        if not secret:
            out("   ⚠️ 应用密码为空，再试一次")
            continue
        result = netdisk_sync.connect(chan, "membridge", provider="jianguoyun",
                                      webdav_user=user, webdav_pass=secret)
        if result.get("ok"):
            out("   ✅ 主通道连接达标：坚果云三步接线完成，继续安装")
            connected = [("jianguoyun", "membridge", "primary")]
            break
        out(f"   ⚠️ 连接未达标：{result.get('detail', '')[:200]}")
    if not connected:
        out("   ⏭ 稍后配置：继续安装（记忆仅存本机）；随时重跑 membridge init 补齐。")
        return None, True, []
    ans = (ask_fn("顺便把 OneDrive 备胎也接上？(y/n，默认 n)") or "").strip().lower()
    if ans == "y":
        out("      请在有浏览器的电脑跑 `rclone authorize \"onedrive\"`，点允许后")
        out("      把终端输出的 {\"access_token\":...} 贴过来。")
        token = (ask_fn("粘贴授权 JSON（留空 = 跳过备胎）") or "").strip()
        if token:
            r2 = netdisk_sync.connect(chan, "membridge", provider="onedrive",
                                      token=token)
            if r2.get("ok"):
                out("   ✅ 备胎接好：坚果云出问题时 OneDrive 顶上")
                connected.append(("onedrive", "membridge", "backup"))
            else:
                out(f"   ⚠️ 备胎未接（不影响主通道）：{r2.get('detail', '')[:200]}")
    return chan, False, connected


def run_init(opts: InitOptions, out=print) -> int:
    interactive = sys.stdin.isatty() if opts.interactive is None else opts.interactive

    # ── 第一步：云盘通道（强制配置；通道按项目规定自动选择，零提问）──
    out("—— 第一步：配置跨设备同步（云盘中转，必做）——")
    out("   原理：记忆先变成加密差分包放进你的云盘，任何设备都能接着上一台设备的进度。")
    out("   通道自动选择规则（规定于 RFC-001）：坚果云 > OneDrive > 百度网盘同步盘 > iCloud > Dropbox > Google Drive")
    netdisk = opts.netdisk_dir
    skipped = False
    pending: List[Tuple[str, str, str]] = []
    if opts.skip_netdisk:
        skipped = True
    elif netdisk is None:
        found = detect_sync_roots()
        if found:
            netdisk = str(Path(found[0][1]) / "membridge")
            reach = REACHABILITY.get(found[0][0], "")
            alts = "、".join(
                f"{n}（{REACHABILITY.get(n, '可达性未知')}）" for n, _ in found[1:])
            out(f"   ☁️ 自动选定：{found[0][0]}（{reach or '可达性未知'}）→ {netdisk}"
                + (f"（检测到备选：{alts}，可用 --netdisk-dir 覆盖）" if alts else ""))
        elif interactive:
            # v0.25：未检测到时走交互式引导接线——连接达标才继续安装，
            # 留「稍后配置」明确出口（门槛不拦安装）
            netdisk, skipped, pending = guided_netdisk_setup(out)
        else:
            skipped = True
            out(FREE_CLOUD_GUIDE)
    # 双网盘建议（v0.19 引入；v0.20 主备分明）：坚果云主通道 + OneDrive 备胎
    out("   🌐 双网盘建议：保持一条主通道——坚果云（WebDAV，全端可达，网页端 / "
        "手机平板 / PC 都能到达）；OneDrive 作备胎（坚果云出问题时顶上，不是淘汰）。")
    out("      网页端 AI 容器两家都能接：")
    out("      · 坚果云（主）：membridge netdisk-connect --provider jianguoyun --dir <通道目录>"
        " --webdav-user <账号> --webdav-pass <应用密码>")
    out("      · OneDrive（备）：membridge netdisk-connect --dir <通道目录>（三步：装同步工具 → 授权 → 拉取）")

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
        for prov, rpath, role in pending:  # v0.25 引导接线的各家登记
            from . import netdisk_sync

            netdisk_sync.record_state(netdisk, prov, rpath, role)

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
        elif not opts.no_autosync:
            _register_posix_autosync(out)
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
