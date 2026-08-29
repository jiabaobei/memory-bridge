# MemoryBridge (记忆桥)

> 🌉 **Give your AI a memory that follows you** — a cross-device × cross-platform shared memory layer.
>
> The official engineering implementation of CDSMP (Cross-Device Semantic Memory Persistence).
> [中文文档](README.md) · [Design RFC](docs/RFC-001-architecture.md) · [Roadmap](docs/roadmap.md) · [Threat model](docs/threat-model.md) · [Changelog](CHANGELOG.md)

![Version](https://img.shields.io/github/v/release/jiabaobei/memory-bridge)

## The problem

You discuss a hard problem with your AI on the phone during the commute; back at your desk you want to continue on the PC — and today that means scrolling history, copy-pasting, and re-explaining everything.

Cloud full-sync is heavy and often unacceptable for privacy; RAG is passive retrieval that only kicks in *after* you switch; mainstream memory systems (Mem0, MemGPT/Letta, …) are effectively device-locked.

MemoryBridge takes a different position:

1. **Cross-device continuity** — memory follows the person, not the app. Devices share one semantic memory graph, synchronized with incremental delta packets, never full dumps.
2. **Edge preloading** — before you even open the new device, hot memories are already pushed there. Switching is continuous instead of "switch, then wait for retrieval".
3. **Content freezing** — MemoryBridge only extracts associations and tunes structural parameters; it **never rewrites your raw memory content**. Per the Faulty Memory line of research, letting an LLM auto-abstract/rewrite memory inevitably injects hallucinated distortion.

And it is **cross-platform**: via MCP, one memory store is shared by Claude Code, Cursor, Cline, and any MCP client. See the coverage matrix in the [Chinese README](README.md).

### Platform coverage

| Channel | Platforms | Status |
|---|---|---|
| `membridge init` auto-config (MCP) | ZCode, Claude Code, Claude Desktop, Cursor, Cline, Windsurf, VS Code (Copilot), Gemini CLI, Qwen Code | ✅ |
| init skill install (SKILL.md) | WorkBuddy (`~/.workbuddy/skills`), Claude skills dir | ✅ |
| Remote MCP (HTTP mode) | Coze and other remote-MCP platforms via `membridge mcp --http` | ✅ |
| Manual guides | ByteDance TRAE and UI-based MCP clients (init prints steps) | ✅ |
| Browser extension | Doubao, Kimi, ChatGPT web, … | 📋 |

## Status (v0.2)

| Capability | Status |
|---|---|
| One-command platform setup — `membridge init` auto-configures detected MCP clients and installs the WorkBuddy memory skill | ✅ implemented |
| SAN (semantic association network, `w_ij = λ·co-occurrence + (1−λ)·cosine`) | ✅ implemented |
| Path A injection (auditable context block) | ✅ implemented |
| MCP server (Add / Search / Preload only) | ✅ implemented |
| DSS delta sync (semantic fingerprints, edge-quantization ε=0.01) | ✅ implemented |
| Netdisk-folder transport | Point the publisher at any synced folder (Baidu Netdisk, Jianguoyun, OneDrive, USB, LAN share); delta packets are end-to-end encrypted by default — the provider only ever sees ciphertext | ✅ implemented |
| PAMS privacy gates (L1 migration tags + L2 scene domains) | ✅ implemented; L3 DP deferred |
| TMT heat & preloading (recency × frequency heuristic) | ✅ heuristic done; edge tiers in Phase 3 |
| AEE adaptive evolution (α / π_nav / θ_window) | 📋 Phase 4 (interfaces reserved) |
| Path B hidden-state fusion | 🧪 Phase 4 experimental branch |

## Quick start

```bash
git clone https://github.com/jiabaobei/memory-bridge.git
cd memory-bridge
pip install -e .
membridge init             # mandatory cloud-drive channel setup first (auto-detects installed
                           # sync clients, guides you to a free one otherwise; explicit confirm
                           # required to skip), then wires up every AI platform detected here
python examples/demo.py    # phone memories → delta packet → PC, in 90 seconds
```

CLI:

```bash
membridge init                                      # one-command platform setup
membridge add "Working on the MemoryBridge project" --tags dev
membridge search "MemoryBridge" -k 3
membridge context "continue this morning's discussion"
membridge preload my-phone
membridge delta phone.db --out delta.json
membridge apply delta.json
membridge publish --dir "D:/netdisk-sync/membridge" --passphrase my-secret
membridge fetch   --dir "D:/netdisk-sync/membridge" --passphrase my-secret
membridge doctor
```

MCP clients (Cursor `mcp.json`):

```json
{
  "mcpServers": {
    "memory-bridge": {
      "command": "membridge",
      "args": ["mcp"],
      "env": { "MEMBRIDGE_DB": "D:/mem/my.db", "MEMBRIDGE_DEVICE": "my-pc" }
    }
  }
}
```

Tools exposed: `memory_add`, `memory_search`, `memory_context`, `memory_preload` — strictly limited to the UEP permission boundary; there is no "rewrite memory" tool.

## Relationship to the paper

MemoryBridge implements the CDSMP architecture (v7 preprint, in Chinese). Components
deliberately deferred in the paper (Path B, AEE, L3 differential privacy, full UEP
benchmarking) are deferred in the same order here. Experimental figures cited from the
paper (e.g., TCR 94.7%, bandwidth −89%, token overhead −87.1%) are **paper-reported
values**; reproduction scripts ship in Phase 4.

```bibtex
@techreport{cdsmp2026,
  title  = {Cross-Device Semantic Memory Persistence: Zero-Cognitive-Overhead Inference via Edge Preloading and Multi-Level Hot Caching (CDSMP)},
  author = {Xian, Yujia},
  year   = {2026},
  note   = {Preprint v7}
}
```

## Privacy

Three standing commitments (see the [threat model](docs/threat-model.md)):

1. Memories tagged `local` **cannot** leave the device — enforced in code paths, not by policy.
2. Every sync/payload exits through PAMS L1/L2 gates; sensitive content is auto-downgraded to `local`.
3. The store is a single SQLite file per device: encrypt it, delete it, or take it with you.

## Contributing

```bash
pip install -e ".[dev]"   # or zero-install: python tests/run_tests.py
pytest -q
```

Good first areas: real embedding backends, mobile connectors, the sync relay, benchmark reproduction.

## License

[MIT](LICENSE)
