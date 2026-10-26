#!/usr/bin/env python3
"""
SWFW_5S_12 Submission Packaging Utility
Zoho Learning Program - SETU 2026 Project Submission

Packages the verified codebase and technical report into:
  <CANDIDATE_NAME>_SWFW_5S_12_PROJECT-FILES.zip
"""

import os
import sys
import zipfile
import hashlib

EXCLUDE_DIRS = {
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".git",
    "recordings",
    ".local",
    "node_modules",
    "venv",
    ".venv"
}

EXCLUDE_EXTENSIONS = {
    ".pyc",
    ".pyo",
    ".db",
    ".tmp",
    ".zip"
}


def compute_sha256(filepath: str) -> str:
    """Computes SHA-256 hash of a file."""
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(8192):
            h.update(chunk)
    return h.hexdigest()


def create_submission_package(candidate_name: str = "ADARSH") -> str:
    candidate_clean = candidate_name.strip().upper().replace(" ", "_")
    zip_filename = f"{candidate_clean}_SWFW_5S_12_PROJECT-FILES.zip"
    repo_root = os.path.dirname(os.path.abspath(__file__))
    zip_path = os.path.join(repo_root, zip_filename)

    print("=================================================================")
    print("SWFW_5S_12: PACKAGING SUBMISSION ARTIFACTS")
    print("=================================================================")
    print(f"Candidate: {candidate_clean}")
    print(f"Target Zip: {zip_filename}\n")

    files_added = 0
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
        # 1. Add Fleet Manager Code & Docs
        target_dir = os.path.join(repo_root, "fleet-manager")
        for root, dirs, files in os.walk(target_dir):
            dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
            for file in files:
                ext = os.path.splitext(file)[1].lower()
                if ext in EXCLUDE_EXTENSIONS:
                    continue
                full_path = os.path.join(root, file)
                rel_path = os.path.relpath(full_path, repo_root)
                zipf.write(full_path, rel_path)
                files_added += 1

        # 2. Add Prerequisites if present
        prereq_dir = os.path.join(repo_root, "00-Prerequisites")
        if os.path.exists(prereq_dir):
            for root, dirs, files in os.walk(prereq_dir):
                dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
                for file in files:
                    ext = os.path.splitext(file)[1].lower()
                    if ext in EXCLUDE_EXTENSIONS:
                        continue
                    full_path = os.path.join(root, file)
                    rel_path = os.path.relpath(full_path, repo_root)
                    zipf.write(full_path, rel_path)
                    files_added += 1

    file_size_kb = round(os.path.getsize(zip_path) / 1024, 2)
    checksum = compute_sha256(zip_path)

    print(f"  -> Added {files_added} clean source files.")
    print(f"  -> Archive Size: {file_size_kb} KB")
    print(f"  -> SHA-256 Checksum: {checksum}")
    print("\n[SUCCESS] Package generated successfully at:")
    print(f"  {zip_path}")
    print("=================================================================")
    return zip_path


if __name__ == "__main__":
    name = sys.argv[1] if len(sys.argv) > 1 else "ADARSH"
    create_submission_package(name)
