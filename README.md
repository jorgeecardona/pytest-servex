# pytest-servex

[![pipeline status](https://gitlab.com/cardona-oss/pytest-servex/badges/main/pipeline.svg)](https://gitlab.com/cardona-oss/pytest-servex/-/pipelines)
[![PyPI version](https://img.shields.io/pypi/v/pytest-servex.svg)](https://pypi.org/project/pytest-servex/)
[![Python versions](https://img.shields.io/pypi/pyversions/pytest-servex.svg)](https://pypi.org/project/pytest-servex/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](https://gitlab.com/cardona-oss/pytest-servex/-/blob/main/LICENSE)

Starts the Docker containers your tests need, once per test run, and shares them with all workers.
Any image works, in pytest or plain Python. Postgres has a ready-made recipe with one database per
worker.

## Install

```bash
pip install pytest-servex "psycopg[binary]"
```

Requires Python 3.12+ and a Docker daemon. Talks to the Docker API directly with the standard
library: no docker SDK, no requests.

## Quickstart

Request `servex_postgres` in a test. It is a database of your own, on a container started once
for the run:

```python
import psycopg


def test_insert(servex_postgres):
    with psycopg.connect(servex_postgres.url) as conn:
        conn.execute("CREATE TABLE t (x int)")
        conn.execute("INSERT INTO t VALUES (1)")
```

To run migrations once, override `servex_postgres_prepare` in `conftest.py`. Every worker
database starts as a copy of the result:

```python
import subprocess

import pytest


@pytest.fixture(scope="session")
def servex_postgres_prepare():
    def prepare(url: str) -> None:
        subprocess.run(["alembic", "upgrade", "head"], env={"DATABASE_URL": url}, check=True)

    return prepare
```

## Valkey and Redis

Request `servex_valkey`. Each worker gets its own database number on one shared server, flushed
when the worker starts and ends:

```python
import redis


def test_cache(servex_valkey):
    r = redis.Redis.from_url(servex_valkey.url)  # redis://127.0.0.1:32772/0
    r.set("k", "v")
```

The container runs with persistence off and 128 databases. Set `SERVEX_VALKEY_IMAGE=redis:7-alpine`
to test against Redis instead.

## Any image

`container_fixture` turns a `Container` into a session fixture. The variable name is the fixture
name:

```python
from pytest_servex import Container, container_fixture

api = container_fixture(Container(image="myorg/api:1.4", ports=(8080,), env={"MODE": "test"}))


def test_health(api):
    endpoint = api.endpoint(8080)  # Endpoint(host='127.0.0.1', port=32773)
```

Pass `ready=` to wait for the service. Speak its protocol (a query, a `PING`, an HTTP request):
Docker accepts TCP connections on the published port before the service listens.

## How Postgres works

1. `servex_postgres_server` starts one Postgres container for the run, with `fsync` off and
   data on tmpfs.
2. `servex_postgres_template` creates the database `servex_template` and runs your prepare
   function on it, once.
3. `servex_postgres` copies the template into one database per worker
   (`CREATE DATABASE servex_f0 TEMPLATE servex_template`). This copies files, so it takes
   milliseconds instead of a migration run.

Under [pytest-parallex](https://pypi.org/project/pytest-parallex/) steps 1 and 2 run once in
the controller, before the fork. Under pytest-xdist each worker runs its own session, so each
worker starts its own container.

## Outside pytest

Specs are frozen dataclasses. `running` starts one on enter and removes it on exit, so nested
blocks stop in reverse order:

```python
from dataclasses import replace

from pytest_servex import POSTGRES, Network, running

net = Network("app")
pg = replace(POSTGRES, networks=(net,), alias="db", pull="never")

with running(net), running(pg) as started:
    print(started.endpoint(5432))  # Endpoint(host='127.0.0.1', port=32771)
```

Errors subclass the built-in they resemble, and all subclass `ServexError`:

| Error | Also a | When |
|---|---|---|
| `NotReady` | `TimeoutError` | The ready check timed out, or the container exited first. Has `.logs`. |
| `ImageNotFound` | `LookupError` | The image is missing and `pull="never"`, or the pull failed. |
| `NotFound` | `LookupError` | Docker has no such object (HTTP 404). |
| `Conflict` | | A name is taken, or a network or volume is still in use (HTTP 409). |
| `DockerUnavailable` | `ConnectionError` | The Docker socket is missing or refuses connections. |

## Configuration

- `SERVEX_POSTGRES_URL`: use this server and start nothing (for example a CI service). It must
  point at a database whose user may create databases.
- `SERVEX_POSTGRES_IMAGE`: the image to start. Default `postgres:17-alpine`.
- `SERVEX_VALKEY_URL`: use this Valkey or Redis server and start nothing
  (`redis://[:password@]host:port`). An external server has 16 databases by default, so at most
  16 workers.
- `SERVEX_VALKEY_IMAGE`: the image to start. Default `valkey/valkey:8-alpine`.
- `DOCKER_HOST`: the Docker API, `unix://` or `tcp://`. Podman's Docker-compatible socket is
  meant to work but is not tested yet.
- `SERVEX_HOST`: where tests connect to published ports, when that is not the `DOCKER_HOST`
  address (for example `docker` with a GitLab `docker:dind` service).

## Compared to testcontainers

- No Ryuk container. Containers carry labels with the run's pid. The next run removes the
  containers of runs that were killed.
- No Docker client crosses a fork. Fixtures hand workers plain URL strings.
- A template database and one copy per worker are built in, not left to each `conftest.py`.

## Links

- Documentation: https://cardona-oss.gitlab.io/pytest-servex/
- Source: https://gitlab.com/cardona-oss/pytest-servex
- Issues: https://gitlab.com/cardona-oss/pytest-servex/-/issues
- Changelog: https://gitlab.com/cardona-oss/pytest-servex/-/blob/main/CHANGELOG.md

## License

MIT © 2026 Jorge Cardona.
