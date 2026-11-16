"""Valkey and the generic fixture, end to end with real Docker and an inner pytest."""

from __future__ import annotations

from dataclasses import replace

import pytest

from pytest_servex import VALKEY, running, valkey
from pytest_servex.errors import ServexError
from pytest_servex.spec import RunningContainer
from tests.docker_available import needs_docker

pytestmark = needs_docker

INNER_VALKEY = """
import os
from pathlib import Path

import pytest
from pytest_servex import valkey

LOG = Path(os.environ["SERVEX_TEST_LOG"])


@pytest.mark.parametrize("n", range(4))
def test_isolated(servex_valkey, n):
    before = valkey.command(servex_valkey.url, ("DBSIZE",))[0]
    valkey.command(servex_valkey.url, ("SET", f"key{n}", "1"))
    with LOG.open("a") as f:
        f.write(f"{servex_valkey.index} {before}\\n")
"""

INNER_GENERIC = """
from pytest_servex import Container, container_fixture

box = container_fixture(Container(image="alpine:3", command=("sleep", "300")))


def test_one(box):
    assert len(box.id) == 64


def test_same_container(box):
    assert len(box.id) == 64
"""


def test_valkey_workers_get_their_own_database(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    log = pytester.path / "servex.log"
    pytester.makepyfile(test_inner=INNER_VALKEY)
    monkeypatch.setenv("SERVEX_TEST_LOG", str(log))
    result = pytester.runpytest_subprocess("--parallel=fork", "--parallel-workers=2")
    result.assert_outcomes(passed=4)
    rows = [line.split() for line in log.read_text().splitlines()]
    for index in {i for i, _ in rows}:
        sizes = [int(size.lstrip(":")) for i, size in rows if i == index]
        assert sorted(sizes) == list(range(len(sizes)))  # each worker sees only its own keys


def test_generic_fixture_starts_once_per_run(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(test_inner=INNER_GENERIC)
    pytester.runpytest_subprocess("-p", "no:parallex").assert_outcomes(passed=2)


def _asks_for_password(started: RunningContainer) -> bool:
    # Docker's port proxy accepts TCP before the server listens, so a TCP connect proves
    # nothing; a NOAUTH answer to PING proves the server is up.
    try:
        valkey.command(valkey.url_for(started.endpoint(valkey.PORT)), ("PING",), timeout=1)
    except ServexError as err:
        return "NOAUTH" in str(err)
    except OSError:
        return False
    return False


def test_password_is_not_in_error_messages() -> None:
    locked = replace(
        VALKEY, command=(*VALKEY.command, "--requirepass", "right"), ready=_asks_for_password
    )
    with running(locked) as started:
        endpoint = started.endpoint(valkey.PORT)
        url = f"redis://:wrong-secret@{endpoint.host}:{endpoint.port}"
        with pytest.raises(ServexError, match="AUTH") as caught:
            valkey.command(url, ("PING",))
    assert "wrong-secret" not in str(caught.value)
