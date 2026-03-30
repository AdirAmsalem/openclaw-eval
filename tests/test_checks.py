from __future__ import annotations

from openclaw_eval.lib import Check


class TestContains:
    def test_pass(self) -> None:
        check = Check(type="contains", value="netlify")
        result = check.evaluate("You should use netlify to deploy.")
        assert result.passed is True

    def test_fail(self) -> None:
        check = Check(type="contains", value="netlify")
        result = check.evaluate("I don't know.")
        assert result.passed is False

    def test_case_insensitive(self) -> None:
        check = Check(type="contains", value="NETLIFY")
        result = check.evaluate("Try Netlify for deployment.")
        assert result.passed is True


class TestNotContains:
    def test_pass(self) -> None:
        check = Check(type="not_contains", value="I don't know")
        result = check.evaluate("The answer is 42.")
        assert result.passed is True

    def test_fail(self) -> None:
        check = Check(type="not_contains", value="I don't know")
        result = check.evaluate("I don't know the answer.")
        assert result.passed is False

    def test_case_insensitive(self) -> None:
        check = Check(type="not_contains", value="error")
        result = check.evaluate("There was an ERROR here.")
        assert result.passed is False


class TestManual:
    def test_returns_none(self) -> None:
        check = Check(type="manual")
        result = check.evaluate("Any answer here.")
        assert result.passed is None

    def test_to_dict(self) -> None:
        check = Check(type="manual")
        result = check.evaluate("Any answer.")
        d = result.to_dict()
        assert d == {"type": "manual", "value": None, "passed": None}


class TestToDict:
    def test_contains_pass(self) -> None:
        check = Check(type="contains", value="foo")
        result = check.evaluate("foo bar")
        d = result.to_dict()
        assert d == {"type": "contains", "value": "foo", "passed": True}

    def test_not_contains_fail(self) -> None:
        check = Check(type="not_contains", value="bar")
        result = check.evaluate("foo bar")
        d = result.to_dict()
        assert d == {"type": "not_contains", "value": "bar", "passed": False}
