"""Turn any ``Container`` spec into a pytest fixture with one line."""

from __future__ import annotations

from collections.abc import Callable, Iterator

import pytest

from pytest_servex.lifecycle import remove_stale, running
from pytest_servex.spec import Container, RunningContainer


def container_fixture(
    spec: Container, *, timeout: float = 60.0
) -> Callable[[], Iterator[RunningContainer]]:
    """Return a session fixture that starts ``spec`` once per run and yields it running.

    Assign it to a name in ``conftest.py``; that name becomes the fixture name::

        api = container_fixture(Container(image="myorg/api:1.4", ports=(8080,)))

        def test_health(api):
            host, port = api.endpoint(8080).host, api.endpoint(8080).port

    Under pytest-parallex the container starts once, before the workers fork, and every
    worker shares it. Under pytest-xdist each worker starts its own. The container is
    removed at the end of the run; containers of killed runs are removed first.
    """

    @pytest.fixture(scope="session")
    def _container() -> Iterator[RunningContainer]:
        remove_stale()
        with running(spec, timeout=timeout) as started:
            yield started

    return _container
