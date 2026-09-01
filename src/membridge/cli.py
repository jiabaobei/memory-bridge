"""membridge 命令行入口。

示例：
  membridge add "用户在调试 membridge 的 DSS 同步模块" --tags dev,project
  membridge search "DSS" -k 3
  membridge context "继续早上的推理"
  membridge preload 我的手机
  membridge delta C:/sync/phone.db --out delta.json   # 生成 → 另一设备的差异包
  membridge apply delta.json                          # 并入差异包
  membridge stats
  membridge rebuild-edges                # 全量重建语义关联边（常规 add 只增量建边）
  membridge mcp                                       # 启动 MCP server
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import List, Optional

from . import capabilities, dss, heat, injection, privacy, retrieval, transport
from .embeddings import HashingEmbedder, embedder_identity
from .node import MemoryNode
from .privacy import classify_scene, default_migration, preload_allowed
from .san import build_edges, build_entity_edges
from .store import MemoryStore, default_db_path


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
    embedder = capabilities.best_embedder()
    node = MemoryNode(
        content=args.text,
        embedding=embedder.embed(args.text),
        tags=[t.strip() for t in (args.tags or "").split(",") if t.strip()],
        scene=args.scene or classify_scene(args.text),
        device=args.device or store.device_name,
        migration=args.migration or default_migration(args.text),
        kind=(args.kind or "").strip(),
    )
    # v0.8：add + 增量建边单事务提交；只算新节点与既有节点的关联（O(n)）
    with store.transaction():
        if not store._get_meta("embedder_id"):
            store._set_meta("embedder_id", json.dumps(embedder_identity(embedder), ensure_ascii=False))
        store.add(node)
        new_edges = build_edges(store, embedder, only_new=node)
        # v0.14：确定性锚点边（共享同一代码符号/文件路径/仓库/标签即连边）
        ent_edges = build_entity_edges(store, node)
    extra = f"，其中锚点边 {len(ent_edges)} 条" if ent_edges else ""
    print(f"已记忆 {node.node_id}（场景 {node.scene}，迁移 {node.migration}，"
          f"新增关联边 {len(new_edges)} 条{extra}）")
    return 0


def cmd_search(args: argparse.Namespace) -> int:
    store = _open_store(args)
    hits = retrieval.hybrid_search(store, capabilities.best_embedder(), args.query,
                                   k=args.k, scope=getattr(args, "scope", ""))
    if not hits:
        if getattr(args, "scope", ""):
            print("（该范围内暂无相关记忆）")
        else:
            print("（暂无相关记忆——已记入缺口，membridge doctor 可查看）")
        return 0
    for i, (n, s) in enumerate(hits, 1):
        kind_tag = f"[{n.kind}] " if n.kind else ""
        print(f"[{i}]（相关度 {s:.3f}）{kind_tag}{n.content}")
    return 0


def cmd_context(args: argparse.Namespace) -> int:
    from .handoff import workbench_block

    store = _open_store(args)
    hits = retrieval.search_with_reasons(
        store, capabilities.best_embedder(), args.query,
        k=args.k, scope=getattr(args, "scope", ""),
    )
    # v0.14：注入时标注极短召回理由，便于判断该不该信这条记忆
    reasons = {n.node_id: why for n, _, why in hits}
    # v0.15：工作台恒定注入——交接卡是状态声明，不走相关性检索；
    # 工作台已含最新交接卡，检索命中里去重避免同一条出现两次
    from .handoff import workbench, workbench_block

    wb = workbench_block(store)
    active = workbench(store)
    nodes = [n for n, _, _ in hits
             if not (active and n.node_id == active.node_id)]
    print(injection.serialize(nodes, reasons=reasons, workbench=wb))
    return 0


def cmd_handoff(args: argparse.Namespace) -> int:  # noqa: ARG001
    """查看当前工作台：最新交接卡的原文与生效状态（取代是推导出来的）。"""
    from .handoff import (HANDOFF_STALE_HOURS, age_hours, latest_handoff,
                          summary, TEMPLATE)

    store = _open_store(args)
    card = latest_handoff(store)
    if card is None:
        print("还没有交接卡——任务告一段落、上下文将满、或要切换设备前，"
              "把这一阶段写成一张：")
        print()
        print(f'membridge add "{TEMPLATE}" --kind handover')
        print()
        print("新卡自动取代旧卡；交接卡的正文永远保持原文，不会被改写。")
        return 0
    hours = age_hours(card)
    if hours > HANDOFF_STALE_HOURS:
        print(f"⚠️ 最新交接卡已过期（{hours / 24:.0f} 天前，来自 {card.device}）"
              "——过期工作台不再恒定注入，只走检索：")
    else:
        print(f"当前工作台（{hours:.1f} 小时前，来自 {card.device}）：")
    print()
    print(card.content)
    print()
    print(f"摘要：{summary(card)}")
    return 0


def cmd_handoff_hint(args: argparse.Namespace) -> int:  # noqa: ARG001
    """打印可粘贴进宿主指令文件的常驻交接提示（自愿启用，本工具不代写）。"""
    from .handoff import handoff_hint

    print("把下面这一段，粘贴进你 AI 助手的常驻指令文件即可：")
    print("（Claude Code → CLAUDE.md；Codex / 通用 → AGENTS.md；Cursor → 规则文件）")
    print()
    print(handoff_hint())
    return 0


def cmd_preload(args: argparse.Namespace) -> int:
    store = _open_store(args)
    if getattr(args, "cluster", False):
        cands = heat.preload_cluster(store, allowed=preload_allowed, k=args.k)
        mode = "整簇"
    else:
        cands = heat.preload_candidates(store, allowed=preload_allowed, k=args.k)
        mode = "热度"
    if not cands:
        print("（当前无可预加载的记忆）")
        return 0
    print(f"将向设备「{args.target}」预加载 {len(cands)} 条（{mode}，PAMS 门控已通过）：")
    for n in cands:
        print(f"- {n.content}（热度 {heat.heat(n):.2f}，迁移 {n.migration}）")
    return 0


def _safe_delta_file(p: str, *, for_write: bool,
                     allowed_bases: Optional[List[str]] = None) -> str:
    """差异包路径校验：禁止 '..' 上跳、必须 .json；写入且提供 allowed_bases 时做包含性校验。"""
    raw = (p or "").strip()
    if not raw or ".." in raw.replace("\\", "/").split("/"):
        raise SystemExit(f"路径不允许包含 '..' 上跳成分：{raw}")
    norm = os.path.normpath(os.path.abspath(os.path.expanduser(raw)))
    if os.path.splitext(norm)[1].lower() != ".json":
        raise SystemExit(f"差异包必须是 .json 文件：{norm}")
    if for_write and allowed_bases:
        bases = [os.path.realpath(os.path.abspath(b)) for b in allowed_bases]

        def _within(base: str, target: str) -> bool:
            try:
                return os.path.commonpath([base, target]) == base
            except ValueError:
                return False  # Windows 跨盘符无公共父目录：仅该基座不匹配，不影响其他基座

        target = os.path.realpath(norm)
        if not any(_within(b, target) for b in bases):
            raise SystemExit(
                "写入位置必须在记忆库目录或当前目录内（防路径穿越）："
                + " 或 ".join(set(bases))
            )
        if os.path.exists(norm):
            raise SystemExit(f"目标已存在，拒绝覆盖：{norm}")
    elif not for_write and not os.path.isfile(norm):
        raise SystemExit(f"差异包不存在：{norm}")
    return norm


def cmd_delta(args: argparse.Namespace) -> int:
    local = _open_store(args)
    remote = MemoryStore(args.remote_db)
    delta = dss.compute_delta(local, remote)
    payload = delta.to_json()
    full = json.dumps([n.to_dict() for n in local.all_nodes()], ensure_ascii=False)
    if args.out:
        out_path = _safe_delta_file(
            args.out, for_write=True,
            allowed_bases=[os.path.dirname(os.path.abspath(local.path)), os.getcwd()],
        )
        Path(out_path).write_text(payload, encoding="utf-8")
        print(f"差异包已写入 {out_path}")
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
    in_path = os.path.normpath(_safe_delta_file(args.file, for_write=False))
    with open(in_path, "r", encoding="utf-8") as f:
        delta = dss.Delta.from_json(f.read())
    result = dss.apply_delta(store, delta)
    if result.get("rejected"):
        print(f"已拒绝该差异包：嵌入器不一致"
              f"（本库 {result.get('local_fp')} / 来包 {result.get('incoming_fp')}）——"
              f"两端必须使用同一嵌入模型")
        return 2
    print(
        f"来自 {delta.from_device} 的差异包已并入：新增节点 {result['nodes_added']}，"
        f"指纹去重跳过 {result['nodes_skipped']}，应用边 {result['edges_applied']}"
    )
    return 0


def _resolve_passphrase(args: argparse.Namespace) -> Optional[str]:
    """命令行优先，其次环境变量 MEMBRIDGE_PASSPHRASE（便于自动化同步）。"""
    return args.passphrase or os.environ.get("MEMBRIDGE_PASSPHRASE")


def cmd_publish(args: argparse.Namespace) -> int:
    store = _open_store(args)
    passphrase = _resolve_passphrase(args)
    if not passphrase and not args.plaintext:
        print("出于隐私安全，写入网盘默认必须加密：请加 --passphrase <口令>，"
              "或设置环境变量 MEMBRIDGE_PASSPHRASE，"
              "或显式加 --plaintext 放弃加密（不推荐）。")
        return 2
    tr = transport.FolderTransport(args.dir, store)
    try:
        path = tr.publish(
            passphrase=passphrase,
            plaintext=args.plaintext,
            embedder_info=embedder_identity(capabilities.best_embedder()),
            force=getattr(args, "force", False),
        )
    except ImportError as exc:
        print(str(exc))
        return 2
    if path is None:
        print("没有需要发布的新记忆。")
        if not getattr(args, "force", False):
            print("（若云盘侧差分包已丢失，可加 --force 重发全量）")
    else:
        print(f"差分包已写入通道：{path}")
    if tr.channel_status == "mismatch":
        print("⚠️ 通道身份不一致：本机记录的通道 ID 与云盘里的身份证不符"
              "（疑似通道分裂，运行 membridge channel 查看详情）")
    return 0


def cmd_fetch(args: argparse.Namespace) -> int:
    store = _open_store(args)
    tr = transport.FolderTransport(args.dir, store)
    result = tr.fetch(passphrase=_resolve_passphrase(args))
    for fn, src, r in result["applied"]:
        if r.get("rejected"):
            print(f"已拒绝来自 {src} 的差分包 {fn}：嵌入器不一致"
                  f"（本库 {r.get('local_fp')} / 来包 {r.get('incoming_fp')}）——"
                  f"两端必须使用同一嵌入模型，见 docs/RFC-001-architecture.md §4")
            continue
        print(f"已并入来自 {src} 的差分包 {fn}："
              f"新增节点 {r['nodes_added']}，去重跳过 {r['nodes_skipped']}，应用边 {r['edges_applied']}")
    for fn, reason in result["skipped"]:
        print(f"跳过 {fn}：{reason}")
    for fn, reason in result.get("errors", []):
        print(f"环境错误 {fn}（包已保留，下次 fetch 自动重试）：{reason}")
    if not result["applied"] and not result["skipped"] and not result.get("errors"):
        print("通道中暂无新差分包。")
    if tr.channel_status == "mismatch":
        print("⚠️ 通道身份不一致：本机记录的通道 ID 与云盘里的身份证不符"
              "（疑似通道分裂，运行 membridge channel 查看详情）")
    return 0


def cmd_rebuild_edges(args: argparse.Namespace) -> int:
    """全量重建语义关联边（v0.8：常规 add 只增量建边，这里是显式重建出口）。"""
    store = _open_store(args)
    embedder = capabilities.best_embedder()
    with store.transaction():
        added = build_edges(store, embedder, min_weight=args.min_weight)
    print(
        f"全量重建完成：当前 {store.count_edges()} 条关联，"
        f"本次新写 {len(added)} 条（已有且权重未变的边不重写）"
    )
    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    store = _open_store(args)
    for key, value in store.stats().items():
        print(f"{key}: {value}")
    return 0


def cmd_channel(args: argparse.Namespace) -> int:  # noqa: ARG001
    """通道一致性体检（v0.13）：本机通道 / 通道身份证 / 通道内设备是否同一个。"""
    from . import channel

    store = _open_store(args)
    netdisk = store.netdisk
    if not netdisk:
        print("尚未配置云盘通道：请先运行 membridge init。")
        return 2
    print(f"本机通道: {netdisk}")
    print(f"本机通道 ID: {store.channel_id or '（尚未认领，首次同步时自动认领）'}")
    if not os.path.isdir(netdisk):
        print("⚠️ 通道目录不存在（云盘未登录 / 未开启同步 / 路径已变更）——"
              "跨设备同步当前不可用")
        return 1
    manifest = channel.read_manifest(netdisk)
    if manifest:
        print(f"通道身份证: {manifest['channel_id']}"
              f"（由设备「{manifest.get('creator')}」创建于 {manifest.get('created')}）")
        if store.channel_id and store.channel_id != manifest["channel_id"]:
            print("⚠️ 本机通道 ID 与云盘里的身份证不一致——疑似通道分裂："
                  "本设备与其他设备可能指向了不同的云盘/目录")
        else:
            print("✅ 通道身份一致：本机与其他设备指向同一个通道")
    else:
        print("通道身份证尚未创建（首次发布时自动创建；也可立即 membridge publish）")
    others = channel.peers(netdisk, exclude=store.device_name)
    print(f"通道里出现过的其他设备: {'、'.join(others)}" if others
          else "通道里还没见过其他设备的差分包")
    warning = channel.channel_warning(store)
    if warning:
        print(f"⚠️ 历史分裂告警（{warning.get('seen')}）："
              f"本机 {warning.get('local')} vs 通道 {warning.get('remote')}")
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    """导出人类可读的 Markdown 视图（只读渲染，永不回写——内容冻结）。"""
    from .export import render_markdown

    store = _open_store(args)
    text = render_markdown(store)
    if args.out:
        out_path = os.path.normpath(
            os.path.abspath(os.path.expanduser(args.out.strip()))
        )
        if os.path.exists(out_path) and not args.force:
            print(f"目标已存在，拒绝覆盖：{out_path}（确要覆盖请加 --force）")
            return 2
        Path(out_path).write_text(text, encoding="utf-8")
        print(f"已导出 {store.count_nodes()} 条记忆 → {out_path}")
        print("提示：这是只读视图，手工编辑它不会写回记忆库。")
    else:
        print(text)
    return 0


RECALL_HINT = (
    "开始任务前，先用 memory_search（as_context=true）检索与当前任务相关的"
    "跨设备记忆并采用；若返回「本轮不干预」，不要编造记忆。"
)


def cmd_recall_hint(args: argparse.Namespace) -> int:  # noqa: ARG001
    """打印可粘贴进宿主指令文件的常驻召回提示（自愿启用，本工具不代写）。"""
    print("把下面这一行，粘贴进你 AI 助手的常驻指令文件即可：")
    print("（Claude Code → CLAUDE.md；Codex / 通用 → AGENTS.md；Cursor → 规则文件）")
    print()
    print(RECALL_HINT)
    return 0


def cmd_gateway(args: argparse.Namespace) -> int:
    """手机/平板接入网关（路线 A：瘦客户端 + 基站；口令强制，详见 docs/mobile.md）。"""
    import socket

    from .gateway import create_gateway_server, resolve_token, serve_gateway
    from .mcp_server import open_store

    store = open_store(args.db if args.db != "membridge.db" else None)
    embedder = capabilities.best_embedder()
    token = resolve_token(store, token_arg=args.token,
                          env_token=os.environ.get("MEMBRIDGE_TOKEN"))
    allow = [p.strip() for p in (args.allow or "").split(",") if p.strip()] or None
    server = create_gateway_server(store, embedder, token,
                                   host=args.host, port=args.port, allow=allow)

    lan_ip = args.host
    if args.host in ("0.0.0.0", "::"):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            lan_ip = s.getsockname()[0]
            s.close()
        except OSError:
            lan_ip = "127.0.0.1"
    scheme = "https" if args.cert else "http"
    print(f"记忆桥网关已启动（设备 {store.device_name}）")
    print(f"  手机/平板访问：{scheme}://{lan_ip}:{args.port}")
    print(f"  访问口令：{token}")
    if allow:
        print(f"  IP 白名单：{', '.join(allow)}（其余来源一律 403，口令仍是第一道门）")
    print("  （浏览器打开即内置随身记页面；iOS 快捷指令 / 任意 HTTP 客户端")
    print("    调 /add、/search，鉴权头 Authorization: Bearer <口令>）")
    if not args.cert:
        print("  ⚠️ 当前为明文 HTTP：仅限局域网 / Tailscale 等自持加密网络内使用；")
        print("    跨网可达请改用 --cert/--key 启用 TLS，绝不开公网明文端口")
    try:
        serve_gateway(server, certfile=args.cert, keyfile=args.key)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        store.close()
    return 0


def cmd_gateway_token(args: argparse.Namespace) -> int:
    """显示网关访问口令（首次查看时自动生成并托管，同 show-passphrase 哲学）。"""
    from .gateway import resolve_token
    from .mcp_server import open_store

    store = open_store(args.db if args.db != "membridge.db" else None)
    token = resolve_token(store, env_token=os.environ.get("MEMBRIDGE_TOKEN"))
    store.close()
    print("网关访问口令（配置手机快捷指令 / 浏览器页面时使用）：")
    print(token)
    print("\n提示：请勿泄露；泄露后用 membridge gateway --token <新口令> 更换。")
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
            skip_netdisk=args.skip_netdisk,
            no_autosync=args.no_autosync,
            all_mode=args.all,
        )
    )


def cmd_autosync(args: argparse.Namespace) -> int:
    from .sync_agent import run_autosync

    db = args.db if args.db != "membridge.db" else None
    return run_autosync(store_path=db, passphrase=args.passphrase)


def cmd_set_passphrase(args: argparse.Namespace) -> int:  # noqa: ARG001
    import getpass

    from .store import default_db_path
    from .vault import save_passphrase, supported

    if not supported():
        print("口令托管目前仅支持 Windows。")
        return 2
    store = MemoryStore(default_db_path())
    if not store.netdisk:
        print("尚未配置云盘通道：请先运行 membridge init。")
        store.close()
        return 2
    p1 = getpass.getpass("设置自动同步口令（输入时不显示）: ")
    p2 = getpass.getpass("再输入一次确认: ")
    if not p1 or p1 != p2:
        print("两次输入为空或不一致，未保存。")
        store.close()
        return 2
    save_passphrase(store, p1)
    print("✅ 口令已更新（自动同步立即使用新口令；其他设备取回需改用同一新口令）。")
    store.close()
    return 0


def cmd_show_passphrase(args: argparse.Namespace) -> int:  # noqa: ARG001
    """配对新设备时展示系统托管的同步口令（AI 替用户记住，需要时才看）。"""
    from .store import default_db_path
    from .vault import load_passphrase

    store = MemoryStore(default_db_path())
    key = load_passphrase(store)
    store.close()
    if not key:
        print("尚未配置：请先运行 membridge init。")
        return 2
    print("本机的自动同步口令是（配对新设备时，在对方设备输入同一个）：")
    print(key)
    print("\n提示：请仅在配对新设备时使用，勿泄露给他人。")
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:  # noqa: ARG001
    from .doctor import run_doctor

    return run_doctor()


def main(argv: Optional[List[str]] = None) -> int:
    _utf8_console()
    parser = argparse.ArgumentParser(
        prog="membridge",
        description="记忆桥 MemoryBridge — 跨设备、跨平台的 AI 共享记忆层",
    )
    parser.add_argument(
        "--db",
        default=default_db_path(),
        help="记忆库 SQLite 文件路径（默认同 init：环境变量 MEMBRIDGE_DB，"
        "其次 ~/.membridge/memory.db）",
    )
    parser.add_argument("--device", default=None, help="本机设备名（首次使用时写入记忆库）")
    from . import __version__

    parser.add_argument("--version", action="version", version=f"membridge {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("add", help="写入一条记忆")
    p.add_argument("text")
    p.add_argument("--tags", default="", help="逗号分隔标签")
    p.add_argument("--scene", default=None, help="场景域（默认自动分类）")
    p.add_argument("--migration", default=None, help="迁移标签 local/edge/cloud（默认自动判定）")
    p.add_argument("--kind", default="", choices=["", "fact", "procedure", "handover"],
                   help="可选标注：fact 稳定事实 / procedure 试过什么、结果 / "
                        "handover 交接卡（goal/done/failed/next/refs 行前缀约定）")
    p.set_defaults(func=cmd_add)

    p = sub.add_parser("search", help="语义检索记忆")
    p.add_argument("query")
    p.add_argument("-k", type=int, default=5)
    p.add_argument("--scope", default="",
                   help="可选范围直达：已知记忆在哪时先过滤再检索"
                        "（如 tag:dev / scene:work / kind:procedure / kind:handover）")
    p.set_defaults(func=cmd_search)

    p = sub.add_parser("context", help="输出 Path A 记忆上下文块")
    p.add_argument("query")
    p.add_argument("-k", type=int, default=5)
    p.add_argument("--scope", default="",
                   help="可选范围直达：同 search --scope")
    p.set_defaults(func=cmd_context)

    p = sub.add_parser("preload", help="列出可预加载到目标设备的记忆")
    p.add_argument("target", help="目标设备名")
    p.add_argument("-k", type=int, default=heat.PRELOAD_BUDGET)
    p.add_argument("--cluster", action="store_true",
                   help="整簇预加载：取当前最热节点所在的记忆簇（v0.14）")
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
    p.add_argument(
        "--force",
        action="store_true",
        help="忽略本地「已发布」记录，重发全量。"
        "用于云盘侧差分包丢失后重建通道（否则记忆会被锁死、推不出去）",
    )
    p.set_defaults(func=cmd_publish)

    p = sub.add_parser("fetch", help="从同步文件夹取回并应用其他设备的差分包")
    p.add_argument("--dir", required=True)
    p.add_argument("--passphrase", default=None, help="端到端加密口令（与发布端一致）")
    p.set_defaults(func=cmd_fetch)

    p = sub.add_parser("stats", help="记忆库统计")
    p.set_defaults(func=cmd_stats)

    p = sub.add_parser("channel",
                       help="通道一致性体检：本机与其他设备是否指向同一个云盘通道（v0.13）")
    p.set_defaults(func=cmd_channel)

    p = sub.add_parser("export", help="导出人类可读的 Markdown 视图（只读，不回写）")
    p.add_argument("--out", default=None, help="输出 .md 文件路径（默认打印到屏幕）")
    p.add_argument("--force", action="store_true", help="目标已存在时允许覆盖")
    p.set_defaults(func=cmd_export)

    p = sub.add_parser("recall-hint",
                       help="打印常驻召回提示（粘贴进 CLAUDE.md / AGENTS.md，自愿启用）")
    p.set_defaults(func=cmd_recall_hint)

    p = sub.add_parser("handoff",
                       help="查看当前工作台：最新交接卡原文与生效状态（v0.15）")
    p.set_defaults(func=cmd_handoff)

    p = sub.add_parser("handoff-hint",
                       help="打印常驻交接提示（粘贴进 CLAUDE.md / AGENTS.md，自愿启用）")
    p.set_defaults(func=cmd_handoff_hint)

    p = sub.add_parser(
        "rebuild-edges",
        help="全量重建语义关联边（常规 add 已增量建边；调整 λ/阈值后或异常时使用）",
    )
    p.add_argument("--min-weight", type=float, default=0.15,
                   help="低于该权重的关联不落库（默认 0.15）")
    p.set_defaults(func=cmd_rebuild_edges)

    p = sub.add_parser("gateway",
                       help="手机/平板接入网关（基站模式：口令保护的 HTTP 接入，详见 docs/mobile.md）")
    p.add_argument("--host", default="0.0.0.0", help="监听地址（默认 0.0.0.0，局域网可访问）")
    p.add_argument("--port", type=int, default=8766)
    p.add_argument("--token", default=None,
                   help="访问口令（默认：环境变量 MEMBRIDGE_TOKEN，其次库内托管口令）")
    p.add_argument("--allow", default=None,
                   help="可选 IP 白名单：逗号分隔的 IP 或前缀（如 192.168.1.,100.64.）；"
                        "不匹配的来源一律 403")
    p.add_argument("--cert", default=None, help="TLS 证书（跨网可达时启用，配合 --key）")
    p.add_argument("--key", default=None, help="TLS 私钥")
    p.set_defaults(func=cmd_gateway)

    p = sub.add_parser("gateway-token", help="显示网关访问口令（首次自动生成并托管）")
    p.set_defaults(func=cmd_gateway_token)

    p = sub.add_parser("mcp", help="启动 MCP server（供 Claude Code / Cursor 等接入）")
    p.add_argument("--http", action="store_true",
                   help="以远程 HTTP 模式运行（SSE/Streamable HTTP，供扣子 Coze 等平台经 URL 接入）")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--transport", default="streamable-http",
                   choices=["streamable-http", "sse"])
    p.set_defaults(func=cmd_mcp)

    p = sub.add_parser("init",
                       help="一键配置：云盘通道自动选定 + 一次性口令 + 平台接入 + 自动同步计划任务")
    p.add_argument("--all", action="store_true",
                   help="非交互：配置所有检测到的平台，并打印其余平台的手动指南")
    p.add_argument("--netdisk-dir", default=None,
                   help="直接指定云盘/同步文件夹路径（跳过询问）")
    p.add_argument("--skip-netdisk", action="store_true",
                   help="跳过云盘配置（仅单设备使用）")
    p.add_argument("--no-autosync", action="store_true",
                   help="不注册自动同步计划任务（默认注册，每 15 分钟自动同步）")
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("autosync",
                       help="自动同步：重要记忆立即上云、普通记忆批量上云 + 取回其他设备记忆")
    p.add_argument("--passphrase", default=None,
                   help="口令（已托管到本机保险库时无需提供；供计划任务外的手动使用）")
    p.set_defaults(func=cmd_autosync)

    p = sub.add_parser("set-passphrase",
                       help="手动设置/修改自动同步口令（通常无需使用：init 会自动生成并托管）")
    p.set_defaults(func=cmd_set_passphrase)

    p = sub.add_parser("show-passphrase",
                       help="配对新设备时查看系统托管的同步口令")
    p.set_defaults(func=cmd_show_passphrase)

    p = sub.add_parser("doctor", help="环境自检：版本 / 记忆库 / 可选依赖 / 平台检测")
    p.set_defaults(func=cmd_doctor)

    args = parser.parse_args(argv)
    return args.func(args)
