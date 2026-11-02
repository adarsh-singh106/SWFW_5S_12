#!/usr/bin/env python3
"""Setup and teardown helper for the 3 isolated SSH/exporter service endpoints on WSL2.

This script manages disposable local test endpoints on loopback ports:
  - endpoint-alpha: SSH 2201, Node Exporter 9101
  - endpoint-beta:  SSH 2202, Node Exporter 9102
  - endpoint-gamma: SSH 2203, Node Exporter 9103

Failure Domain Transparency:
  These endpoints share the WSL2 Linux kernel, root filesystem, and underlying
  system resource metrics. They isolate process execution trees, cryptographic
  host identities, network ports, and service availability.
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

DEFAULT_BASE_DIR = Path("/tmp/fleet_three_endpoints")
DEFAULT_TARGETS_PATH = Path("/etc/prometheus/targets.json")
DEFAULT_BACKUP_PATH = Path("/etc/prometheus/targets.json.fleet_orig")

ENDPOINTS = [
    {"name": "endpoint-alpha", "ssh_port": 2201, "exporter_port": 9101, "node_id": 1},
    {"name": "endpoint-beta", "ssh_port": 2202, "exporter_port": 9102, "node_id": 2},
    {"name": "endpoint-gamma", "ssh_port": 2203, "exporter_port": 9103, "node_id": 3},
]


def _run_cmd(cmd: list[str], timeout: float = 10.0) -> str:
    res = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=timeout)
    return res.stdout.strip()


def is_pid_alive(pid: int) -> bool:
    """Check if a process with given PID exists."""
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def is_process_owned(pid: int, expected_tokens: list[str]) -> bool:
    """Verify that a PID exists and its command line contains the expected tokens.

    Prevents terminating unrelated processes if PIDs were reused.
    """
    if not is_pid_alive(pid):
        return False
    if os.name == "posix" and Path("/proc").is_dir():
        cmdline_file = Path(f"/proc/{pid}/cmdline")
        if not cmdline_file.exists():
            return False
        try:
            cmdline = (
                cmdline_file.read_bytes().decode("latin1", errors="replace").replace("\x00", " ")
            )
            return all(tok in cmdline for tok in expected_tokens)
        except Exception:
            return False
    return True


def check_port_conflicts(endpoints: list[dict], host: str = "127.0.0.1") -> list[int]:
    """Check whether any of the endpoint ports are already bound on host."""
    conflicts: list[int] = []
    ports_to_check: list[int] = []
    for ep in endpoints:
        ports_to_check.extend([ep["ssh_port"], ep["exporter_port"]])

    for port in sorted(set(ports_to_check)):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(0.2)
                res = s.connect_ex((host, port))
                if res == 0:
                    conflicts.append(port)
        except Exception:
            pass
    return conflicts


def is_setup_active(base_dir: Path) -> bool:
    """Return True if an active setup with running tracked processes already exists."""
    marker = base_dir / ".fleet_managed"
    pids_dir = base_dir / "pids"
    if not marker.exists() or not pids_dir.exists():
        return False

    for pid_file in pids_dir.glob("*.pid"):
        try:
            pid = int(pid_file.read_text().strip())
            if is_pid_alive(pid):
                return True
        except Exception:
            pass
    return False


def rollback_startup(
    base_dir: Path,
    targets_path: Path,
    backup_path: Path,
    targets_existed_originally: bool,
) -> None:
    """Roll back partially started services and restore configuration on startup failure."""
    print("[!] Rolling back partial startup...", file=sys.stderr)
    stop(
        base_dir=base_dir,
        targets_path=targets_path,
        backup_path=backup_path,
        targets_existed_originally=targets_existed_originally,
    )


def start(
    base_dir: Path = DEFAULT_BASE_DIR,
    targets_path: Path = DEFAULT_TARGETS_PATH,
    backup_path: Path = DEFAULT_BACKUP_PATH,
) -> int:
    """Initialize and start the 3 isolated SSH and Node Exporter endpoints."""
    # 1. Guard against duplicate active setups
    if is_setup_active(base_dir):
        print(
            f"[!] Error: An active 3-endpoint setup is already running in {base_dir}. "
            "Run 'stop' first.",
            file=sys.stderr,
        )
        return 1

    # 2. Port conflict pre-flight check
    conflicts = check_port_conflicts(ENDPOINTS)
    if conflicts:
        print(
            f"[!] Error: Port conflict detected. Ports {conflicts} in use on 127.0.0.1. "
            "Aborting setup to prevent collisions.",
            file=sys.stderr,
        )
        return 1

    targets_existed_originally = targets_path.exists()
    keys_dir = base_dir / "keys"
    configs_dir = base_dir / "configs"
    pids_dir = base_dir / "pids"

    try:
        print(f"[*] Initializing 3-endpoint environment in {base_dir}...")
        base_dir.mkdir(parents=True, exist_ok=True)
        keys_dir.mkdir(parents=True, exist_ok=True)
        configs_dir.mkdir(parents=True, exist_ok=True)
        pids_dir.mkdir(parents=True, exist_ok=True)

        # Write managed ownership marker
        marker_data = {
            "managed_by": "setup_three_endpoints.py",
            "targets_existed_originally": targets_existed_originally,
            "created_at": time.time(),
        }
        (base_dir / ".fleet_managed").write_text(json.dumps(marker_data), encoding="utf-8")

        # 1. Generate client observer key if missing
        observer_key = keys_dir / "observer_key"
        if not observer_key.exists():
            _run_cmd(["ssh-keygen", "-t", "ed25519", "-N", "", "-f", str(observer_key)])

        # 2. Write authorized_keys
        auth_keys_path = keys_dir / "authorized_keys"
        auth_keys_path.write_text(Path(f"{observer_key}.pub").read_text(encoding="utf-8"))

        # 3. Generate distinct host keys and build known_hosts
        known_hosts_lines: list[str] = []
        for ep in ENDPOINTS:
            host_key = keys_dir / f"host_{ep['name']}"
            if not host_key.exists():
                _run_cmd(["ssh-keygen", "-t", "ed25519", "-N", "", "-f", str(host_key)])
            pub_content = Path(f"{host_key}.pub").read_text(encoding="utf-8").strip()
            parts = pub_content.split()
            if len(parts) >= 2:
                key_type, key_b64 = parts[0], parts[1]
                known_hosts_lines.append(f"[127.0.0.1]:{ep['ssh_port']} {key_type} {key_b64}")

        known_hosts_path = keys_dir / "known_hosts"
        known_hosts_path.write_text("\n".join(known_hosts_lines) + "\n", encoding="utf-8")

        # Set proper permissions so sshd and ssh client are happy
        if os.name == "posix" and hasattr(os, "geteuid") and os.geteuid() == 0:
            target_user = os.getenv("SUDO_USER") or os.getenv("FLEET_MANAGER_SSH_USER") or "ash"
            _run_cmd(["chown", "-R", f"{target_user}:{target_user}", str(base_dir)])

        if os.name == "posix":
            _run_cmd(
                [
                    "chmod",
                    "755",
                    str(base_dir),
                    str(keys_dir),
                    str(configs_dir),
                    str(pids_dir),
                ]
            )
            _run_cmd(["chmod", "600", str(observer_key)])
            _run_cmd(["chmod", "644", str(known_hosts_path), str(auth_keys_path)])
            for ep in ENDPOINTS:
                _run_cmd(["chmod", "600", str(keys_dir / f"host_{ep['name']}")])
                _run_cmd(["chmod", "644", str(keys_dir / f"host_{ep['name']}.pub")])

        # 4. Generate sshd configs and launch sshd processes
        for ep in ENDPOINTS:
            name = ep["name"]
            ssh_port = ep["ssh_port"]
            pid_file = pids_dir / f"sshd_{name}.pid"
            host_key = keys_dir / f"host_{name}"
            config_path = configs_dir / f"sshd_{name}.conf"

            config_content = f"""Port {ssh_port}
ListenAddress 127.0.0.1
HostKey {host_key}
AuthorizedKeysFile {auth_keys_path}
StrictModes no
PidFile {pid_file}
UsePAM yes
PasswordAuthentication no
KbdInteractiveAuthentication no
Subsystem sftp /usr/lib/openssh/sftp-server
"""
            config_path.write_text(config_content, encoding="utf-8")

            # Launch sshd
            cmd = ["/usr/sbin/sshd", "-f", str(config_path)]
            subprocess.run(cmd, check=True, timeout=10.0)
            print(f"[+] Started sshd for {name} on port {ssh_port}")

        # 5. Launch Node Exporter instances
        for ep in ENDPOINTS:
            name = ep["name"]
            exp_port = ep["exporter_port"]
            pid_file = pids_dir / f"exporter_{name}.pid"
            cmd = [
                "/usr/bin/prometheus-node-exporter",
                f"--web.listen-address=127.0.0.1:{exp_port}",
            ]
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            pid_file.write_text(str(proc.pid), encoding="ascii")
            print(f"[+] Started node_exporter for {name} on port {exp_port} (PID {proc.pid})")

        # 6. Update Prometheus targets.json with backup
        if targets_existed_originally and not backup_path.exists():
            shutil.copy2(targets_path, backup_path)
            print(f"[+] Backed up original Prometheus targets to {backup_path}")

        targets_config = []
        for ep in ENDPOINTS:
            targets_config.append(
                {
                    "targets": [f"127.0.0.1:{ep['exporter_port']}"],
                    "labels": {
                        "node_id": str(ep["node_id"]),
                        "node_name": ep["name"],
                        "job": "node_exporter",
                        "fleet": "local-three-node-demo",
                    },
                }
            )
        targets_path.write_text(json.dumps(targets_config, indent=2), encoding="utf-8")
        print(f"[+] Updated {targets_path} with 3 endpoint targets")

        # 7. Write topology metadata
        topology = {
            "base_dir": str(base_dir),
            "observer_key": str(observer_key),
            "known_hosts": str(known_hosts_path),
            "endpoints": ENDPOINTS,
        }
        (base_dir / "topology.json").write_text(json.dumps(topology, indent=2), encoding="utf-8")
        print("[*] 3-Endpoint topology setup complete!")
        return 0

    except Exception as exc:
        print(f"[!] Startup failed: {exc}", file=sys.stderr)
        rollback_startup(base_dir, targets_path, backup_path, targets_existed_originally)
        return 1


def stop(
    base_dir: Path = DEFAULT_BASE_DIR,
    targets_path: Path = DEFAULT_TARGETS_PATH,
    backup_path: Path = DEFAULT_BACKUP_PATH,
    targets_existed_originally: bool = True,
) -> int:
    """Tear down 3-endpoint environment, terminating only owned processes."""
    print(f"[*] Tearing down 3-endpoint environment in {base_dir}...")

    # Check marker for saved settings if present
    marker = base_dir / ".fleet_managed"
    if marker.exists():
        try:
            m_data = json.loads(marker.read_text(encoding="utf-8"))
            targets_existed_originally = m_data.get(
                "targets_existed_originally", targets_existed_originally
            )
        except Exception:
            pass

    # 1. Terminate only owned sshd and node_exporter processes
    pids_dir = base_dir / "pids"
    if pids_dir.exists():
        for pid_file in pids_dir.glob("*.pid"):
            try:
                pid = int(pid_file.read_text().strip())
                stem = pid_file.stem
                expected_tokens: list[str] = []
                if stem.startswith("sshd_"):
                    name = stem.replace("sshd_", "")
                    expected_tokens = ["sshd", f"sshd_{name}.conf"]
                elif stem.startswith("exporter_"):
                    name = stem.replace("exporter_", "")
                    ep = next((e for e in ENDPOINTS if e["name"] == name), None)
                    exp_port = str(ep["exporter_port"]) if ep else ""
                    expected_tokens = ["node_exporter", exp_port] if exp_port else ["node_exporter"]

                if is_process_owned(pid, expected_tokens):
                    try:
                        os.kill(pid, signal.SIGTERM)
                        print(f"[-] Terminated process {pid} ({stem})")
                    except OSError as e:
                        print(f"[!] Warning killing process {pid} ({stem}): {e}")
                else:
                    if is_pid_alive(pid):
                        print(
                            f"[!] Warning: Process {pid} ({stem}) does not match identity.\n"
                            "    Skipping kill to protect unrelated processes."
                        )
                    else:
                        print(f"[-] Process {pid} ({stem}) is already stopped.")
            except Exception as e:
                print(f"[!] Warning processing {pid_file.name}: {e}")
            finally:
                pid_file.unlink(missing_ok=True)

    # Give processes a moment to exit cleanly
    time.sleep(0.5)

    # 2. Restore Prometheus targets.json safely
    if backup_path.exists():
        shutil.copy2(backup_path, targets_path)
        backup_path.unlink(missing_ok=True)
        print(f"[+] Restored original Prometheus targets from backup to {targets_path}")
    elif not targets_existed_originally and targets_path.exists():
        targets_path.unlink(missing_ok=True)
        print(f"[+] Removed targets file {targets_path} created during setup")

    # 3. Clean up directory only if verified as owned by this script
    if base_dir.exists():
        if marker.exists():
            shutil.rmtree(base_dir, ignore_errors=True)
            print(f"[+] Cleaned up managed directory {base_dir}")
        else:
            print(
                f"[!] Notice: {base_dir} does not contain .fleet_managed marker; skipping deletion."
            )

    print("[*] Teardown complete.")
    return 0


if __name__ == "__main__":
    action = sys.argv[1] if len(sys.argv) > 1 else "start"
    if action == "start":
        sys.exit(start())
    elif action == "stop":
        sys.exit(stop())
    else:
        print(f"Usage: {sys.argv[0]} [start|stop]", file=sys.stderr)
        sys.exit(1)
