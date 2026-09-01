"""MCP Server：把记忆桥暴露为任意 MCP 客户端（Claude Code / Cursor / Cline …）的记忆工具。

这是"跨平台"能力的接入层：同一个记忆库，经由 MCP 协议被多个 AI 应用共享。
对应论文 UEP 的权限边界 —— 只开放 Add 与 Search/Preload 两类操作，
不提供任何改写记忆内容的工具（内容冻结原则）。

v0.8 工具面收敛（省 token）：memory_context 并入 memory_search（as_context
参数），工具从 4 个减为 3 个——每个工具描述都会常驻所有客户端会话。

启动：membridge mcp   （或 python -m membridge mcp）
环境变量：MEMBRIDGE_DB 指定记忆库路径；MEMBRIDGE_DEVICE 指定本机设备名。
"""

from __future__ import annotations

import json
import logging
import os
import sys
from typing import Optional

from . import capabilities
from .embeddings import Embedder, embedder_identity
from .node import MemoryNode
from .privacy import classify_scene, default_migration, preload_allowed
from .retrieval import hybrid_search
from .san import build_edges
from .store import MemoryStore, default_db_path

DB_ENV = "MEMBRIDGE_DB"
DEVICE_ENV = "MEMBRIDGE_DEVICE"

# add 端软引导阈值：超过该长度的记忆建议拆分（检索注入更省 token）
SOFT_LENGTH_HINT = 200


def open_store(store_path: Optional[str] = None) -> MemoryStore:
    """库路径与 CLI / init 同源：显式参数 > MEMBRIDGE_DB > ~/.membridge/memory.db。

    v0.8 修复：不再退回 CWD 相对 "membridge.db"——MCP server 从任意目录启动
    都会在该目录生成游离库，破坏「一台设备一份全局记忆库」语义。
    """
    db = store_path or default_db_path()
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
    embedder = embedder or capabilities.best_embedder()
    if not store._get_meta("embedder_id"):
        with store.transaction():
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
    def memory_add(text: str, tags: str = "", migration: str = "",
                   kind: str = "") -> str:
        """写入一条跨设备记忆：一句话一条最省 token；tags 逗号分隔；migration 可选 local/edge/cloud（默认自动）；kind 可选 fact（事实）/procedure（经验）/handover（交接卡：goal:/done:/failed:/next:/refs: 行前缀，新卡自动取代旧卡并常驻注入的工作台）。"""
        node = MemoryNode(
            content=text,
            embedding=embedder.embed(text),
            tags=[t.strip() for t in tags.split(",") if t.strip()],
            scene=classify_scene(text),
            device=store.device_name,
            migration=migration.strip() or default_migration(text),
            kind=kind.strip() if kind.strip() in ("fact", "procedure", "handover") else "",
        )
        with store.transaction():
            store.add(node)
            build_edges(store, embedder, only_new=node)
        msg = f"已记忆（{node.node_id}，场景 {node.scene}，迁移 {node.migration}）"
        if node.kind == "handover":
            from .handoff import summary

            msg += f"。工作台已切到这张交接卡：{summary(node)}"
        if len(text) > SOFT_LENGTH_HINT:
            msg += (
                f"。提示：本条超过 {SOFT_LENGTH_HINT} 字，"
                "下次建议拆成一句话一条，检索时更省 token、更准"
            )
        return msg

    @mcp.tool()
    def memory_search(query: str, k: int = 5, as_context: bool = False,
                      budget: int = 0, scope: str = "") -> str:
        """检索记忆（三路混合，弱命中已过滤）；已知记忆在哪可用 scope 直达（如 tag:dev / kind:procedure / kind:handover）；as_context=true 返回带预算可注入块（最新交接卡恒定注入在工作台小节），无高质量命中明确告知不注入。"""
        hits = hybrid_search(store, embedder, query, k=k, scope=scope)
        if as_context:
            from .handoff import workbench, workbench_block
            from .injection import serialize

            active = workbench(store)
            nodes = (n for n, _ in hits
                     if not (active and n.node_id == active.node_id))
            return serialize(nodes, max_chars=budget or 1500,
                             workbench=workbench_block(store))
        if not hits:
            return "（暂无相关记忆——本轮不注入，保持沉默）"
        return "\n".join(
            f"[{i + 1}]（相关度 {s:.3f}）{n.content}" for i, (n, s) in enumerate(hits)
        )

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
    # stdio 模式下 stdout 是 MCP 协议通道：日志必须走 stderr
    logging.basicConfig(
        level=logging.INFO,
        stream=sys.stderr,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    settings = {}
    if host:
        settings["host"] = host
    if port:
        settings["port"] = port
    create_server(**settings).run(transport=transport)


if __name__ == "__main__":
    main()
