"""Isolated operation worker: executes one remote command in a dedicated child process."""

import json
import sys
from pathlib import Path
from typing import Any

from fleet_manager.config import SSHSettings
from fleet_manager.errors import ConnectivityConfigurationError
from fleet_manager.inventory.models import Node, ObservationState
from fleet_manager.operations.models import (
    OperationExecutionResult,
    OperationFailureCategory,
    OperationOutcome,
)
from fleet_manager.operations.transport import ParamikoOperationTransport


def main() -> None:
    try:
        request: dict[str, Any] = json.load(sys.stdin)
        node_data = request["node"]
        ssh_data = request["ssh"]
        command = str(request["command"])
        timeout_seconds = float(request.get("timeout_seconds", 10.0))
        max_output_bytes = int(request.get("max_output_bytes", 65536))

        node = Node(
            id=int(node_data["id"]),
            name="registered-node",
            address=str(node_data["address"]),
            ssh_port=int(node_data["ssh_port"]),
            observation_state=ObservationState.NOT_CHECKED,
        )
        settings = SSHSettings(
            username=str(ssh_data["username"]),
            known_hosts_path=Path(ssh_data["known_hosts_path"]),
            private_key_path=Path(ssh_data["private_key_path"]),
            connect_timeout_seconds=float(ssh_data["connect_timeout_seconds"]),
            authentication_timeout_seconds=float(ssh_data["authentication_timeout_seconds"]),
            banner_timeout_seconds=float(ssh_data["banner_timeout_seconds"]),
        )
        result = ParamikoOperationTransport().execute(
            node=node,
            command=command,
            settings=settings,
            timeout_seconds=timeout_seconds,
            max_output_bytes=max_output_bytes,
        )
    except ConnectivityConfigurationError:
        sys.exit(2)
    except Exception:
        result = OperationExecutionResult(
            outcome=OperationOutcome.FAILURE,
            failure_category=OperationFailureCategory.UNAVAILABLE,
            exit_code=None,
            stdout=None,
            stderr="Operation worker failed",
            output_truncated=False,
        )

    output = {
        "outcome": result.outcome.value,
        "failure_category": result.failure_category.value if result.failure_category else None,
        "exit_code": result.exit_code,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "output_truncated": result.output_truncated,
    }
    json.dump(output, sys.stdout)
    sys.stdout.flush()


if __name__ == "__main__":
    main()
