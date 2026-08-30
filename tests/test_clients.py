"""平台接入注册表 / init 向导 / doctor 测试（HOME 目录注入到临时目录）。"""

import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

import membridge.clients as clients  # noqa: E402
from membridge.skill_template import SKILL_MD  # noqa: E402


def _tmp_home():
    return Path(tempfile.mkdtemp(prefix="membridge-home-"))


def _with_home():
    """装饰器替代：返回 (home, restore) —— 测试结束恢复真实 HOME。"""
    home = _tmp_home()
    clients.HOME_DIR = home
    return home


def _restore():
    clients.HOME_DIR = None


def test_registry_structure_and_unique_keys():
    reg = clients.registry()
    keys = [c.key for c in reg]
    assert len(keys) == len(set(keys))
    assert {"zcode", "cursor", "workbuddy", "trae", "coze"}.issubset(set(keys))
    for c in reg:
        assert c.name and c.tier in ("mcp", "skill", "manual")
        if c.tier == "manual":
            assert c.manual.strip()


def test_zcode_merge_idempotent_preserves_existing():
    home = _with_home()
    try:
        cfg = home / ".zcode" / "cli" / "config.json"
        cfg.parent.mkdir(parents=True)
        cfg.write_text(json.dumps({"plugins": {"enabledPlugins": {"x@y": True}}}),
                       encoding="utf-8")
        z = [c for c in clients.registry() if c.key == "zcode"][0]
        assert z.detect()
        r1 = z.configure("D:/mem.db", "PC")
        assert r1.status == "configured"
        r2 = z.configure("D:/mem.db", "PC")
        assert r2.status == "already"
        data = json.loads(cfg.read_text(encoding="utf-8"))
        assert data["plugins"]["enabledPlugins"] == {"x@y": True}  # 原有内容未破坏
        entry = data["mcp"]["servers"]["memory-bridge"]
        assert entry["args"] == ["-m", "membridge", "mcp"]
        assert entry["env"]["MEMBRIDGE_DB"] == "D:/mem.db"
    finally:
        _restore()


def test_cursor_merge_creates_file_when_dir_exists():
    home = _with_home()
    try:
        (home / ".cursor").mkdir()
        cur = [c for c in clients.registry() if c.key == "cursor"][0]
        assert cur.detect()
        r = cur.configure("/home/u/.membridge/memory.db", "我的电脑")
        assert r.status == "configured"
        data = json.loads((home / ".cursor" / "mcp.json").read_text(encoding="utf-8"))
        assert data["mcpServers"]["memory-bridge"]["env"]["MEMBRIDGE_DEVICE"] == "我的电脑"
    finally:
        _restore()


def test_workbuddy_skill_install_and_idempotent():
    home = _with_home()
    try:
        (home / ".workbuddy").mkdir()
        wb = [c for c in clients.registry() if c.key == "workbuddy"][0]
        assert wb.detect()
        r1 = wb.configure("D:/mem.db", "PC")
        assert r1.status == "configured"
        target = home / ".workbuddy" / "skills" / "memory-bridge" / "SKILL.md"
        assert target.exists() and target.read_text(encoding="utf-8") == SKILL_MD
        r2 = wb.configure("D:/mem.db", "PC")
        assert r2.status == "already"
        # 未安装 WorkBuddy 的机器上应跳过
        (home / ".workbuddy").rename(home / ".workbuddy-bak")
        assert not wb.detect()
    finally:
        _restore()


def test_skill_template_has_frontmatter_and_commands():
    assert SKILL_MD.startswith("---")
    assert "name: memory-bridge" in SKILL_MD
    assert "membridge add" in SKILL_MD and "membridge context" in SKILL_MD


def test_manual_guides_cover_trae_and_coze():
    guides = {c.key: c for c in clients.manual_guides()}
    assert "trae" in guides and "coze" in guides
    assert "membridge mcp --http" in guides["coze"].manual


def test_wizard_noninteractive_all_mode():
    import membridge.wizard as wizard
    home = _with_home()
    wizard.HOME_DIR = home
    try:
        (home / ".workbuddy").mkdir()
        (home / "我的坚果云").mkdir()  # 检测到同步盘：非交互也应自动配好云盘
        from membridge.wizard import InitOptions, run_init

        lines = []
        rc = run_init(
            InitOptions(db=str(home / "mem.db"), device="测试机",
                        all_mode=True, interactive=False),
            out=lines.append,
        )
        assert rc == 0
        text = "\n".join(lines)
        assert "测试机" in text and "WorkBuddy" in text
        # 云盘是第一步，且被强制配置（非交互自动使用检测到的同步盘）
        assert text.index("云盘中转") < text.index("WorkBuddy")
        assert "云盘通道已配置" in text
        assert (home / "我的坚果云" / "membridge" / "outbox").is_dir()
        assert (home / ".workbuddy" / "skills" / "memory-bridge" / "SKILL.md").exists()
        assert (home / "mem.db").exists()  # 向导建库
        # 扣子等手动指南出现在输出里
        assert "--http" in text
    finally:
        wizard.HOME_DIR = None
        _restore()


def test_wizard_no_cloud_warns_loudly():
    import membridge.wizard as wizard
    home = _with_home()
    wizard.HOME_DIR = home
    try:
        from membridge.wizard import InitOptions, run_init

        lines = []
        rc = run_init(
            InitOptions(db=str(home / "mem.db"), device="测试机",
                        all_mode=True, interactive=False),
            out=lines.append,
        )
        assert rc == 0
        text = "\n".join(lines)
        assert "未配置云盘" in text and "免费云盘" in text
    finally:
        wizard.HOME_DIR = None
        _restore()


def test_wizard_netdisk_dir_creates_channel():
    import membridge.wizard as wizard
    home = _with_home()
    wizard.HOME_DIR = home
    try:
        ch = home / "netdisk-sync" / "membridge"
        from membridge.wizard import InitOptions, run_init

        lines = []
        rc = run_init(
            InitOptions(db=str(home / "mem.db"), device="手机",
                        netdisk_dir=str(ch), no_autosync=True, interactive=False),
            out=lines.append,
        )
        assert rc == 0
        text = "\n".join(lines)
        assert "云盘通道已配置" in text
        assert (ch / "outbox").is_dir() and (ch / "archive").is_dir()
        # 同步口令由系统自动生成并托管（用户无需设置）；不再输出手动 publish/fetch 命令
        assert "自动生成" in text
        assert "publish --dir" not in text
    finally:
        wizard.HOME_DIR = None
        _restore()


def test_detect_sync_roots_uses_injected_home():
    import membridge.wizard as wizard
    home = _with_home()
    wizard.HOME_DIR = home
    try:
        assert wizard.detect_sync_roots() == []  # 临时目录下无同步盘
        (home / "我的坚果云").mkdir()
        found = wizard.detect_sync_roots()
        assert found and found[0][0] == "坚果云"
    finally:
        wizard.HOME_DIR = None
        _restore()


def test_doctor_runs_without_error():
    home = _with_home()
    try:
        from membridge.doctor import run_doctor

        lines = []
        assert run_doctor(out=lines.append) == 0
        assert any("membridge 版本" in ln for ln in lines)
        assert any("平台检测" in ln for ln in lines)
    finally:
        _restore()


def test_init_never_writes_real_user_configs():
    """回归（v0.8.0）：init 测试曾因漏注入 clients.HOME_DIR，把真实的
    ZCode / Cursor / VS Code 配置改写到临时 membridge-gen-* 目录——
    用户每平台的 MCP 配置被测试劫持。此金丝雀保证：跑全套测试时，
    真实用户配置必须字节级不变。"""
    appdata = os.environ.get("APPDATA", "")
    real_files = [
        Path.home() / ".zcode" / "cli" / "config.json",
        Path.home() / ".cursor" / "mcp.json",
        Path(appdata) / "Code" / "User" / "mcp.json" if appdata else None,
    ]
    snapshot = {}
    for p in real_files:
        if p and p.is_file():
            snapshot[p] = p.read_bytes()

    home = _with_home()
    import membridge.wizard as wizard

    wizard.HOME_DIR = home
    try:
        from membridge.wizard import InitOptions, run_init

        rc = run_init(
            InitOptions(db=str(home / "mem.db"), device="测试机",
                        all_mode=True, no_autosync=True, interactive=False),
            out=lambda *_: None,
        )
        assert rc == 0
    finally:
        wizard.HOME_DIR = None
        _restore()

    for p, data in snapshot.items():
        assert p.read_bytes() == data, f"真实用户配置被测试改写：{p}"
