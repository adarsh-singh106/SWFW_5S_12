"""SSH trust mechanisms: server identity (host-key) verification and client credential management.

CRITICAL ARCHITECTURAL DISTINCTION:
1. Server identity / host-key trust:
   The managed server presents its SSH host public key during key exchange.
   Fleet Manager MUST validate its fingerprint against an explicitly trusted source (known_hosts).
   Unknown host keys are rejected until verified out-of-band by the operator.
   Mismatched host keys are strictly rejected (preventing MitM attacks).
   Never blind-trust arbitrary ssh-keyscan responses without independent fingerprint verification.

2. Client authentication:
   Fleet Manager authenticates using its configured private key (settings.private_key_path).
   The matching public key must already be authorized for the remote user in ~/.ssh/authorized_keys.
   The private key is NEVER exposed in the browser or persisted in plaintext database fields.
   A copyable public key bootstrap command is provided for authorized manual enrollment.
"""

from __future__ import annotations

import base64
import hashlib
import ipaddress
import os
import shlex
import socket
import stat
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Final

import paramiko

from fleet_manager.errors import ConnectivityConfigurationError

DEFAULT_SSH_TIMEOUT: Final[float] = 5.0


def normalize_address(address: str) -> str:
    value = address.strip().strip("[]")
    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        if not value or any(c.isspace() or c in ",|*?![]" for c in value):
            raise ValueError("Invalid SSH endpoint") from None
        return value.lower().rstrip(".")


def endpoint_identity(address: str, port: int) -> str:
    if not 1 <= port <= 65535:
        raise ValueError("Invalid SSH port")
    address = normalize_address(address)
    return address if port == 22 else f"[{address}]:{port}"


def calculate_fingerprint(key: paramiko.PKey) -> str:
    """Calculate the standard OpenSSH SHA256 base64 fingerprint without padding."""
    digest = hashlib.sha256(key.asbytes()).digest()
    encoded = base64.b64encode(digest).decode("ascii").rstrip("=")
    return f"SHA256:{encoded}"


def get_presented_host_key(
    address: str, port: int, timeout: float = DEFAULT_SSH_TIMEOUT
) -> tuple[str, str, str]:
    """Connect to the endpoint and perform key exchange to retrieve the presented host key.

    Does NOT authenticate or accept the key.
    Returns:
        tuple of (key_type, base64_key, sha256_fingerprint)
    """
    transport: paramiko.Transport | None = None
    try:
        sock = socket.create_connection((normalize_address(address), port), timeout=timeout)
        transport = paramiko.Transport(sock)
        transport.start_client(timeout=timeout)
        remote_key = transport.get_remote_server_key()
        if remote_key is None:
            raise ConnectivityConfigurationError("No remote server host key presented")
        key_type = remote_key.get_name()
        base64_key = remote_key.get_base64()
        fingerprint = calculate_fingerprint(remote_key)
        return key_type, base64_key, fingerprint
    except (TimeoutError, socket.gaierror, ConnectionRefusedError, OSError) as exc:
        raise ConnectionError(f"Could not connect to {address}:{port}: {exc}") from exc
    except paramiko.SSHException as exc:
        raise ConnectionError(f"SSH key exchange failed for {address}:{port}: {exc}") from exc
    finally:
        if transport is not None:
            try:
                transport.close()
            except Exception:
                pass


def parse_public_key(line: str) -> paramiko.PKey:
    """Accept one OpenSSH public key, never options or private material."""
    try:
        if "PRIVATE KEY" in line or "\n" in line.strip() or "\r" in line.strip():
            raise ValueError("Not a public key")
        parts = line.strip().split(None, 2)
        raw = base64.b64decode(parts[1], validate=True)
        key = paramiko.PKey.from_type_string(parts[0], raw)
        if key.get_name() != parts[0] or key.asbytes() != raw:
            raise ValueError("Invalid key encoding")
        return key
    except Exception as exc:
        raise ConnectivityConfigurationError("Invalid OpenSSH public key") from exc


def _read_store(path: Path) -> tuple[bytes, list[paramiko.hostkeys.HostKeyEntry]]:
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return b"", []
    except OSError as exc:
        raise ConnectivityConfigurationError("Cannot read trusted host keys") from exc
    entries = []
    try:
        for line in raw.decode("utf-8").splitlines():
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            # Paramiko silently skips unsupported keys; enrollment must fail closed.
            entry = paramiko.hostkeys.HostKeyEntry.from_line(line)
            if entry is None or entry.key is None:
                raise ValueError("Unsupported host key entry")
            entries.append(entry)
    except Exception as exc:
        raise ConnectivityConfigurationError("Malformed or unsupported known_hosts entry") from exc
    return raw, entries


def _matches(token: str, identity: str) -> bool:
    if token.startswith("|1|"):
        return paramiko.HostKeys.hash_host(identity, token) == token
    if token.startswith("[") and "]:" in token:
        host, port = token[1:].rsplit("]:", 1)
        return endpoint_identity(host, int(port)) == identity
    return endpoint_identity(token, 22) == identity


def trusted_host_key(address: str, port: int, path: Path) -> paramiko.PKey | None:
    _, entries = _read_store(path)
    return _unique_key(entries, endpoint_identity(address, port))


def _unique_key(
    entries: list[paramiko.hostkeys.HostKeyEntry], identity: str
) -> paramiko.PKey | None:
    keys = [e.key for e in entries if any(_matches(t, identity) for t in e.hostnames)]
    # Even identical duplicate entries require administrative cleanup, not silent rewriting.
    if len(keys) > 1:
        raise ValueError("Ambiguous trusted endpoint: administrative review required")
    return keys[0] if keys else None


def format_known_hosts_entry(address: str, port: int, key_type: str, base64_key: str) -> str:
    return f"{endpoint_identity(address, port)} {key_type} {base64_key}\n"


def check_host_key_trust(
    address: str, port: int, known_hosts_path: Path, key_type: str, base64_key: str
) -> str:
    try:
        key = trusted_host_key(address, port, known_hosts_path)
    except ValueError:
        return "MISMATCH"
    if key is None:
        return "UNTRUSTED"
    return "TRUSTED" if (key.get_name(), key.get_base64()) == (key_type, base64_key) else "MISMATCH"


@contextmanager
def _store_lock(path: Path) -> Iterator[None]:
    """Stable sidecar lock shared by processes; never unlink the lock inode."""
    import sys

    with path.with_name(path.name + ".lock").open("a+b") as lock:
        lock.seek(0, os.SEEK_END)
        if lock.tell() == 0:
            lock.write(b"\0")
            lock.flush()
        deadline = time.monotonic() + 30
        while True:
            try:
                lock.seek(0)
                if sys.platform == "win32":
                    import msvcrt

                    msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise ConnectivityConfigurationError("Host trust store is busy") from None
                time.sleep(0.02)
        try:
            yield
        finally:
            lock.seek(0)
            if sys.platform == "win32":
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def enroll_host_key(
    address: str,
    port: int,
    known_hosts_path: Path,
    expected_fingerprint: str,
    timeout: float = DEFAULT_SSH_TIMEOUT,
) -> str:
    """Append one verified identity. Rotation is deliberately not supported."""
    known_hosts_path = known_hosts_path.resolve()
    known_hosts_path.parent.mkdir(parents=True, exist_ok=True)
    with _store_lock(known_hosts_path):
        raw, entries = _read_store(known_hosts_path)
        trusted = _unique_key(entries, endpoint_identity(address, port))
        key_type, data, fingerprint = get_presented_host_key(
            normalize_address(address), port, timeout
        )
        presented = parse_public_key(f"{key_type} {data}")
        if calculate_fingerprint(presented) != fingerprint or fingerprint != expected_fingerprint:
            raise ValueError("Presented fingerprint differs from operator confirmation")
        if trusted is not None:
            if trusted.asbytes() != presented.asbytes():
                raise ValueError(
                    "Existing trusted identity cannot be replaced; administrative rotation required"
                )
            return fingerprint
        suffix = b"\n" if raw and not raw.endswith(b"\n") else b""
        content = raw + suffix + format_known_hosts_entry(address, port, key_type, data).encode()
        previous = known_hosts_path.stat() if known_hosts_path.exists() else None
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=known_hosts_path.parent, delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(content)
                stream.flush()
                if os.name == "posix":
                    if previous is not None and hasattr(os, "fchown"):
                        os.fchown(stream.fileno(), previous.st_uid, previous.st_gid)
                    os.chmod(temporary, stat.S_IMODE(previous.st_mode) if previous else 0o600)
                os.fsync(stream.fileno())
            temporary.replace(known_hosts_path)
            if os.name == "posix":
                fd = os.open(known_hosts_path.parent, os.O_RDONLY)
                try:
                    os.fsync(fd)
                finally:
                    os.close(fd)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        return fingerprint


def get_operator_public_key(private_key_path: Path) -> str:
    try:
        private = paramiko.PKey.from_path(private_key_path)
        pub_path = Path(str(private_key_path) + ".pub")
        try:
            line = pub_path.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            line = f"{private.get_name()} {private.get_base64()} fleet-manager-operator"
        public = parse_public_key(line)
        if public.asbytes() != private.asbytes() or public.get_name() != private.get_name():
            raise ValueError("Public key does not match configured credential")
        return line
    except Exception as exc:
        raise ConnectivityConfigurationError(
            "Configured client public/private key pair is invalid"
        ) from exc


def generate_bootstrap_instruction(username: str, public_key_line: str) -> str:
    key = parse_public_key(public_key_line)
    # awk compares key data, including entries with authorized_keys options.
    return (
        f"# Execute as configured SSH user: {shlex.quote(username)}\n"
        f'test "$(id -un)" = {shlex.quote(username)} && (\n'
        'umask 077 && mkdir -p "$HOME/.ssh" && chmod 700 "$HOME/.ssh" &&\n'
        'touch "$HOME/.ssh/authorized_keys" && chmod 600 "$HOME/.ssh/authorized_keys" &&\n'
        f"if ! awk -v key={shlex.quote(key.get_base64())} "
        "' { for (i=1; i<=NF; i++) if ($i == key) found=1 } END { exit !found }' "
        '"$HOME/.ssh/authorized_keys"; then\n'
        # A leading newline preserves a previous unterminated line, including comments.
        f"  printf '\\n%s\\n' {shlex.quote(public_key_line)} >> \"$HOME/.ssh/authorized_keys\"\n"
        "fi\n)"
    )
