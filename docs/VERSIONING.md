# 版本与发布规约

适用范围：memory-bridge 全部代码与文档变更。项目所有者（jiabaobei）于 2026-08-29 定立。

## 1. 版本号规则（语义化版本：主.次.修订）

| 变更类型 | 版本动作 | 示例 |
|---|---|---|
| 新增功能、新通道、新连接器 | 升**次版本** | 0.1.0 → 0.2.0 |
| 缺陷修复、文档勘误、小优化 | 升**修订版本** | 0.2.0 → 0.2.1 |
| 不兼容的架构 / 接口变更 | 升**主版本** | 0.x → 1.0.0 → 2.0.0 |

0.x 阶段对外标注 Alpha；1.0.0 的门槛是 UEP 评测复现（roadmap Phase 4）完成。

## 2. 版本号写在哪（三处必须同步）

1. `pyproject.toml` → `[project] version`
2. `src/membridge/__init__.py` → `__version__`
3. `CHANGELOG.md` → 对应版本的条目

## 3. 每次改版的固定动作（缺一不可）

1. 完成代码 / 文档改动，测试通过（`python tests/run_tests.py`）
2. 升版本号（三处同步）
3. 在 `CHANGELOG.md` 顶部新增该版本条目：**一段简短精炼的改版说明**
   （一句话主题 + 要点列表）——这是项目全过程的历程记录
4. `git commit`
5. `git tag vX.Y.Z` 并 `git push origin main vX.Y.Z`
6. `gh release create vX.Y.Z --title "vX.Y.Z 一句话主题" --notes-file <notes>`
   —— GitHub Release 是对外的历程记录，说明与 CHANGELOG 保持一致

## 4. 特别约定

- 修改 `.github/workflows/*` 需要 workflow 权限令牌（gh 默认登录令牌无此权限），避免无谓改动
- 论文组件（Path B / AEE / L3 差分隐私）按 RFC-001 §13 后置，不因版本节奏提前
- AI 协作会话遵守仓库根目录 `AGENTS.md`
