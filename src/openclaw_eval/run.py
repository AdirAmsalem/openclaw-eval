from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from openclaw_eval.lib import (
    EvalError,
    Scenario,
    Setup,
    agent_session_transcript_path,
    basename_list,
    copy_workspace,
    extract_tool_calls,
    load_scenarios,
    make_agent_id,
    now_iso,
    parse_setup,
    read_files_from_tool_calls,
    run_command,
    safe_json_loads,
    workspace_root,
    write_json,
)
from openclaw_eval.report import render


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def extract_answer(data: dict[str, Any]) -> str:
    result = data.get("result") or {}
    payloads = result.get("payloads") or []
    texts = [p.get("text", "") for p in payloads if isinstance(p, dict) and p.get("text")]
    return "\n\n".join(texts).strip()


def maybe_print(verbose: bool, text: str) -> None:
    if verbose:
        print(text, file=sys.stderr, flush=True)


def materialize_workspace(setup: Setup, scenario_id: str, run_root: Path, workspace_mode: str) -> tuple[Path, bool]:
    if workspace_mode == "direct":
        return setup.workspace, False
    temp_parent = run_root / "tmp-workspaces"
    temp_parent.mkdir(parents=True, exist_ok=True)
    dest = Path(tempfile.mkdtemp(prefix=f"{setup.id}-{scenario_id}-", dir=str(temp_parent)))
    copy_workspace(setup.workspace, dest)
    return dest, True


def cleanup_agent(agent_id: str) -> None:
    run_command(["openclaw", "agents", "delete", agent_id, "--force"], check=False)


def _count_tools(tool_calls: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for call in tool_calls:
        name = call.get("name") or "unknown"
        counts[name] = counts.get(name, 0) + 1
    return counts


def evaluate_checks(scenario: Scenario, answer: str) -> list[dict[str, Any]]:
    return [check.evaluate(answer).to_dict() for check in scenario.checks]


def run_one(
    setup: Setup,
    scenario: Scenario,
    *,
    workspace_mode: str = "copy",
    thinking: str | None = None,
    agent_timeout: int = 600,
    keep_workspaces: bool = False,
    keep_agents_on_failure: bool = False,
    verbose: bool = False,
    run_root: Path,
) -> dict[str, Any]:
    agent_id = make_agent_id("oc-eval", setup.id, scenario.id)
    artifacts_dir = run_root / "artifacts" / scenario.id / setup.id
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    materialized_workspace, owns_workspace = materialize_workspace(setup, scenario.id, run_root, workspace_mode)
    session_id = None
    status = "ok"
    error = None
    raw_output = None
    start = time.monotonic()

    try:
        add_cmd = ["openclaw", "agents", "add", agent_id, "--workspace", str(materialized_workspace), "--non-interactive", "--json"]
        if setup.model:
            add_cmd += ["--model", setup.model]
        maybe_print(verbose, f"[{setup.id}:{scenario.id}] add agent {agent_id}")
        add_proc = run_command(add_cmd)
        add_json = safe_json_loads(add_proc.stdout)
        write_json(artifacts_dir / "agent-add.json", add_json)
        (artifacts_dir / "agent-add.stderr.txt").write_text(add_proc.stderr)

        agent_cmd = [
            "openclaw", "agent", "--agent", agent_id, "--message", scenario.prompt, "--json", "--timeout", str(agent_timeout),
        ]
        if thinking:
            agent_cmd += ["--thinking", thinking]
        maybe_print(verbose, f"[{setup.id}:{scenario.id}] run prompt")
        proc = run_command(agent_cmd, check=False, timeout=agent_timeout + 30)
        (artifacts_dir / "openclaw-agent.stdout.txt").write_text(proc.stdout)
        (artifacts_dir / "openclaw-agent.stderr.txt").write_text(proc.stderr)
        if proc.returncode != 0:
            raise EvalError(f"openclaw agent exited {proc.returncode}")
        raw_output = safe_json_loads(proc.stdout)
        write_json(artifacts_dir / "openclaw-result.json", raw_output)

        meta = ((raw_output.get("result") or {}).get("meta") or {})
        session_id = ((meta.get("agentMeta") or {}).get("sessionId"))
        if session_id:
            transcript_path = agent_session_transcript_path(agent_id, session_id)
            if transcript_path.exists():
                shutil.copy2(transcript_path, artifacts_dir / "session-transcript.jsonl")

    except Exception as exc:
        status = "error"
        error = str(exc)
        maybe_print(verbose, f"[{setup.id}:{scenario.id}] ERROR: {error}")
    finally:
        if not (status == "error" and keep_agents_on_failure):
            cleanup_agent(agent_id)
        if owns_workspace and not keep_workspaces:
            shutil.rmtree(materialized_workspace, ignore_errors=True)

    elapsed = round(time.monotonic() - start, 3)
    result_meta = ((raw_output or {}).get("result") or {}) if raw_output else {}
    meta = result_meta.get("meta") or {}
    agent_meta = meta.get("agentMeta") or {}
    tool_calls = extract_tool_calls(artifacts_dir / "session-transcript.jsonl")
    read_files = read_files_from_tool_calls(tool_calls)
    answer = extract_answer(raw_output or {}) if raw_output else ""

    return {
        "setupId": setup.id,
        "sourceWorkspace": str(setup.workspace),
        "materializedWorkspace": str(materialized_workspace),
        "workspaceMode": workspace_mode,
        "workspaceDeleted": owns_workspace and not keep_workspaces,
        "scenarioId": scenario.id,
        "prompt": scenario.prompt,
        "scenarioTags": scenario.tags,
        "scenarioSource": scenario.source,
        "status": status,
        "error": error,
        "agentId": agent_id,
        "sessionId": session_id,
        "model": setup.model or agent_meta.get("model"),
        "provider": agent_meta.get("modelProvider"),
        "latencySeconds": elapsed,
        "answer": answer,
        "checks": evaluate_checks(scenario, answer),
        "toolCalls": tool_calls,
        "toolCallCounts": _count_tools(tool_calls),
        "readFiles": read_files,
        "readBasenames": basename_list(read_files),
        "usage": agent_meta.get("usage"),
        "promptTokens": agent_meta.get("promptTokens"),
        "inputTokens": agent_meta.get("inputTokens"),
        "outputTokens": agent_meta.get("outputTokens"),
        "contextTokens": agent_meta.get("contextTokens"),
        "systemPromptReport": meta.get("systemPromptReport"),
        "artifactsDir": str(artifacts_dir),
        "stdoutPath": str(artifacts_dir / "openclaw-agent.stdout.txt"),
        "stderrPath": str(artifacts_dir / "openclaw-agent.stderr.txt"),
        "transcriptPath": str(artifacts_dir / "session-transcript.jsonl") if (artifacts_dir / "session-transcript.jsonl").exists() else None,
        "createdAt": now_iso(),
    }


def build_payload(
    *,
    setups: list[Setup],
    scenarios: list[Scenario],
    results: list[dict[str, Any]],
    run_root: Path,
    suite_file: str,
    workspace_mode: str,
    thinking: str | None,
    agent_timeout: int,
    started_at: str,
    failures: int,
) -> dict[str, Any]:
    return {
        "schemaVersion": 1,
        "tool": "openclaw-eval",
        "createdAt": started_at,
        "updatedAt": now_iso(),
        "suiteFile": suite_file,
        "outDir": str(run_root),
        "workspaceMode": workspace_mode,
        "thinking": thinking,
        "agentTimeoutSeconds": agent_timeout,
        "setups": [{"id": s.id, "workspace": str(s.workspace), "model": s.model} for s in setups],
        "scenarios": [
            {
                "id": sc.id, "prompt": sc.prompt, "tags": sc.tags,
                "notes": sc.notes, "source": sc.source,
                "checks": [{"type": c.type, "value": c.value} for c in sc.checks],
            }
            for sc in scenarios
        ],
        "summary": {
            "runCount": len(results),
            "failureCount": failures,
            "okCount": sum(1 for r in results if r.get("status") == "ok"),
        },
        "runs": results,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def cmd_run(args: argparse.Namespace) -> int:
    setups = [parse_setup(raw) for raw in args.setup]
    if len({s.id for s in setups}) != len(setups):
        raise EvalError("Setup ids must be unique")
    scenarios = load_scenarios(Path(args.suite))
    out_dir = Path(args.out).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    results_path = out_dir / "results.json"
    suite_file = str(Path(args.suite).expanduser().resolve())

    results: list[dict] = []
    failures = 0
    started_at = now_iso()

    for scenario in scenarios:
        for setup in setups:
            maybe_print(args.verbose, f"Running {setup.id}:{scenario.id}")
            run_result = run_one(
                setup, scenario,
                workspace_mode=args.workspace_mode, thinking=args.thinking,
                agent_timeout=args.agent_timeout, keep_workspaces=args.keep_workspaces,
                keep_agents_on_failure=args.keep_agents_on_failure,
                verbose=args.verbose, run_root=out_dir,
            )
            if run_result.get("status") != "ok":
                failures += 1
            results.append(run_result)
            _save(results_path, out_dir, setups, scenarios, results, suite_file, args, started_at, failures)
            if run_result.get("status") != "ok" and args.stop_on_error:
                print(results_path)
                print(f"runs={len(results)} failures={failures}")
                return 1

    _save(results_path, out_dir, setups, scenarios, results, suite_file, args, started_at, failures)
    print(results_path)
    print(f"runs={len(results)} failures={failures}")
    return 1 if failures else 0


def _save(
    results_path: Path, out_dir: Path, setups: list[Setup], scenarios: list[Scenario],
    results: list[dict[str, Any]], suite_file: str, args: argparse.Namespace,
    started_at: str, failures: int,
) -> None:
    payload = build_payload(
        setups=setups, scenarios=scenarios, results=results, run_root=out_dir,
        suite_file=suite_file, workspace_mode=args.workspace_mode,
        thinking=args.thinking, agent_timeout=args.agent_timeout,
        started_at=started_at, failures=failures,
    )
    write_json(results_path, payload)
    (out_dir / "summary.md").write_text(render(payload))


def cmd_report(args: argparse.Namespace) -> int:
    path = Path(args.results).expanduser().resolve()
    data = json.loads(path.read_text())
    report = render(data)
    if args.out:
        out_path = Path(args.out).expanduser().resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(report)
    else:
        print(report, end="")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="openclaw-eval", description="Compare OpenClaw setups on the same scenarios.")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("run", help="Run a scenario suite against one or more setups")
    p.add_argument("--setup", action="append", required=True, help="Setup as label:/abs/path or label:/abs/path:model")
    p.add_argument("--suite", required=True, help="Scenario suite file (.jsonl, .md, or .txt)")
    p.add_argument("--out", required=True, help="Output bundle directory")
    p.add_argument("--workspace-mode", choices=["copy", "direct"], default="copy")
    p.add_argument("--thinking", choices=["off", "minimal", "low", "medium", "high", "xhigh"])
    p.add_argument("--agent-timeout", type=int, default=600)
    p.add_argument("--keep-workspaces", action="store_true")
    p.add_argument("--keep-agents-on-failure", action="store_true")
    p.add_argument("--stop-on-error", action="store_true")
    p.add_argument("--verbose", action="store_true")

    p = sub.add_parser("report", help="Render a markdown report from results.json")
    p.add_argument("results", help="Path to results.json")
    p.add_argument("--out", help="Output markdown path; prints to stdout if omitted")

    args = parser.parse_args()
    if args.command == "run":
        return cmd_run(args)
    if args.command == "report":
        return cmd_report(args)
    return 1


def cli_entry() -> None:
    try:
        raise SystemExit(main())
    except EvalError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2)
