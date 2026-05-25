"""Smoke test so `pytest tests/unit` has at least one collected test.

The per-lib test split (commit 275499fe) moved every real unit test into
`libs/*/tests/`, leaving this directory effectively empty. The CI command
`pytest tests/unit tests/functional -m "not integration"` was failing
with `file or directory not found: tests/unit` because pytest refuses to
treat a directory with no collectable files as a valid path argument.

This file gives pytest something to find. Real unit tests are still in
`libs/*/tests/`.
"""


def test_tests_unit_directory_exists():
    assert True
