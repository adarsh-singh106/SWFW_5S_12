"""Isolated Chrome/CDP acceptance runner. No dependency install or remote SSH."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import secrets
import socket
import subprocess
import tempfile
import threading
import time
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import httpx
import paramiko
import uvicorn
from fastapi import Request
from fastapi.responses import JSONResponse

from fleet_manager.config import SSHSettings
from fleet_manager.connectivity.models import ConnectivityOutcome
from fleet_manager.connectivity.trust import calculate_fingerprint, format_known_hosts_entry
from fleet_manager.inventory.models import NewNode
from fleet_manager.main import create_app
from fleet_manager.metrics.health import PrometheusHealth
from fleet_manager.operations.models import (
    OperationExecutionResult,
    OperationOutcome,
    OperationRecord,
)

ROOT = Path(__file__).resolve().parents[1]
CHROME = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")


class FakeSSH:
    def __init__(self, controls):
        self.controls = controls

    def verify(self, node, settings):
        return (
            ConnectivityOutcome.AUTH_FAILED
            if self.controls["ssh_fail"]
            else ConnectivityOutcome.CONNECTED
        )


class FakeOperations:
    def execute(self, node, command, settings, timeout_seconds=10, max_output_bytes=65536):
        return OperationExecutionResult(
            OperationOutcome.SUCCESS, None, 0, "isolated uptime\n", "", False
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inject-failure", action="store_true")
    parser.add_argument("--first-run", action="store_true")
    args = parser.parse_args()
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%S") + "-" + secrets.token_hex(4)
    output = ROOT / ".local" / "browser-qa" / run_id
    output.mkdir(parents=True, exist_ok=False)
    evidence = {"run_id": run_id, "output": str(output), "cleanup": False}
    server = None
    thread = None
    chrome = None
    driver = None
    sock = None
    exit_code = 1
    scratch = tempfile.TemporaryDirectory(prefix="fm_browser_qa_")
    work = Path(scratch.name)
    evidence["temporary_directory"] = str(work)
    try:
        token = secrets.token_urlsafe(32)
        key = paramiko.RSAKey.generate(2048)
        private = work / "operator.key"
        key.write_private_key_file(str(private))
        hosts = work / "known_hosts"
        hosts.write_text(
            format_known_hosts_entry("127.0.0.1", 2201, key.get_name(), key.get_base64())
        )
        settings = SSHSettings("operator", hosts, private)
        controls = {
            "outage": False,
            "delay": 0.0,
            "ssh_fail": False,
            "scan_mismatch": False,
            "health_mode": "varying",
        }
        app = create_app(
            database_path=work / "inventory.db",
            api_token=token,
            initial_password="" if args.first_run else "CHANGEME",
            enable_password_auth=True,
            ssh_settings=settings,
            ssh_transport=FakeSSH(controls),
            operation_transport=FakeOperations(),
            enable_scheduler=False,
        )

        @app.middleware("http")
        async def qa_controls(request: Request, call_next):
            if request.url.path == "/__qa/owner":
                return JSONResponse({"owner": run_id})
            if request.url.path == "/__qa/control":
                if request.headers.get("authorization") != "Bearer " + token:
                    return JSONResponse({}, status_code=401)
                changes = await request.json()
                if changes.pop("expire_sessions", False):
                    app.state.session_store.clear()
                controls.update(changes)
                return JSONResponse({"ok": True})
            if request.url.path.startswith("/api/") and controls["outage"]:
                return JSONResponse({"error": {"message": "QA controlled outage"}}, status_code=503)
            if request.url.path == "/api/nodes/2/onboarding" and controls["delay"]:
                await asyncio.sleep(float(controls["delay"]))
            return await call_next(request)

        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        base = f"http://127.0.0.1:{port}"
        server = uvicorn.Server(uvicorn.Config(app, log_level="error", access_log=False))
        thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
        # Fake BOTH scan call sites for the test; enrollment executes real locking/writes.
        mismatch_key = paramiko.RSAKey.generate(2048)

        def presented_key(address, port, timeout):
            scanned_key = mismatch_key if controls["scan_mismatch"] and port == 2201 else key
            return (
                scanned_key.get_name(),
                scanned_key.get_base64(),
                calculate_fingerprint(scanned_key),
            )

        with (
            patch(
                "fleet_manager.connectivity.router.get_presented_host_key",
                side_effect=presented_key,
            ),
            patch(
                "fleet_manager.connectivity.trust.get_presented_host_key",
                side_effect=presented_key,
            ),
        ):
            thread.start()
            deadline = time.monotonic() + 15
            while not server.started:
                if not thread.is_alive() or time.monotonic() > deadline:
                    raise RuntimeError("Owned test server failed startup")
                time.sleep(0.05)
            with urllib.request.urlopen(base + "/__qa/owner", timeout=3) as response:
                assert json.load(response)["owner"] == run_id
            inv = app.state.inventory_repository

            def prometheus_fixture(request: httpx.Request) -> httpx.Response:
                query = request.url.params.get("query", "")
                mode = controls["health_mode"]
                if mode == "unavailable":
                    raise httpx.ConnectError("QA unavailable")
                evaluation = float(
                    request.url.params.get("time", request.url.params.get("end", time.time()))
                )
                is_source = "timestamp(" in query
                if is_source and "timestamp(up{" in query:
                    data = {
                        "resultType": "vector",
                        "result": [
                            {
                                "metric": {},
                                "value": [
                                    evaluation,
                                    str(evaluation - (200 if mode == "stale" else 10)),
                                ],
                            }
                        ],
                    }
                    return httpx.Response(200, json={"status": "success", "data": data})
                if query.startswith("up{"):
                    stamp = time.time()
                    rows = [
                        {
                            "metric": {
                                "node_id": str(node_id),
                                "instance": f"127.0.0.1:{9100 + node_id}",
                            },
                            "value": [stamp, "1" if node_id == 1 else "0"],
                        }
                        for node_id in (1, 2, 3)
                    ]
                    return httpx.Response(
                        200,
                        json={
                            "status": "success",
                            "data": {"resultType": "vector", "result": rows},
                        },
                    )
                elif query.startswith("100 * (1 - (node_memory"):
                    value = "50"
                elif "MemTotal" in query or "filesystem_size" in query:
                    value = "8589934592"
                elif "MemAvailable" in query or "filesystem_avail" in query:
                    value = "4294967296"
                elif "boot_time" in query:
                    value = "7200"
                elif "load1" in query:
                    value = "0.8"
                elif "network" in query:
                    value = "1500"
                else:
                    value = "27.5"
                stamp = evaluation
                if request.url.path.endswith("query_range"):
                    count = 2 if mode == "constant" else 25
                    values = []
                    for index in range(count):
                        tick = stamp - (count - 1 - index) * 150
                        if mode == "missing" and 8 <= index <= 14:
                            continue
                        sample = tick - 10 if is_source else float(value)
                        if not is_source and mode != "constant":
                            sample *= 0.5 + (index % 7) / 12
                        values.append([tick, str(sample)])
                    data = {
                        "resultType": "matrix",
                        "result": [{"metric": {}, "values": values}],
                    }
                else:
                    data = {
                        "resultType": "vector",
                        "result": [
                            {
                                "metric": {},
                                "value": [stamp, str(stamp - 10) if is_source else value],
                            }
                        ],
                    }
                return httpx.Response(200, json={"status": "success", "data": data})

            app.state.prometheus_health = PrometheusHealth(
                transport=httpx.MockTransport(prometheus_fixture)
            )
            evidence["telemetry_source"] = "Mocked Prometheus fixture; no live host measurements"
            service = app.state.connectivity_service
            ready = inv.add_node(NewNode("alpha-ready", "127.0.0.1", 2201))
            inv.add_node(NewNode("beta-pending", "127.0.0.1", 2202))
            inv.add_node(NewNode("gamma-pending", "127.0.0.1", 2203))
            service.check(ready.id)
            for index in range(25):
                now = datetime.now(UTC)
                app.state.operations_repository.create(
                    OperationRecord(
                        id=f"qa-{index:03}",
                        node_id=ready.id,
                        action="system.uptime",
                        arguments={},
                        requested_at=now,
                        started_at=now,
                        completed_at=now,
                        outcome=OperationOutcome.SUCCESS,
                        failure_category=None,
                        exit_code=0,
                        stdout="isolated output",
                        stderr="",
                        output_truncated=False,
                        audit_metadata={},
                    )
                )
            profile = work / "chrome-profile"
            chrome = subprocess.Popen(
                [
                    str(CHROME),
                    "--headless=new",
                    "--disable-gpu",
                    "--no-first-run",
                    "--no-default-browser-check",
                    "--disable-background-networking",
                    "--disable-component-update",
                    "--disable-sync",
                    "--metrics-recording-only",
                    "--proxy-server=http://127.0.0.1:9",
                    "--proxy-bypass-list=127.0.0.1;localhost",
                    "--remote-debugging-port=0",
                    f"--user-data-dir={profile}",
                    "about:blank",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            evidence["chrome_pid"] = chrome.pid
            active = profile / "DevToolsActivePort"
            deadline = time.monotonic() + 15
            while not active.exists():
                if chrome.poll() is not None or time.monotonic() > deadline:
                    raise RuntimeError("Owned Chrome failed startup")
                time.sleep(0.05)
            debug_port = int(active.read_text().splitlines()[0])
            driver = subprocess.Popen(
                ["node", str(ROOT / "scripts/browser_qa.cjs")],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            payload = json.dumps(
                {
                    "base": base,
                    "token": token,
                    "debugPort": debug_port,
                    "output": str(output),
                    "injectFailure": args.inject_failure,
                    "firstRun": args.first_run,
                }
            )
            stdout, stderr = driver.communicate(payload, timeout=150)
            (output / "driver-stdout.txt").write_text(stdout, encoding="utf-8")
            (output / "driver-stderr.txt").write_text(stderr, encoding="utf-8")
            exit_code = driver.returncode
            evidence["driver_exit"] = exit_code
    except Exception as exc:
        evidence["error"] = type(exc).__name__ + ": " + str(exc)
    finally:
        if driver is not None and driver.poll() is None:
            driver.kill()
            driver.wait(timeout=5)
        if chrome is not None:
            try:
                chrome.wait(timeout=5)
            except subprocess.TimeoutExpired:
                if os.name == "nt":
                    subprocess.run(
                        ["taskkill", "/PID", str(chrome.pid), "/T", "/F"],
                        capture_output=True,
                        timeout=10,
                    )
                else:
                    chrome.terminate()
                chrome.wait(timeout=10)
        if server is not None:
            server.should_exit = True
        if thread is not None:
            thread.join(timeout=10)
        if sock is not None:
            sock.close()
        try:
            scratch.cleanup()
            evidence["cleanup"] = (
                not work.exists()
                and (thread is None or not thread.is_alive())
                and (chrome is None or chrome.poll() is not None)
            )
        except OSError as exc:
            evidence["cleanup_error"] = str(exc)
        (output / "runner.json").write_text(json.dumps(evidence, indent=2), encoding="utf-8")
        print(json.dumps(evidence, indent=2))
    return exit_code if evidence["cleanup"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
