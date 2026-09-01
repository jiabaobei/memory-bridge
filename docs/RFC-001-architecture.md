# RFC-001：记忆桥工程架构（CDSMP 论文 → 工程实现映射）

状态：已采纳（v0.1） · 作者：jiabaobei · 2026-08-29

本文是连接论文与代码的桥梁：每一节先给出论文中的定义，再给出记忆桥 v0 的
工程决策与后置计划。**架构总约束：内容冻结** —— 任何模块只读记忆内容、
只调节结构参数，绝不生成或改写语义（规避 Faulty Memory 失效域）。

## 1. 范围：跨设备 + 跨平台

- 论文覆盖**跨设备**（手机/平板/PC/边缘网关之间的记忆连续性）。
- 记忆桥在此基础上扩展**跨平台**：通过 MCP 协议与 SDK 连接器，让同一个记忆库
  被多个 AI 应用（Claude Code、Cursor、Cline、未来的移动端与浏览器插件）共享。
- 分工：MCP/连接器是"跨平台"接入层；DSS 同步是"跨设备"数据层。两层正交组合。

## 2. 术语与模块映射

| 论文概念 | 记忆桥模块 | v0 状态 |
|---|---|---|
| 感知层（交互信号采集） | 连接器（CLI / MCP 工具调用 / 手机网关 `gateway`，v0.11） | ✅ 以工具调用为感知入口 |
| 蒸馏层 SAN（n_i, e_i, w_ij） | `san.py` + `node.py` + `embeddings.py` | ✅ 简化版 |
| 缓存层 TMT（H(n)、四级驻留、预加载） | `heat.py` + `store.py` | ✅ 启发式；边缘驻留 Phase 3 |
| 同步层 DSS（ΔG、指纹、ε 量化） | `dss.py` | ✅ 本地差分；E2E 通道 Phase 2 |
| 注入层 Path A（Serialize ⊕ Prompt） | `injection.py` | ✅ |
| 注入层 Path B（隐藏状态融合） | experimental 分支 | 🧪 Phase 4 |
| 隐私层 PAMS（L1/L2/L3） | `privacy.py` | ✅ L1/L2；L3 后置 |
| 反馈层 AEE（α/M/β/W_align/φ/θ_window） | `heat.py` 接口签名预留 | 📋 Phase 4 |
| UEP 统一评测协议 | `benchmark/`（规划） | 📋 Phase 4 |

## 3. 数据模型

**产品语义（v0.4.1 确立）：一台设备一份全局记忆库**（默认 `~/.membridge/memory.db`，
env `MEMBRIDGE_DB` 可覆盖）——记忆跟着人走，不跟项目走；init / doctor / add /
search / stats 默认解析到同一份库，需要项目隔离时显式传 `--db`。

一条记忆 = 论文中的语义节点 n_i：

```
MemoryNode:
  content      原始内容（内容冻结：落库后任何模块不得改写）
  embedding    语义向量 e_i
  tags         用户标签
  scene        PAMS L2 场景域（work/personal/medical/financial/...）
  device       产生时所在设备
  migration    PAMS L1 迁移标签（local/edge/cloud）
  confidence   置信度（注入阈值 θ_c 的判据）
  created_at / last_access / access_count   TMT 热度依据
```

存储：每设备一个 SQLite 文件（`nodes` / `edges` / `meta` 三张表）。
理由：全平台零部署、单文件可整库加密/备份/删除、便于 DSS 做整库差分。
向量检索 v0 为余弦暴力扫描；超过 ~10⁴ 节点后引入 sqlite-vec 索引。

## 4. 嵌入一致性约束（跨设备正确性的前提）

DSS 假设两端向量可比，因此：**同一用户的全部设备必须使用同一 embedder**
（同模型、同维度、同预处理）。v0 内置 `HashingEmbedder`（字符 n-gram 特征哈希，
零依赖、跨平台确定性一致）用于开发与离线场景；生产推荐全设备统一真实模型
（如 OpenAI text-embedding-3-small 或本地 bge 系列）。embedder 标识
（名称+维度）将在 Phase 2 写入 `meta` 并参与 DSS 握手校验。

## 5. 蒸馏层：SAN 简化版

论文：`w_ij = λ·PMI(n_i, n_j) + (1-λ)·cos(e_i, e_j)`，λ∈[0,1]。

v0 决策：
- PMI 项以字符 n-gram 集合的 Jaccard 共现代理（无需语料级统计）；
  `san.build_edges(pmi_fn=...)` 保留注入点，后续可换完整 PMI。
- 建边阈值 `min_weight=0.15`，保持图稀疏（论文：边密度 < 0.1%）。
- 复杂度 O(n²)（v0 规模 < 10³ 节点可接受）；规模化后按嵌入分桶降为近似 O(n)。
- 边界约束：只对**已存在内容**计算关联，绝不生成新语义。

## 6. 缓存层：TMT 热度与预加载

论文：`H(n_i) = Σ_k e^(−α_k·Δt_k) · I[device=d_current] · γ_d`，
预加载 `Preload(d') = {n_i | γ_{d'}(n_i) > θ_preload ∧ H(n_i) > θ_hot}`。

v0 决策（按约定采用启发式，接口签名对齐论文）：
- `heat(n) = e^(−α·Δt) × (1 + ln(1+access_count)) × confidence`，
  α 单位为小时、默认 0.5（论文可复现性声明的初值）。
- 阈值沿用论文声明：θ_hot=0.4、θ_preload=0.6、预算 K=8。
- 预加载候选 = PAMS 门控通过后的热度 Top-K；π_nav 图游走导航（Phase 4）
  仅替换 `heat.preload_candidates` 的实现。
- 四级驻留映射：v0 只有 T3（本地 SQLite）；T1/T2（设备内存/边缘网关）
  Phase 3 引入 hot/cold 两级；T4 云归档随中继服务引入。

## 7. 同步层：DSS 协议

论文：`ΔG_{A→B} = (G_A \ G_B) ∪ {w_ij | w_ij^A ≠ w_ij^B}`。

实现（`dss.py`，纯本地计算，传输通道 Phase 2 接入）：

1. **节点指纹** h(n)：内容做空白/大小写归一后取 blake2b-128。
   存在性比较 O(1)，天然幂等（重复同步收敛为空差分）。
2. **节点差分**：指纹不在远端 → 整节点（含向量）进入差分包。
3. **边差分**：两端点在远端"已知"（已存在或随本次差分到达）且
   `|Δw| > ε`（ε=0.01，论文声明值）→ 同步该边。

   > **v0.14 已知限制**：差分包只同步 `(src, dst, weight)` 三元组——边类型
   > `kind` 与 `evidence` 属本机派生结构，**不跨设备同步**。理由：改动差分
   > 线上格式会让旧版本设备解包失败（破坏跨版本互同步），收益（对端少一次
   > 重建）小于兼容性代价。实践影响可忽略：类型标注是本机可读的"为什么
   > 相关"解释，随时可在本机 `membridge rebuild-edges` 重建；实体锚点边也会
   > 在接收端随记忆内容落库后重新计算。若日后随主版本统一升级，可再议。
4. **PAMS 出口门控**：`migration=local` 的节点在差分包生成前即被剔除 ——
   隐私过滤发生在数据通路构造处，而非传输后过滤。
5. **应用规则**：接收端按指纹去重后原样落库（内容冻结），边仅在两端点存在时应用。
6. **载荷**：JSON（`Delta.to_json`）。版本向量（`Delta.seq` 已占位）与
   冲突解决（LWW 起步）在 Phase 2 完成。

### 7.1 传输通道矩阵（可插拔）

| 通道 | 端到端加密 | 实时性 | 状态 | 适用 |
|---|---|---|---|---|
| **文件夹 / 网盘中转**：百度网盘同步盘、坚果云、OneDrive、U 盘、局域网共享目录 | ✅ Fernet 口令加密（`membridge[netdisk]`） | 随网盘同步节奏 | ✅ v0 已实现 | 零服务器，国内环境最务实 |
| 局域网直连 | ✅（计划） | 好 | 📋 Phase 2 | 家庭 / 办公多设备 |
| 自托管实时中继 | ✅（计划） | 最好 | 📋 Phase 2 | 异地实时连续性 |

网盘中转的工程落位（`transport.py`）：发送端 `publish` 把"尚未发布过"的
差分包写入通道 `outbox/`（先写临时文件再改名，避免网盘读到半包）；接收端
`fetch` 应用后把包移入 `archive/` —— 这正是论文 T4 云归档的工程落位。
隐私约定（PAMS 传输落位）：写入网盘默认必须口令加密（网盘服务商只见密文），
明文需显式 `--plaintext` 确认。已发布指纹持久化在本地库 `meta` 中，重复
发布幂等为空。

### 7.2 自动同步（v0.5，用户零点击）

- **通道自动选择规则**：按优先级取第一个检测到的同步盘——坚果云 > OneDrive >
  百度网盘同步盘 > iCloud > Dropbox > Google Drive；多盘共存不询问，其余列为备选。
  OneDrive 匹配家目录下所有 `OneDrive*` 根（`OneDrive - 个人` / `OneDrive - 公司`
  等变体，v0.13）——同一云盘在不同设备上的根目录名常常不同。
- **通道身份归一（v0.13）**：自动选择规则只解决"单台设备选哪个云"，不解决
  "多台设备是否选了同一个"。为此通道目录内置自描述清单 `channel.json`
  （通道 ID / 创建者 / 创建时间 / 嵌入器指纹）：首个发布/初始化的设备创建，
  后续设备首次 init / publish / fetch / autosync 时**自动认领**（adopt）；
  本机通道 ID 与清单不一致即显式告警（先到先得不改写）。约束：清单是**纯
  元数据——不含口令、不含任何记忆内容**，先写临时文件再改名（与差分包同一
  半包防御）；`membridge channel` 提供一致性体检。它与嵌入器指纹握手互补：
  握手保证两端"语义一致"，身份证保证两端"指向同一个地方"。
- **口令托管**：同步口令由**系统自动生成**（强随机 token_urlsafe）并用 Windows
  DPAPI（绑定当前用户，纯 ctypes 零依赖）加密存于本库 meta——用户全程无需
  设置、无需记忆；配对新设备时用 `membridge show-passphrase` 查看一次即可
  （`set-passphrase` 保留为手动覆盖）。换机器/换账户不可解。
- **重要度规则**：重要记忆（confidence ≥ 0.8 / 访问 ≥ 2 次 / important 标签）
  立即上云；普通记忆 ≥ 5 条或距上次发布 ≥ 24h 批量上云；`migration=local`
  永不上云（PAMS 优先级最高）。
- **调度**：init 自动注册 Windows 计划任务（每 15 分钟 `membridge autosync`），
  双向（发布 + 取回）；`--no-autosync` 退出。

## 8. 注入层

- **Path A（已实现）**：`injection.serialize` 把高置信节点序列化为带出处的
  上下文块（时间/设备/场景），`build_prompt_aug` 完成
  `[System] ⊕ [记忆块] ⊕ [当前问题]`。显式、可审计、跨模型可用。
- **Path B（Phase 4，experimental）**：`H' = H + β·W_align·h_i·p_pos`。
  仅对本地开源模型可行；需解决维度对齐（跨设备不同量化/架构）与噪声放大。
  约定：进入 experimental 分支单独演进，不阻塞主线。

## 9. 隐私层：PAMS

- **L1（已实现）**：`migration ∈ {local, edge, cloud}`。local 节点在
  差分构造、预加载候选两个出口都被硬过滤。敏感内容（凭据类关键词）
  写入时自动降级为 local（`privacy.default_migration`）。
- **L2（已实现）**：场景域关键词分类（medical/financial/work/personal），
  跨域预加载默认拒绝；显式授权流 Phase 3。
- **L3（后置）**：差分隐私噪声注入。在 L3 就位前，传输以 E2E 加密兜底
  （中继只见密文，见 threat-model.md）。

## 10. MCP 工具设计（跨平台接入）

工具集严格限定在 UEP 权限边界（Add / Search / Preload）：

| 工具 | 论文阶段 | 说明 |
|---|---|---|
| `memory_add` | Add（写） | 自动场景分类 + 迁移标签判定；增量建边（语义/共现边 + v0.14 实体锚点边）；超 200 字软引导拆分（v0.8）；可选 `kind` 标注 fact/procedure（v0.9） |
| `memory_search` | Search（读） | 三路混合检索（向量 + 关键词 + SAN 一跳图）+ RRF 融合（v0.9）；命中计入热度；相对阈值滤弱命中；`as_context=true` 返回**带预算**的 Path A 上下文块，无高质量命中时显式返回「本轮不干预」（沉默契约，v0.9）；可选 `scope` 范围直达 `tag:/scene:/kind:`（已知目标先过滤再融合，v0.13.1）；v0.14 起 context 标注极短召回理由（向量/关键词/图谱），`hybrid_search` 为兼容薄封装；v0.8 并入原 `memory_context` |
| `memory_preload` | Preload | 热度候选（PAMS 门控后）；v0.14 增整簇模式（`--cluster`，连通分量切簇后按当前最热节点所在簇返回） |

> v0.8 工具面收敛：原 `memory_context` 并入 `memory_search(as_context=true)`，
> 工具数 4 → 3——每个工具描述都常驻所有客户端会话，省 token 从工具面开始。
> v0.9 描述瘦身：三个工具描述各压缩到一行；预算注入中超预算条目注入原文
> 前缀（截断 ≠ 改写，内容冻结无损）。检索/注入契约的逐项外部借鉴映射见
> docs/roadmap.md「借鉴版」一节。

**刻意不提供**：任何改写/删除/摘要记忆的工具（内容冻结），以及读取
`migration=local` 内容的跨设备工具。

## 11. AEE 演进接口契约（Phase 4）

v0 的可进化参数全部集中、具名、带范围，AEE 上线时只动这些参数：

| 论文机制 | v0 占位 | AEE 目标 |
|---|---|---|
| α 时间衰减自适应 | `heat.heat(alpha=0.5)` 常量 | 在线梯度更新（有限差分） |
| 设备-场景自发现 | scene 为静态标签 | 关联矩阵 M 贝叶斯在线更新 |
| Path B 反馈闭环 | —（experimental） | β/W_align 策略梯度 |
| π_nav 导航策略 | `heat.preload_candidates` 热度 Top-K | SAN 图上的受限策略游走 |
| θ_window 预加载窗口 | Phase 3 引入 | 自适应窗口 + 冷启动 8h 保底 |

## 12. 评测（Phase 4）

按论文 UEP 思路做轻量版：固定生成/评测模型与 prompt 模板，差异只允许
出现在记忆模块的 Add/Search/Preload；指标 TCR / TTFT / 带宽 / token 开销 /
Recall@K。复现脚本置于 `benchmark/`，README 数字届时与脚本输出绑定。

## 13. 明确的后置决策（已达成一致）

1. **Path B** → Phase 4 experimental 分支（闭源 API 无 hidden states）。
2. **AEE / π_nav** → Phase 4，v0 用"最近访问+频率"启发式，接口对齐论文签名。
3. **L3 差分隐私** → Phase 4+，先行以 E2E 加密兜底。
