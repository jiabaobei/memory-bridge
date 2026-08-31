"""注入层：Path A 显式上下文拼接（论文 §3.5）。

Prompt_aug = [System] ⊕ Serialize({n_i | conf(n_i) > θ_c}) ⊕ [当前问题]

Path A 提供显式、可审计的记忆注入，适合事实检索与对话延续；
Path B（隐藏状态融合）按约定放入 experimental，Phase 4 再碰
（闭源 API 模型拿不到 hidden states，仅对本地开源模型可行）。

v0.9 借鉴修订（极度省 token 原则的进一步落地）：
- 预算填充：上下文块受 max_chars 预算约束，按给定顺序（检索排名）填充。
- 超额截断：预算不够时注入条目**原文的前缀**而非整条丢弃——截断是取原文
  连续片段，不改写任何字（内容冻结无损）；对应 Metis 论文"查询时只读
  约 56 token 而不重放 1410 token 历史"与 airllm"只载入当前需要的层"。
- 沉默契约：没有可注入的高置信记忆时返回显式的"本轮不干预"标注
  （Meta Proactive Memory Agent：沉默也是动作），不硬凑弱命中。
"""

from __future__ import annotations

import time
from typing import Iterable, List

from .node import MemoryNode

CONFIDENCE_THRESHOLD = 0.3  # 论文中的 θ_c

# 沉默契约：无高置信命中时的显式"不干预"输出（而不是空块或硬凑）
SILENCE_NOTE = "（记忆桥：本轮没有需要干预的记忆——保持沉默，不注入上下文）"

_TRUNC_MARK = "…[原文截断]"


def _fmt_line(n: MemoryNode, content: str) -> str:
    ts = time.strftime("%m-%d %H:%M", time.localtime(n.created_at))
    return f"- {content}（{ts}，来自 {n.device}，场景 {n.scene}）"


def serialize(nodes: Iterable[MemoryNode], max_chars: int = 1500) -> str:
    """把高置信记忆节点序列化为自然语言上下文块（显式可审计）。

    max_chars 为注入预算：预算内的条目全文注入；第一个超预算的条目注入
    原文前缀并标注截断（截断 ≠ 改写，内容冻结原则完整保持）；再往后
    的条目放弃。无任何高置信条目时返回 SILENCE_NOTE。
    """
    eligible = [n for n in nodes if n.confidence >= CONFIDENCE_THRESHOLD]
    if not eligible:
        return SILENCE_NOTE
    lines: List[str] = ["[记忆桥 · 跨设备记忆上下文 开始]"]
    used = 0
    for n in eligible:
        line = _fmt_line(n, n.content)
        if used + len(line) <= max_chars:
            lines.append(line)
            used += len(line)
            continue
        # 预算不足：注入原文前缀（剩余预算扣除标注与出处开销后全给正文）
        overhead = len(_fmt_line(n, "")) + len(_TRUNC_MARK)
        keep = max_chars - used - overhead
        if keep < 10:
            break
        lines.append(_fmt_line(n, n.content[:keep] + _TRUNC_MARK))
        break
    lines.append("[记忆桥 · 跨设备记忆上下文 结束]")
    return "\n".join(lines)


def build_prompt_aug(
    system: str, memory_nodes: Iterable[MemoryNode], query: str,
    max_chars: int = 1500,
) -> str:
    """生成增强后的完整 prompt（System ⊕ 记忆块 ⊕ 当前问题）。"""
    block = serialize(memory_nodes, max_chars=max_chars)
    return f"{system}\n\n{block}\n\n[当前问题] {query}"
