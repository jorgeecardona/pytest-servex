# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- `servex_postgres`: a Postgres database for each worker, copied from a template built once per run.
- `servex_postgres_prepare`: override it to run migrations or insert seed data into the template.
- `SERVEX_POSTGRES_URL` uses an existing server instead of starting a container.
- `SERVEX_POSTGRES_IMAGE` picks the Postgres image, including Postgres 18.
- Containers, networks and volumes left by a killed run are removed by the next run.
- `Network`, `Volume`, `Container` specs and `start`, `stop`, `running` to use containers outside pytest.
- `Container(pull=...)` with `missing`, `always`, `never`, plus `entrypoint`, `user`, `memory`, `shm_size` and `host_config`.
- Errors subclass built-ins: `NotReady` is a `TimeoutError`, `NotFound` a `LookupError`, `DockerUnavailable` a `ConnectionError`.
- A container that exits while starting fails at once with its logs, instead of waiting for the timeout.
- `SERVEX_HOST` sets where tests connect when the published ports are not on the `DOCKER_HOST` address.
- No docker SDK: the Docker API is called with the standard library.
