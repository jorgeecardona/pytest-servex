"""The pytest plugin: Postgres and Valkey fixtures, one server per run, one database per worker.

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
from dataclasses import replace

import pytest

from pytest_servex import postgres, valkey
from pytest_servex.lifecycle import remove_stale, running
from pytest_servex.postgres import PostgresDatabase, PostgresServer
from pytest_servex.valkey import ValkeyDatabase, ValkeyServer

ENV_URL = "SERVEX_POSTGRES_URL"
ENV_IMAGE = "SERVEX_POSTGRES_IMAGE"
ENV_VALKEY_URL = "SERVEX_VALKEY_URL"
ENV_VALKEY_IMAGE = "SERVEX_VALKEY_IMAGE"
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
    remove_stale()
    with running(service) as started:
        yield PostgresServer(url=postgres.admin_url(started.endpoint(postgres.PORT)))


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
    _fresh.add(name)
    try:
        yield database
    finally:
        postgres.drop(servex_postgres_server, name)


_fresh: set[str] = set()  # worker databases not used by any test yet; per process, so per worker


@pytest.fixture
def servex_postgres_clean(
    servex_postgres_server: PostgresServer,
    servex_postgres_template: str,
    servex_postgres: PostgresDatabase,
) -> PostgresDatabase:
    """This worker's database, reset to a fresh copy of the template before the test.

    Use it instead of ``servex_postgres`` when tests must not see each other's rows. The
    reset drops the database and clones the template again, so seed data from
    ``servex_postgres_prepare`` comes back too. It closes every open connection to the
    database: create engines and pools inside the test, or use SQLAlchemy's
    ``pool_pre_ping=True``. Measured at 175 ms per reset for 66 tables, about half the
    cost of a ``TRUNCATE`` of the same tables.
    """
    if servex_postgres.name in _fresh:
        _fresh.discard(servex_postgres.name)  # the first test gets the new clone as is
        return servex_postgres
    return postgres.clone(servex_postgres_server, servex_postgres_template, servex_postgres.name)


@pytest.fixture(scope="session")
def servex_valkey_server() -> Iterator[ValkeyServer]:
    """The run's Valkey server.

    If ``SERVEX_VALKEY_URL`` is set (``redis://[:password@]host:port``), that server is used
    and nothing is started. Otherwise a container is started from ``SERVEX_VALKEY_IMAGE``
    (default ``valkey/valkey:8-alpine``; a ``redis:`` image works too) and removed at the
    end of the run.
    """
    if url := os.environ.get(ENV_VALKEY_URL):
        yield ValkeyServer(url=url)
        return
    service = valkey.VALKEY
    if image := os.environ.get(ENV_VALKEY_IMAGE):
        binary = "redis-server" if "redis" in image.rsplit("/", 1)[-1] else "valkey-server"
        service = replace(valkey.VALKEY, image=image, command=(binary, *valkey.VALKEY.command[1:]))
    remove_stale()
    with running(service) as started:
        yield ValkeyServer(url=valkey.url_for(started.endpoint(valkey.PORT)))


@pytest.fixture(scope="session")
def servex_valkey(servex_valkey_server: ValkeyServer, worker_id: str) -> Iterator[ValkeyDatabase]:
    """This worker's own database number, flushed at worker start and at worker end."""
    database = valkey.claim(servex_valkey_server, valkey.worker_index(worker_id))
    try:
        yield database
    finally:
        valkey.claim(servex_valkey_server, database.index)
