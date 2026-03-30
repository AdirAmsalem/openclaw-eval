from __future__ import annotations

from openclaw_eval.report import avg, fmt_num, render, short_answer


class TestAvg:
    def test_basic(self) -> None:
        assert avg([1, 2, 3]) == 2.0

    def test_with_none(self) -> None:
        assert avg([1, None, 3]) == 2.0

    def test_empty(self) -> None:
        assert avg([]) is None

    def test_all_none(self) -> None:
        assert avg([None, None]) is None


class TestFmtNum:
    def test_none(self) -> None:
        assert fmt_num(None) == "—"

    def test_int(self) -> None:
        assert fmt_num(42) == "42"

    def test_float(self) -> None:
        assert fmt_num(3.14159) == "3.1"

    def test_float_zero_digits(self) -> None:
        assert fmt_num(3.7, 0) == "4"


class TestShortAnswer:
    def test_short(self) -> None:
        assert short_answer("hello") == "hello"

    def test_truncate(self) -> None:
        result = short_answer("a" * 200, max_len=10)
        assert len(result) == 10
        assert result.endswith("…")

    def test_whitespace_normalization(self) -> None:
        assert short_answer("  foo   bar  ") == "foo bar"


class TestRender:
    def test_basic_structure(self) -> None:
        data = {
            "createdAt": "2026-03-30T00:00:00Z",
            "updatedAt": "2026-03-30T00:01:00Z",
            "suiteFile": "/tmp/suite.jsonl",
            "outDir": "/tmp/out",
            "workspaceMode": "copy",
            "thinking": "minimal",
            "setups": [
                {"id": "main", "workspace": "/tmp/ws-main", "model": None},
            ],
            "scenarios": [
                {"id": "q1", "prompt": "What is X?", "tags": ["test"], "source": None, "notes": None, "checks": [{"type": "contains", "value": "answer"}]},
            ],
            "runs": [
                {
                    "setupId": "main",
                    "scenarioId": "q1",
                    "status": "ok",
                    "answer": "The answer is here.",
                    "latencySeconds": 5.2,
                    "promptTokens": 1000,
                    "contextTokens": 500,
                    "inputTokens": 800,
                    "outputTokens": 200,
                    "readBasenames": ["README.md"],
                    "checks": [{"type": "contains", "value": "answer", "passed": True}],
                    "systemPromptReport": None,
                },
            ],
        }
        report = render(data)
        assert "# OpenClaw Eval Report" in report
        assert "## Summary by setup" in report
        assert "## Per-scenario comparison" in report
        assert "**main**" in report
        assert "`pass`" in report
        assert "The answer is here." in report

    def test_error_run(self) -> None:
        data = {
            "createdAt": "2026-03-30T00:00:00Z",
            "updatedAt": "2026-03-30T00:01:00Z",
            "suiteFile": "/tmp/suite.jsonl",
            "outDir": "/tmp/out",
            "workspaceMode": "copy",
            "thinking": None,
            "setups": [{"id": "pr", "workspace": "/tmp/ws-pr", "model": None}],
            "scenarios": [{"id": "q1", "prompt": "What?", "tags": [], "source": None, "notes": None, "checks": []}],
            "runs": [
                {
                    "setupId": "pr",
                    "scenarioId": "q1",
                    "status": "error",
                    "error": "agent crashed",
                    "answer": "",
                    "latencySeconds": 1.0,
                    "promptTokens": None,
                    "contextTokens": None,
                    "inputTokens": None,
                    "outputTokens": None,
                    "readBasenames": [],
                    "checks": [],
                    "systemPromptReport": None,
                },
            ],
        }
        report = render(data)
        assert "agent crashed" in report
        assert "failed `1`" in report
