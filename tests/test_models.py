from __future__ import annotations

from pathlib import Path

import pytest

from openclaw_eval.lib import Check, EvalError, Scenario, load_scenarios, parse_setup


class TestParseSetup:
    def test_basic(self, tmp_path: Path) -> None:
        ws = tmp_path / "workspace"
        ws.mkdir()
        setup = parse_setup(f"main:{ws}")
        assert setup.id == "main"
        assert setup.workspace == ws
        assert setup.model is None

    def test_with_model(self, tmp_path: Path) -> None:
        ws = tmp_path / "workspace"
        ws.mkdir()
        setup = parse_setup(f"fast:{ws}:some-provider/some-model")
        assert setup.id == "fast"
        assert setup.workspace == ws
        assert setup.model == "some-provider/some-model"

    def test_missing_path_raises(self) -> None:
        with pytest.raises(EvalError, match="does not exist"):
            parse_setup("bad:/nonexistent/path")

    def test_empty_label_raises(self, tmp_path: Path) -> None:
        ws = tmp_path / "workspace"
        ws.mkdir()
        with pytest.raises(EvalError, match="empty label"):
            parse_setup(f":{ws}")

    def test_no_colon_raises(self) -> None:
        with pytest.raises(EvalError, match="Expected label"):
            parse_setup("just-a-string")


class TestLoadScenarios:
    def test_load_sample(self) -> None:
        path = Path(__file__).parent / "fixtures" / "sample.jsonl"
        scenarios = load_scenarios(path)
        assert len(scenarios) == 3
        assert scenarios[0].id == "ssh-workaround"
        assert scenarios[0].prompt == "The agent on the remote node fails with 'Permission denied' when sandboxing. What's the workaround?"
        assert scenarios[0].tags == ["infra"]
        assert len(scenarios[0].checks) == 1
        assert scenarios[0].checks[0].type == "contains"
        assert scenarios[0].checks[0].value == "--no-sandbox"

    def test_multiple_checks(self) -> None:
        path = Path(__file__).parent / "fixtures" / "sample.jsonl"
        scenarios = load_scenarios(path)
        sc = scenarios[1]
        assert len(sc.checks) == 2
        assert sc.checks[0].type == "contains"
        assert sc.checks[1].type == "not_contains"

    def test_manual_check(self) -> None:
        path = Path(__file__).parent / "fixtures" / "sample.jsonl"
        scenarios = load_scenarios(path)
        sc = scenarios[2]
        assert len(sc.checks) == 1
        assert sc.checks[0].type == "manual"
        assert sc.checks[0].value is None

    def test_auto_id(self, tmp_path: Path) -> None:
        suite = tmp_path / "suite.jsonl"
        suite.write_text('{"prompt":"hello"}\n{"prompt":"world"}\n')
        scenarios = load_scenarios(suite)
        assert scenarios[0].id == "q1"
        assert scenarios[1].id == "q2"

    def test_missing_prompt_raises(self, tmp_path: Path) -> None:
        suite = tmp_path / "bad.jsonl"
        suite.write_text('{"id":"x"}\n')
        with pytest.raises(EvalError, match="missing 'prompt'"):
            load_scenarios(suite)

    def test_empty_file_raises(self, tmp_path: Path) -> None:
        suite = tmp_path / "empty.jsonl"
        suite.write_text("")
        with pytest.raises(EvalError, match="No scenarios found"):
            load_scenarios(suite)

    def test_unknown_check_type_raises(self, tmp_path: Path) -> None:
        suite = tmp_path / "bad_check.jsonl"
        suite.write_text('{"id":"x","prompt":"hi","checks":[{"type":"regex","value":".*"}]}\n')
        with pytest.raises(EvalError, match="Unknown check type"):
            load_scenarios(suite)

    def test_load_text(self, tmp_path: Path) -> None:
        suite = tmp_path / "suite.txt"
        suite.write_text("How do I deploy?\n# comment\n- What is the status?\n* Where are logs?\n\n")
        scenarios = load_scenarios(suite)
        assert len(scenarios) == 3
        assert scenarios[0].prompt == "How do I deploy?"
        assert scenarios[1].prompt == "What is the status?"
        assert scenarios[2].prompt == "Where are logs?"
        assert scenarios[0].id == "q1"
        assert scenarios[0].checks == []

    def test_load_markdown(self, tmp_path: Path) -> None:
        suite = tmp_path / "suite.md"
        suite.write_text("- First question\n- Second question\n")
        scenarios = load_scenarios(suite)
        assert len(scenarios) == 2

    def test_empty_text_raises(self, tmp_path: Path) -> None:
        suite = tmp_path / "empty.txt"
        suite.write_text("# just comments\n\n")
        with pytest.raises(EvalError, match="No scenarios found"):
            load_scenarios(suite)
