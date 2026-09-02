"""v0.18 网盘三端直达测试：rclone 探测 / 授权落盘 / 三步接线 / 双向基线。

用临时目录里的假 rclone 脚本顶替真工具，验证命令拼装与纪律
（授权只落盘不打印、首跑 --resync、标记文件排除出同步）。
"""

import json
import os
import stat
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from membridge import netdisk_sync  # noqa: E402


def _fake_rclone(tmp: Path, log: Path) -> Path:
    """在临时目录装一个记录参数的假 rclone。"""
    fake = tmp / "rclone"
    fake.write_text(
        "#!/bin/sh\n"
        f'echo "$@" >> "{log}"\n'
        'if [ "$1" = "config" ] && [ "$2" = "file" ]; then\n'
        f'  echo "Configuration file is"\n  echo "{tmp}/rclone.conf"\n'
        "  exit 0\n"
        "fi\n"
        "exit 0\n",
        encoding="utf-8",
    )
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return fake


def _with_fake_rclone():
    tmp = Path(tempfile.mkdtemp())
    log = tmp / "calls.log"
    _fake_rclone(tmp, log)
    old_path = os.environ.get("PATH", "")
    os.environ["PATH"] = str(tmp) + os.pathsep + old_path
    return tmp, log, old_path


def _restore_path(old_path: str) -> None:
    os.environ["PATH"] = old_path


def test_write_remote_token_only_on_disk_600():
    tmp = Path(tempfile.mkdtemp())
    cfg = tmp / "rclone.conf"
    token = json.dumps({"access_token": "abc", "token_type": "Bearer"})
    path = netdisk_sync.write_remote(token, config_path=cfg)
    text = path.read_text(encoding="utf-8")
    assert f"[{netdisk_sync.REMOTE_NAME}]" in text
    assert "type = onedrive" in text
    assert token in text
    assert (path.stat().st_mode & 0o777) == 0o600


def test_write_remote_replaces_existing_section():
    tmp = Path(tempfile.mkdtemp())
    cfg = tmp / "rclone.conf"
    netdisk_sync.write_remote('{"access_token": "old"}', config_path=cfg)
    netdisk_sync.write_remote('{"access_token": "new"}', config_path=cfg)
    text = cfg.read_text(encoding="utf-8")
    assert text.count(f"[{netdisk_sync.REMOTE_NAME}]") == 1
    assert '"access_token": "new"' in text
    assert '"old"' not in text


def test_write_remote_rejects_invalid_token():
    tmp = Path(tempfile.mkdtemp())
    cfg = tmp / "rclone.conf"
    try:
        netdisk_sync.write_remote("not-json", config_path=cfg)
    except ValueError:
        pass
    else:
        raise AssertionError("非法 token JSON 应被拒绝")


def test_remove_remote():
    tmp = Path(tempfile.mkdtemp())
    cfg = tmp / "rclone.conf"
    netdisk_sync.write_remote('{"access_token": "x"}', config_path=cfg)
    assert netdisk_sync.has_remote(cfg)
    assert netdisk_sync.remove_remote(cfg) is True
    assert not netdisk_sync.has_remote(cfg)
    assert netdisk_sync.remove_remote(cfg) is False  # 幂等


def test_connect_without_token_reports_need_token():
    tmp, _, old_path = _with_fake_rclone()
    try:
        local = tmp / "channel"
        result = netdisk_sync.connect(str(local), "membridge", token=None)
        assert result["stage"] == "need-token"
        assert result["ok"] is False
        assert "rclone authorize" in result["detail"]
    finally:
        _restore_path(old_path)


def test_connect_with_token_pulls_and_finishes():
    tmp, log, old_path = _with_fake_rclone()
    try:
        local = tmp / "channel"
        token = json.dumps({"access_token": "t", "token_type": "Bearer"})
        result = netdisk_sync.connect(str(local), "membridge", token=token)
        assert result["stage"] == "done" and result["ok"]
        calls = log.read_text(encoding="utf-8")
        assert "copy membridge_od:membridge" in calls  # 第三步首次拉取
        assert netdisk_sync.has_remote(tmp / "rclone.conf")
    finally:
        _restore_path(old_path)


def test_connect_shortcut_with_existing_drive_dir():
    tmp = Path(tempfile.mkdtemp())
    drive = tmp / "OneDrive"
    drive.mkdir()
    local = tmp / "channel"
    result = netdisk_sync.connect(str(local), "membridge", drive_dir=str(drive))
    assert result["stage"] == "done" and result["ok"]
    assert (drive / "membridge").is_dir()  # 直接指向，不需要 rclone
    assert "无需 rclone" in result["detail"]


def test_bisync_first_run_resync_then_plain():
    tmp, log, old_path = _with_fake_rclone()
    try:
        local = tmp / "channel"
        local.mkdir()
        ok, _ = netdisk_sync.bisync(str(local), "membridge")
        assert ok
        first = log.read_text(encoding="utf-8").splitlines()[-1]
        assert "--resync" in first
        assert netdisk_sync._MARKER in first  # 标记与心跳目录不入同步
        assert "devices/**" in first
        ok2, _ = netdisk_sync.bisync(str(local), "membridge")
        assert ok2
        second = log.read_text(encoding="utf-8").splitlines()[-1]
        assert "--resync" not in second  # 基线已建立
        assert (local / netdisk_sync._MARKER).exists()
    finally:
        _restore_path(old_path)


def test_status_lines_readable():
    lines = netdisk_sync.status(None)
    assert any("rclone" in line for line in lines)
    assert any("授权" in line for line in lines)
