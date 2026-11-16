"""End-to-end tests: real Docker, real Postgres, the plugin run by an inner pytest."""

from __future__ import annotations

import socket
from typing import Any

import pytest

from pytest_servex import lifecycle
from pytest_servex._engine import Engine
from tests.docker_available import needs_docker

pytestmark = needs_docker

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
    with Engine() as engine:
        found: list[Any] = engine.call(
            "GET", "/containers/json", query={"filters": f'{{"label": ["{lifecycle.LABEL}"]}}'}
        )
    return len(found)


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


def test_objects_of_a_dead_run_are_removed() -> None:
    dead = {
        lifecycle.LABEL: "1",
        lifecycle.LABEL_PID: "999999999",  # above pid_max: never a live process
        lifecycle.LABEL_HOST: socket.gethostname(),
    }
    with Engine() as engine:
        engine.call("POST", "/volumes/create", body={"Name": "servex_dead_v", "Labels": dead})
        net = engine.call(
            "POST", "/networks/create", body={"Name": "servex_dead_n", "Labels": dead}
        )
        ctr = engine.call(
            "POST",
            "/containers/create",
            body={"Image": "alpine:3", "Cmd": ["sleep", "300"], "Labels": dead},
        )
    assert lifecycle.remove_stale() >= 3
    with Engine() as engine:
        for path in (
            f"/containers/{ctr['Id']}/json",
            f"/networks/{net['Id']}",
            "/volumes/servex_dead_v",
        ):
            with pytest.raises(LookupError):
                engine.call("GET", path)


INNER_CLEAN = """
import psycopg
import pytest


@pytest.fixture(scope="session")
def servex_postgres_prepare():
    def prepare(url):
        with psycopg.connect(url, autocommit=True) as conn:
            conn.execute("CREATE TABLE item (id int)")
            conn.execute("INSERT INTO item VALUES (1)")  # seed row
    return prepare


@pytest.mark.parametrize("n", range(3))
def test_sees_only_the_seed(servex_postgres_clean, n):
    with psycopg.connect(servex_postgres_clean.url, autocommit=True) as conn:
        assert conn.execute("SELECT count(*) FROM item").fetchone()[0] == 1
        conn.execute("INSERT INTO item VALUES (2)")
"""


def test_clean_fixture_resets_between_tests(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(test_inner=INNER_CLEAN)
    pytester.runpytest_subprocess("-p", "no:parallex").assert_outcomes(passed=3)
