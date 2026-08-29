# Changelog

所有显著变更记录于此。格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)。

## [0.1.0] - 2026-08-29

### 新增
- 核心引擎 v0：`MemoryNode` / `MemoryStore`（SQLite 单文件）
- 蒸馏层：SAN 语义关联网络（`w_ij = λ·共现代理 + (1-λ)·余弦`，PMI 项可注入替换）
- 注入层：Path A 显式上下文拼接（`injection.serialize` / `build_prompt_aug`）
- 同步层：DSS 增量语义同步（语义指纹 + 边差异量化 ε=0.01 + 差分包编码/应用）
- 隐私层：PAMS L1 迁移标签 + L2 场景域门控（L3 差分隐私按约定后置）
- 缓存层：TMT 热度启发式（recency × frequency）与预加载候选
- MCP Server：`memory_add` / `memory_search` / `memory_context` / `memory_preload`
- CLI：`add` / `search` / `context` / `preload` / `delta` / `apply` / `stats` / `mcp`
- 端到端演示 `examples/demo.py`（手机 → PC 跨设备记忆继承）
- 测试：7 项核心测试（pytest 与零依赖运行器双兼容）
- 文档：设计 RFC、路线图、隐私威胁模型、中英双语 README

### 设计决策（按约定后置）
- Path B 隐藏状态融合 → Phase 4 experimental 分支
- AEE 自适应进化引擎（α / π_nav / θ_window）→ Phase 4（接口签名已对齐论文）
- L3 内容级差分隐私 → Phase 4+（Phase 2 先以端到端加密兜底）
