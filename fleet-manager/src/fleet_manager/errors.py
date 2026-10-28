"""Errors shared across application layers."""


class InvalidNode(ValueError):
    """The requested node record does not satisfy the inventory contract."""


class DuplicateNode(Exception):
    """The normalized SSH endpoint already exists in inventory."""


class StorageError(Exception):
    """Inventory storage could not complete an operation safely."""


class AuthenticationError(Exception):
    """The request does not carry the configured operator token."""


class NodeNotFound(Exception):
    """The requested inventory ID does not exist."""


class ConnectivityConfigurationError(Exception):
    """SSH verification lacks trusted identity or a configured credential."""


class ConnectivityBusy(Exception):
    """The bounded SSH worker pool has no free capacity."""


class ConnectivityInProgress(Exception):
    """This node already has an active connectivity check."""


class ConnectivityUnavailable(Exception):
    """The SSH worker could not run or the application is stopping."""


class InvalidAction(ValueError):
    """The requested action is not in the allowlisted catalog."""


class InvalidOperationArguments(ValueError):
    """The action arguments are invalid or violate typed constraints."""


class OperationBusy(Exception):
    """The bounded operation worker pool has no free capacity."""


class OperationInProgress(Exception):
    """This node already has an active operation executing."""


class OperationUnavailable(Exception):
    """The operation worker could not run or the application is stopping."""


class OperationNotFound(Exception):
    """The requested operation record does not exist."""
