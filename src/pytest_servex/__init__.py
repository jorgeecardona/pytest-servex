"""Start Docker containers, networks and volumes from frozen dataclasses, in pytest or plain Python, once per test run and shared by parallel workers."""

from pytest_servex.errors import (
    Conflict,
    DockerError,
    DockerUnavailable,
    ImageNotFound,
    NotFound,
    NotReady,
    ServexError,
)
from pytest_servex.lifecycle import remove_stale, running, start, stop
from pytest_servex.postgres import POSTGRES, PostgresDatabase, PostgresServer
from pytest_servex.spec import (
    Container,
    Endpoint,
    Mount,
    Network,
    RunningContainer,
    RunningNetwork,
    RunningVolume,
    Tmpfs,
    Volume,
)

__version__ = "0.1.2"  # the single source of truth; pyproject reads it via [tool.hatch.version]

__all__ = [
    "POSTGRES",
    "Conflict",
    "Container",
    "DockerError",
    "DockerUnavailable",
    "Endpoint",
    "ImageNotFound",
    "Mount",
    "Network",
    "NotFound",
    "NotReady",
    "PostgresDatabase",
    "PostgresServer",
    "RunningContainer",
    "RunningNetwork",
    "RunningVolume",
    "ServexError",
    "Tmpfs",
    "Volume",
    "__version__",
    "remove_stale",
    "running",
    "start",
    "stop",
]
