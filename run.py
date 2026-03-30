#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from lib import (
    EvalError,
    Variant,
    agent_session_transcript_path,
    basename_list,
    copy_workspace,
    extract_tool_calls,
    heuristic_pass,
    load_prompts,
    make_agent_id,
    now_iso,
    parse_variant,
    read_files_from_tool_calls,
    run_command,
    safe_json_loads,
    write_json,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Run a Decart-owned eval harness around the openclaw CLI.')
    parser.add_argument('--variant', action='append', required=True, help='Variant as label:/abs/path or label:/abs/path:model')
    parser.add_argument('--prompts', required=True, help='Prompt file (.jsonl preferred; markdown/text line fallback supported)')
    parser.add_argument('--out', required=True, help='Output JSON path')
    parser.add_argument('--run-root', help='Root directory for artifacts; defaults under workspace/tmp/openclaw-eval-runs/')
    parser.add_argument('--workspace-mode', choices=['copy', 'direct'], default='copy', help='Copy each variant workspace per run (default) or use it directly')
    parser.add_argument('--thinking', choices=['off', 'minimal', 'low', 'medium', 'high', 'xhigh'], help='Pass through to openclaw agent')
    parser.add_argument('--agent-timeout', type=int, default=600, help='openclaw agent timeout in seconds (default: 600)')
    parser.add_argument('--keep-workspaces', action='store_true', help='Keep materialized temp workspaces after the run')
    parser.add_argument('--keep-agents-on-failure', action='store_true', help='Leave temp agents behind for debugging failed runs')
    parser.add_argument('--stop-on-error', action='store_true', help='Stop immediately on the first failed run')
    parser.add_argument('--verbose', action='store_true', help='Print per-run progress to stderr')
    return parser.parse_args()


def default_run_root() -> Path:
    ts = time.strftime('%Y%m%d-%H%M%S', time.gmtime())
    return Path('/home/ubuntu/.openclaw/workspace/tmp/openclaw-eval-runs') / ts


def render_variant(variant: Variant) -> dict[str, Any]:
    return {
        'id': variant.id,
        'workspace': str(variant.workspace),
        'model': variant.model,
    }


def extract_answer(data: dict[str, Any]) -> str:
    result = data.get('result') or {}
    payloads = result.get('payloads') or []
    texts = [payload.get('text', '') for payload in payloads if isinstance(payload, dict) and payload.get('text')]
    return '\n\n'.join(texts).strip()


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def maybe_print(verbose: bool, text: str) -> None:
    if verbose:
        print(text, file=sys.stderr, flush=True)


def materialize_workspace(variant: Variant, prompt_id: str, run_root: Path, workspace_mode: str) -> tuple[Path, bool]:
    if workspace_mode == 'direct':
        return variant.workspace, False
    temp_parent = run_root / 'tmp-workspaces'
    temp_parent.mkdir(parents=True, exist_ok=True)
    dest = Path(tempfile.mkdtemp(prefix=f'{variant.id}-{prompt_id}-', dir=str(temp_parent)))
    copy_workspace(variant.workspace, dest)
    return dest, True


def cleanup_agent(agent_id: str) -> None:
    run_command(['openclaw', 'agents', 'delete', agent_id, '--force'], check=False)


def run_one(variant: Variant, prompt, args: argparse.Namespace, run_root: Path) -> dict[str, Any]:
    agent_id = make_agent_id('oc-eval', variant.id, prompt.id)
    artifacts_dir = run_root / 'artifacts' / prompt.id / variant.id
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    materialized_workspace, owns_workspace = materialize_workspace(variant, prompt.id, run_root, args.workspace_mode)
    session_id = None
    status = 'ok'
    error = None
    raw_output = None
    stdout = ''
    stderr = ''
    start = time.monotonic()

    try:
        add_cmd = ['openclaw', 'agents', 'add', agent_id, '--workspace', str(materialized_workspace), '--non-interactive', '--json']
        if variant.model:
            add_cmd += ['--model', variant.model]
        maybe_print(args.verbose, f'[{variant.id}:{prompt.id}] add agent {agent_id}')
        add_proc = run_command(add_cmd)
        add_json = safe_json_loads(add_proc.stdout)
        write_json(artifacts_dir / 'agent-add.json', add_json)
        (artifacts_dir / 'agent-add.stderr.txt').write_text(add_proc.stderr)

        agent_cmd = [
            'openclaw', 'agent', '--agent', agent_id, '--message', prompt.prompt, '--json', '--timeout', str(args.agent_timeout)
        ]
        if args.thinking:
            agent_cmd += ['--thinking', args.thinking]
        maybe_print(args.verbose, f'[{variant.id}:{prompt.id}] run prompt')
        proc = run_command(agent_cmd, check=False, timeout=args.agent_timeout + 30)
        stdout = proc.stdout
        stderr = proc.stderr
        (artifacts_dir / 'openclaw-agent.stdout.txt').write_text(stdout)
        (artifacts_dir / 'openclaw-agent.stderr.txt').write_text(stderr)
        if proc.returncode != 0:
            raise EvalError(f'openclaw agent exited {proc.returncode}')
        raw_output = safe_json_loads(stdout)
        write_json(artifacts_dir / 'openclaw-result.json', raw_output)

        meta = ((raw_output.get('result') or {}).get('meta') or {})
        session_id = (((meta.get('agentMeta') or {}).get('sessionId')))
        if session_id:
            transcript_path = agent_session_transcript_path(agent_id, session_id)
            if transcript_path.exists():
                shutil.copy2(transcript_path, artifacts_dir / 'session-transcript.jsonl')

    except Exception as exc:  # noqa: BLE001
        status = 'error'
        error = str(exc)
        maybe_print(args.verbose, f'[{variant.id}:{prompt.id}] ERROR: {error}')
        if args.stop_on_error:
            raise
    finally:
        should_keep_agent = status == 'error' and args.keep_agents_on_failure
        if not should_keep_agent:
            cleanup_agent(agent_id)
        if owns_workspace and (not args.keep_workspaces):
            shutil.rmtree(materialized_workspace, ignore_errors=True)

    elapsed = round(time.monotonic() - start, 3)

    result_meta = ((raw_output or {}).get('result') or {}) if raw_output else {}
    meta = result_meta.get('meta') or {}
    system_prompt_report = meta.get('systemPromptReport')
    agent_meta = meta.get('agentMeta') or {}
    tool_calls = extract_tool_calls(artifacts_dir / 'session-transcript.jsonl')
    read_files = read_files_from_tool_calls(tool_calls)
    answer = extract_answer(raw_output or {}) if raw_output else ''
    heuristic = heuristic_pass(prompt, answer)

    return {
        'variantId': variant.id,
        'sourceWorkspace': str(variant.workspace),
        'materializedWorkspace': str(materialized_workspace),
        'workspaceMode': args.workspace_mode,
        'workspaceDeleted': owns_workspace and (not args.keep_workspaces),
        'promptId': prompt.id,
        'prompt': prompt.prompt,
        'promptTags': prompt.tags,
        'promptSource': prompt.source,
        'status': status,
        'error': error,
        'agentId': agent_id,
        'sessionId': session_id,
        'model': variant.model or agent_meta.get('model'),
        'provider': agent_meta.get('modelProvider'),
        'latencySeconds': elapsed,
        'answer': answer,
        'toolCalls': tool_calls,
        'toolCallCounts': _count_tools(tool_calls),
        'readFiles': read_files,
        'readBasenames': basename_list(read_files),
        'heuristic': heuristic,
        'usage': agent_meta.get('usage'),
        'promptTokens': agent_meta.get('promptTokens'),
        'inputTokens': agent_meta.get('inputTokens'),
        'outputTokens': agent_meta.get('outputTokens'),
        'contextTokens': agent_meta.get('contextTokens'),
        'systemPromptReport': system_prompt_report,
        'artifactsDir': str(artifacts_dir),
        'stdoutPath': str(artifacts_dir / 'openclaw-agent.stdout.txt'),
        'stderrPath': str(artifacts_dir / 'openclaw-agent.stderr.txt'),
        'transcriptPath': str(artifacts_dir / 'session-transcript.jsonl') if (artifacts_dir / 'session-transcript.jsonl').exists() else None,
        'createdAt': now_iso(),
    }


def _count_tools(tool_calls: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for call in tool_calls:
        name = call.get('name') or 'unknown'
        counts[name] = counts.get(name, 0) + 1
    return counts


def main() -> int:
    args = parse_args()
    variants = [parse_variant(raw) for raw in args.variant]
    if len({variant.id for variant in variants}) != len(variants):
        raise EvalError('Variant ids must be unique')
    prompts = load_prompts(Path(args.prompts))
    out_path = Path(args.out).expanduser().resolve()
    ensure_parent(out_path)
    run_root = Path(args.run_root).expanduser().resolve() if args.run_root else default_run_root().resolve()
    run_root.mkdir(parents=True, exist_ok=True)

    results: list[dict[str, Any]] = []
    failures = 0
    started_at = now_iso()

    for prompt in prompts:
        for variant in variants:
            maybe_print(args.verbose, f'Running {variant.id}:{prompt.id}')
            try:
                run_result = run_one(variant, prompt, args, run_root)
            except Exception as exc:  # noqa: BLE001
                failures += 1
                run_result = {
                    'variantId': variant.id,
                    'sourceWorkspace': str(variant.workspace),
                    'promptId': prompt.id,
                    'prompt': prompt.prompt,
                    'status': 'error',
                    'error': str(exc),
                    'createdAt': now_iso(),
                }
                if args.stop_on_error:
                    results.append(run_result)
                    payload = _build_payload(args, variants, prompts, results, run_root, started_at, failures)
                    write_json(out_path, payload)
                    raise
            if run_result.get('status') != 'ok':
                failures += 1
            results.append(run_result)
            payload = _build_payload(args, variants, prompts, results, run_root, started_at, failures)
            write_json(out_path, payload)

    payload = _build_payload(args, variants, prompts, results, run_root, started_at, failures)
    write_json(out_path, payload)
    print(out_path)
    print(f'runs={len(results)} failures={failures}')
    return 1 if failures else 0


def _build_payload(args: argparse.Namespace, variants: list[Variant], prompts, results, run_root: Path, started_at: str, failures: int) -> dict[str, Any]:
    return {
        'schemaVersion': 1,
        'tool': 'automation/openclaw-eval',
        'createdAt': started_at,
        'updatedAt': now_iso(),
        'promptFile': str(Path(args.prompts).expanduser().resolve()),
        'runRoot': str(run_root),
        'workspaceMode': args.workspace_mode,
        'thinking': args.thinking,
        'agentTimeoutSeconds': args.agent_timeout,
        'variants': [render_variant(v) for v in variants],
        'prompts': [
            {
                'id': prompt.id,
                'prompt': prompt.prompt,
                'tags': prompt.tags,
                'notes': prompt.notes,
                'source': prompt.source,
                'expectedContains': prompt.expected_contains,
            }
            for prompt in prompts
        ],
        'summary': {
            'runCount': len(results),
            'failureCount': failures,
            'okCount': sum(1 for r in results if r.get('status') == 'ok'),
        },
        'runs': results,
    }


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except EvalError as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        raise SystemExit(2)
