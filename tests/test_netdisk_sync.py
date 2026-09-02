"""v0.18/v0.19 网盘三端直达测试：双网盘（OneDrive + 坚果云）接线全链路。

用临时目录里的假 rclone 脚本顶替真工具，验证命令拼装与纪律
（凭据只落盘不打印、首跑 --resync、标记文件排除出同步、按家撤销）。
"""

import json
import os
import stat
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from membridge import netdisk_sync  # noqa: E402

TOKEN = json.dumps({"access_token": "abc", "token_type": "Bearer"})


def _fake_rclone(tmp: Path, log: Path) -> Path:
    """在临时目录装一个记录参数的假 rclone（含 obscure 的确定性回声）。"""
    fake = tmp / "rclone"
    fake.write_text(
        "#!/bin/sh\n"
        f'echo "$@" >> "{log}"\n'
        'if [ "$1" = "config" ] && [ "$2" = "file" ]; then\n'
        f'  echo "Configuration file is"\n  echo "{tmp}/rclone.conf"\n'
        "  exit 0\n"
        "fi\n"
        'if [ "$1" = "obscure" ]; then\n'
        '  echo "OBS_PASSWORD"\n  exit 0\n'  # 固定混淆值：不含原密码，贴近真实行为
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


# ---------------------------------------------------------------------------
# 凭据落盘纪律
# ---------------------------------------------------------------------------

def test_onedrive_token_only_on_disk_600():
    tmp = Path(tempfile.mkdtemp())
    cfg = tmp / "rclone.conf"
    path = netdisk_sync.write_remote("onedrive", TOKEN, config_path=cfg)
    text = path.read_text(encoding="utf-8")
    assert "[membridge_od]" in text
    assert "type = onedrive" in text
    assert TOKEN in text
    assert (path.stat().st_mode & 0o777) == 0o600


def test_onedrive_write_replaces_existing_section():
    tmp = Path(tempfile.mkdtemp())
    cfg = tmp / "rclone.conf"
    netdisk_sync.write_remote("onedrive", '{"access_token": "old"}', config_path=cfg)
    netdisk_sync.write_remote("onedrive", '{"access_token": "new"}', config_path=cfg)
    text = cfg.read_text(encoding="utf-8")
    assert text.count("[membridge_od]") == 1
    assert '"access_token": "new"' in text
    assert '"old"' not in text


def test_jianguoyun_webdav_section_obscured():
    tmp, _, old_path = _with_fake_rclone()
    try:
        cfg = tmp / "rclone.conf"
        cred = json.dumps({"user": "me@example.com", "pass": "secret-123"})
        netdisk_sync.write_remote("jianguoyun", cred, config_path=cfg)
        text = cfg.read_text(encoding="utf-8")
        assert "[membridge_jgy]" in text
        assert "type = webdav" in text
        assert "url = https://dav.jianguoyun.com/dav/" in text
        assert "user = me@example.com" in text
        assert "secret-123" not in text          # 明文密码不得落盘
        assert "pass = OBS_PASSWORD" in text     # 混淆后落盘
    finally:
        _restore_path(old_path)


def test_jianguoyun_requires_user_and_pass():
    tmp = Path(tempfile.mkdtemp())
    cfg = tmp / "rclone.conf"
    try:
        netdisk_sync.write_remote("jianguoyun", '{"user": "only"}', config_path=cfg)
    except ValueError:
        pass
    else:
        raise AssertionError("缺应用密码的坚果云凭据应被拒绝")


def test_invalid_credential_rejected():
    tmp = Path(tempfile.mkdtemp())
    cfg = tmp / "rclone.conf"
    try:
        netdisk_sync.write_remote("onedrive", "not-json", config_path=cfg)
    except ValueError:
        pass
    else:
        raise AssertionError("非法凭据 JSON 应被拒绝")


def test_remove_remote_per_provider_and_all():
    tmp = Path(tempfile.mkdtemp())
    cfg = tmp / "rclone.conf"
    netdisk_sync.write_remote("onedrive", TOKEN, config_path=cfg)
    netdisk_sync.write_remote("jianguoyun",
                              json.dumps({"user": "u", "pass": "p"}), config_path=cfg)
    assert netdisk_sync.has_remote("onedrive", cfg)
    assert netdisk_sync.has_remote("jianguoyun", cfg)
    assert netdisk_sync.remove_remote("onedrive", config_path=cfg) is True
    assert not netdisk_sync.has_remote("onedrive", cfg)
    assert netdisk_sync.has_remote("jianguoyun", cfg)      # 按家撤销不殃及
    assert netdisk_sync.remove_remote(config_path=cfg) is True  # 全撤
    assert not netdisk_sync.has_remote("jianguoyun", cfg)
    assert netdisk_sync.remove_remote(config_path=cfg) is False  # 幂等


# ---------------------------------------------------------------------------
# 三步接线
# ---------------------------------------------------------------------------

def test_onedrive_connect_without_token_reports_need_token():
    tmp, _, old_path = _with_fake_rclone()
    try:
        result = netdisk_sync.connect(str(tmp / "channel"), "membridge")
        assert result["stage"] == "need-token" and result["ok"] is False
        assert "rclone authorize" in result["detail"]
    finally:
        _restore_path(old_path)


def test_jianguoyun_connect_without_credential_reports_need_credential():
    tmp, _, old_path = _with_fake_rclone()
    try:
        result = netdisk_sync.connect(str(tmp / "channel"), "membridge",
                                      provider="jianguoyun")
        assert result["stage"] == "need-credential" and result["ok"] is False
        assert "应用密码" in result["detail"]
    finally:
        _restore_path(old_path)


def test_onedrive_connect_with_token_pulls_and_finishes():
    tmp, log, old_path = _with_fake_rclone()
    try:
        local = tmp / "channel"
        result = netdisk_sync.connect(str(local), "membridge", token=TOKEN)
        assert result["stage"] == "done" and result["ok"]
        calls = log.read_text(encoding="utf-8")
        assert "copy membridge_od:membridge" in calls  # 第三步首次拉取
        assert netdisk_sync.has_remote("onedrive", tmp / "rclone.conf")
    finally:
        _restore_path(old_path)


def test_jianguoyun_connect_with_credential_pulls_and_finishes():
    tmp, log, old_path = _with_fake_rclone()
    try:
        local = tmp / "channel"
        result = netdisk_sync.connect(str(local), "membridge", provider="jianguoyun",
                                      webdav_user="me@example.com", webdav_pass="pw")
        assert result["stage"] == "done" and result["ok"]
        calls = log.read_text(encoding="utf-8")
        assert "copy membridge_jgy:membridge" in calls
        assert netdisk_sync.has_remote("jianguoyun", tmp / "rclone.conf")
    finally:
        _restore_path(old_path)


def test_connect_shortcut_with_existing_drive_dir():
    tmp = Path(tempfile.mkdtemp())
    drive = tmp / "OneDrive"
    drive.mkdir()
    result = netdisk_sync.connect(str(tmp / "channel"), "membridge", drive_dir=str(drive))
    assert result["stage"] == "done" and result["ok"]
    assert (drive / "membridge").is_dir()  # 直接指向，不需要 rclone
    assert "无需 rclone" in result["detail"]


# ---------------------------------------------------------------------------
# 双向同步
# ---------------------------------------------------------------------------

def test_bisync_first_run_resync_then_plain():
    tmp, log, old_path = _with_fake_rclone()
    try:
        local = tmp / "channel"
        local.mkdir()
        ok, detail = netdisk_sync.bisync(str(local), "membridge")
        assert ok and "OneDrive" in detail
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


def test_bisync_jianguoyun_uses_jgy_remote():
    tmp, log, old_path = _with_fake_rclone()
    try:
        local = tmp / "channel"
        local.mkdir()
        ok, detail = netdisk_sync.bisync(str(local), "membridge", provider="jianguoyun")
        assert ok and "坚果云" in detail
        assert "membridge_jgy:membridge" in log.read_text(encoding="utf-8")
    finally:
        _restore_path(old_path)


def test_status_lines_readable():
    lines = netdisk_sync.status(None)
    assert any("rclone" in line for line in lines)
    assert any("OneDrive" in line for line in lines)
    assert any("坚果云" in line for line in lines)


def test_connect_default_roles_primary_backup():
    """v0.20 主备分明：坚果云缺省 primary（主通道），OneDrive 缺省 backup（备胎）。"""
    from membridge import cli

    tmp, _, old_path = _with_fake_rclone()
    try:
        local = tmp / "channel"
        ns = type("A", (), {"dir": str(local), "remote": "membridge",
                            "provider": "jianguoyun", "role": None,
                            "paste_token": None, "webdav_user": "u@x.com",
                            "webdav_pass": "pw", "drive_dir": None,
                            "db": str(tmp / "mem.db"), "device": None})()
        assert cli.cmd_netdisk_connect(ns) == 0
        state = json.loads((local / ".membridge-netdisk.json").read_text(encoding="utf-8"))
        assert state["jianguoyun"]["role"] == "primary"

        ns2 = type("A", (), {"dir": str(local), "remote": "membridge",
                             "provider": "onedrive", "role": None,
                             "paste_token": TOKEN, "webdav_user": None,
                             "webdav_pass": None, "drive_dir": None,
                             "db": str(tmp / "mem.db"), "device": None})()
        assert cli.cmd_netdisk_connect(ns2) == 0
        state = json.loads((local / ".membridge-netdisk.json").read_text(encoding="utf-8"))
        assert state["onedrive"]["role"] == "backup"
        assert state["jianguoyun"]["role"] == "primary"  # 按家登记互不覆盖
    finally:
        _restore_path(old_path)
