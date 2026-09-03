"""netdisk_sync — 网盘三端直达（v0.18.0 新增；v0.19.0 双网盘：OneDrive + 坚果云）

把网盘变成同步文件夹，让「网页端容器 / PC / 手机平板」三端都能到达
同一个通道目录，兑现各端自动双向同步。支持两家网盘，建议两个都配：

- **OneDrive**（默认主通道）：OAuth 授权，token 经 --paste-token 交入；
- **坚果云**：WebDAV + 应用密码，无浏览器往返，天然适合网页端容器与
  手机平板端 ↔ PC 端的共享桥。

设计约束（对齐 AGENTS.md 架构铁律）：
- 核心零依赖：只用标准库，rclone 作为外部工具经 subprocess 调用；
  本机没有 rclone 时，除 connect 的安装步骤外一切行为不受影响。
- 不改写记忆内容：本模块只搬运通道文件夹（网盘层），包级加解密、
  通道身份核对仍由 transport 层完成。
- 凭据纪律：OAuth token / 应用密码只落盘（rclone 配置，权限 600，
  密码先经 `rclone obscure` 混淆），永不打印、永不写进任何记忆或日志。

三步接线（网页端容器这类无头环境）：
  ① rclone 就位   —— 已有则复用；Linux 无头端可自动下载安装
  ② 授权          —— OneDrive：有浏览器的设备跑 `rclone authorize onedrive`，
                     token 经 --paste-token 交入；
                     坚果云：网页「安全设置 → 第三方应用管理」建应用密码，
                     账号 + 密码经 --webdav-user / --webdav-pass 交入
  ③ 首次拉取      —— 把网盘里的通道文件夹拉到本机同步目录并登记

已有网盘客户端的设备（PC / Mac）不需要三步：connect 检测到
本机云盘目录后直接指向它，零配置。
"""

import json
import os
import shutil
import stat
import subprocess
import sys
import urllib.request
from pathlib import Path
from typing import List, Optional, Tuple

_MARKER = ".membridge-bisync-initialized"
_DOWNLOAD_URL = "https://downloads.rclone.org/rclone-current-linux-{arch}.zip"
_TIMEOUT = 120

# 双网盘档案：remote 名是各端约定（同一网盘各端必须一致）
PROVIDERS = {
    "onedrive": {
        "remote": "membridge_od",
        "label": "OneDrive",
    },
    "jianguoyun": {
        "remote": "membridge_jgy",
        "label": "坚果云",
        "webdav_url": "https://dav.jianguoyun.com/dav/",
    },
}
# v0.18 兼容：未注明 provider 的旧接线状态按 OneDrive 处理
LEGACY_PROVIDER = "onedrive"


def _provider(name: Optional[str]) -> dict:
    p = PROVIDERS.get(name or LEGACY_PROVIDER)
    if not p:
        raise ValueError(f"未知网盘：{name}（可选：{'/'.join(PROVIDERS)}）")
    return p


def _out(msg: str) -> None:
    print(msg)


# ---------------------------------------------------------------------------
# rclone 就位（第一步）
# ---------------------------------------------------------------------------

def find_rclone() -> Optional[str]:
    """返回 rclone 可执行文件路径；未安装返回 None。"""
    return shutil.which("rclone")


def install_rclone() -> Tuple[bool, str]:
    """Linux 无头端自动安装 rclone 到 /usr/local/bin（无权限则 ~/.local/bin）。

    其他平台引导手动安装（官网包管理器渠道更可靠）。
    返回 (是否成功, 说明)。
    """
    if find_rclone():
        return True, f"rclone 已就位：{find_rclone()}"
    if sys.platform not in ("linux",):
        return False, "请到 https://rclone.org/install/ 按系统指引安装 rclone 后重试"
    # 优先系统包管理器（容器环境里官方下载通道常不可达；apt 源的旧版由
    # bisync 的双向复制降级兜底，功能不缺）
    if shutil.which("apt-get"):
        try:
            proc = subprocess.run(["apt-get", "install", "-y", "rclone"],
                                  capture_output=True, text=True, timeout=600)
            if proc.returncode == 0 and find_rclone():
                return True, f"rclone 经系统包管理器安装：{find_rclone()}"
        except (subprocess.SubprocessError, OSError):
            pass
    import platform
    arch = {"x86_64": "amd64", "aarch64": "arm64"}.get(platform.machine(), "amd64")
    url = _DOWNLOAD_URL.format(arch=arch)
    tmp_zip = Path(os.environ.get("TMPDIR", "/tmp")) / "rclone-install.zip"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "membridge/0.22.0"})
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            tmp_zip.write_bytes(resp.read())
        import zipfile
        with zipfile.ZipFile(tmp_zip) as zf:
            names = [n for n in zf.namelist() if n.endswith("/rclone")]
            if not names:
                return False, "下载的压缩包里没找到 rclone 可执行文件"
            zf.extract(names[0], tmp_zip.parent)
            binary = tmp_zip.parent / names[0]
    except Exception as exc:  # noqa: BLE001 — 安装失败必须给出可读原因
        return False, f"下载或解压 rclone 失败：{exc}"
    finally:
        tmp_zip.unlink(missing_ok=True)
    for dest in (Path("/usr/local/bin/rclone"), Path.home() / ".local" / "bin" / "rclone"):
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(binary, dest)
            dest.chmod(dest.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
            binary.unlink(missing_ok=True)
            if shutil.which("rclone"):
                return True, f"rclone 已安装：{shutil.which('rclone')}"
        except OSError:
            continue
    binary.unlink(missing_ok=True)
    return False, "rclone 已下载但无写入目录权限，请手动放入 PATH"


# ---------------------------------------------------------------------------
# rclone 配置（第二步的落盘部分）
# ---------------------------------------------------------------------------

def rclone_config_path() -> Path:
    """解析 `rclone config file` 输出拿配置路径；拿不到用默认位置。"""
    rclone = find_rclone()
    if rclone:
        try:
            out = subprocess.run(
                [rclone, "config", "file"], capture_output=True, text=True, timeout=30
            ).stdout
            for line in out.splitlines():
                line = line.strip()
                if line and not line.startswith("Configuration file is"):
                    return Path(line)
        except (subprocess.SubprocessError, OSError):
            pass
    return Path.home() / ".config" / "rclone" / "rclone.conf"


def _rewrite_config(cfg: Path, transform) -> None:
    text = cfg.read_text(encoding="utf-8") if cfg.exists() else ""
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text(transform(text), encoding="utf-8")
    try:
        os.chmod(cfg, 0o600)
    except OSError:
        pass


def _drop_section(text: str, remote: str) -> str:
    lines, out, skip = [], [], False
    for line in text.splitlines():
        if line.strip() == f"[{remote}]":
            skip = True
            continue
        if skip and line.startswith("["):
            skip = False
        if not skip:
            out.append(line)
    body = "\n".join(out).rstrip("\n")
    return body + "\n" if body else ""


def has_remote(provider: Optional[str] = None, config_path: Optional[Path] = None) -> bool:
    remote = _provider(provider)["remote"]
    cfg = Path(config_path or rclone_config_path())
    try:
        return f"[{remote}]" in cfg.read_text(encoding="utf-8")
    except OSError:
        return False


def _obscure(password: str) -> str:
    """rclone 要求 WebDAV 密码以混淆形式落盘；拿不到 rclone 时原样返回。"""
    rclone = find_rclone()
    if not rclone:
        return password
    try:
        proc = subprocess.run([rclone, "obscure", password],
                              capture_output=True, text=True, timeout=30)
        return proc.stdout.strip() or password
    except (subprocess.SubprocessError, OSError):
        return password


def write_remote(provider: str, credential: str, config_path: Optional[Path] = None) -> Path:
    """把网盘凭据写入 rclone 配置对应段；凭据只落盘不打印，文件权限 600。

    - onedrive：credential 为 OAuth token JSON（校验合法性）
    - jianguoyun：credential 为 JSON {"user": 账号, "pass": 应用密码}
      （密码先经 `rclone obscure` 混淆再落盘）
    """
    p = _provider(provider)
    data = json.loads(credential)  # 不合法直接抛给调用方
    if provider == "jianguoyun":
        if not data.get("user") or not data.get("pass"):
            raise ValueError("坚果云凭据需包含 user（账号）与 pass（应用密码）")
        section = (
            f"\n[{p['remote']}]\n"
            f"type = webdav\n"
            f"url = {p['webdav_url']}\n"
            f"vendor = other\n"
            f"user = {data['user']}\n"
            f"pass = {_obscure(data['pass'])}\n"
        )
    else:
        section = (
            f"\n[{p['remote']}]\n"
            f"type = onedrive\n"
            f"token = {credential.strip()}\n"
            f"drive_type = personal\n"
        )
    cfg = Path(config_path or rclone_config_path())

    def transform(text: str) -> str:
        return _drop_section(text, p["remote"]).rstrip("\n") + section

    _rewrite_config(cfg, transform)
    return cfg


def remove_remote(provider: Optional[str] = None, config_path: Optional[Path] = None) -> bool:
    """删除某家网盘的授权段；不指定则两家都删。返回是否有删除。"""
    targets = ([provider] if provider else list(PROVIDERS))
    cfg = Path(config_path or rclone_config_path())
    if not cfg.exists():
        return False
    removed = False

    def transform(text: str) -> str:
        nonlocal removed
        for name in targets:
            remote = _provider(name)["remote"]
            if f"[{remote}]" in text:
                removed = True
                text = _drop_section(text, remote)
        return text

    _rewrite_config(cfg, transform)
    return removed


# ---------------------------------------------------------------------------
# 本机云盘目录探测（PC / Mac 零配置路径）
# ---------------------------------------------------------------------------

def detect_local_drive_dirs() -> List[str]:
    """返回本机已存在的 OneDrive / 坚果云同步目录候选（按平台惯例路径）。"""
    home = Path.home()
    candidates = []
    if sys.platform == "win32":
        profile = Path(os.environ.get("USERPROFILE", home))
        candidates = ([profile / "OneDrive"] + sorted(profile.glob("OneDrive - *"))
                      + [profile / "坚果云同步盘"] + sorted(profile.glob("Nutstore*")))
    elif sys.platform == "darwin":
        cloud = home / "Library" / "CloudStorage"
        if cloud.exists():
            candidates = sorted(cloud.glob("OneDrive*")) + sorted(cloud.glob("Nutstore*"))
    else:
        candidates = [home / "OneDrive", home / "Nutstore",
                      Path("/mnt/onedrive"), Path("/media/onedrive")]
    return [str(p) for p in candidates if p.is_dir()]


# ---------------------------------------------------------------------------
# 三步接线
# ---------------------------------------------------------------------------

def _run_rclone(args: List[str], timeout: int = 600) -> subprocess.CompletedProcess:
    rclone = find_rclone()
    if not rclone:
        raise RuntimeError("rclone 未安装")
    return subprocess.run(
        [rclone] + args, capture_output=True, text=True, timeout=timeout
    )


def connect(local_dir: str, remote_path: str, provider: str = "onedrive",
            token: Optional[str] = None, webdav_user: Optional[str] = None,
            webdav_pass: Optional[str] = None, drive_dir: Optional[str] = None) -> dict:
    """三步接线；返回 {"stage": ..., "ok": bool, "detail": str}。

    stage=done             全部完成（或本机已有云盘目录直接指向）
    stage=need-token       OneDrive 走到第二步，等授权 token
    stage=need-credential  坚果云走到第二步，等账号 + 应用密码
    """
    p = _provider(provider)
    local = Path(local_dir).expanduser()
    local.mkdir(parents=True, exist_ok=True)

    # PC / Mac 捷径：本机已有网盘客户端目录，直接指向，不需要三步
    found = [drive_dir] if drive_dir else detect_local_drive_dirs()
    found = [d for d in found if d and Path(d).is_dir()]
    if found and not token and not webdav_user:
        target = Path(found[0]) / remote_path
        target.mkdir(parents=True, exist_ok=True)
        return {"stage": "done", "ok": True, "provider": provider,
                "detail": f"检测到本机云盘目录，已直接指向 {target}（无需 rclone）",
                "resolved_dir": str(target)}

    # 第一步：rclone 就位
    ok, detail = install_rclone() if not find_rclone() else (True, f"rclone 已就位：{find_rclone()}")
    if not ok:
        return {"stage": "rclone", "ok": False, "provider": provider, "detail": detail}
    _out(f"① rclone 就位：{detail}")

    # 第二步：授权
    credential = None
    if provider == "jianguoyun":
        if webdav_user and webdav_pass:
            credential = json.dumps({"user": webdav_user, "pass": webdav_pass},
                                    ensure_ascii=False)
        elif not has_remote("jianguoyun"):
            return {
                "stage": "need-credential", "ok": False, "provider": provider,
                "detail": (
                    "② 需要坚果云应用密码：登录坚果云网页 → 账户信息 → 安全选项 → "
                    "第三方应用管理 → 添加应用，把生成的应用密码交给网页端："
                    "membridge netdisk-connect --provider jianguoyun "
                    "--webdav-user <账号> --webdav-pass <应用密码>"
                ),
            }
    else:
        if token:
            credential = token
        elif not has_remote("onedrive"):
            return {
                "stage": "need-token", "ok": False, "provider": provider,
                "detail": (
                    "② 需要授权：请在有浏览器的电脑上跑 `rclone authorize \"onedrive\"`，"
                    "浏览器点允许后终端会输出一段 {\"access_token\":...}，"
                    "把它交给网页端：membridge netdisk-connect --paste-token <那段JSON>"
                ),
            }
    if credential:
        cfg = write_remote(provider, credential)
        _out(f"② 授权已写入 {cfg}（权限 600，不打印内容）")
    else:
        _out("② 授权已就位（沿用既有配置）")

    # 第三步：首次拉取
    proc = _run_rclone(["copy", f"{p['remote']}:{remote_path}", str(local)])
    if proc.returncode != 0:
        return {"stage": "pull", "ok": False, "provider": provider,
                "detail": f"③ 首次拉取失败：{(proc.stderr or proc.stdout).strip()[:300]}"}
    _out(f"③ 首次拉取完成：{p['remote']}:{remote_path} → {local}")
    return {"stage": "done", "ok": True, "provider": provider,
            "detail": str(local), "resolved_dir": str(local)}


def _rclone_has_bisync() -> bool:
    """bisync 需要 rclone ≥1.58；旧版返回 False 走双向复制降级。"""
    try:
        proc = _run_rclone(["bisync", "--help"], timeout=30)
        return proc.returncode == 0
    except (RuntimeError, subprocess.SubprocessError):
        return False


def bisync(local_dir: str, remote_path: str, provider: str = "onedrive",
           timeout: int = 600) -> Tuple[bool, str]:
    """文件夹级双向同步（rclone bisync）。首跑自动加 --resync 建基线。

    旧版 rclone（<1.58，无 bisync）降级为双向复制：通道目录是 append-only
    （差分包只增不删），双向复制与并集同步等价，不会误删文件。
    """
    p = _provider(provider)
    local = Path(local_dir)
    marker = local / _MARKER
    remote = f"{p['remote']}:{remote_path}"
    if not _rclone_has_bisync():
        excludes = ["--exclude", _MARKER, "--exclude", "devices/**"]
        for src, dst in ((remote, str(local)), (str(local), remote)):  # 先取后推
            proc = _run_rclone(["copy", src, dst] + excludes, timeout=timeout)
            if proc.returncode != 0:
                return False, (proc.stderr or proc.stdout).strip()[:300]
        if not marker.exists():
            local.mkdir(parents=True, exist_ok=True)
            marker.write_text("bisync baseline", encoding="utf-8")
        return True, f"{p['label']} 双向同步完成（旧版 rclone，双向复制兜底）"
    args = ["bisync", str(local), remote,
            "--exclude", _MARKER, "--exclude", "devices/**"]
    if not marker.exists():
        args.append("--resync")
    try:
        proc = _run_rclone(args, timeout=timeout)
    except (RuntimeError, subprocess.SubprocessError) as exc:
        return False, str(exc)
    if proc.returncode != 0:
        return False, (proc.stderr or proc.stdout).strip()[:300]
    if not marker.exists():
        local.mkdir(parents=True, exist_ok=True)
        marker.write_text("bisync baseline", encoding="utf-8")
    return True, f"{p['label']} 双向同步完成"


def inside_drive_dir(local_dir: str, drives: Optional[List[str]] = None) -> Optional[str]:
    """通道目录是否落在本机某个云盘客户端同步目录内（v0.22）。

    落在其中 = 本机网盘客户端已经在同步它了，无需 rclone、也无需接线。
    此前体检只看 rclone 授权段，PC 这类装了客户端的机器会被误报成「未接线」。
    """
    try:
        target = Path(local_dir).resolve()
    except OSError:
        return None
    for d in (drives if drives is not None else detect_local_drive_dirs()):
        try:
            target.relative_to(Path(d).resolve())
            return d
        except (OSError, ValueError):
            continue
    return None


def status(local_dir: Optional[str]) -> List[str]:
    """网盘直达体检：给出可读状态行（两家网盘分开报）。"""
    lines = []
    rclone = find_rclone()
    lines.append(f"rclone：{'已安装 ' + rclone if rclone else '未安装（无头端跑 netdisk-connect 会自动装）'}")
    for name, p in PROVIDERS.items():
        lines.append(f"{p['label']}授权（{p['remote']} 段）：{'已配置' if has_remote(name) else '未配置'}")
    drives = detect_local_drive_dirs()
    lines.append("本机云盘目录：" + ("、".join(drives) if drives else "未发现（容器/无头端属正常）"))
    if local_dir:
        marker = Path(local_dir) / _MARKER
        lines.append(f"网盘同步基线：{'已建立' if marker.exists() else '未建立（首次 netdisk-sync 自动建立）'}")
        inside = inside_drive_dir(local_dir, drives)
        if inside:
            lines.append(f"✅ 通道目录在「{inside}」的客户端同步范围内"
                         f"——桌面客户端直连，无需 rclone 接线")
    return lines
