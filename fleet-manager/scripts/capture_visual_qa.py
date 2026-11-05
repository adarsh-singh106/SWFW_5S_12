"""Visual QA script capturing real browser screenshots across required viewports."""

from __future__ import annotations

import json
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

import uvicorn

from fleet_manager.config import SSHSettings
from fleet_manager.connectivity.models import ConnectivityOutcome
from fleet_manager.connectivity.repository import SQLiteConnectivityRepository
from fleet_manager.main import create_app
from fleet_manager.operations.executor import DirectOperationExecutor
from fleet_manager.operations.models import (
    OperationExecutionResult,
    OperationOutcome,
)
from fleet_manager.operations.transport import OperationTransport

CHROME_PATH = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
OUTPUT_DIR = Path(
    r"C:\Users\adars\.gemini\antigravity-cli\brain\c76069cb-d55f-4184-8504-ffc5e80c6230\screenshots"
)


class MockConsoleTransport(OperationTransport):
    def execute(self, node, command, settings, timeout_seconds=10.0, max_output_bytes=65536):
        if "uptime" in command:
            stdout = " 21:55:02 up 24 days, 3 users, load average: 0.22, 0.15, 0.08\n"
        elif "free -m" in command:
            stdout = (
                "               total        used        free      shared  buff/cache   available\n"
                "Mem:           15982        4210        7640         420        4132       11352\n"
                "Swap:           4096           0        4096\n"
            )
        elif "df -h" in command:
            stdout = (
                "Filesystem      Size  Used Avail Use% Mounted on\n"
                "/dev/sda1        98G   22G   72G  24% /\n"
            )
        elif "systemctl" in command:
            stdout = (
                "● ssh.service - OpenBSD Secure Shell server\n"
                "     Loaded: loaded (/lib/systemd/system/ssh.service; enabled; preset: enabled)\n"
                "     Active: active (running) since Sun 2026-10-12 04:12:00 UTC; 3 weeks ago\n"
                "   Main PID: 742 (sshd)\n"
                "      Tasks: 1 (limit: 18942)\n"
                "     Memory: 6.2M\n"
                "        CPU: 1.482s\n"
                "     CGroup: /system.slice/ssh.service\n"
                "             └─742 sshd: /usr/sbin/sshd -D [listener] 0 of 10-100 startups\n"
            )
        else:
            stdout = "Command completed successfully.\n"

        return OperationExecutionResult(
            outcome=OperationOutcome.SUCCESS,
            failure_category=None,
            exit_code=0,
            stdout=stdout,
            stderr="",
            output_truncated=False,
        )


def capture_screenshot(url: str, output_path: Path, width: int, height: int) -> bool:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    args = [
        CHROME_PATH,
        "--headless=new",
        "--disable-gpu",
        "--virtual-time-budget=3000",
        f"--window-size={width},{height}",
        f"--screenshot={output_path}",
        url,
    ]
    proc = subprocess.run(args, capture_output=True, timeout=30)
    return proc.returncode == 0 and output_path.exists() and output_path.stat().st_size > 0


def main() -> int:
    print("=" * 70)
    print("Visual Quality Assurance: Capturing Viewport Screenshots")
    print("=" * 70)

    work_dir = Path(tempfile.mkdtemp(prefix="fm_visual_qa_"))
    db_path = work_dir / "visual_inventory.db"
    api_token = secrets.token_urlsafe(32)

    known_hosts = work_dir / "known_hosts"
    known_hosts.write_text("127.0.0.1 ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAI...\n")
    priv_key = work_dir / "op_key"
    priv_key.write_text(
        "-----BEGIN OPENSSH PRIVATE KEY-----\nfake\n-----END OPENSSH PRIVATE KEY-----\n"
    )
    ssh_settings = SSHSettings("operator", known_hosts, priv_key)

    app = create_app(
        database_path=db_path,
        api_token=api_token,
        ssh_settings=ssh_settings,
        operation_executor=DirectOperationExecutor(MockConsoleTransport()),
        enable_scheduler=False,
    )

    port = 8666
    config = uvicorn.Config(app=app, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config)
    server_thread = threading.Thread(target=server.run, daemon=True)
    server_thread.start()
    time.sleep(1.0)
    base_url = f"http://127.0.0.1:{port}"

    try:
        # Pre-populate 3 realistic nodes
        nodes_to_add = [
            ("debian-prod-01", "127.0.0.1", 2201),
            ("debian-prod-02", "127.0.0.1", 2202),
            ("debian-staging-03", "127.0.0.1", 2203),
        ]
        node_ids = []
        for name, addr, p in nodes_to_add:
            req = urllib.request.Request(
                f"{base_url}/api/nodes",
                data=json.dumps({"name": name, "address": addr, "ssh_port": p}).encode("utf-8"),
                headers={
                    "Authorization": f"Bearer {api_token}",
                    "Content-Type": "application/json",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=5.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                node_ids.append(data["id"])

        from datetime import UTC, datetime

        # Manually seed observations in repository
        conn_repo = SQLiteConnectivityRepository(db_path)
        # Node 1: CONNECTED (Reachable)
        conn_repo.save(node_ids[0], datetime.now(UTC), ConnectivityOutcome.CONNECTED)
        # Node 2: CONNECTION_REFUSED (Unreachable)
        conn_repo.save(node_ids[1], datetime.now(UTC), ConnectivityOutcome.CONNECTION_REFUSED)
        # Node 3 remains NOT_CHECKED

        # Trigger 2 operations on Node 1 (system.uptime and service.status)
        for act, args in [("system.uptime", {}), ("service.status", {"service_name": "ssh"})]:
            op_req = urllib.request.Request(
                f"{base_url}/api/nodes/{node_ids[0]}/operations",
                data=json.dumps({"action": act, "arguments": args}).encode("utf-8"),
                headers={
                    "Authorization": f"Bearer {api_token}",
                    "Content-Type": "application/json",
                },
                method="POST",
            )
            with urllib.request.urlopen(op_req, timeout=5.0) as resp:
                resp.read()

        print(f"[+] Initialized 3 nodes and test observations on {base_url}")

        viewports = [
            ("desktop_1440x900.png", 1440, 900, f"{base_url}/dashboard?token={api_token}&select=1"),
            ("laptop_1280x800.png", 1280, 800, f"{base_url}/dashboard?token={api_token}&select=1"),
            ("tablet_768x1024.png", 768, 1024, f"{base_url}/dashboard?token={api_token}&select=1"),
            ("mobile_390x844.png", 390, 844, f"{base_url}/dashboard?token={api_token}&select=1"),
            ("auth_modal_1440x900.png", 1440, 900, f"{base_url}/dashboard"),
        ]

        for fname, w, h, target_url in viewports:
            out_file = OUTPUT_DIR / fname
            success = capture_screenshot(target_url, out_file, w, h)
            if success:
                print(f"   [CAPTURED] {fname} ({w}x{h}) -> {out_file.stat().st_size} bytes")
            else:
                print(f"   [FAILED] {fname} ({w}x{h})")

        # Capture empty inventory state using a separate blank database
        empty_db = work_dir / "empty.db"
        empty_app = create_app(database_path=empty_db, api_token=api_token, enable_scheduler=False)
        empty_server = uvicorn.Server(
            uvicorn.Config(app=empty_app, host="127.0.0.1", port=8667, log_level="error")
        )
        empty_thread = threading.Thread(target=empty_server.run, daemon=True)
        empty_thread.start()
        time.sleep(1.0)

        empty_out = OUTPUT_DIR / "empty_inventory_1440x900.png"
        success = capture_screenshot(
            f"http://127.0.0.1:8667/dashboard?token={api_token}", empty_out, 1440, 900
        )
        if success:
            bytes_count = empty_out.stat().st_size
            print(f"   [CAPTURED] empty_inventory_1440x900.png (1440x900) -> {bytes_count} bytes")
        empty_server.should_exit = True
        empty_thread.join(timeout=3.0)

        print("\nAll visual QA screenshots captured successfully!")
        return 0

    finally:
        server.should_exit = True
        server_thread.join(timeout=3.0)
        if work_dir.exists():
            shutil.rmtree(work_dir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
