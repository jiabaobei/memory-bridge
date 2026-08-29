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

from . import dss, heat, injection, privacy, transport
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


def cmd_publish(args: argparse.Namespace) -> int:
    store = _open_store(args)
    if not args.passphrase and not args.plaintext:
        print("出于隐私安全，写入网盘默认必须加密：请加 --passphrase <口令>，"
              "或显式加 --plaintext 放弃加密（不推荐）。")
        return 2
    tr = transport.FolderTransport(args.dir, store)
    try:
        path = tr.publish(passphrase=args.passphrase, plaintext=args.plaintext)
    except ImportError as exc:
        print(str(exc))
        return 2
    if path is None:
        print("没有需要发布的新记忆。")
    else:
        print(f"差分包已写入通道：{path}")
    return 0


def cmd_fetch(args: argparse.Namespace) -> int:
    store = _open_store(args)
    tr = transport.FolderTransport(args.dir, store)
    result = tr.fetch(passphrase=args.passphrase)
    for fn, src, r in result["applied"]:
        print(f"已并入来自 {src} 的差分包 {fn}："
              f"新增节点 {r['nodes_added']}，去重跳过 {r['nodes_skipped']}，应用边 {r['edges_applied']}")
    for fn, reason in result["skipped"]:
        print(f"跳过 {fn}：{reason}")
    if not result["applied"] and not result["skipped"]:
        print("通道中暂无新差分包。")
    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    store = _open_store(args)
    for key, value in store.stats().items():
        print(f"{key}: {value}")
    return 0


def cmd_mcp(args: argparse.Namespace) -> int:
    from .mcp_server import main as mcp_main

    mcp_main(
        host=args.host if args.http else None,
        port=args.port if args.http else None,
        transport=args.transport if args.http else "stdio",
    )
    return 0


def cmd_init(args: argparse.Namespace) -> int:
    from .wizard import InitOptions, run_init

    # 全局 --db 的默认值是 "membridge.db"；init 在未显式指定时应走智能默认
    db = args.db if args.db != "membridge.db" else None
    return run_init(
        InitOptions(
            db=db,
            device=args.device,
            netdisk_dir=args.netdisk_dir,
            all_mode=args.all,
        )
    )


def cmd_doctor(args: argparse.Namespace) -> int:  # noqa: ARG001
    from .doctor import run_doctor

    return run_doctor()


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

    p = sub.add_parser("publish", help="把本设备未发布的记忆差分包写入同步文件夹（网盘中转）")
    p.add_argument("--dir", required=True, help="同步文件夹（百度网盘同步盘/坚果云/OneDrive/U盘/局域网共享）")
    p.add_argument("--passphrase", default=None, help="端到端加密口令（推荐，收发需一致）")
    p.add_argument("--plaintext", action="store_true", help="明文写入（不推荐，需显式确认）")
    p.set_defaults(func=cmd_publish)

    p = sub.add_parser("fetch", help="从同步文件夹取回并应用其他设备的差分包")
    p.add_argument("--dir", required=True)
    p.add_argument("--passphrase", default=None, help="端到端加密口令（与发布端一致）")
    p.set_defaults(func=cmd_fetch)

    p = sub.add_parser("stats", help="记忆库统计")
    p.set_defaults(func=cmd_stats)

    p = sub.add_parser("mcp", help="启动 MCP server（供 Claude Code / Cursor 等接入）")
    p.add_argument("--http", action="store_true",
                   help="以远程 HTTP 模式运行（SSE/Streamable HTTP，供扣子 Coze 等平台经 URL 接入）")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--transport", default="streamable-http",
                   choices=["streamable-http", "sse"])
    p.set_defaults(func=cmd_mcp)

    p = sub.add_parser("init",
                       help="一键接入本机检测到的 AI 平台（MCP 自动配置 / WorkBuddy 技能 / 可选网盘）")
    p.add_argument("--all", action="store_true",
                   help="非交互：配置所有检测到的平台，并打印其余平台的手动指南")
    p.add_argument("--netdisk-dir", default=None,
                   help="直接指定网盘/同步文件夹路径（跳过询问）")
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("doctor", help="环境自检：版本 / 记忆库 / 可选依赖 / 平台检测")
    p.set_defaults(func=cmd_doctor)

    args = parser.parse_args(argv)
    return args.func(args)
