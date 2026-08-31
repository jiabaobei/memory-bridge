"""v0.11 网关测试：手机/平板接入（路线 A）。真实起 HTTP 服务、真请求往返。"""

import json
import os
import sys
import tempfile
import threading
import urllib.error
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from membridge.embeddings import HashingEmbedder  # noqa: E402
from membridge.gateway import create_gateway_server, resolve_token  # noqa: E402
from membridge.store import MemoryStore  # noqa: E402

TOKEN = "test-gateway-token"
COFFEE = "用户喜欢喝美式咖啡，不加糖"


def _start_gateway():
    tmp = tempfile.TemporaryDirectory()
    store = MemoryStore(os.path.join(tmp.name, "mem.db"), device="pc")
    store._tmp = tmp
    server = create_gateway_server(store, HashingEmbedder(), TOKEN,
                                   host="127.0.0.1", port=0)
    port = server.server_address[1]
    th = threading.Thread(target=server.serve_forever, daemon=True)
    th.start()
    return server, store, port


def _call(port, path, body=None, token=TOKEN, method=None):
    url = f"http://127.0.0.1:{port}{path}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method or ("POST" if data else "GET"))
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    if data:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8") or "{}")


def test_gateway_rejects_missing_and_wrong_token():
    server, store, port = _start_gateway()
    code, _ = _call(port, "/health", token=None)
    assert code == 401
    code, _ = _call(port, "/health", token="wrong-token")
    assert code == 401
    code, _ = _call(port, "/add", body={"text": COFFEE}, token=None)
    assert code == 401
    assert store.count_nodes() == 0  # 未鉴权的写入绝不可能落库
    server.shutdown()
    store.close()


def test_gateway_add_search_roundtrip():
    server, store, port = _start_gateway()
    code, d = _call(port, "/add", body={"text": COFFEE, "kind": "fact"})
    assert code == 200 and d["ok"]
    code, d = _call(port, "/search", body={"query": "咖啡", "k": 3})
    assert code == 200 and any(h["content"] == COFFEE for h in d["hits"])
    code, d = _call(port, "/health", token=TOKEN)
    assert code == 200 and d["nodes"] == 1 and d["device"] == "pc"
    server.shutdown()
    store.close()


def test_gateway_search_silence_contract():
    """沉默契约在网关侧同样生效：无关查询返回「本轮不干预」。"""
    server, store, port = _start_gateway()
    _call(port, "/add", body={"text": COFFEE})
    code, d = _call(port, "/search",
                    body={"query": "完全不相关的量子物理", "as_context": True})
    assert code == 200 and "不注入" in d["context"]
    server.shutdown()
    store.close()


def test_gateway_builtin_page_served_behind_auth():
    server, store, port = _start_gateway()
    code, _ = _call(port, "/", token=None)
    assert code == 401
    req = urllib.request.Request(f"http://127.0.0.1:{port}/")
    req.add_header("Authorization", f"Bearer {TOKEN}")
    with urllib.request.urlopen(req, timeout=10) as r:
        html = r.read().decode("utf-8")
    assert "记忆桥" in html and "localStorage" in html
    server.shutdown()
    store.close()


def test_gateway_bad_request_messages():
    server, store, port = _start_gateway()
    code, d = _call(port, "/add", body={"text": ""})
    assert code == 400 and d.get("error") == "bad_request"
    code, _ = _call(port, "/no-such-path", body={})
    assert code == 404
    server.shutdown()
    store.close()


def test_resolve_token_autogenerates_and_persists():
    tmp = tempfile.TemporaryDirectory()
    store = MemoryStore(os.path.join(tmp.name, "mem.db"), device="pc")
    store._tmp = tmp
    t1 = resolve_token(store)
    t2 = resolve_token(store)
    assert t1 == t2 and len(t1) >= 20  # 托管口令稳定
    assert resolve_token(store, token_arg="手动指定") == "手动指定"
    assert resolve_token(store, env_token="环境变量") == "环境变量"
    store.close()


def test_gateway_stats_reported_in_health():
    """/health 报告运行时长与请求统计（v0.12 基站可观测性）。"""
    server, store, port = _start_gateway()
    _call(port, "/add", body={"text": COFFEE})
    _call(port, "/search", body={"query": "咖啡", "k": 3})
    code, d = _call(port, "/health")
    assert code == 200
    assert d["uptime_sec"] >= 0
    assert d["requests"] == 3          # add + search + health 本次
    assert d["adds"] == 1 and d["searches"] == 1
    assert d["hits"] >= 1
    server.shutdown()
    store.close()


def test_gateway_allowlist_blocks_non_matching_ip():
    """IP 白名单：不匹配的来源一律 403（口令仍是第一道门）。"""
    tmp = tempfile.TemporaryDirectory()
    store = MemoryStore(os.path.join(tmp.name, "mem.db"), device="pc")
    store._tmp = tmp
    # 白名单只放行不存在的网段 → 本机请求被拒
    server = create_gateway_server(store, HashingEmbedder(), TOKEN,
                                   host="127.0.0.1", port=0,
                                   allow=["192.0.2."])
    port = server.server_address[1]
    th = threading.Thread(target=server.serve_forever, daemon=True)
    th.start()
    code, d = _call(port, "/health")
    assert code == 403 and d.get("error") == "forbidden"
    server.shutdown()
    # 白名单放行本机 → 正常
    server2 = create_gateway_server(store, HashingEmbedder(), TOKEN,
                                    host="127.0.0.1", port=0,
                                    allow=["127.0.0.1"])
    port2 = server2.server_address[1]
    threading.Thread(target=server2.serve_forever, daemon=True).start()
    code, d = _call(port2, "/health")
    assert code == 200 and d["ok"]
    server2.shutdown()
    store.close()
