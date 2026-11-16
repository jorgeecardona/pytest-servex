"""Skip marker for tests that need a running Docker daemon."""

import pytest

from pytest_servex import ServexError
from pytest_servex._engine import Engine


def _docker_available() -> bool:
    try:
        with Engine(timeout=2) as engine:
            engine.raw("GET", "/_ping", query={})
    except (ServexError, OSError):
        return False
    return True


needs_docker = pytest.mark.skipif(not _docker_available(), reason="needs a Docker daemon")
