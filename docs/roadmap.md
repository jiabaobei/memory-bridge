# 路线图

约定：每个 Phase 结束时主线分支保持可发布（测试全绿、demo 可跑）。
三项原则性后置（Path B / AEE / L3）见 RFC-001 §13，不因任何 Phase 提前。

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
- [ ] E2E 加密实时中继（可自托管）：设备密钥对、中继只见密文
- [ ] 局域网直连通道
- [ ] 版本向量与冲突解决（Delta.seq 启用，LWW 起步）
- [ ] embedder 一致性握手（不一致拒绝同步并提示）
- [ ] `membridge pair`：设备配对流程（二维码/配对码）
- [ ] 同步节流与断点续传

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
