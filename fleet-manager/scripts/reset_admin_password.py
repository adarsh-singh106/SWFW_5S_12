#!/usr/bin/env python3
"""Interactive CLI maintenance command for local operator administrator password reset."""

from __future__ import annotations

import argparse
import getpass
import os
import sys
from pathlib import Path

# Add project root and src to sys.path so script can be run standalone
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
if str(PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "src"))

from fleet_manager.security.passwords import (  # noqa: E402
    hash_password,
    validate_password_bounds,
)
from fleet_manager.security.repository import SQLiteAuthRepository  # noqa: E402


def reset_password(
    database_path: Path,
    password_getter=getpass.getpass,
) -> int:
    """Prompt for new administrator password and update persistent storage without echoing."""
    if not database_path.is_file():
        print(f"Error: Database file does not exist at {database_path}", file=sys.stderr)
        return 1

    try:
        pw1 = password_getter("Enter new administrator password: ")
        pw2 = password_getter("Confirm new administrator password: ")
    except (KeyboardInterrupt, EOFError):
        print("\nOperation cancelled by user.", file=sys.stderr)
        return 130

    if pw1 != pw2:
        print("Error: Passwords do not match.", file=sys.stderr)
        return 2

    try:
        validate_password_bounds(pw1)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 3

    if pw1 == "CHANGEME":
        print(
            "Error: Cannot set administrator password to placeholder 'CHANGEME'.",
            file=sys.stderr,
        )
        return 4

    try:
        repo = SQLiteAuthRepository(database_path)
        repo.initialize()
        new_hash = hash_password(pw1)
        if repo.has_credential():
            repo.update_password(new_hash, must_change_password=False)
        else:
            repo.create_credential(new_hash, must_change_password=False)
    except Exception as exc:
        print(f"Error: Failed to update administrator password in storage: {exc}", file=sys.stderr)
        return 5

    print(
        f"Success: Administrator password updated successfully in {database_path}.\n"
        "Active in-memory sessions must be invalidated; restart fleet-manager service if running."
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Reset the administrator password for Fleet Manager."
    )
    default_db = PROJECT_ROOT / ".local" / "inventory.db"
    configured_db = os.getenv("FLEET_MANAGER_DATABASE_PATH")
    selected_default = Path(configured_db) if configured_db else default_db

    parser.add_argument(
        "--database",
        type=Path,
        default=selected_default,
        help="Path to SQLite inventory.db file",
    )
    args = parser.parse_args()
    return reset_password(args.database)


if __name__ == "__main__":
    sys.exit(main())
