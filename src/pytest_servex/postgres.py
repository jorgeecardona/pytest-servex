"""Postgres: the service definition, a migrated template database, and a clone per worker.

The template is built once per run (migrations and seed data go in here). Each worker
then gets its own database with ``CREATE DATABASE ... TEMPLATE``, which copies the
template's files instead of replaying migrations.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import Any
from urllib.parse import quote, urlsplit, urlunsplit

import psycopg
from psycopg import sql

from pytest_servex.spec import Container, Endpoint, RunningContainer, Tmpfs

USER = "servex"
PASSWORD = "servex"  # noqa: S105  # a throwaway container on 127.0.0.1
ADMIN_DATABASE = "postgres"

_IDENTIFIER = re.compile(r"[a-z_][a-z0-9_]{0,62}")


PORT = 5432
FIRST_MAJOR_WITH_NEW_DATA_PATH = 18


def _ready(started: RunningContainer) -> bool:
    """True once Postgres answers a query over TCP.

    The image runs ``initdb`` with a temporary server that does not listen on TCP, so a
    TCP connection only succeeds once the real server is up.
    """
    try:
        with psycopg.connect(admin_url(started.endpoint(PORT)), connect_timeout=1) as conn:
            conn.execute("SELECT 1")
    except psycopg.OperationalError:
        return False
    return True


POSTGRES = Container(
    image="postgres:17-alpine",
    ports=(PORT,),
    ready=_ready,
    env={"POSTGRES_USER": USER, "POSTGRES_PASSWORD": PASSWORD},
    # Durability settings off: test data never needs to survive a crash.
    command=(
        "postgres",
        "-c",
        "fsync=off",
        "-c",
        "synchronous_commit=off",
        "-c",
        "full_page_writes=off",
    ),
    mounts=(Tmpfs("/var/lib/postgresql/data"),),
)


def admin_url(endpoint: Endpoint) -> str:
    """Return the libpq URL of the ``postgres`` database on a servex container."""
    return f"postgresql://{USER}:{quote(PASSWORD)}@{endpoint.host}:{endpoint.port}/{ADMIN_DATABASE}"


def with_database(url: str, database: str) -> str:
    """Return ``url`` pointing at ``database`` instead, keeping credentials and query."""
    parts = urlsplit(url)
    return urlunsplit(parts._replace(path=f"/{database}"))


def check_identifier(name: str) -> str:
    """Return ``name`` if it is a safe unquoted Postgres identifier, else raise ValueError.

    Names are quoted with ``psycopg.sql.Identifier``. The rule still refuses uppercase and
    punctuation, so the name a user passes is the name ``psql`` shows, with no quoting.
    """
    if not _IDENTIFIER.fullmatch(name):
        raise ValueError(f"not a safe database name: {name!r} (use [a-z_][a-z0-9_]*, max 63)")
    return name


@dataclass(frozen=True)
class PostgresServer:
    """A Postgres server for this run, as a URL to its admin (``postgres``) database.

    Only strings: safe to hand to forked or spawned workers.
    """

    url: str

    def database_url(self, database: str) -> str:
        """Return the URL of ``database`` on this server."""
        return with_database(self.url, database)


@dataclass(frozen=True)
class PostgresDatabase:
    """One database on the run's server, owned by one worker."""

    name: str
    url: str

    def sqlalchemy_url(self, driver: str = "psycopg") -> str:
        """Return ``url`` with a SQLAlchemy driver in the scheme (``postgresql+psycopg://``)."""
        return re.sub(r"^postgres(ql)?://", f"postgresql+{driver}://", self.url)


def _terminate_and_drop(conn: psycopg.Connection[Any], name: str) -> None:
    conn.execute(
        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
        "WHERE datname = %s AND pid <> pg_backend_pid()",
        (name,),
    )
    conn.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(name)))


def create_empty(server: PostgresServer, name: str) -> PostgresDatabase:
    """Create (or recreate) an empty database ``name`` and return it."""
    check_identifier(name)
    with psycopg.connect(server.url, autocommit=True) as conn:
        _terminate_and_drop(conn, name)
        conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    return PostgresDatabase(name=name, url=server.database_url(name))


def clone(server: PostgresServer, template: str, name: str) -> PostgresDatabase:
    """Create (or recreate) database ``name`` as a copy of database ``template``.

    Postgres refuses to copy a template that has open connections, so close every
    connection to the template before calling this.
    """
    check_identifier(template)
    check_identifier(name)
    with psycopg.connect(server.url, autocommit=True) as conn:
        _terminate_and_drop(conn, name)
        conn.execute(
            sql.SQL("CREATE DATABASE {} TEMPLATE {}").format(
                sql.Identifier(name), sql.Identifier(template)
            )
        )
    return PostgresDatabase(name=name, url=server.database_url(name))


def drop(server: PostgresServer, name: str) -> None:
    """Drop database ``name``, closing its open connections first. Missing is fine."""
    check_identifier(name)
    with psycopg.connect(server.url, autocommit=True) as conn:
        _terminate_and_drop(conn, name)


def worker_database_name(prefix: str, worker_id: str) -> str:
    """Return the database name for one worker (``servex_f0``, ``servex_gw1``, ``servex_main``)."""
    safe = re.sub(r"[^a-z0-9_]", "_", worker_id.lower())
    return check_identifier(f"{prefix}_{safe}")


def postgres_image(image: str) -> Container:
    """Return the Postgres service with another image, for example ``postgres:18``.

    Postgres 18 images keep data under ``/var/lib/postgresql`` instead of
    ``/var/lib/postgresql/data``, so the tmpfs mount follows the major version.
    """
    tag = image.rsplit(":", 1)[-1] if ":" in image else ""
    major = tag.split(".", 1)[0].split("-", 1)[0]
    new_layout = major.isdigit() and int(major) >= FIRST_MAJOR_WITH_NEW_DATA_PATH
    data = "/var/lib/postgresql" if new_layout else "/var/lib/postgresql/data"
    return replace(POSTGRES, image=image, mounts=(Tmpfs(data),))
