"""记忆节点：记忆桥的最小记忆单元（论文 §3.2 SAN 中的 n_i）。"""

from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class MemoryNode:
    """一条结构化记忆。

    对应论文中的语义节点 n_i：content 为原始内容（内容冻结，永不改写），
    embedding 为语义向量 e_i，其余字段服务于 TMT 热度驻留与 PAMS 隔离判定。
    """

    content: str
    embedding: List[float] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    scene: str = "personal"   # PAMS L2 场景域：work / personal / medical / financial ...
    device: str = "unknown"   # 记忆产生时所在设备
    migration: str = "edge"   # PAMS L1 迁移标签：local / edge / cloud
    confidence: float = 1.0
    # v0.9 可选标注（借鉴 Proactive Memory Agent 的记忆三分法）：
    # "fact" 稳定事实 / "procedure" 试过什么、结果怎样；空 = 未标注，纯可选不强制
    kind: str = ""
    node_id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])
    created_at: float = field(default_factory=time.time)
    last_access: float = field(default_factory=time.time)
    access_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "MemoryNode":
        fields = set(cls.__dataclass_fields__)  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in d.items() if k in fields})

    def touch(self, when: Optional[float] = None) -> None:
        """记录一次被引用（提升 TMT 热度 H(n) 的 frequency 项）。"""
        self.last_access = when if when is not None else time.time()
        self.access_count += 1
