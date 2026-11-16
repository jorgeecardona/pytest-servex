"""The data that describes a test service, and where a started one listens."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class Endpoint:
    """A host and port where a started service accepts connections."""

    host: str
    port: int


@dataclass(frozen=True)
class Service:
    """One container image to start for a test run, and how to tell when it is ready.

    The fields are plain data so a service definition can be shared, compared, and
    changed with ``dataclasses.replace`` (for example to pin another image tag).

    Args:
        name: Short name used in container names and labels (``"postgres"``).
        image: Image reference. Pin a tag; ``latest`` gets pulled again.
        port: The port the service listens on inside the container.
        ready: Returns True once the service accepts real work at the endpoint. It is
            called in a loop until it returns True or the start timeout passes. It must
            not raise for "not ready yet"; return False instead.
        env: Environment variables for the container, as ``(name, value)`` pairs.
        command: Replaces the image's default command when not empty.
        tmpfs: Paths inside the container to mount as tmpfs (data in memory, no disk
            writes). Test data does not need to survive the container.
    """

    name: str
    image: str
    port: int
    ready: Callable[[Endpoint], bool]
    env: tuple[tuple[str, str], ...] = ()
    command: tuple[str, ...] = ()
    tmpfs: tuple[str, ...] = ()
