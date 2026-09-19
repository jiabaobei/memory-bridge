"""记忆技能模板：安装到支持 SKILL.md 约定的 agent 平台（WorkBuddy / Claude 技能目录等）。

单一事实来源：`SkillInstaller`（见 `clients.py`）从这里生成技能文件，
写入 `<skills>/memory-bridge/SKILL.md`，内容与本常量逐字节一致（幂等，相同则跳过）。

命令面以 `cli.py` 的子命令为准；`tests/test_clients.py` 有一条测试强制校验
本模板覆盖全部子命令，漏写即测试失败——避免"加了命令但技能不知道"的历史缺口重演。
"""

SKILL_MD = """---
name: memory-bridge
description: 跨设备跨平台的持久记忆（记忆桥）。当用户要求"记住/记一下/别忘了/remember"某事时写入记忆；当需要回忆此前对话、项目背景、用户偏好，或回答与用户历史相关的问题时检索记忆；每次会话开始处理新主题前可先检索一次相关记忆。
---

# 记忆桥（MemoryBridge）技能

通过 `membridge` 命令行读写用户的跨设备记忆库（SQLite 单文件，位置由环境变量
`MEMBRIDGE_DB` 指定，默认 `~/.membridge/memory.db`）。

## 何时使用

1. **写入**：用户告知值得长期记住的信息（偏好、决定、项目背景、进行中的任务），
   或明确说"记住这个"。
2. **检索**：回答与用户历史相关的问题前；用户提到"之前/上次/我们说过"时；
   开始一个新主题前先搜一次相关记忆。
3. **注入**：需要把记忆作为上下文带给模型时，用 `context` 命令取现成的记忆块
   （最新交接卡会以【工作台】小节恒定注入，先读它再决定要不要检索旧账）。
4. **交接班**：任务告一段落、上下文将满、或即将切换设备前，写一张交接卡
   （goal/done/failed/next/refs 五行；新卡自动取代旧卡）。
   failed 行用硬句式：试过什么；因为什么失败；除非什么改变否则别重试。
5. **体检**：记忆疑似没写进来、同步失灵、或用户问"你到底记住了什么"时，
   先跑体检命令拿事实，再回答——不要凭印象说"应该记住了"。

## 命令

### 日常：写入、检索、注入

```bash
# 写入一条记忆（内容保持用户原意，不要改写润色）
# --kind 只取 fact（稳定事实）/ procedure（试过什么、结果）/ handover（交接卡）
# --tags 逗号分隔标签；--scene 场景域（留空自动分类）
membridge add "<要记住的内容>" --tags <逗号分隔标签> --kind <fact|procedure|handover>

# 语义检索最相关的 k 条
membridge search "<关键词>" -k 5

# 取出可直接注入 prompt 的记忆上下文块
membridge context "<主题>" -k 5

# 记忆库统计（条数 / 标签 / 关联）
membridge stats

# 批量导入：把 Markdown/文本日志的条目行写进记忆库（零 LLM，逐条内容判重）
# 条目行 = `- `/`* `/`N. ` 开头；标题/空行/代码块跳过；文件名带日期时加 [日期] 前缀
membridge import-md <文件或目录>          # 目录取 *.md 与 *.txt
membridge import-md <路径> --dry-run      # 只解析与判重，不写库；先看再导
membridge import-md <路径> --tags imported --min-len 8
```

要点：
- `import-md` 是 autosync 缺的 Ingest 一环：自动同步只运「已在库里的」，**从不采集**。
  会话产出了值得长期记住的东西、而没走 `add` 时，用 `import-md` 把日志补进库。
- 隐私词照走 PAMS 自动判定（命中即 `local` 永不上云），与单条 `add` 同一套规则。
- 逐条按内容精确判重：重复跑安全，不会产生重复记忆。

### 交接班

```bash
# 写一张交接卡（新卡自动取代旧卡）
membridge add "goal:…
done:…
failed:…
next:…
refs:…" --kind handover

# 查看当前工作台（最新交接卡原文与生效状态）
membridge handoff

# 打印常驻提示，供粘贴进 CLAUDE.md / AGENTS.md（自愿启用）
membridge handoff-hint
membridge recall-hint
```

### 同步：本机 ↔ 其他设备

```bash
# 一键双向同步：先取回他端记忆，再发布本机新记忆（最常用）
membridge sync --dir "<同步文件夹>"

# 拆开做：publish 发布本机差分，fetch 取回他端差分
membridge publish --dir "<同步文件夹>"
membridge fetch --dir "<同步文件夹>"

# 离线/可审计：先生成 DSS 差异包，再手动并入
membridge delta <对端库路径> --out <包路径>
membridge apply <包路径>

# 列出可预加载到目标设备的记忆（过 PAMS 出口门控）
membridge preload <目标设备> -k 5

# 自动同步：重要记忆立即上云、普通记忆批量上云 + 取回他端
membridge autosync
```

### 网盘三端直达（rclone / WebDAV）

```bash
membridge netdisk-status        # 体检：rclone / 授权 / 云盘目录 / 基线
membridge netdisk-connect --dir "<云盘目录>"   # 接线：rclone 就位 → 授权 → 首次拉取
membridge netdisk-sync          # 文件夹级双向同步，随后链式跑包级 sync
membridge netdisk-disconnect    # 撤销接线：删除授权段与本机基线标记
```

### 体检与维护（只报告，不改写记忆）

```bash
membridge doctor                # 环境自检：版本 / 记忆库 / 可选依赖 / 平台检测
membridge lint                  # 内容体检：悬空边 / 孤立 / 陈旧 / 凭证泄露
membridge channel               # 通道一致性：本机与其他设备是否同一个云盘通道
membridge schema                # 容器一致性：本端容器清单 / 指纹 / 与对端对账
membridge export                # 导出人类可读 Markdown 视图（只读，永不回写）
membridge rebuild-edges         # 全量重建语义关联边（调过阈值或边异常时用）
```

- `lint` 退出码：仅**悬空边**与**凭证泄露**算失败（返回 1）；孤立/陈旧只提示，不染红 CI。
- `lint --json` 换结构化输出；`lint --fix-structure` 清除悬空边；两者可同时用，
  JSON 里的 `fixed_edges` 会如实报告删了几条。
- `lint --fix-structure` 只删悬空边（边是结构，不是记忆内容），**不碰任何记忆内容**。
- `lint` 报出的凭证一律打码回显，不会把密钥原文写进输出。
- `lint --stale-days <N>` 可改陈旧阈值（默认 90 天）。

### 接入其他客户端

```bash
membridge init                  # 一键配置：云盘通道 + 口令 + 平台接入 + 自动同步计划任务
membridge mcp                   # 启动 MCP server（Claude Code / Cursor / VS Code 等）
membridge gateway               # 手机 / 平板接入网关（基站模式，口令保护）
membridge gateway-token         # 显示网关访问口令（首次自动生成并托管）
```

### 口令

```bash
membridge show-passphrase       # 查看本机托管的同步口令（默认只显示指纹）
membridge set-passphrase        # 手动设置 / 修改同步口令（通常无需：init 会自动生成）
```

## 工作流约定

- **内容冻结**：写入时忠实记录用户原意，记忆桥永远不会改写已有记忆。
- **少而准**：只记有长期价值的信息，不要把一次性细节塞进记忆。
- **隐私**：含密码/密钥/证件的内容不要写入（系统会自动标记为 local，永不跨设备）。
- **同步节奏**：每次会话开始与结束各跑一次 `membridge sync --dir "<通道目录>"`——
  各端共享记忆靠这一步兑现，不要等自动任务。
- **秘密纪律**：口令 / 令牌 / 密钥永不打印、永不写进聊天或记忆；需要核对时只报指纹
  （`membridge channel` 只给通道密钥指纹，`show-passphrase` 默认掩码）。
- **体检优先**：说"记住了"之前可以先 `membridge search` 证实一次；说"同步好了"之前
  先 `membridge stats` 或 `membridge channel` 看事实。
- 命令失败（如 membridge 未安装）时，告知用户运行 `pip install membridge` 并 `membridge init`。
"""
