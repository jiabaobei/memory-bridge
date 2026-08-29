"""MCP Server：把记忆桥暴露为任意 MCP 客户端（Claude Code / Cursor / Cline …）的记忆工具。

这是"跨平台"能力的接入层：同一个记忆库，经由 MCP 协议被多个 AI 应用共享。
对应论文 UEP 的权限边界 —— 只开放 Add 与 Search/Preload 两类操作，
不提供任何改写记忆内容的工具（内容冻结原则）。

启动：membridge mcp   （或 python -m membridge mcp）
环境变量：MEMBRIDGE_DB 指定记忆库路径；MEMBRIDGE_DEVICE 指定本机设备名。
"""

from __future__ import annotations

import json
import os
from typing import Optional

from . import capabilities
from .embeddings import Embedder, HashingEmbedder, embedder_identity
from .node import MemoryNode
from .privacy import classify_scene, default_migration, preload_allowed
from .san import build_edges
from .store import MemoryStore

DB_ENV = "MEMBRIDGE_DB"
DEVICE_ENV = "MEMBRIDGE_DEVICE"


def open_store(store_path: Optional[str] = None) -> MemoryStore:
    db = store_path or os.environ.get(DB_ENV) or "membridge.db"
    store = MemoryStore(db)
    if store.device_name == "unknown":
        store.set_device(os.environ.get(DEVICE_ENV) or os.path.basename(db))
    return store


def create_server(
    store_path: Optional[str] = None,
    embedder: Optional[Embedder] = None,
    host: Optional[str] = None,
    port: Optional[int] = None,
):
    try:
        from mcp.server.fastmcp import FastMCP  # 延迟导入，保持核心零依赖
    except ImportError as exc:
        raise ImportError(
            f"MCP 依赖不可用：{exc}。请安装 mcp 1.x：pip install \"membridge[mcp]\""
        ) from exc

    store = open_store(store_path)
    embedder = capabilities.best_embedder()
    if not store._get_meta("embedder_id"):
        from .embeddings import embedder_identity

        store._set_meta(
            "embedder_id",
            json.dumps(embedder_identity(embedder), ensure_ascii=False),
        )

    settings = {}
    if host:
        settings["host"] = host
    if port:
        settings["port"] = port
    mcp = FastMCP("memory-bridge", **settings)

    @mcp.tool()
    def memory_add(text: str, tags: str = "", migration: str = "") -> str:
        """写入一条跨设备记忆（Add 阶段）。

        tags: 逗号分隔的标签；migration: 可选 local/edge/cloud（默认按内容自动判定）。
        """
        node = MemoryNode(
            content=text,
            embedding=embedder.embed(text),
            tags=[t.strip() for t in tags.split(",") if t.strip()],
            scene=classify_scene(text),
            device=store.device_name,
            migration=migration.strip() or default_migration(text),
        )
        store.add(node)
        build_edges(store, embedder)
        return f"已记忆（{node.node_id}，场景 {node.scene}，迁移 {node.migration}）"

    @mcp.tool()
    def memory_search(query: str, k: int = 5) -> str:
        """按语义检索记忆（Search 阶段），返回最相关的 k 条。"""
        hits = store.search(embedder.embed(query), k=k)
        if not hits:
            return "（暂无相关记忆）"
        return "\n".join(
            f"[{i + 1}]（相似度 {s:.2f}）{n.content}" for i, (n, s) in enumerate(hits)
        )

    @mcp.tool()
    def memory_context(query: str, k: int = 5) -> str:
        """获取可注入系统提示的跨设备记忆上下文块（Path A 显式注入）。"""
        from .injection import serialize

        hits = store.search(embedder.embed(query), k=k)
        return serialize(n for n, _ in hits)

    @mcp.tool()
    def memory_preload(target_device: str, k: int = 8) -> str:
        """列出可预加载到目标设备的记忆（TMT 热度排序 + PAMS 门控）。"""
        from .heat import preload_candidates

        cands = preload_candidates(store, allowed=preload_allowed, k=k)
        if not cands:
            return "（当前无可预加载的记忆）"
        head = f"将向设备「{target_device}」预加载 {len(cands)} 条："
        return head + "\n" + "\n".join(f"- {n.content}" for n in cands)

    return mcp


def main(host: Optional[str] = None, port: Optional[int] = None,
         transport: str = "stdio") -> None:
    settings = {}
    if host:
        settings["host"] = host
    if port:
        settings["port"] = port
    create_server(**settings).run(transport=transport)


if __name__ == "__main__":
    main()
