"""交接班层：工作台（交接卡）的读取与呈现（v0.15）。

问题：Agent 的上下文有限，长任务靠反复压缩续命，而压缩是有损的——
"方案B被否决"或许留了下来，"为什么被否决"往往先丢。下一个窗口于是
重蹈覆辙。与其要求系统在某个时刻"预判未来需要什么"，不如让收工方
**显式写一张交接卡**（goal / done / failed / next / refs 五行约定），
完整的历史仍由记忆库承载，细节随时可查。

与三层记忆形态的对应：
- **工作台**（本模块）：全库最新一张未过期交接卡，注入时**恒定在场**——
  它是状态声明，不是对问题的回答，因此不走相关性检索、不受沉默契约约束；
- **交接卡**（kind=handover 记忆）：就是普通记忆节点，同步 / 检索 /
  审计设施全部复用（库内之物，不另建存储）；
- **档案**（全部记忆）：交接卡漏掉的细节，回库里查。

三条纪律：
- **取代是推导出来的，不是写进去的**：最新一张（created_at 最大，同刻按
  node_id 定序）即生效，旧的自动降级为历史——零新增状态位，跨设备同步
  后各端自动收敛到同一张卡，天然无冲突；
- **新鲜度门槛**：超过 τ（默认 7 天）未更新的卡不再恒定注入（过期工作台
  比没有工作台更危险），降级为普通记忆走检索；
- **内容冻结**：本模块只读原文做行前缀解析与摘要提取，绝不改写；
  五行约定是"推荐格式"，不合规的交接卡原文照常呈现。
"""

from __future__ import annotations

import re
import time
from typing import Dict, Optional, Tuple

from .node import MemoryNode
from .store import MemoryStore

# 交接卡的记忆类型标注（nodes.kind 的第三个取值）
HANDOFF_KIND = "handover"

# 新鲜度门槛（小时）：超过该时长未更新的交接卡不再恒定注入。
# 与 confidence / rel_floor 同级的结构参数，不进用户可调面，留给 AEE。
HANDOFF_STALE_HOURS = 24 * 7

# 工作台在注入预算中的份额（下限 120 字符，防止预算给满时挤压检索区）
WORKBENCH_BUDGET_RATIO = 1 / 3
WORKBENCH_BUDGET_MIN = 120

# 推荐行前缀（只用于解析展示与摘要提取；正文原文冻结）
SECTIONS = ("goal", "done", "failed", "next", "refs")

# 一行约定：允许行首空白、ASCII/全角冒号；值从冒号后开始原样保留
_SECTION_LINE_RE = re.compile(
    r"^\s*(" + "|".join(SECTIONS) + r")\s*[:：]\s?(.*)$"
)

# 面向用户 / 宿主的推荐模板（handoff-hint、随身记页面共用一个事实来源）
TEMPLATE = (
    "goal: <当前目标>\n"
    "done: <已完成>\n"
    "failed: <试过什么>；因为<原因>；除非<条件>否则别重试\n"
    "next: <下一步>\n"
    "refs: <相关文件/符号/标识>"
)

FAILED_DISCIPLINE = (
    "failed 行用硬句式：试过什么；因为什么失败；除非什么改变否则别重试"
    "——『被否决』和『为什么被否决』必须一起留下，这是交接卡最值钱的一行"
)


def parse_sections(content: str) -> Tuple[Dict[str, str], str]:
    """按行前缀只读解析交接卡：返回 ({section: 原文值}, 未归类原文)。

    不改写任何字符：值保留行内原文；无行前缀的行（含模板前的引导语）
    归入第二段。解析仅服务于摘要与展示，不合规内容不视为错误。
    """
    sections: Dict[str, str] = {}
    extras: list = []
    for line in content.splitlines():
        m = _SECTION_LINE_RE.match(line)
        if m and m.group(1) in SECTIONS:
            key, value = m.group(1), m.group(2).rstrip()
            sections[key] = (
                sections[key] + "\n" + value if key in sections else value
            )
        else:
            if line.strip():
                extras.append(line)
    return sections, "\n".join(extras)


def summary(node: MemoryNode, limit: int = 48) -> str:
    """一行摘要：优先 goal 段，退回首行——供 doctor / export 标题行使用。"""
    sections, extras = parse_sections(node.content)
    text = (sections.get("goal") or "").strip() or (extras or "").strip()
    text = text.splitlines()[0] if text else node.content.strip()
    return text[:limit] + ("…" if len(text) > limit else "")


def latest_handoff(store: MemoryStore) -> Optional[MemoryNode]:
    """全库最新的交接卡（created_at 最大；同刻按 node_id 定序，保证各端收敛一致）。"""
    cards = [n for n in store.all_nodes() if n.kind == HANDOFF_KIND]
    if not cards:
        return None
    return max(cards, key=lambda n: (n.created_at, n.node_id))


def age_hours(node: MemoryNode, now: Optional[float] = None) -> float:
    return ((now if now is not None else time.time()) - node.created_at) / 3600.0


def workbench(store: MemoryStore, now: Optional[float] = None) -> Optional[MemoryNode]:
    """当前生效的工作台：最新交接卡且未过期；无卡或过期返回 None。"""
    card = latest_handoff(store)
    if card is None:
        return None
    if age_hours(card, now) > HANDOFF_STALE_HOURS:
        return None
    return card


def workbench_block(store: MemoryStore, now: Optional[float] = None) -> str:
    """注入用工作台文本块（不含内容改写；过期/无卡返回空串）。"""
    card = workbench(store, now)
    if card is None:
        return ""
    ts = time.strftime("%m-%d %H:%M", time.localtime(card.created_at))
    header = f"【工作台】交接卡（{ts}，来自 {card.device}）："
    body = "\n".join("  " + line for line in card.content.splitlines() if line.strip())
    return f"{header}\n{body}"


def handoff_hint() -> str:
    """可粘贴进宿主指令文件的常驻交接提示（与 recall-hint 对称，自愿启用）。"""
    return (
        "任务告一段落、当前上下文将满、或即将切换设备前，把这一阶段写成一张交接卡："
        'membridge add "goal:…\ndone:…\nfailed:…\nnext:…\nrefs:…" --kind handover。'
        "failed 行用硬句式：试过什么；因为什么失败；除非什么改变否则别重试。"
        "新卡自动取代旧卡；新会话开始时先读注入块中的【工作台】，再决定要不要检索旧账。"
    )
