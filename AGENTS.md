# AGENTS.md

Guidance for AI coding agents working in this repo. Humans: read README.md and CHANGELOG.md.

## Overview

pytest-servex: Starts the Docker containers your tests need, once per test run, and shares them with all workers.

## Build

- `uv sync` installs dependencies. Toolchain (moon, uv) is pinned in `.prototools`; `proto install` brings it up.
- `make install-hooks` once, to enable the tracked git hooks.

## Test

- `make test` runs the suite.
- `make check` runs lint + typecheck + test (the same stage CI runs via `moon run :ci`).
- Everything in `make check` must pass before you commit.

## Style

- Format and autofix: `make format` (ruff, line length 100).
- Lint: `make lint`. Types: `make typecheck` (pyright strict on `src/`).
- Prefer frozen dataclasses and explicit types. Keep the public API typed (`py.typed`).

## Design rules

Jorge, 2026-11-16: the Zen of Python is the guide.

- Frozen dataclasses for every spec (`Network`, `Volume`, `Tmpfs`, `Container`) and every
  result (`RunningContainer`). Change one with `dataclasses.replace`, never by mutation.
- Plain verbs: `start()`, `stop()`, and the context manager `running()`. No builder chains
  (`.with_env().with_port()`), no class per service. A service is data: `POSTGRES = Container(...)`.
- Flat, explicit flow: `with running(net), running(pg) as started:`.
- Results hold ids and endpoints only, never a live Docker client.

## Gotchas

- Most tests need a Docker daemon. They skip themselves without one (`tests/docker_available.py`).
- `tests/test_flows.py` model-checks start, stop, crash and cleanup order with musil. Change it
  when the lifecycle order changes.
- Never keep a Docker client in a fixture value or module global. Under pytest-parallex the
  controller forks workers, and a shared client socket breaks. Open and close one per call
  (see `_engine.py`, which uses stdlib `http.client`; do not add the docker SDK).
- Fixtures that must run once per worker request `worker_id`. That is how parallex knows not
  to build them in the controller.

- Version lives as `__version__` in `src/pytest_servex/__init__.py`; `pyproject.toml` reads it via `[tool.hatch.version]` (`version` is `dynamic`). The pre-commit hook auto-bumps it when `src/` changes. Do not edit versions by hand elsewhere.
- Record follow-ups in `docs/issues/`, not as scattered TODO comments.
