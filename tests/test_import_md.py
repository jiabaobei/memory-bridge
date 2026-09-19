"""v0.29 import-md 确定性导入测试。

回归守卫：解析规则稳定（条目行/代码块/标题）、逐条内容判重（重复导入安全）、
dry-run 不写库、迁移标签与单条 add 走同一套自动判定。
"""

import argparse
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from membridge.cli import cmd_import_md  # noqa: E402
from membridge.privacy import default_migration  # noqa: E402
from membridge.store import MemoryStore  # noqa: E402


def _args(db: str, paths, **kw) -> argparse.Namespace:
    d = dict(paths=paths, dry_run=False, tags="imported", scene=None,
             migration=None, kind="", min_len=8, db=db, device="测试机")
    d.update(kw)
    return argparse.Namespace(**d)


def _sample_md(tmp: str) -> str:
    p = Path(tmp) / "2026-09-19.md"
    p.write_text(
        "# 9月19日工作日志\n"
        "\n"
        "- 修复了定时同步的电池门槛问题\n"
        "  - 缩进的子条目也算一条\n"
        "普通段落不是条目，跳过\n"
        "```python\n"
        "- 代码块里的伪条目必须跳过\n"
        "```\n"
        "- 短\n"
        "2. 编号条目也认\n",
        encoding="utf-8",
    )
    return str(p)


def test_import_md_parses_bullets_and_skips_noise():
    tmp = tempfile.TemporaryDirectory()
    try:
        db = os.path.join(tmp.name, "mem.db")
        store = MemoryStore(db)
        rc = cmd_import_md(_args(db, [_sample_md(tmp.name)]))
        assert rc == 0
        rows = [r[0] for r in store.conn.execute("SELECT content FROM nodes")]
        assert len(rows) == 4, rows
        assert "[2026-09-19] 修复了定时同步的电池门槛问题" in rows
        assert "[2026-09-19] 缩进的子条目也算一条" in rows
        assert "[2026-09-19] 编号条目也认" in rows
        assert not any("代码块" in r for r in rows), "代码块内容不得入库"
        assert not any("普通段落" in r for r in rows)
        # 标签 + 迁移标签走同一套自动判定
        mig = dict(store.conn.execute("SELECT content, migration FROM nodes"))
        for c, m in mig.items():
            assert m == default_migration(c), (c, m)
        store.close()
    finally:
        tmp.cleanup()


def test_import_md_dedup_on_rerun():
    tmp = tempfile.TemporaryDirectory()
    try:
        db = os.path.join(tmp.name, "mem.db")
        cmd_import_md(_args(db, [_sample_md(tmp.name)]))
        store = MemoryStore(db)
        n1 = store.count_nodes()
        store.close()
        cmd_import_md(_args(db, [_sample_md(tmp.name)]))
        store = MemoryStore(db)
        assert store.count_nodes() == n1, "重复导入不得产生新条目"
        store.close()
    finally:
        tmp.cleanup()


def test_import_md_dry_run_writes_nothing():
    tmp = tempfile.TemporaryDirectory()
    try:
        db = os.path.join(tmp.name, "mem.db")
        rc = cmd_import_md(_args(db, [_sample_md(tmp.name)], dry_run=True))
        assert rc == 0
        store = MemoryStore(db)
        assert store.count_nodes() == 0, "dry-run 不得写库"
        store.close()
    finally:
        tmp.cleanup()


def test_import_md_directory_takes_md_and_txt():
    tmp = tempfile.TemporaryDirectory()
    try:
        Path(tmp.name, "2026-09-18.md").write_text("- 甲条目内容足够长\n", encoding="utf-8")
        Path(tmp.name, "2026-09-19.txt").write_text("- 乙条目内容足够长\n", encoding="utf-8")
        Path(tmp.name, "ignore.log").write_text("- 不该被取的日志\n", encoding="utf-8")
        db = os.path.join(tmp.name, "mem.db")
        cmd_import_md(_args(db, [tmp.name]))
        store = MemoryStore(db)
        rows = [r[0] for r in store.conn.execute("SELECT content FROM nodes")]
        assert rows == ["[2026-09-18] 甲条目内容足够长", "[2026-09-19] 乙条目内容足够长"], rows
        store.close()
    finally:
        tmp.cleanup()
