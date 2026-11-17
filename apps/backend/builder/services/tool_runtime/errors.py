"""Tool runtime errors. Each maps to one HTTP status in ``builder.api``."""
from __future__ import annotations


class ToolRuntimeError(Exception):
    """Base class. ``message`` is safe to show the end user."""

    status_code = 500

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class ToolNotFound(ToolRuntimeError):
    status_code = 404


class ServerNotAuthorized(ToolRuntimeError):
    """The server doesn't exist for this user, or they may not use it."""

    status_code = 404


class NotConnected(ToolRuntimeError):
    """The user hasn't connected their own account/credential for the server."""

    status_code = 409

    def __init__(self, message: str, server_id: str):
        super().__init__(message)
        self.server_id = server_id


class InvalidArguments(ToolRuntimeError):
    status_code = 422

    def __init__(self, message: str, errors: list[str]):
        super().__init__(message)
        self.errors = errors


class ConfirmationRequired(ToolRuntimeError):
    """A tool that changes data was called without explicit confirmation."""

    status_code = 409

    def __init__(self, message: str, risk: str):
        super().__init__(message)
        self.risk = risk


class ToolTimeout(ToolRuntimeError):
    status_code = 504


class ToolUnavailable(ToolRuntimeError):
    """The server couldn't be started/reached, or the call failed in transit.

    ``may_have_run`` is True when the request had already been sent: the tool
    may or may not have executed, so a data-changing tool must not be retried
    blindly.
    """

    status_code = 502

    def __init__(self, message: str, may_have_run: bool = False):
        super().__init__(message)
        self.may_have_run = may_have_run
