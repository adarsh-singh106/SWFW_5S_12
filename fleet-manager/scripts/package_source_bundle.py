#!/usr/bin/env python3
"""Safe source-bundle packaging and validation utility for Fleet Manager.

Creates a reproducible, standalone source tarball from the working tree
that captures all uncommitted modifications and untracked implementation files,
reflects intentional file deletions, excludes secrets and development caches,
and generates a SHA-256 checksum and JSON manifest.

Can be safely transferred to Cloud Shell or directly to fleet-controller
without relying on git clone, git archive, or remote GitHub repository access.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tarfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent

# Top-level directories and files to include from the project root
INCLUDED_ROOT_DIRECTORIES = ["src", "deploy", "scripts", "monitoring", "tests", "docs"]
INCLUDED_ROOT_FILES = ["README.md", "pyproject.toml", "uv.lock", "AGENTS.md"]

# Strict exclusions: paths matching these components or extensions are excluded
EXCLUDED_DIR_NAMES = {
    ".git",
    ".venv",
    ".local",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    "dist",
    "build",
    "node_modules",
}

EXCLUDED_FILE_EXTENSIONS = {
    ".pyc",
    ".pyo",
    ".pyd",
    ".db",
    ".db-wal",
    ".db-shm",
    ".sqlite",
    ".sqlite3",
    ".log",
    ".bak",
    ".tmp",
}

# Critical required files that MUST exist inside the verified bundle
REQUIRED_BUNDLE_FILES = [
    "pyproject.toml",
    "uv.lock",
    "README.md",
    "src/fleet_manager/__init__.py",
    "src/fleet_manager/main.py",
    "src/fleet_manager/config.py",
    "src/fleet_manager/connectivity/onboarding.py",
    "src/fleet_manager/connectivity/trust.py",
    "src/fleet_manager/connectivity/readiness.py",
    "src/fleet_manager/connectivity/router.py",
    "src/fleet_manager/connectivity/service.py",
    "src/fleet_manager/inventory/repository.py",
    "src/fleet_manager/inventory/router.py",
    "src/fleet_manager/operations/router.py",
    "src/fleet_manager/operations/service.py",
    "src/fleet_manager/ui/router.py",
    "src/fleet_manager/ui/index.html",
    "src/fleet_manager/ui/templates/dashboard.html",
    "src/fleet_manager/ui/static/js/app.js",
    "src/fleet_manager/ui/static/js/node-onboarding.js",
    "src/fleet_manager/ui/static/css/tokens.css",
    "monitoring/prometheus/prometheus.yml",
    "monitoring/prometheus/targets.json",
    "monitoring/grafana/provisioning/datasources/prometheus.yaml",
    "monitoring/grafana/provisioning/dashboards/dashboards.yaml",
    "monitoring/grafana/dashboards/fleet-monitoring.json",
    "deploy/fleet-manager.service",
    "deploy/fleet-manager-backup.service",
    "deploy/fleet-manager-backup.timer",
    "deploy/fleet-manager.env.example",
    "deploy/gce/00-config.env",
    "deploy/gce/01-start-vms.sh",
    "deploy/gce/02-setup-nodes.sh",
    "deploy/gce/03-setup-controller.sh",
    "deploy/gce/04-deploy-app.sh",
    "deploy/gce/05-transfer-keys.sh",
    "deploy/gce/06-start-tunnel.sh",
    "deploy/gce/07-cleanup-vms.sh",
    "deploy/gce/deploy-all.sh",
    "scripts/backup_restore.py",
    "scripts/gce_acceptance_test.py",
    "tests/test_gce_acceptance.py",
    "tests/dashboard_regression.cjs",
]


def calculate_sha256(path: Path) -> str:
    """Calculate the SHA-256 digest of a file in 64 KiB chunks."""
    hasher = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


def is_excluded_path(rel_path: Path) -> bool:
    """Check if a relative path matches any exclusion criteria."""
    parts = set(rel_path.parts)
    if parts.intersection(EXCLUDED_DIR_NAMES):
        return True

    name = rel_path.name.lower()

    # Exclude temporary or cache files
    if rel_path.suffix.lower() in EXCLUDED_FILE_EXTENSIONS:
        return True

    # Exclude secret environment files, but retain template and configuration files
    if (name.endswith(".env") or ".env." in name) and not name.endswith(".env.example"):
        if name != "00-config.env":
            return True

    # Exclude private key patterns
    if name in ("id_rsa", "id_ed25519", "id_ecdsa", "fleet-bootstrap"):
        return True
    if name.endswith(".key") or name.endswith(".pem"):
        return True

    return False


def collect_bundle_files(root: Path) -> list[Path]:
    """Collect all valid source files from the working tree."""
    collected: list[Path] = []

    # 1. Collect from approved top-level files
    for fname in INCLUDED_ROOT_FILES:
        target = root / fname
        if target.is_file():
            rel = target.relative_to(root)
            if not is_excluded_path(rel):
                collected.append(rel)

    # 2. Collect from approved directories
    for dname in INCLUDED_ROOT_DIRECTORIES:
        target_dir = root / dname
        if not target_dir.is_dir():
            continue
        for p in target_dir.rglob("*"):
            if p.is_file():
                rel = p.relative_to(root)
                if not is_excluded_path(rel):
                    collected.append(rel)

    return sorted(collected, key=lambda p: str(p).replace("\\", "/"))


def validate_source_files(collected: list[Path]) -> list[str]:
    """Check that all required bundle files exist in the collected list."""
    collected_posix = {str(p).replace("\\", "/") for p in collected}
    missing: list[str] = []
    for req in REQUIRED_BUNDLE_FILES:
        if req not in collected_posix:
            missing.append(req)
    return missing


def create_source_bundle(
    root: Path,
    output_dir: Path,
    bundle_name: str = "fleet-manager-source-bundle.tar.gz",
) -> tuple[Path, str, dict[str, Any]]:
    """Build a deterministic gzipped tar archive with checksum and manifest."""
    output_dir.mkdir(parents=True, exist_ok=True)
    bundle_path = output_dir / bundle_name
    sha256_path = output_dir / f"{bundle_name}.sha256"
    manifest_path = output_dir / f"{bundle_name}.manifest.json"

    files = collect_bundle_files(root)
    missing = validate_source_files(files)
    if missing:
        raise RuntimeError(f"Cannot package source bundle. Missing required files: {missing}")

    # Build tarball
    if bundle_path.exists():
        bundle_path.unlink()

    start_time = time.monotonic()
    with tarfile.open(bundle_path, "w:gz") as tar:
        for rel_path in files:
            full_path = root / rel_path
            posix_name = str(rel_path).replace("\\", "/")

            # Normalize permissions: 0755 for executables/scripts, 0644 for regular files
            tarinfo = tar.gettarinfo(str(full_path), arcname=posix_name)
            tarinfo.uid = 0
            tarinfo.gid = 0
            tarinfo.uname = "root"
            tarinfo.gname = "root"
            if (
                posix_name.endswith(".sh")
                or posix_name.endswith(".py")
                or posix_name.endswith(".cjs")
            ):
                tarinfo.mode = 0o755
            else:
                tarinfo.mode = 0o644

            with full_path.open("rb") as f:
                tar.addfile(tarinfo, f)

    elapsed = time.monotonic() - start_time
    checksum = calculate_sha256(bundle_path)

    # Write companion sha256 checksum file with strict POSIX LF (never CRLF)
    sha256_path.write_bytes(f"{checksum}  {bundle_name}\n".encode())

    # Write companion manifest JSON with strict POSIX LF
    manifest_data = {
        "bundle_name": bundle_name,
        "created_at": datetime.now(UTC).isoformat(),
        "sha256": checksum,
        "size_bytes": bundle_path.stat().st_size,
        "file_count": len(files),
        "build_duration_seconds": round(elapsed, 3),
        "files": [str(p).replace("\\", "/") for p in files],
    }
    manifest_path.write_bytes(json.dumps(manifest_data, indent=2).encode("utf-8") + b"\n")

    return bundle_path, checksum, manifest_data


def verify_bundle(bundle_path: Path, expected_sha256: str | None = None) -> tuple[bool, str]:
    """Verify an existing bundle tarball against checksum and required files."""
    if not bundle_path.is_file():
        return False, f"Bundle file {bundle_path} does not exist"

    # 1. Verify checksum if provided or if .sha256 file exists alongside
    if expected_sha256 is None:
        sha_file = bundle_path.with_suffix(bundle_path.suffix + ".sha256")
        if not sha_file.exists():
            sha_file = bundle_path.parent / f"{bundle_path.name}.sha256"
        if sha_file.exists():
            expected_sha256 = sha_file.read_text(encoding="utf-8").split()[0]

    actual_sha = calculate_sha256(bundle_path)
    if expected_sha256 and actual_sha != expected_sha256.strip():
        return (
            False,
            f"Checksum mismatch: expected {expected_sha256.strip()}, got {actual_sha}",
        )

    # 2. Inspect members inside tarball
    try:
        with tarfile.open(bundle_path, "r:gz") as tar:
            members = {m.name for m in tar.getmembers() if m.isfile()}
    except Exception as exc:
        return False, f"Failed to read tar archive: {exc}"

    # Check for prohibited patterns
    for name in members:
        p = Path(name)
        if is_excluded_path(p):
            return False, f"Prohibited file found in bundle: {name}"

    # Check required files
    missing = [req for req in REQUIRED_BUNDLE_FILES if req not in members]
    if missing:
        return False, f"Bundle is missing required files: {missing}"

    return True, f"Verified {len(members)} files; SHA-256: {actual_sha}"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Package or verify safe Fleet Manager source bundle"
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "dist",
        help="Target directory for archive and manifest",
    )
    parser.add_argument(
        "--bundle-name",
        default="fleet-manager-source-bundle.tar.gz",
        help="Archive filename",
    )
    parser.add_argument(
        "--verify-only",
        type=Path,
        default=None,
        help="Verify an existing bundle without creating a new one",
    )
    parser.add_argument(
        "--sha256",
        default=None,
        help="Expected SHA-256 digest when verifying",
    )

    args = parser.parse_args()

    if args.verify_only:
        ok, msg = verify_bundle(args.verify_only, args.sha256)
        if ok:
            print(f"[OK] {msg}")
            return 0
        else:
            print(f"[ERROR] {msg}", file=sys.stderr)
            return 1

    try:
        bundle_path, checksum, manifest = create_source_bundle(
            root=ROOT,
            output_dir=args.output_dir,
            bundle_name=args.bundle_name,
        )
        print("=" * 70)
        print("Fleet Manager Source Bundle Created Successfully")
        print("=" * 70)
        print(f"Archive Path : {bundle_path}")
        print(f"Archive Size : {manifest['size_bytes']} bytes ({manifest['file_count']} files)")
        print(f"SHA-256      : {checksum}")
        print(f"Checksum File: {bundle_path.parent / (args.bundle_name + '.sha256')}")
        print(f"Manifest JSON: {bundle_path.parent / (args.bundle_name + '.manifest.json')}")
        print("=" * 70)

        # Immediate self-verification
        ok, msg = verify_bundle(bundle_path, checksum)
        if not ok:
            print(f"[ERROR] Immediate verification failed: {msg}", file=sys.stderr)
            return 1
        print(f"[OK] Pre-flight verification passed: {msg}")
        return 0
    except Exception as exc:
        print(f"[ERROR] Packaging failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
