"""The pytest plugin: Postgres fixtures, one server per run and one database per worker.

Fixture graph::

    servex_postgres_server   (session, once per run: container or SERVEX_POSTGRES_URL)
      -> servex_postgres_template  (session, once per run: runs servex_postgres_prepare)
        -> servex_postgres  (session, once per worker: needs worker_id)

Under pytest-parallex the first two are built in the controller before the fork, so one
container and one template serve every worker. ``servex_postgres`` requests
``worker_id``, which is how parallex knows to build it in each worker instead.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator

import pytest

from pytest_servex import _docker, postgres
from pytest_servex.postgres import PostgresDatabase, PostgresServer

ENV_URL = "SERVEX_POSTGRES_URL"
ENV_IMAGE = "SERVEX_POSTGRES_IMAGE"
TEMPLATE_NAME = "servex_template"
WORKER_PREFIX = "servex"

Prepare = Callable[[str], None]


class _MainWorkerId:
    """Provides ``worker_id`` = ``"main"`` when neither pytest-xdist nor pytest-parallex does."""

    @pytest.fixture(scope="session")
    def worker_id(self) -> str:
        """The worker name; always ``"main"`` in a serial run without a parallel plugin."""
        return "main"


@pytest.hookimpl(trylast=True)
def pytest_configure(config: pytest.Config) -> None:
    """Register a fallback ``worker_id`` fixture if no parallel plugin provides one.

    ``trylast`` runs this after pytest-parallex's own ``pytest_configure``, which is where
    parallex registers its ``worker_id``.
    """
    has_worker_id = config.pluginmanager.hasplugin("xdist") or config.pluginmanager.hasplugin(
        "parallex-worker-id"
    )
    if not has_worker_id:
        config.pluginmanager.register(_MainWorkerId(), "servex-worker-id")


@pytest.fixture(scope="session")
def servex_postgres_server() -> Iterator[PostgresServer]:
    """The run's Postgres server.

    If ``SERVEX_POSTGRES_URL`` is set (for example in CI, with a Postgres service), that
    server is used and nothing is started. The URL must reach a database the user may
    create databases from. Otherwise a container is started from ``SERVEX_POSTGRES_IMAGE``
    (default ``postgres:17-alpine``) and removed at the end of the run.
    """
    if url := os.environ.get(ENV_URL):
        yield PostgresServer(url=url)
        return
    service = postgres.POSTGRES
    if image := os.environ.get(ENV_IMAGE):
        service = postgres.postgres_image(image)
    _docker.remove_stale_containers()
    running = _docker.start(service)
    try:
        yield PostgresServer(url=postgres.admin_url(running.endpoint))
    finally:
        _docker.stop(running)


@pytest.fixture(scope="session")
def servex_postgres_prepare() -> Prepare | None:
    """Override this to fill the template database: run migrations, insert seed rows.

    Return a function that takes the template's URL. It runs once per run, before any
    worker database is cloned. Close every connection it opens: Postgres refuses to copy a
    template with open connections. The default returns None, which leaves the template
    empty.
    """
    return None


@pytest.fixture(scope="session")
def servex_postgres_template(
    servex_postgres_server: PostgresServer,
    servex_postgres_prepare: Prepare | None,
) -> str:
    """The name of the template database, built once per run."""
    template = postgres.create_empty(servex_postgres_server, TEMPLATE_NAME)
    if servex_postgres_prepare is not None:
        servex_postgres_prepare(template.url)
    return template.name


@pytest.fixture(scope="session")
def servex_postgres(
    servex_postgres_server: PostgresServer,
    servex_postgres_template: str,
    worker_id: str,
) -> Iterator[PostgresDatabase]:
    """This worker's own database, a copy of the template. Dropped when the worker ends."""
    name = postgres.worker_database_name(WORKER_PREFIX, worker_id)
    database = postgres.clone(servex_postgres_server, servex_postgres_template, name)
    try:
        yield database
    finally:
        postgres.drop(servex_postgres_server, name)
