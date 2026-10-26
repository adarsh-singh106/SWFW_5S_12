import os
import json
import sqlite3
from typing import List, Dict, Any


def generate_targets(nodes: List[Dict[str, Any]], exporter_port: int = 9100) -> List[Dict[str, Any]]:
    """
    Transforms a list of node records into Prometheus file_sd_configs target structure.
    
    Each node produces an entry with its target IP:exporter_port and metadata labels.
    """
    targets_config = []
    for node in nodes:
        address = node.get("address", "").strip()
        if not address:
            continue
        
        target_entry = {
            "targets": [f"{address}:{exporter_port}"],
            "labels": {
                "node_id": str(node.get("id", "")),
                "node_name": str(node.get("name", address)),
                "job": "node_exporter",
                "fleet": "production"
            }
        }
        targets_config.append(target_entry)
        
    return targets_config


def atomic_write_targets(targets: List[Dict[str, Any]], output_file: str) -> None:
    """
    Writes target configurations atomically to disk to prevent race conditions
    where Prometheus reads a partially written file.
    
    Algorithm:
    1. Write JSON to output_file.tmp
    2. Flush and fsync to ensure buffers are persisted
    3. Atomic rename via os.replace()
    """
    dir_name = os.path.dirname(output_file)
    if dir_name:
        os.makedirs(dir_name, exist_ok=True)
        
    temp_file = f"{output_file}.tmp"
    with open(temp_file, "w", encoding="utf-8") as f:
        json.dump(targets, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
        
    os.replace(temp_file, output_file)


def export_inventory_to_prometheus(
    db_path: str = "inventory.db",
    output_file: str = "targets.json",
    exporter_port: int = 9100
) -> List[Dict[str, Any]]:
    """
    Reads all nodes from SQLite inventory and exports them to Prometheus targets.json.
    Safe against empty databases or missing files.
    """
    nodes = []
    if os.path.exists(db_path):
        conn = sqlite3.connect(db_path)
        try:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("""
                SELECT id, name, address, ssh_port, status
                FROM nodes
                ORDER BY id ASC
            """)
            nodes = [dict(row) for row in cursor.fetchall()]
        except sqlite3.OperationalError:
            # Table might not exist yet if empty DB initialized
            nodes = []
        finally:
            conn.close()

    targets = generate_targets(nodes, exporter_port=exporter_port)
    atomic_write_targets(targets, output_file)
    return targets


if __name__ == "__main__":
    import sys
    db = sys.argv[1] if len(sys.argv) > 1 else "inventory.db"
    out = sys.argv[2] if len(sys.argv) > 2 else "targets.json"
    result = export_inventory_to_prometheus(db, out)
    print(f"Exported {len(result)} targets to {out}")
