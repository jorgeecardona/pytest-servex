---
title: Measure start time against testcontainers on an idle machine
status: open
area: postgres
owner: null
filed: 2026-11-16
fixed_in: null
scope: S
verify: probe
---

The first measurement (2026-11-16) ran at load average 31: a bare `docker run` of
`postgres:17-alpine` took 12.4 s to accept connections, and `_docker.start` took 16.5 s,
including 1.4 s of imports. Repeat on an idle machine, against `testcontainers` with the same
image, and put the numbers in the README.
