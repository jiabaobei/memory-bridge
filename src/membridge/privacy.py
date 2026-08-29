"""隐私层：PAMS 三级隔离的 v0 实现（论文 §3.6）。

L1 设备级：migration 标签（local / edge / cloud），local 节点禁止离开原设备 —— 已实现
L2 场景级：场景域分类 + 跨域预加载默认拒绝 —— 已实现（关键词分类器，可替换为模型）
L3 内容级：差分隐私 —— 按约定后置；Phase 2 以"同步载荷端到端加密"兜底
（中继只见密文），差分隐私进入 Phase 4+（docs/roadmap.md）。

论文约束：三级隔离是不可约组件 —— v0 虽未实现 L3，但 L1/L2 从第一版起就在
数据通路的所有出口上强制生效（见 dss.compute_delta 的门控参数）。
"""

from __future__ import annotations

from typing import Optional

from .node import MemoryNode

MIGRATION_LOCAL = "local"
MIGRATION_EDGE = "edge"
MIGRATION_CLOUD = "cloud"

# L2 场景分类器的关键词表（v0 极简版，误判率可接受；后续换小模型分类器）
_SCENE_KEYWORDS = {
    "medical": ("病历", "处方", "诊断", "血压", "用药", "医院", "diagnosis", "prescription"),
    "financial": ("银行卡", "转账", "工资", "股票", "账单", "salary", "invoice", "bank"),
    "work": ("会议", "代码", "需求", "评审", "部署", "项目", "deploy", "meeting", "code"),
}

# L1 兜底：命中即强制 local，永不离开原设备
_SENSITIVE_MARKERS = (
    "密码", "口令", "身份证", "护照", "私钥", "密钥",
    "api key", "apikey", "access token", "secret", "password", "credential",
)


def classify_scene(content: str, default: str = "personal") -> str:
    """场景域分类（PAMS L2）。命中多个域时按 medical > financial > work 取最严。"""
    text = content.lower()
    for scene in ("medical", "financial", "work"):
        if any(w in text for w in _SCENE_KEYWORDS[scene]):
            return scene
    return default


def default_migration(content: str) -> str:
    """v0 保守默认：疑似敏感内容（凭据类）一律 local；其余 edge（可到边缘网关）。"""
    lowered = content.lower()
    return MIGRATION_LOCAL if any(s in lowered for s in _SENSITIVE_MARKERS) else MIGRATION_EDGE


def preload_allowed(node: MemoryNode, target_scene: Optional[str] = None) -> bool:
    """PAMS 门控：该节点是否允许被预加载 / 迁移到目标设备。

    target_scene 为目标设备当前场景域；None 表示不做 L2 判定（仅 L1）。
    """
    if node.migration == MIGRATION_LOCAL:
        return False  # L1：local 节点永不离开原设备
    if target_scene is not None and node.scene != target_scene:
        return False  # L2：跨场景域预加载默认拒绝（显式授权流在 Phase 3）
    return True
