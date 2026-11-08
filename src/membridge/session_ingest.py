"""会话索引沉淀（v0.33.0）：只读扫描 agent 会话归档，产出一行式索引。

真机事故（2026-11-08）：四天前在另一台电脑做完「军队文职岗位匹配」，桌面留了
两份 xlsx；换机后问「岗位表在哪」，记忆桥精确匹配 **0 条**。会话做完了，却从未
写库——autosync 只运「已在库里的」，`import-md` 要人手喂文件，中间这环一直是空的。
当时的错误结论是「没有文件」，而线索一直躺在会话归档里。

本模块补 Ingest 的最后一米，只做最省的一件事：**每个会话一条索引** =
日期 + 任务标题 + 产出文件名 + 会话 id。另一台设备真正需要的是
「做过没有 / 东西叫什么 / 去哪找」，把整段对话塞进记忆既费 token，
又违反内容冻结。正文一个字都不复制。

三原则对照：
  ① 极省 token —— 每条索引一行，无正文、无摘要、无 LLM；
  ② 极简 —— 纯标准库（json/re/pathlib/datetime），无新依赖、无配置项；
  ③ 绝不动记忆 —— 只新增节点，不读取来改写任何既有记忆；重复跑按内容判重。

宿主不绑定：`--projects-dir` 可指向任何装有 `*.jsonl` 会话归档的目录，
默认落在 WorkBuddy / CodeBuddy 的 `~/.workbuddy/projects`。
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

_DATE_RE = re.compile(r"(20\d{2}-\d{2}-\d{2})")
# 按 JSON / 路径里最常见的分隔符切词，比正则猜文件名可靠得多
_SPLIT_RE = re.compile(r"[\"'\\/<>|,，;；:：\s()\[\]{}]+")
# 只认「成果类」扩展名：源码 / 日志类（.py/.txt/.json）在会话里噪声太大
_EXTS = (".xlsx", ".xls", ".et", ".docx", ".doc", ".pdf", ".csv",
         ".pptx", ".zip", ".md")
# 仓库文档与依赖名不算「这次任务产出了什么」
_NOISE_NAMES = {
    "readme.md", "changelog.md", "skill.md", "agents.md", "license.md",
    "requirements.txt", "pyproject.toml", "contributing.md",
    # agent 宿主自带的配置 / 人格文档，不是任务产出。2026-11-08 真机：
    # 11-04 会话按出现顺序取的前 6 个「产出」全是这些，把岗位表挤出名额。
    "bootstrap.md", "soul.md", "identity.md", "user.md",
    "skill_tree.md", "memory.md", "claude.md", "mcp.json",
}
_TITLE_KEYS = ("aiTitle", "ai_title", "title")


def default_projects_dir() -> Path:
    """默认会话归档根；别的宿主用 --projects-dir 指过来即可。"""
    return Path.home() / ".workbuddy" / "projects"


def session_date(path: Path) -> str:
    """目录名带日期就用它（跨设备拷贝后仍稳定），否则退回文件 mtime。"""
    m = _DATE_RE.search(path.parent.name) or _DATE_RE.search(path.name)
    if m:
        return m.group(1)
    try:
        return datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d")
    except OSError:
        return "未知日期"


def _artifacts(line: str) -> List[str]:
    out: List[str] = []
    for tok in _SPLIT_RE.split(line):
        name = tok.strip(".,;:：，。；、")
        low = name.lower()
        if not low.endswith(_EXTS) or len(name) > 80 or low in _NOISE_NAMES:
            continue
        if "://" in name or low.startswith("http"):
            continue
        # 通配符、Excel 临时文件、反引号残留、纯数字临时名一律不算产出
        if "*" in name or name.startswith(("`", "~$")):
            continue
        if re.fullmatch(r"\d{6,}\.\w+", name):
            continue
        if name not in out:
            out.append(name)
    return out


def parse_session(path: Path, max_files: int = 6) -> Optional[Dict]:
    """只读一个 jsonl → {date, title, artifacts, sid}；连标题都取不到就跳过。

    标题优先取宿主生成的 ai-title，退回第一条用户消息的前 30 字——
    两者都没有的会话不索引（少而准，宁可漏也不塞噪声）。

    产出文件名按**最后一次出现的位置**取末尾 N 个：长会话里往往试过几十个
    临时/失败的文件名，真正落盘的成果通常在结尾的总结里（真机 2026-11-08：
    11-04 会话共 79 个候选，前 6 个全是宿主配置文档）。
    """
    title, first_user = "", ""
    artifacts: Dict[str, int] = {}      # 文件名 -> 最后一次出现的行号
    try:
        with path.open(encoding="utf-8", errors="replace") as f:
            for lineno, line in enumerate(f):
                if not line.strip():
                    continue
                for name in _artifacts(line):
                    artifacts[name] = lineno
                try:
                    obj = json.loads(line)
                except (ValueError, TypeError):
                    continue
                if not isinstance(obj, dict):
                    continue
                if not title and obj.get("type") in ("ai-title", "title", "summary"):
                    for key in _TITLE_KEYS:
                        val = obj.get(key)
                        if isinstance(val, str) and val.strip():
                            title = val.strip().splitlines()[0][:60]
                            break
                if not first_user and _is_user_message(obj):
                    text = _message_text(obj)
                    text = re.sub(r"<system-reminder.*?</system-reminder>", "",
                                  text, flags=re.S)
                    text = " ".join(text.split())
                    if text and not text.startswith("<"):
                        first_user = text[:30]
    except OSError:
        return None
    title = title or first_user
    if not title:
        return None
    return {
        "date": session_date(path),
        "title": title,
        "artifacts": [name for name, _ in sorted(
            artifacts.items(), key=lambda kv: kv[1])[-max_files:]],
        "sid": path.stem[:8],
    }


def _is_user_message(obj: dict) -> bool:
    if obj.get("type") == "message" and obj.get("role") == "user":
        return True
    if obj.get("type") == "user":
        return True
    msg = obj.get("message")
    return isinstance(msg, dict) and msg.get("role") == "user"


def _message_text(obj: dict) -> str:
    content = obj.get("content")
    if content is None and isinstance(obj.get("message"), dict):
        content = obj["message"].get("content")
    if isinstance(content, list):
        return " ".join(str(x.get("text", "")) for x in content
                        if isinstance(x, dict))
    return str(content or "")


def index_line(entry: Dict) -> str:
    """一行式索引：能判「做过没有」、能按文件名搜到、能定位归档。"""
    out = f"[{entry['date']}] 任务:{entry['title']}"
    if entry["artifacts"]:
        out += " | 产出:" + ",".join(entry["artifacts"])
    return out + f" | 会话:{entry['sid']}"


def scan(root: Path, since: str = "", limit: int = 300,
         max_files: int = 6) -> List[Dict]:
    """只读扫描；按路径排序保证确定性，超 limit 截断（防止超大目录拖慢）。"""
    if not root.is_dir():
        return []
    out: List[Dict] = []
    for path in sorted(root.rglob("*.jsonl")):
        if since and session_date(path) < since:
            continue
        entry = parse_session(path, max_files=max_files)
        if entry:
            out.append(entry)
        if len(out) >= limit:
            break
    return out
