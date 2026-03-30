from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any


def avg(values: list[float | int | None]) -> float | None:
    nums = [float(v) for v in values if v is not None]
    if not nums:
        return None
    return sum(nums) / len(nums)


def fmt_num(value: float | int | None, digits: int = 1) -> str:
    if value is None:
        return "—"
    if isinstance(value, int):
        return str(value)
    return f"{value:.{digits}f}"


def injected_chars(run: dict[str, Any], name: str) -> int | None:
    report = run.get("systemPromptReport") or {}
    files = report.get("injectedWorkspaceFiles") or []
    for item in files:
        if item.get("name") == name:
            return item.get("injectedChars")
    return None


def summarize_setup(runs: list[dict[str, Any]]) -> dict[str, Any]:
    read_names: Counter[str] = Counter()
    ok_runs = [r for r in runs if r.get("status") == "ok"]
    for run in ok_runs:
        for name in run.get("readBasenames") or []:
            read_names[name] += 1

    checks_passed = 0
    checks_failed = 0
    for run in ok_runs:
        for check in run.get("checks") or []:
            if check.get("passed") is True:
                checks_passed += 1
            elif check.get("passed") is False:
                checks_failed += 1

    return {
        "runCount": len(runs),
        "okCount": len(ok_runs),
        "failureCount": len(runs) - len(ok_runs),
        "checksPassed": checks_passed,
        "checksFailed": checks_failed,
        "avgLatencySeconds": avg([r.get("latencySeconds") for r in ok_runs]),
        "avgPromptTokens": avg([r.get("promptTokens") for r in ok_runs]),
        "avgContextTokens": avg([r.get("contextTokens") for r in ok_runs]),
        "avgInputTokens": avg([r.get("inputTokens") for r in ok_runs]),
        "avgOutputTokens": avg([r.get("outputTokens") for r in ok_runs]),
        "avgToolsInjectedChars": avg([injected_chars(r, "TOOLS.md") for r in ok_runs]),
        "readBasenames": read_names,
    }


def short_answer(text: str, max_len: int = 180) -> str:
    text = " ".join((text or "").split())
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "…"


def render(data: dict[str, Any]) -> str:
    runs = data.get("runs") or []
    setups = data.get("setups") or []
    scenarios = data.get("scenarios") or []

    runs_by_setup: dict[str, list[dict[str, Any]]] = defaultdict(list)
    runs_by_scenario_setup: dict[tuple[str, str], dict[str, Any]] = {}
    for run in runs:
        setup_id = run.get("setupId") or "unknown"
        scenario_id = run.get("scenarioId") or "unknown"
        runs_by_setup[setup_id].append(run)
        runs_by_scenario_setup[(scenario_id, setup_id)] = run

    lines: list[str] = []
    lines.append("# OpenClaw Eval Report")
    lines.append("")
    lines.append(f"- created: `{data.get('createdAt')}`")
    lines.append(f"- updated: `{data.get('updatedAt')}`")
    lines.append(f"- suite file: `{data.get('suiteFile')}`")
    lines.append(f"- output dir: `{data.get('outDir')}`")
    lines.append(f"- workspace mode: `{data.get('workspaceMode')}`")
    lines.append(f"- thinking: `{data.get('thinking')}`")
    lines.append("")

    lines.append("## Summary by setup")
    lines.append("")
    for setup in setups:
        setup_id = setup.get("id")
        summary = summarize_setup(runs_by_setup.get(setup_id, []))
        lines.append(f"### {setup_id}")
        lines.append("")
        lines.append(f"- workspace: `{setup.get('workspace')}`")
        if setup.get("model"):
            lines.append(f"- model override: `{setup.get('model')}`")
        lines.append(f"- runs: `{summary['runCount']}` (ok `{summary['okCount']}`, failed `{summary['failureCount']}`)")
        lines.append(f"- checks: `{summary['checksPassed']}` passed, `{summary['checksFailed']}` failed")
        lines.append(f"- avg latency: `{fmt_num(summary['avgLatencySeconds'])}s`")
        lines.append(f"- avg prompt tokens: `{fmt_num(summary['avgPromptTokens'])}`")
        lines.append(f"- avg context tokens: `{fmt_num(summary['avgContextTokens'])}`")
        lines.append(f"- avg input tokens: `{fmt_num(summary['avgInputTokens'])}`")
        lines.append(f"- avg output tokens: `{fmt_num(summary['avgOutputTokens'])}`")
        lines.append(f"- avg injected `TOOLS.md` chars: `{fmt_num(summary['avgToolsInjectedChars'])}`")
        if summary["readBasenames"]:
            read_bits = ", ".join(f"`{name}` ×{count}" for name, count in summary["readBasenames"].most_common())
            lines.append(f"- read files: {read_bits}")
        else:
            lines.append("- read files: none")
        lines.append("")

    lines.append("## Per-scenario comparison")
    lines.append("")
    for scenario in scenarios:
        scenario_id = scenario.get("id")
        lines.append(f"### {scenario_id}")
        lines.append("")
        lines.append(f"**Prompt:** {scenario.get('prompt')}  ")
        if scenario.get("source"):
            lines.append(f"**Source:** {scenario.get('source')}  ")
        if scenario.get("tags"):
            lines.append(f"**Tags:** {', '.join(scenario.get('tags'))}  ")
        lines.append("")
        for setup in setups:
            setup_id = setup.get("id")
            run = runs_by_scenario_setup.get((scenario_id, setup_id))
            if not run:
                lines.append(f"- **{setup_id}:** missing")
                continue
            status = run.get("status")
            answer = short_answer(run.get("answer") or "")
            read_names = ", ".join(f"`{name}`" for name in run.get("readBasenames") or []) or "none"
            tools_chars = injected_chars(run, "TOOLS.md")
            lines.append(
                f"- **{setup_id}** — status `{status}`, latency `{fmt_num(run.get('latencySeconds'))}s`, "
                f"prompt tokens `{fmt_num(run.get('promptTokens'))}`, "
                f"injected `TOOLS.md` chars `{fmt_num(tools_chars, 0)}`, reads {read_names}"
            )
            checks = run.get("checks") or []
            for check in checks:
                passed = check.get("passed")
                label = "pass" if passed is True else "fail" if passed is False else "manual"
                check_desc = f"{check.get('type')}"
                if check.get("value"):
                    check_desc += f"({check['value']})"
                lines.append(f"  - check `{check_desc}`: `{label}`")
            if status == "ok":
                lines.append(f"  - answer: {answer}")
            else:
                lines.append(f"  - error: `{run.get('error')}`")
        lines.append("")

    return "\n".join(lines).strip() + "\n"
