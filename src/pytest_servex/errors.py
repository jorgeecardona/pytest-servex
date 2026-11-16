"""Exceptions. Each one also subclasses the built-in it resembles, so plain ``except`` works.

``except ServexError`` catches everything this library raises. ``except TimeoutError``
catches ``NotReady``; ``except LookupError`` catches ``NotFound``; ``except ConnectionError``
catches ``DockerUnavailable``.
"""

from __future__ import annotations


class ServexError(Exception):
    """Base class of every error pytest-servex raises."""


class DockerUnavailable(ServexError, ConnectionError):  # noqa: N818  # reads as a state, like TimeoutError
    """The Docker API socket is missing or refuses connections (is the daemon running?)."""


class DockerError(ServexError):
    """The Docker API answered with an error status.

    Args:
        status: The HTTP status code.
        message: Docker's own error message.
    """

    def __init__(self, status: int, message: str) -> None:
        """Keep the status and Docker's message."""
        super().__init__(f"Docker API {status}: {message}")
        self.status = status
        self.message = message


class NotFound(DockerError, LookupError):  # noqa: N818
    """Docker has no such container, network, volume, or image (HTTP 404)."""


class Conflict(DockerError):  # noqa: N818  # pairs with NotFound
    """The name is taken, or the object is still in use (HTTP 409)."""


class ImageNotFound(NotFound):
    """The image is not local and the pull policy forbids pulling it, or the pull failed."""


class NotReady(ServexError, TimeoutError):  # noqa: N818
    """A container did not pass its ``ready`` check: it timed out, or it exited first.

    The container is removed before this is raised. ``logs`` holds its last lines.
    """

    def __init__(self, image: str, reason: str, logs: str) -> None:
        """Keep the image and the container's last log lines."""
        super().__init__(f"{image} not ready: {reason}. Last logs:\n{logs}")
        self.image = image
        self.logs = logs


def docker_error(status: int, message: str) -> DockerError:
    """Return the most specific ``DockerError`` subclass for an HTTP status."""
    if status == 404:  # noqa: PLR2004
        return NotFound(status, message)
    if status == 409:  # noqa: PLR2004
        return Conflict(status, message)
    return DockerError(status, message)
