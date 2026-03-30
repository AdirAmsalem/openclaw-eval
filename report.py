#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Render a markdown summary for an openclaw eval results JSON file.')
    parser.add_argument('results', help='Path to results.json produced by run.py')
    parser.add_argument('--out', help='Optional markdown output path; prints to stdout if omitted')
    return parser.parse_args()


def avg(values: list[float | int | None]) -> float | None:
    nums = [float(v) for v in values if v is not None]
    if not nums:
        return None
    return sum(nums) / len(nums)


def fmt_num(value: float | int | None, digits: int = 1) -> str:
    if value is None:
        return '—'
    if isinstance(value, int):
        return str(value)
    return f'{value:.{digits}f}'


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def injected_chars(run: dict[str, Any], name: str) -> int | None:
    report = run.get('systemPromptReport') or {}
    files = report.get('injectedWorkspaceFiles') or []
    for item in files:
        if item.get('name') == name:
            return item.get('injectedChars')
    return None


def summarize_variant(runs: list[dict[str, Any]]) -> dict[str, Any]:
    read_names = Counter()
    ok_runs = [r for r in runs if r.get('status') == 'ok']
    for run in ok_runs:
        for name in run.get('readBasenames') or []:
            read_names[name] += 1
    return {
        'runCount': len(runs),
        'okCount': len(ok_runs),
        'failureCount': len(runs) - len(ok_runs),
        'avgLatencySeconds': avg([r.get('latencySeconds') for r in ok_runs]),
        'avgPromptTokens': avg([r.get('promptTokens') for r in ok_runs]),
        'avgContextTokens': avg([r.get('contextTokens') for r in ok_runs]),
        'avgInputTokens': avg([r.get('inputTokens') for r in ok_runs]),
        'avgOutputTokens': avg([r.get('outputTokens') for r in ok_runs]),
        'avgToolsInjectedChars': avg([injected_chars(r, 'TOOLS.md') for r in ok_runs]),
        'readBasenames': read_names,
    }


def short_answer(text: str, max_len: int = 180) -> str:
    text = ' '.join((text or '').split())
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + '…'


def render(data: dict[str, Any]) -> str:
    runs = data.get('runs') or []
    variants = data.get('variants') or []
    prompts = data.get('prompts') or []

    runs_by_variant: dict[str, list[dict[str, Any]]] = defaultdict(list)
    runs_by_prompt_variant: dict[tuple[str, str], dict[str, Any]] = {}
    for run in runs:
        variant_id = run.get('variantId') or 'unknown'
        prompt_id = run.get('promptId') or 'unknown'
        runs_by_variant[variant_id].append(run)
        runs_by_prompt_variant[(prompt_id, variant_id)] = run

    lines: list[str] = []
    lines.append('# OpenClaw Eval Report')
    lines.append('')
    lines.append(f"- created: `{data.get('createdAt')}`")
    lines.append(f"- updated: `{data.get('updatedAt')}`")
    lines.append(f"- prompt file: `{data.get('promptFile')}`")
    lines.append(f"- run root: `{data.get('runRoot')}`")
    lines.append(f"- workspace mode: `{data.get('workspaceMode')}`")
    lines.append(f"- thinking: `{data.get('thinking')}`")
    lines.append('')

    lines.append('## Summary by variant')
    lines.append('')
    for variant in variants:
        variant_id = variant.get('id')
        summary = summarize_variant(runs_by_variant.get(variant_id, []))
        lines.append(f"### {variant_id}")
        lines.append('')
        lines.append(f"- workspace: `{variant.get('workspace')}`")
        if variant.get('model'):
            lines.append(f"- model override: `{variant.get('model')}`")
        lines.append(f"- runs: `{summary['runCount']}` (ok `{summary['okCount']}`, failed `{summary['failureCount']}`)")
        lines.append(f"- avg latency: `{fmt_num(summary['avgLatencySeconds'])}s`")
        lines.append(f"- avg prompt tokens: `{fmt_num(summary['avgPromptTokens'])}`")
        lines.append(f"- avg context tokens: `{fmt_num(summary['avgContextTokens'])}`")
        lines.append(f"- avg input tokens: `{fmt_num(summary['avgInputTokens'])}`")
        lines.append(f"- avg output tokens: `{fmt_num(summary['avgOutputTokens'])}`")
        lines.append(f"- avg injected `TOOLS.md` chars: `{fmt_num(summary['avgToolsInjectedChars'])}`")
        if summary['readBasenames']:
            read_bits = ', '.join(f"`{name}` ×{count}" for name, count in summary['readBasenames'].most_common())
            lines.append(f"- read files: {read_bits}")
        else:
            lines.append('- read files: none')
        lines.append('')

    lines.append('## Per-prompt comparison')
    lines.append('')
    for prompt in prompts:
        prompt_id = prompt.get('id')
        lines.append(f"### {prompt_id}")
        lines.append('')
        lines.append(f"**Prompt:** {prompt.get('prompt')}  ")
        if prompt.get('source'):
            lines.append(f"**Source:** {prompt.get('source')}  ")
        if prompt.get('tags'):
            lines.append(f"**Tags:** {', '.join(prompt.get('tags'))}  ")
        lines.append('')
        for variant in variants:
            variant_id = variant.get('id')
            run = runs_by_prompt_variant.get((prompt_id, variant_id))
            if not run:
                lines.append(f"- **{variant_id}:** missing")
                continue
            status = run.get('status')
            answer = short_answer(run.get('answer') or '')
            read_names = ', '.join(f"`{name}`" for name in run.get('readBasenames') or []) or 'none'
            tools_chars = injected_chars(run, 'TOOLS.md')
            lines.append(f"- **{variant_id}** — status `{status}`, latency `{fmt_num(run.get('latencySeconds'))}s`, prompt tokens `{fmt_num(run.get('promptTokens'))}`, injected `TOOLS.md` chars `{fmt_num(tools_chars, 0)}`, reads {read_names}")
            if run.get('heuristic') is not None:
                heur = run['heuristic']
                lines.append(f"  - heuristic: `{'pass' if heur.get('passed') else 'fail'}`")
                if heur.get('missing'):
                    lines.append(f"  - missing expected: {', '.join(f'`{item}`' for item in heur['missing'])}")
            if status == 'ok':
                lines.append(f"  - answer: {answer}")
            else:
                lines.append(f"  - error: `{run.get('error')}`")
        lines.append('')

    return '\n'.join(lines).strip() + '\n'


def main() -> int:
    args = parse_args()
    path = Path(args.results).expanduser().resolve()
    data = load(path)
    report = render(data)
    if args.out:
        out_path = Path(args.out).expanduser().resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(report)
    else:
        print(report, end='')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
