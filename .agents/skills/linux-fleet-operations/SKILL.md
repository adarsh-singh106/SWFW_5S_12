---
name: linux-fleet-operations
description: Governs Linux node fleet management over SSHv2, host identity verification, timeout management, failure classification, and secure remote command execution. Use when implementing SSH connectivity, probing node availability, handling exit codes, or executing remote operations.
---

# Linux Fleet Operations & Secure SSH Management

Engineering guidelines and protocols for managing distributed Linux nodes, verifying SSH host identities, classifying failure modes, and executing controlled remote commands.

## Core Principles

1. **Verify Host Identity Explicitly**: Never use `AutoAddPolicy()` or blind `ssh-keyscan`. Known host keys must be validated against out-of-band trusted fingerprints. Reject unknown or mismatched keys immediately.
2. **Strict Failure Taxonomy**: Distinguish between network unreachability, host failure, authentication errors, and protocol errors. An SSH connection failure does not prove host failure; exit code 255 does not identify a single cause.
3. **Bound Every Operation**: Enforce strict, isolated timeouts for socket connection, SSH banner exchange, authentication, and command execution. Never allow an unbounded wait.
4. **Least Privilege & Structured Execution**: Prohibit arbitrary interactive shell access (`/bin/bash -i`). Only execute whitelisted, structured commands with non-root accounts and explicit parameterization.
5. **Sanitized Auditability**: Record structured audit logs for every command execution, outcome, and observation. Never expose private keys, credentials, or sensitive node output in logs or API responses.

---

## SSH Transport & Verification Pattern

Using Paramiko securely with explicit host key enforcement:

```python
import errno
import socket
from enum import Enum
from pathlib import Path
import paramiko

class ConnectivityOutcome(str, Enum):
    CONNECTED = "CONNECTED"
    HOST_KEY_UNKNOWN = "HOST_KEY_UNKNOWN"
    HOST_KEY_MISMATCH = "HOST_KEY_MISMATCH"
    AUTH_FAILED = "AUTH_FAILED"
    CONNECTION_REFUSED = "CONNECTION_REFUSED"
    TIMEOUT = "TIMEOUT"
    DNS_ERROR = "DNS_ERROR"
    UNKNOWN_ERROR = "UNKNOWN_ERROR"

class _RejectUnknownHostKey(paramiko.MissingHostKeyPolicy):
    def missing_host_key(self, client: paramiko.SSHClient, hostname: str, key: paramiko.PKey) -> None:
        raise paramiko.SSHException(f"Rejecting untrusted host key for {hostname}")

def verify_node_ssh(
    address: str,
    port: int,
    username: str,
    private_key_path: Path,
    known_hosts_path: Path,
    timeout: float = 5.0,
) -> ConnectivityOutcome:
    """Verifies SSH connectivity and host identity without opening a shell or channel."""
    client = paramiko.SSHClient()
    try:
        client.load_host_keys(str(known_hosts_path))
        client.set_missing_host_key_policy(_RejectUnknownHostKey())
        pkey = paramiko.PKey.from_path(private_key_path)

        client.connect(
            hostname=address,
            port=port,
            username=username,
            pkey=pkey,
            allow_agent=False,       # Never probe local SSH agent
            look_for_keys=False,     # Never search ~/.ssh for random keys
            timeout=timeout,
            banner_timeout=timeout,
            auth_timeout=timeout,
        )
        return ConnectivityOutcome.CONNECTED
    except paramiko.BadHostKeyException:
        return ConnectivityOutcome.HOST_KEY_MISMATCH
    except paramiko.AuthenticationException:
        return ConnectivityOutcome.AUTH_FAILED
    except paramiko.SSHException as exc:
        if "Rejecting untrusted host key" in str(exc):
            return ConnectivityOutcome.HOST_KEY_UNKNOWN
        return ConnectivityOutcome.UNKNOWN_ERROR
    except socket.gaierror:
        return ConnectivityOutcome.DNS_ERROR
    except TimeoutError:
        return ConnectivityOutcome.TIMEOUT
    except ConnectionRefusedError:
        return ConnectivityOutcome.CONNECTION_REFUSED
    except OSError as exc:
        if exc.errno == errno.ECONNREFUSED:
            return ConnectivityOutcome.CONNECTION_REFUSED
        return ConnectivityOutcome.UNKNOWN_ERROR
    finally:
        client.close()
```

---

## Failure Mode Classification Taxonomy

Never collapse distinct failure categories into a generic "Host Down" status:

| Observed Symptom | Underlying Mechanism | Honest Interpretation | Safe Action |
|------------------|----------------------|-----------------------|-------------|
| `socket.gaierror` | DNS resolution failure | Name lookup failed; host address unresolvable. | Check DNS server or `/etc/hosts`; do not retry aggressively. |
| `ConnectionRefusedError` | TCP RST packet received | Machine or gateway is alive, but SSH daemon is not listening on that port. | Verify `sshd` status on target; do not assume machine crashed. |
| `TimeoutError` | TCP SYN dropped / no ACK | Firewall drop, network partition, or power failure. | Mark as `UNREACHABLE`; trigger bounded retry after backoff. |
| `BadHostKeyException` | Host key does not match `known_hosts` | Node re-imaged, IP reassigned, or man-in-the-middle attack. | **DO NOT AUTO-ACCEPT**. Alert operator to re-verify fingerprint. |
| `AuthenticationException` | Key rejected by `authorized_keys` | Credential revoked, wrong user, or permissions issue on `.ssh`. | Fail closed; notify operator. Retries will not fix invalid credentials. |
| `SSH Exit Code 255` | Generic SSH client error | Transport broken, remote host disconnected, or setup failure. | Inspect transport logs and stderr; do not treat 255 as a single diagnosis. |

---

## Controlled Remote Command Execution (Requirement 4)

### Execution Guardrails

1. **Whitelisted Commands**:
   Only permit pre-approved maintenance operations (e.g., `uptime`, `systemctl restart node_exporter`, `df -h /`). Reject raw shell input or unvetted parameter strings.
2. **Channel Isolation**:
   Open a dedicated session channel with `exec_command()`. Never allocate a pseudo-terminal (`pty`) unless strictly required by the command.
3. **Capture Both Streams**:
   Read `stdout` and `stderr` completely, record exit code, and verify post-condition.
4. **Execution Timeouts**:
   Set explicit channel read timeouts so hung commands do not deadlock the control plane.

```python
def run_controlled_command(
    client: paramiko.SSHClient, command: str, timeout_seconds: float = 10.0
) -> tuple[int, str, str]:
    """Execute a structured command with bounded execution."""
    transport = client.get_transport()
    if not transport or not transport.is_active():
        raise RuntimeError("SSH transport is not active")

    channel = transport.open_session()
    channel.settimeout(timeout_seconds)
    channel.exec_command(command)

    stdout = channel.makefile("r", -1).read()
    stderr = channel.makefile_stderr("r", -1).read()
    exit_code = channel.recv_exit_status()
    channel.close()

    return exit_code, stdout, stderr
```

---

## Security and Production Readiness Checklist

- [ ] Private key file permissions are validated (`0600` on POSIX, restricted ACL on Windows).
- [ ] No `known_hosts` entry is auto-accepted without independent out-of-band verification.
- [ ] SSH agent discovery and home directory key discovery are explicitly disabled.
- [ ] Connect, banner, and auth timeouts are individually bounded (e.g. $\le 5$s).
- [ ] Error messages returned to API clients omit internal paths, credentials, and raw stack traces.
- [ ] Commands executed remotely run under a dedicated unprivileged user account.
- [ ] Remote operations leave an append-only audit entry in the local database.
- [ ] WSL2 test environments are documented as single-kernel shared domains, not independent physical nodes.
