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

## Status (v0.8)

| Capability | Status |
|---|---|
| **Incremental edge building** — on write, only the new node is paired against existing nodes (O(n), no more full O(n²) recompute per add); `membridge rebuild-edges` is the explicit full-rebuild exit | ✅ v0.8 |
| **Engineering robustness** — SQLite WAL concurrency + single atomic transaction (add + edge building, delta apply); delta packets split into "data error → skip" vs "environment error → kept for retry" | ✅ v0.8 |
| **Token economy** — MCP tools consolidated to 3 (`memory_context` merged into `memory_search`), retrieval relative-threshold filters weak hits, oversized memories get a soft "one sentence per memory" hint on write | ✅ v0.8 |
| **doctor location health** — warns when the DB sits in a temp/generated directory, when the default DB and the env-var DB coexist (likely a split store), or when the device name is unset | ✅ v0.8 |
| **Storage & retrieval** — embeddings stored as float32 BLOBs (⅓–⅕ of the JSON size, legacy DBs auto-migrate on open); two-phase search with an in-process vector cache | ✅ v0.8 |
| One-command setup — `membridge init`: mandatory cloud channel (auto-picked by priority rule), **sync passphrase auto-generated & vaulted (DPAPI)**, scheduled auto-sync every 15 min, platform auto-config + WorkBuddy skill install | ✅ implemented |
| Auto-sync engine — important memories upload immediately, routine ones batched (≥5 or ≥24h), `local`-tagged never leave the device | ✅ implemented |
| SAN (semantic association network, `w_ij = λ·co-occurrence + (1−λ)·cosine`) | ✅ implemented |
| Path A injection (auditable context block) | ✅ implemented |
| MCP server (Add / Search / Preload only) + remote HTTP mode for Coze-class platforms | ✅ implemented |
| DSS delta sync (semantic fingerprints, ε quantization, **embedder-consistency handshake**) | ✅ implemented |
| Netdisk-folder transport (`--force` rebuilds a wiped channel) + end-to-end encryption | ✅ implemented |
| PAMS privacy gates (L1 migration tags + L2 scene domains) | ✅ implemented; L3 DP deferred |
| TMT heat & preloading (recency × frequency heuristic) | ✅ heuristic done; edge tiers in Phase 3 |
| Portable `membridge.exe` (ncnn-style per-platform binaries) | ✅ v0.4 |
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
membridge init                                      # cloud channel (auto-picked) + passphrase
                                                    # (auto-generated & vaulted) + platform wiring
membridge add "Working on the MemoryBridge project" --tags dev
membridge search "MemoryBridge" -k 3
membridge context "continue this morning's discussion"
membridge preload my-phone
membridge autosync                                  # runs automatically every 15 min (scheduled task)
membridge show-passphrase                           # reveal vaulted passphrase when pairing a device
membridge delta phone.db --out delta.json
membridge apply delta.json
membridge publish --dir "D:/netdisk-sync/membridge" --passphrase my-secret
membridge publish --dir "D:/netdisk-sync/membridge" --force   # rebuild a wiped channel
membridge fetch   --dir "D:/netdisk-sync/membridge" --passphrase my-secret
membridge stats
membridge rebuild-edges                             # full rebuild of association edges (regular adds build incrementally)
membridge doctor                                    # env self-check (incl. DB location health)
```

The passphrase can also come from the `MEMBRIDGE_PASSPHRASE` environment variable.

**Recovering a lost channel.** `publish` only sends memories that are not yet marked
as published locally. If the delta packets are deleted on the cloud side (or a sync
failure empties the channel), the local record still says "published", so a plain
`publish` reports nothing to do. Use `--force` to rebuild the channel from scratch:

```bash
membridge publish --dir "..." --force
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

Tools exposed: `memory_add`, `memory_search` (`as_context=true` returns the Path A injection block directly), `memory_preload` — strictly limited to the UEP permission boundary; there is no "rewrite memory" tool.

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
