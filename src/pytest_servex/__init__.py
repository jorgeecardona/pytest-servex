"""Pytest fixtures that start test services in Docker once per run and give each worker its own database."""

from pytest_servex._docker import ServiceStartError
from pytest_servex.postgres import POSTGRES, PostgresDatabase, PostgresServer
from pytest_servex.service import Endpoint, Service

__version__ = "0.1.0"  # the single source of truth; pyproject reads it via [tool.hatch.version]

__all__ = [
    "POSTGRES",
    "Endpoint",
    "PostgresDatabase",
    "PostgresServer",
    "Service",
    "ServiceStartError",
    "__version__",
]
