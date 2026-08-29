# AGENTS.md — 记忆桥项目规约（AI 协作会话必读）

所有者：jiabaobei（2026-08-29 定立）

## 版本与发布（硬性规则，所有者 2026-08-29 定）

1. **每次改版必须升版本号**，并在三处同步：`pyproject.toml`、
   `src/membridge/__init__.py` 的 `__version__`、`CHANGELOG.md`。
2. **每个版本必须在 CHANGELOG.md 顶部写一段简短精炼的改版说明**
   （一句话主题 + 要点列表），用于记录项目全过程历程。
3. 发布动作固定为：commit → `git tag vX.Y.Z` → push →
   `gh release create vX.Y.Z`（Release 说明与 CHANGELOG 一致）。
   版本号语义与完整流程见 `docs/VERSIONING.md`。

## 架构铁律

- **内容冻结**：任何模块不得改写记忆内容，只允许调节结构参数（RFC-001）。
- **后置约定**：Path B / AEE / L3 差分隐私按 RFC-001 §13 后置，不提前混入主线。
- **核心零依赖**：仅 Python 标准库；可选能力一律走 extras（mcp / openai / netdisk）。
- **PAMS 出口门控**：所有数据出口（同步、预加载）必须过 `privacy.preload_allowed`。

## 工程习惯

- 改动必须附带或更新测试；零依赖验证：`python tests/run_tests.py`；CI 矩阵 3.9–3.13。
- 修改 `.github/workflows/*` 需要 workflow 权限令牌（gh 默认登录令牌无此权限）。
- 提交信息用中文，主题行说清"为什么"。
