# RFC-002：容器一致性（各端记忆容器可声明、可对账、可自动补齐）

状态：已采纳（v0.16.0） · 作者：jiabaobei · 2026-09-02

## 1. 背景与问题

v0.13.0 通道归一解决了「各端指向同一个云盘通道」（channel.json + 自动认领），
v0.14.0 在本地库加上了类型化边（`kind`/`evidence`）。但实际跨端使用时发现
两个「容器不一致」问题：

1. **差分链路 schema 丢失**：差分包 `Delta` 的 `edges` 仍是 `(src, dst, w)`
   三元组，`apply_delta` 解包后调用 `add_edge(src, dst, w)`——`kind` 与
   `evidence` 在跨设备往返中**静默丢失**。v0.14 的类型化边只在本地有效，
   一跨端就退化成 v0.13 的裸权重边。这是 RFC-001 已记载的已知限制，
   但在真实多端使用（如网页端 VIBEX 自建容器）时被放大成「两端容器长得
   完全不一样」。
2. **schema 无对账机制**：各端升级节奏不同（有的还停在 v0.13、有的跑
   v0.14+），谁缺 `kind` 列、谁多一档边类型，没有可程序化的检测手段，
   全靠肉眼对比，冲突只能靠猜。

**目标**：让「容器」成为一等公民——每端可声明自己的容器身份证
（manifest），跨端可指纹对账，差异可按迁移登记自动补齐；不能自动补的
差异给出明确的升级路径，而不是静默错乱。

**约束（延续三铁律）**：只加结构不碰记忆内容；极度省 token（清单要小）；
极简洁（零新依赖）；向后兼容（v0.14 旧端收 v0.15 的包不崩）。

## 2. 术语

| 术语 | 含义 |
|---|---|
| 容器（container） | 一台设备上的记忆存储实体，即 SQLite 库（表结构 + 字段 + 类型枚举） |
| 容器清单（manifest） | 描述本端容器 schema 的声明文件（结构上从库实读生成） |
| schema 版本 | 容器 schema 的演进版本号，跟随记忆桥语义版本（0.15.0） |
| 指纹（fingerprint） | 对清单序列化的哈希，跨端对账的最小比较单位 |
| 迁移登记（migration） | 描述「从某版本到某版本补了什么字段」的声明，可执行 |
| 对账（reconcile） | 本端清单 × 对端清单 → 差异清单 + 可执行补齐动作 |

## 3. 容器清单设计

清单是纯声明、可机器读的 JSON，结构从本端库**实读**生成（不硬编码）：

```json
{
  "device": "DESKTOP-8GC3CQQ",
  "schema_version": "0.15.0",
  "node_fields": ["node_id","content","embedding","tags","scene","device",
                  "migration","confidence","created_at","last_access","access_count"],
  "edge_fields": ["src","dst","weight","kind","evidence"],
  "kind_enum": ["semantic","cooccur","entity"],
  "migrations": ["0.14:edges.kind default semantic",
                 "0.14:edges.evidence default ''"]
}
```

要点：

- `schema.py` 提供 `local_manifest(store)`（实读 `PRAGMA table_info` +
  内置字段声明）、`manifest_fingerprint(manifest)`（规范化序列化 +
  SHA-256，前 12 位展示用）、`reconcile(local, remote)`。
- 指纹只比较「字段集 + 类型枚举 + 迁移登记」三个维度；`device` 不参与
  指纹（设备名只是标签，各端自然不同）。
- 清单体积 < 1KB，随差分包携带只占极少 token。

## 4. 差分链路改造（根因修复）

### 4.1 `Delta` 新增字段（双键向后兼容）

```python
@dataclass
class Delta:
    ...
    edges:   List[Tuple[str, str, float]]          # 老键：三元组，保留
    edges_v2: List[Tuple[str, str, float, str, str]]  # 新键：含 kind/evidence
    schema:  Optional[str] = None                  # 发送端清单指纹
```

- `to_json` 同时输出 `edges`（老键，继续填充）与 `edges_v2`（新键），
  **v0.14 旧端读包时忽略未知键，照常应用三元组**——不崩。
- v0.15 端之间优先消费 `edges_v2`，类型与证据完整落地。

### 4.2 `make_delta` 采集完整边

改用 `store.all_edges_full()`（返回 `(src,dst,weight,kind,evidence)`
五元组；原 `all_edges()` 保留不动，兼容旧调用方）。发送端打包时：
- 老 `edges` 键 = 五元组前三维（保持 v0.14 语义）
- 新 `edges_v2` 键 = 完整五元组

### 4.3 `apply_delta` 先对账后合并

接收端应用顺序：

1. 若 `delta.schema` 存在 → 与 `local_manifest(store)` 对账：
   - 本端缺字段且对方 `migrations` 有登记 → 自动 `ALTER TABLE` 补齐
   - 本端缺字段且无登记 → 拒绝应用该包并报告升级路径（不静默错乱）
   - 对方缺字段 → 可正常应用（对方落后，本端兼容）
2. 优先消费 `edges_v2`；老包无此键时退回三元组，旧边按 v0.14 迁移
   约定视为 `kind="semantic"`、`evidence=""`。

## 5. CLI 与体检

- `membridge schema`：本端清单一屏看（含指纹、缺字段、迁移登记）。
  - `--json`：机器可读输出，供网页端 / 其他端程序化对账。
  - `--peer <file>`：与对端清单（文件或 URL 拉取）双向对账——本端缺什么 /
    对端缺什么分别列出；可补齐提示「下次 fetch 应用对方差分包时自动
    ALTER 补齐」；不可补给出升级路径，退出码非 0。
- `doctor` 增加容器段落：本端清单指纹 + 通道内最近见到的其他端清单指纹，
  不一致时显式告警（呼应 channel 体检的通道维度，互为补充）。

## 6. 兼容性与迁移

| 场景 | 行为 |
|---|---|
| v0.15/v0.16 ↔ v0.15/v0.16 | edges_v2 全量往返，kind/evidence 不丢；schema 指纹一致 |
| 新端收 v0.14 包 | 无 edges_v2 → 退回三元组，kind 按 semantic 落库；不崩 |
| v0.14 收新包 | 忽略未知键 edges_v2/schema，按三元组应用；不崩 |
| 旧库（无 kind 列）打开 | 自动迁移补列（v0.14 已有），清单指纹同步登记 |
| 新包 seq=0（老发端） | 不写 watermark，照常合并——版本协商对旧端零侵入 |

## 6.5 三存储平面与版本协商（v0.16，开源借鉴）

| 借鉴来源 | 落地点 | 说明 |
|---|---|---|
| mem0（★28k） | `storage_planes` 三平面声明 | graph=edges / vector=nodes.embedding / kv=meta，实读表结构判定；缺平面即指纹不同，doctor 可查 |
| 0xPlaygrounds/rig（★2.4k） | seq 版本协商 + watermark | 发包 seq 单调递增（meta `sync_seq`）；接收端写 `sync_watermark_<device>` 只增不减；重复/乱序包内容指纹去重天然幂等 |
| zillur-av/docker-image-schemavalidator | 差分包携带 schema 指纹 | `Delta.schema_fp` 随包，接收端先对账后合并（4.3 节） |

## 7. 验证

`tests/test_v015_container.py`（29 项）：

- 老库缺 kind/evidence 列 → 对账判定可补齐 → ALTER 后指纹对齐
- 三端差分往返（A→B→C）→ edges_v2 五元组完整、kind/evidence 不丢
- v0.14 旧格式包 → apply 不崩且语义正确（kind=semantic）
- CLI `schema --peer` 双向对账（对端缺列 / 对端多字段 / 完全一致）
- manifest 声明三存储平面（graph/kv/vector），缺 vector 平面指纹不同
- seq 单调递增（1→2）、watermark 只增不减、重复包 nodes_added=0

## 8. 后置（不随 v0.16 做）

- 节点主键 UUID 化（当前用内容指纹作 node_id；UUID 化解决跨端节点命名
  截断问题，但涉及全库主键迁移，破坏性大，放后续版本评估）
- manifest 随包的强制校验开关（默认宽松告警，未来可 `--strict`）
- VIBEX 等复刻端的一键接入脚本 `mb.py init --remote <端名>`（识别非
  jiabaobei 通道的容器并引导对账）
