# 记忆桥 MemoryBridge

> 🌉 **给 AI 一个跟着你走的记忆** —— 跨设备 × 跨平台的共享记忆层
>
> CDSMP（大模型跨设备语义记忆连续性架构）的官方工程实现。
> [English](README_EN.md) · [设计 RFC](docs/RFC-001-architecture.md) · [路线图](docs/roadmap.md) · [隐私威胁模型](docs/threat-model.md) · [版本历程](CHANGELOG.md)

![Version](https://img.shields.io/github/v/release/jiabaobei/memory-bridge)
![CI](https://github.com/jiabaobei/memory-bridge/actions/workflows/ci.yml/badge.svg)
![License](https://img.shields.io/badge/license-MIT-green)
![Python](https://img.shields.io/badge/python-3.9%2B-blue)
![核心零依赖](https://img.shields.io/badge/core%20deps-0-success)

## 这解决什么问题

早上通勤时你在手机上和 AI 讨论到一半的推理，回到办公室想在 PC 上继续——
今天的做法是：翻聊天记录、复制粘贴、重新解释一遍背景。

云全量同步很重也未必安全；RAG 是"到了新设备再被动检索"；主流记忆系统
（Mem0、MemGPT/Letta 等）本质上是**单机的**。记忆桥的答案是三个差异化主张：

1. **跨设备连续性**：记忆跟着人走，而不是跟着 App 走。手机、PC、平板共享同一份语义记忆，通过增量差分同步。
2. **边缘预加载**：在你打开新设备之前，高热度的记忆已经被推送到位——切换即连续，而不是切换后等待检索。
3. **内容冻结原则**：记忆桥只提取语义关联、只调节结构参数，**永不改写你的原始记忆内容**。这正是论文所依据的 Faulty Memory 研究的结论：让 LLM 自动改写/摘要记忆，必然引入幻觉式失真。

同时，记忆桥是**跨平台**的：通过 MCP 协议，同一个记忆库可以被 Claude Code、Cursor、Cline 等任意 MCP 客户端共享使用（平台覆盖详情见下文矩阵）。

## 当前能力（v0.9）

| 能力 | 说明 | 状态 |
|---|---|---|
| 三路混合检索 + RRF | 向量 + 关键词（字面命中兜底）+ SAN 图谱一跳三路召回，按排名做 RRF 融合（k=60）——多路共识天然加分，无新参数可调 | ✅ v0.9 |
| 预算注入 + 沉默契约 | Path A 注入受 token 预算约束，超预算条目注入**原文前缀**（截断 ≠ 改写，内容冻结无损）；无高质量命中时明确返回「本轮不干预」，不硬凑弱命中 | ✅ v0.9 |
| MCP 工具描述瘦身 | 三个工具的描述各压缩到一行——工具描述常驻每个客户端会话，省 token 从描述面开始 | ✅ v0.9 |
| 缺口发现 | 零命中查询记入本地（纯元数据），`doctor` 显示缺口并提示——系统只提醒，内容永远由用户写 | ✅ v0.9 |
| 可选 kind 标注 | `fact`（稳定事实）/ `procedure`（试过什么、结果怎样）可选标注，纯可选不强制 | ✅ v0.9 |
| 增量建边 | 写入时只计算新节点与既有节点的关联（O(n)，不再每次全量 O(n²) 重算）；`membridge rebuild-edges` 提供全量重建出口 | ✅ v0.8 |
| 工程健壮性 | SQLite WAL 并发 + 单事务原子提交（add+建边、差分应用）；差分包"数据错误跳过 / 环境错误保留重试"分流 | ✅ v0.8 |
| token 经济 | MCP 工具收敛为 3 个（context 并入 search）、检索相对阈值滤除弱命中、超长记忆写入软引导拆分 | ✅ v0.8 |
| doctor 库位置健康 | 库位于临时/生成目录、多库分裂（默认库与环境变量库并存）、设备名未设置——显式告警 | ✅ v0.8 |
| 存储与检索优化 | embedding 以 float32 BLOB 存储（体积降为 JSON 的 1/3～1/5，旧库打开自动迁移），检索两阶段 + 进程内向量缓存 | ✅ v0.8 |
| 一键接入平台 | `membridge init` 自动检测并配置主流 AI 平台（MCP 自动写入 / WorkBuddy 技能自动安装 / 其余打印指南） | ✅ v0.2 |
| 全自动同步 | 云盘自动选定（多盘按优先级）、口令由系统生成并托管（用户无感）、按重要程度自动上云（计划任务每 15 分钟），零点击 | ✅ v0.5/v0.6 |
| 环境变量口令 | 口令支持 `MEMBRIDGE_PASSPHRASE` 环境变量（优先级：参数 > 环境变量 > 保险库），自动化/CI 场景免交互 | ✅ v0.7 |
| 便携免安装 | `membridge.exe` 单文件构建（scripts/build_exe.bat），拷到任何 Windows 机器即用，无需 Python | ✅ v0.4 |
| 嵌入一致性握手 | 差分包内嵌嵌入器指纹，两端模型不一致即拒绝同步——排除记忆语义漂移 | ✅ v0.4 |
| SAN 语义关联网络 | 记忆条目 + 语义向量 + 关联边（`w_ij = λ·共现 + (1-λ)·余弦`） | ✅ v0 已实现 |
| Path A 记忆注入 | 高置信记忆序列化为上下文块拼入 prompt（显式、可审计） | ✅ v0 已实现 |
| MCP Server | 任意 MCP 客户端即插即用；`--http` 远程模式供扣子 Coze 等平台接入 | ✅ v0 已实现 |
| DSS 增量同步 | 语义指纹 + 边差异量化（ε=0.01），只传差异不传全量 | ✅ 已实现 |
| 网盘中转传输 | 差分包写入百度网盘同步盘/坚果云/OneDrive 等同步文件夹即可跨设备，默认端到端加密，网盘服务商只见密文 | ✅ v0 已实现 |
| PAMS 隐私门控 | L1 迁移标签（local 节点永不离开设备）+ L2 场景域隔离 | ✅ v0 已实现；L3 差分隐私后置 |
| TMT 热度与预加载 | recency × frequency 启发式，热度 Top-K 预加载候选 | ✅ v0 启发式；边缘驻留 Phase 3 |
| AEE 自适应进化 | α/π_nav/θ_window 等结构参数自适应 | 📋 Phase 4（接口已预留） |
| Path B 隐藏状态融合 | 隐藏状态注入层间激活 | 🧪 Phase 4（experimental 分支） |

## 与同类项目的差异

| | 记忆桥 | OpenMemory (mem0) | MemGPT/Letta |
|---|---|---|---|
| 跨应用共享（MCP） | ✅ | ✅ | — |
| **跨设备同步**（手机↔PC↔边缘） | ✅ 核心能力 | ❌ 单机 | ❌ |
| 切换前**预加载**（零等待） | ✅ | ❌ 被动检索 | ❌ |
| **内容冻结**（不重写记忆） | ✅ 架构级约束 | ❌ LLM 摘要改写 | 部分 |
| 隐私分级（迁移标签 + 场景域） | ✅ | 部分 | ❌ |

## 领域收敛：外置记忆路线正在被前沿研究背书

记忆桥的三个差异化主张不是孤立的设计选择。2026 年的前沿工作正从三个独立方向
收敛到同一条路线：

- **Metis（记忆基础模型，arXiv 2607.26760）** 把历史压进模型内部参数，
  但论文自己承认：固定容量必然遗忘、参数态**难以审计、难以精确删除、隐私
  边界难保证**，并给出混合蓝图——低频、可审计、超长历史继续留在外部存储，
  由外部系统负责容量、可解释检索与纠错。这正是记忆桥所在的生态位：
  原生记忆是互补者，不是替代者。
- **Proactive Memory Agent（Meta，arXiv 2607.08716）** 证明长程任务的
  关键不是"存更多"，而是"哪条记忆应该在什么时候重新进入决策回路"——
  其核心载体就是一个独立于模型的**外置结构化记忆库** + 守门策略，且消融显示
  「把沉默当作动作」比全量暴露更稳。记忆桥 v0.9 的沉默契约与相对阈值
  过滤与之同构。
- **Perplexity Portable Computer**（本地 Agent，零 token 成本）的工程纪律
  ——极小系统提示、极少核心工具、按需加载——验证了记忆桥「极度省 token」
  原则的普适性；其"敏感内容不出设备 + 出口显式门控"与 PAMS 设计哲学一致。

v0.9 即是一次对照这三份研究的集中借鉴（检索质量 / token 经济 / 缺口发现），
全部只落在检索、注入与调度层——**不改写任何记忆内容**，详见
[路线图「借鉴版」一节](docs/roadmap.md)。

## 平台覆盖（跨平台记忆共享）

用户只需运行 **`membridge init`**：自动检测本机已安装的平台并接入（幂等安全，重复执行无副作用）。

| 接入方式 | 覆盖的平台 | 状态 |
|---|---|---|
| **init 自动配置（MCP）** | ZCode、Claude Code、Claude 桌面版、Cursor、Cline、Windsurf、VS Code（Copilot MCP）、Gemini CLI、通义千问 Code | ✅ v0.2 |
| **init 技能自动安装（SKILL.md）** | WorkBuddy（`~/.workbuddy/skills`）、Claude 技能目录 | ✅ v0.2 |
| **远程 MCP（HTTP 模式）** | 扣子 Coze 等支持远程 MCP 的平台（`membridge mcp --http` 后经 URL 接入） | ✅ v0.2 |
| **init 手动指南** | 字节 Trae 等界面化 MCP 平台（init 打印逐步指引） | ✅ v0.2 |
| **CLI / SDK** | 任意能调用命令行的环境（剪贴板兜底：`membridge context "<主题>"`） | ✅ v0 |
| **浏览器插件** | 豆包、Kimi、ChatGPT 网页版等封闭 Web 助手 | 📋 Phase 1+ |

> 对完全封闭、不支持任何外部接入的 App，兜底方案是"剪贴板/分享"通道
> （`membridge context` 复制粘贴），永远可用。

## 快速开始

```bash
git clone https://github.com/jiabaobei/memory-bridge.git
cd memory-bridge
pip install -e .
membridge init               # 强制完成云盘通道配置（默认必做，检测已装同步盘自动配好；
                             # 没有则引导免费云盘；确要跳过需显式确认），
                             # 随后自动接入本机各 AI 平台
python examples/demo.py      # 90 秒看懂：手机记忆 → 差分包 → PC 无缝继续
```

> 为什么第一件事是配云盘？**记忆不上云，跨设备无从谈起。** 早上手机上的讨论，
> 只有进了云盘通道，办公室的电脑才能接着继续。按论文测算你的记忆一年仅约 1GB，
> 任何免费云盘都够用；且同步的是端到端加密的差分包——云盘服务商也看不到内容。

### CLI

```bash
membridge init                                           # 一键接入本机检测到的 AI 平台
membridge add "用户在开发记忆桥项目" --tags dev          # 写入记忆（可选 --kind fact / procedure）
membridge search "记忆桥" -k 3                          # 三路混合检索（向量 + 关键词 + 图谱，RRF 融合）
membridge context "继续早上的讨论"                       # 输出 Path A 上下文块（无命中时明确"本轮不注入"）
membridge preload 我的手机                               # 预加载候选（PAMS 门控）
membridge delta phone.db --out delta.json               # 生成到另一设备的差分包
membridge apply delta.json                              # 并入差分包
membridge publish --dir "D:\百度网盘同步盘\membridge" --passphrase 我的口令   # 发到网盘通道
membridge fetch   --dir "D:\百度网盘同步盘\membridge" --passphrase 我的口令   # 从网盘取回
membridge stats                                         # 记忆库概况
membridge rebuild-edges                                 # 全量重建语义关联边（常规 add 只增量建边）
membridge doctor                                        # 环境自检（库位置健康 + 记忆缺口提醒）
membridge autosync                                      # 自动同步（init 已注册计划任务，每 15 分钟自动运行）
membridge show-passphrase                               # 配对新设备时查看同步口令（系统已替你生成并托管）
membridge set-passphrase                                # 手动设置/修改同步口令（一般不需要）
```

口令也可由环境变量 `MEMBRIDGE_PASSPHRASE` 提供，免得每次手输。

#### 云盘差分包丢失时的补救

`publish` 只发送「本地记录中尚未发布过」的记忆。若云盘侧差分包被误删、
或同步故障清空了通道，本地仍认为已发布——此时：

```bash
membridge publish --dir "..." --force    # 忽略本地记录，重发全量重建通道
```

不加 `--force` 会输出「没有需要发布的新记忆。」，这是幂等表现，不是故障。

### 手动接入 MCP 客户端（`membridge init` 已覆盖的平台可跳过）

个别平台如需手动配置，Claude Code：

```bash
claude mcp add memory-bridge -- membridge mcp
```

Cursor / 其他 MCP 客户端（`mcp.json`）：

```json
{
  "mcpServers": {
    "memory-bridge": {
      "command": "membridge",
      "args": ["mcp"],
      "env": { "MEMBRIDGE_DB": "D:/mem/my.db", "MEMBRIDGE_DEVICE": "我的PC" }
    }
  }
}
```

可用工具：`memory_add`（Add，可选 `kind` 标注）、`memory_search`（Search，
三路混合检索；`as_context=true` 直接返回带预算的 Path A 注入块，无高质量
命中时明确告知本轮不注入）、`memory_preload`（Preload）——严格限定在 UEP
权限边界内，没有"改写记忆"的工具。

## 架构一览

```
              ┌────────────────────────────────────────────────┐
              │           跨平台接入层（连接器）                  │
              │  MCP Server │ CLI │ 平台技能（WorkBuddy 等）     │
              │        移动端 / 浏览器插件（计划中）               │
              └───────────────────────┬────────────────────────┘
                                      │ 仅开放 Add / Search / Preload
   ┌──────────────────────────────────▼───────────────────────────────────┐
   │                 CDSMP 六阶段流水线（记忆桥核心）                        │
   │                                                                      │
   │   感知 ──▶ 蒸馏 ──▶ 缓存 ──▶ 同步 ──▶ 注入 ──▶ 反馈                   │
   │            SAN    TMT    DSS    Path A    AEE(Phase 4)               │
   │                                                                      │
   │        PAMS 三级隐私隔离（贯穿所有阶段的数据出口）                       │
   └──────────────────────────────────┬───────────────────────────────────┘
                                      │ DSS 差分包（默认端到端加密）
                                      │ 通道：网盘中转 ✅ / 局域网直连 / 实时中继（Phase 2）
                        ┌─────────────▼──────────┐
                        │  本设备记忆库（SQLite）   │◀──▶ 手机 / 平板 / 边缘网关
                        └────────────────────────┘
```

模块与论文公式的逐条映射见 [docs/RFC-001-architecture.md](docs/RFC-001-architecture.md)。

## 路线图

- **Phase 0 ✅** 仓库与骨架、核心引擎 v0（SAN + Path A + DSS 本地差分 + PAMS L1/L2）、MCP Server
- **Phase 1 🔄** `membridge init` 一键接入 + doctor 自检 + WorkBuddy 技能 + 远程 MCP 已完成（v0.2）；待办：PyPI 发布、真实 embedding 后端、TS SDK
- **Phase 2** 跨设备传输通道：E2E 加密中继（自托管）、版本向量、冲突解决
- **Phase 3** TMT 边缘驻留（hot/cold 两级）、预加载时机、移动端接入、L2 授权流
- **Phase 4** AEE 自适应进化（α / π_nav / θ_window）、Path B experimental 分支、L3 差分隐私、UEP 评测复现脚本

详见 [docs/roadmap.md](docs/roadmap.md)。

## 与论文的关系

记忆桥是论文《大模型跨设备语义记忆连续性架构（CDSMP）》的工程实现，论文中
未实现/后置的组件（Path B、AEE、L3、完整评测）在项目中按同样的顺序后置。
论文预印本已发布于 Zenodo（含完整 LaTeX 源文件包）：[DOI 10.5281/zenodo.22064641](https://doi.org/10.5281/zenodo.22064641)。
README 与文档中引用的实验数字（如 TCR 94.7%、带宽 −89%、token 开销 −87.1%）
均为**论文报告值**，对应复现脚本将在 Phase 4 随 `benchmark/` 目录提供。

```bibtex
@techreport{cdsmp2026,
  title  = {大模型跨设备语义记忆连续性架构：基于边缘预加载与多级热缓存的零认知开销推理（CDSMP）},
  author = {鲜妤佳},
  year   = {2026},
  doi    = {10.5281/zenodo.22064641},
  note   = {预印本 v7}
}
```

## 隐私

三条不变承诺（详细威胁模型见 [docs/threat-model.md](docs/threat-model.md)）：

1. `local` 标签的记忆**在代码路径上**就不可能离开原设备（不是策略承诺，是结构保证）；
2. 跨设备同步的默认门控为 PAMS L1/L2，敏感内容自动降级为 local；
3. 记忆库是单机单文件（SQLite），可以整库加密、整库删除、整库带走。

## 参与

```bash
pip install -e ".[dev]"    # 或不装任何东西：python tests/run_tests.py
pytest -q
```

设计变更请先提 Issue 或阅读 [docs/RFC-001-architecture.md](docs/RFC-001-architecture.md)。
特别欢迎：真实 embedding 后端、移动端连接器、同步中继实现、评测复现。

## 灵感与致谢

- [Tencent ncnn](https://github.com/tencent/ncnn)：v0.4 起借鉴其零依赖、自描述模型文件
  （param/bin）与便携免安装发布的工程实践，映射详见
  [docs/design-notes/ncnn-borrowings.md](docs/design-notes/ncnn-borrowings.md)。
- Metis（arXiv 2607.26760）、Proactive Memory Agent（arXiv 2607.08716）与
  Perplexity Portable Computer：v0.9 的检索融合、预算注入、沉默契约与工具
  描述瘦身借鉴自这三份工作，逐项映射与"明确不借"清单见
  [路线图「借鉴版」一节](docs/roadmap.md)；airllm 的"只载入当前需要的层"
  启发了超额条目的原文前缀注入。

## License

[MIT](LICENSE)
