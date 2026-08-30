# 路线图

约定：每个 Phase 结束时主线分支保持可发布（测试全绿、demo 可跑）。
三项原则性后置（Path B / AEE / L3）见 RFC-001 §13，不因任何 Phase 提前。

## 版本总览（逐版本改版说明）

> 本节即"改版说明"索引：一行一版，倒序。完整条目见 [CHANGELOG.md](../CHANGELOG.md)，
> 每个版本在 GitHub Releases 页有对应发布。v0.4.1 起大量版本号由实战反馈驱动。

| 版本 | 日期 | 改版说明 |
|---|---|---|
| v0.8.1 | 2026-08-30 | 实战修复：跨盘符差分导出被误判路径穿越（C 盘默认库 + D 盘正式库场景），改为逐基座独立判断 |
| v0.8.0 | 2026-08-30 | 工程修订：增量建边 O(n²)→O(n)、embedding float32 BLOB + 旧库自动迁移、WAL + 单事务原子提交、MCP 工具面 4→3（token 经济）、doctor 库位置健康检查、修复测试劫持用户真实配置的两处隔离洞、内容冻结守卫测试 |
| v0.7.0 | 2026-08-30 | 环境变量口令 `MEMBRIDGE_PASSPHRASE` + 测试环境隔离 + 文档同步 |
| v0.6.1 | 2026-08-29 | 补齐 v0.6.0 遗漏的 force 文档与测试，口令报错改为可操作提示 |
| v0.6.0 | 2026-08-29 | 同步口令零负担：系统自动生成并 DPAPI 托管，用户彻底不用记 |
| v0.5.1 | 2026-08-29 | 口令设置体验修复：空回车不再静默跳过，新增 `set-passphrase` |
| v0.5.0 | 2026-08-29 | 全自动同步：重要记忆立即上云、普通记忆批量上云，用户零点击 |
| v0.4.1 | 2026-08-29 | WorkBuddy 实战反馈双修复：全新机器建库崩溃 + 记忆库割裂（一机一库语义确立） |
| v0.4.0 | 2026-08-29 | 借鉴腾讯 ncnn 工程实践：自描述包、运行时能力调度、便携免安装构建 |
| v0.3.1 | 2026-08-29 | 云盘配置强制化：init 必做第一步（记忆不上云，跨设备无从谈起） |
| v0.3.0 | 2026-08-29 | 安装即上云：云盘配置成为第一件事，自动识别已装同步盘 |
| v0.2.1 | 2026-08-29 | README 同步 v0.2 能力（文档勘误） |
| v0.2.0 | 2026-08-29 | 一键接入：init 自动配置主流 AI 平台（MCP / 技能 / 手动指南），新增 doctor 自检 |
| v0.1.1 | 2026-08-29 | 修复 mcp 2.x 兼容（锁定 mcp>=1.2,<2），依赖缺失给可操作提示 |
| v0.1.0 | 2026-08-29 | 首个公开版本：跨设备、跨平台 AI 共享记忆层（SAN + DSS + PAMS + Path A + MCP） |

## 工程修订 ✅（v0.8.0，2026-08-30）

对照外部评审与作者两大产品原则（极度省 token、极度简化易上手）的集中修订：

- [x] 增量建边：add 只算新节点关联（O(n)）；`membridge rebuild-edges` 全量重建出口
- [x] embedding float32 BLOB 存储 + 旧库自动迁移 + 检索两阶段 + 进程内向量缓存
- [x] SQLite WAL + busy_timeout + transaction() 单事务原子提交（add+建边 / 差分应用）
- [x] 差分包 fetch 异常分流：数据错误 skip / 环境错误（OSError）errors 且保留重试
- [x] 工具面收敛：memory_context 并入 memory_search（as_context 参数），4 → 3 个
- [x] token 经济：检索相对阈值滤弱命中；add 超 200 字软引导"一句话一条"
- [x] doctor 库位置健康：临时/生成目录、多库分裂、设备名未设置告警
- [x] MCP open_store 废除 CWD 相对兜底，统一 default_db_path（一机一库）
- [x] embedder 指纹支持 revision 版本标识（为空时与 v0.7 握手兼容）

## Phase 0 ✅（2026-08-29 完成）

- [x] 仓库骨架、MIT License、中英双语 README、CI（3.9–3.13 矩阵）
- [x] 核心引擎 v0：存储 / SAN / 热度 / Path A / DSS 本地差分 / PAMS L1+L2
- [x] MCP Server（memory_add / memory_search / memory_context / memory_preload）
- [x] CLI（add / search / context / preload / delta / apply / stats / mcp）
- [x] 端到端 demo（手机 → 差分包 → PC）与 7 项核心测试
- [x] 设计 RFC、威胁模型

## Phase 1 — 可安装性与真实语义

- [x] `membridge init` 一键接入向导：主流平台检测 + 自动配置 + 手动指南（v0.2.0）
- [x] `membridge doctor` 环境自检（v0.2.0）
- [x] WorkBuddy 记忆技能包自动安装（v0.2.0）
- [x] `membridge mcp --http` 远程模式：扣子 Coze 等平台经 URL 接入（v0.2.0）
- [x] 便携 `membridge.exe` 免安装构建（借鉴 ncnn 便携发布，v0.4.0）
- [ ] PyPI 发布（`pip install membridge`）
- [ ] 真实 embedding 后端：OpenAI / 本地 bge（含 embedder 标识写库与校验）
- [ ] TypeScript SDK（覆盖 Cursor/Cline 生态的 TS 用户）
- [ ] README 动图（GIF/视频）：跨设备演示

## Phase 2 — 跨设备传输通道（安全优先）

- [x] **文件夹 / 网盘中转通道（v0 已实现）**：百度网盘同步盘 / 坚果云 / OneDrive /
      U 盘 / 局域网共享皆可为通道；差分包默认 Fernet 口令端到端加密，
      `archive/` 兼作论文 T4 云归档
- [x] **云盘前置上导向导（v0.3.0）**：init 第一步配置云盘；自动识别坚果云 / OneDrive /
      百度网盘同步盘 / iCloud 云盘 / Dropbox / Google Drive；未装时引导免费云盘
- [x] **全自动同步（v0.5/v0.6 提前落地）**：通道自动选定 + 口令系统自动生成并
      DPAPI 托管 + 计划任务每 15 分钟双向同步 + 重要度上云规则（重要立即/普通批量）
- [ ] E2E 加密实时中继（可自托管）：设备密钥对、中继只见密文
- [ ] 局域网直连通道
- [ ] 版本向量与冲突解决（Delta.seq 启用，LWW 起步）
- [x] **embedder 一致性握手**（借鉴 ncnn 自描述 param 思想，提前实现于 v0.4）：
      差分包内嵌嵌入器指纹，两端模型不一致即拒绝应用
- [ ] `membridge pair`：设备配对流程（二维码/配对码）
- [ ] 同步节流与断点续传
- [ ] 记忆格式转换器（借鉴 ncnn 的 pnnx 生态：从 ChatGPT / Claude / mem0 导出导入）

## Phase 3 — 边缘预加载与移动端

- [ ] TMT hot/cold 两级驻留（对应论文 T1/T2/T3）
- [ ] 预加载时机：显式信号 + 简单时间模式（θ_window 固定冷启动值）
- [ ] L2 跨场景域显式授权流
- [ ] 移动端接入：Android（Termux/MobileMCP 优先）、iOS 快捷指令
- [ ] 记忆库整库加密（SQLCipher 或应用层加密）

## Phase 4 — AEE 与研究模块

- [ ] AEE：α 在线自适应（有限差分梯度）
- [ ] π_nav：SAN 图游走导航替换热度 Top-K（Deep Drill / Broad Scan / Device Bridge）
- [ ] θ_window 自适应与带宽熔断
- [ ] Path B experimental 分支（本地开源模型，维度对齐 + 稳定性约束）
- [ ] L3 差分隐私（按数据类型的 ε_DP 配置）
- [ ] `benchmark/`：UEP 轻量评测 + 论文数字复现脚本
