"""钩子层：把注入块自动投递进 agent 的对话上下文（v0.32）。

问题：v0.31 及以前，注入块只有两条出口——手动 `membridge context "查询"`，
或 agent 自己想起调用 MCP 工具。结果是「记忆在库里、在云盘上，但没有任何
一条路径把它自动送进当前对话」，跨对话/跨设备共享全靠 agent 自觉。

本模块补最后一米，且**不阻塞对话**（v0.32 的关键约束）：

  闲时/开机   membridge hook --warm   预计算候选池 + 常驻块 → 落盘缓存
  对话时      membridge hook          只读缓存（毫秒级），按当前任务关键词过滤
  缓存缺失    membridge hook          立即返回空（沉默），后台 detached 预热

三原则对照：
  ① 极省 token —— 缓存里只放高置信候选池，对话时只输出**命中项**（通常 0-3 条）；
     没有命中就一个字都不写（沉默契约），绝不把"相关但没用"的记忆刷进上下文。
  ② 极简 —— 不引新依赖、不加配置项：一个 JSON 缓存 + 关键词过滤，序列化全复用
     injection.serialize / handoff.workbench_block。
  ③ 绝不动记忆 —— 钩子只读库与缓存，不写回记忆；缓存是派生视图，删了可重建。

平台契约：脚本把文本打到 stdout，宿主并入会话上下文（Claude Code / CodeBuddy /
WorkBuddy 同源）；`--json` 给出 hookSpecificOutput.additionalContext 结构。

ponytail: 缓存失效靠 TTL + 后台预热，没有跨进程锁——两个进程同时预热只是
重复算一遍、后写覆盖，不丢数据；真写坏了删缓存重跑即可。
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import List, Optional

# 本模块写进宿主配置的命令都带这个标记，卸载/查重只认它——绝不碰别人的钩子
MARKER = "-m membridge hook"
EVENTS = ("SessionStart", "UserPromptSubmit")
DEFAULT_BUDGET = 800        # 注入预算（字符）：宿主另有上限，这里只占小头
DEFAULT_K = 3               # 对话时最多注入几条命中记忆
POOL_MAX = 120              # 候选池（预热时算一次）。缓存不花 token：只有命中的才注入
CACHE_TTL = 12 * 3600       # 缓存有效期：半天。过期只影响新鲜度，不影响对话
CONF_MIN = 0.3              # 与 injection.CONFIDENCE_THRESHOLD 同义
# 与 injection.SILENCE_NOTE 同文案：热路径不导入该模块，省 0.4s 启动
SILENCE = "（记忆桥：本轮没有需要干预的记忆——保持沉默，不注入上下文）"

def cache_path() -> Path:
    """注入缓存位置。MEMBRIDGE_CACHE 可覆盖——测试与临时库必须用独立缓存，
    否则 `--db 别的库 hook --warm` 会把主库的缓存冲掉（v0.32.1 真机踩到）。"""
    return Path(os.environ.get("MEMBRIDGE_CACHE")
                or Path.home() / ".membridge" / "inject-cache.json")


# ------------------------------------------------------------------ 关键词

_TOKEN_RE = re.compile(r"[\u4e00-\u9fa5]{2,}|[A-Za-z][A-Za-z0-9_.+-]{1,}")


def tokens(text: str) -> set:
    """任务 → 关键词集合。中文长串补 2 字滑动窗，够用且不依赖分词库。"""
    out = set()
    for tok in _TOKEN_RE.findall(text or ""):
        out.add(tok.lower())
        if len(tok) >= 4 and re.match(r"[\u4e00-\u9fa5]", tok):
            out.update(tok[i:i + 2].lower() for i in range(len(tok) - 1))
    return out


def _score(entry: dict, q: set) -> int:
    """匹配分：2 字词 1 分、3 字及以上 2 分。低于 2 分算噪音（如"今天/这个"）。"""
    if not q:
        return 0
    hay = (entry.get("t", "") + " " + " ".join(entry.get("tags", []))).lower()
    return sum(2 if len(tok) >= 3 else 1 for tok in q if tok in hay)


MIN_SCORE = 2


# ------------------------------------------------------------------ 预热

def warm(store, budget: int = DEFAULT_BUDGET, pool: int = POOL_MAX) -> Path:
    """闲时调用：把候选池 + 常驻块算好落盘。这是唯一会碰库/向量的路径。"""
    from . import handoff
    from .heat import preload_candidates

    wb = handoff.workbench_block(store)
    # 池子 = 记忆桥自己的「热度」排序（近期反复用到的最可能再次用到），
    # 不用全库检索：预热只跑一次，但仍按项目既有语义挑，不另造指标
    try:
        hot = preload_candidates(store, allowed=lambda n: True, k=pool, hot_only=False)
    except Exception:
        hot = []
    if not hot:
        hot = sorted([n for n in store.all_nodes() if n.confidence >= CONF_MIN],
                     key=lambda n: n.confidence, reverse=True)[:pool]
    # 交接卡已在工作台小节恒定注入，不再重复进候选池
    top = [n for n in hot if getattr(n, "kind", "") != "handover"][:pool]
    payload = {
        "ts": time.time(),
        "budget": budget,
        "workbench": wb,
        "entries": [{
            "id": n.node_id[:8],
            "t": n.content[:500],
            "tags": n.tags or [],
            "c": round(float(n.confidence), 3),
        } for n in top],
    }
    target = cache_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    tmp.replace(target)
    return target


def is_stale(cache: Optional[dict]) -> bool:
    """缓存缺失或过期 → 该后台预热了。"""
    return not cache or time.time() - cache.get("ts", 0) > CACHE_TTL


def load_cache() -> Optional[dict]:
    try:
        return json.loads(cache_path().read_text(encoding="utf-8"))
    except Exception:
        return None


def spawn_warm() -> None:
    """缓存缺失/过期：后台补，绝不阻塞当前这条消息。"""
    try:
        kwargs = {}
        if sys.platform == "win32":
            kwargs["creationflags"] = 0x00000008 | 0x00000200  # DETACHED | NEW_GROUP
        subprocess.Popen(
            [sys.executable, "-m", "membridge", "hook", "--warm", "--quiet"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kwargs
        )
    except Exception:
        pass  # 预热失败不影响对话，下次再说


# ------------------------------------------------------------------ 组装

def render(cache: dict, query: str, budget: int = DEFAULT_BUDGET,
           k: int = DEFAULT_K) -> str:
    """从缓存组装本轮注入块。命中不到 → 只给工作台；都没有 → 沉默。"""
    q = tokens(query)
    entries = cache.get("entries") or []
    hits: List[dict] = []
    if q:
        scored = [(e, _score(e, q)) for e in entries]
        hits = [e for e, s in sorted(scored, key=lambda x: (-x[1], -x[0].get("c", 0)))
                if s >= MIN_SCORE][:k]
    wb = (cache.get("workbench") or "").strip()
    if not hits and not wb:
        return SILENCE

    lines = ["[记忆桥 · 跨设备记忆上下文 开始]"]
    used = 0
    if wb:
        wb = wb[: max(120, budget // 3)]
        lines.append(wb)
        used += len(wb)
    for e in hits:
        line = f"- {e['t']}"
        if used + len(line) > budget:
            break
        lines.append(line)
        used += len(line)
    if len(lines) == 1:
        return SILENCE
    lines.append("[记忆桥 · 跨设备记忆上下文 结束]")
    return "\n".join(lines)


def build_block(store, query: str = "", budget: int = DEFAULT_BUDGET,
                k: int = DEFAULT_K) -> str:
    """不走缓存的即时组装（给工具类命令用；对话路径不要走这条，要 2-4 秒）。"""
    from . import capabilities, handoff, injection, retrieval

    wb = handoff.workbench_block(store)
    active = handoff.workbench(store)
    hits = retrieval.search_with_reasons(
        store, capabilities.best_embedder(), query, k=k
    ) if query else []
    nodes = [n for n, _, _ in hits if not (active and n.node_id == active.node_id)]
    reasons = {n.node_id: why for n, _, why in hits}
    return injection.serialize(nodes, max_chars=budget, reasons=reasons, workbench=wb)


def emit(block: str, as_json: bool = False, event: str = "SessionStart") -> int:
    """把注入块打到 stdout。沉默契约：无可注入内容时一个字节都不写。"""
    if not block or block == SILENCE:
        return 0
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
    if as_json:
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": event, "additionalContext": block,
        }}, ensure_ascii=False))
    else:
        print(block)
    return 0


def stdin_query() -> str:
    """钩子载荷里的当前任务。SessionStart 没有 prompt → 空串（只注入工作台）。"""
    if sys.stdin is None or sys.stdin.isatty():
        return ""
    try:
        raw = (sys.stdin.read() or "").strip()
    except Exception:
        return ""
    if not raw:
        return ""
    if raw.startswith("{"):
        try:
            d = json.loads(raw)
        except Exception:
            return ""
        for key in ("prompt", "task", "input", "message", "content"):
            v = d.get(key)
            if isinstance(v, str) and v.strip():
                return v.strip()
        return ""
    return raw[:2000]


# ---------------------------------------------------------------- 安装/卸载

def platform_paths(explicit: Optional[str] = None) -> dict:
    """探测本机存在的宿主配置。只写已存在的平台，不凭空造配置目录。"""
    home = Path.home()
    cands = {
        "claude": home / ".claude" / "settings.json",
        "workbuddy": home / ".workbuddy" / "settings.json",
        "codebuddy": home / ".codebuddy" / "settings.json",
        "zcode": home / ".zcode" / "settings.json",
        "cursor": home / ".cursor" / "settings.json",
        "gemini": home / ".gemini" / "settings.json",
    }
    out = {name: p for name, p in cands.items() if p.exists()}
    if explicit:
        out["custom"] = Path(explicit).expanduser()
    return out


def _hook_cmd() -> str:
    # 用解释器直调模块：避免 PATH 里没有 membridge 时钩子静默失败
    return f'"{sys.executable}" {MARKER} --quiet'


def _is_ours(entry: dict) -> bool:
    return any(MARKER in str(h.get("command", "")) for h in entry.get("hooks", []))


def install(paths: dict, dry_run: bool = False, events: tuple = EVENTS) -> list:
    """幂等合并：只增自己的条目，别人的钩子原样保留。

    events 决定注入时机——`session` 只在会话开始跑一次（每会话一次启动开销），
    `prompt` 每条消息都跑（最相关，但每条都吃一次进程启动），`both` 两者都挂。
    """
    actions = []
    cmd = _hook_cmd()
    for name, path in paths.items():
        try:
            data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        except Exception as exc:
            actions.append(f"{name}: 跳过（配置不是合法 JSON：{exc}）")
            continue
        if not isinstance(data, dict):
            actions.append(f"{name}: 跳过（配置根不是对象）")
            continue
        hooks = data.setdefault("hooks", {})
        changed = False
        for event in events:
            entries = hooks.setdefault(event, [])
            if any(_is_ours(e) for e in entries):
                continue
            entries.append({
                "hooks": [{
                    "type": "command", "command": cmd, "timeout": 20,
                    "description": "记忆桥：把跨设备记忆注入本会话上下文",
                }]
            })
            changed = True
        if not changed:
            actions.append(f"{name}: 已装（无需改动）")
            continue
        if dry_run:
            actions.append(f"{name}: 将写入 {path}")
            continue
        if path.exists():
            bak = path.with_suffix(f".json.membridge-bak-{time.strftime('%Y%m%d%H%M%S')}")
            shutil.copy2(path, bak)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        actions.append(f"{name}: 已装 → {path}")
    return actions


def uninstall(paths: dict) -> list:
    actions = []
    for name, path in paths.items():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            actions.append(f"{name}: 跳过（读不到配置）")
            continue
        hooks = data.get("hooks") or {}
        removed = 0
        for event in EVENTS:
            entries = hooks.get(event) or []
            keep = [e for e in entries if not _is_ours(e)]
            removed += len(entries) - len(keep)
            if keep:
                hooks[event] = keep
            elif event in hooks:
                del hooks[event]
        if not removed:
            actions.append(f"{name}: 未装")
            continue
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        actions.append(f"{name}: 已摘除 {removed} 条")
    return actions


def status(paths: dict) -> list:
    out = []
    cache = load_cache()
    age = (f"{int((time.time() - cache['ts']) / 60)} 分钟前预热"
           if cache else "尚无缓存（对话时首次会沉默，后台自动预热）")
    for name, path in paths.items():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            out.append(f"{name}: ✗ 配置读不到（{path}）")
            continue
        hooks = data.get("hooks") or {}
        n = sum(1 for e in hooks.get("SessionStart", []) if _is_ours(e))
        m = sum(1 for e in hooks.get("UserPromptSubmit", []) if _is_ours(e))
        mark = "✅" if n or m else "—"
        out.append(f"{name}: {mark} SessionStart={n} UserPromptSubmit={m}（{path}）")
    out.append(f"缓存: {age}｜池 {len(cache.get('entries', [])) if cache else 0} 条")
    return out


def quick() -> int:
    """热路径入口：`python -S -c "...hook.quick()" --quiet`。

    只用标准库 + 一个 JSON 缓存，因此可以配 `-S` 跳掉 site 初始化，把每次
    注入从 ~1.1s 压到 ~0.5s。带 --warm/--install 等管理参数时转交完整 CLI。
    """
    import argparse

    p = argparse.ArgumentParser(add_help=False)
    p.add_argument("--quiet", action="store_true")
    p.add_argument("--json", action="store_true")
    p.add_argument("--event", default="SessionStart")
    p.add_argument("--budget", type=int, default=DEFAULT_BUDGET)
    p.add_argument("-k", type=int, default=DEFAULT_K)
    args, rest = p.parse_known_args()
    if rest:                                  # 管理类参数：交给完整 CLI
        from .cli import main as cli_main
        return cli_main()
    try:
        cache = load_cache()
        if is_stale(cache):
            spawn_warm()
            if not cache:
                return 0
        return emit(render(cache, stdin_query(), budget=args.budget, k=args.k),
                    as_json=args.json, event=args.event)
    except Exception:
        return 0 if args.quiet else 1         # fail-open
