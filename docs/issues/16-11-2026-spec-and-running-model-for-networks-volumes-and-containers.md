---
title: Spec and running model for networks, volumes and containers
status: done
area: core
owner: null
filed: 2026-11-16
fixed_in: null
scope: M
verify: test
---

Jorge, 2026-11-16: the Zen of Python is the guide, frozen dataclasses as much as possible, and
a natural flow to start networks, containers and volumes. It must work outside pytest too.

Replace `Service` with specs and results, all frozen:

```python
net = Network("servex")
pg = Container(
    image="postgres:17-alpine",
    ports=(5432,),
    mounts=(Tmpfs("/var/lib/postgresql/data"),),
    networks=(net,),
    ready=pg_ready,
)

with running(net), running(pg) as started:
    started.endpoint(5432)
```

- Specs: `Network`, `Volume`, `Tmpfs`, `Container`. Hashable; `env` stored as sorted pairs.
- Results: `RunningNetwork`, `RunningContainer`: ids and endpoints only, no Docker client.
- Verbs: `start`, `stop`, `running` (a context manager over the two).
- `POSTGRES` becomes a `Container`; `replace(POSTGRES, image="postgres:18")` works.
- The pytest fixtures use `running` for their setup and teardown.

Do this before the first PyPI release, so 0.1.0 ships this API.
