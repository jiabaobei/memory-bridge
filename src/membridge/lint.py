"""记忆库内容体检（v0.28）：确定性 lint —— 零 LLM、零依赖、只报告。

借鉴 llm_wiki（Karpathy「LLM Wiki」路线）的 deterministic lint：它同样不调
LLM，把「结构可判定」与「需要语义判断」的问题分开。本模块只取前者——四类
结构问题，零误报，判断与内容语义无关。

与 doctor 的分工：doctor 管「环境能不能跑」（版本 / 库位置 / 云盘通道），
lint 管「库本身好不好」（结构健康）。两者都只报告，都不自动改。

四项检查：
- 悬空边：edges 的 src / dst 指向不存在的节点。真实来源——PAMS L1 门控
  拒绝节点迁移（local 记忆永不离开设备），但边随差分包到了对端。
- 孤立记忆：无任何入边与出边（写入时与既有记忆无共现、无实体锚点）。
- 陈旧记忆：孤立 且 超过阈值未访问。有边的记忆不判陈旧——它仍被引用。
- 凭证泄露：正文疑似 API key / token / 私钥。命中处回显一律打码。

内容冻结：本模块只读记忆内容。`fix_structure=True` 只删悬空边——边是结构
不是记忆内容，与 `schema.reconcile` 只补结构同构。
"""

from __future__ import annotations

import json
import re
import time
from typing import Any, Dict, List

from .store import MemoryStore

# 陈旧阈值（天）。与交接卡的 HANDOFF_STALE_HOURS（7 天）刻意分开：
# 记忆不是工作台，长周期未访问不等于失效。
STALE_DAYS = 90

# 凭证模式表：(类别名, 正则)。只报类别与脱敏片段，绝不回显命中原文——
# 否则体检报告本身就成了泄露渠道。
_SECRET_PATTERNS = [
    ("private-key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("openai-key", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}")),
    ("github-token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}")),
    ("aws-key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("slack-token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}")),
    ("assigned-secret", re.compile(
        r"(?i)\b(?:password|passwd|api[_-]?key|secret|access[_-]?token)"
        r"\s*[:=]\s*\S{6,}"
    )),
]


def _redact(text: str, limit: int = 60) -> str:
    """报告用片段：命中处整体打码后再截断。"""
    for _name, rx in _SECRET_PATTERNS:
        text = rx.sub("***", text)
    text = " ".join(text.split())
    return text[:limit] + ("…" if len(text) > limit else "")


def run_lint(
    store: MemoryStore,
    stale_days: int = STALE_DAYS,
    fix_structure: bool = False,
) -> Dict[str, Any]:
    """体检一遍记忆库，返回结构化报告（不改任何记忆内容）。"""
    now = time.time()
    nodes = store.all_nodes()
    ids = {n.node_id for n in nodes}
    edges = store.all_edges_full()

    dangling: List[Dict[str, str]] = [
        {"src": s, "dst": d} for s, d, *_ in edges if s not in ids or d not in ids
    ]

    linked = {x for s, d, *_ in edges for x in (s, d)}
    isolated = [n for n in nodes if n.node_id not in linked]
    cutoff = now - stale_days * 86400
    stale = [n for n in isolated if n.last_access < cutoff]

    secrets: List[Dict[str, str]] = []
    for n in nodes:
        for name, rx in _SECRET_PATTERNS:
            if rx.search(n.content):
                secrets.append({
                    "node_id": n.node_id,
                    "pattern": name,
                    "excerpt": _redact(n.content),
                })
                break

    removed = 0
    if fix_structure and dangling:
        with store.transaction():
            for e in dangling:
                store.conn.execute(
                    "DELETE FROM edges WHERE src = ? AND dst = ?", (e["src"], e["dst"])
                )
        removed = len(dangling)

    counts = {
        "dangling_edges": len(dangling),
        "isolated": len(isolated),
        "stale": len(stale),
        "secrets": len(secrets),
    }
    # 退出码口径：悬空边与凭证泄露是真错误；孤立/陈旧只是提示。
    counts["errors"] = counts["dangling_edges"] + counts["secrets"]

    return {
        "db": getattr(store, "path", ""),
        "nodes": len(nodes),
        "edges": len(edges),
        "stale_days": stale_days,
        "counts": counts,
        "dangling_edges": dangling,
        "isolated": [n.node_id for n in isolated],
        "stale": [n.node_id for n in stale],
        "secrets": secrets,
        "fixed_edges": removed,
        "clean": counts["errors"] == 0,
    }


def print_report(report: Dict[str, Any], out=print) -> None:
    """人类可读体检报告（内容冻结：只陈述，不给修改建议以外的动作）。"""
    c = report["counts"]
    out(f"记忆库体检：{report['db']}")
    out(f"  记忆 {report['nodes']} 条 / 关联 {report['edges']} 条"
        f"（陈旧阈值 {report['stale_days']} 天）")

    if report["fixed_edges"]:
        out(f"  已删悬空边 {report['fixed_edges']} 条（结构修复，未触碰记忆内容）")

    if c["dangling_edges"]:
        out(f"\n[!] 悬空边 {c['dangling_edges']} 条：边指向不存在的节点"
            f"（差分包带了边、节点被 PAMS 门控留下）")
        for e in report["dangling_edges"][:10]:
            out(f"    {e['src']} -> {e['dst']}")
        if c["dangling_edges"] > 10:
            out(f"    …另有 {c['dangling_edges'] - 10} 条")
        if not report["fixed_edges"]:
            out("    （--fix-structure 可清除；边是结构，删它不碰记忆内容）")

    if c["secrets"]:
        out(f"\n[!] 疑似凭证 {c['secrets']} 处（正文已打码）：")
        for s in report["secrets"][:10]:
            out(f"    {s['node_id']} [{s['pattern']}] {s['excerpt']}")
        out("    （请用 membridge search 定位后自行处理；本工具只报告）")

    if c["isolated"]:
        out(f"\n[i] 孤立记忆 {c['isolated']} 条：与任何记忆都无边"
            f"（检索仍可达，只是没有图路）")
    if c["stale"]:
        out(f"[i] 其中陈旧 {c['stale']} 条：孤立且 {report['stale_days']} 天未访问")

    if report["clean"] and not c["isolated"]:
        out("\n结果：结构健康，无错误项。")
    elif report["clean"]:
        out("\n结果：无错误项（孤立/陈旧仅为提示，不作失败）。")


def report_json(report: Dict[str, Any]) -> str:
    return json.dumps(report, ensure_ascii=False, indent=2)
