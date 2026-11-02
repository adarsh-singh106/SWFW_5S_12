"""Isolated SSH worker: reads one structured request and emits one outcome."""

import json
import sys
from pathlib import Path
from typing import Any

from fleet_manager.config import SSHSettings
from fleet_manager.connectivity.models import ConnectivityOutcome
from fleet_manager.connectivity.transport import ParamikoSSHTransport
from fleet_manager.errors import ConnectivityConfigurationError
from fleet_manager.inventory.models import Node, ObservationState


def main() -> None:
    try:
        request: dict[str, Any] = json.load(sys.stdin)
        node_data = request["node"]
        ssh_data = request["ssh"]
        node = Node(
            int(node_data["id"]),
            "registered-node",
            str(node_data["address"]),
            int(node_data["ssh_port"]),
            ObservationState.NOT_CHECKED,
        )
        settings = SSHSettings(
            str(ssh_data["username"]),
            Path(ssh_data["known_hosts_path"]),
            Path(ssh_data["private_key_path"]),
            float(ssh_data["connect_timeout_seconds"]),
            float(ssh_data["authentication_timeout_seconds"]),
            float(ssh_data["banner_timeout_seconds"]),
        )
        outcome = ParamikoSSHTransport().verify(node, settings)
    except ConnectivityConfigurationError:
        sys.exit(2)
    except Exception:
        outcome = ConnectivityOutcome.UNKNOWN_ERROR
    print(outcome.value)


if __name__ == "__main__":
    main()
