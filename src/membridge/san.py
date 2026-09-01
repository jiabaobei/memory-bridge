"""蒸馏层：SAN 语义关联网络（论文 §3.2）。

论文公式：w_ij = λ·PMI(n_i, n_j) + (1-λ)·cos(e_i, e_j)

v0 的 PMI 项用"字符 n-gram 集合的 Jaccard 共现"作代理（无需语料级统计），
完整 PMI 可通过 pmi_fn 参数注入替换，上层接口不变。

架构约束（与论文一致）：SAN 只做提取与关联，绝不生成原始交互中不存在的新语义
（内容冻结原则，规避 Faulty Memory 失效域）。

v0.8 工程修订：建边从「每次 add 全量 O(n²) 重算」改为增量——写入时只算新节点
与既有节点的关联（O(n)）；全量两两重建仅用于 init / rebuild-edges 命令。
内容冻结原则下边本就只增不改，增量建边不损失语义；已存在且权重未变的边
不再重写（写放大归零）。
"""

from __future__ import annotations

import re
from typing import Callable, Iterator, List, Optional, Set, Tuple

from .embeddings import Embedder, cosine
from .node import MemoryNode
from .store import MemoryStore

# ---- v0.14 确定性实体锚点（正则，零依赖）----
# 借鉴代码知识图谱的"确定性关系源"思路，但只抽取、不解析：
# 不引入 Tree-sitter、不建 AST，仅用正则抽出原文中确凿存在的符号，
# 作为记忆之间的确定性关联锚点（中英混写/同义改写也能连上）。
_PATH_RE = re.compile(
    r"[\w\-./]+\.(?:py|js|ts|tsx|jsx|go|java|rs|md|json|ya?ml|toml|sh|sql"
    r"|html|css|c|cpp|cs|rb|php)\b",
    re.IGNORECASE,
)
_FUNC_RE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]{2,})\s*\(")
_CODE_RE = re.compile(r"\b([A-Z][A-Z0-9_]{2,})\b")
_REPO_RE = re.compile(r"\b([A-Za-z0-9_.\-]+)/([A-Za-z0-9_.\-]{2,})\b")

# 过泛的锚点不建边（否则图会退化成"万物相连"，违背稀疏原则与省 token）
_ENTITY_MIN_LEN = 3

# v0.15 交接卡边权重衰减：交接卡（kind=handover）正文含大量历史指涉，
# 若不加抑制会连成超级枢纽、把检索排名抬到压过普通记忆——但工作台槽位
# 已让最新交接卡恒定注入，交接卡不需要靠边权重获得存在感。衰减只调
# 结构参数、不碰任何记忆内容；对既有库，全量重建（rebuild-edges）时生效。
HANDOFF_EDGE_DECAY = 0.85


def extract_entities(text: str) -> Set[str]:
    """从原文抽取确定性锚点：文件路径 / 函数名 / 全大写代号 / owner-repo。

    纯只读抽取，不生成任何新语义、不回写内容（内容冻结完整保持）。
    抽取结果只用于建 entity 边——回答"这两条记忆凭什么相关"。
    """
    out: Set[str] = set()
    for m in _PATH_RE.finditer(text):
        out.add(m.group(0).lower())
    for m in _FUNC_RE.finditer(text):
        out.add(m.group(1).lower())
    for m in _CODE_RE.finditer(text):
        out.add(m.group(1))
    for m in _REPO_RE.finditer(text):
        whole = m.group(0)
        tail = whole.rsplit("/", 1)[-1]
        if "." in tail:  # 带扩展名的是文件路径，已由 _PATH_RE 覆盖
            continue
        out.add(whole.lower())
    return {e for e in out if len(e) >= _ENTITY_MIN_LEN}


def _node_entities(n: MemoryNode) -> Set[str]:
    """节点锚点集合 = 原文抽取出的符号 ∪ 用户显式打的标签。"""
    ents = extract_entities(n.content)
    ents |= {"tag:" + t.strip().lower() for t in n.tags if t.strip()}
    return ents


def _ordered(a: str, b: str) -> Tuple[str, str]:
    """边方向归一（小 id 在前）：避免 (a,b) 与 (b,a) 重复成两条边。"""
    return (a, b) if a <= b else (b, a)


def build_entity_edges(
    store: MemoryStore,
    node: MemoryNode,
    max_edges: int = 5,
    base_weight: float = 0.85,
) -> List[Tuple[str, str, float]]:
    """共享确定性锚点的记忆之间建 entity 边（v0.14）。

    与 semantic 边互补：semantic 依赖统计代理（字符共现/向量相似），
    entity 依赖原文中确凿存在的同一符号——不靠字面巧合。

    每节点最多 max_edges 条（按共享锚点数降序），保持图稀疏、
    省存储也省 token；内容冻结：只读原文与标签，不改任何记忆内容。
    任一端为交接卡（kind=handover）时，权重乘 HANDOFF_EDGE_DECAY——
    交接卡由工作台槽位恒定注入，不需要靠边权重抬排名（v0.15）。
    """
    ents = _node_entities(node)
    if not ents:
        return []
    others = store.all_nodes()
    kind_of = {n.node_id: n.kind for n in others}
    scored: List[Tuple[int, str, List[str]]] = []
    for other in others:
        if other.node_id == node.node_id:
            continue
        shared = ents & _node_entities(other)
        if not shared:
            continue
        scored.append((len(shared), other.node_id, sorted(shared)[:2]))
    scored.sort(reverse=True)

    added: List[Tuple[str, str, float]] = []
    for nshared, other_id, sample in scored[:max_edges]:
        src, dst = _ordered(node.node_id, other_id)
        weight = round(min(0.95, base_weight + 0.05 * (nshared - 1)), 4)
        if node.kind == "handover" or kind_of.get(other_id) == "handover":
            weight = round(weight * HANDOFF_EDGE_DECAY, 4)
        evidence = "ent:" + ",".join(sample)
        if store.edge_weight(src, dst) == weight:
            continue  # 幂等：同权重不重写
        store.add_edge(src, dst, weight, kind="entity", evidence=evidence)
        added.append((src, dst, weight))
    return added


def _gram_set(text: str, ngram: int = 2) -> set:
    t = "".join(text.lower().split())
    if not t:
        return set()
    if len(t) <= ngram:
        return {t}
    return {t[i: i + ngram] for i in range(len(t) - ngram + 1)}


def jaccard_pmi(a: str, b: str) -> float:
    """PMI 的共现代理：两段文本共享的区分性片段占比越高，关联越强。"""
    sa, sb = _gram_set(a), _gram_set(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def build_edges(
    store: MemoryStore,
    embedder: Embedder,
    lam: float = 0.5,
    min_weight: float = 0.15,
    pmi_fn: Callable[[str, str], float] = jaccard_pmi,
    only_new: Optional[MemoryNode] = None,
) -> List[Tuple[str, str, float]]:
    """建边，返回本次实际写入的新增边 [(src, dst, weight)]。

    only_new   增量模式：传入刚写入的新节点，只计算它与库内既有节点的
               关联（O(n)）——memory_add / cli add 的常规路径。
    全量模式   only_new=None 时全库两两重建（O(n²)）——仅 init 后首次建图
               或 membridge rebuild-edges 显式触发。
    lam        论文中的平衡系数 λ：PMI 共现项与语义相似项的权重比
    min_weight 低于该权重的关联不落库（保持图稀疏，对应论文 edge density < 0.1%）

    embedder 参数保留以兼容既有调用签名；权重直接由已存储的向量计算。
    """
    if only_new is not None:
        others = (n for n in store.all_nodes() if n.node_id != only_new.node_id)
        pairs: Iterator[Tuple[MemoryNode, MemoryNode]] = (
            (only_new, b) for b in others
        )
    else:
        nodes = store.all_nodes()
        pairs = (
            (nodes[i], nodes[j])
            for i in range(len(nodes))
            for j in range(i + 1, len(nodes))
        )
    added: List[Tuple[str, str, float]] = []
    for a, b in pairs:
        pmi = pmi_fn(a.content, b.content)
        cos = cosine(a.embedding, b.embedding)
        w = lam * pmi + (1.0 - lam) * cos
        if w < min_weight:
            continue
        weight = round(w, 4)
        src, dst = _ordered(a.node_id, b.node_id)
        if a.kind == "handover" or b.kind == "handover":
            weight = round(weight * HANDOFF_EDGE_DECAY, 4)
        if store.edge_weight(src, dst) == weight:
            continue  # 已存在且权重未变：不重写（幂等，写放大归零）
        # 共现主导（字面重叠高但语义向量不相似）单独标注，
        # 与语义主导区分开——"为什么相关"可解释（v0.14 类型化边）
        kind = "cooccur" if pmi > cos else "semantic"
        store.add_edge(
            src, dst, weight, kind=kind, evidence=f"pmi={pmi:.2f},cos={cos:.2f}"
        )
        added.append((src, dst, weight))
    return added
