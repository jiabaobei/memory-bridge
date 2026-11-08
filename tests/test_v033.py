"""v0.33 回归测试：会话索引沉淀 / 铁律保底召回 / 同步跳过分类。

刻意不依赖 pytest —— `tests/run_tests.py` 是零依赖执行器，所有用例都用
tempfile + argparse.Namespace 直接调命令函数，与 test_import_md.py 同风格。
缓存类用例一律把 MEMBRIDGE_CACHE 指到临时文件（v0.32.1 真机教训：
测试写全局缓存会把生产候选池冲掉）。
"""

import argparse
import json
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from membridge import hook, session_ingest  # noqa: E402
from membridge.cli import classify_skips, cmd_session_ingest  # noqa: E402
from membridge.embeddings import HashingEmbedder  # noqa: E402
from membridge.node import MemoryNode  # noqa: E402
from membridge.privacy import default_migration  # noqa: E402
from membridge.store import MemoryStore  # noqa: E402

_EMB = HashingEmbedder()


def _args(db, root, **kw):
    d = dict(projects_dir=str(root), dry_run=False, since="", limit=50,
             max_files=6, tags="session,index", scene=None, migration=None,
             kind="", verbose=False, db=db, device="测试机")
    d.update(kw)
    return argparse.Namespace(**d)


def _session(root, dirname, lines):
    d = Path(root) / dirname
    d.mkdir(parents=True, exist_ok=True)
    p = d / "abcdef12-3456-7890.jsonl"
    p.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in lines) + "\n",
                 encoding="utf-8")
    return p


def _node(text, **kw):
    d = dict(content=text, embedding=_EMB.embed(text), device="test")
    d.update(kw)
    return MemoryNode(**d)


# ---------------------------------------------------------------- A 会话索引

def test_session_parse_title_artifacts_and_no_body():
    tmp = tempfile.TemporaryDirectory()
    try:
        p = _session(tmp.name, "D-2026-11-04-13-43-03", [
            {"type": "ai-title", "aiTitle": "分析军队文职岗位匹配"},
            {"type": "message", "role": "user", "content": "帮我找最准确的全国岗位表"},
            {"type": "message", "role": "assistant",
             "content": "桌面产出 2027年军队文职招聘岗位表.xlsx 和 "
                        "2027军队文职_鲜妤佳可报岗位34个.xlsx"},
        ])
        e = session_ingest.parse_session(p)
        assert e["date"] == "2026-11-04"
        assert e["title"] == "分析军队文职岗位匹配"
        assert "2027年军队文职招聘岗位表.xlsx" in e["artifacts"]
        assert "2027军队文职_鲜妤佳可报岗位34个.xlsx" in e["artifacts"]
        line = session_ingest.index_line(e)
        assert "分析军队文职岗位匹配" in line and "岗位表.xlsx" in line
        assert "帮我找最准确" not in line, "会话正文一个字都不许进索引"
        assert e["sid"] == "abcdef12"
    finally:
        tmp.cleanup()


def test_session_ingest_dry_run_dedup_and_pams():
    tmp = tempfile.TemporaryDirectory()
    try:
        root = Path(tmp.name) / "projects"
        root.mkdir()
        _session(root, "D-2026-11-04-13-43-03", [
            {"type": "ai-title", "aiTitle": "分析军队文职岗位匹配"},
            {"type": "message", "role": "assistant",
             "content": "产出 2027年军队文职招聘岗位表.xlsx"},
        ])
        db = str(Path(tmp.name) / "m.db")
        assert cmd_session_ingest(_args(db, root, dry_run=True)) == 0
        s = MemoryStore(db)
        assert s.count_nodes() == 0, "dry-run 不得写库"
        s.close()

        cmd_session_ingest(_args(db, root))
        s = MemoryStore(db)
        rows = list(s.conn.execute("SELECT content, tags, migration FROM nodes"))
        assert len(rows) == 1, rows
        assert "分析军队文职岗位匹配" in rows[0][0]
        assert "session" in rows[0][1]
        assert rows[0][2] == default_migration(rows[0][0]), "PAMS 与 add 同一套判定"
        s.close()

        cmd_session_ingest(_args(db, root))   # 重复跑
        s = MemoryStore(db)
        assert s.count_nodes() == 1, "重复导入不得产生重复索引"
        s.close()
    finally:
        tmp.cleanup()


def test_session_ingest_sensitive_title_stays_local():
    tmp = tempfile.TemporaryDirectory()
    try:
        root = Path(tmp.name) / "projects"
        root.mkdir()
        _session(root, "D-2026-11-05-10-00-00", [
            {"type": "ai-title", "aiTitle": "核对账号密码配置"},
        ])
        db = str(Path(tmp.name) / "m.db")
        cmd_session_ingest(_args(db, root))
        s = MemoryStore(db)
        rows = list(s.conn.execute("SELECT content, migration FROM nodes"))
        assert len(rows) == 1
        assert rows[0][1] == "local", "含凭据词的索引必须留在本地，永不上云"
        s.close()
    finally:
        tmp.cleanup()


def test_session_scan_since_and_missing_dir():
    tmp = tempfile.TemporaryDirectory()
    try:
        root = Path(tmp.name) / "projects"
        root.mkdir()
        _session(root, "D-2026-11-01-09-00-00",
                 [{"type": "ai-title", "aiTitle": "旧任务"}])
        _session(root, "D-2026-11-04-13-43-03",
                 [{"type": "ai-title", "aiTitle": "新任务"}])
        assert len(session_ingest.scan(root)) == 2
        got = session_ingest.scan(root, since="2026-11-04")
        assert len(got) == 1 and got[0]["title"] == "新任务"
        assert session_ingest.scan(Path(tmp.name) / "不存在") == []
    finally:
        tmp.cleanup()


def test_session_artifacts_skip_host_docs_and_take_last():
    """真机 2026-11-08：11-04 会话前 6 个「产出」全是宿主配置文档，
    末尾才是真正落盘的岗位表。过滤 + 末尾优先把这条锁成回归。"""
    tmp = tempfile.TemporaryDirectory()
    try:
        p = _session(tmp.name, "D-2026-11-04-13-43-03", [
            {"type": "ai-title", "aiTitle": "整理岗位表"},
            {"type": "message", "role": "assistant",
             "content": "参考 BOOTSTRAP.md SOUL.md USER.md *.xls ~$临时.xlsx"},
            {"type": "message", "role": "assistant",
             "content": "尝试下载 2027gwy.xls 失败"},
            {"type": "message", "role": "assistant",
             "content": "最终生成 2027军队文职_鲜妤佳可报岗位34个.xlsx"},
        ])
        e = session_ingest.parse_session(p, max_files=2)
        assert "BOOTSTRAP.md" not in e["artifacts"], "宿主配置文档不算任务产出"
        assert "*.xls" not in e["artifacts"], "通配符占位不算产出"
        assert "~$临时.xlsx" not in e["artifacts"], "Excel 临时文件不算产出"
        assert e["artifacts"][-1] == "2027军队文职_鲜妤佳可报岗位34个.xlsx", \
            "末尾出现的最终成果必须优先保留"
    finally:
        tmp.cleanup()


def test_session_without_title_is_skipped():
    tmp = tempfile.TemporaryDirectory()
    try:
        p = _session(tmp.name, "D-2026-11-04-13-43-03",
                     [{"type": "tool_result", "content": "ok"}])
        assert session_ingest.parse_session(p) is None, "无标题无正文线索的会话不该进库"
    finally:
        tmp.cleanup()


# ---------------------------------------------------------------- B 铁律保底

def test_is_rule_by_tag_and_marker():
    assert hook.is_rule(_node("普通内容", tags=["教训"]))
    assert hook.is_rule(_node("勿再 用旧钥匙发包"))
    assert not hook.is_rule(_node("今天天气不错"))


def test_warm_keeps_rules_when_pool_is_tiny():
    tmp = tempfile.TemporaryDirectory()
    old = os.environ.get("MEMBRIDGE_CACHE")
    os.environ["MEMBRIDGE_CACHE"] = str(Path(tmp.name) / "cache.json")
    try:
        db = str(Path(tmp.name) / "m.db")
        s = MemoryStore(db)
        rule = _node("铁律：查历史素材必先查本地会话归档",
                     tags=["教训"], confidence=0.35)
        s.add(rule)
        for i in range(4):
            s.add(_node(f"普通记忆第{i}条 通道治理周报", confidence=0.99))
        path = hook.warm(s, budget=800, pool=2)
        cache = json.loads(Path(path).read_text(encoding="utf-8"))
        assert rule.node_id[:8] in cache["rules"]
        assert any(e["id"] == rule.node_id[:8] for e in cache["entries"]), \
            "低热度规则类必须保底进池，不能被 POOL_MAX 截断"
        s.close()
    finally:
        if old is None:
            os.environ.pop("MEMBRIDGE_CACHE", None)
        else:
            os.environ["MEMBRIDGE_CACHE"] = old
        tmp.cleanup()


def test_render_rule_bonus_and_silence_contract():
    cache = {
        "ts": time.time(), "budget": 800, "workbench": "",
        "rules": ["aaaaaaaa"],
        "entries": [
            {"id": "aaaaaaaa", "t": "铁律：检索历史素材必先查本地会话归档",
             "tags": [], "c": 0.3},
            {"id": "bbbbbbbb", "t": "检索历史素材的另一条普通记忆",
             "tags": [], "c": 0.99},
        ],
    }
    block = hook.render(cache, "检索历史素材", budget=800)
    assert "铁律" in block
    assert block.index("铁律") < block.index("另一条"), "规则类命中时须排在普通记忆前"
    assert hook.render(cache, "今天天气怎么样", budget=800) == hook.SILENCE, \
        "无命中时规则类也不许占 token（沉默契约不破）"


# ---------------------------------------------------------------- C 跳过分类

def test_classify_skips_splits_normal_and_abnormal():
    skipped = [
        ("a.json", "自己发布的包，等待其他设备取走"),
        ("b.json", "重复包：所有节点均已在库"),
        ("c.json", "已被上次 fetch 归档"),
        ("d.enc.json", "口令不匹配，无法解密"),
        ("e.json", "差分包 JSON 损坏"),
    ]
    normal, abnormal = classify_skips(skipped)
    assert [x[0] for x in normal] == ["a.json", "b.json", "c.json"]
    assert [x[0] for x in abnormal] == ["d.enc.json", "e.json"]
    assert classify_skips(None) == ([], [])
