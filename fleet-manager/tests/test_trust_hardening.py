"""Trust regression contracts; all keys and trust files are disposable fixtures."""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import patch

import paramiko
import pytest

from fleet_manager.connectivity import trust
from fleet_manager.errors import ConnectivityConfigurationError


@pytest.fixture(scope="module")
def keys() -> tuple[paramiko.RSAKey, paramiko.RSAKey]:
    return paramiko.RSAKey.generate(1024), paramiko.RSAKey.generate(1024)


def presented(key: paramiko.PKey) -> tuple[str, str, str]:
    return key.get_name(), key.get_base64(), trust.calculate_fingerprint(key)


def entry(host: str, port: int, key: paramiko.PKey) -> str:
    return trust.format_known_hosts_entry(host, port, key.get_name(), key.get_base64())


@pytest.mark.parametrize(
    ("host", "port", "identity"),
    [
        ("192.0.2.1", 22, "192.0.2.1"),
        ("192.0.2.1", 2222, "[192.0.2.1]:2222"),
        ("2001:db8::1", 22, "2001:db8::1"),
        ("2001:db8::1", 2222, "[2001:db8::1]:2222"),
        ("[2001:db8::1]", 2222, "[2001:db8::1]:2222"),
    ],
)
def test_endpoint_identity(host: str, port: int, identity: str) -> None:
    assert trust.format_known_hosts_entry(host, port, "ssh-rsa", "AAAA") == (
        f"{identity} ssh-rsa AAAA\n"
    )


def test_port_22_trust_never_implies_port_2222(tmp_path: Path, keys: tuple) -> None:
    path = tmp_path / "known_hosts"
    path.write_text(entry("host.test", 22, keys[0]), encoding="utf-8")
    assert trust.check_host_key_trust("host.test", 22, path, *presented(keys[0])[:2]) == "TRUSTED"
    assert (
        trust.check_host_key_trust("host.test", 2222, path, *presented(keys[0])[:2]) == "UNTRUSTED"
    )


def test_enrollment_preserves_other_port_and_unrelated_bytes(tmp_path: Path, keys: tuple) -> None:
    path = tmp_path / "known_hosts"
    original = ("# retained comment\r\n" + entry("host.test", 22, keys[0])).encode()
    path.write_bytes(original)
    with patch.object(trust, "get_presented_host_key", return_value=presented(keys[1])):
        trust.enroll_host_key("host.test", 2222, path, presented(keys[1])[2])
    assert path.read_bytes().startswith(original)
    assert trust.check_host_key_trust("host.test", 22, path, *presented(keys[0])[:2]) == "TRUSTED"
    assert trust.check_host_key_trust("host.test", 2222, path, *presented(keys[1])[:2]) == "TRUSTED"


@pytest.mark.parametrize("duplicate", [False, True])
def test_changed_or_ambiguous_trust_cannot_be_replaced(
    tmp_path: Path, keys: tuple, duplicate: bool
) -> None:
    path = tmp_path / "known_hosts"
    original = entry("host.test", 22, keys[0])
    if duplicate:
        original += entry("host.test", 22, keys[1])
    path.write_bytes(original.encode())
    with patch.object(trust, "get_presented_host_key", return_value=presented(keys[1])):
        with pytest.raises((ValueError, ConnectivityConfigurationError)):
            trust.enroll_host_key("host.test", 22, path, presented(keys[1])[2])
    assert path.read_bytes() == original.encode()


def test_duplicate_matching_entry_cannot_hide_changed_key(tmp_path: Path, keys: tuple) -> None:
    path = tmp_path / "known_hosts"
    path.write_text(entry("host.test", 22, keys[0]) + entry("host.test", 22, keys[1]))
    assert trust.check_host_key_trust("host.test", 22, path, *presented(keys[0])[:2]) != "TRUSTED"


def test_existing_matching_enrollment_is_byte_preserving(tmp_path: Path, keys: tuple) -> None:
    path = tmp_path / "known_hosts"
    original = ("# comment\r\n" + entry("host.test", 22, keys[0])).encode()
    path.write_bytes(original)
    with patch.object(trust, "get_presented_host_key", return_value=presented(keys[0])):
        trust.enroll_host_key("host.test", 22, path, presented(keys[0])[2])
    assert path.read_bytes() == original


@pytest.mark.parametrize("bad", [b"host ssh-rsa not-base64!\n", b"not a host entry\n", b"\xff"])
def test_malformed_store_fails_closed(tmp_path: Path, keys: tuple, bad: bytes) -> None:
    path = tmp_path / "known_hosts"
    path.write_bytes(bad)
    with patch.object(trust, "get_presented_host_key", return_value=presented(keys[0])):
        with pytest.raises((ValueError, ConnectivityConfigurationError)):
            trust.enroll_host_key("host.test", 22, path, presented(keys[0])[2])
    assert path.read_bytes() == bad


def test_unreadable_store_never_becomes_empty_replacement(tmp_path: Path, keys: tuple) -> None:
    path = tmp_path / "known_hosts"
    original = entry("other.test", 22, keys[0]).encode()
    path.write_bytes(original)
    real_open = Path.open

    def deny_target(self: Path, *args: object, **kwargs: object):
        if self == path:
            raise PermissionError("simulated unreadable trust file")
        return real_open(self, *args, **kwargs)

    with (
        patch.object(trust, "get_presented_host_key", return_value=presented(keys[1])),
        patch.object(Path, "open", deny_target),
    ):
        with pytest.raises((OSError, ConnectivityConfigurationError)):
            trust.enroll_host_key("new.test", 22, path, presented(keys[1])[2])
    assert path.read_bytes() == original


def test_independent_process_enrollments_preserve_every_endpoint(
    tmp_path: Path, keys: tuple
) -> None:
    path = tmp_path / "known_hosts"
    path.write_text("# original\n")
    gate = tmp_path / "start"
    script = """
import sys, time
from pathlib import Path
from fleet_manager.connectivity import trust
path, gate, host, key_type, key_data, fingerprint = sys.argv[1:]
Path(gate).with_name(host + '.ready').touch()
def scan(*args, **kwargs):
    deadline = time.monotonic() + 20
    while not Path(gate).exists():
        if time.monotonic() > deadline: raise RuntimeError('gate timeout')
        time.sleep(0.005)
    return key_type, key_data, fingerprint
trust.get_presented_host_key = scan
trust.enroll_host_key(host, 22, Path(path), fingerprint)
"""
    processes = []
    try:
        for index in range(8):
            processes.append(
                subprocess.Popen(
                    [
                        sys.executable,
                        "-c",
                        script,
                        str(path),
                        str(gate),
                        f"node-{index}.test",
                        *presented(keys[0]),
                    ],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    env=os.environ.copy(),
                )
            )
        deadline = time.monotonic() + 20
        while len(list(tmp_path.glob("*.ready"))) != len(processes):
            assert time.monotonic() < deadline, "Child enrollment startup timed out"
            time.sleep(0.01)
        gate.touch()
        for process in processes:
            _, stderr = process.communicate(timeout=30)
            assert process.returncode == 0, stderr.decode()
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)
    for index in range(8):
        assert (
            trust.check_host_key_trust(f"node-{index}.test", 22, path, *presented(keys[0])[:2])
            == "TRUSTED"
        )


@pytest.mark.parametrize("filename", ["operator", "operator.key"])
def test_matching_public_sidecar_is_validated(tmp_path: Path, keys: tuple, filename: str) -> None:
    private = tmp_path / filename
    keys[0].write_private_key_file(str(private))
    public = f"{keys[0].get_name()} {keys[0].get_base64()} harmless-comment"
    Path(str(private) + ".pub").write_text(public)
    assert trust.get_operator_public_key(private) == public


@pytest.mark.parametrize("material", ["mismatched", "invalid", "private"])
def test_sidecar_must_be_valid_public_key_matching_private(
    tmp_path: Path, keys: tuple, material: str
) -> None:
    private = tmp_path / "operator.key"
    keys[0].write_private_key_file(str(private))
    contents = {
        "mismatched": f"{keys[1].get_name()} {keys[1].get_base64()}",
        "invalid": "arbitrary unchecked file content",
        "private": private.read_text(),
    }[material]
    Path(str(private) + ".pub").write_text(contents)
    with pytest.raises(ConnectivityConfigurationError):
        trust.get_operator_public_key(private)


def test_bootstrap_quotes_untrusted_comment_and_creates_secure_directory(keys: tuple) -> None:
    public = f"{keys[0].get_name()} {keys[0].get_base64()} $(harmless) `noop` ' quoted"
    command = trust.generate_bootstrap_instruction("operator", public)
    assert shlex.quote(public) in command
    assert "mkdir" in command and "700" in command
    assert "600" in command and "authorized_keys" in command
    assert "operator" in command
    assert "awk" in command  # Compare key type/data independently of mutable comments.
    assert "PRIVATE KEY" not in command
