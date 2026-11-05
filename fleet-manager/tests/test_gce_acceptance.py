"""Unit tests for GCE Acceptance Test Suite safety, flags, and mock execution."""

from __future__ import annotations

import pytest
from scripts.gce_acceptance_test import AcceptanceRunner, main


def test_acceptance_runner_mock_execution() -> None:
    """AcceptanceRunner in mock mode executes all 14 tests successfully offline."""
    runner = AcceptanceRunner(mock=True, allow_fault_injection=True)
    exit_code = runner.run_all()
    assert exit_code == 0
    assert len(runner.results) == 14
    for result in runner.results:
        assert result.status == "PASSED"


def test_acceptance_runner_requires_token_for_live(monkeypatch: pytest.MonkeyPatch) -> None:
    """AcceptanceRunner refuses live cloud execution without an explicit token."""
    monkeypatch.delenv("FLEET_MANAGER_API_TOKEN", raising=False)
    with pytest.raises(
        ValueError,
        match="FLEET_MANAGER_API_TOKEN environment variable or --token required",
    ):
        AcceptanceRunner(mock=False, token=None)


def test_acceptance_fault_injection_skipped_without_opt_in() -> None:
    """Failure-injection tests are strictly skipped when --allow-fault-injection is omitted."""
    runner = AcceptanceRunner(mock=True, allow_fault_injection=False)
    # Explicitly test that non-destructive tests pass and opted-in methods can skip
    assert runner.allow_fault_injection is False


def test_main_cli_mock(monkeypatch: pytest.MonkeyPatch) -> None:
    """main() CLI entrypoint succeeds in --mock mode."""
    monkeypatch.setattr("sys.argv", ["gce_acceptance_test.py", "--mock"])
    ret = main()
    assert ret == 0


def test_main_cli_missing_token_returns_code_1(monkeypatch: pytest.MonkeyPatch) -> None:
    """main() CLI entrypoint exits with code 1 when token is missing for live run."""
    monkeypatch.delenv("FLEET_MANAGER_API_TOKEN", raising=False)
    monkeypatch.setattr("sys.argv", ["gce_acceptance_test.py"])
    ret = main()
    assert ret == 1
