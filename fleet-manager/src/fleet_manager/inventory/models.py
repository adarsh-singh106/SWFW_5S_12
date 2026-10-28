"""Node inventory values and side-effect-free validation."""

import ipaddress
import re
import unicodedata
from dataclasses import dataclass
from enum import StrEnum

from fleet_manager.errors import InvalidNode

_HOST_LABEL = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")


class ObservationState(StrEnum):
    NOT_CHECKED = "NOT_CHECKED"


@dataclass(frozen=True, slots=True)
class NewNode:
    name: str
    address: str
    ssh_port: int


@dataclass(frozen=True, slots=True)
class Node:
    id: int
    name: str
    address: str
    ssh_port: int
    observation_state: ObservationState


def validate_new_node(name: str, address: str, ssh_port: int) -> NewNode:
    """Normalize an inventory record without resolving or contacting its address."""
    if not isinstance(name, str):
        raise InvalidNode("name must be text")
    clean_name = name.strip()
    if not clean_name or len(clean_name) > 100:
        raise InvalidNode("name must contain 1 to 100 characters after trimming")
    if any(unicodedata.category(character) == "Cc" for character in clean_name):
        raise InvalidNode("name must not contain control characters")

    if not isinstance(address, str):
        raise InvalidNode("address must be text")
    clean_address = address.strip()
    if not clean_address:
        raise InvalidNode("address is required")
    if "%" in clean_address:
        raise InvalidNode("IPv6 scope identifiers are not supported")

    try:
        normalized_address = str(ipaddress.ip_address(clean_address))
    except ValueError:
        if len(clean_address) > 253 or all(char in "0123456789." for char in clean_address):
            raise InvalidNode("address must be an IP address or valid ASCII hostname") from None
        if not all(_HOST_LABEL.fullmatch(label) for label in clean_address.split(".")):
            raise InvalidNode("address must be an IP address or valid ASCII hostname") from None
        normalized_address = clean_address.lower()

    if type(ssh_port) is not int or not 1 <= ssh_port <= 65535:
        raise InvalidNode("ssh_port must be an integer from 1 to 65535")

    return NewNode(clean_name, normalized_address, ssh_port)
