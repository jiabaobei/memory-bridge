# 移动端接入指南（手机 / 平板）

PC 与笔记本之间走**网盘差分包**互相同步（`publish` / `fetch` / `autosync`）。
手机与平板无法复用这条路——网盘 App 没有"本地同步文件夹"，iOS 跑不了
Python。因此移动端有两条独立的路线：

| | 路线 A：基站模式（推荐） | 路线 B：Android 完整节点 |
|---|---|---|
| 覆盖 | iOS + Android + 平板 | 仅 Android（Termux） |
| 原理 | 手机是瘦客户端，读写家里常开设备上的记忆库 | 手机自己一份库，差分包同步 |
| 上手难度 | 低（浏览器 / 快捷指令） | 高 |
| 离线可用 | 需能连上基站 | ✅ |

---

## 路线 A：基站模式（`membridge gateway`，v0.11）

在一台家里常开的设备（比如 PC）上启动网关，手机通过 HTTP 读写这台
设备上的记忆库——通勤路上记一笔，回到家所有设备都记得。

### 1. 在基站上启动

```bash
membridge gateway              # 默认 0.0.0.0:8766，口令自动生成并托管
```

启动后显示局域网地址与访问口令；口令也可随时查看：

```bash
membridge gateway-token
```

### 2. 手机端三种接法

**方式一：内置页面（最简单）**
手机浏览器打开 `http://<基站IP>:8766/`，输入口令，就是「随身记」页面：
记一笔 / 找记忆两个动作。iOS / Android 都可以"添加到主屏幕"，像一个
小 App。

**方式二：iOS 快捷指令（锁屏一键记）**
新建快捷指令：
1. 「请求输入」→ 输入要记住的话；
2. 「获取 URL 内容」：方法 POST，URL 填 `http://<基站IP>:8766/add`；
   请求头加两条：`Authorization: Bearer <口令>`、`Content-Type: application/json`；
   请求体选 JSON：`{"text": "提供的输入"}`；
3. 把快捷指令加到锁屏 / 主屏幕，想到什么一键就存。

找记忆同理：URL 换成 `/search`，请求体 `{"query": "提供的输入", "as_context": true}`。

**方式三：任意自动化客户端**
Android 的 Tasker / HTTP 快捷方式类 App、任何能发请求的脚本，接口同下。

### 3. 接口

所有请求都要带鉴权：请求头 `Authorization: Bearer <口令>`（或
`X-Membridge-Token: <口令>`，或 URL 参数 `?token=<口令>`）。

| 接口 | 方法 | 请求体 | 返回 |
|---|---|---|---|
| `/health` | GET | — | `{"ok":true,"device":...,"nodes":n}` |
| `/add` | POST | `{"text":"...","tags":"","kind":"","migration":""}` | `{"ok":true,"node_id":"..."}` |
| `/search` | POST | `{"query":"...","k":5,"as_context":false}` | 命中列表；`as_context=true` 返回可注入的记忆块（沉默契约同样生效） |
| `/preload` | POST | `{"k":8}` | 热度预加载候选 |
| `/` | GET | — | 内置随身记页面 |

### 4. 出门在外（跨网络）

**只推荐一种做法：Tailscale 组网**（免费、自持、端到端加密）——基站与
手机装同一 tailnet，手机直接访问基站的 Tailscale IP，与在家局域网无异。

⚠️ **绝不做**：把明文端口映射到公网。确需公网可达时，用
`membridge gateway --cert server.crt --key server.key` 启用 TLS。

---

## 路线 B：Android 完整节点（Termux，进阶）

手机作为平等节点持有自己的一份记忆库，与基站互发差分包。适合离线需求
强、爱折腾的用户。

```bash
# Termux 内
pkg install python git
git clone https://github.com/jiabaobei/memory-bridge.git
cd memory-bridge && pip install -e .

membridge add "手机上记的第一条"     # 库默认在 ~/.membridge/memory.db
membridge search "..."
```

同步通道（手机没有文件夹同步客户端，用 rclone 把网盘挂成目录）：

```bash
pkg install rclone
rclone config                      # 配好 OneDrive / 坚果云等
rclone mount 远端名:membridge ~/netdisk-membridge --daemon

membridge publish --dir ~/netdisk-membridge --passphrase <与基站一致的口令>
membridge fetch   --dir ~/netdisk-membridge --passphrase <同上>
```

基站侧把同一个网盘目录用于 `fetch` / `publish`，两端即完成双向同步
（差分包默认端到端加密，口令一致才能解）。

> 已知限制：`autosync` 的计划任务注册是 Windows 专属；Termux 里请用
> `crond`（`pkg install cronie`）定时跑 `membridge publish/fetch`。
> iOS 无 Termux 等价物，走路线 A。

---

## 进阶配方：旧手机当 24 小时记忆基站

路线 A 默认"家里一台常开的设备"当基站——但没人愿意 24 小时开 PC。
抽屉里的旧 Android 手机才是天然的低功耗常开服务器（整机功耗约 5–10 瓦，
自带电池天然就是 UPS）。开源项目 OlliteRT（旧手机跑本地大模型的服务端
App）已经验证了这个形态可以常年稳定运行，记忆基站同理：

```bash
# 旧手机装 Termux 后（配好充电线，放在通风处）
pkg install python git
git clone https://github.com/jiabaobei/memory-bridge.git
cd memory-bridge && pip install -e .

membridge gateway --allow 192.168.1.    # 只允许家庭局域网段
# 记下打印的地址与口令；全家手机 / 平板 / PC 都接这台
```

要点：

- 用 `--allow` 把来源锁在家庭网段（或 Tailscale 网段 `100.64.`），
  口令 + 白名单双保险；
- Termux 设置里关闭电池优化 / 允许后台运行，避免系统杀进程；
- **常开充电 + 散热**：垫高或贴散热片，别压在枕头、被子里——
  老化电池长期高温有鼓包风险（这是 OlliteRT 作者也特意叮嘱过的）；
- 这台旧手机同时可以是路线 B 的完整节点：`publish/fetch` 与 PC 的
  网盘通道照常跑，基站与节点两个身份互不冲突。

## 进阶配方：membridge × OlliteRT —— 端侧个人 AI 全栈

Ornith-1.5 的 9B 量化版（约 1.5GB）已能在手机上直接运行，OlliteRT
则把"手机当局域网模型服务器"做成了开箱即用的 App。两者与记忆桥拼起来，
是一部旧手机的完整形态：

| 服务 | 角色 | 项目 |
|---|---|---|
| 本地模型（Gemma 4 E2B 等） | 推理 / 对话 | OlliteRT（OpenAI 兼容 API） |
| 记忆层 | 跨设备记忆共享 | membridge gateway |

**模型归模型，记忆归记忆**：OlliteRT 提供的是宿主侧智能（你的 AI
助手），记忆桥提供的是记忆底座——两者只共享同一台硬件与同一个局域网，
记忆桥的核心链路不会因此引入任何 LLM 调用（服务端零 LLM 是架构承诺，
见 README「领域收敛」）。这样你得到的是一个完全自持、零云端的个人
AI 栈：推理不出家门，记忆不出家门。

---

## 隐私边界

- 路线 A 的网关**只在你自己的设备上运行**，记忆不经过任何第三方；
  口令错误一律 401。
- 路线 B 的差分包默认端到端加密（网盘只见密文）。
- 两条路线都遵守同一套 PAMS 门控：`migration=local` 的记忆永不离开
  原设备——基站网关也查不到别的设备上标为 local 的内容之外的任何东西，
  因为它读的就是基站本机的那份库。
