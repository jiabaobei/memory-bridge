# 设计借鉴：来自腾讯 ncnn 的工程实践

版本：v0.4.0（2026-08-29） · 参照项目：https://github.com/tencent/ncnn

ncnn 是面向移动端、嵌入式和桌面端的高性能推理框架。它与记忆桥共享同一种
气质：**零第三方依赖、随处可运行、为"边缘与普通设备"而生**。本文件记录
v0.4.0 从 ncnn 借鉴的实践及其落点。

## 借鉴映射表

| ncnn 的实践 | 记忆桥的落点 | 状态 |
|---|---|---|
| 无第三方运行时依赖，跑在任何设备上 | 核心保持纯标准库（v0 就已确立）；本次写进设计文档作为不可动摇项 | ✅ 一贯坚守 |
| param/bin 自描述分离：结构人类可读、带版本 | DSS 差分包升级为**自描述包**：内嵌 schema 演进位与 **embedder 自描述指纹**（type/name/dim/fp） | ✅ v0.4 |
| 运行时按 CPU 特性调度内核，旧设备优雅降级 | `capabilities.py` 运行时能力探测：嵌入器（OpenAI→哈希降级）、加密、向量索引、同步盘自动选择；`doctor` 直接展示能力画像 | ✅ v0.4 |
| Releases 提供各平台**免安装便携构建** | PyInstaller 打包便携 `membridge.exe`（membridge.spec / scripts/build_exe.bat），随 Release 分发；拷到任何 Windows 机器免 Python 使用 | ✅ v0.4 |
| pnnx 转换器生态（从训练框架转换而来） | 规划"记忆格式转换器"：从 ChatGPT/Claude/mem0 等导出格式导入既有记忆 | 📋 Phase 2+ |
| Volcano/Vulkan 多后端并行 | 暂无对应需求（Python 层无此瓶颈） | — |

## embedder 一致性握手（param 思想的关键落地）

跨设备同步的正确性前提是"两端向量可比"（RFC-001 §4）。v0.4 起：

1. 每个差分包携带 `embedder = {type, name, dim, fp}`（fp 为嵌入器身份摘要）；
2. 接收端 `apply_delta` 握手：本库已有记录且 fp 不同 → **拒绝应用**并返回原因；
3. 首次收到带指纹的包 → 记录到本库 meta；
4. 旧格式包（无 embedder 字段）向后兼容，照常应用。

自此，"用户在某台机器换了嵌入模型导致记忆语义漂移"这一类静默错误被
结构性排除——这与 ncnn 用自描述模型文件避免"权重与结构错配"是同一类防御。
