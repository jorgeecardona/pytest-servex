---
title: Benchmark time, memory and disk against testcontainers
status: open
area: postgres
owner: null
filed: 2026-11-16
fixed_in: null
scope: S
verify: probe
---

Goal (Jorge, 2026-11-16): pytest-servex must be faster than testcontainers and leave a smaller
memory and disk footprint. Measure both on the same suite and image, on an idle machine, and put
the table in the README.

Measure, for a serial run and for `--parallel=fork --parallel-workers=4`:

1. Wall time from pytest start to the first test, and for the whole run.
2. Peak container memory (`docker stats`), including Ryuk for testcontainers.
3. Disk written: Docker volumes and layers left after the run (`docker system df -v`).
4. Python import time of the plugin (`python -X importtime`).

Known trade-off to report, not hide: servex puts Postgres data on tmpfs, so it writes no disk but
the data counts as container memory.

First numbers (2026-11-16, load average 31, not comparable): bare `docker run` of
`postgres:17-alpine` ready in 12.4 s; `_docker.start` in 16.5 s, with 1.4 s of imports. At a
lower load the full suite (two inner runs, each starting a container) took 8.8 s.
