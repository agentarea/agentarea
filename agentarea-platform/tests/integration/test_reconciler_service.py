"""Test for ReconcilerService."""
import pytest
from agentarea_common.reconciler.service import ReconcilerService, ReconcileResult


def test_reconcile_result_tracks_counts():
    result = ReconcileResult()
    result.created += 1
    result.updated += 2
    result.add_error("mcp_servers", "test error")
    assert result.created == 1
    assert result.updated == 2
    assert len(result.errors) == 1
    assert result.errors[0] == ("mcp_servers", "test error")


def test_reconcile_result_str():
    result = ReconcileResult()
    result.created = 3
    result.updated = 1
    s = str(result)
    assert "3" in s
    assert "1" in s
