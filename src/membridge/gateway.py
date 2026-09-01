"""连接层：手机 / 平板接入网关（v0.11，移动端路线 A「瘦客户端 + 基站」）。

PC / 笔记本之间继续走网盘差分包互相同步；手机与平板不持有完整记忆库，
而是以瘦客户端接入家里一台常开设备（基站）上的记忆库——日常只需要
Add / Search / Preload 三个动作。

- 任意能发 HTTP 的东西都能接：iOS 快捷指令、内置浏览器小页面（加到
  主屏幕即类 App）、任意自动化工具
- 只依赖 Python 标准库（http.server），无新依赖
- 访问口令强制：未带正确口令一律 401（恒定时间比较）
- 隐私边界：**明文 HTTP 只可在局域网或 Tailscale 等自持加密组网内
  使用**；需要跨网可达时用 --cert/--key 启用 TLS。绝不开公网明文端口
  （见 docs/mobile.md）

Android「完整节点」（Termux）是路线 B，纯文档方案，见 docs/mobile.md。
"""

from __future__ import annotations

import hmac
import json
import secrets
import ssl
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional
from urllib.parse import parse_qs, urlparse

from .embeddings import Embedder
from .node import MemoryNode
from .privacy import classify_scene, default_migration, preload_allowed
from .retrieval import hybrid_search
from .san import build_edges
from .store import MemoryStore

TOKEN_META_KEY = "gateway_token"


def resolve_token(store: MemoryStore, token_arg: Optional[str] = None,
                  env_token: Optional[str] = None) -> str:
    """口令优先级：命令行参数 > 环境变量 > 库内托管（首次自动生成）。

    自动生成的口令持久化在本库 meta 中——与「同步口令系统托管」同一
    产品哲学：用户不需要记，需要时看一次。
    """
    if token_arg:
        return token_arg.strip()
    if env_token:
        return env_token.strip()
    saved = store._get_meta(TOKEN_META_KEY)
    if saved:
        return saved
    token = secrets.token_urlsafe(24)
    with store.transaction():
        store._set_meta(TOKEN_META_KEY, token)
    return token


_PAGE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="apple-mobile-web-app-capable" content="yes">
<title>记忆桥</title>
<style>
 body{font-family:system-ui,sans-serif;max-width:560px;margin:0 auto;
      padding:16px;background:#f7f7f5;color:#222}
 h1{font-size:1.2em}
 textarea,input{width:100%;box-sizing:border-box;padding:10px;font-size:16px;
      border:1px solid #ccc;border-radius:8px;margin:6px 0}
 button{padding:10px 18px;font-size:16px;border:0;border-radius:8px;
      background:#2b6cb0;color:#fff;margin-right:8px}
 pre{white-space:pre-wrap;background:#fff;border:1px solid #e2e2e0;
      border-radius:8px;padding:10px;min-height:2em}
 .hint{color:#777;font-size:.85em}
</style>
</head>
<body>
<h1>🌉 记忆桥 · 随身记</h1>
<p class="hint">通勤路上想到什么，记一笔；回到家，所有设备都记得。</p>
<textarea id="text" rows="3" placeholder="要记住的一件事（一句话一条最准）"></textarea>
<button onclick="add()">记一笔</button>
<hr>
<textarea id="ho" rows="6" placeholder="交接卡（收工前填，新卡自动取代旧卡）
goal: 当前目标
done: 已完成
failed: 试过什么；因为什么失败；除非什么否则别重试
next: 下一步
refs: 相关文件/符号"></textarea>
<button onclick="handoff()">交接班</button>
<button onclick="workbench()">看工作台</button>
<hr>
<input id="query" placeholder="想找的记忆…">
<button onclick="search()">找记忆</button>
<pre id="out"></pre>
<p class="hint" id="status"></p>
<script>
const tok = () => {
  let t = localStorage.getItem("membridge_token");
  if (!t) { t = prompt("输入基站访问口令（gateway 启动时显示）") || "";
            localStorage.setItem("membridge_token", t); }
  return t;
};
async function call(path, body) {
  const r = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json",
               "Authorization": "Bearer " + tok() },
    body: JSON.stringify(body),
  });
  if (r.status === 401) { localStorage.removeItem("membridge_token");
    document.getElementById("out").textContent = "口令不对，已清除，请重试"; return; }
  const d = await r.json();
  document.getElementById("out").textContent = d.message || JSON.stringify(d, null, 2);
  status();
}
async function status() {
  try {
    const r = await fetch("/health",
      { headers: { "Authorization": "Bearer " + tok() } });
    if (r.status !== 200) return;
    const d = await r.json();
    const h = Math.floor(d.uptime_sec / 3600),
          m = Math.floor((d.uptime_sec % 3600) / 60);
    document.getElementById("status").textContent =
      `基站「${d.device}」在线 ${h} 小时 ${m} 分 · 记忆 ${d.nodes} 条 · ` +
      `已记 ${d.adds} 次 / 检索 ${d.searches} 次（命中 ${d.hits} 条）`;
  } catch (e) {}
}
function add() {
  const t = document.getElementById("text").value.trim();
  if (t) call("/add", { text: t });
}
function handoff() {
  const t = document.getElementById("ho").value.trim();
  if (t) call("/add", { text: t, kind: "handover" });
}
function workbench() {
  call("/workbench", {});
}
function search() {
  const q = document.getElementById("query").value.trim();
  if (q) call("/search", { query: q, as_context: true });
}
status();
</script>
</body>
</html>
"""


def create_gateway_server(
    store: MemoryStore,
    embedder: Embedder,
    token: str,
    host: str = "0.0.0.0",
    port: int = 8766,
    allow: Optional[list] = None,
) -> ThreadingHTTPServer:
    """构造带口令鉴权的网关 HTTP server（不启动；serve_forever 由调用方负责）。

    allow：可选 IP 白名单前缀列表（如 ["192.168.1.", "100.64."]）；
    提供时客户端 IP 必须匹配其一（口令仍是第一道门，白名单是第二道）。
    """
    stats = {"started": time.time(), "requests": 0, "adds": 0,
             "searches": 0, "hits": 0}

    def _authorized(handler) -> bool:
        auth = handler.headers.get("Authorization", "")
        candidates = []
        if auth.startswith("Bearer "):
            candidates.append(auth[len("Bearer "):])
        header_token = handler.headers.get("X-Membridge-Token", "")
        if header_token:
            candidates.append(header_token)
        query = parse_qs(urlparse(handler.path).query)
        candidates.extend(query.get("token", []))
        return any(hmac.compare_digest(c, token) for c in candidates if c)

    class Handler(BaseHTTPRequestHandler):
        server_version = "MemoryBridgeGateway/0.11"

        def log_message(self, fmt, *args):  # 降噪：只记异常，访问不打屏
            pass

        def _send(self, code: int, payload, content_type="application/json; charset=utf-8"):
            body = payload if isinstance(payload, bytes) else json.dumps(
                payload, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _check_auth(self) -> bool:
            if allow and not any(
                self.client_address[0].startswith(p) for p in allow
            ):
                self._send(403, {"error": "forbidden",
                                 "message": "客户端 IP 不在白名单内"})
                return False
            if _authorized(self):
                stats["requests"] += 1
                return True
            self._send(401, {"error": "unauthorized",
                             "message": "缺少访问口令或口令不正确"})
            return False

        def do_GET(self):
            path = urlparse(self.path).path
            if path in ("/", "/index.html"):
                if not self._check_auth():
                    return
                self._send(200, _PAGE.encode("utf-8"), "text/html; charset=utf-8")
                return
            if path == "/health":
                if not self._check_auth():
                    return
                self._send(200, {"ok": True, "device": store.device_name,
                                 "nodes": store.count_nodes(),
                                 "uptime_sec": int(time.time() - stats["started"]),
                                 "requests": stats["requests"],
                                 "adds": stats["adds"],
                                 "searches": stats["searches"],
                                 "hits": stats["hits"]})
                return
            self._send(404, {"error": "not_found", "message": "未知路径"})

        def do_POST(self):
            if not self._check_auth():
                return
            path = urlparse(self.path).path
            try:
                length = int(self.headers.get("Content-Length", 0))
                data = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
            except (ValueError, TypeError):
                self._send(400, {"error": "bad_request", "message": "请求体不是合法 JSON"})
                return
            if path == "/add":
                text = (data.get("text") or "").strip()
                if not text:
                    self._send(400, {"error": "bad_request", "message": "text 不能为空"})
                    return
                migration = (data.get("migration") or "").strip()
                kind = (data.get("kind") or "").strip()
                node = MemoryNode(
                    content=text,
                    embedding=embedder.embed(text),
                    tags=[t.strip() for t in (data.get("tags") or "").split(",")
                          if t.strip()],
                    scene=classify_scene(text),
                    device=store.device_name,
                    migration=migration or default_migration(text),
                    kind=kind if kind in ("fact", "procedure", "handover") else "",
                )
                with store.transaction():
                    store.add(node)
                    build_edges(store, embedder, only_new=node)
                stats["adds"] += 1
                self._send(200, {"ok": True, "node_id": node.node_id,
                                 "message": f"已记忆（{node.node_id}）"})
                return
            if path == "/search":
                query = (data.get("query") or "").strip()
                if not query:
                    self._send(400, {"error": "bad_request", "message": "query 不能为空"})
                    return
                k = int(data.get("k") or 5)
                hits = hybrid_search(store, embedder, query, k=k)
                stats["searches"] += 1
                stats["hits"] += len(hits)
                if data.get("as_context"):
                    from .handoff import workbench, workbench_block
                    from .injection import serialize

                    active = workbench(store)
                    nodes = (n for n, _ in hits
                             if not (active and n.node_id == active.node_id))
                    self._send(200, {"ok": True,
                                     "context": serialize(
                                         nodes,
                                         workbench=workbench_block(store))})
                    return
                self._send(200, {"ok": True, "hits": [
                    {"content": n.content, "score": round(s, 4), "kind": n.kind,
                     "device": n.device} for n, s in hits]})
                return
            if path == "/preload":
                from .heat import preload_candidates

                cands = preload_candidates(store, allowed=preload_allowed,
                                           k=int(data.get("k") or 8))
                self._send(200, {"ok": True,
                                 "candidates": [n.content for n in cands]})
                return
            if path == "/workbench":
                # 只读槽位（v0.15）：最新未过期交接卡；无卡/过期返回空，
                # 不硬凑——过期工作台比没有工作台更危险
                from .handoff import latest_handoff, workbench_block

                block = workbench_block(store)
                if block:
                    self._send(200, {"ok": True, "message": block})
                else:
                    latest = latest_handoff(store)
                    msg = ("（暂无生效的交接卡——过期卡已降级为普通记忆）"
                           if latest else "（还没有交接卡：用「交接班」写一张）")
                    self._send(200, {"ok": True, "message": msg})
                return
            self._send(404, {"error": "not_found", "message": "未知路径"})

    return ThreadingHTTPServer((host, port), Handler)


def serve_gateway(server: ThreadingHTTPServer,
                  certfile: Optional[str] = None,
                  keyfile: Optional[str] = None) -> None:
    """启动网关；提供证书时启用 TLS（跨网可达的必要条件）。"""
    if certfile:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(certfile=certfile, keyfile=keyfile)
        server.socket = ctx.wrap_socket(server.socket, server_side=True)
    server.serve_forever()
