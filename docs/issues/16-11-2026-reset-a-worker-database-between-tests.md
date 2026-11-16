---
title: Reset a worker database between tests
status: done
area: postgres
owner: null
filed: 2026-11-16
fixed_in: null
scope: M
verify: test
---

`servex_postgres` is per worker, so rows from one test are visible to the next test on the same
worker. Each project now writes its own reset (paas: selective TRUNCATE; accounting:
`create_all`/`drop_all` per test).

Options to compare with timings:

1. Re-clone from the template before each test (`DROP` + `CREATE ... TEMPLATE`).
2. TRUNCATE only the tables the test wrote to (paas measured about 100 ms per test for a full
   TRUNCATE of 66 tables, on 2026-09-20).
3. A transaction per test, rolled back at the end (fast, but breaks tests that commit).

Ship the fastest one that is correct as an opt-in function-scoped fixture.

## Resolved (2026-11-16)

Measured on `postgres:17-alpine`, 66 tables with an index each, load average 47 to 60:
re-clone (`DROP ... WITH (FORCE)` + `CREATE DATABASE ... TEMPLATE`) 173 to 177 ms, one
`TRUNCATE` of all 66 tables 369 ms. Re-clone also restores seed rows. Shipped as the opt-in
fixture `servex_postgres_clean`. Option 3 (rollback per test) was not built: it breaks tests
that commit.
