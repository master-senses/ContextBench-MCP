# ContextBench-MCP

Benchmark harness measuring how **MCP tool schema serialization** affects **agent tool-selection accuracy** and **token cost**.

# UPDATE: I JUST REALISED THAT WHEN I PASS IN TOOLS TO THE AGENT IT RESERIALISES IT, SO THIS CONCEPT DOES NOT WORK. HAHA. YOU LIVE AND YOU LEARN!

Existing benchmarks like [MCPMark](https://github.com/eval-sys/mcpmark) and [MCP-Bench](https://github.com/Accenture/mcp-bench) ask: *can an agent complete multi-step MCP workflows?*

ContextBench-MCP asks a narrower, complementary question:

> **Given the same MCP tools and the same user intent, does schema encoding change which tool the agent picks — and at what token cost?**

## Core hypothesis

Tool schemas are a hidden tax on agent context. Serialization strategy (JSON, TOON, compressed, progressive disclosure) should be evaluated on **selection accuracy**, not token savings alone.

## V1 scope

### What we benchmark

**Tool selection** — not full task execution.

Each benchmark case is:

```
(fixture, encoding strategy, user prompt) → agent picks a tool → verify correct tool
```

Example: *"User wants to open a pull request on repo X"* → expect `create_pull_request`, not `list_issues`.

Optional **phase 2**: arg-filling after correct tool selection (same fixture, same encoding).

End-to-end dev tasks (commit, fetch URL, write files) are **out of scope for v1** — that's MCPMark territory.

### Fixtures

Real MCP server tool surfaces, serialized from the same source:


| Fixture                                         | Why                                                  |
| ----------------------------------------------- | ---------------------------------------------------- |
| **GitHub MCP**                                  | ~80 tools, known token bloat (~20K+ schema tokens) |
| **Filesystem MCP**                              | Smaller, baseline comparison                         |
| **Fetch / Git MCP**                             | Medium-sized, mixed read/action tool names           |


Goal: test at **N = 5, 20, 50, 80+** tools to see where compression matters most.

### Encoding strategies

Same tools, different presentation. Strategies fall into three layers (combinable where noted):

**Layer 1 — serialization format (same semantic schema)**

1. **JSON (pretty)** — full schemas, indented with newlines (typical MCP / `tools/list` dumps)
2. **JSON (minified)** — full schemas, no insignificant whitespace (`separators=(",", ":")`)
3. **TOON** — full schemas encoded as [TOON](https://github.com/toon-format/toon)

Pretty vs minified JSON is a controlled experiment: **identical fields and descriptions**, only whitespace differs. Tokenizers often charge heavily for newlines and indentation on large tool sets — this isolates that effect before comparing TOON or compression.

**Layer 2 — semantic compression (still JSON unless noted)**

1. **Compressed JSON** — strip verbose descriptions, deduplicate shared params (`$ref`-style); default to **minified** unless a run explicitly tests pretty compressed
2. **TOON compressed** *(optional)* — same stripping as (4), TOON-encoded

**Layer 3 — progressive disclosure**

1. **Index-only + lazy schema** — name + one-line description in context; agent calls `get_tool_schema(name)` before invoking (index can be pretty JSON, minified JSON, or TOON — recorded per run)

Progressive disclosure is both a **serving pattern** and an **encoding strategy** — we measure it alongside format swaps.

### Selection prompts (~50–100 for v1)

Natural-language intents mapped to a gold-standard tool per fixture:

- Unambiguous: *"Create a new branch called feature-x"*
- Ambiguous (harder): *"I need to see what changed in the repo lately"*
- Distractor-heavy: fixture includes 3 similar tools (e.g. `create_pr`, `create_issue`, `create_branch`)

Each prompt includes: `prompt`, `fixture`, `gold_tool`, `acceptable_alternatives` (optional).

### Metrics


| Metric                           | Purpose                                                                     |
| -------------------------------- | --------------------------------------------------------------------------- |
| **Schema prompt tokens**         | Token cost of tool context for this encoding                                |
| **Pass@1**                       | Correct tool on first attempt                                               |
| **Pass@3**                       | Correct tool within 3 attempts — measures recovery when first pick is wrong |
| **Misselection rate**            | Which wrong tools get picked (confusion matrix)                             |
| **Tokens-to-first-correct-tool** | Cost including retries / schema fetches                                     |


**Why Pass@3?** Agents often recover on retry. A strategy that saves 50% tokens but drops Pass@1 from 90% → 70% might still be fine if Pass@3 stays at 95%. Pass@3 captures the *practical* DX tradeoff — especially for progressive disclosure where the first turn might be a schema lookup, not a tool call.

### Example output (target)


| Strategy                   | Schema tokens | Pass@1 | Pass@3 | Avg tokens to correct |
| -------------------------- | ------------- | ------ | ------ | --------------------- |
| JSON (pretty)              | 20,444        | 82%    | 94%    | 21,200                |
| JSON (minified)            | 16,800        | 82%    | 94%    | 17,500                |
| Compressed JSON (minified) | 4,900         | 80%    | 93%    | 5,400                 |
| TOON                       | 4,200         | 79%    | 92%    | 4,800                 |
| Index-only + lazy schema   | 520           | 68%    | 91%    | 2,100                 |


*(Illustrative — real numbers TBD)*

The interesting result to publish: *"index-only + lazy schema reduced prompt tokens 52% with no drop in Pass@3 on selection tasks."*

### Planned repo layout

```
ContextBench-MCP/
├── fixtures/           # MCP tool surfaces per server (raw JSON)
├── prompts/            # Selection prompts + gold labels
├── scripts/            # capture_fixture, run_selection (LiteLLM harness)
├── results/            # Eval output JSON (gitignored)
└── report/             # Pareto charts + comparison tables (planned)
```

### Out of scope for v1

- Full multi-step task execution (see MCPMark)
- 28-server coverage (see MCP-Bench)
- Multi-model leaderboard (pick one model, nail methodology first)
- Tool output / response compression (planned — same harness, different layer)

## V2 ideas

- **Arg-filling benchmark** — correct tool + valid args
- **Tool output encoding** — TOON/compressed responses, not just schemas
- **Multi-server fixtures** — filesystem + git + github combined
- End-to-end task slice (small) to test whether selection gains transfer to completion

## Positioning

> MCPMark asks whether agents can complete dev tasks. ContextBench asks whether we're wasting half the context window on tool schemas — and whether compression is free or costs accuracy. Pass@3 tells you whether agents recover.

## Status

🚧 Early scaffolding — README only. Harness implementation in progress.

## License

MIT
