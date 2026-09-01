"""membridge doctor：环境自检（版本、记忆库位置健康、可选依赖、平台检测）。

v0.8 新增「库位置健康」检查——真实故障教训：MEMBRIDGE_DB 指向临时/测试目录
时 doctor 仍报 ✅，直到磁盘清理把库清掉才发现。现在显式告警：
- 库位于 Temp/临时/生成目录
- 环境变量库与默认库并存（疑似记忆库分裂）
- 设备名未设置
"""

from __future__ import annotations

import importlib
import os
import re
import sys
from pathlib import Path

from . import clients


def _db_health_hints(db: str) -> list:
    """库位置健康启发式：返回告警列表（空 = 健康）。"""
    hints: list = []
    # 分段匹配，分隔符无关（/ 与 \ 混用均覆盖）
    parts = re.split(r"[\\/]+", db.lower())
    if any(
        p in ("temp", "tmp", "$recycle.bin") or p.startswith("membridge-gen") or p.startswith("tmp")
        for p in parts
    ):
        hints.append(
            "记忆库位于临时/生成目录（可能被系统清理，或属测试残留）。"
            "请运行 membridge init 重新配置，或把 MEMBRIDGE_DB 指向正式位置"
            "（如 ~/.membridge/memory.db）"
        )
    env_db = os.environ.get("MEMBRIDGE_DB")
    home_db = str(Path.home() / ".membridge" / "memory.db")
    if env_db and os.path.isfile(home_db) and \
            os.path.abspath(env_db).lower() != os.path.abspath(home_db).lower():
        from .store import MemoryStore

        try:
            h = MemoryStore(home_db)
            n = h.count_nodes()
            h.close()
        except Exception:
            n = 0
        if n:
            hints.append(
                f"默认位置 {home_db} 仍有 {n} 条记忆，与环境变量指定的库并存"
                "——疑似记忆库分裂。确认正式库后，把 MEMBRIDGE_DB 统一指向它"
            )
    return hints


def run_doctor(out=print) -> int:
    import membridge

    out(f"membridge 版本: {membridge.__version__}")
    out(f"Python: {sys.version.split()[0]}")

    from .store import default_db_path

    env_db = os.environ.get("MEMBRIDGE_DB")
    db = default_db_path()
    src = "来自环境变量 MEMBRIDGE_DB" if env_db else "默认位置 ~/.membridge/memory.db"
    out(f"记忆库（{src}）: {db}")

    warnings: list = _db_health_hints(db)

    if os.path.exists(db):
        from .store import MemoryStore

        s = MemoryStore(db)
        out(f"  ✅ 可用（{s.count_nodes()} 条记忆，{s.count_edges()} 条关联，设备 {s.device_name}）")
        if s.device_name == "unknown":
            warnings.append("设备名未设置（记忆来源无法标注）——运行 membridge init 或 --device 设置")
        if s.netdisk:
            out(f"  ☁️ 云盘通道: {s.netdisk}")
            out("     （跨设备同步就绪；发布/取回命令见 membridge init 输出）")
            # 通道健康（v0.13）：目录还在吗？本机与其他设备是否同一通道？
            if not os.path.isdir(s.netdisk):
                warnings.append(
                    "云盘通道目录不存在（云盘未登录 / 未开启同步 / 路径已变更）"
                    "——跨设备同步当前不可用，重新登录云盘或 membridge init 重配"
                )
            else:
                from . import channel as _channel

                m = _channel.read_manifest(s.netdisk)
                if m and s.channel_id and m["channel_id"] != s.channel_id:
                    warnings.append(
                        "通道身份不一致：本机通道 ID 与云盘通道里的身份证（channel.json）"
                        "不符——疑似与其他设备分裂到了不同通道，运行 membridge channel 查看"
                    )
        else:
            out("  ⚠️ 云盘通道: 未配置（跨设备功能未启用）——运行 membridge init 配置")
        gaps = s.gap_queries()
        if gaps:
            sample = "、".join(f"「{g['q']}」" for g in gaps[:3])
            out(f"  💡 记忆缺口: 最近 {len(gaps)} 类问题没查到记忆（如 {sample}）")
            out("     （系统只提醒，是否补写由你决定：membridge add \"...\"）")
        # 交接班状态（v0.15）：工作台要么新鲜要么不在，过期卡主动告警
        from .handoff import (HANDOFF_STALE_HOURS, age_hours,
                              latest_handoff, summary)

        card = latest_handoff(s)
        if card is not None:
            hours = age_hours(card)
            if hours <= HANDOFF_STALE_HOURS:
                out(f"  🔖 当前工作台: {summary(card)}（{hours:.1f} 小时前）")
            else:
                warnings.append(
                    f"最新交接卡已过期（{hours / 24:.0f} 天前）——过期工作台"
                    "不再恒定注入，只走检索。收工前写新卡："
                    "membridge handoff 查看模板"
                )
        s.close()
    else:
        out("  ⚠️ 尚未创建（运行 membridge init 即可）")

    if warnings:
        out("\n健康提醒：")
        for w in warnings:
            out(f"  ⚠️ {w}")

    for label, module, extra in (("MCP 接入", "mcp", "mcp"),
                                 ("网盘端到端加密", "cryptography", "netdisk")):
        try:
            importlib.import_module(module)
            out(f"可选依赖 {label}: ✅ 已安装")
        except ImportError:
            out(f"可选依赖 {label}: ⚠️ 未安装（需要时 pip install \"membridge[{extra}]\"）")

    out("平台检测：")
    for c in clients.registry():
        if c.tier == "manual":
            continue
        out(f"  {'✅' if c.detect() else '—'} {c.name}")
    out("提示：membridge init 可一键接入所有检测到的平台。")
    return 0
