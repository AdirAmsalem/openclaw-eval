# OpenClaw Eval Harness Spec (Decart-side)

## Summary

Build a **Decart-owned internal eval harness** around the existing `openclaw` CLI.

This is **not** a proposal to implement product code inside OpenClaw itself.

The harness should let us compare two or more variants of a workspace/config/model/prompt/skill setup against the same prompt set, while capturing:

- final answers
- tool calls / file reads
- injected workspace/bootstrap context
- token usage
- latency
- per-variant diffs

The immediate motivating use case is the workspace modularization test I just ran for `DecartAI/rene` PR #4:

- variant A = monolithic `TOOLS.md`
- variant B = slim `TOOLS.md` + modular `kb/*.md`
- desired questions = did accuracy stay the same, did default context shrink, and did the system actually switch to on-demand reads?

Today this is possible, but awkward. I had to manually create temporary workspaces, spin up temporary agents, force fresh runs, inspect transcripts to recover tool calls, look at `systemPromptReport` for injected files, and then clean everything up.

We should own a small internal harness for this workflow.

---

## Recommendation

### Where to implement it

**Implement v1 on our side**, in this workspace (or a small internal repo if it grows), not inside OpenClaw.

Recommended location:

- `automation/openclaw-eval/`

For runnable examples and copy-paste invocations, use `automation/openclaw-eval/README.md`.
This spec should stay focused on behavior, guarantees, and design intent.

Suggested v1 language/runtime:

- **Python**

Why Python for v1:

- quick to shell out to `openclaw`
- quick to parse JSON/JSONL artifacts
- quick to materialize temp directories
- quick to generate markdown/JSON reports
- lowest-friction path to a working internal tool

If the harness becomes important enough later, we can either:

1. keep evolving it as our own internal tool, or
2. upstream specific missing primitives to OpenClaw separately.

---

## Ownership boundary

### Our code should own

- prompt set handling
- variant definitions
- temp workspace preparation
- temp agent lifecycle
- run orchestration
- results collection
- reporting / diffs
- cleanup

### OpenClaw should remain

- the execution engine we call
- the thing that actually runs the agent/session/tooling logic

### Optional future upstream wishlist

If we repeatedly hit the same OpenClaw limitations, we can later request or contribute:

- cleaner temporary workspace override
- better first-class fresh-session eval runs
- easier export of traces / `systemPromptReport`

But those are **wishlist items**, not prerequisites for v1.

---

## Problem

OpenClaw currently makes it too hard to answer questions like:

- Did a prompt/bootstrap/config change improve or regress answers?
- Did a modularization actually reduce default prompt/context size?
- Did the model read the expected files on demand?
- Did a skill or tool-routing change alter behavior the way we intended?
- Did a model swap preserve correctness while reducing cost/latency?

The core friction points today are:

1. **No built-in eval workflow**
2. **No first-class pairwise comparison output**
3. **No easy trace/report packaging for experiments**
4. **Cleanup is manual unless we automate it ourselves**
5. **Some runtime behavior is subtle** (for example, changing shell cwd is not the same thing as changing injected workspace/bootstrap context)

These are good reasons for an internal harness, even if OpenClaw itself stays unchanged.

---

## Goals

### Primary goals

1. Make it easy to compare **variant A vs variant B** on the same prompt set.
2. Guarantee each run is **fresh and isolated enough** for the eval to be meaningful.
3. Capture not just answer text, but also:
   - tool calls
   - file reads
   - injected workspace/bootstrap files
   - token usage
   - latency
4. Produce a report that makes regressions obvious.
5. Make the workflow cheap enough to use for routine iteration.

### Secondary goals

1. Support more than 2 variants later.
2. Support optional grading/rubrics later.
3. Support CI/regression use later.

---

## Non-goals (v1)

- No OpenClaw code changes required
- No polished GUI
- No automatic LLM judge as a hard requirement
- No full benchmark marketplace / public leaderboard
- No broad distributed eval infra
- No attempt to solve every evaluation problem at once

v1 should be a **practical internal harness**.

---

## Recommended code layout

Current v1 layout:

```text
automation/openclaw-eval/
  README.md
  run.py
  report.py
  lib.py
  specs/
    openclaw-eval-system.md
```

### Rough responsibilities

- `run.py` → main CLI entrypoint / experiment orchestration
- `report.py` → markdown summaries from results JSON
- `lib.py` → prompt loading, variant parsing, workspace copying, CLI calls, and artifact helpers
- `README.md` → runnable examples / common invocations
- `specs/openclaw-eval-system.md` → design intent / guarantees / semantics

If the harness grows, we can split `lib.py` into narrower modules later (`prompts.py`, `workspace.py`, `artifacts.py`, etc.).

---

## Key use cases

### 1. Bootstrap/context experiments
Example: compare large monolithic `TOOLS.md` vs slim `TOOLS.md` + modular `kb/*.md`.

Questions answered:
- same accuracy?
- lower prompt cost?
- did on-demand reads happen?

### 2. Skill changes
Example: a skill file becomes more specific or less verbose.

Questions answered:
- did tool choice improve?
- did the skill get invoked when intended?
- did token use change?

### 3. Model swaps
Example: `gpt-5.4` vs another model alias.

Questions answered:
- same correctness?
- lower latency/cost?
- different retrieval/tooling behavior?

### 4. Safety/routing changes
Example: new allowlist/tool-routing/session behavior.

Questions answered:
- did the right tools get used?
- did answer quality regress?
- did unexpected reads/actions appear?

---

## Proposed UX

## CLI shape

V1 should be our own wrapper CLI, not a new OpenClaw subcommand.

Examples:

```bash
python3 automation/openclaw-eval/run.py \
  --variant old:/path/to/workspace-a \
  --variant new:/path/to/workspace-b \
  --prompts prompts.jsonl \
  --out results.json
```

```bash
python3 automation/openclaw-eval/report.py results.json
```

The README should carry the copy-paste recipes for common flows like `main` vs `pr`, model-vs-model comparisons, `--workspace-mode direct`, and debugging runs that keep artifacts.

If we want a nicer wrapper later, we can add a small shell shim or package entrypoint.

---

## Prompt set format

v1 should support **JSONL** and maybe simple Markdown.

### JSONL example

```jsonl
{"id":"q1","prompt":"can we get a recording by webrtc_sessionid or requestid?","tags":["platform","recordings"]}
{"id":"q2","prompt":"I need to publish something quickly and get a public/shareable URL. What should I use?","tags":["publishing","easl"]}
```

### Optional metadata fields

- `id`
- `prompt`
- `tags`
- `notes`
- `expectedContains` (lightweight heuristic checks)
- `source` (thread/issue/provenance)
- `grader` (future)

---

## Variant definition

In v1, a variant can specify:

- workspace path
- optional model override
- label

Current CLI form:

- `label:/abs/path`
- `label:/abs/path:model-id`

### Example

```bash
python3 automation/openclaw-eval/run.py \
  --variant old:/tmp/workspace-old \
  --variant new:/tmp/workspace-new:openai/gpt-5.4 \
  --prompts prompts.jsonl \
  --out results.json
```

Future structured form (if we want to add a config file later):

```json
{
  "variants": [
    {
      "id": "old",
      "workspace": "/tmp/workspace-old"
    },
    {
      "id": "new",
      "workspace": "/tmp/workspace-new",
      "model": "openai/gpt-5.4"
    }
  ]
}
```

---

## Execution model

For each prompt × variant:

1. Materialize a **temporary workspace** for that variant (if needed)
2. Create a **temporary agent** bound to that workspace
3. Run the prompt once in a **fresh isolated session**
4. Capture raw run artifacts
5. Tear down the temporary agent and temp workspace

### Important constraint

The harness must not silently reuse the main workspace/session bootstrap. That invalidates workspace/layout experiments.

This matters because current `sessions_spawn(..., cwd=...)` behavior does **not** by itself change the injected workspace bootstrap for Project Context. A real eval harness must explicitly manage the workspace it gives OpenClaw.

---

## Interaction with OpenClaw

The harness should use OpenClaw as-is:

- `openclaw agents add ...`
- `openclaw agent --agent ... --message ... --json`
- `openclaw agents delete ... --force`

The harness may additionally read:

- session transcripts
- JSON outputs
- `systemPromptReport`

The harness should avoid depending on fragile UI flows.

---

## Captured artifacts per run

Each run should save:

- `variantId`
- `promptId`
- `prompt`
- `status` (`ok` / `error` / `timeout`)
- final assistant text
- structured tool calls
- structured tool results metadata (at least tool name + outcome)
- full `systemPromptReport`
- injected workspace/bootstrap files list
- token usage
- latency
- session id / run id
- model/provider
- timestamps

### Nice-to-have extras

- transcript path
- stderr / warnings
- approval prompts encountered
- retry count

---

## Metrics

v1 report should compute at least:

### Answer/output metrics
- raw answer text
- optional heuristic pass/fail (`expectedContains` etc.)

### Context metrics
- total prompt/context tokens
- injected `TOOLS.md` chars
- injected bootstrap chars by file
- total bootstrap chars

### Retrieval behavior metrics
- number of `read` calls
- which files were read
- whether expected module files were read
- whether unnecessary large files were read

### Performance metrics
- latency per run
- average latency per variant
- token usage per run
- average token usage per variant

---

## Report format

`report.py` should produce:

### 1. Human-readable summary

Example:

- prompts: 6
- variants: old, new
- correctness: old 6/6, new 6/6
- avg prompt tokens: old X, new Y
- avg `TOOLS.md` injected chars: old 17726, new 1954
- read behavior: new read `PLATFORM.md`, `EASL.md`, `COREWEAVE.md`

### 2. Per-prompt diff

For each prompt:
- answer snippet by variant
- token/context delta
- file-read delta
- pass/fail or human-review-needed

### 3. Raw JSON artifact

A machine-readable result file for future analysis.

---

## Proposed architecture

### Module 1 — prompt/variant ingestion
Parses prompt sets and variant definitions.

### Module 2 — workspace materialization
Creates variant-specific temporary workspaces by:
- copying baseline files
- optionally applying patches
- optionally swapping config/model settings

### Module 3 — OpenClaw runner
Responsible for:
- creating temp agents
- invoking `openclaw agent --json`
- collecting command outputs

### Module 4 — artifact extraction
Pulls out:
- final text
- tool trace
- `systemPromptReport`
- usage / latency
- session ids / transcript paths

### Module 5 — report generation
Produces:
- raw JSON
- markdown summary
- per-prompt diffs

### Module 6 — cleanup
Ensures temp agents/workspaces are deleted even on partial failure.

---

## Suggested implementation phases

## Phase 1 — MVP harness

Deliver:
- `automation/openclaw-eval/run.py`
- `automation/openclaw-eval/report.py`
- pairwise variant comparison
- prompt set input
- fresh isolated runs via temp agents/workspaces
- raw JSON + markdown summary
- tool/file-read capture
- `systemPromptReport` capture
- auto cleanup

This phase is already useful.

## Phase 2 — better scoring

Add:
- `expectedContains` / regex checks
- lightweight pass/fail summaries
- optional human-review bucket

## Phase 3 — better ergonomics

Add:
- nicer wrapper command
- promptset helpers
- reusable presets
- compare multiple variants in one run

## Phase 4 — CI/regression workflows

Add:
- machine-readable exit codes
- thresholds (`fail if new avg prompt tokens > old by 20%`)
- thresholded correctness gates

---

## Acceptance criteria for MVP

A run is successful if I can:

1. point it at two workspace variants,
2. give it a prompt set,
3. run all prompts in fresh isolated sessions,
4. get back a report showing:
   - answer text
   - token/context deltas
   - injected file deltas
   - file-read/tool deltas,
5. and trust that no hidden reuse of the main session/workspace contaminated the result.

---

## Upstream OpenClaw wishlist (explicitly separate)

These are **not** part of v1, but would make the harness cleaner if available later:

1. first-class temporary workspace/bootstrap override
2. first-class eval/fresh-run mode
3. easy export of tool traces without transcript scraping
4. easy export of `systemPromptReport`
5. hidden ephemeral run contexts that do not create user-visible agent clutter

Again: these are optional future improvements, not requirements for starting.

---

## Open questions

1. Should the harness live permanently in this workspace, or move to a small internal repo if it grows?
2. How much transcript/tool-result payload should we keep by default?
3. Do we want built-in heuristic grading in MVP, or just raw artifacts + reporting?
4. Should CI support be part of the initial design, or a later layer?
5. Do we want prompt-set provenance fields to be mandatory for “real history” evals?

---

## Recommendation

Build this as a **small Decart-owned harness around OpenClaw**.

Start with:
- Python
- `automation/openclaw-eval/`
- pairwise comparisons
- temp workspaces + temp agents
- JSON + markdown output
- auto cleanup

That gets us the practical value fast, without depending on OpenClaw internals changing.
