"""平台接入注册表：一键让主流 AI 平台具备跨应用记忆共享（v0.2.0）。

设计原则：
- **幂等**：重复 init 安全，读-改-写合并 JSON，只动自己的 `memory-bridge` 条目，
  绝不破坏平台已有配置；
- **先检测后配置**：只在平台已安装（其配置目录存在）时才写入；
- **三层接入**：MCP 客户端自动写配置 / 技能型平台安装 SKILL.md / 其余打印手动指南。

覆盖：ZCode、Claude Code、Claude 桌面版、Cursor、Cline、Windsurf、
VS Code（Copilot）、Gemini CLI、通义千问 Code（以上自动）；
WorkBuddy、Claude 技能目录（技能自动安装）；
Trae、扣子 Coze 等远程平台（手动指南 + `membridge mcp --http`）。
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional

from .skill_template import SKILL_MD

# 测试可注入的 HOME 覆盖（None = 真实用户目录）
HOME_DIR: Optional[Path] = None
SERVER_NAME = "memory-bridge"


def _home() -> Path:
    return HOME_DIR if HOME_DIR is not None else Path.home()


def _appdata() -> Path:
    """Windows %APPDATA%（其他平台给出合理回退，仅影响候选路径探测）。

    v0.8.0 修复：HOME_DIR 注入时同步覆盖 APPDATA——否则 VS Code 等以
    APPDATA 定位的平台在测试中会读写真实用户配置（真实事故：跑测试
    把 ~/.zcode、~/.cursor、VS Code mcp.json 劫持到临时目录）。
    """
    if os.name == "nt":
        if HOME_DIR is not None:
            return HOME_DIR / "AppData" / "Roaming"
        return Path(os.environ.get("APPDATA", str(_home() / "AppData" / "Roaming")))
    return _home() / ".config"


@dataclass
class ConfigResult:
    key: str
    name: str
    status: str  # configured / already / not-detected / manual / error
    detail: str = ""


@dataclass
class Client:
    key: str
    name: str
    tier: str  # mcp / skill / manual
    detect: Callable[[], bool]
    configure: Callable[[str, str], ConfigResult]
    manual: str = ""


def server_entry(db: str, device: str) -> dict:
    """生成各平台通用的 stdio MCP 服务器条目。"""
    py = sys.executable or "python"
    return {
        "command": py,
        "args": ["-m", "membridge", "mcp"],
        "env": {"MEMBRIDGE_DB": db, "MEMBRIDGE_DEVICE": device},
    }


def _merge_servers(
    path: Path, root_key: str, name: str, entry: dict, nested: bool = False
) -> str:
    """读-改-写合并 MCP 服务器配置。nested=True 为 ZCode 的 mcp.servers 结构。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    data: dict = {}
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise ValueError(f"{path} 不是合法 JSON，请手工检查后重试：{exc}")
    if nested:
        servers = data.setdefault("mcp", {}).setdefault("servers", {})
    else:
        servers = data.setdefault(root_key, {})
    status = "already" if servers.get(name) == entry else "configured"
    servers[name] = entry
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return status


def _first_existing(paths: List[Path]) -> Optional[Path]:
    for p in paths:
        if p.exists():
            return p
    return None


def _json_mcp_client(
    key: str,
    name: str,
    path_fn: Callable[[], Optional[Path]],
    root_key: str = "mcpServers",
    detect_fn: Optional[Callable[[], bool]] = None,
) -> Client:
    """通用"JSON 配置文件型"MCP 客户端接入器。"""

    def configure(db: str, device: str) -> ConfigResult:
        path = path_fn()
        if path is None:
            return ConfigResult(key, name, "not-detected")
        try:
            status = _merge_servers(path, root_key, SERVER_NAME, server_entry(db, device))
        except Exception as exc:
            return ConfigResult(key, name, "error", str(exc))
        return ConfigResult(key, name, status, str(path))

    detected = detect_fn if detect_fn is not None else (lambda: path_fn() is not None)
    return Client(key=key, name=name, tier="mcp", detect=detected, configure=configure)


def _skill_client(key: str, name: str, skills_dir_fn: Callable[[], Path]) -> Client:
    """技能型平台接入器：把记忆技能写到 <skills>/memory-bridge/SKILL.md。"""

    def configure(db: str, device: str) -> ConfigResult:
        target = skills_dir_fn() / SERVER_NAME / "SKILL.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and target.read_text(encoding="utf-8") == SKILL_MD:
            return ConfigResult(key, name, "already", str(target))
        target.write_text(SKILL_MD, encoding="utf-8")
        return ConfigResult(key, name, "configured", str(target))

    return Client(
        key=key,
        name=name,
        tier="skill",
        detect=lambda: skills_dir_fn().parent.exists(),
        configure=configure,
    )


def _manual(key: str, name: str, text: str) -> Client:
    return Client(
        key=key,
        name=name,
        tier="manual",
        detect=lambda: False,
        configure=lambda db, device: ConfigResult(key, name, "manual", text),
        manual=text,
    )


def _zcode() -> Client:
    path = _home() / ".zcode" / "cli" / "config.json"

    def configure(db: str, device: str) -> ConfigResult:
        try:
            status = _merge_servers(
                path, "mcpServers", SERVER_NAME, server_entry(db, device), nested=True
            )
        except Exception as exc:
            return ConfigResult("zcode", "ZCode", "error", str(exc))
        return ConfigResult("zcode", "ZCode", status, str(path))

    return Client("zcode", "ZCode（本机 AI 编程助手）", "mcp", path.exists, configure)


def registry() -> List[Client]:
    """全部支持的平台（mcp/skill 自动配置 + manual 指南）。"""
    claude_json = _home() / ".claude.json"
    claude_desktop = _first_existing(
        [
            _appdata() / "Claude" / "claude_desktop_config.json",
            _home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json",
            _home() / ".config" / "Claude" / "claude_desktop_config.json",
        ]
    )
    cline_paths = [
        _appdata() / code / "User" / "globalStorage" / "saoudrizwan.claude-dev"
        / "settings" / "cline_mcp_settings.json"
        for code in ("Code", "Code - Insiders", "VSCodium")
    ]
    vscode_mcp = _appdata() / "Code" / "User" / "mcp.json"

    return [
        _zcode(),
        _json_mcp_client(
            "claude-code",
            "Claude Code",
            lambda: claude_json if (claude_json.exists() or (_home() / ".claude").exists()) else None,
        ),
        _json_mcp_client(
            "claude-desktop",
            "Claude 桌面版",
            lambda: claude_desktop,
        ),
        _json_mcp_client(
            "cursor",
            "Cursor",
            lambda: _home() / ".cursor" / "mcp.json" if (_home() / ".cursor").exists() else None,
            detect_fn=lambda: (_home() / ".cursor").exists(),
        ),
        _json_mcp_client(
            "cline",
            "Cline（VS Code 插件）",
            lambda: _first_existing(cline_paths),
        ),
        _json_mcp_client(
            "vscode-copilot",
            "VS Code（Copilot MCP）",
            lambda: vscode_mcp if (_appdata() / "Code").exists() else None,
            detect_fn=lambda: (_appdata() / "Code").exists(),
            root_key="servers",
        ),
        _json_mcp_client(
            "windsurf",
            "Windsurf",
            lambda: _home() / ".codeium" / "windsurf" / "mcp_config.json"
            if (_home() / ".codeium").exists()
            else None,
            detect_fn=lambda: (_home() / ".codeium").exists(),
        ),
        _json_mcp_client(
            "gemini-cli",
            "Gemini CLI",
            lambda: _home() / ".gemini" / "settings.json" if (_home() / ".gemini").exists() else None,
            detect_fn=lambda: (_home() / ".gemini").exists(),
        ),
        _json_mcp_client(
            "qwen-code",
            "通义千问 Code（阿里）",
            lambda: _home() / ".qwen" / "settings.json" if (_home() / ".qwen").exists() else None,
            detect_fn=lambda: (_home() / ".qwen").exists(),
        ),
        _skill_client(
            "workbuddy",
            "WorkBuddy（技能方式）",
            lambda: _home() / ".workbuddy" / "skills",
        ),
        _skill_client(
            "claude-skills",
            "Claude 技能目录（SKILL.md 平台通用）",
            lambda: _home() / ".claude" / "skills",
        ),
        _manual(
            "trae",
            "Trae（字节，界面化 MCP）",
            "设置 → MCP → 添加 MCP 服务器：类型 stdio，命令填 python，"
            "参数填 -m membridge mcp，环境变量 MEMBRIDGE_DB 指向你的记忆库路径。",
        ),
        _manual(
            "coze",
            "扣子 Coze 等远程 MCP 平台",
            "本机运行：membridge mcp --http --port 8765，"
            "然后在平台 MCP 设置里添加 URL：http://<本机局域网IP>:8765/mcp"
            "（需同一局域网或自行做公网映射；已含端到端密钥者请另行评估暴露面）。",
        ),
    ]


def manual_guides() -> List[Client]:
    return [c for c in registry() if c.tier == "manual"]
