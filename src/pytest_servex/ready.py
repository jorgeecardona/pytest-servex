"""Ready checks for ``Container(ready=...)``: wait for a log line, or for an HTTP answer.

Each function returns a check; pass it as ``ready``. A check returns False for "not yet" and
never raises, so the start loop keeps polling until it passes or the timeout ends.
"""

from __future__ import annotations

import http.client
import re
from collections.abc import Callable

from pytest_servex.errors import ServexError
from pytest_servex.lifecycle import logs
from pytest_servex.spec import RunningContainer

type Ready = Callable[[RunningContainer], bool]

HTTP_SERVER_ERROR = 500


def log_ready(pattern: str, *, times: int = 1) -> Ready:
    """Return a check that passes once ``pattern`` (a regex) matched ``times`` log lines.

    ``times`` covers images that print the same line twice, such as Postgres, which logs
    "ready to accept connections" once for its init server and once for the real one.
    Prefer a protocol check where one exists: a log line can appear before the port is
    served. (#2)
    """
    regex = re.compile(pattern)

    def check(started: RunningContainer) -> bool:
        try:
            text = logs(started)
        except ServexError:
            return False
        return sum(1 for line in text.splitlines() if regex.search(line)) >= times

    return check


def http_ready(port: int, path: str = "/") -> Ready:
    """Return a check that passes once ``GET path`` on container ``port`` gets any answer below 500.

    A 401 or 404 still means the server is up, which is what readiness asks.
    """

    def check(started: RunningContainer) -> bool:
        endpoint = started.endpoint(port)
        conn = http.client.HTTPConnection(endpoint.host, endpoint.port, timeout=1)
        try:
            conn.request("GET", path)
            return conn.getresponse().status < HTTP_SERVER_ERROR
        except (OSError, http.client.HTTPException):
            return False
        finally:
            conn.close()

    return check
