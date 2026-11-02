"""Explicit action catalog with typed parameter validation and safe command compilation."""

import re
import shlex
from dataclasses import dataclass
from typing import Any

from fleet_manager.errors import InvalidAction, InvalidOperationArguments

_DISK_PATH_PATTERN = re.compile(r"^/[a-zA-Z0-9_\-\./]*$", re.ASCII)
_SERVICE_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9_\-\.@]{1,64}$", re.ASCII)

ALLOWED_ACTIONS = frozenset({"system.uptime", "system.memory", "system.disk", "service.status"})


@dataclass(frozen=True, slots=True)
class ValidatedAction:
    action: str
    sanitized_arguments: dict[str, Any]
    remote_command: str


def validate_action(action: str, arguments: dict[str, Any] | None) -> ValidatedAction:
    """Validate action name and typed parameters against the strict catalog."""
    if action not in ALLOWED_ACTIONS:
        raise InvalidAction(
            f"Action '{action}' is not permitted. Allowed actions: {sorted(ALLOWED_ACTIONS)}"
        )

    args = arguments or {}
    if not isinstance(args, dict):
        raise InvalidOperationArguments("Operation arguments must be a dictionary")

    if action == "system.uptime":
        if args:
            raise InvalidOperationArguments("Action 'system.uptime' does not accept arguments")
        return ValidatedAction(
            action=action,
            sanitized_arguments={},
            remote_command="uptime",
        )

    if action == "system.memory":
        if args:
            raise InvalidOperationArguments("Action 'system.memory' does not accept arguments")
        return ValidatedAction(
            action=action,
            sanitized_arguments={},
            remote_command="free -m",
        )

    if action == "system.disk":
        extra_keys = set(args.keys()) - {"path"}
        if extra_keys:
            raise InvalidOperationArguments(
                f"Action 'system.disk' received unexpected arguments: {sorted(extra_keys)}"
            )
        if "path" not in args:
            raise InvalidOperationArguments("Action 'system.disk' requires 'path' argument")
        raw_path = args["path"]
        if not isinstance(raw_path, str):
            raise InvalidOperationArguments("Argument 'path' must be a string")
        path = raw_path.strip()
        if not path or len(path) > 255:
            raise InvalidOperationArguments("Argument 'path' must be between 1 and 255 characters")
        if not path.startswith("/"):
            raise InvalidOperationArguments(
                "Argument 'path' must be an absolute POSIX path starting with '/'"
            )
        if any(c.isspace() for c in path):
            raise InvalidOperationArguments("Argument 'path' must not contain whitespace")
        if _DISK_PATH_PATTERN.fullmatch(path) is None:
            raise InvalidOperationArguments("Argument 'path' contains invalid characters")
        if any(seg == ".." for seg in path.split("/")):
            raise InvalidOperationArguments(
                "Argument 'path' must not contain directory traversal ('..')"
            )

        return ValidatedAction(
            action=action,
            sanitized_arguments={"path": path},
            remote_command=f"df -h -P -- {shlex.quote(path)}",
        )

    if action == "service.status":
        extra_keys = set(args.keys()) - {"service_name"}
        if extra_keys:
            raise InvalidOperationArguments(
                f"Action 'service.status' received unexpected arguments: {sorted(extra_keys)}"
            )
        if "service_name" not in args:
            raise InvalidOperationArguments(
                "Action 'service.status' requires 'service_name' argument"
            )
        raw_service = args["service_name"]
        if not isinstance(raw_service, str):
            raise InvalidOperationArguments("Argument 'service_name' must be a string")
        service_name = raw_service.strip()
        if not service_name or len(service_name) > 64:
            raise InvalidOperationArguments(
                "Argument 'service_name' must be between 1 and 64 characters"
            )
        if service_name.startswith("-"):
            raise InvalidOperationArguments("Argument 'service_name' must not start with a hyphen")
        if any(c.isspace() for c in service_name):
            raise InvalidOperationArguments("Argument 'service_name' must not contain whitespace")
        if _SERVICE_NAME_PATTERN.fullmatch(service_name) is None:
            raise InvalidOperationArguments("Argument 'service_name' contains invalid characters")

        return ValidatedAction(
            action=action,
            sanitized_arguments={"service_name": service_name},
            remote_command=f"systemctl --no-pager status -- {shlex.quote(service_name)}",
        )

    raise InvalidAction(f"Action '{action}' is unhandled")
