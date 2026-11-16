"""End-to-end tests: real Docker, real Postgres, the plugin run by an inner pytest."""

from __future__ import annotations

import socket

import docker
import pytest
from docker.errors import DockerException

from pytest_servex import _docker


def _docker_available() -> bool:
    try:
        client = docker.from_env()
        client.ping()
        client.close()
    except DockerException:
        return False
    return True


pytestmark = pytest.mark.skipif(not _docker_available(), reason="needs a Docker daemon")

# The inner suite: prepare creates a table and records each call; every test inserts a row
# and records which database it saw. Two tests seeing an empty table proves each worker
# database starts as a copy of the template, not as a shared database.
INNER_CONFTEST = """
import os
from pathlib import Path

import psycopg
import pytest

LOG = Path(os.environ["SERVEX_TEST_LOG"])


@pytest.fixture(scope="session")
def servex_postgres_prepare():
    def prepare(url):
        with LOG.open("a") as f:
            f.write("prepare\\n")
        with psycopg.connect(url, autocommit=True) as conn:
            conn.execute("CREATE TABLE item (id serial PRIMARY KEY, worker text)")
    return prepare
"""

INNER_TESTS = """
import os
from pathlib import Path

import psycopg
import pytest

LOG = Path(os.environ["SERVEX_TEST_LOG"])


@pytest.mark.parametrize("n", range(4))
def test_insert(servex_postgres, n):
    with psycopg.connect(servex_postgres.url, autocommit=True) as conn:
        before = conn.execute("SELECT count(*) FROM item").fetchone()[0]
        conn.execute("INSERT INTO item (worker) VALUES (%s)", (servex_postgres.name,))
    with LOG.open("a") as f:
        f.write(f"test {servex_postgres.name} {before}\\n")
"""


def _servex_containers() -> int:
    client = docker.from_env()
    try:
        return len(client.containers.list(filters={"label": _docker.LABEL}))
    finally:
        client.close()


def _run(pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch, *args: str) -> list[str]:
    log = pytester.path / "servex.log"
    pytester.makeconftest(INNER_CONFTEST)
    pytester.makepyfile(test_inner=INNER_TESTS)
    monkeypatch.setenv("SERVEX_TEST_LOG", str(log))
    result = pytester.runpytest_subprocess(*args)
    result.assert_outcomes(passed=4)
    return log.read_text().splitlines()


def test_serial_run_uses_one_database(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    before = _servex_containers()
    lines = _run(pytester, monkeypatch, "-p", "no:parallex")
    assert lines.count("prepare") == 1
    tests = [line for line in lines if line.startswith("test ")]
    assert {line.split()[1] for line in tests} == {"servex_main"}
    assert sorted(int(line.split()[2]) for line in tests) == [0, 1, 2, 3]
    assert _servex_containers() == before  # removed at session end


def test_parallex_fork_shares_container_and_template(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    lines = _run(pytester, monkeypatch, "--parallel=fork", "--parallel-workers=2")
    assert lines.count("prepare") == 1  # template built once, in the controller
    tests = [line.split() for line in lines if line.startswith("test ")]
    workers = {name for _, name, _ in tests}
    assert workers <= {"servex_f0", "servex_f1"}
    for worker in workers:
        counts = sorted(int(count) for _, name, count in tests if name == worker)
        assert counts == list(range(len(counts)))  # each worker starts from the empty template


def test_stale_container_of_dead_run_is_removed() -> None:
    client = docker.from_env()
    try:
        dead = client.containers.run(
            "alpine:3",
            command=["sleep", "300"],
            labels={
                _docker.LABEL: "test",
                _docker.LABEL_PID: "999999999",  # above pid_max: never a live process
                _docker.LABEL_HOST: socket.gethostname(),
            },
            detach=True,
            auto_remove=True,
        )
        removed = _docker.remove_stale_containers()
        assert dead.id in removed
    finally:
        client.close()
