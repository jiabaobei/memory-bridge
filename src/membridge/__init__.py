"""记忆桥 MemoryBridge —— 跨设备、跨平台的 AI 共享记忆层。

CDSMP（Cross-Device Semantic Memory Persistence，大模型跨设备语义记忆连续性架构）
的官方工程实现。与论文六阶段流水线的模块映射：

    perception   采集入口（各连接器 / CLI / MCP 工具）
    distillation san.SAN        语义关联网络（简化版）
    caching      heat.TMT       热度与预加载候选（v0 启发式）
    sync         dss.DSS        增量语义同步（本地差分，E2E 传输见 Phase 2）
    injection    injection.PathA 显式上下文拼接（Path B 在 experimental 分支）
    privacy      privacy.PAMS   L1/L2 门控（L3 差分隐私按约定后置）
    feedback     AEE            自适应进化引擎（Phase 4）

架构约束：内容冻结 —— 任何模块只读记忆内容、只调结构参数，绝不改写。
"""

from .embeddings import HashingEmbedder, OpenAIEmbedder, cosine, embedder_identity
from .node import MemoryNode
from .store import MemoryStore
from .san import build_edges, build_entity_edges, extract_entities
from .retrieval import hybrid_search, search_with_reasons
from . import capabilities, clients, dss, handoff, heat, injection, privacy, sync_agent, transport, vault

__version__ = "0.15.0"

__all__ = [
    "MemoryNode",
    "MemoryStore",
    "HashingEmbedder",
    "OpenAIEmbedder",
    "cosine",
    "embedder_identity",
    "build_edges",
    "build_entity_edges",
    "extract_entities",
    "hybrid_search",
    "search_with_reasons",
    "capabilities",
    "clients",
    "dss",
    "handoff",
    "heat",
    "injection",
    "privacy",
    "transport",
]
