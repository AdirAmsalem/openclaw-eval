# openclaw-eval plan

This document is the full plan for turning the current internal `automation/openclaw-eval` scripts into a small, clean project with a public-facing README and a stable user surface.

The intended product is deliberately narrow:

> **Compare OpenClaw setups against the same scenario suite and make regressions obvious.**

It is **not** a generic model-eval platform, a HuggingFace dataset runner, or a broad provider/plugin ecosystem.

---

## 1. Goal

Build a simple eval tool that helps answer questions like:

- Did `main` regress relative to `pr`?
- Did a workspace/bootstrap change preserve answer quality while shrinking default context?
- Did a config/model/thinking change improve latency or cost?
- Did a skill/tool-routing change alter which files were read or which tools were used?

The core promise should be:

- same scenarios
- multiple named OpenClaw setups
- fresh isolated runs
- comparable artifacts
- simple reports

---

## 2. Product thesis

The project should feel like:

- **small**
- **opinionated**
- **easy to understand in one README**
- **tied to OpenClaw setups, not arbitrary model providers**

The value is not “look how extensible the framework is.”
The value is “I can compare two OpenClaw setups in 5 minutes and see what changed.”

### What this project is

- an eval harness around the existing `openclaw` CLI
- scenario-based comparison of named setups
- focused on answer quality, context size, file-read behavior, tool usage, latency, and artifacts
- usable locally, in PR review, and eventually in CI

### What this project is not

- not a general LLM benchmark lab
- not a HuggingFace dataset integration project
- not a model/provider adapter layer
- not a plugin marketplace
- not a hosted leaderboard/SaaS

That boundary should stay visible throughout the code and docs.

---

## 3. Decisions already made

These decisions came out of the thread and should be treated as product direction, not optional ideas.

### Keep the scope narrow

The tool is for evaluating **OpenClaw setups** against different inputs and scenarios.

### Do not add generic provider complexity

We should **not** build:

- model-provider adapters as a core concept
- HuggingFace adapters/dataset plumbing
- a broad plugin/extension system
- a generalized “bring any model / any dataset / any runtime” abstraction layer

If a model override exists at all, it is only because a model choice is part of an OpenClaw setup.

### Focus on setups, scenarios, and reports

The product surface should revolve around:

- **setup** — a named OpenClaw configuration/workspace to test
- **scenario** — a prompt + metadata + optional checks
- **run** — one scenario against one setup
- **report** — an aggregated view of all runs

---

## 4. Current state

We already have a strong internal starting point in:

```text
automation/openclaw-eval/
  README.md
  run.py
  report.py
  lib.py
  specs/openclaw-eval-system.md
```

### What already exists

- running prompt sets against multiple workspace variants
- temporary agent creation
- workspace copy/direct execution modes
- results JSON output
- markdown report generation
- tool-call and file-read extraction from transcripts
- `systemPromptReport` capture
- per-run artifacts

### What is still internal / rough

- docs are written from an internal Decart perspective
- naming still says `variant` / `prompts` instead of a more product-shaped public surface
- paths are hard-coded to the local Decart workspace layout in a few places
- output shape is useful but not yet positioned as a stable public API
- checks/scoring are still minimal
- packaging/install story does not exist yet
- there are no polished examples/tests/release mechanics yet

---

## 5. Future-state product definition

### 5.1 Project identity

Repository/package name:

- `openclaw-eval`

Tagline:

- **Compare OpenClaw setups on the same scenarios.**

Core message:

- “This is the simplest way to answer: did this OpenClaw change help, hurt, or just change behavior?”

---

### 5.2 Primary use cases

### A. `main` vs `pr`

Compare two worktrees or copies of a workspace on the same suite.

### B. bootstrap/context changes

Example:

- old monolithic workspace docs
- new modular workspace docs

Measure:

- answer quality
- token/context changes
- file-read behavior

### C. config/model/thinking changes inside OpenClaw

Compare different OpenClaw setup parameters without turning the tool into a general provider framework.

### D. regression suites

Keep a small scenario suite for bugs or important workflows and rerun it after changes.

---

### 5.3 Explicit non-goals

These should be called out in the README and kept out of v1:

- model marketplace integrations
- HuggingFace dataset downloads/browsing
- arbitrary external eval backends
- LLM judge orchestration as the center of the product
- distributed workers / hosted control plane
- broad “framework for anything” abstractions

If we ever add those later, they should be separate layers, not the identity of this project.

---

## 6. Public user surface

The public surface should be small and stable.

### 6.1 CLI

### `openclaw-eval run`

Purpose:

- run a scenario suite against one or more named setups
- write a full run bundle to an output directory

Proposed shape:

```bash
openclaw-eval run \
  --setup main:/abs/path/to/workspace-main \
  --setup pr:/abs/path/to/workspace-pr \
  --suite /abs/path/to/scenarios.jsonl \
  --out runs/main-vs-pr
```

Proposed v1 flags:

- `--setup <id:/abs/path>`
- `--setup <id:/abs/path:model>`
- `--suite <path>`
- `--out <dir>`
- `--workspace-mode copy|direct`
- `--thinking off|minimal|low|medium|high|xhigh`
- `--agent-timeout <seconds>`
- `--keep-workspaces`
- `--keep-agents-on-failure`
- `--stop-on-error`
- `--verbose`

### `openclaw-eval report`

Purpose:

- render a markdown report again from an existing `results.json`

Proposed shape:

```bash
openclaw-eval report runs/main-vs-pr/results.json \
  --out runs/main-vs-pr/summary.md
```

Optional later:

- `--format md|json|html`

### Nice-to-have later, not v1

- `openclaw-eval init` to scaffold example suites
- `openclaw-eval diff` for focused pairwise summaries
- `openclaw-eval ci` / threshold checks

---

### 6.2 Core concepts

### Setup

A named OpenClaw target to evaluate.

Minimum fields:

- `id`
- `workspace`
- optional `model`

Possible later fields:

- env overrides
- config path
- notes

A setup is still an **OpenClaw setup**, not a generic provider.

### Scenario

A single evaluation case.

Minimum fields:

- `id`
- `prompt`

Optional fields:

- `tags`
- `notes`
- `source`
- `checks`

### Run

One scenario executed against one setup.

### Report

The aggregated results across all runs.

---

## 6.3 Scenario file format

Use **JSONL** in v1.

Why JSONL:

- easy to author
- easy to diff
- easy to stream/append
- easy to generate from scripts

### Proposed scenario example

```jsonl
{"id":"publish-url","prompt":"What should I use to publish something quickly and get a public URL?","tags":["publishing"],"checks":[{"type":"contains","value":"easl"}]}
{"id":"compare-pr","prompt":"How would I compare a PR branch against main with this harness?","tags":["evals"],"checks":[{"type":"contains","value":"worktree"}]}
```

### v1 check types

Keep checks intentionally simple:

- `contains`
- `not_contains`
- `manual`

Example:

```json
{"type":"contains","value":"easl"}
```

We can keep backward compatibility with the current internal `expectedContains` field during the transition.

---

## 6.4 Output bundle

Instead of writing only a single JSON file, future-state `run` should write a bundle directory:

```text
runs/main-vs-pr/
  results.json
  summary.md
  artifacts/
    publish-url/
      main/
        openclaw-result.json
        openclaw-agent.stdout.txt
        openclaw-agent.stderr.txt
        session-transcript.jsonl
      pr/
        ...
```

This is much easier to inspect and share.

### `results.json` should be the stable machine-readable API

Top-level fields:

- `schemaVersion`
- `tool`
- `createdAt`
- `updatedAt`
- `suiteFile`
- `outDir`
- `workspaceMode`
- `thinking`
- `agentTimeoutSeconds`
- `setups`
- `scenarios`
- `summary`
- `runs`

### Each run should include

- `setupId`
- `scenarioId`
- `status`
- `error`
- `answer`
- `checks`
- `latencySeconds`
- `usage`
- `promptTokens`
- `inputTokens`
- `outputTokens`
- `contextTokens`
- `toolCalls`
- `toolCallCounts`
- `readFiles`
- `readBasenames`
- `systemPromptReport`
- `artifactsDir`
- `stdoutPath`
- `stderrPath`
- `transcriptPath`
- `createdAt`

That output JSON is the “API” most integrators will actually care about.

---

## 6.5 Python API

We should expose a small Python API, but keep the CLI as the main interface.

Proposed surface:

```python
from openclaw_eval import Setup, Scenario, run_suite

report = run_suite(
    setups=[
        Setup(id="main", workspace="/abs/main"),
        Setup(id="pr", workspace="/abs/pr"),
    ],
    scenarios="scenarios.jsonl",
    out_dir="runs/main-vs-pr",
)

print(report.summary)
```

The Python API should be thin and map almost 1:1 to the CLI behavior.

---

## 7. What the README should communicate

The README should read like the project already exists and is usable.

It should answer, in order:

1. what the project does
2. what it does **not** do
3. how to install it
4. how to run the first comparison
5. what the scenario format looks like
6. what the output bundle contains
7. what the results JSON/API looks like
8. what problems it is good for

The README should feel:

- practical
- concrete
- small
- non-framework-y

It should not spend half its length on abstraction layers.

---

## 8. Gaps between current implementation and future-state README

To make the README true, we need to close these gaps.

### Gap 1 — packaging

Current:

- local scripts

Needed:

- package layout (`pyproject.toml`, entrypoints, installable CLI)

### Gap 2 — naming

Current:

- `variant`
- `prompts`

Wanted:

- `setup`
- `suite` / `scenario suite`

We can preserve current behavior internally first, then rename the public interface.

### Gap 3 — output model

Current:

- one results JSON file + optional report render

Wanted:

- bundle directory with `results.json`, `summary.md`, and `artifacts/`

### Gap 4 — checks API

Current:

- basic `expectedContains`

Wanted:

- small explicit `checks` API with simple types

### Gap 5 — hard-coded internals

Current:

- some Decart/OpenClaw path assumptions in `lib.py`

Wanted:

- all paths explicit or discoverable
- no Decart-specific filesystem assumptions

### Gap 6 — release quality

Current:

- no tests/fixtures/release story

Wanted:

- example suites
- snapshot tests / smoke tests
- CI
- license
- changelog/release notes

---

## 9. Implementation phases

### Phase 0 — freeze the product shape

Goal:

- agree on the narrow identity before changing code

Tasks:

- [ ] confirm project name: `openclaw-eval`
- [ ] confirm public concepts: `setup`, `scenario`, `run`, `report`
- [ ] confirm that provider/HF/plugin abstractions are explicitly out of scope
- [ ] confirm that `results.json` is the stable machine-readable API
- [ ] confirm whether `--out` should be a directory (recommended)

Deliverable:

- this plan
- future-state README

### Phase 1 — refactor current scripts into a package

Goal:

- turn the internal scripts into installable code without changing the core behavior too much

Tasks:

- [ ] add `pyproject.toml`
- [ ] move code into `src/openclaw_eval/`
- [ ] expose console scripts:
  - [ ] `openclaw-eval run`
  - [ ] `openclaw-eval report`
- [ ] keep thin compatibility wrappers for local development if useful
- [ ] replace hard-coded roots with explicit parameters or environment discovery
- [ ] add schema versioning to the output model intentionally

Deliverable:

- installable local package with working CLI

### Phase 2 — align the public interface

Goal:

- make the CLI and data model match the README

Tasks:

- [ ] rename `variant` → `setup` in the public surface
- [ ] rename `prompts` → `suite` / `scenarios`
- [ ] support `checks` in scenario files
- [ ] keep compatibility with `expectedContains` during transition
- [ ] change `--out` to produce a bundle directory
- [ ] write `summary.md` automatically after `run`
- [ ] make the JSON output fields consistent and documented

Deliverable:

- a coherent v1 user experience

### Phase 3 — report and artifact polish

Goal:

- make it easy to see regressions quickly

Tasks:

- [ ] improve summary sections
- [ ] show setup-level averages and failure counts
- [ ] show per-scenario comparisons clearly
- [ ] show check pass/fail summaries
- [ ] keep artifact paths easy to inspect
- [ ] optionally render a compact HTML report later

Deliverable:

- a report you can glance at and understand quickly

### Phase 4 — open-source hardening

Goal:

- make the project safe and credible to publish

Tasks:

- [ ] scrub Decart-specific wording from code/comments/docs where not essential
- [ ] verify there are no internal prompt/spec leaks in examples
- [ ] add example scenario suites
- [ ] add test fixtures and smoke tests
- [ ] add GitHub Actions / CI
- [ ] choose license (MIT or Apache-2.0)
- [ ] add CONTRIBUTING.md if needed
- [ ] add CHANGELOG / release process

Deliverable:

- repo is publishable and understandable to outsiders

### Phase 5 — optional CI/regression workflows

Goal:

- use the tool continuously, not just manually

Tasks:

- [ ] add threshold checks
- [ ] add `--fail-on-check-error`
- [ ] add exit codes suitable for CI
- [ ] add saved baseline comparisons
- [ ] add a documented PR-review workflow

Deliverable:

- good enough for automated regression gating when desired

---

## 10. Recommended repo structure

Target shape:

```text
openclaw-eval/
  README.md
  plan.md
  pyproject.toml
  LICENSE
  CHANGELOG.md
  examples/
    quickstart.jsonl
  src/
    openclaw_eval/
      __init__.py
      cli.py
      runner.py
      report.py
      models.py
      checks.py
      artifacts.py
  tests/
    test_cli.py
    test_report.py
    fixtures/
```

Notes:

- The current `run.py`, `report.py`, and `lib.py` map cleanly into this layout.
- `checks.py` should stay tiny in v1.
- We should avoid speculative modules for features we do not plan to ship.

---

## 11. Risks and mitigations

### Risk: the project becomes a framework instead of a tool

Mitigation:

- keep the README centered on 2–3 concrete workflows
- reject adapter/plugin work unless it clearly serves OpenClaw setup comparison

### Risk: public API drifts away from the actual implementation

Mitigation:

- make the README drive the CLI names early
- keep compatibility shims only temporarily

### Risk: open-sourcing exposes too much internal context

Mitigation:

- scrub examples and docs carefully
- use synthetic example suites
- review artifacts and sample outputs before publishing

### Risk: report complexity grows too fast

Mitigation:

- keep v1 report focused on answer, checks, latency, usage, reads, artifacts
- delay fancy scoring and HTML until after v1 is solid

---

## 12. Acceptance criteria

The plan is successful when an outsider can:

1. install `openclaw-eval`
2. point it at two OpenClaw setups
3. provide a small scenario suite
4. run one command
5. get a bundle with `results.json`, `summary.md`, and artifacts
6. understand from the README what the tool is for in under 5 minutes

And internally, we should be able to use it to answer:

- did this OpenClaw change help?
- did it regress?
- what changed in answers, reads, context, latency, or usage?

---

## 13. Bottom line

The right plan is **not** to build a broad extensible eval platform.

The right plan is to package and polish what we already have into a **small scenario-based OpenClaw comparison tool** with:

- a clean README
- a tiny CLI surface
- a stable `results.json` API
- understandable artifacts
- explicit non-goals

That is both more useful and much easier to open-source than a generalized framework.
