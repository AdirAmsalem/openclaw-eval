from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

def openclaw_home() -> Path:
    return Path(os.environ.get("OPENCLAW_HOME", "~/.openclaw")).expanduser()


def workspace_root() -> Path:
    return openclaw_home() / "workspace"


def agents_root() -> Path:
    return openclaw_home() / "agents"


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class EvalError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

@dataclass
class Setup:
    id: str
    workspace: Path
    model: str | None = None


@dataclass
class Check:
    type: str  # "contains", "not_contains", "manual"
    value: str | None = None

    def evaluate(self, answer: str) -> CheckResult:
        lowered = answer.lower()
        if self.type == "contains":
            return CheckResult(check=self, passed=(self.value or "").lower() in lowered)
        if self.type == "not_contains":
            return CheckResult(check=self, passed=(self.value or "").lower() not in lowered)
        return CheckResult(check=self, passed=None)


@dataclass
class CheckResult:
    check: Check
    passed: bool | None  # None = manual / unknown

    def to_dict(self) -> dict[str, Any]:
        return {"type": self.check.type, "value": self.check.value, "passed": self.passed}


@dataclass
class Scenario:
    id: str
    prompt: str
    tags: list[str] = field(default_factory=list)
    notes: str | None = None
    source: str | None = None
    checks: list[Check] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def slugify(value: str, max_len: int = 32) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "-", value).strip("-").lower()
    return cleaned[:max_len] or "x"


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def parse_setup(raw: str) -> Setup:
    parts = raw.split(":", 2)
    if len(parts) < 2:
        raise EvalError(f"Invalid --setup {raw!r}. Expected label:/abs/path or label:/abs/path:model")
    label, ws = parts[0].strip(), parts[1].strip()
    model = parts[2].strip() if len(parts) == 3 and parts[2].strip() else None
    if not label:
        raise EvalError(f"Invalid --setup {raw!r}: empty label")
    path = Path(ws).expanduser().resolve()
    if not path.exists() or not path.is_dir():
        raise EvalError(f"Setup workspace does not exist: {path}")
    return Setup(id=label, workspace=path, model=model)


def _parse_checks(raw: list[dict[str, Any]]) -> list[Check]:
    checks = []
    for item in raw:
        check_type = item.get("type", "")
        value = item.get("value")
        if check_type not in ("contains", "not_contains", "manual"):
            raise EvalError(f"Unknown check type: {check_type!r}")
        checks.append(Check(type=check_type, value=value))
    return checks


def load_scenarios(path: Path) -> list[Scenario]:
    path = path.expanduser().resolve()
    if not path.exists():
        raise EvalError(f"Suite file not found: {path}")

    suffix = path.suffix.lower()
    if suffix in {".jsonl", ".ndjson"}:
        return _load_jsonl(path)
    return _load_text(path)


def _load_jsonl(path: Path) -> list[Scenario]:
    scenarios: list[Scenario] = []
    with path.open() as fh:
        for idx, line in enumerate(fh, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError as exc:
                raise EvalError(f"Scenario line {idx} is not valid JSON: {exc}") from exc
            prompt_text = (data.get("prompt") or "").strip()
            if not prompt_text:
                raise EvalError(f"Scenario line {idx} missing 'prompt' text")
            scenario_id = str(data.get("id") or f"q{len(scenarios) + 1}")
            checks = _parse_checks(data.get("checks") or [])
            scenarios.append(
                Scenario(
                    id=scenario_id,
                    prompt=prompt_text,
                    tags=list(data.get("tags") or []),
                    notes=data.get("notes"),
                    source=data.get("source"),
                    checks=checks,
                )
            )
    if not scenarios:
        raise EvalError(f"No scenarios found in {path}")
    return scenarios


def _load_text(path: Path) -> list[Scenario]:
    scenarios: list[Scenario] = []
    with path.open() as fh:
        for line in fh:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if stripped.startswith("- "):
                stripped = stripped[2:].strip()
            elif stripped.startswith("* "):
                stripped = stripped[2:].strip()
            scenarios.append(Scenario(id=f"q{len(scenarios) + 1}", prompt=stripped, tags=[]))
    if not scenarios:
        raise EvalError(f"No scenarios found in {path}")
    return scenarios


# ---------------------------------------------------------------------------
# Shell / IO
# ---------------------------------------------------------------------------

def run_command(
    cmd: list[str], *, cwd: Path | None = None, timeout: int | None = None, check: bool = True
) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(cmd, cwd=str(cwd) if cwd else None, text=True, capture_output=True, timeout=timeout)
    if check and proc.returncode != 0:
        raise EvalError(f"Command failed ({proc.returncode}): {' '.join(cmd)}\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}")
    return proc


def safe_json_loads(raw: str) -> Any:
    raw = raw.strip()
    if not raw:
        raise EvalError("Expected JSON output but got empty string")
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise EvalError(f"Failed to parse JSON output: {exc}\nRaw output:\n{raw}") from exc


def copy_workspace(src: Path, dest: Path) -> None:
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(src, dest)


def make_agent_id(prefix: str, setup_id: str, scenario_id: str) -> str:
    bits = [slugify(prefix, 12), slugify(setup_id, 12), slugify(scenario_id, 12), uuid.uuid4().hex[:8]]
    return "-".join(filter(None, bits))


def agent_session_transcript_path(agent_id: str, session_id: str) -> Path:
    return agents_root() / agent_id / "sessions" / f"{session_id}.jsonl"


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
            if obj.get("type") != "message":
                continue
            msg = obj.get("message", {})
            if msg.get("role") != "assistant":
                continue
            for item in msg.get("content", []):
                if item.get("type") == "toolCall":
                    tool_calls.append({"name": item.get("name"), "arguments": item.get("arguments", {})})
    return tool_calls


def read_files_from_tool_calls(tool_calls: list[dict[str, Any]]) -> list[str]:
    paths: list[str] = []
    for call in tool_calls:
        if call.get("name") != "read":
            continue
        args = call.get("arguments") or {}
        for key in ("path", "file_path", "filePath", "file"):
            value = args.get(key)
            if value:
                paths.append(str(value))
                break
    return paths


def basename_list(paths: list[str]) -> list[str]:
    return [os.path.basename(p) for p in paths]


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=False) + "\n")
