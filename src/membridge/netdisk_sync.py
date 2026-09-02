"""netdisk_sync — 网盘三端直达（v0.18.0 新增）

把 OneDrive（或任何 rclone 支持的网盘）变成同步文件夹，让
「网页端容器 / PC / 手机平板」三端都能到达同一个通道目录，兑现
各端自动双向同步。

设计约束（对齐 AGENTS.md 架构铁律）：
- 核心零依赖：只用标准库，rclone 作为外部工具经 subprocess 调用；
  本机没有 rclone 时，除 connect 的安装步骤外一切行为不受影响。
- 不改写记忆内容：本模块只搬运通道文件夹（网盘层），包级加解密、
  通道身份核对仍由 transport 层完成。
- 凭据纪律：rclone config 里的 OAuth token 只落盘（权限 600），
  永不打印、永不写进任何记忆或日志正文。

三步接线（网页端容器这类无头环境）：
  ① rclone 就位   —— 已有则复用；Linux 无头端可自动下载安装
  ② 授权          —— 用户在有浏览器的设备上跑 `rclone authorize onedrive`，
                     把得到的 token JSON 用 --paste-token 交给本端
  ③ 首次拉取      —— 把网盘里的通道文件夹拉到本机同步目录并登记

已有 OneDrive 客户端的设备（PC / Mac）不需要三步：connect 检测到
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

REMOTE_NAME = "membridge_od"
_MARKER = ".membridge-bisync-initialized"
_DOWNLOAD_URL = "https://downloads.rclone.org/rclone-current-linux-{arch}.zip"
_TIMEOUT = 120


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
    import platform
    arch = {"x86_64": "amd64", "aarch64": "arm64"}.get(platform.machine(), "amd64")
    url = _DOWNLOAD_URL.format(arch=arch)
    tmp_zip = Path(os.environ.get("TMPDIR", "/tmp")) / "rclone-install.zip"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "membridge/0.18.0"})
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


def has_remote(config_path: Optional[Path] = None) -> bool:
    cfg = Path(config_path or rclone_config_path())
    try:
        return f"[{REMOTE_NAME}]" in cfg.read_text(encoding="utf-8")
    except OSError:
        return False


def write_remote(token_json: str, config_path: Optional[Path] = None) -> Path:
    """把 OneDrive OAuth token 写入 rclone 配置的 membridge_od 段。

    token 只落盘不打印；配置文件权限收紧到 600。
    """
    json.loads(token_json)  # 校验是合法 JSON，不合法直接抛给调用方
    cfg = Path(config_path or rclone_config_path())
    cfg.parent.mkdir(parents=True, exist_ok=True)
    text = ""
    if cfg.exists():
        text = cfg.read_text(encoding="utf-8")
        # 替换既有同名段（退役旧授权）
        lines, out, skip = [], [], False
        for line in text.splitlines():
            if line.strip() == f"[{REMOTE_NAME}]":
                skip = True
                continue
            if skip and line.startswith("["):
                skip = False
            if not skip:
                out.append(line)
        text = "\n".join(out).rstrip("\n")
        if text:
            text += "\n"
    text += (
        f"\n[{REMOTE_NAME}]\n"
        f"type = onedrive\n"
        f"token = {token_json.strip()}\n"
        f"drive_type = personal\n"
    )
    cfg.write_text(text, encoding="utf-8")
    try:
        os.chmod(cfg, 0o600)
    except OSError:
        pass
    return cfg


def remove_remote(config_path: Optional[Path] = None) -> bool:
    cfg = Path(config_path or rclone_config_path())
    if not cfg.exists():
        return False
    lines = cfg.read_text(encoding="utf-8").splitlines()
    out, skip, removed = [], False, False
    for line in lines:
        if line.strip() == f"[{REMOTE_NAME}]":
            skip, removed = True, True
            continue
        if skip and line.startswith("["):
            skip = False
        if not skip:
            out.append(line)
    if removed:
        cfg.write_text("\n".join(out).rstrip("\n") + "\n", encoding="utf-8")
    return removed


# ---------------------------------------------------------------------------
# 本机云盘目录探测（PC / Mac 零配置路径）
# ---------------------------------------------------------------------------

def detect_local_drive_dirs() -> List[str]:
    """返回本机已存在的 OneDrive 同步目录候选（按平台惯例路径）。"""
    home = Path.home()
    candidates = []
    if sys.platform == "win32":
        profile = Path(os.environ.get("USERPROFILE", home))
        candidates = [profile / "OneDrive"] + sorted(profile.glob("OneDrive - *"))
    elif sys.platform == "darwin":
        candidates = sorted((home / "Library" / "CloudStorage").glob("OneDrive*")) \
            if (home / "Library" / "CloudStorage").exists() else []
    else:
        candidates = [home / "OneDrive", Path("/mnt/onedrive"), Path("/media/onedrive")]
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


def connect(local_dir: str, remote_path: str, token: Optional[str] = None,
            drive_dir: Optional[str] = None) -> dict:
    """三步接线；返回 {"stage": ..., "ok": bool, "detail": str}。

    stage=done            全部完成（或本机已有云盘目录直接指向）
    stage=need-token      走到第二步，等用户把授权 token 交进来
    """
    local = Path(local_dir).expanduser()
    local.mkdir(parents=True, exist_ok=True)

    # PC / Mac 捷径：本机已有 OneDrive 客户端目录，直接指向，不需要三步
    found = [drive_dir] if drive_dir else detect_local_drive_dirs()
    found = [d for d in found if d and Path(d).is_dir()]
    if found and not token:
        target = Path(found[0]) / remote_path
        target.mkdir(parents=True, exist_ok=True)
        return {"stage": "done", "ok": True,
                "detail": f"检测到本机云盘目录，已直接指向 {target}（无需 rclone）",
                "resolved_dir": str(target)}

    # 第一步：rclone 就位
    ok, detail = install_rclone() if not find_rclone() else (True, f"rclone 已就位：{find_rclone()}")
    if not ok:
        return {"stage": "rclone", "ok": False, "detail": detail}
    _out(f"① rclone 就位：{detail}")

    # 第二步：授权
    if not token and not has_remote():
        return {
            "stage": "need-token", "ok": False,
            "detail": (
                "② 需要授权：请在有浏览器的电脑上跑 `rclone authorize \"onedrive\"`，"
                "浏览器点允许后终端会输出一段 {\"access_token\":...}，"
                "把它交给网页端：membridge netdisk-connect --paste-token <那段JSON>"
            ),
        }
    if token:
        cfg = write_remote(token)
        _out(f"② 授权已写入 {cfg}（权限 600，不打印内容）")
    else:
        _out("② 授权已就位（沿用既有配置）")

    # 第三步：首次拉取
    proc = _run_rclone(["copy", f"{REMOTE_NAME}:{remote_path}", str(local)])
    if proc.returncode != 0:
        return {"stage": "pull", "ok": False,
                "detail": f"③ 首次拉取失败：{(proc.stderr or proc.stdout).strip()[:300]}"}
    _out(f"③ 首次拉取完成：{REMOTE_NAME}:{remote_path} → {local}")
    return {"stage": "done", "ok": True, "detail": str(local), "resolved_dir": str(local)}


def bisync(local_dir: str, remote_path: str, timeout: int = 600) -> Tuple[bool, str]:
    """文件夹级双向同步（rclone bisync）。首跑自动加 --resync 建基线。"""
    local = Path(local_dir)
    marker = local / _MARKER
    args = ["bisync", str(local), f"{REMOTE_NAME}:{remote_path}",
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
    return True, "双向同步完成"


def status(local_dir: Optional[str]) -> List[str]:
    """网盘直达体检：给出可读状态行。"""
    lines = []
    rclone = find_rclone()
    lines.append(f"rclone：{'已安装 ' + rclone if rclone else '未安装（无头端跑 netdisk-connect 会自动装）'}")
    lines.append(f"网盘授权（{REMOTE_NAME} 段）：{'已配置' if has_remote() else '未配置'}")
    drives = detect_local_drive_dirs()
    lines.append("本机云盘目录：" + ("、".join(drives) if drives else "未发现（容器/无头端属正常）"))
    if local_dir:
        marker = Path(local_dir) / _MARKER
        lines.append(f"网盘同步基线：{'已建立' if marker.exists() else '未建立（首次 netdisk-sync 自动建立）'}")
    return lines
