"""Valkey (and Redis): the service definition and a database index per worker.

One server per run. Each worker gets its own database number (``SELECT n``), flushed when
the worker starts and when it ends. The container is started with 128 databases, so up to
128 workers fit. No client library is needed here: the ready check and the flush speak the
Redis protocol over a plain socket.
"""

from __future__ import annotations

import re
import socket
from dataclasses import dataclass, replace
from typing import BinaryIO
from urllib.parse import unquote, urlsplit, urlunsplit

from pytest_servex.errors import ServexError
from pytest_servex.spec import Container, Endpoint, RunningContainer

PORT = 6379
DATABASES = 128


def encode(*args: str) -> bytes:
    """Return ``args`` as one Redis protocol (RESP) command."""
    parts = [f"*{len(args)}\r\n".encode()]
    for arg in args:
        data = arg.encode()
        parts.append(b"$%d\r\n%s\r\n" % (len(data), data))
    return b"".join(parts)


def _read_reply(reader: BinaryIO) -> str:
    """Read one simple reply line (``+OK``, ``-ERR``, ``:1``) and return it without CRLF."""
    line = reader.readline()
    if not line:
        raise ServexError("Valkey closed the connection")
    return line.decode(errors="replace").rstrip("\r\n")


def command(url: str, *commands: tuple[str, ...], timeout: float = 2.0) -> list[str]:
    """Send ``commands`` to the server at ``url`` on one connection; return each reply line.

    ``AUTH`` (when the URL has a password) and ``SELECT`` (when it has a database number)
    are sent first. Only simple replies are read, which is all the ready check and the
    flush need.

    Raises:
        ServexError: The server answered a command with an error (``-ERR ...``).
        OSError: The server cannot be reached.
    """
    parts = urlsplit(url)
    prelude: list[tuple[str, ...]] = []
    if parts.password:
        user = unquote(parts.username or "")
        password = unquote(parts.password)
        prelude.append(("AUTH", user, password) if user else ("AUTH", password))
    database = parts.path.lstrip("/")
    if database:
        prelude.append(("SELECT", database))
    every = [*prelude, *commands]
    with socket.create_connection(
        (parts.hostname or "127.0.0.1", parts.port or PORT), timeout
    ) as sock:
        sock.sendall(b"".join(encode(*c) for c in every))
        reader = sock.makefile("rb")
        replies = [_read_reply(reader) for _ in every]
    for sent, reply in zip(every, replies, strict=True):
        if reply.startswith("-"):
            name = sent[0] if sent[0] != "AUTH" else "AUTH (password hidden)"
            raise ServexError(f"Valkey refused {name}: {reply[1:]}")
    return replies[len(prelude) :]


def url_for(endpoint: Endpoint, database: int | None = None) -> str:
    """Return the ``redis://`` URL of a server, with a database number when given."""
    path = "" if database is None else f"/{database}"
    return f"redis://{endpoint.host}:{endpoint.port}{path}"


def _ready(started: RunningContainer) -> bool:
    """True once the server answers ``PING`` with ``PONG``."""
    try:
        return command(url_for(started.endpoint(PORT)), ("PING",), timeout=1) == ["+PONG"]
    except (OSError, ServexError):
        return False


_NO_DISK = ("--save", "", "--appendonly", "no", "--databases", str(DATABASES))

VALKEY = Container(
    image="valkey/valkey:8-alpine",
    ports=(PORT,),
    command=("valkey-server", *_NO_DISK),
    ready=_ready,
)
"""Valkey with persistence off and 128 databases."""

REDIS = replace(VALKEY, image="redis:7-alpine", command=("redis-server", *_NO_DISK))
"""Redis with the same settings. Use it where production runs Redis, not Valkey."""


@dataclass(frozen=True)
class ValkeyServer:
    """The run's Valkey or Redis server, as a ``redis://`` URL without a database number."""

    url: str


@dataclass(frozen=True)
class ValkeyDatabase:
    """One worker's database on the run's server."""

    index: int
    url: str


def worker_index(worker_id: str) -> int:
    """Return the database number for a worker: the digits at the end of its id, else 0.

    ``main`` (serial) is 0, ``f0``/``gw0`` are 0, ``f3``/``gw3`` are 3. Serial and parallel
    workers never run in the same session, so ``main`` and ``f0`` cannot collide.
    """
    match = re.search(r"(\d+)$", worker_id)
    return int(match.group(1)) if match else 0


def with_database(url: str, index: int) -> str:
    """Return ``url`` pointing at database ``index``, keeping host, port, and credentials."""
    parts = urlsplit(url)
    return urlunsplit(parts._replace(path=f"/{index}"))


def claim(server: ValkeyServer, index: int) -> ValkeyDatabase:
    """Flush database ``index`` and return it.

    Raises:
        ServexError: The server has fewer databases than ``index + 1`` (an external server
            has 16 by default; the servex container has 128).
    """
    database = ValkeyDatabase(index=index, url=with_database(server.url, index))
    command(database.url, ("FLUSHDB",))
    return database
