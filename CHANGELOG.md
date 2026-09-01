# Changelog

所有显著变更记录于此。格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)。

## [0.15.0] - 2026-09-01

交接班版（交接卡 + 工作台）：记忆从此管得住「干到哪了」。长任务靠反复
压缩上下文续命，而压缩是有损的——「方案B被否决」或许留下了，「为什么被
否决」往往先丢，下一个窗口于是重蹈覆辙。记忆桥的答案：收工方显式写一张
交接卡，最新一张成为恒定注入的工作台，完整历史仍由记忆库承载、随时可查。
可靠的记忆不是永远不忘，而是忘了也知道去哪找回来。

### 新增

- **交接卡**：第三种记忆类型 `kind=handover`（CLI / MCP / 网关随身记
  三个入口均可写）；`goal:/done:/failed:/next:/refs:` 行前缀约定，
  `failed` 行用硬句式「试过什么；因为什么；除非什么否则别重试」——
  否决和否决的理由必须一起留下。正文原文冻结，不合规格式照常呈现
- **工作台槽位**：全库最新未过期交接卡恒定注入——它是状态声明，不是
  检索命中，因此不走相关性、不受沉默契约约束；独立预算（注入总额 1/3，
  保底 120 字符），超预算按原文前缀截断（截断 ≠ 改写）；`context` /
  MCP `as_context=true` / 网关 `/search?as_context` 统一生效
- **取代即推导**：最新一张（created_at 定序）即生效，旧卡自动降级为
  历史——零新增状态位、零 schema 变更，跨设备同步后各端自动收敛到
  同一张卡，天然无冲突；交接卡随差分包正常同步、随 export 正常审计
- **新鲜度门槛**：超 7 天未更新的卡不再恒定注入（过期工作台比没有
  更危险），降级为普通记忆；`doctor` 显式提醒
- **`handoff` / `handoff-hint` 命令**：查看当前工作台原文与生效状态；
  打印可粘贴进 CLAUDE.md / AGENTS.md 的常驻交接提示（自愿启用，
  与 recall-hint 同款哲学）
- **随身记交接表单**：网关页面内置五行交接卡表单 + 「看工作台」入口，
  新增只读槽位 `POST /workbench`
- **整簇预加载带上交接物**：活跃交接卡若不在热簇内，顶到首位一起
  预加载——到新设备，交接单先于记忆到位

### 调整

- **交接卡边权重衰减**：交接卡正文含大量历史指涉，触点边权重乘
  0.85 结构衰减，防止其连成超级枢纽抬排名——工作台已恒定注入，
  交接卡不需要靠边权重获得存在感（只调结构参数，不碰内容）
- `--kind` / MCP `kind` / 网关 `kind` 接受 `handover`；`scope` 支持
  `kind:handover` 范围直达；export 新增「当前工作台」置顶小节与
  「交接卡（handover）」分节

### 原则守护（本次未越线）

- **内容冻结**：全部改动只加结构/槽位/只读解析，绝不改写任何记忆
  内容；取代是推导出来的，旧卡原文一字不删、一字不改
- **极度省 token**：不新增 MCP 工具（仍是 3 个，工作台复用 search 的
  `as_context`）；行前缀解析零依赖正则；新鲜度门槛是结构参数，
  不进用户可调面
- **零新依赖**：交接卡就是普通节点，同步 / 检索 / 加密 / 审计全部
  复用现成设施；唯一新模块 `handoff.py` 纯标准库

## [0.14.0] - 2026-08-31

GitNexus 借鉴版（图谱结构强化）：对照 GitNexus（abhigyanpatwari/GitNexus，
零服务器代码知识图谱引擎）做的克制借鉴——吸收其「确定性关系源」思路为
实体锚点；其图数据库（KuzuDB/LadybugDB）、Tree-sitter 全量 AST、PDG/
污点分析、提交后重索引等重件一律不借（与三原则相悖）。事前核对发现：
记忆桥 v0.9 已实现三路混合检索 + RRF + SAN 一跳扩展（GraphRAG Local
Search 极简版），差距不在「有没有图谱」而在「边从哪来、可不可信」。

### 新增

- **类型化边 + 证据**：`edges` 表新增 `kind`（semantic / cooccur / entity）
  与 `evidence` 两列，每条边可回答「为什么相关」；存量库打开自动迁移，
  旧边统一标记 semantic（只加结构，不改权重）
- **确定性实体锚点**：`san.extract_entities` 零依赖正则抽取代码符号 /
  文件路径 / owner-repo / 全大写代号 + 用户标签；`build_entity_edges`
  让共享同一锚点的记忆连 entity 边（每节点至多 5 条，保持图稀疏）
- **整簇预加载**：`preload --cluster` 用并查集连通分量把记忆切簇，
  按「当前最热节点所在簇」整簇返回——对应预加载主张的「切换即连续」
- **召回理由标注**：`retrieval.search_with_reasons` 返回命中路径
  （向量 / 关键词 / 图谱），`context` 注入时追加极短标注，一眼判断
  该不该信；`hybrid_search` 变为兼容薄封装，既有调用零改动

### 原则守护（本次未越线）

- **极度省 token**：召回理由每行 ≤8 字符；evidence 不进检索上下文，
  仅按需读取；建边类型收敛为 3 种，不为 temporal/device/scene 建边
  （避免边数爆炸，device/scene 仍走节点元数据 + scope 过滤）
- **极度简洁**：零新依赖、零新文件（实体抽取并入 san.py、聚类并入
  heat.py）；唯一新 CLI 开关是 `preload --cluster`
- **内容冻结**：全部改动只加结构/元数据，绝不改写任何记忆内容；
  不引入图数据库、不解析 AST、不做提交后重索引

## [0.13.2] - 2026-08-31

MoNe 背书版（纯文档，代码零改动）：对照高通 MoNe（Modular Neural Memory，
ICML 2026，「外挂式在线可写神经记忆」）做路线核对。其四条机制与记忆桥
全部同构且已具备（骨干冻结 ≈ 内容冻结；写入一次多查询重读 ≈ 外置记忆
本职；增量续写 ≈ v0.8 增量建边 + DSS 差分；固定记忆预算 ≈ v0.9 预算
注入）；参数态记忆路线本身明确不借（权重态难审计、难精确删除、隐私
边界难保证，且需离线训练，与三原则全部相悖）。

### 文档

- 中英 README「领域收敛」补**第六数据点**：连参数派都在实践「冻结本体
  + 外挂记忆」——冻结是两派共同的纪律，区别只在冻什么：他们冻模型，
  我们冻内容
- 路线图记「MoNe 背书版」与逐项核对结论

## [0.13.1] - 2026-08-31

Context7 借鉴小修订：对照 Context7（upstash，6.1 万星，「最新文档直接注入
prompt」）做的取舍式借鉴。结论：其三大机制（生成时注入 / 预算控制 / 常驻
提醒）记忆桥 v0.9/v0.10 已具备——验证意义大于借鉴意义；云端托管索引、
爬取外部内容入库、多包生态均明确不借。唯一落地的借鉴是它两段式检索里的
「已知目标直达」洞察。

### 新增

- **检索范围直达 `scope`**（借鉴 Context7 斜杠语法 `use library /xx/yy`）：
  调用方已知记忆在哪时先过滤再融合，跳过无关候选——更准、更省。
  CLI：`search/context --scope tag:dev / scene:work / kind:procedure`；
  MCP：`memory_search(scope=...)`，工具描述保持一行。纯可选：不传行为
  与之前完全一致；未知字段静默不过滤
- **范围内无命中不记缺口**：指定了范围而没查到是预期（该范围内没有），
  不是记忆缺失——避免缺口提醒的噪声

### 三原则核对

- 内容冻结：scope 是纯只读过滤（读 tag/scene/kind 元数据），不触碰记忆内容
- 极度省 token：候选更准 → 注入更少；工具描述不膨胀
- 极度简洁：无新命令、无新依赖、无必填参数

测试：80 → 83 项（新增 3 项 scope 用例）

## [0.13.0] - 2026-08-31

通道归一版：让多台设备**一致指向同一个云盘通道**。此前 `netdisk_dir` 只是
每台设备的本地路径——两台设备装的同步盘不同时，自动选择规则会各自选到
不同的云，记忆圈静默分裂且无任何警告。本版给通道一个「身份证」，认领
代替记路径。三原则核对：不改写任何记忆内容（身份证是纯元数据）；零新依赖；
无新必填参数。

### 新增

- **通道身份证 `channel.json`**：首个发布/初始化的设备在通道目录落一份
  自描述清单（通道 ID / 创建者 / 时间 / 嵌入器指纹）；后续设备**自动认领**
  同一通道（adopt），不一致时显式告警、先到先得、清单不改写。**纯元数据，
  不含口令、不含任何记忆内容**——内容冻结不受影响
- **`membridge channel` 通道一致性体检**：本机通道 / 通道身份证 / 通道里
  出现过的其他设备一屏看清；分裂（本机 ID ≠ 云盘身份证）显式 ⚠️
- **init 自动认领**：新设备 `membridge init` 检测到通道文件夹已有身份证
  时，输出「已加入既有通道（由某设备创建）」，不再靠用户手动记路径
- **OneDrive 多根目录识别**：家目录下所有 `OneDrive*` 根（`OneDrive - 个人`
  / `OneDrive - 公司` 等）都能被认出——同一云盘在不同设备上根目录名常常
  不同，此前只匹配 `~/OneDrive` 会漏检
- **doctor / 自动同步通道健康**：通道目录不存在（云盘未登录/未开同步）、
  本机通道 ID 与身份证不符（疑似分裂）——都会显式告警

### 文档

- README / README_EN 能力表、CLI 清单、差异表更新；RFC §7 补通道身份说明
- 路线图记「通道归一版」与 Phase 2 通道身份衔接

## [0.12.0] - 2026-08-31

端侧借鉴版：对照两份端侧研究（Ornith-1.5：9B 量化模型直接跑上手机；
OlliteRT：旧手机变 24 小时局域网模型服务器）做的借鉴。核心判断：边缘
设备正在成为 AI 基础设施的一等公民，基站模式踩在这条线上；记忆层核心
仍然零 LLM。

### 新增

- **网关运行时状态**（借鉴 OlliteRT 的实时状态页）：`/health` 返回运行
  时长 / 请求数 / 写入数 / 检索数 / 命中数；内置随身记页面底部常驻一行
  基站状态。常驻服务排障刚需，纯标准库
- **`membridge gateway --allow` IP 白名单**（借鉴 OlliteRT 的安全默认
  项）：逗号分隔的 IP / 前缀（如 `192.168.1.,100.64.`），不匹配的来源
  一律 403；口令是第一道门，白名单是第二道
- **docs/mobile.md「旧手机 24 小时基站」配方**：Termux + gateway +
  `--allow` 家庭网段 + 常开充电与散热的诚实提醒——整机 5–10 瓦，自带
  电池即 UPS，比 24 小时开 PC 现实得多
- **docs/mobile.md「membridge × OlliteRT 端侧个人 AI 全栈」配方**：
  一部旧手机 = 本地模型（OlliteRT）+ 记忆底座（membridge），完全自持
  零云端；模型归模型、记忆归记忆，记忆核心链路不引入任何 LLM 调用

### 文档

- README / README_EN「领域收敛」补第五数据点（边缘设备成为 AI 基础
  设施一等公民）；能力表 / 状态表更新；致谢补 OlliteRT
- 路线图：版本总览 + 「端侧借鉴版」章节（含明确不借清单）；Phase 3
  补端侧趋势观察与"记忆层核心永不引入 LLM"承诺

测试：新增网关状态与白名单用例 2 项；70 → 72 项

## [0.11.0] - 2026-08-31

移动端接入版：手机与平板加入跨设备记忆圈。PC ↔ 笔记本继续走网盘差分包；
移动端无法复用（网盘 App 没有本地同步文件夹、iOS 跑不了 Python），改走
两条新路线——**路线 A 基站模式落地为代码，路线 B（Android Termux 完整
节点）落地为文档**。核心依旧零依赖：网关只用 Python 标准库。

### 新增

- **`membridge gateway`**：手机/平板接入网关（路线 A「瘦客户端 + 基站」）。
  家里一台常开设备跑网关，手机经 HTTP 读写该设备上的记忆库——日常只需
  Add / Search / Preload 三个动作，无需持有完整记忆库。内置「随身记」
  网页（浏览器打开即用，可加主屏幕）；接口 `/add` `/search` `/preload`
  `/health`，iOS 快捷指令 / 任意 HTTP 客户端可直连
- **访问口令强制**：命令行 > 环境变量 `MEMBRIDGE_TOKEN` > 库内自动托管
  （`membridge gateway-token` 查看，同 show-passphrase 的托管哲学）；
  恒定时间比较，错口令一律 401
- **隐私边界显式化**：明文 HTTP 仅限局域网 / Tailscale 自持组网；跨网
  可达用 `--cert/--key` 启用 TLS；启动输出与文档反复声明"绝不开公网
  明文端口"
- **`docs/mobile.md`**：移动端完整指南——路线 A 三种接法（内置页面 /
  iOS 快捷指令逐步教程 / 任意客户端）+ 接口表；路线 B Termux 完整节点
  （pkg/pip 安装、rclone 挂网盘做通道、crond 定时、已知限制）

### 工程

- `MemoryStore` 连接放开 `check_same_thread`（网关子线程处理请求需要；
  并发安全由既有的 WAL + busy_timeout + 事务收敛保证）
- 复用既有基建：检索走 `hybrid_search`、注入走 `serialize`（沉默契约
  在网关侧同样生效）、写入走与 `memory_add` 完全一致的管线（场景分类 /
  迁移判定 / 增量建边）——内容冻结无任何例外

测试：新增 `tests/test_gateway.py` 6 项（真实起服务真请求：鉴权拒绝、
读写往返、沉默契约、内置页面、错误消息、口令托管）；64 → 70 项

## [0.10.0] - 2026-08-31

memU 借鉴版：对照开源竞品 memU（NevaMind-AI，「记忆存成 Wiki」）做的取舍
式借鉴——借可审计性，不借其「LLM 自动蒸馏入库」管线（该管线让 LLM 生成
记忆内容，与内容冻结原则相悖；写入主动权保留在明面上的 `memory_add`）。

### 新增

- **`membridge export`**：把整座记忆库渲染成人类可读的 Markdown（按场景域
  分组、组内按 fact/procedure 分节、逐条带设备/时间/迁移出处）。**只读
  视图，永不回写**——手工编辑导出文件不会、也无法流回记忆库，内容冻结
  承诺多了一个人人可验证的出口。默认打印，`--out` 落盘（拒绝覆盖，
  `--force` 显式允许）
- **`membridge recall-hint`**：打印一行常驻召回提示，用户自愿粘贴进宿主
  指令文件（CLAUDE.md / AGENTS.md / Cursor 规则）——把「被动等 Agent 想起
  调工具」变成「每个任务前主动召回」。本工具只打印、不代写宿主文件
  （借鉴 memU 的 inject 缝，但改为完全用户主导）

### 文档

- README / README_EN 对比表补 memU 列（诚实标注其强项：技能自动提炼、
  Markdown 透明记忆；我们的强项：跨设备 E2E 同步、预加载、内容冻结、
  隐私分级）；「领域收敛」章节补 memU 为第四个独立数据点（服务端零 LLM
  的共识）
- 经验沉淀约定：README 明确「解决完难题用 `kind=procedure` 存一条」——
  v0.9 的 kind 标注正是 memU 技能线的手工版落点
- 路线图 Phase 4 UEP 补验证任务：SAN 图路召回增益（memU 的 ADR 明确
  弃图，作为反方观点必须在评测中用数据回答）

测试：新增 `tests/test_export.py` 5 项（含导出逐字渲染的内容冻结守卫、
覆盖保护）；59 → 64 项

## [0.9.0] - 2026-08-31

借鉴版：对照三份外部研究（Knowledge OS 混合检索、Meta Proactive Memory
Agent 选择性干预、Perplexity Portable Computer 上下文纪律 + airllm 按需
加载）做的集中借鉴。全部改动只落在检索 / 注入 / 调度层——**不改写任何记忆
内容**（内容冻结原则完整保持），核心依旧零依赖，差分线上格式不变
（v0.8 与 v0.9 设备可互相同步）。

### 检索质量

- **三路混合检索 + RRF 融合**（新模块 `retrieval.py`）：向量（余弦 +
  相对阈值）+ 关键词（n-gram 重叠，字面命中兜底）+ 图谱（SAN 一跳邻居）
  三路召回，按排名做 RRF（k=60）融合——多路共识天然加分，无需归一化、
  无新参数。CLI `search` / `context` 与 MCP `memory_search` 全部切换。
  借鉴来源：Knowledge OS（Wiki-RAG + GraphRAG）的混合检索实践
- **缺口发现**：零命中查询记入本地（纯元数据，至多 20 条），`doctor`
  显示缺口并提示补写——系统只提醒，内容永远由用户写（内容冻结下的
  安全自进化）。CLI / MCP 检索无命中时自动记录、去重

### token 经济（极度省 token 原则的进一步落地）

- **预算注入 + 超额截断**：Path A 注入块受预算约束（`serialize` 的
  max_chars / MCP `memory_search` 新增 `budget` 参数），预算内全文注入，
  第一个超预算条目注入**原文前缀**并标注截断——截断是取原文连续片段，
  不改写任何字。对应 Metis「查询时只读约 56 token 而不重放 1410 token
  历史」与 airllm「只载入当前这一步需要的层」
- **沉默契约**：没有可注入的高置信记忆时，返回显式「本轮不干预」标注
  而不是硬凑弱命中——沉默也是动作（借鉴 Meta Proactive Memory Agent）
- **MCP 工具描述瘦身**：三个工具的描述各压缩到一行——工具描述常驻每个
  客户端会话，是 v0.8「工具面 4→3」之后的第二步（借鉴 Perplexity
  Portable Computer 的上下文纪律）

### 记忆标注

- **可选 `kind` 标注**：`add` / `memory_add` 支持 `kind=fact`（稳定事实）/
  `procedure`（试过什么、结果怎样），纯可选不强制——借鉴 Proactive
  Memory Agent 的记忆三分法（v0 取其二，私有进度类不进库）。旧库打开
  自动平滑加列；差分序列化向后兼容（旧端 from_dict 自动忽略新字段）

### 文档

- README / README_EN 新增「领域收敛」章节：引用 Metis（arXiv 2607.26760）、
  Proactive Memory Agent（arXiv 2607.08716）与 Perplexity Portable
  Computer——外置记忆 + 内容冻结路线获得前沿研究的三重背书
- RFC-001 §10 同步 v0.9 工具面与检索契约；路线图补「借鉴清单」（含明确
  不借的：摘要改写、五层企业架构等违背原则的部分）

测试：新增 `tests/test_retrieval.py` 8 项（混合检索、沉默契约、截断的
内容冻结守卫、旧库迁移、跨版本兼容）；51 → 59 项

## [0.8.2] - 2026-08-31

文档：论文预印本 Zenodo DOI 上架。

- README / README_EN 的「与论文」章节加入 DOI 链接，bibtex 补 `doi` 字段
  （10.5281/zenodo.22064641，v7 预印本，含完整 LaTeX 源文件包），中英对齐
- 路线图版本总览补 v0.8.2 行

## [0.8.1] - 2026-08-30

实战修复：用户确定正式库在 D 盘后，跨盘符差分导出被阻断。

- 修复 `_safe_delta_file`：allowed_bases 跨盘符时（C 盘默认库 + D 盘正式库），
  `commonpath` 的 ValueError 会从 `any()` 中逃逸并否决全部基座——合法的
  D 盘写入被误判为路径穿越。改为逐基座独立判断
- 新增跨盘符回归测试；测试 50 → 51 项

## [0.8.0] - 2026-08-30

工程修订版：对照外部评审与作者两大产品原则（**极度省 token、极度简化易上手**）
的集中修订。全部改动保持核心零依赖、内容冻结原则与差分线上格式不变
（v0.7 与 v0.8 设备仍可互相同步）。

### 性能（规模化）

- **增量建边**：`memory_add` 不再每次全量 O(n²) 重算并重写全部关联边，只计算
  新节点与既有节点的关联（O(n)）；已有且权重未变的边不重写（写放大归零）。
  全量重建收敛到新命令 `membridge rebuild-edges`（调整 λ/阈值后或异常时使用）
- **embedding 存储 BLOB 化**：float32 定点存储替代 JSON 文本（256 维约 2.5KB→1KB，
  1536 维约 30KB→6KB）；打开旧库时一次性自动迁移（`embedding_format` meta 幂等）；
  差分线上格式保持 JSON 列表，跨版本握手不受影响
- **检索两阶段 + 向量缓存**：先快扫 node_id+embedding 打分，仅对 top-k 取完整
  节点；进程内向量缓存随写入同步失效

### 正确性 / 健壮性

- **MCP open_store 修复**：废除 CWD 相对 `"membridge.db"` 兜底，统一走
  `default_db_path()`（环境变量 > `~/.membridge/memory.db`）——此前从任意目录
  启动 MCP server 都会生成游离库，破坏「一台设备一份全局记忆库」语义
- **fetch 异常分流**：差分包读取错误区分为数据问题（损坏/口令错 → skipped）
  与环境问题（磁盘满/权限等 OSError → 新增 errors 通道），后者包保留原位、
  下次 fetch 自动重试，并记 warning 日志；不再静默吞掉环境故障
- **事务收敛**：新增 `MemoryStore.transaction()` 上下文管理器（事务深度计数），
  add+建边、差分应用、指纹登记等收敛为单事务原子提交；未包事务的零散写仍
  即时提交（跨连接立即可见，兼容 v0.7 行为）
- **SQLite 并发**：WAL 日志模式 + busy_timeout=5000ms，MCP 多客户端并发读写
  不再互相锁死
- **embedder 指纹支持 revision**：嵌入器可通过 `revision` 属性参与一致性指纹
  （同名模型不同版本不再误判一致）；为空时指纹与 v0.7 完全一致（握手兼容）。
  `OpenAIEmbedder` 新增 revision 参数；诚实标注：embedding API 不暴露权重版本，
  自动感知静默升级目前不可行

### token 经济（产品原则落地）

- **工具面收敛**：`memory_context` 并入 `memory_search(as_context=true)`，
  MCP 工具 4 → 3——每个工具描述都常驻所有客户端会话
- **检索相对阈值**：低于 top1×0.5 的弱命中不返回（`rel_floor` 可调，0 关闭），
  噪声记忆不再白吃上下文 token
- **add 端软引导**：工具描述明确"建议一句话一条"；单条超 200 字返回温和提示
  建议拆分（不阻止写入，不违反内容冻结）

### 易上手（产品原则落地）

- **doctor 库位置健康**：新增告警——库位于临时/生成目录（测试残留/磁盘清理风险）、
  环境变量库与 `~/.membridge` 默认库并存（疑似记忆库分裂）、设备名未设置；
  自检输出标明库路径来源（环境变量 / 默认位置）

### 测试隔离（真实事故修复）

- **修复：跑测试会劫持用户真实平台配置**。init 向导测试只注入了
  `wizard.HOME_DIR` 而漏掉 `clients.HOME_DIR`，且 `clients._appdata()`
  无视 HOME 注入直读真实 `APPDATA`——每跑一次测试套件，真实的
  `~/.zcode/cli/config.json`、`~/.cursor/mcp.json`、VS Code `mcp.json`
  就被改写到一次性临时目录（`membridge-gen-*`），各平台 MCP 静默失联。
  两处隔离洞均已修复，并新增金丝雀测试 `test_init_never_writes_real_user_configs`：
  跑全套测试前后对真实配置做字节级比对，再泄漏立即红

### 内容冻结（最高定律）加固

- 新增 `test_content_freeze_across_all_flows`：建边、全量重建、检索记热度、
  差分同步、旧库重开（BLOB 迁移）全走一遍后，所有记忆内容必须逐字节不变
- 新增 `test_mcp_tool_surface_is_add_only`：MCP 工具面锁定为
  {memory_add, memory_search, memory_preload}，未来任何改版引入
  update/delete/summarize 类改写工具都会红

### 文档

- README / README_EN 能力表对齐 v0.8；CLI 示例补 `rebuild-edges`；
  RFC-001 §10 工具表与 roadmap 新增「工程修订」节

### 测试

- 新增 9 项：增量建边、相对阈值、事务回滚、旧库 BLOB 迁移、embedder revision
  语义、fetch OSError 分流（含重试闭环）、init 永不改写真实用户配置（金丝雀）、
  全流程内容冻结、MCP 工具面只读边界
- 测试 41 → 50 项，双模式（pytest / run_tests.py）全绿

## [0.7.0] - 2026-08-30

环境变量口令 + 测试环境隔离 + 文档同步（WorkBuddy 协作贡献收编）。

- 口令支持环境变量 `MEMBRIDGE_PASSPHRASE`（优先级：参数 > 环境变量 > 保险库），
  便于自动化场景；修复缺失 `os` 导入导致的 autosync 崩溃
- 测试环境隔离：系统环境变量不再影响 autosync 测试；测试 41 项
- 文档同步：英文 README 升至 v0.7 能力表、路线图勾选全自动同步、CLI 示例补全

## [0.6.1] - 2026-08-29

补齐 v0.6.0 遗漏的文档与测试，并让口令类报错说人话。

- 文档补齐：`publish --force` 的用法与补救场景写入 README / README_EN
  （v0.6.0 已带上该功能却未记录）
- 口令报错可操作：区分「未提供口令」（指名 `MEMBRIDGE_PASSPHRASE`）与
  「口令不匹配」（指引 `membridge show-passphrase`），不再只抛 Fernet 的 InvalidToken
- 新增 5 项测试覆盖 force 重发、force 幂等、三设备补取、两类口令报错
- 测试 36 → 41 项

## [0.6.0] - 2026-08-29

口令零负担：同步口令由系统自动生成并托管，用户彻底不用设置、不用记忆。

- init 自动生成强随机口令（token_urlsafe(24)）存入本机 DPAPI 保险库，用户全程无感
- 新增 `membridge show-passphrase`：配对新设备时查看口令（AI 替你记住，需要时才看）
- `set-passphrase` 保留为手动覆盖
- fetch 增强：同时扫描 outbox 与 archive——三台以上设备都能补取同一个包
  （指纹去重保证不重复入库；已在库中的重复包自动跳过）
- 测试增至 36 项

## [0.5.1] - 2026-08-29

口令设置体验修复：首次真实配置时用户空按回车导致自动同步不生效。

- 新增 `membridge set-passphrase`：独立设置/修改自动同步口令（输入两次确认）
- 向导在口令为空时解释其作用并追问一次，不再静默跳过

## [0.5.0] - 2026-08-29

全自动同步：用户零点击，记忆按重要程度自动上云。

- **云盘通道自动选定**：规定优先级（坚果云 > OneDrive > 百度网盘同步盘 >
  iCloud > Dropbox > Google Drive），检测到哪个用哪个，多盘共存也不问
- **口令保险库**（vault.py）：Windows DPAPI 加密托管同步口令，用户只在 init
  输入一次，此后永不再输（纯标准库 ctypes，零第三方依赖）
- **自动同步引擎**（sync_agent + `membridge autosync`）：重要记忆（高置信 /
  高频访问 / important 标签）**立即上云**；普通记忆攒够 5 条或超 24 小时
  批量上云；`local` 隐私记忆**永不上云**
- **计划任务**：init 自动注册 Windows 计划任务（每 15 分钟双向同步），
  `--no-autosync` 可关闭
- 测试增至 35 项

## [0.4.1] - 2026-08-29

修复 WorkBuddy（技能化 agent）实战反馈的两个真实问题。

- **修复**：全新机器上 `~/.membridge` 父目录不存在导致 `sqlite3.OperationalError`
  建库崩溃（WorkBuddy 首次真实 init 时发现）；补回归测试
- **确立产品语义：一台设备一份全局记忆库**——init / doctor / add / search /
  stats 默认统一解析到 `~/.membridge/memory.db`（env MEMBRIDGE_DB 优先），
  消除"init 建全局库、add 写进工作区旧文件"的割裂；项目隔离显式传 `--db`
- `default_db_path` 收口到 store.py 单一实现，cli / wizard 共用

## [0.4.0] - 2026-08-29

借鉴腾讯 ncnn 的工程实践（docs/design-notes/ncnn-borrowings.md）：自描述包、
运行时能力调度、便携免安装构建。

- **自描述同步包 + embedder 一致性握手**：差分包内嵌嵌入器指纹（type/name/dim/fp），
  接收端发现嵌入模型不一致即拒绝应用——排除"换模型导致记忆语义漂移"的静默错误；
  旧格式包向后兼容
- **运行时能力调度**（capabilities.py）：按环境自动选择最优实现并优雅降级
  （嵌入器 OpenAI→哈希、加密、向量索引、同步盘检测）；`membridge doctor` 展示能力画像
- **便携 membridge.exe**：PyInstaller 免安装单文件构建（scripts/build_exe.bat），
  拷到任何 Windows 机器即可用，无需 Python——ncnn 式便携发布
- CLI 新增 `--version`；测试增至 28 项

## [0.3.1] - 2026-08-29

修复产品逻辑：云盘配置从"可选询问"改为"init 强制完成"——默认必做，跳过必须显式确认。

- 交互模式：不配置云盘无法静默跳过，需连续输入两次 skip 确认
- 非交互 `--all`：自动使用检测到的同步盘（其内 membridge/ 目录）完成配置；
  无任何同步盘时打印免费云盘引导，并以显著警告收尾
- 云盘通道路径持久化到记忆库：`membridge stats` / `doctor` 可见配置状态
- 测试增至 23 项

## [0.3.0] - 2026-08-29

安装即上云：`membridge init` 把"配置云盘中转"提为第一步（产品决策：记忆不上云，跨设备无从谈起）。

- init 新流程：① 云盘通道（默认必做）→ ② 记忆库 → ③ 设备名 → ④ 平台接入
- 自动识别本机已装同步盘：坚果云 / OneDrive / 百度网盘同步盘 / iCloud 云盘 /
  Dropbox / Google Drive，并以其内 membridge/ 目录为通道
- 未装同步盘时引导注册免费云盘（按论文 §4.5 测算：单用户记忆一年约 1GB、
  日写入约 5MB，免费额度足够）
- 新增 `--skip-netdisk`（单设备用户）；`--netdisk-dir` 行为不变；测试增至 22 项
- 安全加固：差分包路径显式禁止 `..` 上跳成分并强制规范化；云盘通道文件名
  白名单校验（针对半可信同步目录的防御，安全扫描发现）

## [0.2.1] - 2026-08-29

文档勘误：README 各处同步 v0.2 能力，消除"WorkBuddy 仍在规划中"等过时表述。

- 中英 README 能力表升级为 v0.2，补"一键接入平台"行
- CLI 示例补齐 `init` / `doctor` / `publish` / `fetch`
- "接入 MCP 客户端"章节改为"手动接入（init 已覆盖的平台可跳过）"
- 架构图连接层补"平台技能（WorkBuddy 等）"；路线图 Phase 1 状态同步

## [0.2.0] - 2026-08-29

新增 `membridge init` 一键接入向导：用户装完即让本机所有主流 AI 平台具备跨应用记忆共享。

- 平台自动配置（检测到即接入、幂等安全）：ZCode、Claude Code、Claude 桌面版、Cursor、
  Cline、Windsurf、VS Code（Copilot MCP）、Gemini CLI、通义千问 Code
- 技能型平台：自动安装记忆技能（SKILL.md）到 WorkBuddy（`~/.workbuddy/skills`）
  与 Claude 技能目录 —— WorkBuddy 正式支持
- 远程 MCP：`membridge mcp --http`（SSE / Streamable HTTP），扣子 Coze 等平台经 URL 接入
- 手动指南：字节 Trae 等界面化平台由 init 打印逐步指引
- 新增 `membridge doctor` 环境自检；核心零依赖不变，测试增至 19 项

## [0.1.1] - 2026-08-29

修复：mcp 2.x 将 FastMCP 更名为 MCPServer，导致 MCP 服务器无法构建。

- 锁定 `mcp>=1.2,<2`（v1 API 为当前生态主流，2.x 迁移列入后续版本）
- 依赖缺失时给出包含原因的错误提示
- 触发场景：首次把记忆桥注册为本机 MCP 服务器时发现

## [0.1.0] - 2026-08-29

### 新增
- 核心引擎 v0：`MemoryNode` / `MemoryStore`（SQLite 单文件）
- 蒸馏层：SAN 语义关联网络（`w_ij = λ·共现代理 + (1-λ)·余弦`，PMI 项可注入替换）
- 注入层：Path A 显式上下文拼接（`injection.serialize` / `build_prompt_aug`）
- 同步层：DSS 增量语义同步（语义指纹 + 边差异量化 ε=0.01 + 差分包编码/应用）
- 传输通道层：文件夹 / 网盘中转（FolderTransport）——差分包写入百度网盘同步盘 /
  坚果云 / OneDrive 等同步文件夹即可跨设备；默认 Fernet 口令端到端加密（随机盐随包
  携带），`archive/` 兼作论文 T4 云归档；CLI 新增 `publish` / `fetch`
- 隐私层：PAMS L1 迁移标签 + L2 场景域门控（L3 差分隐私按约定后置）
- 缓存层：TMT 热度启发式（recency × frequency）与预加载候选
- MCP Server：`memory_add` / `memory_search` / `memory_context` / `memory_preload`
- CLI：`add` / `search` / `context` / `preload` / `delta` / `apply` / `stats` / `mcp`
- 端到端演示 `examples/demo.py`（手机 → PC 跨设备记忆继承）
- 测试：11 项核心测试（pytest 与零依赖运行器双兼容）
- 文档：设计 RFC、路线图、隐私威胁模型、中英双语 README
- 版本与发布规约：docs/VERSIONING.md（语义化版本、三处同步、发布流程）与 AGENTS.md 项目规约

### 设计决策（按约定后置）
- Path B 隐藏状态融合 → Phase 4 experimental 分支
- AEE 自适应进化引擎（α / π_nav / θ_window）→ Phase 4（接口签名已对齐论文）
- L3 内容级差分隐私 → Phase 4+（Phase 2 先以端到端加密兜底）
