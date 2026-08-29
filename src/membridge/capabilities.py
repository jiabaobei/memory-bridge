"""运行时能力探测与自动调度（借鉴 ncnn 的运行时后端选择思想）。

ncnn 在运行时探测 CPU 特性（NEON/AVX）选择最优内核并对旧设备优雅降级；
记忆桥在运行时探测可选依赖与平台设施，为每个能力点选择当前环境的最优实现：

- 嵌入器：有 OpenAI 依赖且配置了密钥 → 真实语义嵌入；否则哈希嵌入降级
- 端到端加密：cryptography 可用则网盘载荷加密
- 向量索引：sqlite-vec 可用则启用（Phase 1+）
- 同步盘：探测本机已装的网盘同步根目录

所有探测均为只读、幂等，无网络请求。
"""

from __future__ import annotations

import importlib
import os
import sys
from typing import Any, Dict

EXTRA_MODULES = {
    "mcp": "mcp",                # MCP server 接入
    "crypto": "cryptography",    # 网盘载荷端到端加密
    "openai": "openai",          # 真实语义嵌入
    "vec_index": "sqlite_vec",   # 向量索引（Phase 1+）
}


def probe() -> Dict[str, Any]:
    """探测当前环境能力，返回只读的能力画像。"""
    info: Dict[str, Any] = {
        "python": sys.version.split()[0],
        "platform": sys.platform,
        "extras": {},
        "sync_drives": [],
    }
    for label, module in EXTRA_MODULES.items():
        try:
            importlib.import_module(module)
            info["extras"][label] = True
        except Exception:
            info["extras"][label] = False
    try:
        from .wizard import detect_sync_roots

        info["sync_drives"] = [
            {"name": n, "root": str(p)} for n, p in detect_sync_roots()
        ]
    except Exception:
        info["sync_drives"] = []
    return info


def best_embedder():
    """按环境选择最优嵌入实现（自动升级，优雅降级）。"""
    if os.environ.get("OPENAI_API_KEY") and probe()["extras"].get("openai"):
        from .embeddings import OpenAIEmbedder

        try:
            return OpenAIEmbedder()
        except Exception:
            pass  # 密钥无效等情况下降级
    from .embeddings import HashingEmbedder

    return HashingEmbedder()
