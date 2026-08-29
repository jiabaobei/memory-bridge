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

## 当前能力（v0.1）

| 能力 | 说明 | 状态 |
|---|---|---|
| SAN 语义关联网络 | 记忆条目 + 语义向量 + 关联边（`w_ij = λ·共现 + (1-λ)·余弦`） | ✅ v0 已实现 |
| Path A 记忆注入 | 高置信记忆序列化为上下文块拼入 prompt（显式、可审计） | ✅ v0 已实现 |
| MCP Server | 跨平台接入：Claude Code / Cursor / Cline 等即插即用 | ✅ v0 已实现 |
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
membridge init               # 一键接入本机检测到的 AI 平台（可选配网盘通道）
python examples/demo.py      # 90 秒看懂：手机记忆 → 差分包 → PC 无缝继续
```

### CLI

```bash
membridge add "用户在开发记忆桥项目" --tags dev          # 写入记忆
membridge search "记忆桥" -k 3                          # 语义检索
membridge context "继续早上的讨论"                       # 输出 Path A 上下文块
membridge preload 我的手机                               # 预加载候选（PAMS 门控）
membridge delta phone.db --out delta.json               # 生成到另一设备的差分包
membridge apply delta.json                              # 并入差分包
membridge publish --dir "D:\百度网盘同步盘\membridge" --passphrase 我的口令   # 发到网盘通道
membridge fetch   --dir "D:\百度网盘同步盘\membridge" --passphrase 我的口令   # 从网盘取回
membridge stats
```

### 接入 MCP 客户端（跨平台）

Claude Code：

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

可用工具：`memory_add`（Add）、`memory_search` / `memory_context`（Search）、
`memory_preload`（Preload）——严格限定在 UEP 权限边界内，没有"改写记忆"的工具。

## 架构一览

```
              ┌────────────────────────────────────────────────┐
              │           跨平台接入层（连接器）                  │
              │    MCP Server │ CLI │ SDK │ 移动端/插件(计划)    │
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
- **Phase 1** 打磨安装体验（PyPI 发布、真实 embedding 后端、TS SDK）
- **Phase 2** 跨设备传输通道：E2E 加密中继（自托管）、版本向量、冲突解决
- **Phase 3** TMT 边缘驻留（hot/cold 两级）、预加载时机、移动端接入、L2 授权流
- **Phase 4** AEE 自适应进化（α / π_nav / θ_window）、Path B experimental 分支、L3 差分隐私、UEP 评测复现脚本

详见 [docs/roadmap.md](docs/roadmap.md)。

## 与论文的关系

记忆桥是论文《大模型跨设备语义记忆连续性架构（CDSMP）》的工程实现，论文中
未实现/后置的组件（Path B、AEE、L3、完整评测）在项目中按同样的顺序后置。
README 与文档中引用的实验数字（如 TCR 94.7%、带宽 −89%、token 开销 −87.1%）
均为**论文报告值**，对应复现脚本将在 Phase 4 随 `benchmark/` 目录提供。

```bibtex
@techreport{cdsmp2026,
  title  = {大模型跨设备语义记忆连续性架构：基于边缘预加载与多级热缓存的零认知开销推理（CDSMP）},
  author = {鲜妤佳},
  year   = {2026},
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

## License

[MIT](LICENSE)
