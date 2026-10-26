import os
import json
import sqlite3
import tempfile
from targets_generator import generate_targets, atomic_write_targets, export_inventory_to_prometheus


def test_generate_targets_empty():
    """Empty list of nodes should return an empty targets list."""
    assert generate_targets([]) == []
    print("PASS: test_generate_targets_empty")


def test_generate_targets_formatting():
    """Nodes should be correctly converted into Prometheus target format."""
    nodes = [
        {"id": 1, "name": "web-prod-01", "address": "192.168.1.100"},
        {"id": 2, "name": "db-prod-01", "address": "192.168.1.101"}
    ]
    targets = generate_targets(nodes, exporter_port=9100)
    assert len(targets) == 2
    assert targets[0]["targets"] == ["192.168.1.100:9100"]
    assert targets[0]["labels"]["node_id"] == "1"
    assert targets[0]["labels"]["node_name"] == "web-prod-01"
    assert targets[0]["labels"]["job"] == "node_exporter"
    assert targets[1]["targets"] == ["192.168.1.101:9100"]
    print("PASS: test_generate_targets_formatting")


def test_generate_targets_custom_port():
    """Custom exporter port should be properly bound."""
    nodes = [{"id": 5, "name": "edge-01", "address": "10.0.0.5"}]
    targets = generate_targets(nodes, exporter_port=9200)
    assert targets[0]["targets"] == ["10.0.0.5:9200"]
    print("PASS: test_generate_targets_custom_port")


def test_atomic_write():
    """Verify file is written, is valid JSON, and no .tmp files linger."""
    with tempfile.TemporaryDirectory() as tmpdir:
        target_path = os.path.join(tmpdir, "targets.json")
        sample_data = [{"targets": ["127.0.0.1:9100"], "labels": {"fleet": "test"}}]
        
        atomic_write_targets(sample_data, target_path)
        
        assert os.path.exists(target_path)
        assert not os.path.exists(f"{target_path}.tmp")
        
        with open(target_path, "r", encoding="utf-8") as f:
            loaded = json.load(f)
        assert loaded == sample_data
    print("PASS: test_atomic_write")


def test_export_inventory_e2e():
    """End-to-end integration: SQLite DB -> targets.json"""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test_inventory.db")
        out_path = os.path.join(tmpdir, "test_targets.json")
        
        # Setup SQLite database with sample table and rows
        conn = sqlite3.connect(db_path)
        try:
            with conn:
                conn.execute("""
                    CREATE TABLE nodes (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        name TEXT NOT NULL,
                        address TEXT NOT NULL,
                        ssh_port INTEGER NOT NULL,
                        status TEXT DEFAULT 'not_checked'
                    )
                """)
                conn.execute(
                    "INSERT INTO nodes (name, address, ssh_port) VALUES (?, ?, ?)",
                    ("node-alpha", "192.168.10.1", 22)
                )
                conn.execute(
                    "INSERT INTO nodes (name, address, ssh_port) VALUES (?, ?, ?)",
                    ("node-beta", "192.168.10.2", 2222)
                )
        finally:
            conn.close()
            
        result = export_inventory_to_prometheus(db_path, out_path, exporter_port=9100)
        assert len(result) == 2
        assert result[0]["targets"] == ["192.168.10.1:9100"]
        assert result[1]["targets"] == ["192.168.10.2:9100"]
        
        # Read back written file
        with open(out_path, "r", encoding="utf-8") as f:
            on_disk = json.load(f)
        assert on_disk == result
    print("PASS: test_export_inventory_e2e")


if __name__ == "__main__":
    test_generate_targets_empty()
    test_generate_targets_formatting()
    test_generate_targets_custom_port()
    test_atomic_write()
    test_export_inventory_e2e()
    print("\nALL TARGETS GENERATOR TESTS PASSED!")
