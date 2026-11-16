---
title: Keep a spare clone so a reset is a rename
status: open
area: postgres
owner: null
filed: 2026-11-16
fixed_in: null
scope: M
verify: test
---

`servex_postgres_clean` re-clones the template before each test (about 175 ms). Clone a spare
database in a background thread while the test runs; the reset then drops the used database and
renames the spare (`ALTER DATABASE ... RENAME`), which takes milliseconds. Measure first: the
background clone competes with the test for I/O.
