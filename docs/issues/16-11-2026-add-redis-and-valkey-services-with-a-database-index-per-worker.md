---
title: Add Redis and Valkey services with a database index per worker
status: done
area: redis
owner: null
filed: 2026-11-16
fixed_in: null
scope: M
verify: test
---

Add `servex_redis` and `servex_valkey`, built like the Postgres fixtures.

- One container per run (`redis:7-alpine`, `valkey/valkey:8-alpine`), `--save "" --appendonly no`.
- Each worker gets a database index (0 to 15). More than 16 workers must fail with a clear
  error, not share an index.
- `SERVEX_REDIS_URL` / `SERVEX_VALKEY_URL` skip the container, like `SERVEX_POSTGRES_URL`.
- Users of this today: tyko (`RedisContainer("redis:7")` in `packages/tyko-server/tests/conftest.py`).

Done when an inner pytest run under `--parallel=fork` shows two workers on two indexes.
