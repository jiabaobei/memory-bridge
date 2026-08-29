# Changelog

所有显著变更记录于此。格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)。

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
