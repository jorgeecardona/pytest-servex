"""Starts the Docker containers your tests need, once per test run, and shares them with all workers."""

from pytest_servex.errors import (
    Conflict,
    DockerError,
    DockerUnavailable,
    ImageNotFound,
    NotFound,
    NotReady,
    ServexError,
)
from pytest_servex.fixtures import container_fixture
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
from pytest_servex.valkey import REDIS, VALKEY, ValkeyDatabase, ValkeyServer

__version__ = "0.2.0"  # the single source of truth; pyproject reads it via [tool.hatch.version]

__all__ = [
    "POSTGRES",
    "REDIS",
    "VALKEY",
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
    "ValkeyDatabase",
    "ValkeyServer",
    "Volume",
    "__version__",
    "container_fixture",
    "remove_stale",
    "running",
    "start",
    "stop",
]
