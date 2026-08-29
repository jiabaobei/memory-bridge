"""membridge doctor：环境自检（版本、记忆库、可选依赖、平台检测）。"""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

from . import clients


def run_doctor(out=print) -> int:
    import membridge

    out(f"membridge 版本: {membridge.__version__}")
    out(f"Python: {sys.version.split()[0]}")

    db = os.environ.get("MEMBRIDGE_DB") or str(Path.home() / ".membridge" / "memory.db")
    out(f"记忆库: {db}")
    if os.path.exists(db):
        from .store import MemoryStore

        s = MemoryStore(db)
        out(f"  ✅ 可用（{s.count_nodes()} 条记忆，{s.count_edges()} 条关联，设备 {s.device_name}）")
        if s.netdisk:
            out(f"  ☁️ 云盘通道: {s.netdisk}")
            out("     （跨设备同步就绪；发布/取回命令见 membridge init 输出）")
        else:
            out("  ⚠️ 云盘通道: 未配置（跨设备功能未启用）——运行 membridge init 配置")
        s.close()
    else:
        out("  ⚠️ 尚未创建（运行 membridge init 即可）")

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
