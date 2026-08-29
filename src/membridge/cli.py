"""membridge 命令行入口。

示例：
  membridge add "用户在调试 membridge 的 DSS 同步模块" --tags dev,project
  membridge search "DSS" -k 3
  membridge context "继续早上的推理"
  membridge preload 我的手机
  membridge delta C:/sync/phone.db --out delta.json   # 生成 → 另一设备的差异包
  membridge apply delta.json                          # 并入差异包
  membridge stats
  membridge mcp                                       # 启动 MCP server
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import List, Optional

from . import dss, heat, injection
from .embeddings import HashingEmbedder
from .node import MemoryNode
from .privacy import classify_scene, default_migration, preload_allowed
from .san import build_edges
from .store import MemoryStore


def _utf8_console() -> None:
    """Windows 控制台默认 GBK，统一按 UTF-8 输出中文。"""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8")
            except Exception:  # pragma: no cover
                pass


def _open_store(args: argparse.Namespace) -> MemoryStore:
    return MemoryStore(args.db, device=args.device)


def cmd_add(args: argparse.Namespace) -> int:
    store = _open_store(args)
    embedder = HashingEmbedder()
    node = MemoryNode(
        content=args.text,
        embedding=embedder.embed(args.text),
        tags=[t.strip() for t in (args.tags or "").split(",") if t.strip()],
        scene=args.scene or classify_scene(args.text),
        device=args.device or store.device_name,
        migration=args.migration or default_migration(args.text),
    )
    store.add(node)
    new_edges = build_edges(store, embedder)
    print(f"已记忆 {node.node_id}（场景 {node.scene}，迁移 {node.migration}，新增关联边 {len(new_edges)} 条）")
    return 0


def cmd_search(args: argparse.Namespace) -> int:
    store = _open_store(args)
    hits = store.search(HashingEmbedder().embed(args.query), k=args.k)
    if not hits:
        print("（暂无相关记忆）")
        return 0
    for i, (n, s) in enumerate(hits, 1):
        print(f"[{i}]（相似度 {s:.2f}）{n.content}")
    return 0


def cmd_context(args: argparse.Namespace) -> int:
    store = _open_store(args)
    hits = store.search(HashingEmbedder().embed(args.query), k=args.k)
    print(injection.serialize(n for n, _ in hits))
    return 0


def cmd_preload(args: argparse.Namespace) -> int:
    store = _open_store(args)
    cands = heat.preload_candidates(store, allowed=preload_allowed, k=args.k)
    if not cands:
        print("（当前无可预加载的记忆）")
        return 0
    print(f"将向设备「{args.target}」预加载 {len(cands)} 条（PAMS 门控已通过）：")
    for n in cands:
        print(f"- {n.content}（热度 {heat.heat(n):.2f}，迁移 {n.migration}）")
    return 0


def cmd_delta(args: argparse.Namespace) -> int:
    local = _open_store(args)
    remote = MemoryStore(args.remote_db)
    delta = dss.compute_delta(local, remote)
    payload = delta.to_json()
    full = json.dumps([n.to_dict() for n in local.all_nodes()], ensure_ascii=False)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(payload)
        print(f"差异包已写入 {args.out}")
    else:
        print(payload)
    ratio = (len(payload) / len(full) * 100) if full else 0.0
    print(
        f"节点 {len(delta.nodes)} 条，边 {len(delta.edges)} 条；"
        f"载荷 {len(payload)} 字节，为全量同步（{len(full)} 字节）的 {ratio:.1f}%"
    )
    return 0


def cmd_apply(args: argparse.Namespace) -> int:
    store = _open_store(args)
    with open(args.file, "r", encoding="utf-8") as f:
        delta = dss.Delta.from_json(f.read())
    result = dss.apply_delta(store, delta)
    print(
        f"来自 {delta.from_device} 的差异包已并入：新增节点 {result['nodes_added']}，"
        f"指纹去重跳过 {result['nodes_skipped']}，应用边 {result['edges_applied']}"
    )
    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    store = _open_store(args)
    for key, value in store.stats().items():
        print(f"{key}: {value}")
    return 0


def cmd_mcp(args: argparse.Namespace) -> int:  # noqa: ARG001
    from .mcp_server import main as mcp_main

    mcp_main()
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    _utf8_console()
    parser = argparse.ArgumentParser(
        prog="membridge",
        description="记忆桥 MemoryBridge — 跨设备、跨平台的 AI 共享记忆层",
    )
    parser.add_argument("--db", default="membridge.db", help="记忆库 SQLite 文件路径")
    parser.add_argument("--device", default=None, help="本机设备名（首次使用时写入记忆库）")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("add", help="写入一条记忆")
    p.add_argument("text")
    p.add_argument("--tags", default="", help="逗号分隔标签")
    p.add_argument("--scene", default=None, help="场景域（默认自动分类）")
    p.add_argument("--migration", default=None, help="迁移标签 local/edge/cloud（默认自动判定）")
    p.set_defaults(func=cmd_add)

    p = sub.add_parser("search", help="语义检索记忆")
    p.add_argument("query")
    p.add_argument("-k", type=int, default=5)
    p.set_defaults(func=cmd_search)

    p = sub.add_parser("context", help="输出 Path A 记忆上下文块")
    p.add_argument("query")
    p.add_argument("-k", type=int, default=5)
    p.set_defaults(func=cmd_context)

    p = sub.add_parser("preload", help="列出可预加载到目标设备的记忆")
    p.add_argument("target", help="目标设备名")
    p.add_argument("-k", type=int, default=heat.PRELOAD_BUDGET)
    p.set_defaults(func=cmd_preload)

    p = sub.add_parser("delta", help="生成本库 → 另一设备的 DSS 差异包")
    p.add_argument("remote_db", help="对端设备记忆库路径（本机模拟）")
    p.add_argument("--out", default=None, help="差异包输出文件（默认打印）")
    p.set_defaults(func=cmd_delta)

    p = sub.add_parser("apply", help="把 DSS 差异包并入本库")
    p.add_argument("file", help="差异包 JSON 文件")
    p.set_defaults(func=cmd_apply)

    p = sub.add_parser("stats", help="记忆库统计")
    p.set_defaults(func=cmd_stats)

    p = sub.add_parser("mcp", help="启动 MCP server（供 Claude Code / Cursor 等接入）")
    p.set_defaults(func=cmd_mcp)

    args = parser.parse_args(argv)
    return args.func(args)
