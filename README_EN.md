# MemoryBridge (记忆桥)

> 🌉 **Give your AI a memory that follows you** — a cross-device × cross-platform shared memory layer.
>
> The official engineering implementation of CDSMP (Cross-Device Semantic Memory Persistence).
> [中文文档](README.md) · [Design RFC](docs/RFC-001-architecture.md) · [Roadmap](docs/roadmap.md) · [Mobile guide](docs/mobile.md) · [Threat model](docs/threat-model.md) · [Changelog](CHANGELOG.md)

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
| Phones / tablets (gateway, "base-station" mode) | `membridge gateway`: browsers on iOS / Android / tablets (built-in pocket-note page, add-to-home-screen) and any HTTP client such as iOS Shortcuts; Android can also run a full node via Termux ([mobile guide](docs/mobile.md)) | ✅ v0.11 |
| Browser extension | Doubao, Kimi, ChatGPT web, … | 📋 |

## Status (v0.15)

| Capability | Status |
|---|---|
| **Shift handover (handover cards + workbench)** — a third memory kind `kind=handover`: when a task phase ends, the context runs low, or you're about to switch devices, write a handover card (line-prefix convention `goal:/done:/failed:/next:/refs:`; the `failed` line keeps the hard format "tried X; failed because Y; don't retry unless Z"). The newest non-stale card becomes the **workbench**, injected constantly — a state declaration, not a retrieval hit, so it skips relevance ranking and the silence contract; a new card automatically supersedes the old one (supersession is *derived*, zero new state — every device converges on the same card after sync); cards stale >7 days silently demote to ordinary memory (an outdated workbench is worse than none); handover-touched edges get a structural weight decay so a card can't become a super-hub; `membridge handoff` shows the workbench, `membridge handoff-hint` prints a resident reminder, and the pocket-note page ships a five-line card form | ✅ v0.15 |
| **Typed edges + evidence** — every edge carries a `kind` (semantic / cooccur / entity) plus a tiny `evidence` note, so every link answers "why are these two related?"; existing stores migrate on open (old edges labeled semantic) — structure only, content untouched | ✅ v0.14 |
| **Entity-anchor edges** — zero-dependency regex extraction of code symbols / file paths / repos / tags as deterministic anchors; memories sharing an anchor get linked — no reliance on literal coincidence, works across mixed Chinese-English phrasing | ✅ v0.14 |
| **Cluster preload** — `preload --cluster`: union-find splits memory into clusters and preloads the whole cluster around the hottest node — on a new device, the entire task-line context is already in place | ✅ v0.14 |
| **Recall-reason annotation** — `context` marks each line with a tiny hit path (vector / keyword / graph) so users can judge at a glance whether to trust a memory; `hybrid_search` stays a compatible thin wrapper | ✅ v0.14 |
| **Channel convergence (all devices point at the same cloud channel)** — a channel ID card `channel.json`: the first device creates it, every later device **auto-adopts** it at `init` / sync time; a split (local ID ≠ the ID card in the channel) warns loudly — first come, first served, the card is never rewritten; `membridge channel` shows the whole picture in one screen (local channel / ID card / devices seen in the channel); OneDrive multi-root detection (`OneDrive - Personal`-style variants); doctor channel-health warnings. **Pure metadata: no passphrase, never touches memory content** | ✅ v0.13 |
| **Gateway observability + IP allowlist** — what a resident base-station service needs to debug: uptime / request count / adds / searches / hits reported live by `/health` and shown in the pocket-note page; `--allow` admits clients by IP/prefix — token first, allowlist second | ✅ v0.12 |
| **Phone / tablet access** — `membridge gateway` (base-station mode): one always-on home device runs a token-protected HTTP gateway; phones read/write that device's store without holding a full copy (they only ever need Add / Search / Preload). Built-in pocket-note web page; iOS Shortcuts and any HTTP client work out of the box; pure stdlib, zero new dependencies. **A retired phone makes a fine 24/7 low-power base station (5–10 W)** and can pair with OlliteRT local models into a zero-cloud personal AI stack — see the [mobile guide](docs/mobile.md) | ✅ v0.11 |
| **Markdown export view** — `membridge export` renders the whole store as human-readable Markdown (grouped by scene, sectioned by fact/procedure, with device/time provenance): **a read-only view that never writes back** — memories become auditable, git-friendly, portable | ✅ v0.10 |
| **Resident recall hint** — `membridge recall-hint` prints a one-liner you may paste into CLAUDE.md / AGENTS.md: "recall before you answer" instead of "hope the agent remembers to search"; prints only, never edits host files | ✅ v0.10 |
| **Hybrid retrieval + RRF** — three recall routes (vector + keyword for exact-literal matches + one-hop SAN graph) fused by Reciprocal Rank Fusion (k=60): multi-route consensus wins, nothing to tune | ✅ v0.9 |
| **Budgeted injection + silence contract** — Path A blocks obey a token budget; the first over-budget entry is injected as a **prefix of the original text** (truncation ≠ rewriting — content freezing intact); when nothing passes the quality bar the tool says so ("no intervention this turn") instead of padding weak hits | ✅ v0.9 |
| **Slim MCP tool descriptions** — each of the 3 tool descriptions compressed to one line: descriptions live in every client session, so this is where token savings start | ✅ v0.9 |
| **Gap discovery** — zero-hit queries are logged locally (pure metadata) and surfaced by `doctor`: the system only reminds; what gets written is always the user's call | ✅ v0.9 |
| **Optional `kind` tagging** — `fact` (stable facts) / `procedure` (what was tried, what happened); strictly optional | ✅ v0.9 |
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

## How it differs from alternatives

| | MemoryBridge | OpenMemory (mem0) | MemGPT/Letta | memU |
|---|---|---|---|---|
| Cross-app sharing (MCP) | ✅ | ✅ | — | ✅ (host adapters) |
| **Cross-device sync** (phone↔PC↔edge) | ✅ core capability (E2E encrypted; the netdisk only ever sees ciphertext) | ❌ device-locked | ❌ | via its hosted cloud |
| **Preloading** before you switch (zero wait) | ✅ | ❌ passive retrieval | ❌ | ❌ |
| **Content freezing** (never rewrites memory) | ✅ architectural constraint | ❌ LLM summarization | partial | ❌ (LLM auto-distillation into the store) |
| Human-auditable memory | ✅ v0.10 Markdown export view | ❌ | ❌ | ✅ (Markdown as memory) |
| Privacy tiers (migration tags + scene domains) | ✅ | partial | ❌ | ❌ |

> memU deserves credit: its automatic skill distillation and zero-LLM backend
> are genuinely good. The fork is where memory content comes from — memU lets
> the LLM distill and *generate* it; MemoryBridge insists on explicit writes
> (`memory_add`), with experience captured via the `kind=procedure` convention
> below, so hallucinations never get a path into the store.

## Field convergence: external memory is getting backed by frontier research

MemoryBridge's three differentiators are not isolated design choices. In 2026,
frontier work converged on the same route from three independent directions:

- **Metis (Memory Foundation Model, arXiv 2607.26760)** compresses history into
  in-model parameters, but the paper itself concedes: fixed capacity must forget,
  and parametric state is **hard to audit, hard to delete precisely, and hard to
  bound for privacy** — and proposes a hybrid blueprint where low-frequency,
  auditable, long-horizon history stays in *external* storage, which provides
  capacity, explainable retrieval, and error correction. That is exactly
  MemoryBridge's niche: native memory is a complement, not a replacement.
- **Proactive Memory Agent (Meta, arXiv 2607.08716)** shows that long-horizon
  tasks fail not from missing information but from losing its grip on behavior;
  the fix is a keeper policy over an **external structured memory store**, and
  ablations show "silence as an action" beats always-exposing the store.
  MemoryBridge v0.9's silence contract and relative-threshold filtering are
  isomorphic to this.
- **Perplexity Portable Computer** (local agent, zero token cost) validates the
  "extreme token economy" principle — tiny system prompts, few core tools,
  on-demand loading — and its "sensitive content never leaves the device +
  explicit exit gating" matches the PAMS philosophy.

v0.9 is a borrowing release aligned with these three works (retrieval quality /
token economy / gap discovery), touching only the retrieval, injection, and
scheduling layers — **never rewriting memory content**. Item-by-item mapping and
the explicit not-borrowed list: [Roadmap, "Borrowing release"](docs/roadmap.md).

A fourth data point comes from the open-source project **memU**
(NevaMind-AI): it likewise insists on a **zero-LLM memory backend** — the
"what is worth remembering" judgment stays with the host agent while the
memory service only stores, embeds, and retrieves. That division of labor is
isomorphic to MemoryBridge's core. The fork is twofold: memU lets the LLM
distill and *generate* memory content (MemoryBridge refuses: content freezing),
and its cross-device story runs through its hosted cloud (MemoryBridge insists
on self-held E2E-encrypted channels). v0.10 borrows its "memory as files"
auditability (`membridge export`, a read-only view that never writes back) —
see [Roadmap, "memU borrowing release"](docs/roadmap.md).

**GitNexus** (abhigyanpatwari/GitNexus), a zero-server code knowledge-graph
engine, is the reference for v0.14. The useful insight is not "use a graph" —
MemoryBridge has had graph retrieval since v0.9 (vector + keyword + one-hop SAN
expansion, RRF-fused) — but that **a graph is only as good as the certainty of
its edges**: GitNexus derives edges from an AST, while MemoryBridge's came from
a statistical proxy (character n-gram co-occurrence). v0.14 therefore adds a
deterministic anchor layer: zero-dependency regex extraction of code symbols /
file paths / repos / tags (no AST, no parser, no new dependency), with memories
sharing an anchor linked by an `entity` edge — plus typed edges (`kind` +
`evidence`) so every link can answer "why are these related?". Its
`[[file:line]]` provenance becomes recall-reason annotations, and its community
detection becomes cluster preload (`preload --cluster`, union-find). Explicitly
**not** borrowed: graph databases (they would break the single-file promise),
full Tree-sitter AST parsing (memories are natural language, and it would break
zero dependencies), PDG / taint analysis, and post-commit auto-reindexing
(content freezing means there is no stale index to rebuild) — see
[Roadmap, "GitNexus borrowing release"](docs/roadmap.md).

A fifth data point comes from the **edge**: devices are becoming first-class AI
infrastructure. Ornith-1.5's 9B quantized build (~1.5 GB) runs directly on
phones; OlliteRT turns a retired Android phone into a 24/7 LAN model server.
Once a phone can host both the model and the service, MemoryBridge's
base-station mode supplies the missing piece — **memory**. One old phone
running OlliteRT (local inference) plus `membridge gateway` (the memory
substrate) is a fully self-held, zero-cloud personal AI stack (recipes in the
[mobile guide](docs/mobile.md)). The boundary stays sharp: the local model
lives on the host side; the memory core remains LLM-free.

A sixth data point comes from inside the **parametric camp**: Qualcomm AI
Research's MoNe (ICML 2026) bolts an online-writable neural memory onto a
**frozen** Transformer backbone — the context is written once, queries never
re-read it. Its architectural discipline is isomorphic to MemoryBridge's:
freeze the body, only the bolt-on is writable. The fork is where memory lives:
MoNe writes history into weights (parametric state), the very route Metis
concedes is hard to audit, hard to delete precisely, and hard to bound for
privacy; MemoryBridge keeps memory in human-auditable external storage.
**Freezing is the shared discipline of both camps — the only difference is
what gets frozen: they freeze the model, we freeze the content.**

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
                                                    # optional: --kind fact / procedure / handover
membridge search "MemoryBridge" -k 3              # hybrid: vector + keyword + graph, RRF-fused
                                                    # (--scope tag:dev to go straight to a known range)
membridge context "continue this morning's discussion"
                                                    # newest handover card injected constantly in a
                                                    # 【workbench】 section; explicit "no injection this
                                                    # turn" only when there is no card and no hit
membridge handoff                                 # show the current workbench (latest handover card)
membridge handoff-hint                            # print the resident handover reminder
membridge preload my-phone
membridge autosync                                  # runs automatically every 15 min (scheduled task)
membridge show-passphrase                           # reveal vaulted passphrase when pairing a device
membridge delta phone.db --out delta.json
membridge apply delta.json
membridge publish --dir "D:/netdisk-sync/membridge" --passphrase my-secret
membridge publish --dir "D:/netdisk-sync/membridge" --force   # rebuild a wiped channel
membridge fetch   --dir "D:/netdisk-sync/membridge" --passphrase my-secret
membridge stats
membridge channel                               # channel-convergence check: same cloud channel on all devices?
membridge gateway                               # phone/tablet gateway (base-station mode, token-protected)
membridge gateway-token                         # show the gateway access token (when configuring a phone)
membridge export                                # human-readable Markdown view (--out writes to disk)
membridge recall-hint                           # print the resident recall one-liner (paste it yourself)
membridge rebuild-edges                             # full rebuild of association edges (regular adds build incrementally)
membridge doctor                                    # env self-check (DB location + channel health + memory gaps)
```

The passphrase can also come from the `MEMBRIDGE_PASSPHRASE` environment variable.

**Experience-distillation convention (with `kind` tags).** When you solve a hard
problem, store the *experience* so future similar tasks hit it directly:

```bash
membridge add "arm64 deploys segfault; switching to the x86 image fixed it" --kind procedure --tags dev
```

`--kind procedure` = "what was tried, what happened"; `--kind fact` = stable
facts. Strictly optional — defaults are unchanged.

**Shift-handover convention (`kind=handover`, v0.15).** An agent's context is
finite, and long tasks survive by repeated compaction — which is lossy: "option
B was rejected" may survive the summary, but "why it was rejected" is usually
the first thing lost. MemoryBridge's answer: **the outgoing side writes one
handover card explicitly; the full history stays in the store, queryable at
any time.**

```bash
membridge add "goal: fix the sync module
done: delta computation landed
failed: full AST parsing; deps too heavy; don't retry unless we drop zero-deps
next: converge the line-prefix parser
refs: membridge/store.py" --kind handover
```

- Five-line convention `goal / done / failed / next / refs`; the card body is
  content-frozen; the `failed` line keeps the hard format: **tried X; failed
  because Y; don't retry unless Z changes**;
- A new card automatically supersedes the old one — the newest card *is* the
  workbench, older ones demote to history, still searchable and auditable,
  never deleted;
- At injection time the workbench is constantly present (it is a state
  declaration, not a retrieval hit, so the silence contract does not apply);
  all other retrieved memories keep their original contract;
- Cards stale >7 days stop being injected constantly (an outdated workbench is
  worse than none) and demote to ordinary memory; `membridge doctor` reminds
  you;
- `membridge handoff-hint` prints a resident reminder to paste into
  CLAUDE.md / AGENTS.md, so the host agent builds the habit of "hand over
  before you leave, read the workbench first when you arrive" (a soft
  contract, same philosophy as recall-hint).

> Phones don't need the command: the gateway pocket-note page ships a
> five-line handover form — fill it in, tap "交接班", done.

**Recovering a lost channel.** `publish` only sends memories that are not yet marked
as published locally. If the delta packets are deleted on the cloud side (or a sync
failure empties the channel), the local record still says "published", so a plain
`publish` reports nothing to do. Use `--force` to rebuild the channel from scratch:

```bash
membridge publish --dir "..." --force
```

**How multiple devices converge on the same channel (v0.13).** The channel's
identity lives **in the channel itself, not on each device** — adoption replaces
path-bookkeeping. All you do is point every device's channel folder at the **same
cloud-synced location** (e.g. `OneDrive/membridge` on all of them). Then:

- The **first device** writes a **channel ID card** `channel.json` into the
  channel directory on its first publish (channel ID / creator / creation time /
  embedder fingerprint) — **pure metadata: no passphrase, never any memory
  content**;
- **Every later device** detects the card at `membridge init` (or its first
  `publish`/`fetch`/`autosync`) and **auto-adopts** the same channel, printing
  "joined an existing channel (created by …)" — no path to remember, no config
  to copy;
- If a device is misconfigured to a *different* channel (its recorded channel ID
  disagrees with the card), `membridge channel` / `doctor` / `publish` / `fetch`
  / auto-sync all **warn loudly** (first come, first served — the card is never
  rewritten, so two devices can't clobber each other);
- `membridge channel` is the one-screen health check: local channel, the ID
  card, and every device seen in the channel.

> Phones / tablets don't need a channel at all — they join through the
> `membridge gateway` base-station mode ([mobile guide](docs/mobile.md)) and
> inherently point at that one store.

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

Tools exposed: `memory_add` (optional `kind` tag: fact / procedure / handover),
`memory_search` (hybrid three-route retrieval; optional `scope` for direct
access to a known range, e.g. `tag:dev`; `as_context=true` returns a budgeted
Path A injection block — the newest handover card is injected constantly in a
workbench section — and explicitly reports "no intervention" when there is no
card and nothing passes the quality bar), `memory_preload` — strictly limited
to the UEP permission boundary; there is no "rewrite memory" tool.

## Relationship to the paper

MemoryBridge implements the CDSMP architecture (v7 preprint, in Chinese). Components
deliberately deferred in the paper (Path B, AEE, L3 differential privacy, full UEP
benchmarking) are deferred in the same order here. The preprint is published on
Zenodo (full LaTeX source included): [DOI 10.5281/zenodo.22064641](https://doi.org/10.5281/zenodo.22064641).
Experimental figures cited from the
paper (e.g., TCR 94.7%, bandwidth −89%, token overhead −87.1%) are **paper-reported
values**; reproduction scripts ship in Phase 4.

```bibtex
@techreport{cdsmp2026,
  title  = {Cross-Device Semantic Memory Persistence: Zero-Cognitive-Overhead Inference via Edge Preloading and Multi-Level Hot Caching (CDSMP)},
  author = {Xian, Yujia},
  year   = {2026},
  doi    = {10.5281/zenodo.22064641},
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
