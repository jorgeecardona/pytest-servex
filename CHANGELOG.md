# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.4.2] - 2026-11-21

### Changed

- The PyPI summary and the README no longer say that one container serves all workers. Under
  pytest-xdist each worker starts its own container.
- The PyPI page lists Python 3.14 and no longer links to a documentation site that is not public.

## [0.4.1] - 2026-11-17

### Added

- `refresh(started)` returns the container with the ports Docker publishes now. Use it after a
  restart, which gives new host ports (#3).

### Changed

- The README says that the Postgres data directory is on tmpfs, so a restart starts a new empty
  database. Use `replace(POSTGRES, mounts=())` to keep data across a restart (#3).

## [0.4.0] - 2026-11-16

### Added

- `servex_postgres_clean`: a fresh copy of the template database before each test, seed rows
  included.

## [0.3.0] - 2026-11-16

### Added

- `Bind(source, target)` mounts a host path into a container, read-only by default (#1).
- `log_ready(pattern, times=1)` waits for a log line; `http_ready(port, path)` waits for an HTTP
  answer (#2).
- `logs(started)` returns a running container's output.

## [0.2.0] - 2026-11-16

### Added

- `servex_valkey`: a Valkey database number for each worker on one shared server. `REDIS` recipe
  and `SERVEX_VALKEY_IMAGE` for Redis.
- `container_fixture(Container(...))`: any image as a session fixture, started once per run.
- `SERVEX_VALKEY_URL` uses an existing Valkey or Redis server instead of starting a container.

## [0.1.3] - 2026-11-16

### Added

- `servex_postgres`: a Postgres database for each worker, copied from a template built once per run.
- `servex_postgres_prepare`: override it to run migrations or insert seed data into the template.
- `SERVEX_POSTGRES_URL` uses an existing server instead of starting a container.
- `SERVEX_POSTGRES_IMAGE` picks the Postgres image, including Postgres 18.
- Containers, networks and volumes left by a killed run are removed by the next run.
- `Network`, `Volume`, `Container` specs and `start`, `stop`, `running` to use containers outside
  pytest.
- `Container(pull=...)` with `missing`, `always`, `never`, plus `entrypoint`, `user`, `memory`,
  `shm_size` and `host_config`.
- Errors subclass built-ins: `NotReady` is a `TimeoutError`, `NotFound` a `LookupError`,
  `DockerUnavailable` a `ConnectionError`.
- A container that exits while starting fails at once with its logs, instead of waiting for the
  timeout.
- `SERVEX_HOST` sets where tests connect when the published ports are not on the `DOCKER_HOST`
  address.
- No docker SDK: the Docker API is called with the standard library.
