"""v0.10 导出层测试：Markdown 视图的内容冻结守卫 + 覆盖保护 + 召回提示。"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from membridge import cli  # noqa: E402
from membridge.embeddings import HashingEmbedder  # noqa: E402
from membridge.export import render_markdown  # noqa: E402
from membridge.node import MemoryNode  # noqa: E402
from membridge.store import MemoryStore  # noqa: E402

COFFEE = "用户喜欢喝美式咖啡，不加糖"
DEPLOY = "部署脚本在 arm64 上会报段错误，换 x86 镜像后通过"


def _tmp_store(device: str = "pc") -> MemoryStore:
    tmp = tempfile.TemporaryDirectory()
    store = MemoryStore(os.path.join(tmp.name, "mem.db"), device=device)
    store._tmp = tmp
    return store


def test_export_contains_every_content_verbatim():
    """内容冻结守卫：导出是原样渲染——每条内容必须逐字出现，不允许改写。"""
    store = _tmp_store()
    emb = HashingEmbedder()
    store.add(MemoryNode(content=COFFEE, embedding=emb.embed(COFFEE), device="pc"))
    store.add(MemoryNode(content=DEPLOY, embedding=emb.embed(DEPLOY), device="pc",
                         kind="procedure"))
    text = render_markdown(store)
    assert COFFEE in text and DEPLOY in text
    assert "只读视图" in text  # 视图自带"不回写"声明
    assert "procedure" in text  # kind 分组可见
    store.close()


def test_export_groups_by_scene_and_kind():
    store = _tmp_store()
    emb = HashingEmbedder()
    store.add(MemoryNode(content=COFFEE, embedding=emb.embed(COFFEE),
                         device="pc", scene="personal"))
    store.add(MemoryNode(content=DEPLOY, embedding=emb.embed(DEPLOY),
                         device="pc", scene="work", kind="fact"))
    text = render_markdown(store)
    assert "场景：personal" in text and "场景：work" in text
    store.close()


def test_export_empty_store_placeholder():
    store = _tmp_store()
    text = render_markdown(store)
    assert "共 0 条" in text
    store.close()


def test_cli_export_refuses_overwrite_without_force(capsys=None):
    store = _tmp_store()
    emb = HashingEmbedder()
    store.add(MemoryNode(content=COFFEE, embedding=emb.embed(COFFEE), device="pc"))
    db = store.path
    store.close()
    tmp = tempfile.TemporaryDirectory()
    out = os.path.join(tmp.name, "wiki.md")
    assert cli.main(["--db", db, "export", "--out", out]) == 0
    assert os.path.isfile(out)
    # 无 --force 拒绝覆盖；加 --force 允许
    assert cli.main(["--db", db, "export", "--out", out]) == 2
    assert cli.main(["--db", db, "export", "--out", out, "--force"]) == 0


def test_recall_hint_prints_pasteable_instruction():
    import io
    import contextlib

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = cli.main(["recall-hint"])
    out = buf.getvalue()
    assert rc == 0
    assert "memory_search" in out and "as_context" in out
    assert "CLAUDE.md" in out and "AGENTS.md" in out
