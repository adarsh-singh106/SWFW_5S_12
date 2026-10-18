import ipaddress
import re
from validate_port import validate_ssh_port
from db_storage import init_db, add_node, get_node_by_id, update_node_probe_result, list_nodes
from probe_engine import probe_ssh_endpoint


def validate_node_address(address: str) -> str:
    """Validates that address is a valid IPv4/IPv6 address or a valid DNS hostname."""
    if not isinstance(address, str):
        raise ValueError("Node address must be a string")
    clean = address.strip()
    if not clean:
        raise ValueError("Node address cannot be empty")

    # 1. Check if it's a valid IPv4 or IPv6 address
    try:
        ipaddress.ip_address(clean)
        return clean
    except ValueError:
        pass

    # 2. Check if it's a valid DNS hostname (e.g. server1.lab.local)
    hostname_regex = r"^[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?)*$"
    if re.match(hostname_regex, clean) and not clean.replace(".", "").isdigit():
        return clean

    raise ValueError(f"Invalid IP address or hostname: {clean!r}")


def register_node(node: dict, db_path: str = "inventory.db") -> dict:
    """Validate incoming payload and save to SQLite inventory."""
    if "name" not in node or "address" not in node or "port" not in node:
        raise ValueError("Payload must contain 'name', 'address', and 'port'")

    name = node["name"]
    if not isinstance(name, str):
        raise ValueError("Node name must be a string")
    clean_name = name.strip()
    if not clean_name:
        raise ValueError("Node name cannot be empty")

    clean_address = validate_node_address(node["address"])
    validated_port = validate_ssh_port(node["port"])

    init_db(db_path)
    node_id = add_node(clean_name, clean_address, validated_port, db_path=db_path)

    return {
        "id": node_id,
        "name": clean_name,
        "address": clean_address,
        "ssh_port": validated_port,
        "status": "not_checked"
    }


def probe_node(node_id: int, db_path: str = "inventory.db") -> dict:
    """Fetch node by ID, execute SSH banner probe, and update state in database."""
    node = get_node_by_id(node_id, db_path=db_path)
    if not node:
        raise ValueError(f"Node with id {node_id} does not exist")

    # Execute lightweight pre-auth banner probe
    probe_result = probe_ssh_endpoint(node["address"], node["ssh_port"])

    if probe_result["reachable"]:
        status = "reachable"
        banner = probe_result["banner"]
        latency_ms = probe_result["latency_ms"]
        last_error = None
    else:
        status = "unreachable"
        banner = None
        latency_ms = None
        last_error = probe_result["error"]

    updated_node = update_node_probe_result(
        node_id=node_id,
        status=status,
        banner=banner,
        latency_ms=latency_ms,
        last_error=last_error,
        db_path=db_path
    )
    return updated_node
