"""Release archives must not carry credentials, runtime data or recursive bundles."""

from pathlib import Path

import pytest
from scripts.package_source_bundle import is_excluded_path


@pytest.mark.parametrize(
    "name",
    [
        "docs/.ssh/config",
        "docs/session.db-journal",
        "scripts/credentials.json",
        "deploy/application_default_credentials.json",
        "docs/old.zip",
        "docs/old.tar.gz",
        "deploy/operator.pem",
        "deploy/operator.key",
        "deploy/.env",
    ],
)
def test_release_excludes_sensitive_or_generated_files(name: str) -> None:
    assert is_excluded_path(Path(name))


@pytest.mark.parametrize("name", ["deploy/fleet-manager.env.example", "deploy/gce/00-config.env"])
def test_release_retains_reviewed_configuration_templates(name: str) -> None:
    assert not is_excluded_path(Path(name))
