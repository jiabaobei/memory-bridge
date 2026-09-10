"""v0.27：通道接线描述（只写一次 + 凭据加密）与接线状态改存本机。

刻意不依赖 rclone / schtasks——这两样在本机沙箱里跑不起来，而本次改动的
要害（凭据绝不明文落地、描述只写一次、状态不再写进共享网盘、两份探测同源）
恰好都能用纯文件验证。
"""

import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from membridge import channel, netdisk_sync, wizard  # noqa: E402

PW = "应用密码-绝不该出现在明文里"
USER = "u@x.com"


def _chan():
    return tempfile.mkdtemp(prefix="mb-wire-chan-")


def test_wiring_roundtrip_and_never_plaintext():
    """凭据整块加密：文件明文里既没有密码也没有账号。"""
    chan = _chan()
    entries = {"jianguoyun": netdisk_sync.wiring_entry(
        "jianguoyun", "membridge", "primary", webdav_user=USER, webdav_pass=PW)}
    path, status = channel.write_wiring(chan, entries, PW, device="PC-A",
                                        channel_id="mb-abc")
    assert status == "created" and path

    raw = Path(path).read_text(encoding="utf-8")
    assert PW not in raw and USER not in raw

    got = channel.read_wiring(chan, PW)
    assert got["status"] == "ok"
    assert got["entries"]["jianguoyun"]["webdav_pass"] == PW
    assert got["meta"]["written_by"] == "PC-A"

    # 拿不到钥匙/钥匙不对 → 明说 locked，绝不假装「没有描述」
    assert channel.read_wiring(chan)["status"] == "locked"
    assert channel.read_wiring(chan, "错口令")["status"] == "locked"


def test_wiring_is_write_once_first_writer_wins():
    """只写一次：别的设备只读不改——共享可写状态正是铁律要防的东西。"""
    chan = _chan()
    channel.write_wiring(chan, {"jianguoyun": {"remote_path": "membridge"}},
                         PW, device="PC-A")
    _p, status = channel.write_wiring(chan, {"onedrive": {"x": 1}}, PW,
                                      device="PC-B")
    assert status == "skipped"
    assert set(channel.read_wiring(chan, PW)["entries"]) == {"jianguoyun"}

    # 写者本人可补写（本机再接一家）
    _p, status = channel.write_wiring(
        chan, {"jianguoyun": {"remote_path": "membridge"},
               "onedrive": {"remote_path": "membridge"}}, PW, device="PC-A")
    assert status == "updated"


def test_wiring_never_writes_without_key():
    """拿不到钥匙就宁可不写——绝不落明文凭据。"""
    chan = _chan()
    path, status = channel.write_wiring(chan, {"jianguoyun": {"x": 1}}, None,
                                        device="PC-A")
    assert path is None and status == "nocrypto"
    assert not os.path.exists(channel.wiring_path(chan))


def test_share_wiring_merges_then_reports_readonly():
    chan = _chan()
    _s, note = netdisk_sync.share_wiring(
        chan, {"jianguoyun": {"remote_path": "membridge"}}, device="PC-A",
        passphrase=PW)
    assert "已写入通道" in note
    _s, note2 = netdisk_sync.share_wiring(
        chan, {"onedrive": {"remote_path": "membridge"}}, device="PC-B",
        passphrase=PW)
    assert "只读" in note2
    assert set(channel.read_wiring(chan, PW)["entries"]) == {"jianguoyun"}


def test_state_file_is_local_not_in_channel():
    """接线状态与库同目录（本机）；通道目录里不再有本机状态文件。"""
    tmp = Path(tempfile.mkdtemp(prefix="mb-wire-st-"))
    chan = tmp / "membridge"
    chan.mkdir()
    db = tmp / "mem.db"
    netdisk_sync.record_state(str(chan), "jianguoyun", "membridge", "primary",
                              db_path=str(db))
    p = netdisk_sync.state_path(str(db))
    assert p == tmp / netdisk_sync.STATE_FILE and p.is_file()
    assert not (chan / netdisk_sync._LEGACY_STATE_FILE).exists()
    assert netdisk_sync.load_state(str(db))["jianguoyun"]["role"] == "primary"


def test_load_state_migrates_legacy_channel_file():
    """老位置（通道里的 .membridge-netdisk.json）迁回本机，且不删老文件。"""
    tmp = Path(tempfile.mkdtemp(prefix="mb-wire-mig-"))
    chan = tmp / "membridge"
    chan.mkdir()
    legacy = chan / netdisk_sync._LEGACY_STATE_FILE
    legacy.write_text(json.dumps({"jianguoyun": {"remote_path": "membridge",
                                                 "local_dir": str(chan),
                                                 "role": "primary"}}),
                      encoding="utf-8")
    state = netdisk_sync.load_state(str(tmp / "mem.db"), str(chan))
    assert state["jianguoyun"]["role"] == "primary"
    assert netdisk_sync.state_path(str(tmp / "mem.db")).is_file()
    assert legacy.is_file()  # 不删：别的设备可能还在读它


def test_nutstore_container_root_is_not_picked():
    """真机教训（v0.27）：Windows 坚果云的同步根在 `Nutstore/<序号>/我的坚果云`，
    直接匹配 `Nutstore` 只会拿到**容器**目录——那会让 init 把通道指到错位置。"""
    home = Path(tempfile.mkdtemp(prefix="mb-wire-nut-"))
    (home / "Nutstore" / "1" / "我的坚果云").mkdir(parents=True)
    wizard.HOME_DIR = home
    try:
        found = netdisk_sync.detect_sync_roots()
        assert found == [("坚果云", home / "Nutstore" / "1" / "我的坚果云")]
    finally:
        wizard.HOME_DIR = None


def test_single_detector_source():
    """两份云盘探测合成一份：wizard 门面与 netdisk 实现同源。"""
    home = Path(tempfile.mkdtemp(prefix="mb-wire-home-"))
    (home / "我的坚果云").mkdir()
    (home / "OneDrive - 个人").mkdir()
    wizard.HOME_DIR = home
    try:
        found = netdisk_sync.detect_sync_roots()
        assert found == wizard.detect_sync_roots()
        assert [n for n, _ in found] == ["坚果云", "OneDrive"]
        assert [str(p) for _, p in found] == netdisk_sync.detect_local_drive_dirs()
    finally:
        wizard.HOME_DIR = None
