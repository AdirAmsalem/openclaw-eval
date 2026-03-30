#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

WORKSPACE_ROOT = Path('/home/ubuntu/.openclaw/workspace')
AGENTS_ROOT = Path('/home/ubuntu/.openclaw/agents')


class EvalError(RuntimeError):
    pass


@dataclass
class Variant:
    id: str
    workspace: Path
    model: str | None = None


@dataclass
class Prompt:
    id: str
    prompt: str
    tags: list[str]
    notes: str | None = None
    source: str | None = None
    expected_contains: list[str] | None = None


def now_iso() -> str:
    return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())


def slugify(value: str, max_len: int = 32) -> str:
    cleaned = re.sub(r'[^a-zA-Z0-9]+', '-', value).strip('-').lower()
    return cleaned[:max_len] or 'x'


def parse_variant(raw: str) -> Variant:
    parts = raw.split(':', 2)
    if len(parts) < 2:
        raise EvalError(f'Invalid --variant {raw!r}. Expected label:/abs/path or label:/abs/path:model')
    label, workspace = parts[0].strip(), parts[1].strip()
    model = parts[2].strip() if len(parts) == 3 and parts[2].strip() else None
    if not label:
        raise EvalError(f'Invalid --variant {raw!r}: empty label')
    path = Path(workspace).expanduser().resolve()
    if not path.exists() or not path.is_dir():
        raise EvalError(f'Variant workspace does not exist: {path}')
    return Variant(id=label, workspace=path, model=model)


def load_prompts(path: Path) -> list[Prompt]:
    path = path.expanduser().resolve()
    if not path.exists():
        raise EvalError(f'Prompt file not found: {path}')
    suffix = path.suffix.lower()
    prompts: list[Prompt] = []
    if suffix in {'.jsonl', '.ndjson'}:
        with path.open() as fh:
            for idx, line in enumerate(fh, start=1):
                line = line.strip()
                if not line:
                    continue
                data = json.loads(line)
                prompt_text = (data.get('prompt') or '').strip()
                if not prompt_text:
                    raise EvalError(f'Prompt line {idx} missing "prompt" text')
                prompt_id = str(data.get('id') or f'q{len(prompts) + 1}')
                expected = data.get('expectedContains')
                if expected is not None and not isinstance(expected, list):
                    raise EvalError(f'Prompt line {idx} expectedContains must be a list if present')
                prompts.append(
                    Prompt(
                        id=prompt_id,
                        prompt=prompt_text,
                        tags=list(data.get('tags') or []),
                        notes=data.get('notes'),
                        source=data.get('source'),
                        expected_contains=expected,
                    )
                )
        return prompts

    with path.open() as fh:
        for line in fh:
            raw = line.rstrip('\n')
            stripped = raw.strip()
            if not stripped or stripped.startswith('#'):
                continue
            if stripped.startswith('- '):
                stripped = stripped[2:].strip()
            elif stripped.startswith('* '):
                stripped = stripped[2:].strip()
            prompts.append(Prompt(id=f'q{len(prompts) + 1}', prompt=stripped, tags=[]))
    if not prompts:
        raise EvalError(f'No prompts found in {path}')
    return prompts


def run_command(cmd: list[str], *, cwd: Path | None = None, timeout: int | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        text=True,
        capture_output=True,
        timeout=timeout,
    )
    if check and proc.returncode != 0:
        raise EvalError(
            f'Command failed ({proc.returncode}): {" ".join(cmd)}\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}'
        )
    return proc


def safe_json_loads(raw: str) -> Any:
    raw = raw.strip()
    if not raw:
        raise EvalError('Expected JSON output but got empty string')
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise EvalError(f'Failed to parse JSON output: {exc}\nRaw output:\n{raw}') from exc


def copy_workspace(src: Path, dest: Path) -> None:
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(src, dest)


def make_agent_id(prefix: str, variant_id: str, prompt_id: str) -> str:
    bits = [slugify(prefix, 12), slugify(variant_id, 12), slugify(prompt_id, 12), uuid.uuid4().hex[:8]]
    return '-'.join(filter(None, bits))


def agent_session_transcript_path(agent_id: str, session_id: str) -> Path:
    return AGENTS_ROOT / agent_id / 'sessions' / f'{session_id}.jsonl'


def extract_tool_calls(transcript_path: Path) -> list[dict[str, Any]]:
    if not transcript_path.exists():
        return []
    tool_calls: list[dict[str, Any]] = []
    with transcript_path.open() as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if obj.get('type') != 'message':
                continue
            msg = obj.get('message', {})
            if msg.get('role') != 'assistant':
                continue
            for item in msg.get('content', []):
                if item.get('type') == 'toolCall':
                    tool_calls.append(
                        {
                            'name': item.get('name'),
                            'arguments': item.get('arguments', {}),
                        }
                    )
    return tool_calls


def read_files_from_tool_calls(tool_calls: list[dict[str, Any]]) -> list[str]:
    paths: list[str] = []
    for call in tool_calls:
        if call.get('name') != 'read':
            continue
        args = call.get('arguments') or {}
        for key in ('path', 'file_path', 'filePath', 'file'):
            value = args.get(key)
            if value:
                paths.append(str(value))
                break
    return paths


def basename_list(paths: list[str]) -> list[str]:
    return [os.path.basename(p) for p in paths]


def heuristic_pass(prompt: Prompt, answer: str) -> dict[str, Any] | None:
    if not prompt.expected_contains:
        return None
    lowered = answer.lower()
    missing = [needle for needle in prompt.expected_contains if needle.lower() not in lowered]
    return {
        'passed': not missing,
        'missing': missing,
        'expectedContains': prompt.expected_contains,
    }


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=False) + '\n')
