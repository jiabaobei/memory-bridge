"""注入层：Path A 显式上下文拼接（论文 §3.5）。

Prompt_aug = [System] ⊕ Serialize({n_i | conf(n_i) > θ_c}) ⊕ [当前问题]

Path A 提供显式、可审计的记忆注入，适合事实检索与对话延续；
Path B（隐藏状态融合）按约定放入 experimental，Phase 4 再碰
（闭源 API 模型拿不到 hidden states，仅对本地开源模型可行）。
"""

from __future__ import annotations

import time
from typing import Iterable, List

from .node import MemoryNode

CONFIDENCE_THRESHOLD = 0.3  # 论文中的 θ_c


def serialize(nodes: Iterable[MemoryNode], max_chars: int = 1500) -> str:
    """把高置信记忆节点序列化为自然语言上下文块（显式可审计）。"""
    lines: List[str] = ["[记忆桥 · 跨设备记忆上下文 开始]"]
    used = 0
    for n in nodes:
        if n.confidence < CONFIDENCE_THRESHOLD:
            continue
        ts = time.strftime("%m-%d %H:%M", time.localtime(n.created_at))
        line = f"- {n.content}（{ts}，来自 {n.device}，场景 {n.scene}）"
        if used + len(line) > max_chars:
            break
        lines.append(line)
        used += len(line)
    lines.append("[记忆桥 · 跨设备记忆上下文 结束]")
    return "\n".join(lines)


def build_prompt_aug(
    system: str, memory_nodes: Iterable[MemoryNode], query: str
) -> str:
    """生成增强后的完整 prompt（System ⊕ 记忆块 ⊕ 当前问题）。"""
    return f"{system}\n\n{serialize(memory_nodes)}\n\n[当前问题] {query}"
