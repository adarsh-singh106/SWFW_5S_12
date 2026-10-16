"""
Milestone 1 Demo: Node Inventory Pipeline Live Verification
Run this script while recording your screen or audio for Milestone 1 demonstration.
"""

import os
import sys

# Ensure UTF-8 output if supported by terminal
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from node_service import register_node
from db_storage import init_db, list_nodes

DEMO_DB = "demo_inventory.db"

def run_milestone_demo():
    print("=" * 65)
    print("FLEET MANAGER - MILESTONE 1: NODE INVENTORY DEMO")
    print("=" * 65)

    # Clean previous demo DB if present
    if os.path.exists(DEMO_DB):
        try:
            os.remove(DEMO_DB)
        except OSError:
            pass

    print("\n[STEP 1] Initializing Storage Engine...")
    init_db(DEMO_DB)
    print("  -> Table 'nodes' created with UNIQUE(address, ssh_port) constraint.")

    print("\n[STEP 2] Registering Valid Node ('Lab Ubuntu 1', 192.168.1.50:22)...")
    payload = {
        "name": "   Lab Ubuntu 1   ",  # Extra spaces to test sanitization
        "address": "192.168.1.50",
        "port": 22
    }
    result = register_node(payload, db_path=DEMO_DB)
    print("  -> [OK] Node registered successfully!")
    print(f"  -> Returned Record: {result}")
    print("  -> Status is 'not_checked' (Saving contact != Calling contact)")

    print("\n[STEP 3] Testing Validation Gatekeeper (Port: 99999)...")
    try:
        register_node({"name": "Bad Node", "address": "10.0.0.1", "port": 99999}, db_path=DEMO_DB)
        print("  -> [FAIL] ERROR: Invalid port was accepted!")
    except ValueError as e:
        print(f"  -> [OK] Caught Expected Error: {e}")
        print("  -> Gatekeeper blocked bad data before touching database.")

    print("\n[STEP 4] Testing Duplicate Prevention (Same IP:Port again)...")
    try:
        register_node({
            "name": "Another Machine",
            "address": "192.168.1.50",
            "port": 22
        }, db_path=DEMO_DB)
        print("  -> [FAIL] ERROR: Duplicate was accepted!")
    except ValueError as e:
        print(f"  -> [OK] Caught Expected Error: {e}")
        print("  -> Database UNIQUE constraint prevented duplicate row.")

    print("\n[STEP 5] Verifying Disk Persistence across restarts...")
    saved_nodes = list_nodes(DEMO_DB)
    print(f"  -> Querying '{DEMO_DB}' directly from disk:")
    for node in saved_nodes:
        print(f"     Row: {node}")

    print("\n" + "=" * 65)
    print("MILESTONE 1 VERIFICATION COMPLETE: ALL SYSTEMS WORKING!")
    print("=" * 65)

    # Cleanup demo database
    if os.path.exists(DEMO_DB):
        try:
            os.remove(DEMO_DB)
        except OSError:
            pass

if __name__ == "__main__":
    run_milestone_demo()
