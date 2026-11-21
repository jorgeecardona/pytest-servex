"""A pytest plugin that starts the Docker containers your tests need, one database per worker."""

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
from pytest_servex.lifecycle import logs, refresh, remove_stale, running, start, stop
from pytest_servex.postgres import POSTGRES, PostgresDatabase, PostgresServer
from pytest_servex.ready import http_ready, log_ready
from pytest_servex.spec import (
    Bind,
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

__version__ = "0.4.2"  # the single source of truth; pyproject reads it via [tool.hatch.version]

__all__ = [
    "POSTGRES",
    "REDIS",
    "VALKEY",
    "Bind",
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
    "http_ready",
    "log_ready",
    "logs",
    "refresh",
    "remove_stale",
    "running",
    "start",
    "stop",
]
