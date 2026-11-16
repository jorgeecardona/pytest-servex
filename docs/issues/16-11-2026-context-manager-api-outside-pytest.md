---
title: Context manager API outside pytest
status: open
area: core
owner: null
filed: 2026-11-16
fixed_in: null
scope: S
verify: test
---

Jorge wants the library to feel more Pythonic than testcontainers (2026-11-16), and usable in
scripts and notebooks, not only in pytest.

Add a public context manager over `_docker.start` / `stop`:

```python
from pytest_servex import POSTGRES, running

with running(POSTGRES) as endpoint:
    ...
```

Rules: plain functions and frozen dataclasses, no builder chains (`.with_env().with_port()`),
no classes per service. The pytest fixtures then use the same context manager.
