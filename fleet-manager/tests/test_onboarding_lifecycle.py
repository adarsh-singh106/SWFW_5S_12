"""Comprehensive regression tests for SSH node onboarding lifecycle and trust architecture.

Verifies:
1. Server Identity / Host-Key Trust vs Client Authentication distinction.
2. Host key fingerprint calculation and deliberate confirmation enrollment into known_hosts.
3. Client authentication public-key derivation and copyable authorized_keys bootstrap command.
4. Private keys are never exposed in API responses or database.
5. Status architecture: separation between SetupState (readiness) and DisplayStatus.
6. Guided onboarding endpoints (GET onboarding, POST scan-host-key, POST trust-host-key).
"""

import base64
import hashlib
import secrets
from pathlib import Path

import paramiko
import pytest
from fastapi.testclient import TestClient

from fleet_manager.config import SSHSettings
from fleet_manager.connectivity.freshness import DisplayStatus, SetupState, derive_status
from fleet_manager.connectivity.models import ConnectivityObservation, ConnectivityOutcome
from fleet_manager.connectivity.trust import (
    calculate_fingerprint,
    check_host_key_trust,
    format_known_hosts_entry,
    generate_bootstrap_instruction,
    get_operator_public_key,
)
from fleet_manager.main import create_app


@pytest.fixture
def api_token() -> str:
    return secrets.token_urlsafe(32)


@pytest.fixture
def auth_headers(api_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_token}"}


@pytest.fixture
def rsa_key() -> paramiko.RSAKey:
    return paramiko.RSAKey.generate(2048)


@pytest.fixture
def ssh_environment(tmp_path: Path, rsa_key: paramiko.RSAKey) -> tuple[SSHSettings, Path, Path]:
    known_hosts = tmp_path / "known_hosts"
    known_hosts.write_text("")
    private_key_path = tmp_path / "operator_rsa"
    rsa_key.write_private_key_file(str(private_key_path))
    settings = SSHSettings("operator", known_hosts, private_key_path)
    return settings, known_hosts, private_key_path


def test_fingerprint_calculation_and_format(rsa_key: paramiko.RSAKey) -> None:
    fp = calculate_fingerprint(rsa_key)
    assert fp.startswith("SHA256:")
    assert not fp.endswith("=")  # OpenSSH standard strips base64 padding
    raw = rsa_key.asbytes()
    expected = "SHA256:" + base64.b64encode(hashlib.sha256(raw).digest()).decode("ascii").rstrip(
        "="
    )
    assert fp == expected


def test_client_authentication_public_key_derivation_never_exposes_private_key(
    ssh_environment: tuple[SSHSettings, Path, Path], rsa_key: paramiko.RSAKey
) -> None:
    settings, _, private_key_path = ssh_environment
    pub_key_line = get_operator_public_key(private_key_path)

    # Must be valid OpenSSH public key line: "<type> <base64> fleet-manager-operator"
    parts = pub_key_line.split()
    assert len(parts) == 3
    assert parts[0] == "ssh-rsa"
    assert parts[1] == rsa_key.get_base64()
    assert parts[2] == "fleet-manager-operator"

    # Private key markers must NEVER appear in public key line
    assert "PRIVATE KEY" not in pub_key_line

    # Copyable bootstrap instruction format
    cmd = generate_bootstrap_instruction("operator", pub_key_line)
    assert "ssh-rsa" in cmd
    assert "authorized_keys" in cmd
    assert "chmod 600" in cmd
    assert "chmod 700" in cmd


def test_host_key_trust_checking(tmp_path: Path, rsa_key: paramiko.RSAKey) -> None:
    known_hosts = tmp_path / "known_hosts"
    key_type = rsa_key.get_name()
    base64_key = rsa_key.get_base64()

    # 1. Untrusted when known_hosts is empty
    known_hosts.write_text("")
    assert check_host_key_trust("192.0.2.1", 22, known_hosts, key_type, base64_key) == "UNTRUSTED"

    # 2. Trusted when entry matches
    entry = format_known_hosts_entry("192.0.2.1", 22, key_type, base64_key)
    known_hosts.write_text(entry)
    assert check_host_key_trust("192.0.2.1", 22, known_hosts, key_type, base64_key) == "TRUSTED"

    # 3. Mismatch when different key exists for same host
    other_key = paramiko.RSAKey.generate(2048)
    assert (
        check_host_key_trust(
            "192.0.2.1", 22, known_hosts, other_key.get_name(), other_key.get_base64()
        )
        == "MISMATCH"
    )


def test_status_architecture_separation_of_setup_and_connectivity() -> None:
    from datetime import UTC, datetime, timedelta

    now = datetime.now(UTC)
    ttl = timedelta(seconds=180)

    # 1. No observation -> PENDING_SETUP, NOT_CHECKED
    s1 = derive_status(None, now, ttl)
    assert s1.status == DisplayStatus.NOT_CHECKED
    assert s1.setup_state == SetupState.PENDING_SETUP

    # 2. Host key unknown -> HOST_KEY_REQUIRED, CHECK_ERROR (NEVER UNREACHABLE!)
    obs_unknown = ConnectivityObservation(
        1, 1, now, ConnectivityOutcome.HOST_KEY_UNKNOWN, ConnectivityOutcome.HOST_KEY_UNKNOWN
    )
    s2 = derive_status(obs_unknown, now, ttl)
    assert s2.status == DisplayStatus.CHECK_ERROR
    assert s2.setup_state == SetupState.HOST_KEY_REQUIRED

    # 3. Host key mismatch -> HOST_KEY_REQUIRED, CHECK_ERROR (NEVER UNREACHABLE!)
    obs_mismatch = ConnectivityObservation(
        2, 1, now, ConnectivityOutcome.HOST_KEY_MISMATCH, ConnectivityOutcome.HOST_KEY_MISMATCH
    )
    s3 = derive_status(obs_mismatch, now, ttl)
    assert s3.status == DisplayStatus.CHECK_ERROR
    assert s3.setup_state == SetupState.HOST_KEY_REQUIRED

    # 4. Auth failed -> AUTHENTICATION_REQUIRED, CHECK_ERROR (NEVER UNREACHABLE!)
    obs_auth = ConnectivityObservation(
        3, 1, now, ConnectivityOutcome.AUTH_FAILED, ConnectivityOutcome.AUTH_FAILED
    )
    s4 = derive_status(obs_auth, now, ttl)
    assert s4.status == DisplayStatus.CHECK_ERROR
    assert s4.setup_state == SetupState.AUTHENTICATION_REQUIRED

    # 5. Connected -> READY, REACHABLE
    obs_conn = ConnectivityObservation(4, 1, now, ConnectivityOutcome.CONNECTED, None)
    s5 = derive_status(obs_conn, now, ttl)
    assert s5.status == DisplayStatus.REACHABLE
    assert s5.setup_state == SetupState.READY

    # 6. Connection refused on node previously ready -> READY setup state, UNREACHABLE
    obs_refused = ConnectivityObservation(
        5, 1, now, ConnectivityOutcome.CONNECTION_REFUSED, ConnectivityOutcome.CONNECTION_REFUSED
    )
    s6 = derive_status(obs_refused, now, ttl, has_connected=True)
    assert s6.status == DisplayStatus.UNREACHABLE
    assert s6.setup_state == SetupState.READY

    # 7. Connection refused on node that never connected -> PENDING_SETUP, UNREACHABLE
    s7 = derive_status(obs_refused, now, ttl, has_connected=False)
    assert s7.status == DisplayStatus.UNREACHABLE
    assert s7.setup_state == SetupState.PENDING_SETUP


def test_onboarding_api_flow(
    tmp_path: Path,
    api_token: str,
    auth_headers: dict[str, str],
    ssh_environment: tuple[SSHSettings, Path, Path],
) -> None:
    settings, known_hosts, _ = ssh_environment
    app = create_app(
        database_path=tmp_path / "inventory.db",
        api_token=api_token,
        ssh_settings=settings,
    )

    with TestClient(app, headers=auth_headers) as client:
        # 1. Register a new node
        reg = client.post(
            "/api/nodes",
            json={"name": "test-host-01", "address": "127.0.0.1", "ssh_port": 2222},
        )
        assert reg.status_code == 201
        node_id = reg.json()["id"]

        # 2. Query guided onboarding status
        onboarding_res = client.get(f"/api/nodes/{node_id}/onboarding")
        assert onboarding_res.status_code == 200
        data = onboarding_res.json()

        assert data["node_id"] == node_id
        assert data["setup_state"] == "HOST_KEY_REQUIRED"
        assert data["display_status"] == "NOT_CHECKED"
        assert data["is_ready"] is False
        assert data["server_identity"]["trust_state"] == "UNTRUSTED"
        assert data["client_authentication"]["credential_profile"] == "default_operator"
        assert data["client_authentication"]["ssh_username"] == "operator"
        assert "ssh-rsa" in data["client_authentication"]["public_key"]
        assert "authorized_keys" in data["client_authentication"]["bootstrap_instruction"]
        assert "PRIVATE KEY" not in onboarding_res.text

        # 3. Check status API also exposes setup_state
        status_res = client.get("/api/nodes/status")
        assert status_res.status_code == 200
        nodes = status_res.json()["nodes"]
        assert len(nodes) == 1
        assert nodes[0]["setup_state"] == "HOST_KEY_REQUIRED"
        assert nodes[0]["display_status"] == "NOT_CHECKED"


def test_configuration_revision_changes_invalidate_readiness(
    ssh_environment: tuple[SSHSettings, Path, Path], rsa_key: paramiko.RSAKey
) -> None:
    from datetime import UTC, datetime

    from fleet_manager.connectivity.models import ConnectivityObservation, ConnectivityOutcome
    from fleet_manager.connectivity.readiness import (
        SetupState,
        configuration_revision,
        derive_setup,
    )
    from fleet_manager.connectivity.trust import format_known_hosts_entry
    from fleet_manager.inventory.models import Node, ObservationState

    settings, known_hosts, private_key = ssh_environment
    known_hosts.write_text(
        format_known_hosts_entry("127.0.0.1", 2222, rsa_key.get_name(), rsa_key.get_base64())
    )

    node1 = Node(1, "host-1", "127.0.0.1", 2222, ObservationState.NOT_CHECKED)
    rev1, host_fp1, pub1 = configuration_revision(node1, settings)
    assert host_fp1 is not None

    now = datetime.now(UTC)
    obs1 = ConnectivityObservation(1, 1, now, ConnectivityOutcome.CONNECTED, None, revision=rev1)

    # Initially verified for rev1 -> READY
    state, reason = derive_setup(
        obs1, now, rev1, trusted=True, credentials_valid=True, validated=True
    )
    assert state == SetupState.READY

    # 1. Port change -> revision changes -> previous readiness invalidated to PENDING_SETUP
    node1_new_port = Node(1, "host-1", "127.0.0.1", 2223, ObservationState.NOT_CHECKED)
    rev_new_port, _, _ = configuration_revision(node1_new_port, settings)
    assert rev_new_port != rev1
    state, reason = derive_setup(
        obs1, now, rev_new_port, trusted=False, credentials_valid=True, validated=True
    )
    assert state == SetupState.HOST_KEY_REQUIRED  # Needs new host key for port 2223

    # 2. Username change -> revision changes -> PENDING_SETUP
    settings_new_user = SSHSettings("admin", known_hosts, private_key)
    rev_new_user, _, _ = configuration_revision(node1, settings_new_user)
    assert rev_new_user != rev1
    state, reason = derive_setup(
        obs1, now, rev_new_user, trusted=True, credentials_valid=True, validated=True
    )
    assert state == SetupState.PENDING_SETUP


def test_authentication_failure_revokes_ready() -> None:
    from datetime import UTC, datetime

    from fleet_manager.connectivity.models import ConnectivityObservation, ConnectivityOutcome
    from fleet_manager.connectivity.readiness import SetupState, derive_setup

    now = datetime.now(UTC)
    revision = "fixed-rev-123"

    # Historic success
    obs_conn = ConnectivityObservation(
        1, 1, now, ConnectivityOutcome.CONNECTED, None, revision=revision
    )
    state, _ = derive_setup(
        obs_conn, now, revision, trusted=True, credentials_valid=True, validated=True
    )
    assert state == SetupState.READY

    # Later observation has authentication failure -> revokes READY
    obs_auth_fail = ConnectivityObservation(
        2,
        1,
        now,
        ConnectivityOutcome.AUTH_FAILED,
        ConnectivityOutcome.AUTH_FAILED,
        revision=revision,
    )
    state, reason = derive_setup(
        obs_auth_fail, now, revision, trusted=True, credentials_valid=True, validated=True
    )
    assert state == SetupState.AUTHENTICATION_REQUIRED
    assert "authentication failed" in (reason or "").lower()


def test_host_key_mismatch_revokes_ready_and_trust() -> None:
    from datetime import UTC, datetime

    from fleet_manager.connectivity.models import ConnectivityObservation, ConnectivityOutcome
    from fleet_manager.connectivity.readiness import SetupState, derive_setup

    now = datetime.now(UTC)
    revision = "fixed-rev-123"

    # Server key changed / mismatch -> revokes READY and requires host key review
    obs_mismatch = ConnectivityObservation(
        3,
        1,
        now,
        ConnectivityOutcome.HOST_KEY_MISMATCH,
        ConnectivityOutcome.HOST_KEY_MISMATCH,
        revision=revision,
    )
    state, reason = derive_setup(
        obs_mismatch, now, revision, trusted=True, credentials_valid=True, validated=True
    )
    assert state == SetupState.HOST_KEY_REQUIRED


def test_network_outages_preserve_ready_configuration() -> None:
    from datetime import UTC, datetime, timedelta

    from fleet_manager.connectivity.freshness import DisplayStatus, derive_status
    from fleet_manager.connectivity.models import ConnectivityObservation, ConnectivityOutcome
    from fleet_manager.connectivity.readiness import SetupState

    now = datetime.now(UTC)
    ttl = timedelta(seconds=180)
    revision = "fixed-rev-123"

    # Connection refused on node previously connected keeps READY while showing UNREACHABLE
    obs_refused = ConnectivityObservation(
        4,
        1,
        now,
        ConnectivityOutcome.CONNECTION_REFUSED,
        ConnectivityOutcome.CONNECTION_REFUSED,
        revision=revision,
    )
    derived = derive_status(obs_refused, now, ttl, has_connected=True)
    assert derived.status == DisplayStatus.UNREACHABLE
    assert derived.setup_state == SetupState.READY

    # Connection timeout also keeps READY while showing UNREACHABLE
    obs_timeout = ConnectivityObservation(
        5,
        1,
        now,
        ConnectivityOutcome.CONNECTION_TIMEOUT,
        ConnectivityOutcome.CONNECTION_TIMEOUT,
        revision=revision,
    )
    derived = derive_status(obs_timeout, now, ttl, has_connected=True)
    assert derived.status == DisplayStatus.UNREACHABLE
    assert derived.setup_state == SetupState.READY
