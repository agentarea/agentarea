import pytest
from agentarea_evals.suites.checks import TrialOutcome, run_checks, validate_checks


def outcome(**overrides):
    fields = {
        "status": "completed",
        "response": "The capital of France is Paris.",
        "cost_usd": 0.02,
        "iterations": 3,
        "tools_called": ["shell_bash", "mcp__search__query"],
        "artifacts": ["reports/summary.md", "deck.pptx"],
    }
    fields.update(overrides)
    return TrialOutcome(**fields)


def test_a_completed_run_without_checks_passes():
    passed, results = run_checks([], outcome())
    assert passed
    assert results == [{"type": "completed", "passed": True, "detail": "completed"}]


def test_a_failed_run_fails_even_without_checks():
    passed, _ = run_checks([], outcome(status="failed"))
    assert not passed


def test_an_explicit_status_check_replaces_the_implicit_one():
    passed, _ = run_checks([{"type": "status_is", "status": "failed"}], outcome(status="failed"))
    assert passed


@pytest.mark.parametrize(
    ("check", "expected"),
    [
        ({"type": "response_contains", "text": "paris"}, True),
        ({"type": "response_contains", "text": "paris", "case_sensitive": True}, False),
        ({"type": "response_not_contains", "text": "London"}, True),
        ({"type": "response_matches", "pattern": r"capital of \w+"}, True),
        ({"type": "tool_called", "tool": "shell_bash"}, True),
        ({"type": "tool_called", "tool": "files_save_file"}, False),
        ({"type": "tool_not_called", "tool": "files_save_file"}, True),
        ({"type": "artifact_exists", "glob": "*.pptx"}, True),
        ({"type": "artifact_exists", "glob": "reports/*.csv"}, False),
        ({"type": "max_cost", "usd": 0.05}, True),
        ({"type": "max_cost", "usd": 0.01}, False),
        ({"type": "max_iterations", "count": 2}, False),
    ],
)
def test_each_check(check, expected):
    passed, results = run_checks([check], outcome())
    assert passed is expected
    assert results[-1]["type"] == check["type"]


def test_validate_rejects_unknown_types_and_missing_fields():
    with pytest.raises(ValueError, match="unknown check"):
        validate_checks([{"type": "vibes"}])
    with pytest.raises(ValueError, match="text"):
        validate_checks([{"type": "response_contains"}])
    with pytest.raises(ValueError, match="pattern"):
        validate_checks([{"type": "response_matches", "pattern": "("}])


def test_validate_returns_normalized_checks():
    assert validate_checks([{"type": "max_cost", "usd": "0.5"}]) == [{"type": "max_cost", "usd": 0.5}]


@pytest.mark.parametrize(
    ("check", "detail"),
    [
        ({"type": "response_contains", "text": "London"}, '"London" not found'),
        ({"type": "response_contains", "text": "paris"}, 'found: "…France is Paris."'),
        ({"type": "response_not_contains", "text": "France"}, 'found: "…capital of France is Paris."'),
        ({"type": "response_matches", "pattern": r"Ber\w+"}, "no match"),
    ],
)
def test_response_checks_say_what_they_saw(check, detail):
    _, results = run_checks([check], outcome())
    assert results[-1]["detail"] == detail
