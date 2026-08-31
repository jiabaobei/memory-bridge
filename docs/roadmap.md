# 路线图

约定：每个 Phase 结束时主线分支保持可发布（测试全绿、demo 可跑）。
三项原则性后置（Path B / AEE / L3）见 RFC-001 §13，不因任何 Phase 提前。

## 版本总览（逐版本改版说明）

> 本节即"改版说明"索引：一行一版，倒序。完整条目见 [CHANGELOG.md](../CHANGELOG.md)，
> 每个版本在 GitHub Releases 页有对应发布。v0.4.1 起大量版本号由实战反馈驱动。

| 版本 | 日期 | 改版说明 |
|---|---|---|
| v0.11.0 | 2026-08-31 | 移动端接入版：`gateway` 手机/平板接入网关（基站模式，口令强制 + 内置随身记页面，纯标准库）、`docs/mobile.md`（iOS 快捷指令教程 + Android Termux 完整节点路线）；移动端正式加入跨设备记忆圈 |
| v0.10.0 | 2026-08-31 | memU 借鉴版：`export` Markdown 只读视图（记忆可审计可带走，永不回写）、`recall-hint` 常驻召回提示（用户自愿粘贴）；对比表补 memU；路线图记图路验证任务 |
| v0.9.0 | 2026-08-31 | 借鉴版：三路混合检索 + RRF 融合、预算注入 + 超额截断、沉默契约、MCP 工具描述瘦身、缺口发现、可选 kind 标注；README 增「领域收敛」章节（Metis / Proactive Memory Agent / Portable Computer 背书） |
| v0.8.2 | 2026-08-31 | 文档：论文预印本 Zenodo DOI 链接与 bibtex doi 字段（中英对齐） |
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

## 移动端接入版 ✅（v0.11.0，2026-08-31）

手机与平板无法复用「网盘差分包」模型（网盘 App 没有本地同步文件夹；
iOS 跑不了 Python），本版给出两条分开的路线，详见
[docs/mobile.md](mobile.md)：

- [x] **路线 A「瘦客户端 + 基站」**：`membridge gateway`（纯标准库
      http.server，零新依赖）。手机不持有完整记忆库，经口令保护的
      HTTP 读写家里常开设备上的库——移动端日常只需要 Add / Search /
      Preload 三个动作。内置随身记网页；`/add` `/search` `/preload`
      接口供 iOS 快捷指令与任意客户端直连；跨网推荐 Tailscale 自持
      组网，支持 --cert/--key TLS，绝不开公网明文端口。写入管线与
      `memory_add` 完全一致——内容冻结无任何例外
- [x] **路线 B「Android 完整节点」**（文档方案）：Termux 跑完整
      membridge，rclone 挂网盘目录做差分包通道，crond 定时——手机
      作为平等节点，离线可用
- 设计判断：路线 A 其实是 Phase 2「自托管中继」的轻量先行形态——
      中继不是独立服务，就是你自己家里那台 PC

遗留：iOS 原生 App / Android 原生 App（若做）都定位为路线 A 的
客户端壳，不引入新协议。

## memU 借鉴版 ✅（v0.10.0，2026-08-31）

对照开源竞品 memU（NevaMind-AI，Apache-2.0，「个人记忆存成 Wiki」）做的
**取舍式借鉴**——它是直接竞品，所以逐项过三原则后只借两样：

借的：

- [x] **「记忆就是文件」的可审计性** → `membridge export`：整座库渲染为
      Markdown（场景域分组 + fact/procedure 分节 + 设备/时间出处）。
      与 memU 的路线分歧在出口方向：**只读视图，永不回写**——手改导出
      文件不会、也无法流回库，内容冻结承诺多一个人人可验证的出口
- [x] **inject 缝（常驻召回指令）** → `membridge recall-hint`：打印一行
      提示由用户自愿粘贴进 CLAUDE.md / AGENTS.md。memU 由安装器代写宿主
      指令文件；我们只打印不代写（极度简化 + 不碰用户环境）

明确不借的：

- ❌ **Agent 自动蒸馏管线**（定时读会话日志 → LLM 蒸馏 → 自动入库）：
      记忆内容由 LLM 生成，幻觉从此有进库通道，与内容冻结相悖。写入
      主动权保留在明面上的 `memory_add`；经验沉淀走人工/Agent 显式写
      `kind=procedure` 的约定（README 已写明）
- ❌ 云托管同步（memu.so）：与「端到端加密、网盘只见密文」的自持隐私
      叙事正面对撞
- ❌ 500 行极简核心的形态对标：记忆桥的核心价值在跨设备同步与隐私
      分级，复杂度花在 DSS/PAMS 上是值得的

遗留的争议问题（诚实记录）：memU 的 ADR 明确论证「不做多跳图遍历，
图结构的收益配不上复杂度」。我们 v0.9 的 SAN 一跳图路恰好是中间位
（一跳、零参数、成本极低），暂保留——但 **Phase 4 UEP 必须用数据回答
图路增益**（见下）。

## 借鉴版 ✅（v0.9.0，2026-08-31）

对照三份外部研究做的集中借鉴。三条产品原则的对照检查：**内容冻结**——
全部改动只落在检索 / 注入 / 调度层，截断注入只取原文连续片段；**极度省
token**——预算注入、沉默契约、工具描述瘦身全部指向 token 开销；**极度
简化易上手**——无新命令（能力并入既有 search / context / doctor）、无新
必填参数、核心保持零依赖。

借鉴清单（来源 → 落位）：

- [x] 三路混合检索 + RRF 融合（Knowledge OS：Wiki-RAG + GraphRAG 实践）
      → 新模块 `retrieval.py`，CLI 与 MCP 检索全部切换
- [x] 缺口发现（Knowledge OS「检索即更新」的安全子集：只记元数据、只提醒，
      内容永远由用户写）→ `store.record_gap` + `doctor` 显示
- [x] 预算注入 + 超额截断（Metis：查询时只读约 56 token 而不重放 1410；
      airllm：只载入当前这一步需要的层）→ `injection.serialize` 预算填充，
      超预算条目注入原文前缀（截断 ≠ 改写，内容冻结无损）
- [x] 沉默契约（Meta Proactive Memory Agent：沉默也是动作）→ 无高置信命中
      时显式返回「本轮不干预」，不硬凑弱命中
- [x] 工具描述瘦身（Perplexity Portable Computer 的上下文纪律）→ MCP 三个
      工具描述各压缩到一行，是 v0.8「工具面 4→3」之后的第二步
- [x] 可选 `kind` 标注（Proactive Memory Agent 记忆三分法取其二：
      fact / procedure；私有进度类不进库）→ `add --kind` / `memory_add(kind=)`，
      纯可选不强制；旧库自动加列，差分序列化向后兼容

明确不借的（违背三条原则）：

- ❌ 摘要 / 改写式记忆处理（GraphRAG 社区摘要、Metis 参数态压缩写入）
      ——违反内容冻结
- ❌ 五层企业架构（Qdrant + PostgreSQL + Redis + MinIO + 编排框架）
      ——违反单文件零依赖与极简哲学
- ❌ 全量记忆常驻暴露（Proactive Memory Agent 消融证明全量暴露反而更差）
      ——违反省 token

README / README_EN 新增「领域收敛」章节，引用 Metis
（arXiv 2607.26760）、Proactive Memory Agent（arXiv 2607.08716）与
Perplexity Portable Computer 作为外置记忆路线的背书。测试 51 → 59 项。

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
- [x] 移动端接入（v0.11 路线 A 网关 + 路线 B Termux 指南先行落地，
      见 docs/mobile.md）；待办：原生 App 壳（如需）、移动端预加载推送
- [ ] 记忆库整库加密（SQLCipher 或应用层加密）

## Phase 4 — AEE 与研究模块

- [ ] AEE：α 在线自适应（有限差分梯度）
- [ ] π_nav：SAN 图游走导航替换热度 Top-K（Deep Drill / Broad Scan / Device Bridge）
- [ ] θ_window 自适应与带宽熔断
- [ ] Path B experimental 分支（本地开源模型，维度对齐 + 稳定性约束）
- [ ] L3 差分隐私（按数据类型的 ε_DP 配置）
- [ ] `benchmark/`：UEP 轻量评测 + 论文数字复现脚本
- [ ] **SAN 图路召回增益验证**：memU 的 ADR 明确弃图（"不做多跳遍历的
      前提下，图结构收益配不上复杂度"）——作为反方观点，UEP 必须测
      一跳图路相对纯向量+关键词的增益，无增益则在 1.0 前移除该路
