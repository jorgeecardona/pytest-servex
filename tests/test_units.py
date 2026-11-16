"""Tests for the pure functions: no Docker, no Postgres."""

import pytest

from pytest_servex import _docker, postgres
from pytest_servex.postgres import PostgresDatabase


@pytest.mark.parametrize(
    ("docker_host", "expected"),
    [
        (None, "127.0.0.1"),
        ("", "127.0.0.1"),
        ("unix:///var/run/docker.sock", "127.0.0.1"),
        ("tcp://10.0.0.5:2375", "10.0.0.5"),
        ("ssh://me@build-box", "build-box"),
    ],
)
def test_docker_host_address(docker_host: str | None, expected: str) -> None:
    assert _docker.docker_host_address(docker_host) == expected


def test_stale_only_when_same_host_and_dead() -> None:
    labels = {_docker.LABEL_HOST: "here"}
    assert _docker.is_stale(labels, "here", pid_alive=False)
    assert not _docker.is_stale(labels, "here", pid_alive=True)
    assert not _docker.is_stale(labels, "elsewhere", pid_alive=False)


def test_with_database_keeps_credentials_and_query() -> None:
    url = "postgresql://u:p@h:5432/postgres?sslmode=disable"
    assert postgres.with_database(url, "db1") == "postgresql://u:p@h:5432/db1?sslmode=disable"


@pytest.mark.parametrize("name", ["Upper", "has-dash", "1starts_digit", 'x"; DROP', "a" * 64])
def test_unsafe_identifier_is_refused(name: str) -> None:
    with pytest.raises(ValueError, match="not a safe database name"):
        postgres.check_identifier(name)


@pytest.mark.parametrize(
    ("worker", "expected"),
    [("main", "servex_main"), ("f0", "servex_f0"), ("gw1", "servex_gw1"), ("W-2", "servex_w_2")],
)
def test_worker_database_name(worker: str, expected: str) -> None:
    assert postgres.worker_database_name("servex", worker) == expected


@pytest.mark.parametrize(
    ("image", "data"),
    [
        ("postgres:17-alpine", "/var/lib/postgresql/data"),
        ("postgres:16.4", "/var/lib/postgresql/data"),
        ("postgres:18", "/var/lib/postgresql"),
        ("postgres:18-alpine", "/var/lib/postgresql"),
        ("my.registry/postgres", "/var/lib/postgresql/data"),
    ],
)
def test_postgres_image_moves_tmpfs_for_18(image: str, data: str) -> None:
    service = postgres.postgres_image(image)
    assert service.image == image
    assert service.tmpfs == (data,)


def test_sqlalchemy_url() -> None:
    database = PostgresDatabase(name="d", url="postgresql://u:p@h:1/d")
    assert database.sqlalchemy_url() == "postgresql+psycopg://u:p@h:1/d"
    assert database.sqlalchemy_url("asyncpg") == "postgresql+asyncpg://u:p@h:1/d"
