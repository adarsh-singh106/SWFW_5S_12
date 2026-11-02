"""Hard deadline, admission control, and shutdown for SSH worker processes."""

import sys
import threading
import time
from pathlib import Path
from unittest.mock import Mock

import pytest

from fleet_manager.config import ConnectivityLimits, SSHSettings
from fleet_manager.connectivity.executor import ProcessSSHExecutor
from fleet_manager.connectivity.models import ConnectivityOutcome
from fleet_manager.errors import ConnectivityBusy, ConnectivityInProgress, ConnectivityUnavailable
from fleet_manager.inventory.models import Node, ObservationState

_WORKER = """
import json
import pathlib
import socket
import sys
import time

request = json.load(sys.stdin)
node = request["node"]
folder = pathlib.Path(sys.argv[1])
(folder / f'{node["id"]}.started').write_text('started')
if node["address"] == "dns":
    socket.getaddrinfo = lambda *_args, **_kwargs: time.sleep(5)
    socket.getaddrinfo("delayed.example", 22)
elif node["address"] == "attempts":
    time.sleep(0.18)
    time.sleep(0.18)
else:
    time.sleep(float(node["address"]))
(folder / f'{node["id"]}.done').write_text('done')
print('CONNECTED')
"""


def _node(node_id: int, delay: str) -> Node:
    return Node(node_id, "test", delay, 22, ObservationState.NOT_CHECKED)


def _wait_for(path: Path) -> None:
    deadline = time.monotonic() + 3
    while not path.exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert path.exists()


@pytest.fixture
def ssh_settings(tmp_path: Path) -> SSHSettings:
    return SSHSettings("observer", tmp_path / "hosts", tmp_path / "key")


def _executor(tmp_path: Path, capacity: int, budget: float) -> ProcessSSHExecutor:
    return ProcessSSHExecutor(
        ConnectivityLimits(capacity, budget),
        worker_command=(sys.executable, "-c", _WORKER, str(tmp_path)),
    )


def test_fast_worker_succeeds_and_capacity_recovers(
    tmp_path: Path, ssh_settings: SSHSettings
) -> None:
    executor = _executor(tmp_path, 1, 1)
    try:
        assert executor.run(_node(1, "0.01"), ssh_settings) is ConnectivityOutcome.CONNECTED
        assert executor.run(_node(2, "0.01"), ssh_settings) is ConnectivityOutcome.CONNECTED
    finally:
        executor.close()


@pytest.mark.parametrize("delay", ["dns", "attempts"])
def test_total_deadline_kills_blocked_dns_or_multiple_attempts(
    tmp_path: Path, ssh_settings: SSHSettings, delay: str
) -> None:
    executor = _executor(tmp_path, 1, 0.25)
    try:
        start = time.monotonic()
        assert executor.run(_node(1, delay), ssh_settings) is ConnectivityOutcome.TIMEOUT
        assert time.monotonic() - start < 1.5
        time.sleep(0.4)
        assert not (tmp_path / "1.done").exists()
        assert executor.run(_node(2, "0.01"), ssh_settings) is ConnectivityOutcome.CONNECTED
    finally:
        executor.close()


def test_limit_and_same_node_reject_without_queueing(
    tmp_path: Path, ssh_settings: SSHSettings
) -> None:
    executor = _executor(tmp_path, 1, 2)
    results: list[ConnectivityOutcome] = []
    thread = threading.Thread(
        target=lambda: results.append(executor.run(_node(1, "0.5"), ssh_settings))
    )
    thread.start()
    try:
        _wait_for(tmp_path / "1.started")
        with pytest.raises(ConnectivityInProgress):
            executor.run(_node(1, "0.01"), ssh_settings)
        with pytest.raises(ConnectivityBusy):
            executor.run(_node(2, "0.01"), ssh_settings)
        assert not (tmp_path / "2.started").exists()
        thread.join(timeout=2)
        assert results == [ConnectivityOutcome.CONNECTED]
        assert executor.run(_node(2, "0.01"), ssh_settings) is ConnectivityOutcome.CONNECTED
    finally:
        executor.close()
        thread.join(timeout=2)


def test_shutdown_kills_active_worker_without_success_observation(
    tmp_path: Path, ssh_settings: SSHSettings
) -> None:
    executor = _executor(tmp_path, 1, 6)
    failures: list[Exception] = []

    def run_check() -> None:
        try:
            executor.run(_node(1, "5"), ssh_settings)
        except Exception as exc:
            failures.append(exc)

    thread = threading.Thread(target=run_check)
    thread.start()
    _wait_for(tmp_path / "1.started")
    executor.close()
    thread.join(timeout=2)
    assert not thread.is_alive()
    assert len(failures) == 1 and isinstance(failures[0], ConnectivityUnavailable)
    assert not (tmp_path / "1.done").exists()
    with pytest.raises(ConnectivityUnavailable):
        executor.run(_node(2, "0.01"), ssh_settings)


def test_communicate_oserror_kills_and_reaps_child(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, ssh_settings: SSHSettings
) -> None:
    process = Mock()
    process.communicate.side_effect = OSError("pipe failed")
    process.poll.return_value = None
    monkeypatch.setattr(
        "fleet_manager.connectivity.executor.subprocess.Popen", lambda *_a, **_k: process
    )
    executor = _executor(tmp_path, 1, 1)

    with pytest.raises(ConnectivityUnavailable):
        executor.run(_node(1, "0.01"), ssh_settings)

    process.kill.assert_called_once_with()
    process.wait.assert_called_once_with()
