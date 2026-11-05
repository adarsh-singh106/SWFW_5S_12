"""Unit tests for Fleet Manager safe source-bundle packaging and validation."""

from __future__ import annotations

import tarfile
import tempfile
from pathlib import Path

import pytest
from scripts.package_source_bundle import (
    collect_bundle_files,
    create_source_bundle,
    is_excluded_path,
    main,
    validate_source_files,
    verify_bundle,
)


def test_is_excluded_path() -> None:
    """Verifies strict exclusions for development caches, keys, and databases."""
    assert is_excluded_path(Path(".git/config"))
    assert is_excluded_path(Path(".venv/bin/python"))
    assert is_excluded_path(Path(".local/browser-qa/screenshot.png"))
    assert is_excluded_path(Path("src/__pycache__/app.cpython-312.pyc"))
    assert is_excluded_path(Path("inventory.db"))
    assert is_excluded_path(Path("inventory.db-wal"))
    assert is_excluded_path(Path("inventory.sqlite3"))
    assert is_excluded_path(Path("secrets.key"))
    assert is_excluded_path(Path("id_rsa"))
    assert is_excluded_path(Path("id_ed25519"))
    assert is_excluded_path(Path(".env"))
    assert is_excluded_path(Path("custom.env"))

    # Legitimate non-secret paths MUST NOT be excluded
    assert not is_excluded_path(Path("deploy/fleet-manager.env.example"))
    assert not is_excluded_path(Path("deploy/gce/00-config.env"))
    assert not is_excluded_path(Path("src/fleet_manager/main.py"))
    assert not is_excluded_path(Path("uv.lock"))


def test_collect_bundle_files_finds_core_sources() -> None:
    """Working-tree traversal captures untracked and modified core files."""
    from scripts.package_source_bundle import ROOT

    files = collect_bundle_files(ROOT)
    posix_files = {str(p).replace("\\", "/") for p in files}

    assert "src/fleet_manager/main.py" in posix_files
    assert "src/fleet_manager/connectivity/onboarding.py" in posix_files
    assert "src/fleet_manager/connectivity/trust.py" in posix_files
    assert "src/fleet_manager/ui/static/js/app.js" in posix_files
    assert "deploy/gce/00-config.env" in posix_files
    assert "uv.lock" in posix_files

    missing = validate_source_files(files)
    assert not missing, f"Missing required files in working tree: {missing}"


def test_create_and_verify_source_bundle() -> None:
    """Creates a temporary bundle and verifies its checksum and members."""
    from scripts.package_source_bundle import ROOT

    with tempfile.TemporaryDirectory(prefix="fm_test_bundle_") as tmp:
        tmp_dir = Path(tmp)
        bundle_path, checksum, manifest = create_source_bundle(
            root=ROOT,
            output_dir=tmp_dir,
            bundle_name="test-bundle.tar.gz",
        )

        assert bundle_path.is_file()
        assert len(checksum) == 64
        assert manifest["file_count"] > 100
        assert manifest["sha256"] == checksum

        # Verify bundle self-check
        ok, msg = verify_bundle(bundle_path, checksum)
        assert ok, f"Bundle verification failed: {msg}"

        # Tampering detection: modify checksum
        tampered_sha = checksum[:-4] + "0000"
        ok_tamper, msg_tamper = verify_bundle(bundle_path, tampered_sha)
        assert not ok_tamper
        assert "Checksum mismatch" in msg_tamper


def test_verify_bundle_missing_file_detection() -> None:
    """verify_bundle detects when an archive lacks required files."""
    with tempfile.TemporaryDirectory(prefix="fm_test_empty_tar_") as tmp:
        empty_tar = Path(tmp) / "empty.tar.gz"
        with tarfile.open(empty_tar, "w:gz") as tar:
            # Add single unrelated file
            dummy_file = Path(tmp) / "dummy.txt"
            dummy_file.write_text("dummy")
            tar.add(dummy_file, arcname="dummy.txt")

        ok, msg = verify_bundle(empty_tar)
        assert not ok
        assert "Bundle is missing required files" in msg


def test_main_cli_verify_only(monkeypatch: pytest.MonkeyPatch) -> None:
    """main() CLI verification flag passes for valid bundle."""
    from scripts.package_source_bundle import ROOT

    valid_bundle = ROOT / "dist" / "fleet-manager-source-bundle.tar.gz"
    if valid_bundle.is_file():
        monkeypatch.setattr(
            "sys.argv",
            ["package_source_bundle.py", "--verify-only", str(valid_bundle)],
        )
        assert main() == 0
