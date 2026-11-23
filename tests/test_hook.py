"""钩子层测试：缓存预热、相关性过滤（只注入有用）、幂等安装。"""

import json

import pytest

from membridge import hook
from membridge.node import MemoryNode
from membridge.store import MemoryStore


@pytest.fixture(autouse=True)
def _isolated_cache(tmp_path, monkeypatch):
    """每个测试用独立缓存，绝不碰 ~/.membridge/inject-cache.json（v0.32.1 教训）。"""
    monkeypatch.setenv("MEMBRIDGE_CACHE", str(tmp_path / "cache.json"))


def _store(tmp_path):
    s = MemoryStore(str(tmp_path / "m.db"))
    s.add(MemoryNode(content="通道治理周报走 gen_card.py 生成卡片版 PDF",
                     embedding=[0.0] * 256, device="test", confidence=0.9))
    s.add(MemoryNode(content="女儿简历投递只用简历主档素材", embedding=[0.0] * 256,
                     device="test", confidence=0.8))
    return s


def test_tokens_chinese_ngrams():
    t = hook.tokens("通道治理周报")
    assert "通道" in t and "治理" in t and "周报" in t      # 2 字滑动窗
    assert "gen_card.py" in hook.tokens("gen_card.py 怎么跑")


def test_render_only_relevant(tmp_path):
    s = _store(tmp_path)
    cache = json.loads(hook.warm(s, budget=800).read_text(encoding="utf-8"))
    block = hook.render(cache, "周报怎么生成", budget=800)
    assert "gen_card.py" in block
    assert "简历主档" not in block          # 不相关的一条不许进来（省 token）

    miss = hook.render(cache, "今天天气怎么样", budget=800)
    assert miss == hook.SILENCE             # 命中不到 → 一个字都不写


def test_warm_cache_roundtrip(tmp_path):
    s = _store(tmp_path)
    path = hook.warm(s, budget=500)
    cache = json.loads(path.read_text(encoding="utf-8"))
    assert cache["entries"] and cache["ts"]
    assert hook.is_stale(cache) is False
    assert hook.is_stale({"ts": 0}) is True


def test_emit_json_and_silence(capsys):
    hook.emit("[记忆桥 · x]", as_json=True, event="UserPromptSubmit")
    out = json.loads(capsys.readouterr().out)
    assert out["hookSpecificOutput"]["additionalContext"] == "[记忆桥 · x]"
    hook.emit(hook.SILENCE)
    assert capsys.readouterr().out == ""


def test_install_idempotent_and_keeps_foreign_hooks(tmp_path):
    p = tmp_path / "settings.json"
    p.write_text(json.dumps({"hooks": {"SessionStart": [
        {"hooks": [{"type": "command", "command": "bash other.sh"}]}]}}),
        encoding="utf-8")
    paths = {"host": p}

    assert "已装" in hook.install(paths)[0]
    data = json.loads(p.read_text(encoding="utf-8"))
    assert len(data["hooks"]["SessionStart"]) == 2          # 别人的 + 我们的
    assert any("other.sh" in h["command"]
               for e in data["hooks"]["SessionStart"] for h in e["hooks"])

    assert "已装（无需改动）" in hook.install(paths)[0]      # 幂等
    assert len(json.loads(p.read_text(encoding="utf-8"))["hooks"]["SessionStart"]) == 2

    hook.uninstall(paths)
    data = json.loads(p.read_text(encoding="utf-8"))
    assert len(data["hooks"]["SessionStart"]) == 1          # 只摘自己那条
    assert "other.sh" in data["hooks"]["SessionStart"][0]["hooks"][0]["command"]


def test_status_reports_installed(tmp_path):
    p = tmp_path / "settings.json"
    p.write_text("{}", encoding="utf-8")
    hook.install({"host": p})
    assert "✅" in hook.status({"host": p})[0]


# ---------------------------------------------------------------------------
# v0.33.1 真机回归：用户在另一个对话里问「周报规则」，注入 0 条，agent 找不到
# ---------------------------------------------------------------------------

def test_two_char_topic_is_not_noise(tmp_path):
    """「帮我做周报」必须命中：「周报」是滑窗碎片，但它是主题词，不许当噪音丢。"""
    s = _store(tmp_path)
    cache = json.loads(hook.warm(s, budget=800).read_text(encoding="utf-8"))
    block = hook.render(cache, "帮我做周报", budget=800)
    assert "gen_card.py" in block


def test_three_char_phrase_gets_window(tmp_path):
    """「出通报」整串不在任何记忆里，滑窗门槛必须放到 3 字才接得住。"""
    s = MemoryStore(str(tmp_path / "m.db"))
    s.add(MemoryNode(content="卡片式通报：跑 gen_card.py 出两页卡片",
                     embedding=[0.0] * 256, device="test"))
    cache = json.loads(hook.warm(s, budget=800).read_text(encoding="utf-8"))
    assert "gen_card.py" in hook.render(cache, "出通报", budget=800)


def test_ask_word_does_not_hijack_topic(tmp_path):
    """「周报规则在哪」要给周报流程，不能被别的「规则」条目抢走。"""
    s = MemoryStore(str(tmp_path / "m.db"))
    s.add(MemoryNode(content="网申字数双口径规则：1 字符算 1 字，全角算 2",
                     embedding=[0.0] * 256, device="test", kind="procedure",
                     confidence=1.0))
    s.add(MemoryNode(content="卡片式周报流水线：跑 gen_card.py 生成卡片版 PDF",
                     embedding=[0.0] * 256, device="test", kind="procedure",
                     confidence=0.5))
    cache = json.loads(hook.warm(s, budget=800).read_text(encoding="utf-8"))
    first = [ln for ln in hook.render(cache, "周报规则在哪", budget=800).splitlines()
             if ln.startswith("- ")][0]
    assert "gen_card.py" in first


def test_fragment_hits_do_not_inflate(tmp_path):
    """碎片命中多个也只算 1 分：否则「周报规则」的「报规」碎片会把别的条目顶上来。"""
    s = MemoryStore(str(tmp_path / "m.db"))
    # 含「周报」「报规」两个碎片，但主题是「失忆」——不该压过真正的周报流程
    s.add(MemoryNode(content="跨对话失忆根因：周报规则章节在截断线之后",
                     embedding=[0.0] * 256, device="test", kind="fact", confidence=1.0))
    s.add(MemoryNode(content="周报流水线：跑 gen_card.py 生成卡片版 PDF",
                     embedding=[0.0] * 256, device="test", kind="procedure",
                     confidence=0.4))
    cache = json.loads(hook.warm(s, budget=800).read_text(encoding="utf-8"))
    first = [ln for ln in hook.render(cache, "周报规则在哪", budget=800).splitlines()
             if ln.startswith("- ")][0]
    assert "gen_card.py" in first


def test_chitchat_stays_silent(tmp_path):
    """客套话不许撞进记忆（真机：「嗯嗯好的收到」撞进了投简历规则）。"""
    s = _store(tmp_path)
    cache = json.loads(hook.warm(s, budget=800).read_text(encoding="utf-8"))
    assert hook.render(cache, "嗯嗯好的收到", budget=800) == hook.SILENCE


def test_long_entry_is_truncated(tmp_path):
    """单条 500 字会把预算吃满，后面的命中被丢——必须截断保多条。"""
    s = MemoryStore(str(tmp_path / "m.db"))
    for i in range(3):
        s.add(MemoryNode(content="周报步骤" + str(i) * 400, embedding=[0.0] * 256,
                         device="test", kind="procedure"))
    cache = json.loads(hook.warm(s, budget=800).read_text(encoding="utf-8"))
    hits = [ln for ln in hook.render(cache, "周报步骤", budget=800).splitlines()
            if ln.startswith("- ")]
    assert len(hits) >= 2 and all(len(h) <= hook.LINE_MAX + 3 for h in hits)
