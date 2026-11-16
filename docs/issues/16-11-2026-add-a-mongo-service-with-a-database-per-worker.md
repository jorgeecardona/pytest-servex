---
title: Add a Mongo service with a database per worker
status: open
area: mongo
owner: null
filed: 2026-11-16
fixed_in: null
scope: M
verify: test
---

Add `servex_mongo`: one `mongo:8` container per run, one database per worker (`servex_f0`),
dropped at worker end. The ready check runs `ping` with `pymongo`, as an optional extra
(`pytest-servex[mongo]`) so Postgres-only users do not install it.

Done when an inner pytest run under `--parallel=fork` shows two workers on two databases.
