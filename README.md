# 记忆桥 MemoryBridge

> 🌉 **给 AI 一个跟着你走的记忆** —— 跨设备 × 跨平台的共享记忆层
>
> CDSMP（大模型跨设备语义记忆连续性架构）的官方工程实现。
> [English](README_EN.md) · [设计 RFC](docs/RFC-001-architecture.md) · [容器一致性 RFC](docs/RFC-002-container-consistency.md) · [路线图](docs/roadmap.md) · [移动端接入](docs/mobile.md) · [隐私威胁模型](docs/threat-model.md) · [版本历程](CHANGELOG.md)

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

## 当前能力（v0.31）

| 能力 | 说明 | 状态 |
|---|---|---|
| **跨设备互通零配置**（密码写在项目文档里，加密形态） | 通道密钥由**源码种子确定性派生**（PBKDF2-HMAC-SHA256 200000 轮，纯标准库），各端各自算、逐字节相同；通道目录不再存明文口令。README 逐字公布算法/盐/轮数/自检密文，**任何 AI 或语言不装本项目也能独立算出密钥并解包**。本机历史口令（环境变量 / 保险库）不再盖住它，旧通道仍用旧密钥并显式告警 | ✅ v0.31 |
| 时间窗检索（Hindsight 借鉴·只取结构层） | `scope` 新增 `at:` 时间窗：相对量 `at:7d` / `at:12h` / `at:30m` / `at:2w`、月 `at:2026-09`、日 `at:2026-09-20`、区间 `at:2026-09-01..2026-09-20`（任一端可省，**右端点含当日整天**）——对齐 Hindsight recall 的第 4 路 temporal，先过滤再融合；纯标准库解析、写法非法一律＝不过滤，`tag:` / `scene:` / `kind:` 老用法逐字节不变 | ✅ v0.30 |
| 证据计数（proof count，Hindsight 借鉴） | 按边表统计「这条记忆被多少条**不同**记忆引用」（入边出边去重）：`search` 结果行尾只读尾注 `· 被 N 条记忆引用`，RRF **同分时作次级排序键**；**注入块刻意不加**（每轮常驻 token 优先省）。v0.14 起就落库、却一直只在内部可见的边关系数，第一次对外可见 | ✅ v0.30 |
| 容器一致性（各端 schema 可声明可对账） | 容器清单 `schema.py` 实读库结构生成本端身份证（schema 版本 / 节点边字段 / 边类型枚举 / 三存储平面 / 迁移登记）；`membridge schema` 查看本端、`--peer` 与对端双向对账，缺列按迁移登记自动 ALTER 补齐；差分包携带 `edges_v2` 五元组（含 kind/evidence）随包对账——**v0.14 的类型化边跨端往返不再退化** | ✅ v0.16 |
| 三存储平面声明（mem0 借鉴） | manifest 声明 graph（edges）/ vector（nodes.embedding）/ kv（meta）三平面，实读表结构判定，缺平面即指纹不同、体检可查 | ✅ v0.16 |
| seq 版本协商（rig 借鉴） | 发包 seq 单调递增，接收端按设备记 `sync_watermark` 水位线（只增不减），重复/乱序包内容指纹去重天然幂等 | ✅ v0.16 |
| 通道密钥随通道走（各端零输入） | 通道目录里的 `channel.key` 随网盘同步到各端，首次发布自动生成——跨端共享不必再记、再传、再复述任何口令；`--passphrase` 仍优先，严格端到端加密一字未改 | ✅ v0.17 |
| 设备心跳（谁在通道里一眼可查） | 每端只写自己的 `devices/<设备>.json`（设备名 / 平台 / 最后活跃 / 节点数 / 容器指纹），只写自己的文件 → 无共享可变状态 → 零冲突；`init` 即登记，没发过包的设备不再隐身 | ✅ v0.17 |
| `membridge sync` 一键双向 | 先取回他端记忆、再发布本机新记忆，输出一行汇总；网页 / 手机 / 平板无计划任务也能对齐，各端共享节奏统一 | ✅ v0.17 |
| 通道接线描述（配一次，各端自动） | 首次配置那台设备把「接了哪家网盘 / 远端子路径 / 角色 / 凭据」加密写进通道目录的 `wiring.json`——**只写一次**：写者唯一（`written_by` 非本机则本机只读），所以没有共享可写状态，网盘上不会出现 `wiring (1).json` 冲突副本（与 `devices/` 心跳同约定）。其他端 `init` 读到即**自动接上**，不必再输一遍账号与应用密码。凭据走差分包同一条加密链（Fernet + PBKDF2，随机盐随文件携带），明文里只有写者/时间/版本/通道 ID，**账号与密码整块加密**；拿不到钥匙宁可不写（`nocrypto`），绝不落明文凭据。接线状态同时改回**本机文件** `<库目录>/netdisk.json`（原先写进共享网盘＝读-改-写，多端并发必丢更新；老位置自动迁移、老文件不删） | ✅ v0.27 |
| 网盘三端直达（双网盘主备分明：坚果云主通道 + OneDrive 备胎） | 无头端三步接线：rclone 就位（Linux 容器自动装）→ 授权（凭据只落盘权限 600 永不打印）→ 首次拉取。坚果云走 WebDAV + 应用密码（全端可达，无浏览器往返）；OneDrive 走 OAuth token（备胎，坚果云出问题时顶上，不是淘汰）。同一通道目录可两家同时接、主通道先跑；`--role` 可显式定主备。PC / Mac 已装网盘客户端则探测即指向、零配置。`netdisk-sync` 一条命令逐家完成「文件夹级双向 + 包级同步」，电脑、手机平板、网页端容器三端自动双向；`channel --move` 一条命令迁通道宿主（v0.20）；旧版 rclone 自动降级双向复制（v0.21）；体检识别桌面客户端直连、`--dir` 省略时回落已配置通道（v0.22） | ✅ v0.22 |
| 交接班（交接卡 + 工作台） | 第三种记忆类型 `kind=handover`：任务告一段落、上下文将满、或切换设备前写一张交接卡（`goal:/done:/failed:/next:/refs:` 行前缀约定；`failed` 行用硬句式留下「试过什么；因为什么；除非什么否则别重试」）。全库最新未过期交接卡成为**工作台**：注入时恒定在场、不走相关性检索——交接卡是状态声明，不是检索命中；新卡自动取代旧卡（取代是推导出来的，零新增状态位，跨设备同步后各端自动收敛到同一张卡）；超 7 天未更新自动降级为普通记忆（过期工作台比没有更危险）；交接卡触点边权重结构衰减，防止其连成超级枢纽抬排名；`membridge handoff` 查看工作台，`membridge handoff-hint` 打印常驻交接提示，随身记页面内置交接卡表单 | ✅ v0.15 |
| 类型化边 + 证据 | 边带 `kind`（semantic / cooccur / entity）+ 极短 `evidence`——每条边可回答「为什么相关」；存量库打开自动迁移（旧边标 semantic），只加结构不碰内容 | ✅ v0.14 |
| 实体锚点边 | 零依赖正则抽取代码符号 / 文件路径 / 仓库 / 标签为确定性锚点，共享同一锚点即连边——不靠字面巧合，中英混写也能连上 | ✅ v0.14 |
| 整簇预加载 | `preload --cluster`：连通分量把记忆切簇，按「当前最热节点所在簇」整簇加载——到新设备，整条任务线的上下文已就位 | ✅ v0.14 |
| 召回理由标注 | `context` 注入时标注极短命中路径（向量 / 关键词 / 图谱）——一眼判断该不该信这条记忆；`hybrid_search` 兼容封装，行为不变 | ✅ v0.14 |
| 通道归一（多设备指向同一云盘通道） | 通道身份证 `channel.json`：首设备创建，后续设备 `init` / 同步时**自动认领**；分裂（本机与通道身份证不一致）显式告警，先到先得不改写；`membridge channel` 一屏体检（本机通道 / 身份证 / 通道内出现过的设备）；OneDrive 多根目录识别（`OneDrive - 个人` 等变体）；doctor 通道健康告警。**纯元数据：不含口令、不碰记忆内容** | ✅ v0.13 |
| 网关可观测 + IP 白名单 | 基站常驻服务的排障刚需：运行时长 / 请求数 / 写入数 / 检索命中数实时可查（`/health` + 随身记页面）；`--allow` 按 IP/网段白名单放行，口令 + 白名单双保险 | ✅ v0.12 |
| 手机 / 平板接入 | `membridge gateway` 基站模式：家里一台常开设备跑网关，手机经口令保护的 HTTP 读写记忆库（内置随身记网页，可加主屏幕；iOS 快捷指令直连），纯标准库零新依赖；**旧手机可当 24 小时低功耗基站**（5–10 瓦），还能与 OlliteRT 本地模型拼成零云端个人 AI 栈，见 [移动端指南](docs/mobile.md) | ✅ v0.11 |
| Markdown 导出视图 | `membridge export` 把整座库渲染成人类可读的 Markdown（场景分组 + fact/procedure 分节 + 出处）——**只读视图，永不回写**，记忆可审计、可进 Git、可带走 | ✅ v0.10 |
| 常驻召回提示 | `membridge recall-hint` 打印一行提示，自愿粘贴进 CLAUDE.md / AGENTS.md——「任务前主动召回」代替「被动等想起」；只打印不代写宿主文件 | ✅ v0.10 |
| 三路混合检索 + RRF | 向量 + 关键词（字面命中兜底）+ SAN 图谱一跳三路召回，按排名做 RRF 融合（k=60）——多路共识天然加分，无新参数可调 | ✅ v0.9 |
| 预算注入 + 沉默契约 | Path A 注入受 token 预算约束，超预算条目注入**原文前缀**（截断 ≠ 改写，内容冻结无损）；无高质量命中时明确返回「本轮不干预」，不硬凑弱命中；v0.26 起预算装不下的召回降为**一行指针**（`mb:#id 片段`，按需 `search "片段"` 取全文，借鉴 Headroom CCR——原文冻结在库，只省注入视图），注入块稳定前缀排序 + 同输入字节一致，命中宿主 KV-cache | ✅ v0.9 / v0.26 |
| MCP 工具描述瘦身 | 三个工具的描述各压缩到一行——工具描述常驻每个客户端会话，省 token 从描述面开始 | ✅ v0.9 |
| 缺口发现 | 零命中查询记入本地（纯元数据），`doctor` 显示缺口并提示——系统只提醒，内容永远由用户写 | ✅ v0.9 |
| 可选 kind 标注 | `fact`（稳定事实）/ `procedure`（试过什么、结果怎样）可选标注，纯可选不强制 | ✅ v0.9 |
| 增量建边 | 写入时只计算新节点与既有节点的关联（O(n)，不再每次全量 O(n²) 重算）；`membridge rebuild-edges` 提供全量重建出口 | ✅ v0.8 |
| 工程健壮性 | SQLite WAL 并发 + 单事务原子提交（add+建边、差分应用）；差分包"数据错误跳过 / 环境错误保留重试"分流 | ✅ v0.8 |
| token 经济 | MCP 工具收敛为 3 个（context 并入 search）、检索相对阈值滤除弱命中、超长记忆写入软引导拆分 | ✅ v0.8 |
| doctor 库位置健康 | 库位于临时/生成目录、多库分裂（默认库与环境变量库并存）、设备名未设置——显式告警 | ✅ v0.8 |
| 记忆库内容体检 | `membridge lint`：四项**确定性**结构检查（悬空边 / 孤立 / 陈旧 / 凭证泄露），零 LLM、零依赖、只报告；`--json` 供计划任务与 CI，`--fix-structure` 只删悬空边（结构，非记忆内容）。与 `doctor` 分工：doctor 管环境能不能跑，lint 管库本身好不好 | ✅ v0.28 |
| 确定性批量导入 | `membridge import-md`：把 Markdown/文本日志的条目行批量写进记忆库（零 LLM、逐条内容判重、隐私词照走 PAMS、`--dry-run` 先看后导），补上自动同步缺失的 Ingest 一环——同步只运「已在库里的」，从不采集 | ✅ v0.29 |
| 计划任务防静默跳过 | Windows 计划任务改用 XML 注册：关掉「电池供电跳过 / 切电池即停」两个默认条件，错过班次开机补跑（`StartWhenAvailable`）——笔记本上不再「该跑却没跑」 | ✅ v0.29 |
| 存储与检索优化 | embedding 以 float32 BLOB 存储（体积降为 JSON 的 1/3～1/5，旧库打开自动迁移），检索两阶段 + 进程内向量缓存 | ✅ v0.8 |
| 一键接入平台 | `membridge init` 自动检测并配置主流 AI 平台（MCP 自动写入 / WorkBuddy 技能自动安装 / 其余打印指南）；第一步云盘未检测到时走交互式引导接线（安心文案 + 逐步配坚果云主通道 + 连接达标门槛，留「稍后配置」出口；v0.25） | ✅ v0.2/v0.25 |
| 全自动同步 | 云盘自动选定（多盘按优先级）、口令由系统生成并托管（用户无感，v0.23 起托管覆盖 Windows / Linux / macOS 全平台）、按重要程度自动上云（全平台计划任务每 15 分钟，v0.24 起含文件夹级双向轮），零点击 | ✅ v0.5/v0.6/v0.23/v0.24 |
| 加密钥匙（默认自动，特殊场景可手动） | **默认且主流：自动派生**——通道密钥由源码种子确定性算出，**日常什么都不用传**，同通道各端自动同钥（AI 读文档即可接手）。**特定情况才手动**：`--passphrase 你的口令`，用于把记忆手动搬到移动硬盘/U 盘/离线归档、给未装记忆桥的机器解密、或为不同通道各设一把。优先级：`--passphrase` > 源码派生 > 环境变量 > 保险库。⚠️ 不要设 `MEMBRIDGE_PASSPHRASE` 环境变量：它是每台机器各自的历史、跨机互不可见，会被自动忽略并告警 | ✅ v0.31 |
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

| | 记忆桥 | OpenMemory (mem0) | MemGPT/Letta | memU |
|---|---|---|---|---|
| 跨应用共享（MCP） | ✅ | ✅ | — | ✅（宿主适配器） |
| **跨设备同步**（手机↔PC↔边缘） | ✅ 核心能力（端到端加密、网盘只见密文） | ❌ 单机 | ❌ | 依赖其云托管 |
| 切换前**预加载**（零等待） | ✅ | ❌ 被动检索 | ❌ | ❌ |
| **内容冻结**（不重写记忆） | ✅ 架构级约束 | ❌ LLM 摘要改写 | 部分 | ❌（LLM 自动蒸馏入库） |
| 记忆人类可审计 | ✅ v0.10 Markdown 导出视图 | ❌ | ❌ | ✅（Markdown 即记忆） |
| 隐私分级（迁移标签 + 场景域） | ✅ | 部分 | ❌ | ❌ |

> memU 值得尊敬：它的「技能自动提炼」（会话历史自动变成可复用技能）与
> 「服务端零 LLM」都很出色。分歧在记忆内容的来源——memU 让 LLM 蒸馏生成，
> 记忆桥坚持明面上的显式写入（`memory_add`），经验沉淀用
> `kind=procedure` 标注（见下方约定），幻觉没有进库通道。

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

第四个数据点来自开源竞品 **memU**（NevaMind-AI）：它同样坚持**记忆服务端
零 LLM**——「什么值得记」的判断交还给宿主 Agent，记忆服务只做存储、嵌入、
检索这件确定性的事。这与记忆桥核心的分工完全同构。路线分歧在两点：
memU 用 LLM 蒸馏**生成**记忆内容（记忆桥拒绝：内容冻结），跨设备走其
云托管（记忆桥坚持端到端加密的自持通道）。v0.10 借鉴了它「记忆就是文件」
的可审计性（`membridge export`，只读视图永不回写），见
[路线图「memU 借鉴版」一节](docs/roadmap.md)。

第五个数据点来自端侧：**边缘设备正在成为 AI 基础设施的一等公民**。
Ornith-1.5 的 9B 量化版（约 1.5GB）已能在手机上直接运行；OlliteRT 把
旧手机变成了 24 小时在线的局域网模型服务器。当手机同时装得下模型与
服务，记忆桥的基站模式恰好补上这块拼图缺的「记忆」——一部旧手机跑
OlliteRT（本地推理）+ `membridge gateway`（记忆底座），就是完全自持、
零云端的个人 AI 栈（配方见 [移动端指南](docs/mobile.md)）。边界仍然
清晰：本地模型在宿主侧，记忆层核心零 LLM。

第六个数据点来自参数派内部：**连高通也在实践「冻结本体 + 外挂记忆」**。
Qualcomm AI Research 的 MoNe（ICML 2026）给冻结的模型骨干外挂「在线可写
的神经记忆」，上下文写入一次、提问不再重读——其架构纪律与记忆桥同构：
本体冻结，只外挂可写。分歧只在记忆住在哪：MoNe 把历史写进权重（参数态），
而 Metis 已承认这条路线难审计、难精确删除、隐私边界难保证；记忆桥坚持
把记忆留在人人可审计的外部存储。**冻结是这个领域两派共同的纪律，区别
只在冻什么——他们冻模型，我们冻内容。**

## 平台覆盖（跨平台记忆共享）

用户只需运行 **`membridge init`**：自动检测本机已安装的平台并接入（幂等安全，重复执行无副作用）。

| 接入方式 | 覆盖的平台 | 状态 |
|---|---|---|
| **init 自动配置（MCP）** | ZCode、Claude Code、Claude 桌面版、Cursor、Cline、Windsurf、VS Code（Copilot MCP）、Gemini CLI、通义千问 Code | ✅ v0.2 |
| **init 技能自动安装（SKILL.md）** | WorkBuddy（`~/.workbuddy/skills`）、Claude 技能目录 | ✅ v0.2 |
| **远程 MCP（HTTP 模式）** | 扣子 Coze 等支持远程 MCP 的平台（`membridge mcp --http` 后经 URL 接入） | ✅ v0.2 |
| **init 手动指南** | 字节 Trae 等界面化 MCP 平台（init 打印逐步指引） | ✅ v0.2 |
| **CLI / SDK** | 任意能调用命令行的环境（剪贴板兜底：`membridge context "<主题>"`） | ✅ v0 |
| **手机 / 平板（网关基站模式）** | `membridge gateway`：iOS / Android / 平板的浏览器（内置随身记页面）与快捷指令等任意 HTTP 客户端；Android 也可 Termux 跑完整节点（[移动端指南](docs/mobile.md)） | ✅ v0.11 |
| **浏览器插件** | 豆包、Kimi、ChatGPT 网页版等封闭 Web 助手 | 📋 Phase 1+ |

> 对完全封闭、不支持任何外部接入的 App，兜底方案是"剪贴板/分享"通道
> （`membridge context` 复制粘贴），永远可用。

## 快速开始

```bash
git clone https://github.com/jiabaobei/memory-bridge.git
cd memory-bridge
pip install -e .        # 本地可编辑安装。⚠️ 切勿 pip install membridge（见下方警示）
membridge init               # 强制完成云盘通道配置（默认必做，检测已装同步盘自动配好；
                             # 没有则引导免费云盘；确要跳过需显式确认），
                             # 随后自动接入本机各 AI 平台
python examples/demo.py      # 90 秒看懂：手机记忆 → 差分包 → PC 无缝继续
```

> ⚠️ **`pip install membridge` 装到的不是本项目。** PyPI 上的 `membridge`
> 是另一个项目抢注的名字，与本仓库无关。memory-bridge **从未在 PyPI 发布**，
> 一律从 Git 源码装（即上面三行：clone → cd → `pip install -e .`）。
>
> 这和项目改名无关——仓库名、模块名、CLI 名都不需要动。

> 为什么第一件事是配云盘？**记忆不上云，跨设备无从谈起。** 早上手机上的讨论，
> 只有进了云盘通道，办公室的电脑才能接着继续。按论文测算你的记忆一年仅约 1GB，
> 任何免费云盘都够用；且同步的是端到端加密的差分包——云盘服务商也看不到内容。

## 跨设备同步：通道是什么、密码是什么、怎么上传取回

这一节写给**人和 AI  alike**：读完就能自己把记忆传到别的设备、或从别的设备取回，
**不需要向任何人索取密码**。所有算法与参数都逐字写在这里，任何语言的实现者
都能独立复现，不依赖本项目的代码。

### 一、通道 = 一个云盘文件夹

`membridge init` 会在你选的云盘里建一个 `membridge/` 目录，这就是**通道**：

```
<你的云盘>/membridge/
├── channel.json       ← 通道身份证（通道 ID / 创建者 / 时间）
├── devices/           ← 每台设备的心跳（在线状态、节点数、容器指纹）
├── outbox/            ← 待取走的加密差分包
└── archive/           ← 已取走的包归档
```

**没有服务器、没有账号、没有 API key。** 云盘只是各设备碰面的地方。

> v0.31 起通道目录里**不再存放 `channel.key`**。密钥由下面的种子确定性派生，
> 各端各自算、结果逐字节相同。见下一节。

### 二、密码（通道密钥）是什么：种子 + 标准 KDF，自己算

通道密钥不是随机生成后靠文件流转的，而是由**源码里的种子**确定性派生。
任何设备、任何时间、任何语言算出来的结果完全一样——这就是跨设备天然同钥的原因，
也是「装了项目就通、不用问人」的实现方式。

**种子**（在 `src/membridge/channel.py`，常量名 `CHANNEL_SEED`）：

```
membridge/mb-639d44f1/jiabaobei
```

**固定盐**（同文件常量 `SEED_SALT`）：

```
membridge.channel.v1
```

**迭代次数**（同文件常量 `KDF_ITERATIONS`）：

```
200000
```

**派生算法**（任何语言都能照此实现，只用标准原语）：

```
dk  = PBKDF2-HMAC-SHA256(
          password = utf8(种子),
          salt     = utf8(固定盐),
          iterations = 200000,
          dkLen    = 32 )
key = base64.urlsafe_b64encode(dk)     # 标准 base64，字母表 A–Z a–z 0–9 - _
key = key.rstrip("=")                  # 去掉尾部 = padding
```

得到的 `key` 是 **43 个字符**，它就是通道密钥，直接作为 Fernet 的口令使用。

**别用 `hashlib.sha256(种子)` 之类的捷径**——必须走 PBKDF2 且参数如上，
否则算出的密钥与他人不一致，表现为「发布端与接收端必须使用同一口令」。

**自检串**（验证你算对了，避免算错后静默发包）：

```
gAAAAABqwKqSJr8bLK6huRI9Dg5pLs-O8uMg5UYxU66NlZ1elIKgQ7qFCGF9WuZgUpheTigx4ekl-QABZT4qAr3UVtb_MBXZrbH90TheJo5JGyUg8M_0qco=
```

它是「用派生出的 key、固定盐 `00×16`、Fernet 加密明文
`membridge-channel-ok`」的结果。解出来等于这句明文，就说明派生正确。
（盐固定为 16 个 `00`，所以这段密文每次生成都一样，可以直接比对。）

Python 里的完整复现：

```python
import base64, hashlib
from cryptography.fernet import Fernet

SEED  = "membridge/mb-639d44f1/jiabaobei"
SALT  = "membridge.channel.v1"
dk = hashlib.pbkdf2_hmac("sha256", SEED.encode(), SALT.encode(), 200000, 32)
key = base64.urlsafe_b64encode(dk).decode().rstrip("=")
print(key)   # 这就是通道密钥
```

> **关于安全性，说清楚**：种子随源码公开，所以**任何拿到这份源码的人都能算出
> 通道密钥**。这是「任何人读完文档就能自己动手」与「密钥保密」之间的逻辑取舍，
> 不是实现缺陷——要让 AI 独立完成，派生输入就不能是秘密。这里选零配置，因为
> 密钥的职责是「让各设备用同一把钥匙、且云盘服务商只见密文」，不是「挡住能读
> 源码的人」。真正挡住未授权访问的是**云盘目录本身的访问权限**，那才是通道文件夹
> 的职责。（本项目开源、MIT 许可，这一点是明说的，不含糊。）

### 三、加解密规则（差分包）

| | |
|---|---|
| 加密谁 | 上面派生出的通道密钥（43 字符） |
| 算法 | Fernet（AES-128-CBC + HMAC-SHA256），口令再经 PBKDF2-HMAC-SHA256 200000 轮 |
| 每包盐 | 16 字节随机，**随包携带**（信封的 `salt` 字段） |
| 信封格式 | `{"fmt":"membridge-delta-enc-v1","salt":"<hex>","token":"<fernet>"}` |
| 云盘服务商 | 看到的是 `token` 里的密文，看不到内容 |

### 四、上传（发布）

```bash
membridge sync      # 取回他端记忆 + 发布本机新记忆（手动，随时可跑）
membridge publish   # 只发布
```

自动任务（`init` 时已注册，无需配置）：

| 平台 | 机制 | 频率 |
|---|---|---|
| Windows | 计划任务 `MemoryBridge AutoSync` | 每 15 分钟 |
| macOS / Linux | cron `membridge-autosync` | 每 15 分钟 |

**默认始终加密**，不传任何口令即可——内部用派生密钥。真要严格端到端或跨通道，
可显式 `--passphrase 你的口令`（此时该口令优先，仅当次生效）。

**重要记忆立即上云，普通记忆批量上**；`migration=local` 的记忆在代码路径上
永不上云（见 [隐私](#隐私)）。

### 五之二、特定情况：手动口令搬运到别的硬件

云盘同步之外，还有一种场景：把整份记忆**手动搬到移动硬盘、U 盘、离线归档**，
或者交给一台没装记忆桥的机器解密。**日常不需要这样**——同一通道内的设备走上面的自动派生即可；只有在**离开通道、搬到介质上**时才需要手动口令。用这对命令：

```bash
# 在原机器上：生成加密差异包（--out 可以是 U 盘 / 移动硬盘的路径）
membridge delta D:/备份库.db --out E:/记忆备份.mbd --passphrase "我的口令"

# 在目标机器上：用同一把口令解封并入
membridge apply E:/记忆备份.mbd --passphrase "我的口令"

# 想自己先看看内容（可选，会产生明文文件，慎用）
membridge delta D:/备份库.db --out 明文包.json --plaintext
```

- 不写 `--passphrase` 也会加密——此时用源码派生值，适合同一通道内搬运。
- 写了 `--passphrase` 就用你给的那把，另一台机器必须传**同一把**才能解开。
- 产出的 `.mbd` 就是普通 JSON 文本，你可以直接拷到任何介质上。
- **明文模式（`--plaintext`）必须显式指定**，且会在输出里标注「（明文）」提醒你。

### 五、取回（拉取）

```bash
membridge fetch     # 从通道取回他端发布的差分包
membridge sync      # 等价：先 fetch 再 publish，日常用这个
```

不传 `--dir` 时用 `init` 配置的通道目录。**同样不需要口令**——走派生。

### 六、新设备接入：三步，零配置

```bash
git clone https://github.com/jiabaobei/memory-bridge.git
cd memory-bridge && pip install -e .
membridge init          # 指向同一个云盘文件夹；接入本机各 AI 平台
membridge sync          # 立刻取回该设备此前的全部记忆
```

**没有任何一步需要索取密码，也没有任何一步需要传密钥文件。**
新设备只要指到同一个云盘文件夹，密钥由源码自行算出，与其他设备逐字节相同。

### 七、出问题时先跑这两条

```bash
membridge doctor         # 一屏体检：库、通道、平台接入
membridge netdisk-status # 云盘是否在客户端同步范围内
membridge channel        # 通道身份 + 密钥指纹 + 各端心跳名册
```

常见提示的含义：

| 提示 | 含义与处理 |
|---|---|
| `本机保险库/环境变量与通道密钥不一致` | 那台机器留着历史口令。**派生密钥已自动接管，功能不受影响**；清掉那条历史口令可消除提示。 |
| `通道目录里存着旧密钥…要改用派生值需轮换` | 升级自 v0.30 之前的通道。程序**故意继续用旧密钥**（否则历史包集体解不开），需要时才手动轮换。 |
| `发布端与接收端必须使用同一口令` | 发送端还在用旧版 v0.30.3 之前的口令。让那台设备升级后重发即可。 |
| `口令不匹配，无法解密` | 同上，接收端视角的同一问题。 |

### 八、给 AI 的一页速查

如果你是在替用户操作本项目，按这四步做，不需要询问密码：

1. **确认通道目录**：`membridge channel` 第一行就是。多设备要指向**同一个**目录。
2. **取回他端记忆**：`membridge fetch`（等价 `membridge sync`）。不传 `--passphrase`。
3. **发布本机记忆**：`membridge publish`。不传 `--passphrase`。
4. **核对是否同一把钥匙**：`membridge channel` 里的「通道密钥: 指纹 xxxx」，
   各端应一致。

自行加解密时：按第二节派生 43 字符密钥，用它作 Fernet 口令；
每包随机 16 字节盐并以 hex 写进信封的 `salt`；解密前先用自检串确认派生无误。

**永远不要**把通道密钥或任何口令打印进聊天、提交进仓库、贴进 issue——
它对能读源码的人本就不是秘密，但泄露仍会让未授权者读到你的记忆内容。

### CLI

```bash
membridge init                                           # 一键接入本机检测到的 AI 平台
membridge add "用户在开发记忆桥项目" --tags dev          # 写入记忆（可选 --kind fact / procedure / handover）
membridge search "记忆桥" -k 3                          # 三路混合检索（向量 + 关键词 + 图谱，RRF 融合；--scope tag:dev 范围直达、at:7d 时间窗、at:2026-09-01..2026-09-20 区间）
membridge context "继续早上的讨论"                       # 输出 Path A 上下文块（最新交接卡恒定注入在【工作台】小节；无命中时明确"本轮不注入"）
membridge handoff                                       # 查看当前工作台：最新交接卡原文与生效状态
membridge handoff-hint                                  # 打印常驻交接提示（自愿粘贴进 CLAUDE.md / AGENTS.md）
membridge preload 我的手机                               # 预加载候选（PAMS 门控）
membridge delta phone.db --out delta.json               # 生成到另一设备的差分包
membridge apply delta.json                              # 并入差分包
membridge publish --dir "D:\百度网盘同步盘\membridge"                   # 发到网盘通道（零口令，自动派生）
membridge fetch   --dir "D:\百度网盘同步盘\membridge"                   # 从网盘取回（零口令，自动派生）
membridge stats                                         # 记忆库概况
membridge channel                                       # 通道一致性体检：本机与其他设备是否指向同一云盘通道
membridge gateway                                       # 手机/平板接入网关（基站模式，口令保护；--allow 加 IP 白名单）
membridge gateway-token                                 # 显示网关访问口令（配置手机时用）
membridge export                                        # 导出人类可读的 Markdown 视图（--out 落盘）
membridge recall-hint                                   # 打印常驻召回提示（自愿粘贴进 CLAUDE.md / AGENTS.md）
membridge rebuild-edges                                 # 全量重建语义关联边（常规 add 只增量建边）
membridge doctor                                        # 环境自检（库位置健康 + 通道健康 + 记忆缺口提醒）
membridge autosync                                      # 自动同步（init 已注册计划任务，每 15 分钟自动运行）
membridge show-passphrase                               # 查看本机口令（v0.31 后通常无需关心：默认走源码派生）
membridge set-passphrase                                # 设置本机常驻口令（可选；也可每次 --passphrase 现传）
```

**默认什么都不用传**——通道密钥由源码种子自动算出，各端零输入。

只有在**离开通道、把手动的记忆搬到介质上**这类情况下才自己设口令：

| | 什么时候用 | 怎么写 |
|---|---|---|
| **自动（默认，主流）** | 同一通道内的多台设备互传 | 什么都不用传 |
| **手动口令（特定情况）** | 搬到移动硬盘/U 盘/离线归档；给未装记忆桥的机器解密；不同通道各设一把 | 收发都传 `--passphrase 你的口令` |

两者产出的是同一种密文信封（`membridge-delta-enc-v1`），所以同一把口令在
`publish/fetch` 和 `delta/apply` 两边都能用。

> ⚠️ **不要设 `MEMBRIDGE_PASSPHRASE` 环境变量。** 它是每台机器各自的历史，跨设备互不可见；
> 一旦盖住派生值，同一条通道就会发出两种钥匙的包，他端表现为「时好时坏」。
> 真机事故已发生两次（2026-09-28 保险库口令、2026-10-03 环境变量）。

#### 经验沉淀约定（配合 `kind` 标注）

解决完一个难题、调通一个坑，值得存一条**经验**记忆，未来遇到同类任务
直接命中：

```bash
membridge add "部署到 arm64 会段错误，换 x86 镜像后通过" --kind procedure --tags dev
```

`--kind procedure` = 「试过什么、结果怎样」；`--kind fact` = 稳定事实。
纯可选标注，不改变任何默认行为。

#### 交接班约定（`kind=handover`，v0.15）

Agent 的上下文有限，长任务靠反复压缩续命，而压缩是有损的——
「方案B被否决」或许留下了，「为什么被否决」往往先丢。记忆桥的答案：
**收工方显式写一张交接卡，完整历史仍由记忆库承载**。

```bash
membridge add "goal: 修好同步模块
done: 差分计算已落地
failed: 全量AST解析；依赖太重；除非放弃零依赖否则别重试
next: 收敛行前缀解析
refs: membridge/store.py" --kind handover
```

- 五行约定 `goal / done / failed / next / refs`，正文原文冻结不改写；
  `failed` 行用硬句式：**试过什么；因为什么失败；除非什么改变否则别重试**；
- 新卡自动取代旧卡——最新一张即生效的工作台，旧的自动降级为历史，
  可检索、可审计，永不删除；
- 注入时工作台恒定在场（不受沉默契约约束——它是状态声明，不是检索命中），
  检索命中的其他记忆照常走原契约；
- 超 7 天未更新的卡不再恒定注入（过期工作台比没有更危险），降级为
  普通记忆；`membridge doctor` 会提醒；
- `membridge handoff-hint` 打印常驻提示，粘贴进 CLAUDE.md / AGENTS.md，
  让宿主 Agent 养成"收工前交接、接班先看工作台"的习惯（软约束，
  与 recall-hint 同款哲学）。

> 手机侧不需要记命令：网关随身记页面内置交接卡表单，填五行点「交接班」即可。

#### 云盘差分包丢失时的补救

`publish` 只发送「本地记录中尚未发布过」的记忆。若云盘侧差分包被误删、
或同步故障清空了通道，本地仍认为已发布——此时：

```bash
membridge publish --dir "..." --force    # 忽略本地记录，重发全量重建通道
```

不加 `--force` 会输出「没有需要发布的新记忆。」，这是幂等表现，不是故障。

#### 网盘三端直达：双网盘把网页端容器拉进三端闭环（v0.18 引入，v0.20 主备分明）

各端共享的前提是「每台设备都能到达同一个网盘文件夹」。电脑有网盘客户端、
手机平板有 App，唯独网页端容器这类无头 Linux 环境没有任何网盘客户端——
`netdisk-*` 命令组补的就是这一环（经 rclone）。**两家都配，主备分明**：
坚果云作主通道（WebDAV 全端可达），OneDrive 作备胎（坚果云出问题时顶上，
不是淘汰）——始终保持一条主通道：

```bash
# 网页端容器接坚果云（主通道；无浏览器往返：账号 + 应用密码直接交入）：
#   应用密码在坚果云网页「账户信息 → 安全选项 → 第三方应用管理」生成
membridge netdisk-connect --provider jianguoyun --dir /path/to/channel \
    --webdav-user <账号> --webdav-pass <应用密码>

# 网页端容器接 OneDrive（备胎；三步：装同步工具 → 授权 → 首次拉取）：
membridge netdisk-connect --dir /path/to/channel
#   ② 会提示去有浏览器的电脑跑：rclone authorize "onedrive"
#      把得到的 {"access_token":...} 交给本端：
membridge netdisk-connect --dir /path/to/channel --paste-token '{"access_token":...}'

# 日常同步（主通道先跑、备胎殿后，再跑包级同步）：
membridge netdisk-sync --dir /path/to/channel
membridge sync --netdisk --dir /path/to/channel   # 同效

# 电脑（已装网盘客户端，零配置捷径）：
membridge netdisk-connect --dir "D:\sync\membridge"  # 探测到本机云盘目录直接指向

# 迁通道宿主（v0.20）：复制通道文件 + 改本机指向，差分包去重天然安全
membridge channel --move /path/to/new/channel

membridge netdisk-status                          # 体检：两家授权与主备角色分开报
membridge netdisk-disconnect [--provider onedrive|jianguoyun]  # 按家或全撤（幂等）
```

纪律：OAuth token / 应用密码只落盘（rclone 配置文件，权限 600，坚果云密码
先混淆再落盘），永不打印、永不写进记忆或日志；基线标记与 `devices/` 心跳
目录排除出双向同步；同一通道目录可同时接两家（状态按家登记、主备分明，
v0.18 旧接线自动兼容）；老通道与既有命令行为不变。

#### 多台设备如何一致指向同一个通道（v0.13）

核心思路：**通道的「身份」记在通道自己身上，而不是记在每台设备上**——
认领代替记路径。你唯一要做的，是让各台设备的通道文件夹落在**同一个会被
云盘同步的位置**（例如都用 `D:\OneDrive\membridge`，或都用坚果云的
`我的坚果云\membridge`）。之后：

- **首个设备**发布记忆时，会在通道目录写一份**通道身份证** `channel.json`
  （通道 ID / 创建设备 / 创建时间 / 嵌入器指纹）——**纯元数据，不含口令、
  不含任何记忆内容**；
- **之后的每台设备**运行 `membridge init`（或第一次 `publish`/`fetch`/
  `autosync`）时，检测到目录里已有身份证就**自动认领**同一通道，并输出
  「已加入既有通道（由某设备创建）」——不需要你手动记路径、不需要复制配置；
- 若某台设备被误配到**另一个**通道（本机记录的通道 ID 与身份证对不上），
  `membridge channel` / `doctor` / `publish` / `fetch` / 自动同步都会**显式
  告警**（先到先得不改写，避免两台设备互相覆盖身份证）；
- 随时用 `membridge channel` 一屏体检：本机通道、通道身份证、通道里出现过
  的其他设备。

> 手机 / 平板不需要通道——它们经 `membridge gateway` 基站模式直连家里那台
> 常开设备（见 [移动端指南](docs/mobile.md)），天然只指向那一个库。

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

可用工具：`memory_add`（Add，可选 `kind` 标注：fact / procedure / handover）、
`memory_search`（Search，三路混合检索；已知记忆在哪可用 `scope` 范围直达，
如 `tag:dev`、`at:7d` 时间窗、`at:2026-09-01..2026-09-20` 区间；`as_context=true` 直接返回带预算的 Path A 注入块——最新交接卡
恒定注入在【工作台】小节，无高质量命中时明确告知本轮不注入）、
`memory_preload`（Preload）——严格限定在 UEP 权限边界内，没有"改写记忆"的工具。

## 架构一览

```
              ┌────────────────────────────────────────────────┐
              │           跨平台接入层（连接器）                  │
              │  MCP Server │ CLI │ 平台技能（WorkBuddy 等）     │
              │   手机/平板（网关 ✅）│ 浏览器插件（计划中）        │
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
- **Phase 2** 跨设备传输通道：网盘三端直达已完成（v0.18–v0.20，双网盘主备分明，详见路线图）；待办：E2E 加密中继（自托管）、版本向量、冲突解决
- **Phase 3** TMT 边缘驻留（hot/cold 两级）、预加载时机、移动端原生壳（网关已先行，v0.11）、L2 授权流
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
git clone https://github.com/jiabaobei/memory-bridge.git   # 从源码装，勿 pip install membridge
cd memory-bridge
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
- [memU](https://github.com/NevaMind-AI/memU)：v0.10 借鉴其「记忆就是文件」
  的可审计性与常驻召回指令思路（分别落为 `export` 只读视图与
  `recall-hint`）；其「服务端零 LLM」架构与记忆桥同构。自动蒸馏管线与
  云托管不在借鉴之列，理由见 [路线图「memU 借鉴版」一节](docs/roadmap.md)。
- [OlliteRT](https://github.com/NightMean/OlliteRT)（旧手机变局域网模型
  服务器）：v0.12 借鉴其运行时状态页与「监听范围 + IP 白名单 + Bearer
  口令」的安全默认项；「旧手机 24 小时基站」与两者组合的端侧全栈配方
  见 [移动端指南](docs/mobile.md)。Ornith-1.5 9B 上手机的进展则印证了
  端侧趋势（见「领域收敛」）。
- [Context7](https://github.com/upstash/context7)（最新文档直接注入
  prompt）：其三大机制（生成时注入 / 预算控制 / 常驻提醒）与记忆桥
  v0.9/v0.10 同构，是路线的外部背书；v0.13.1 仅借鉴其「已知目标直达」
  洞察（检索 `scope` 范围直达）。云端托管索引、爬取入库、多包生态不在
  借鉴之列，理由见 [路线图「Context7 借鉴版」一节](docs/roadmap.md)。
- [GitNexus](https://github.com/abhigyanpatwari/GitNexus)（零服务器代码
  知识图谱引擎）：v0.14 借鉴其「图谱的价值在关系确定」这一核心思路，
  降级落地为**确定性实体锚点**（零依赖正则抽取，不解析 AST）与类型化边；
  其 `[[file:line]]` 溯源思路落为召回理由标注，社区检测落为整簇预加载。
  图数据库、Tree-sitter 全量 AST、PDG 污点分析、提交后重索引一律不借
  （与三原则相悖），理由见 [路线图「GitNexus 借鉴版」一节](docs/roadmap.md)。
- [Hindsight](https://github.com/vectorize-io/hindsight)（42k★，声称让
  agent「学习」而不只是记忆）：**只取结构层**——v0.30 借鉴其 recall 的第
  4 路 temporal（落为 `scope` 的 `at:` 时间窗）与 proof count（落为只读
  「证据计数」+ 同分次级键）。其价值主干全在 LLM 管线（retain 抽事实/实体、
  consolidation 生成 observations、reflect 推理、mental models 后台重写），
  条条撞「内容冻结」与「服务端零 LLM」，**一律不借**；论文自引的
  Faulty Memory（ACL 2026）恰是「抽象不可靠」的证据。逐条对照见
  [设计笔记](docs/design-notes/hindsight-borrowings.md) 与
  [路线图「Hindsight 对标」一节](docs/roadmap.md)。

## License

[MIT](LICENSE)
