"""导出层：人类可读的 Markdown Wiki 视图（v0.10）。

借鉴 memU「记忆就是文件」的可审计性：记忆渲染成 Markdown——人能打开看、
能进版本管理、能带走。与 memU 的路线分歧在出口方向：本导出是**只读视图，
永不回写**——手改 Markdown 不会、也无法流回记忆库，内容冻结承诺多了一个
人人可验证的出口（审计 = 读，而不是写）。

对应 README「领域收敛」：与 memU 共享"记忆可被人直接审阅"的判断，
但不引入其"LLM 自动蒸馏入库"管线。
"""

from __future__ import annotations

import time
from typing import Dict, List

from .node import MemoryNode
from .store import MemoryStore

_HEADER_NOTE = (
    "> 本文件是记忆库的**只读视图**：由 `membridge export` 生成。"
    "手工编辑本文件不会、也无法写回记忆库（内容冻结）。"
)


def _fmt_node(n: MemoryNode) -> str:
    ts = time.strftime("%Y-%m-%d %H:%M", time.localtime(n.created_at))
    meta = [f"来自 {n.device}", ts, f"迁移 {n.migration}"]
    if n.tags:
        meta.append("标签 " + "/".join(n.tags))
    return f"- {n.content}（{'，'.join(meta)}）"


def render_markdown(store: MemoryStore) -> str:
    """把整座记忆库渲染为 Markdown：按场景域分组，组内按 kind 分节。

    内容原样输出（内容冻结：渲染不改写任何字）；空库返回说明性占位。
    v0.15：最新未过期交接卡置顶为「当前工作台」（原样呈现）；
    已过期的交接卡与普通交接卡照常进场景分组（历史交接卡可审计）。
    """
    from .handoff import workbench

    nodes = store.all_nodes()
    lines: List[str] = [
        f"# 记忆桥 · 记忆库导出（{store.device_name}）",
        "",
        _HEADER_NOTE,
        "",
        f"共 {len(nodes)} 条记忆，导出时间 "
        + time.strftime("%Y-%m-%d %H:%M", time.localtime()) + "。",
        "",
    ]
    if not nodes:
        lines.append("（记忆库为空：`membridge add \"...\"` 写入第一条）")
        return "\n".join(lines)

    active = workbench(store)
    if active is not None:
        ts = time.strftime("%Y-%m-%d %H:%M", time.localtime(active.created_at))
        lines.append(f"## 当前工作台（最新交接卡，{ts}，来自 {active.device}）")
        lines.append("")
        lines.append("```")
        lines.extend(active.content.splitlines())
        lines.append("```")
        lines.append("")

    by_scene: Dict[str, List[MemoryNode]] = {}
    for n in sorted(nodes, key=lambda x: x.created_at):
        # 工作台已置顶的卡不在场景分组里重复出现
        if active is not None and n.node_id == active.node_id:
            continue
        by_scene.setdefault(n.scene, []).append(n)

    kind_names = {"fact": "事实（fact）", "procedure": "经验（procedure）",
                  "handover": "交接卡（handover）", "": "未分类"}
    for scene in sorted(by_scene):
        group = by_scene[scene]
        lines.append(f"## 场景：{scene}（{len(group)} 条）")
        lines.append("")
        by_kind: Dict[str, List[MemoryNode]] = {}
        for n in group:
            by_kind.setdefault(n.kind if n.kind in kind_names else "", []).append(n)
        for kind in ("fact", "procedure", "handover", ""):
            if kind not in by_kind:
                continue
            if len(by_kind) > 1 or kind:
                lines.append(f"### {kind_names[kind]}")
                lines.append("")
            lines.extend(_fmt_node(n) for n in by_kind[kind])
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"
