"""记忆技能模板：安装到支持 SKILL.md 约定的 agent 平台（WorkBuddy / Claude 技能目录等）。

单一事实来源：`membridge init` 从这里生成技能文件；
仓库内的 skills/memory-bridge/SKILL.md 与本常量保持一致。
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
   `membridge handoff-hint` 可打印完整版交接提示。

## 命令

```bash
# 写入一条记忆（内容保持用户原意，不要改写润色）
membridge add "<要记住的内容>" --tags <逗号分隔标签>

# 写一张交接卡（新卡自动取代旧卡）
membridge add "goal:…
done:…
failed:…
next:…
refs:…" --kind handover

# 查看当前工作台（最新交接卡与生效状态）
membridge handoff

# 语义检索最相关的 k 条
membridge search "<关键词>" -k 5

# 取出可直接注入 prompt 的记忆上下文块
membridge context "<主题>" -k 5

# 查看记忆库概况
membridge stats
```

## 工作流约定

- **内容冻结**：写入时忠实记录用户原意，记忆桥永远不会改写已有记忆。
- **少而准**：只记有长期价值的信息，不要把一次性细节塞进记忆。
- **隐私**：含密码/密钥/证件的内容不要写入（系统会自动标记为 local，永不跨设备）。
- 命令失败（如 membridge 未安装）时，告知用户运行 `pip install membridge` 并 `membridge init`。
"""
