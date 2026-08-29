"""端到端演示：手机上的记忆 → DSS 差分包 → PC 应用 → Path A 注入。

运行：python examples/demo.py
全程无网络、无模型依赖（内置哈希嵌入），用同一台机器上的两个 SQLite 库
模拟「手机」与「PC」两台设备。
"""

import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8")

from membridge import dss, heat, injection, privacy  # noqa: E402
from membridge.embeddings import HashingEmbedder  # noqa: E402
from membridge.node import MemoryNode  # noqa: E402
from membridge.san import build_edges  # noqa: E402
from membridge.store import MemoryStore  # noqa: E402

embedder = HashingEmbedder()
workdir = tempfile.mkdtemp(prefix="membridge-demo-")
phone = MemoryStore(os.path.join(workdir, "phone.db"), device="手机")
pc = MemoryStore(os.path.join(workdir, "pc.db"), device="PC")


def section(title: str) -> None:
    print("\n" + "=" * 62)
    print(title)
    print("=" * 62)


# 1) 感知 + 蒸馏：在手机上积累记忆，SAN 自动建立语义关联
section("1) 手机：写入记忆并蒸馏为语义关联网络（SAN）")
memories = [
    "用户在开发记忆桥：跨设备跨平台的 AI 共享记忆层",
    "用户在调试记忆桥的 DSS 增量同步模块",
    "用户喜欢喝美式咖啡，不加糖",
    "用户也喜欢手冲咖啡",
    "家里 WiFi 管理密码是 admin888",
]
for text in memories:
    node = MemoryNode(
        content=text,
        embedding=embedder.embed(text),
        scene=privacy.classify_scene(text),
        device="手机",
        migration=privacy.default_migration(text),
    )
    phone.add(node)
edges = build_edges(phone, embedder)
print(f"手机记忆库：{phone.count_nodes()} 个节点，{phone.count_edges()} 条关联边")
if edges:
    first, second, weight = edges[0]
    n1, n2 = phone.get(first), phone.get(second)
    print(f"示例关联边：「{n1.content}」↔「{n2.content}」权重 {weight}")

# 2) 注入：手机端 Path A 上下文块
section("2) 手机：Path A 记忆注入（进入新的对话时）")
hits = phone.search(embedder.embed("记忆桥 项目进展"), k=3)
print(injection.serialize(n for n, _ in hits))

# 3) 同步：生成 手机 → PC 的 DSS 差分包
section("3) DSS 增量同步：手机 → PC（注意 PAMS L1 过滤）")
delta = dss.compute_delta(phone, pc)
payload = delta.to_json()
full = json.dumps([n.to_dict() for n in phone.all_nodes()], ensure_ascii=False)
synced = [n["content"] for n in delta.nodes]
print(f"差分包包含 {len(delta.nodes)} 个节点、{len(delta.edges)} 条边")
print(f"载荷大小 {len(payload)} 字节，为全量同步（{len(full)} 字节）的 {len(payload) / len(full) * 100:.1f}%")
leaked = [c for c in synced if "密码" in c]
print(f"PAMS L1 检查：密码类节点是否泄漏到差分包？{'否 ✓' if not leaked else '是 ✗ ' + str(leaked)}")

# 4) PC 应用差异包并检索
section("4) PC：应用差异包并验证跨设备记忆继承")
result = dss.apply_delta(pc, delta)
print(f"应用结果：{result}")
hits = pc.search(embedder.embed("继续聊记忆桥的开发"), k=2)
for n, s in hits:
    print(f"  PC 检索命中（相似度 {s:.2f}）：{n.content}")

# 5) 预加载：TMT 热度 + PAMS 门控
section("5) TMT 预加载：回到手机前，热度 Top-K 候选")
for n in heat.preload_candidates(phone, allowed=privacy.preload_allowed, k=3):
    print(f"  候选（热度 {heat.heat(n):.2f}）：{n.content}")

phone.close()
pc.close()
print("\n演示完成 ✓  （记忆库位于临时目录，已随进程结束丢弃）")
