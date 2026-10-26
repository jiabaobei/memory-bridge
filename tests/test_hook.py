"""钩子层测试：缓存预热、相关性过滤（只注入有用）、幂等安装。"""

import json

from membridge import hook
from membridge.node import MemoryNode
from membridge.store import MemoryStore


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
