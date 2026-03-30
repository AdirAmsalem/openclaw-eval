# openclaw-eval

Compare **OpenClaw setups** against the same scenario suite.

`openclaw-eval` runs the same prompts against multiple named OpenClaw setups and produces a single report bundle with:

- final answers
- check results
- latency and token usage
- tool calls and file reads
- injected context metadata
- per-run artifacts for debugging

It is intentionally narrow.

- It **does** evaluate OpenClaw setups.
- It **does not** try to be a general LLM benchmark framework.
- It **does not** need model-provider adapters or HuggingFace dataset adapters.

If you want to answer “did this OpenClaw change help, hurt, or just change behavior?”, this is the tool.

---

## What you can compare

- `main` vs `pr`
- old workspace/bootstrap layout vs new layout
- config changes
- model/thinking changes **inside** OpenClaw
- skill/tool-routing changes
- bug/regression scenario suites

---

## Install

```bash
pip install openclaw-eval
```

Requirements:

- Python 3.11+
- `openclaw` installed and available in `PATH`
- local access to the workspaces/setups you want to compare

---

## Quick start

### 1. Create a scenario suite

`scenarios.jsonl`

```jsonl
{"id":"publish-url","prompt":"What should I use to publish something quickly and get a public URL?","tags":["publishing"],"checks":[{"type":"contains","value":"easl"}]}
{"id":"compare-pr","prompt":"How would I compare a PR branch against main with this harness?","tags":["evals"],"checks":[{"type":"contains","value":"worktree"}]}
```

### 2. Run the comparison

```bash
openclaw-eval run \
  --setup main:/abs/path/to/worktree-main \
  --setup pr:/abs/path/to/worktree-pr \
  --suite /abs/path/to/scenarios.jsonl \
  --out runs/main-vs-pr
```

### 3. Inspect the output bundle

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

### 4. Re-render the markdown report later

```bash
openclaw-eval report runs/main-vs-pr/results.json \
  --out runs/main-vs-pr/summary.md
```

---

## Core concepts

### Setup

A named OpenClaw target to evaluate.

A setup is usually:

- a workspace path
- an optional model override
- optional runtime settings

Examples:

- `main:/abs/path/to/worktree-main`
- `pr:/abs/path/to/worktree-pr`
- `gpt:/abs/path/to/worktree:openai/gpt-5.4`

### Scenario

One prompt plus optional metadata and checks.

### Run

One scenario executed against one setup.

### Report

The aggregated output across all runs, including summary stats and artifacts.

---

## CLI

### `openclaw-eval run`

Run a scenario suite against one or more setups.

```bash
openclaw-eval run \
  --setup main:/abs/path/to/worktree-main \
  --setup pr:/abs/path/to/worktree-pr \
  --suite /abs/path/to/scenarios.jsonl \
  --out runs/main-vs-pr
```

### Flags

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

### Notes

- `copy` mode is the default and is safer for isolation.
- `direct` mode is useful for fast local iteration when you are comfortable pointing OpenClaw at the workspace in place.
- each scenario × setup run gets a fresh temporary agent
- artifacts are kept per run for inspection and debugging

### `openclaw-eval report`

Render a markdown report from an existing results bundle.

```bash
openclaw-eval report runs/main-vs-pr/results.json \
  --out runs/main-vs-pr/summary.md
```

---

## Scenario format

v1 uses **JSONL**.

Each line is one scenario.

### Required fields

- `id`
- `prompt`

### Optional fields

- `tags`
- `notes`
- `source`
- `checks`

### Example

```jsonl
{"id":"publish-url","prompt":"What should I use to publish something quickly and get a public URL?","tags":["publishing"],"checks":[{"type":"contains","value":"easl"}]}
{"id":"coreweave-login","prompt":"What is the CoreWeave login node?","source":"ops-faq","checks":[{"type":"contains","value":"login.cw.rene"}]}
{"id":"manual-review","prompt":"Summarize the difference between these two approaches.","checks":[{"type":"manual"}]}
```

### Supported check types

#### `contains`

Passes if the final answer contains the provided string.

```json
{"type":"contains","value":"easl"}
```

#### `not_contains`

Passes if the final answer does not contain the provided string.

```json
{"type":"not_contains","value":"I don't know"}
```

#### `manual`

Marks the scenario for human review.

```json
{"type":"manual"}
```

---

## What gets captured

For every run, `openclaw-eval` captures:

- final assistant answer
- status / error
- latency
- token usage
- model/provider metadata
- tool calls
- file reads
- `systemPromptReport`
- stdout/stderr
- transcript path when available
- artifact directory

This makes it easy to answer not just “which answer was better?” but also:

- did context size change?
- did the agent read the expected files?
- did a skill change alter tool choice?
- did latency or token usage regress?

---

## Results JSON API

`results.json` is the stable machine-readable output.

### Top-level shape

```json
{
  "schemaVersion": 1,
  "tool": "openclaw-eval",
  "createdAt": "2026-03-30T00:00:00Z",
  "updatedAt": "2026-03-30T00:03:42Z",
  "suiteFile": "/abs/path/to/scenarios.jsonl",
  "outDir": "/abs/path/to/runs/main-vs-pr",
  "workspaceMode": "copy",
  "thinking": "minimal",
  "agentTimeoutSeconds": 600,
  "setups": [
    {
      "id": "main",
      "workspace": "/abs/path/to/worktree-main",
      "model": null
    },
    {
      "id": "pr",
      "workspace": "/abs/path/to/worktree-pr",
      "model": "openai/gpt-5.4"
    }
  ],
  "scenarios": [
    {
      "id": "publish-url",
      "prompt": "What should I use to publish something quickly and get a public URL?",
      "tags": ["publishing"],
      "checks": [{"type": "contains", "value": "easl"}]
    }
  ],
  "summary": {
    "runCount": 2,
    "okCount": 2,
    "failureCount": 0
  },
  "runs": []
}
```

### Run object

Each item in `runs` contains fields such as:

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

---

## Report contents

`summary.md` includes:

- run metadata
- summary by setup
- average latency and token usage
- per-scenario comparison
- answer snippets
- check results
- file-read summaries
- artifact locations

The goal is to make regressions obvious without opening raw JSON unless you want to.

---

## Python API

The CLI is the main interface, but the project also exposes a thin Python API.

```python
from openclaw_eval import Setup, run_suite

report = run_suite(
    setups=[
        Setup(id="main", workspace="/abs/path/to/worktree-main"),
        Setup(id="pr", workspace="/abs/path/to/worktree-pr"),
    ],
    scenarios="/abs/path/to/scenarios.jsonl",
    out_dir="runs/main-vs-pr",
)

print(report.summary)
```

The Python API maps closely to the CLI and writes the same output bundle.

---

## Typical workflows

### Compare `main` vs `pr`

```bash
openclaw-eval run \
  --setup main:/abs/path/to/worktree-main \
  --setup pr:/abs/path/to/worktree-pr \
  --suite /abs/path/to/scenarios.jsonl \
  --out runs/main-vs-pr
```

### Compare workspace/bootstrap layouts

```bash
openclaw-eval run \
  --setup monolith:/abs/path/to/workspace-monolith \
  --setup modular:/abs/path/to/workspace-modular \
  --suite /abs/path/to/context-scenarios.jsonl \
  --out runs/monolith-vs-modular
```

### Compare model/thinking choices inside the same workspace

```bash
openclaw-eval run \
  --setup gpt:/abs/path/to/workspace:openai/gpt-5.4 \
  --setup sonnet:/abs/path/to/workspace:anthropic/claude-sonnet-4-6 \
  --suite /abs/path/to/scenarios.jsonl \
  --thinking minimal \
  --out runs/gpt-vs-sonnet
```

### Keep workspaces and failed agents for debugging

```bash
openclaw-eval run \
  --setup main:/abs/path/to/worktree-main \
  --setup pr:/abs/path/to/worktree-pr \
  --suite /abs/path/to/scenarios.jsonl \
  --out runs/debug-main-vs-pr \
  --keep-workspaces \
  --keep-agents-on-failure \
  --verbose
```

---

## Why this tool stays simple

`openclaw-eval` is intentionally about **OpenClaw setup comparison**.

That means:

- no generic model-provider abstraction layer
- no HuggingFace dataset plumbing
- no plugin marketplace
- no “universal eval platform” ambitions

The simplicity is the feature.

You give it:

- setups
- scenarios
- one output directory

It gives you:

- comparable answers
- comparable artifacts
- a report you can actually use

---

## Project structure

```text
openclaw-eval/
  README.md
  plan.md
  src/openclaw_eval/
  examples/
  tests/
```

---

## License

Apache-2.0 or MIT.
