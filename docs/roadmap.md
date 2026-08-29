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

- [ ] PyPI 发布（`pip install membridge`）
- [ ] 真实 embedding 后端：OpenAI / 本地 bge（含 embedder 标识写库与校验）
- [ ] `membridge doctor`：环境自检（embedder 一致性、库版本）
- [ ] TypeScript SDK（覆盖 Cursor/Cline 生态的 TS 用户）
- [ ] README 动图（GIF/视频）：跨设备演示

## Phase 2 — 跨设备传输通道（安全优先）

- [ ] E2E 加密中继（可自托管）：设备密钥对、中继只见密文
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
